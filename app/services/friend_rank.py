"""Friend Rank - a live-computed relationship depth/completeness score.

Unlike gamification.py (which needs persistent accumulating state), this is purely DERIVED from
data that already exists on a Person - no new tables, no migration, no risk of the score getting
out of sync with reality. Recomputed fresh every time it's displayed.

Two purposes:
  1. A gentle, gamified nudge toward filling in profiles (shown as a score/tier badge).
  2. Richer AI context: the "gaps" list feeds into `ai_client.build_person_context()` so AI
     features can proactively suggest what to ask about/fill in - directly useful for someone
     who finds it hard to know what to ask people about.
"""
from __future__ import annotations

import datetime as dt

TIERS = [
    (0, "Acquaintance", "🌱"),
    (20, "Getting to know them", "🙂"),
    (45, "Close Friend", "💛"),
    (70, "Inner Circle", "💎"),
]


def compute_friend_rank(person) -> dict:
    """Returns {"score": 0-100, "tier": str, "emoji": str, "gaps": [str, ...]}.
    `gaps` is a short, human-readable list of what's missing/stale, capped to keep it useful in
    a UI hint or an AI prompt rather than an overwhelming wall of text."""
    score = 0
    gaps: list[str] = []

    # --- Activity: journal entries logged with this person (up to 40 points) ---
    entry_count = len(person.journal_entries)
    score += min(entry_count * 4, 40)
    if entry_count == 0:
        gaps.append("no journal entries logged yet")

    # --- Recency: has something been logged lately? (up to 15 points) ---
    if person.last_contact_date:
        days_since = (dt.date.today() - person.last_contact_date).days
        if days_since <= 30:
            score += 15
        elif days_since <= 90:
            score += 7
        else:
            gaps.append(f"hasn't been logged in {days_since} days")
    else:
        gaps.append("no logged contact date yet")

    # --- Profile completeness (up to 45 points spread across these fields) ---
    checks = [
        (bool(person.birthday_month), "their birthday"),
        (bool(person.how_we_met), "how you met"),
        (bool(person.occupation), "their occupation"),
        (bool(person.hobbies), "their hobbies/interests"),
        (bool(person.email or person.phone or person.instagram_username), "contact info"),
        (bool(person.notable_dates), "a notable date (anniversary, etc.)"),
        (bool(person.notable_people_refs), "notable people in their life"),
        (bool(person.immich_person_id), "a linked photo"),
    ]
    filled = sum(1 for ok, _ in checks if ok)
    score += round((filled / len(checks)) * 45)
    for ok, label in checks:
        if not ok:
            gaps.append(label)

    score = max(0, min(100, score))

    tier_label, tier_emoji = TIERS[0][1], TIERS[0][2]
    for threshold, label, emoji in TIERS:
        if score >= threshold:
            tier_label, tier_emoji = label, emoji

    return {"score": score, "tier": tier_label, "emoji": tier_emoji, "gaps": gaps[:4]}
