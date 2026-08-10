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


class ConflictApproachSuggestions(BaseModel):
    """Structured output for the conflict approach-suggestion generator (see
    AIClient.suggest_conflict_approach below). These are offered immediately, with no waiting
    period and no requirement to interact with the person first - the user acts whenever *they*
    feel ready. This is a suggestion/scaffolding engine, never a verdict or auto-action engine.

    Fields added for the neurodivergent flow: explicit cooling-off guidance (how to ride out the
    elevated RSD/anxiety window without forcing action) and follow-through scripts (what to do
    *after* the first message - a reply, a rough patch mid-talk, or a defer). Combined with the
    relational context passed to the prompt, these let the user lean on the scaffold at every
    stage instead of getting a single opener and being left stranded."""
    reflection: str
    cool_down: str  # validating framing + a specific way to wait out the elevated window
    approach_casual: str
    approach_direct: str
    boundary_script: str
    if_they_reply: str  # how to handle the response while staying regulated
    if_it_gets_hard: str  # staying grounding / pausing if the exchange becomes overwhelming
    defer_script: str  # a gentle "I need to step back for now" message for mid-conversation exits


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

    def suggest_conflict_approach(self, person_name: str, conflict_summary: str,
                                  relationship_context: str = "") -> ConflictApproachSuggestions:
        """Generate conflict-SPECIFIC approach & navigation support, immediately - no waiting
        period, no requirement to interact with the person first. Rejection Sensitive Dysphoria
        (RSD) often drives *avoidance* of the person involved, so gating help behind "wait and see
        if a future interaction goes well" is actively unhelpful - it requires the very contact the
        user may be anxious about before offering any support. Instead this gives structure,
        safety, and a jumping-off point the user can lean on across the whole arc of the conflict
        (cooling off -> first message -> handling the reply -> pausing if it gets overwhelming),
        usable whenever *they* feel ready, or ignorable entirely.

        `relationship_context` carries what we know about this specific relationship (closeness,
        shared history, prior conflicts, known facts) so the scripts feel tailored to THIS person
        rather than generic."""
        first_name = person_name.split()[0] if person_name else person_name
        system = (
            "You help someone with AuDHD/Rejection Sensitive Dysphoria (RSD) navigate a specific "
            "interpersonal conflict, whenever (if ever) they feel ready. They may also have social "
            "anxiety. Assume they may still feel emotionally elevated or anxious about this even if "
            "time has passed, and that they want to resolve things in good faith - never assume "
            "they're overreacting or that they have to act. Your job is gentle scaffolding and "
            "grounding, not judgment and not pressure. Never assign blame to either party unless the "
            "description clearly states who did what.\n\n"
            "Write suggestions SPECIFIC to the situation described and the relationship context "
            "given below - never generic greeting-card phrases like 'thinking of our chat the other "
            "day'. Reference the actual topic/situation and, where it helps, the real closeness "
            "between the two people, in your own words where natural.\n\n"
            "Assume the user experiences RSD: a perceived or real social rejection can feel "
            "catastrophic, spike anxiety, and drive avoidance of the person involved. Address this "
            "compassionately and concretely. Never shame them for struggling to act, for needing to "
            "wait, or for choosing to let it go.\n\n"
            "Write exactly these things:\n"
            "1. reflection: one short, warm, validating sentence about the specific situation - no "
            "advice, just acknowledgement.\n"
            "2. cool_down: 2-3 sentences of calming, concrete support for the cooling-off window. "
            "Normalize needing space when the feelings are still elevated, and give one SPECIFIC, "
            "grounding way to ride it out without acting out of anxiety (e.g. setting the thought "
            "aside for a specific amount of time, physically grounding, or writing the anxious story "
            "down to look at it later). Reassure them it is not urgent and there is no deadline. "
            "Never frame waiting as avoidance or failure.\n"
            "3. approach_casual: a relaxed-tone message they could send to check in / clear the "
            "air, specific to this situation and relationship, ready to copy-paste as-is (1-3 "
            "sentences).\n"
            "4. approach_direct: a warmer-but-clearer message that names wanting to talk it "
            "through, specific to this situation, ready to copy-paste (1-3 sentences).\n"
            "5. boundary_script: a gentle boundary-setting message for if they don't have the "
            "bandwidth right now, but want to leave the door open - specific to this relationship/"
            "situation where possible, ready to copy-paste (1-2 sentences).\n"
            "6. if_they_reply: short guidance (2-3 sentences) on staying regulated while reading "
            f"and responding to {first_name}'s reply: remind them to slow down, read it more "
            "than once before responding, that a neutral/curt reply is not proof of rejection, and "
            "that they don't have to reply immediately. Include ONE specific short copy-paste "
            "fallback line they can use if they feel the urge to just disappear.\n"
            "7. if_it_gets_hard: short grounding guidance (2-3 sentences) for if the actual "
            "conversation becomes overwhelming mid-way: permission to slow down or pause, one "
            "grounding reminder, and a nod that stepping back now is a legitimate, self-respecting "
            "choice - not a failure. Do not write the word 'defer_script' - just naturally describe "
            "that they may send the stepping-back message included in this response.\n"
            "8. defer_script: a gentle, self-respecting message to send if they need to step back "
            "from the conversation now, without pretending nothing happened or burning the "
            "relationship - leaves the door open to revisit later, ready to copy-paste (1-2 "
            "sentences).\n\n"
            "Relationship context (use this to tailor tone and length - closer/safer relationships "
            "can carry a warmer directness; newer/more fragile ones need more care):\n"
            "{relationship_context or '(no specific context available - keep it general but warm)'}\n\n"
            "Respond ONLY with valid JSON matching this schema:\n"
            '{"reflection": string, "cool_down": string, "approach_casual": string, '
            '"approach_direct": string, "boundary_script": string, "if_they_reply": string, '
            '"if_it_gets_hard": string, "defer_script": string}'
        )
        user = f"Person: {person_name}\n\nWhat happened, in the user's own words:\n{conflict_summary}"
        raw = self._chat(system, user, max_tokens=700, temperature=0.7)
        data = _safe_json(raw)
        try:
            return ConflictApproachSuggestions(**data)
        except Exception as e:
            raise AIError(f"AI returned an unexpected shape for conflict suggestions: {e}")

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
