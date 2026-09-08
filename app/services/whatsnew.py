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
Hi, it's Skye. This update is all about letting Kin meet your people halfway — everything still waits for your OK before it touches a profile.

### 📥 Import from Instagram
You can now upload a copy of your own Instagram data (Accounts Center → Download your information → **JSON**) and Kin will gently learn who you talk to:
- You'll see the conversations Kin found and **say who each person is** — link them to someone already in Kin, or create them.
- Once matched, tap **✨ Suggest profile details** and Kin reads a short, recent slice of your conversation to propose details worth remembering — their job, hobbies, where they live, people in their life, notable dates, and small things to bring up next time.
- Suggestions only cover what the profile is **missing** — it won't re-suggest a birthday you've already saved, or list someone twice just because they're called "mum" one day and "mother" the next. If something looks *different* from what's saved (like a new job), it's flagged so you can decide.
- Anything sensitive is kept vague on purpose: Kin may note that someone's dealing with health stuff, but never the details.
- Every suggestion goes to the **Review queue** and is saved **only when you tap Accept** — one at a time, or accept them all.

### 🧠 The Review queue now holds these too
Chat suggestions appear right alongside birthday drafts in the Review queue, and the sidebar badge counts them — so nothing waits for you in a corner you'll forget to check.

### 🐌 Big files, no problem
Instagram exports are full of photos and can be huge. Kin now streams uploads properly and, for very large files, can import straight from a folder on your own server — no size cap, nothing leaving your machine.

### 🔧 Quiet fixes
- Saving settings without touching a key field no longer wipes your stored secrets.
- Birthday-draft and gift suggestions are backfilled cleanly for existing people.

That's everything for now. Thank you for being here — don't let the bastards get you down~ — Skye
""".strip(),
}
