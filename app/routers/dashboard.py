import datetime as dt

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import Person, NotableDate, ConflictLog, ConflictStatus
from ..render import render
from ..services import birthdays as bday_service
from ..services import checkins as checkin_service
from ..services import gamification
from ..services.immich_client import get_client_from_settings as immich_from_settings, ImmichError
from ..settings_store import get_setting

router = APIRouter()


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")

    today = dt.date.today()
    lead_days = int(get_setting(db, "birthday_lead_days", "3") or 3)
    upcoming_birthdays = bday_service.people_with_upcoming_birthdays(db, lead_days)

    upcoming_notable = []
    for nd in db.query(NotableDate).all():
        try:
            nb = dt.date(today.year, nd.month, nd.day)
        except ValueError:
            continue
        if nb < today:
            try:
                nb = dt.date(today.year + 1, nd.month, nd.day)
            except ValueError:
                continue
        delta = (nb - today).days
        if 0 <= delta <= lead_days:
            upcoming_notable.append((nd, delta))
    upcoming_notable.sort(key=lambda t: t[1])

    overdue = checkin_service.overdue_people(db)
    progress = gamification.get_stats_and_achievements(db)

    memories = []
    memories_error = None
    try:
        client = immich_from_settings(db)
        memories = client.on_this_day_with_fallback()
    except ImmichError as e:
        memories_error = str(e)

    if memories:
        gamification.check_only(request, db, context={"viewed_on_this_day": True})

    # Gentle, dismissible AI-suggested conflict resolutions (see services/conflict_resolution.py).
    # Never auto-resolved - just surfaced here for a one-click confirm or "still working on it".
    suggested_resolutions = (
        db.query(ConflictLog)
        .filter(ConflictLog.status == ConflictStatus.unresolved)
        .filter(ConflictLog.ai_suggested_resolution.is_(True))
        .filter(ConflictLog.ai_suggested_prompt.isnot(None))
        .all()
    )

    return render(
        request, "dashboard.html", db=db, user=user, active="dashboard",
        upcoming_birthdays=upcoming_birthdays,
        upcoming_notable=upcoming_notable,
        overdue=overdue,
        memories=memories,
        memories_error=memories_error,
        today=today,
        progress=progress,
        suggested_resolutions=suggested_resolutions,
    )


@router.get("/progress")
def progress_page(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    progress = gamification.get_stats_and_achievements(db)
    return render(request, "progress.html", db=db, user=user, active="progress", progress=progress)


@router.post("/checkin/{person_id}/snooze")
def snooze_checkin(person_id: int, request: Request, db: Session = Depends(get_db),
                    user=Depends(current_user), days: int = Form(14)):
    person = db.get(Person, person_id)
    if person:
        person.checkin_snoozed_until = dt.date.today() + dt.timedelta(days=days)
        db.commit()
    return RedirectResponse("/", status_code=303)


@router.post("/checkin/{person_id}/mark-contacted")
def mark_contacted(person_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    person = db.get(Person, person_id)
    if person:
        was_overdue = checkin_service.is_overdue(person)
        person.last_contact_date = dt.date.today()
        person.checkin_snoozed_until = None
        db.commit()
        if was_overdue:
            all_cleared = len(checkin_service.overdue_people(db)) == 0
            gamification.award_and_flash(request, db, "OVERDUE_CHECKIN",
                                          context={"all_overdue_cleared": all_cleared})
    return RedirectResponse("/", status_code=303)
