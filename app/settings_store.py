"""Simple key/value settings stored in the DB.

Two layers:
- `settings` — instance-level config (AI/Immich/TTS/Whisper creds, push VAPID, scheduler
  hour). Admin-controlled, shared by every user on the instance.
- `user_settings` — per-user preferences (birthday lead days, cadence defaults, grace note,
  notification toggles, calendar-sync choices). One row per (user, key).
"""
from sqlalchemy.orm import Session

from .models import Setting, UserSetting

DEFAULTS = {
    "immich_url": "",
    "immich_api_key": "",
    "ai_base_url": "https://api.openai.com/v1",
    "ai_api_key": "",
    "ai_model": "gpt-4o-mini",
    "support_chat_model": "gpt-4o",
    # Whisper (voice transcription) — if unset, falls back to AI settings (OpenAI-compatible)
    "whisper_base_url": "",
    "whisper_api_key": "",
    "whisper_model": "whisper-1",
    "whisper_provider": "openai",  # 'openai' or 'asr-webservice'
    "birthday_lead_days": "14",
    "checkin_default_cadence_days": "60",
    "daily_job_hour": "8",
    "push_enabled": "0",
    "push_birthdays": "1",
    "push_cadence": "1",
    # Calendar sync (ICS feed served by Kin, subscribed to from any external calendar)
    "calendar_ics_enabled": "0",
    "calendar_ics_token": "",
    "calendar_sync_birthdays": "1",
    "calendar_sync_notable_dates": "1",
    "calendar_birthday_reminder_days": "14",
    "calendar_notable_reminder_days": "1",
    "grace_until": "",
    "reassurance_note": "",
    "conflict_plan_idle_minutes": "15",
    "chat_retention_days": "14",
    # TTS (voice replies)
    "tts_provider": "piper",           # piper | openai
    "tts_base_url": "",               # Piper base URL or OpenAI base (or LiteLLM)
    "tts_api_key": "",                # OpenAI/LiteLLM key if needed
    "tts_voice": "en_GB-alba-medium", # Piper default (Alba); OpenAI e.g. 'alloy'
    "tts_lang": "en-GB",
    "tts_format": "mp3",
    "tts_piper_host": "",
    "tts_piper_port": "10200",
    "tts_piper_web_port": "5500",      # Piper web UI (used only to enumerate voices)
    "tts_mirror_mode": "1",           # if on, bot replies with voice when user sends voice; if off, bot always replies with text
}


SENSITIVE_KEYS = {"immich_api_key", "ai_api_key", "vapid_private_key", "whisper_api_key", "tts_api_key"}

# Per-user preferences. Everything here is personal (notification toggles, cadence defaults,
# the grace "stepping back" state, calendar-sync choices) and must be isolated per user.
USER_DEFAULTS = {
    "birthday_lead_days": "14",
    "checkin_default_cadence_days": "60",
    "grace_until": "",
    "reassurance_note": "",
    "tts_mirror_mode": "1",
    "push_enabled": "0",
    "push_birthdays": "1",
    "push_cadence": "1",
    "calendar_ics_enabled": "0",
    "calendar_ics_token": "",
    "calendar_sync_birthdays": "1",
    "calendar_sync_notable_dates": "1",
    "calendar_birthday_reminder_days": "14",
    "calendar_notable_reminder_days": "1",
}

# Keys that migrated from the old global `settings` table into per-user `user_settings`.
PER_USER_KEYS = set(USER_DEFAULTS)


def get_all_settings(db: Session) -> dict:
    out = dict(DEFAULTS)
    for row in db.query(Setting).all():
        out[row.key] = row.value or ""
    for key in SENSITIVE_KEYS:
        if key in out and out[key]:
            out[key] = "••••••••"
    return out


def get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.get(Setting, key)
    if row is not None and row.value is not None:
        return row.value
    return DEFAULTS.get(key, default)


def get_setting_sensitive(db: Session, key: str) -> str:
    row = db.get(Setting, key)
    if row is not None and row.value is not None:
        return row.value
    return DEFAULTS.get(key, "")


def set_setting(db: Session, key: str, value: str):
    row = db.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()


def set_many(db: Session, values: dict):
    for k, v in values.items():
        set_setting(db, k, v)


def get_user_setting(db: Session, user_id: int, key: str, default: str = "") -> str:
    row = db.query(UserSetting).filter(UserSetting.user_id == user_id, UserSetting.key == key).first()
    if row is not None and row.value is not None:
        return row.value
    return USER_DEFAULTS.get(key, default)


def set_user_setting(db: Session, user_id: int, key: str, value: str):
    row = db.query(UserSetting).filter(UserSetting.user_id == user_id, UserSetting.key == key).first()
    if row is None:
        row = UserSetting(user_id=user_id, key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()


def get_all_user_settings(db: Session, user_id: int) -> dict:
    out = dict(USER_DEFAULTS)
    for row in db.query(UserSetting).filter(UserSetting.user_id == user_id).all():
        out[row.key] = row.value or ""
    return out


def set_many_user(db: Session, user_id: int, values: dict):
    for k, v in values.items():
        set_user_setting(db, user_id, k, v)
