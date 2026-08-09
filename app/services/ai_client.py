"""AI integration - uses any OpenAI-compatible chat completions endpoint.

Works with real OpenAI, Azure OpenAI (compatible mode), or a local/self-hosted
server such as Ollama (`ollama serve` exposes an OpenAI-compatible API at
http://localhost:11434/v1). All features degrade gracefully: if AI isn't
configured or a call fails, callers get None/[] back and the UI hides the
feature or shows a friendly note instead of crashing.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from openai import OpenAI, APIError, APIConnectionError
from pydantic import BaseModel


class AIError(Exception):
    pass


class ConflictResolutionAnalysis(BaseModel):
    """Structured output for the implicit-conflict-repair analyzer (see
    AIClient.analyze_conflict_resolution below). AuDHD-safety rule baked into the prompt itself:
    when in doubt, the model is instructed to return is_resolved=False - the confidence gate in
    the calling route further requires confidence_score >= 0.75 before a suggestion is even
    surfaced to the user, and even then it's just a dismissible suggestion, never an auto-action."""
    is_resolved: bool
    confidence_score: float  # 0.0 to 1.0
    resolution_type: str  # "explicit_repair" | "implicit_warmth" | "implicit_normalcy" | "ongoing_friction" | "uncertain"
    reasoning: str
    suggested_ui_prompt: Optional[str] = None


class AIClient:
    def __init__(self, base_url: str, api_key: str, model: str):
        if not api_key or not base_url or not model:
            raise AIError("AI is not configured yet. Add an API key, base URL and model in Settings.")
        self.model = model
        self.client = OpenAI(base_url=base_url, api_key=api_key)

    def _chat(self, system: str, user: str, max_tokens: int = 700, temperature: float = 0.7) -> str:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return (resp.choices[0].message.content or "").strip()
        except (APIError, APIConnectionError) as e:
            raise AIError(f"AI request failed: {e}")
        except Exception as e:
            raise AIError(f"AI request failed: {e}")

    def test_connection(self) -> str:
        return self._chat("You are a connection test.", "Reply with the single word: ok", max_tokens=5)

    def extract_facts(self, person_name: str, journal_text: str) -> dict:
        """Given a journal entry, ask the model to suggest structured profile updates.
        Returns a dict the caller can present to the user for approval - never
        auto-applied (human in the loop)."""
        system = (
            "You are an assistant helping someone maintain a personal relationship-tracking "
            "journal (a personal CRM for friends/family). Extract useful structured facts from "
            "a journal entry about a specific person. Only include things actually stated or "
            "strongly implied in the text - never invent details. Respond ONLY with compact JSON "
            "matching this schema: {\"tags\": [string], \"notable_dates\": "
            "[{\"label\": string, \"month\": int, \"day\": int, \"year\": int|null}], "
            "\"follow_ups\": [string], \"summary_update\": string}. "
            "If nothing applies for a field, use an empty list or empty string."
        )
        user = f"Person: {person_name}\n\nJournal entry:\n{journal_text}"
        raw = self._chat(system, user, max_tokens=500, temperature=0.2)
        return _safe_json(raw)

    def draft_birthday_message(self, person_name: str, relationship_label: str,
                                context: str, tone: str = "warm and casual") -> str:
        system = (
            "You write short, genuine, human-sounding birthday messages. Avoid generic greeting-card "
            "cliches. Keep it brief (2-4 sentences), personal, and specific to details given. "
            f"Tone: {tone}."
        )
        user = (
            f"Write a birthday message for {person_name} ({relationship_label or 'friend'}).\n"
            f"What we know about them:\n{context or 'No extra notes available.'}"
        )
        return self._chat(system, user, max_tokens=200, temperature=0.8)

    def suggest_gift(self, person_name: str, context: str, previous_gifts: list[str]) -> str:
        """Suggest a single specific gift idea under $40, avoiding anything already given or
        suggested before. Always human-in-the-loop - lands in the review queue, never auto-bought
        or sent anywhere."""
        system = (
            "You suggest ONE specific, thoughtful gift idea for someone based on what's known "
            "about them. Hard constraint: it must plausibly cost under $40 USD - say so isn't "
            "required, but never suggest anything clearly pricier. Never repeat anything already "
            "given or suggested before (listed below). Respond with 1-2 sentences: the specific "
            "gift idea plus a short reason it fits them. No preamble, no markdown, no price talk "
            "unless it's part of the natural sentence."
        )
        prev = "\n".join(f"- {g}" for g in previous_gifts) if previous_gifts else "(none yet)"
        user = (
            f"Person: {person_name}\n\nWhat we know about them:\n{context or 'Not much known yet.'}\n\n"
            f"Previously suggested/given gifts (do not repeat these or close variants):\n{prev}"
        )
        return self._chat(system, user, max_tokens=150, temperature=0.85)

    def analyze_conflict_resolution(self, person_name: str, conflict_summary: str,
                                     new_entry_text: str) -> ConflictResolutionAnalysis:
        """Compare a past unresolved conflict against a newly logged interaction to gently detect
        whether it's been explicitly or implicitly repaired. AuDHD-safety: the prompt instructs
        the model to never assume repair from surface-level politeness, and to default to
        is_resolved=False when uncertain - this is a suggestion engine, not a verdict engine."""
        system = (
            "You are an empathetic interpersonal dynamics analyzer for an AuDHD-centered CRM. "
            "Compare a past unresolved conflict against a newly logged interaction to evaluate if "
            "the conflict has been implicitly or explicitly resolved.\n\n"
            "RULES:\n"
            "1. EXPLICIT RESOLUTION: New entry mentions apologizing, talking it through, or "
            "clearing the air.\n"
            "2. IMPLICIT RESOLUTION: New entry shows genuine warmth, relaxed hangout vibes, "
            "laughing, or comfortable contact without referencing the conflict.\n"
            "3. ONGOING FRICTION / UNCERTAIN: New entry shows coldness, obligation/masking, or "
            "lacks enough emotional context.\n"
            "4. AuDHD SAFETY: Never assume repair from surface-level politeness. When in doubt, "
            "return is_resolved=false.\n\n"
            "Respond strictly with valid JSON matching this schema:\n"
            '{"is_resolved": boolean, "confidence_score": float, "resolution_type": string, '
            '"reasoning": string, "suggested_ui_prompt": "Gentle, non-demanding 1-sentence prompt '
            'for a UI banner asking if they want to close the conflict (or null if false)."}'
        )
        user = (
            f"Person: {person_name}\n\n"
            f"Unresolved conflict, logged earlier:\n{conflict_summary}\n\n"
            f"Newly logged interaction with this person:\n{new_entry_text}"
        )
        raw = self._chat(system, user, max_tokens=300, temperature=0.3)
        data = _safe_json(raw)
        try:
            return ConflictResolutionAnalysis(**data)
        except Exception as e:
            raise AIError(f"AI returned an unexpected shape for conflict analysis: {e}")

    def profile_summary(self, person_name: str, journal_snippets: list[str], context: str = "") -> str:
        system = (
            "You summarize a person's relationship history into a short, warm 3-5 sentence "
            "summary for a personal relationship-tracking app. Focus on who they are, shared "
            "history, and anything important to remember. Be concrete, not generic."
        )
        joined = "\n---\n".join(journal_snippets[-40:])
        context_block = f"Known context:\n{context}\n\n" if context else ""
        user = f"Person: {person_name}\n{context_block}Journal entries (most recent last):\n{joined}"
        return self._chat(system, user, max_tokens=350, temperature=0.5)

    def conversation_starters(self, person_name: str, journal_snippets: list[str], context: str = "") -> list[str]:
        system = (
            "Suggest 3-5 short, specific conversation starters or follow-up questions to ask "
            "next time the user talks to this person, based on their journal history. "
            "Respond ONLY as a JSON array of strings."
        )
        joined = "\n---\n".join(journal_snippets[-20:])
        context_block = f"Known context:\n{context}\n\n" if context else ""
        user = f"Person: {person_name}\n{context_block}Recent journal entries:\n{joined or 'No entries yet.'}"
        raw = self._chat(system, user, max_tokens=300, temperature=0.7)
        data = _safe_json(raw)
        if isinstance(data, list):
            return [str(x) for x in data]
        return []


def build_person_context(person) -> str:
    """Assemble a compact free-text context blurb about a person for AI prompts, combining
    whatever profile fields exist (occupation, hobbies, notable people, notes, prior AI summary,
    and friend-rank "gaps" - what's missing from their profile, so AI features can proactively
    suggest what to ask about/fill in next, which is the whole point for someone who finds it
    hard to know what to ask people about).
    Duck-typed - works with any object exposing these attributes, no model import needed."""
    parts = []
    if getattr(person, "occupation", None):
        parts.append(f"Occupation: {person.occupation}")
    if getattr(person, "hobbies", None):
        parts.append(f"Hobbies/interests: {person.hobbies}")
    refs = getattr(person, "notable_people_refs", None)
    if refs:
        joined = ", ".join(f"{r.name} ({r.relation})" if r.relation else r.name for r in refs)
        parts.append(f"People in their life: {joined}")
    if getattr(person, "notes", None):
        parts.append(f"Notes: {person.notes}")
    if getattr(person, "ai_summary", None):
        parts.append(f"Summary so far: {person.ai_summary}")

    try:
        from .friend_rank import compute_friend_rank
        gaps = compute_friend_rank(person).get("gaps")
        if gaps:
            parts.append(f"Not yet known about them (consider asking, if relevant): {', '.join(gaps)}")
    except Exception:
        pass  # friend-rank context is a nice-to-have, never let it break AI features

    return "\n".join(parts)


def _safe_json(raw: str):
    """Models sometimes wrap JSON in markdown fences or add commentary - try hard to parse."""
    raw = raw.strip()
    raw = re.sub(r"^```(json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\}|\[.*\])", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
    return {}


def get_client_from_settings(db) -> Optional["AIClient"]:
    from ..settings_store import get_setting
    base_url = get_setting(db, "ai_base_url")
    api_key = get_setting(db, "ai_api_key")
    model = get_setting(db, "ai_model")
    if not api_key:
        return None
    return AIClient(base_url, api_key, model)
