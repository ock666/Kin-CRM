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
    "date": "November 2026",
    "body": """
Hi, it's Skye. A small, cosy one this time — something for the moments when your thoughts are looping and you just need your eyes and hands busy for a minute, plus a quiet step up for anyone sharing Kin.

### 🟡 Dot Muncher
There's a new game in the Regulation toolkit, under 🧱 Soothe: Dot Muncher — a warm, Pac-Man-style maze chase. Gobble the dots and dodge the four ghosts (Blinky chases, Pinky ambushes, Inky flanks, Clyde's a bit shy), then grab a power pellet to turn the tables and chase them right back. It's a proper little arcade game — score, three lives, levels that gently pick up the pace, a cherry bonus, and a wrap-around tunnel. Play with the keyboard or the on-screen buttons, and pause whenever you need a breath.

The four quieter games are still there too — Soft Fall, 2048, Memory, and Minesweeper — no clocks, no pressure, as always.

### 👥 Multiple people, one Kin
Kin now supports multiple users on a single install, each with their own fully private world — their own people, journal, tags, reminders, and progress, kept completely separate from everyone else's. It's the perfect fit if you'd like to host Kin for a friend or partner without each of you running your own instance. To add someone: Settings → Users → add their name and email, and they'll log into a fresh, empty Kin of their own.

### 🏠 Households
Two people can now opt to share one Kin. A single-use invite link (from the new Household page) lets a partner or friend join your household — merging their people and journal into yours — or create a brand-new account straight into it. Households come with roles: household owners manage members and config, instance owners administer the whole install, and a per-user "hide config" toggle lets you manage things for someone less technical. A household of one is just your own private Kin, so nothing changes if you'd rather keep it that way.

That's everything for now. Be gentle with yourself — Skye 💛
""".strip(),
}
