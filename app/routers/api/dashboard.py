"""API v1 — dashboard (today)."""
import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import Person
from ...services import birthdays, checkins
from ...settings_store import get_setting
from .deps import get_current_api_user

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


def _safe_int(value: str, default: int) -> int:
    try:
        return int(value) if value else default
    except (ValueError, TypeError):
        return default


@router.get("/today")
def dashboard_today(db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    today = dt.date.today()
    lead = _safe_int(get_setting(db, "birthday_lead_days", "3"), 3)

    upcoming = birthdays.people_with_upcoming_birthdays(db, lead)
    birthdays_list = [
        {"id": p.id, "name": p.name, "days_away": d} for p, d in upcoming
    ]

    overdue = checkins.overdue_people(db)
    overdue_list = [
        {"id": p.id, "name": p.name, "days_overdue": d}
        for p, d in sorted(overdue, key=lambda t: -t[1])[:10]
    ]

    return {
        "today": today.isoformat(),
        "birthdays": birthdays_list,
        "overdue_checkins": overdue_list,
        "grace_active": get_setting(db, "grace_until", "").strip() != "",
    }
