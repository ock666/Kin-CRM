"""Grace mode - "stepping back for now".

A single, calm, no-questions-asked way to pause the gentle pressure for a week when the user
is burned out. It silences the *demanding* nudges (the reach-out list, unresolved-conflict
reminders, and push notifications) without deleting anything or requiring a reason. Note this
is deliberately different from the per-person snooze: grace mode is global and momentary -
a self-compassion tool, not a data-removal tool.

Why no "take a reason": forcing a reason adds friction and can feel shaming when someone's
simply overwhelmed. Activating it is as quiet and simple as it should be.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from ..settings_store import get_setting, set_setting

GRACE_DAYS = 7


def grace_until(db: Session) -> dt.date | None:
    """Return the date grace mode is active until, or None if it isn't active."""
    raw = (get_setting(db, "grace_until") or "").strip()
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        return None


def is_grace_active(db: Session, today: dt.date | None = None) -> bool:
    """True when grace mode is currently in effect (or a programmatic check happens during it)."""
    until = grace_until(db)
    if until is None:
        return False
    today = today or dt.date.today()
    return today <= until


def remaining_days(db: Session, today: dt.date | None = None) -> int | None:
    """How many days of grace remain (inclusive). None when grace isn't active."""
    until = grace_until(db)
    if until is None:
        return None
    today = today or dt.date.today()
    if today > until:
        return None
    return (until - today).days + 1


def start_grace(db: Session, days: int = GRACE_DAYS, today: dt.date | None = None) -> dt.date:
    """Begin grace mode for `days` days. Returns the last active date. Covers exactly `days`
    calendar days starting today (so 7 days = today through today+6)."""
    today = today or dt.date.today()
    until = today + dt.timedelta(days=days - 1)
    set_setting(db, "grace_until", until.isoformat())
    return until


def end_grace(db: Session):
    set_setting(db, "grace_until", "")
