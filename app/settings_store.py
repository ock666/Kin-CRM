"""Simple key/value settings stored in the DB (Immich creds, AI creds, app prefs)."""
from sqlalchemy.orm import Session

from .models import Setting

DEFAULTS = {
    "immich_url": "",
    "immich_api_key": "",
    "ai_base_url": "https://api.openai.com/v1",
    "ai_api_key": "",
    "ai_model": "gpt-4o-mini",
    "instagram_username": "",
    "instagram_password": "",
    "birthday_lead_days": "3",
    "checkin_default_cadence_days": "60",
    "daily_job_hour": "8",
}


def get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.get(Setting, key)
    if row is not None and row.value is not None:
        return row.value
    return DEFAULTS.get(key, default)


def get_all_settings(db: Session) -> dict:
    out = dict(DEFAULTS)
    for row in db.query(Setting).all():
        out[row.key] = row.value or ""
    return out


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
