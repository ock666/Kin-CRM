"""Calendar ICS feed endpoint - subscribe from any external calendar (Google, Apple, etc.).

The feed is unauthenticated by design (calendar clients can't send bearer tokens), so access is
gated by a high-entropy token in the URL: GET /calendar.ics?token=... Each user has their OWN
token (and their own feed showing only their people). A wrong/missing token 404s silently so the
feed URL isn't discoverable.
"""
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, UserSetting
from ..settings_store import get_user_setting
from ..services.calendar_ics import build_ics

router = APIRouter()


def _reminder_days(db: Session, user_id: int, key: str, fallback: int) -> int:
    try:
        return max(0, int(get_user_setting(db, user_id, key, str(fallback)) or fallback))
    except (TypeError, ValueError):
        return fallback


@router.get("/calendar.ics")
def calendar_ics(token: str = "", db: Session = Depends(get_db)):
    if not token:
        return Response(status_code=404)
    # Resolve the token to its owner, then build that user's feed.
    row = (
        db.query(UserSetting)
        .filter(UserSetting.key == "calendar_ics_token", UserSetting.value == token)
        .first()
    )
    if row is None:
        return Response(status_code=404)
    user_id = row.user_id
    if get_user_setting(db, user_id, "calendar_ics_enabled", "0") != "1":
        return Response(status_code=404)
    user = db.get(User, user_id)
    if user is None:
        return Response(status_code=404)

    body = build_ics(
        db,
        user,
        birthday_reminder_days=_reminder_days(db, user_id, "calendar_birthday_reminder_days", 14),
        notable_reminder_days=_reminder_days(db, user_id, "calendar_notable_reminder_days", 1),
        include_birthdays=get_user_setting(db, user_id, "calendar_sync_birthdays", "1") != "0",
        include_notable_dates=get_user_setting(db, user_id, "calendar_sync_notable_dates", "1") != "0",
    )
    return Response(
        content=body,
        media_type="text/calendar",
        headers={
            "Content-Disposition": 'attachment; filename="kin.ics"',
            "Cache-Control": "no-store",
        },
    )
