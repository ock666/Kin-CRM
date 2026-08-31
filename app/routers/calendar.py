"""Calendar ICS feed endpoint - subscribe from any external calendar (Google, Apple, etc.).

The feed is unauthenticated by design (calendar clients can't send bearer tokens), so access is
gated by a high-entropy token in the URL: GET /calendar.ics?token=... The token is generated on
first enable in Settings and can be rotated by toggling the feed. A wrong/missing token 404s
silently so the feed URL isn't discoverable.
"""
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..settings_store import get_setting
from ..services.calendar_ics import build_ics

router = APIRouter()


def _reminder_days(db: Session, key: str, fallback: int) -> int:
    try:
        return max(0, int(get_setting(db, key, str(fallback)) or fallback))
    except (TypeError, ValueError):
        return fallback


@router.get("/calendar.ics")
def calendar_ics(token: str = "", db: Session = Depends(get_db)):
    if get_setting(db, "calendar_ics_enabled", "0") != "1":
        return Response(status_code=404)
    expected = get_setting(db, "calendar_ics_token", "")
    if not expected or not token or token != expected:
        return Response(status_code=404)

    body = build_ics(
        db,
        birthday_reminder_days=_reminder_days(db, "calendar_birthday_reminder_days", 14),
        notable_reminder_days=_reminder_days(db, "calendar_notable_reminder_days", 1),
        include_birthdays=get_setting(db, "calendar_sync_birthdays", "1") != "0",
        include_notable_dates=get_setting(db, "calendar_sync_notable_dates", "1") != "0",
    )
    return Response(
        content=body,
        media_type="text/calendar",
        headers={
            "Content-Disposition": 'attachment; filename="kin.ics"',
            "Cache-Control": "no-store",
        },
    )
