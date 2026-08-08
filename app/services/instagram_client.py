"""Instagram integration using the unofficial `instagrapi` library.

IMPORTANT CAVEATS (documented for the user in Settings UI + README too):
  - This uses an unofficial, reverse-engineered API. It is against Instagram's
    Terms of Service and carries a real (if generally low, for light/read-only
    personal use) risk of the login account being challenged or restricted.
  - Never use your only/important Instagram account for this - consider a
    secondary account that follows the people you want to track.
  - Instagram frequently changes behaviour; this integration may break and
    need updating.
  - Everything fetched lands in a pending review queue - nothing is ever
    posted, messaged, or acted on automatically (human in the loop).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..config import settings


class InstagramError(Exception):
    pass


def _session_path(username: str) -> Path:
    safe = "".join(c for c in username if c.isalnum() or c in "._-")
    return settings.INSTAGRAM_SESSION_DIR / f"{safe}.json"


class InstagramClient:
    def __init__(self, username: str, password: str):
        if not username or not password:
            raise InstagramError("Instagram is not configured. Add credentials in Settings.")
        self.username = username
        self.password = password
        self._cl = None

    def _client(self):
        if self._cl is not None:
            return self._cl
        try:
            from instagrapi import Client
        except ImportError:
            raise InstagramError(
                "instagrapi is not installed in this image. Rebuild the container "
                "with requirements.txt as provided."
            )
        cl = Client()
        session_file = _session_path(self.username)
        try:
            if session_file.exists():
                cl.load_settings(session_file)
                cl.login(self.username, self.password)
            else:
                cl.login(self.username, self.password)
            cl.dump_settings(session_file)
        except Exception as e:
            raise InstagramError(f"Instagram login failed: {e}")
        self._cl = cl
        return cl

    def get_recent_posts(self, target_username: str, count: int = 12) -> list[dict]:
        cl = self._client()
        try:
            user_id = cl.user_id_from_username(target_username)
            medias = cl.user_medias(user_id, amount=count)
        except Exception as e:
            raise InstagramError(f"Could not fetch posts for @{target_username}: {e}")

        out = []
        for m in medias:
            out.append({
                "ig_post_id": str(m.pk),
                "caption": m.caption_text or "",
                "media_url": str(m.thumbnail_url) if m.thumbnail_url else (
                    str(m.video_url) if m.video_url else None
                ),
                "permalink": f"https://www.instagram.com/p/{m.code}/",
                "post_type": str(m.media_type),
                "posted_at": m.taken_at,
            })
        return out


def get_client_from_settings(db) -> Optional["InstagramClient"]:
    from ..settings_store import get_setting
    username = get_setting(db, "instagram_username")
    password = get_setting(db, "instagram_password")
    if not username or not password:
        return None
    return InstagramClient(username, password)
