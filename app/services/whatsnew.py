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
    "date": "August 2026",
    "body": """
Hi, it's Skye. Thanks for trusting Kin with your relationships — this one's a big one, all built to make keeping in touch feel lighter, not heavier.

### 🎙️ Talk, don't type
Record or upload voice notes in the journal and in "Talk it through". Whisper transcribes them into your entries and chats.

### 🔊 Voice replies
The support chat can reply out loud using a local Piper voice or OpenAI, and it mirrors you when you speak. Emoji stay out of the spoken audio (they stay in the text).

### 🖼️ Click any photo to zoom
An in-page cinematic viewer across memories, timelines, galleries, and Instagram — the page dims, and you dismiss it anytime.

### 🧘 A bigger regulation toolkit
Four breathing patterns (Box, 4-7-8, physiological sigh, 4-6), "name it to tame it", the STOP technique, and four gentle games: Soft Fall, 2048, Memory, and Minesweeper. No timers, no scores, no pressure.

### 🗣️ AI that sounds like you
Conversation starters, quick replies, gift ideas, and birthday drafts now match how close you are to someone and mirror your own writing style — no more "coworker" or greeting-card energy.

### 🤫 Dismiss reminders when you need a breather
Quiet a person's gentle nudges with a tap; they'll be there when you're ready. You can also regenerate "things to ask" anytime.

### 📵 Notifications actually work
Fixed the push subscription flow so gentle nudges and test notifications arrive properly.

### 🕵️ Hangout detection
Kin can spot a linked face in a photo from the last month and suggest a quick "looks like you hung out" log.

### 🌙 Calmer look
A moodier evening-lamp theme with gentler entrance motion.

### 🛡️ Safer defaults
Host settings that keep updates from breaking self-hosted setups.

That's everything for now. Thank you for being here — don't let the bastards get you down~ — Skye
""".strip(),
}
