"""Tests for the invisible 'familiarity register' that shapes AI prompt tone.

The register is derived from friend rank (journal count + contact recency + profile
completeness) and is never shown to the user - it only influences how AI-suggested messages
are written so they land at the right level of warmth/familiarity.
"""

import datetime as dt

from app.services.ai_client import (
    AIClient,
    familiarity_register,
    build_person_context,
    _REGISTER_BY_TIER,
)


class _Person:
    """Minimal duck-typed stand-in for Person, matching the fields compute_friend_rank reads."""

    def __init__(self, **kw):
        self.journal_entries = kw.get("journal_entries", [])
        self.last_contact_date = kw.get("last_contact_date")
        self.birthday_month = kw.get("birthday_month")
        self.how_we_met = kw.get("how_we_met")
        self.occupation = kw.get("occupation")
        self.hobbies = kw.get("hobbies")
        self.email = kw.get("email")
        self.phone = kw.get("phone")
        self.instagram_username = kw.get("instagram_username")
        self.notable_dates = kw.get("notable_dates", [])
        self.notable_people_refs = kw.get("notable_people_refs", [])
        self.immich_person_id = kw.get("immich_person_id")
        self.notes = kw.get("notes")
        self.ai_summary = kw.get("ai_summary")


def test_familiarity_register_acquaintance():
    reg = familiarity_register(_Person())
    assert reg == _REGISTER_BY_TIER["Acquaintance"]


def test_familiarity_register_warmer_with_more_data():
    p = _Person(
        journal_entries=[object() for _ in range(8)],
        last_contact_date=dt.date.today(),
        birthday_month=6,
        how_we_met="school",
        occupation="nurse",
        hobbies="yoga",
        email="x@y.com",
        phone="123",
    )
    reg = familiarity_register(p)
    assert reg != _REGISTER_BY_TIER["Acquaintance"]
    assert reg in set(_REGISTER_BY_TIER.values())


def test_familiarity_register_never_errors_on_partial_stub():
    reg = familiarity_register(object())  # object has none of the expected fields
    assert reg == "warm, natural, and human"  # graceful fallback when rank can't be computed


def test_build_person_context_includes_register():
    ctx = build_person_context(_Person(occupation="teacher", hobbies="gardening"))
    assert "Relationship register" in ctx


def test_register_values_avoid_cheesy_language():
    for tier, reg in _REGISTER_BY_TIER.items():
        assert "playful" not in reg, tier
        assert "intimate" not in reg, tier
        assert "understated" in reg or "low-key" in reg or "plain" in reg, tier


def test_conversation_starters_prompt_is_understated():
    captured = {}

    ai = AIClient("http://example.com/v1", "sk-test", "gpt-4o-mini")

    def fake_chat(system, user, max_tokens=700, temperature=0.7):
        captured["system"] = system
        captured["user"] = user
        return '["a", "b"]'

    ai._chat = fake_chat
    items = ai.conversation_starters("Sam", ["tried the new bakery"], "Occupation: nurse")
    assert items == ["a", "b"]
    assert "understated" in captured["system"]
    assert "no greeting-card phrasing" in captured["system"]
    assert "partner in crime" in captured["system"]  # explicitly named as a cliché to avoid
