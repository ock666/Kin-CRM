"""AI integration - uses any OpenAI-compatible chat completions endpoint.

Works with real OpenAI, Azure OpenAI (compatible mode), or a local/self-hosted
server such as Ollama (`ollama serve` exposes an OpenAI-compatible API at
http://localhost:11434/v1). All features degrade gracefully: if AI isn't
configured or a call fails, callers get None/[] back and the UI hides the
feature or shows a friendly note instead of crashing.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional, Generator

from openai import OpenAI, APIError, APIConnectionError
from pydantic import BaseModel

logger = logging.getLogger(__name__)


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


class ResolutionPlan(BaseModel):
    """Structured resolution plan generated from a conflict support chat transcript."""
    summary: str  # brief recap of the conflict from the chat
    feelings: str  # validating acknowledgment of their emotional state
    goal: str  # what they'd like to achieve or resolve
    steps: list[str]  # ordered concrete actions to attempt when ready
    approach_messages: list[str]  # copy-paste message options
    boundary_script: str  # gentle boundary-setting option
    release_option: str  # reminder that letting go is a valid path


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
            logger.error("AI request failed: %s", e)
            raise AIError("AI service is currently unavailable. Please try again later.")
        except Exception as e:
            logger.error("AI request failed (unexpected): %s", e)
            raise AIError("AI service is currently unavailable. Please try again later.")

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

    def bio_blurb(self, person_name: str, context: str = "") -> str:
        """A single warm, human one-liner about who this person is - the 'headline' you'd see on
        their profile. Short (1 sentence, under ~20 words), concrete, never generic. No markdown."""
        system = (
            "Write ONE short, warm sentence (under 20 words, no markdown, no quotes) that "
            "captures who this person is for someone keeping a personal relationship journal. "
            "Be concrete and specific from the context - tie in their relationship, interests, "
            "or how you know them. Never generic filler like 'a wonderful person'; make it "
            "recognizably ABOUT them."
        )
        context_block = f"Context:\n{context}" if context else "Context: (not much known yet - keep it general but warm)"
        user = f"Person: {person_name}\n{context_block}"
        return self._chat(system, user, max_tokens=60, temperature=0.7)

    def conversation_gap_questions(self, person_name: str, context: str = "", gaps: list[str] | None = None) -> list[str]:
        """Specific, low-effort, copy-paste questions to ask someone next time, shaped around the
        gaps in what's known about them (from friend rank). Returns a JSON list of strings. These
        help someone who finds it hard to know what to ask - the whole point is removing that load."""
        system = (
            "Help someone prepare 2-3 gentle, specific questions to ask a person they'll "
            "talk to. Focus on the gaps labelled below - things about them it would be nice to "
            "know - and phrase each as a natural, low-pressure question (not an interrogation). "
            "Keep each question to one sentence. Respond ONLY as a JSON array of strings."
        )
        gap_line = ", ".join(gaps) if gaps else "no specific gaps known - keep questions warm and general"
        context_block = f"Known context:\n{context}\n\n" if context else ""
        user = f"Person: {person_name}\nWhat we'd like to know more about: {gap_line}\n\n{context_block}"
        raw = self._chat(system, user, max_tokens=250, temperature=0.7)
        data = _safe_json(raw)
        if isinstance(data, list):
            return [str(x) for x in data]
        return []

    def conversation_starters(self, person_name: str, journal_snippets: list[str], context: str = "") -> list[str]:
        system = (
            "Suggest 3-5 short, specific conversation starters or follow-up questions to ask "
            "next time the user talks to this person, based on their journal history. "
            "The journal entries are the user's own writing about this person - mirror their voice "
            "(warmth, humour, how they refer to the person) so the starters sound like the user "
            "wrote them, never like a generic AI assistant or a coworker. Borrow tone and style "
            "only, never import negative or conflict-heavy wording. Match the relationship register "
            "given in the known context: closer relationships get a casual, warm voice; newer ones "
            "stay warm but lighter. "
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

    def icebreaker_scripts(self, person_name: str, context: str, journal_snippets: list[str],
                            days_since_contact: int = 0) -> list[str]:
        """Generate 3 short, copy-paste quick-reply scripts for reconnecting after being out of
        touch, referencing specifics from the person's profile and recent shared history."""
        system = (
            "You write short, warm, copy-paste quick-reply messages for someone reconnecting "
            "after being out of touch with a friend. The messages should reference specifics "
            "from the person's profile and recent journal history (shared events, hobbies, "
            "people in their life, how they met, recent news) so they feel personal, never "
            "generic. Each is 1-2 sentences, ready to send as-is, low-pressure, genuinely "
            "optional. The journal entries are the user's own writing about this person - mirror "
            "their voice (warmth, humour, how they refer to the person) so the messages sound like "
            "the user wrote them, never like a generic AI assistant or a coworker. Borrow tone and "
            "style only, never import negative or conflict-heavy wording. Match the relationship "
            "register given in the known context. Produce 3 short scripts with varied angles (a "
            "gentle check-in, a specific callback to shared history or recent news, a low-effort "
            "invitation or acknowledgment of the time gap). Respond ONLY as a JSON array of strings."
        )
        gap_note = f"It's been {days_since_contact} days since last contact." if days_since_contact else ""
        joined = "\n---\n".join(journal_snippets[-20:])
        context_block = f"Known context:\n{context}\n\n" if context else ""
        gap_block = f"\n{gap_note}\n" if gap_note else ""
        user = f"Person: {person_name}{gap_block}{context_block}Recent journal entries:\n{joined or 'No entries yet.'}"
        raw = self._chat(system, user, max_tokens=300, temperature=0.7)
        data = _safe_json(raw)
        if isinstance(data, list):
            return [str(x) for x in data]
        return []

    def support_chat(self, messages: list[dict]) -> Generator[str, None, None]:
        """Stream a support-chat response using a capable model (e.g. gpt-4o).
        Takes a full messages list including the system prompt."""
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                max_tokens=800,
                temperature=0.7,
            )
            for chunk in stream:
                delta = getattr(chunk.choices[0].delta, "content", None)
                if delta:
                    yield delta
        except (APIError, APIConnectionError) as e:
            logger.error("AI support-chat request failed: %s", e)
            raise AIError("AI service is currently unavailable. Please try again later.")
        except Exception as e:
            logger.error("AI support-chat request failed (unexpected): %s", e)
            raise AIError("AI service is currently unavailable. Please try again later.")

    def chat_insight(self, messages: list[dict]) -> str:
        """Extract a single key insight or takeaway from the support chat transcript,
        written as a concise 1-2 sentence journal entry the user can save to their timeline."""
        system = (
            "Extract a single key insight or takeaway from this support chat transcript. "
            "Write it as a concise, first-person journal entry (1-2 sentences) — warm, "
            "specific to the situation, concrete. Never generic filler. The insight should "
            "capture something the user learned about the situation, what they want, or how "
            "they plan to approach it. Respond with ONLY the insight text, no markdown, no quotes."
        )
        return self._chat(system, json.dumps(messages, default=str), max_tokens=150, temperature=0.5)

    def suggest_resolution_plan(self, conflict_summary: str, transcript: str,
                                 person_name: str, context: str = "") -> ResolutionPlan:
        """Generate a structured resolution plan from the conflict chat transcript, specific to
        the person and what was discussed."""
        system = (
            "You help someone with AuDHD, RSD, and social anxiety build a gentle, concrete plan "
            "for resolving an interpersonal conflict, based on what they discussed with a support "
            "counsellor.\n\n"
            "The user talked through their feelings during a support chat. Now, using that "
            "transcript plus what's known about the conflict, produce a structured resolution plan "
            "they can follow whenever they feel ready.\n\n"
            "Guidelines:\n"
            "- Be specific to this conflict and person, not generic.\n"
            "- Validate their feelings first, then help them move toward resolution.\n"
            "- Steps should be concrete and ordered (easiest/gentlest first).\n"
            "- Approach messages should be copy-paste ready (1-2 sentences each, 2-3 options).\n"
            "- Never pressure them to act; always include a boundary option and a release path.\n"
            "- 'Letting it go' (release) is always a valid and legitimate choice — frame it as such.\n\n"
            "Respond ONLY with valid JSON matching this schema:\n"
            '{"summary": string, "feelings": string, "goal": string, "steps": [string], '
            '"approach_messages": [string], "boundary_script": string, "release_option": string}'
        )
        ctx = f"\nRelationship context: {context}" if context else ""
        user = (
            f"Person: {person_name}\nConflict: {conflict_summary}{ctx}\n\n"
            f"Support chat transcript:\n{transcript}"
        )
        raw = self._chat(system, user, max_tokens=600, temperature=0.5)
        data = _safe_json(raw)
        try:
            return ResolutionPlan(**data)
        except Exception as e:
            raise AIError(f"AI returned an unexpected shape for resolution plan: {e}")


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

    register = familiarity_register(person)
    parts.append(f"Relationship register (match this warmth/familiarity): {register}")

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


_REGISTER_BY_TIER = {
    "Acquaintance": "warm but polite; lighter register; reference what's known (occupation, hobby, how you met); don't presume shared intimacy or inside jokes",
    "Getting to know them": "friendly and light; use their name; reference a specific known detail; keep it easy to answer",
    "Close Friend": "casual and warm; use contractions; reference shared memories or hobbies; assume warmth",
    "Inner Circle": "playful and intimate; natural shorthand; reference shared or inside references; warm and easy",
}


def familiarity_register(person) -> str:
    """Return a short 'register' instruction for AI prompts, derived from how much we know about
    the person (the friend-rank tier: journal count + contact recency + profile completeness).

    Intentionally invisible to the user - this only shapes how AI-suggested messages are written
    so they land at the right level of warmth/familiarity instead of a flat 'acquaintance/coworker'
    register. Duck-typed on `person` (works with stub objects in tests)."""
    try:
        from .friend_rank import compute_friend_rank
        tier = compute_friend_rank(person).get("tier", "")
        return _REGISTER_BY_TIER.get(tier, "warm, natural, and human")
    except Exception:
        return "warm, natural, and human"


def get_client_from_settings(db) -> Optional["AIClient"]:
    from ..settings_store import get_setting
    base_url = get_setting(db, "ai_base_url")
    api_key = get_setting(db, "ai_api_key")
    model = get_setting(db, "ai_model")
    if not api_key:
        return None
    return AIClient(base_url, api_key, model)


def get_support_client_from_settings(db) -> Optional["AIClient"]:
    from ..settings_store import get_setting
    base_url = get_setting(db, "ai_base_url")
    api_key = get_setting(db, "ai_api_key")
    model = get_setting(db, "support_chat_model", "gpt-4o")
    if not api_key:
        return None
    return AIClient(base_url, api_key, model)
