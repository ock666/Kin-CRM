"""What's New content for Kin.

The "What's New" dialog shows once per release (tracked client-side in localStorage against
`config.settings.APP_VERSION`), and the same content is mirrored compactly at the bottom of the
Settings page so it can be re-read anytime. We intentionally keep only the CURRENT release here —
no rolling version history.
"""
from __future__ import annotations

from ..config import settings

WHATS_NEW = {
    "version": settings.APP_VERSION,
    "title": "What's new in Kin",
    "date": "September 2026",
    "body": """
Hi, it's Skye. Thanks for trusting Kin with your relationships — this one's a big one, all built to make keeping in touch feel lighter, not heavier.

### 🎉 Kin Wrapped
Around mid-December Kin quietly puts together a warm, private year-in-review — the people you were closest to, your standout moments, and the small ways you showed up. No hype, no scoreboard, just a gentle look back. It arrives on its own, and you can share the whole card — or just your year with one person — for a few weeks.

### 📅 Calendar sync
Birthdays and notable dates now live in any calendar you use — Google, Apple, Outlook, or anything that can subscribe to a link.
How it works: Kin serves a private calendar just for you. Birthdays and recurring notable dates appear as yearly all-day events (no timezone fuss), each with a gentle reminder — two weeks ahead for birthdays, so there's room to sort a card or gift.
To set it up: Settings → Calendar sync → turn it on → copy the subscribe link → add it to your calendar app by URL. It stays in sync on its own, and only ever shows the dates you've chosen to sync.

### 🎂 Two weeks to plan
Birthday reminders (drafts, nudges, and calendar alerts) now start two weeks out instead of three days, so there's more grace to sort a card or gift without the scramble.

### 🧹 Instagram, gone
The unofficial Instagram reader never quite worked and kept making "check now" hang, so it's been removed. Nothing else changes — your people, journal, and reviews all stay exactly as they are.

That's everything for now. Thank you for being here — don't let the bastards get you down~ — Skye
""".strip(),
}
