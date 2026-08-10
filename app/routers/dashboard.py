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
from ..services import grace as grace_service
from ..services.immich_client import get_client_from_settings as immich_from_settings, ImmichError
from ..settings_store import get_setting

router = APIRouter()


def _safe_int(val: str | int | None, fallback: int) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return fallback


def _safe_date(year: int, month: int, day: int) -> dt.date | None:
    try:
        return dt.date(year, month, day)
    except ValueError:
        if month == 2 and day == 29:
            return dt.date(year, 3, 1)
        return None


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")

    today = dt.date.today()
    lead_days = _safe_int(get_setting(db, "birthday_lead_days", "3"), 3)
    upcoming_birthdays = bday_service.people_with_upcoming_birthdays(db, lead_days)

    upcoming_notable = []
    for nd in db.query(NotableDate).all():
        nb = _safe_date(today.year, nd.month, nd.day)
        if nb is None:
            continue
        if nb < today:
            nb = _safe_date(today.year + 1, nd.month, nd.day)
            if nb is None:
                continue
        delta = (nb - today).days
        if 0 <= delta <= lead_days:
            upcoming_notable.append((nd, delta))
    upcoming_notable.sort(key=lambda t: t[1])

    # Grace mode ("stepping back for now"): when active, silence the demanding nudges so the
    # user gets a genuine break. Reaching out stays untouched and no data is lost - the cards
    # simply return when grace ends (the calm banner explains how long is left).
    grace_active = grace_service.is_grace_active(db)
    grace_remaining = grace_service.remaining_days(db) if grace_active else None

    if grace_active:
        overdue = []
        unresolved_conflicts = []
    else:
        overdue = checkin_service.overdue_people(db)
        # Gentle, dismissible reminder about unresolved conflicts - not AI-detected, just "this
        # is still open" - the user can view options and act whenever they feel ready, or dismiss.
        unresolved_conflicts = (
            db.query(ConflictLog)
            .filter(ConflictLog.status == ConflictStatus.unresolved)
            .filter(ConflictLog.reminder_dismissed.is_(False))
            .all()
        )

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

    return render(
        request, "dashboard.html", db=db, user=user, active="dashboard",
        upcoming_birthdays=upcoming_birthdays,
        upcoming_notable=upcoming_notable,
        overdue=overdue,
        memories=memories,
        memories_error=memories_error,
        today=today,
        progress=progress,
        unresolved_conflicts=unresolved_conflicts,
        grace_active=grace_active,
        grace_remaining=grace_remaining,
    )


@router.post("/grace/start")
def start_grace(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    """'Stepping back for now' - no reason needed. Silences gentle nudges & push for a week."""
    grace_service.start_grace(db)
    request.session["notice_flash"] = "Stepping back for a week. Gentle nudge and reminders are paused — take the time you need. 🕊️"
    return RedirectResponse("/", status_code=303)


@router.post("/grace/end")
def end_grace(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    """Come out of grace mode early."""
    grace_service.end_grace(db)
    request.session["notice_flash"] = "Welcome back — easy does it. Gentle reminders are on again."
    return RedirectResponse("/", status_code=303)


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
