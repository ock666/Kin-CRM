"""Template-based quick-reply script fallback — deterministic, always works without AI.

Generates person-specific copy-paste reply scripts from structured profile data
(scratchpad items, hobbies, how-we-met, notable people, notable dates). Serves as
the graceful fallback when AI isn't configured or fails, so the micro-replies
dropdown always has something useful to show.
"""
from __future__ import annotations

import datetime as dt


GENERIC = [
    "Hey, sorry for the slow reply — how's your week been?",
    "Just been thinking of you! Hope you're doing well. No rush on replying.",
    "Hey! It's been a while — how are things going? Would love to catch up whenever you're free.",
]


def template_quick_replies(person, days_since_contact: int | None = None) -> list[str]:
    scripts: list[str] = []

    items = getattr(person, "scratchpad_items", []) or []
    if items:
        text = items[0].text.strip()
        topic = _strip_ask_prefix(text)
        scripts.append(f"Hey! Hope you're well — wanted to ask, how did {topic} go?")

    hobbies = getattr(person, "hobbies", None)
    if hobbies:
        first = [h.strip() for h in hobbies.split(",") if h.strip()]
        if first:
            scripts.append(f"How's {first[0]} been treating you?")

    how_we_met = getattr(person, "how_we_met", None)
    if how_we_met:
        scripts.append(f"Still think about when we met {how_we_met.lower()} — feels like ages ago in a good way!")

    refs = getattr(person, "notable_people_refs", []) or []
    if refs:
        r = refs[0]
        label = f"{r.name}"
        if getattr(r, "relation", None):
            label += f" ({r.relation})"
        scripts.append(f"Hope {label} is doing well!")

    notable_dates = getattr(person, "notable_dates", []) or []
    upcoming = []
    today = dt.date.today()
    for nd in notable_dates:
        if not nd.month or not nd.day:
            continue
        try:
            nd_date = dt.date(today.year, nd.month, nd.day)
        except ValueError:
            if nd.month == 2 and nd.day == 29:
                nd_date = dt.date(today.year, 3, 1)
            else:
                continue
        if nd_date < today:
            continue
        delta = (nd_date - today).days
        if delta <= 30:
            upcoming.append((nd.label, delta))
    if upcoming:
        upcoming.sort(key=lambda t: t[1])
        label, days = upcoming[0]
        if days == 0:
            scripts.append(f"Happy {label}! 🎉")
        else:
            scripts.append(f"Almost {label}! Hope you have something nice planned 🎉")

    if days_since_contact and days_since_contact > 30:
        scripts.append(f"It's been a while — just wanted to say hi and see how you're doing.")

    scripts = scripts[:3]

    gap = 3 - len(scripts)
    if gap > 0:
        scripts.extend(GENERIC[:gap])

    return scripts[:3]


def _strip_ask_prefix(text: str) -> str:
    """Strip leading 'ask how/ask about/ask if' prefixes for use in reply scripts."""
    import re
    return re.sub(r"^(ask\s+(how|about|if)\s+)", "", text, flags=re.IGNORECASE).lstrip()
