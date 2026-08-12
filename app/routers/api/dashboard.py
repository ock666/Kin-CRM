"""API v1 — dashboard (today)."""
import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import Person, NotableDate
from ...services import birthdays, checkins, gamification, grace
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

    # Gamification
    gm_data = gamification.get_stats_and_achievements(db)
    gm = {
        "xp": gm_data["stats"].total_xp,
        "level": gm_data["stats"].current_level,
        "next_level_threshold": gm_data["next_level_threshold"],
        "progress_pct": gm_data["progress_pct"],
        "unlocked_count": gm_data["unlocked_count"],
    }

    # Notable dates coming up
    lead_days = _safe_int(get_setting(db, "birthday_lead_days", "3"), 3)
    all_nds = db.query(NotableDate).all()
    notable_dates_list = []
    for nd in all_nds:
        days = (dt.date(today.year, nd.month, nd.day) - today).days
        if days < 0 and nd.recurring:
            days = (dt.date(today.year + 1, nd.month, nd.day) - today).days
        if 0 <= days <= lead_days:
            notable_dates_list.append({
                "id": nd.id, "label": nd.label or "Notable date",
                "month": nd.month, "day": nd.day, "year": nd.year,
                "days_away": days,
                "person_name": nd.person.name if nd.person else "",
            })

    return {
        "today": today.isoformat(),
        "birthdays": birthdays_list,
        "overdue_checkins": overdue_list,
        "grace_active": get_setting(db, "grace_until", "").strip() != "",
        "gamification": gm,
        "notable_dates": notable_dates_list,
        "reassurance_note": get_setting(db, "reassurance_note", ""),
    }
