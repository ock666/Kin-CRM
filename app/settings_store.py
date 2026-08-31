"""Simple key/value settings stored in the DB (Immich creds, AI creds, app prefs)."""
from sqlalchemy.orm import Session

from .models import Setting

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
