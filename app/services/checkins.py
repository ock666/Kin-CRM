import datetime as dt

from sqlalchemy.orm import Session

from ..models import Person


def is_overdue(person: Person, today: dt.date | None = None) -> bool:
    """Single-person version of the same logic used by `overdue_people()` - used by the
    gamification hook to check "was this actually overdue?" before awarding bonus XP for
    clearing it (so casually clicking 'mark caught up' on someone who wasn't overdue doesn't
    farm XP)."""
    if not person.checkin_cadence_days:
        return False
    today = today or dt.date.today()
    if person.checkin_snoozed_until and person.checkin_snoozed_until >= today:
        return False
    baseline = person.last_contact_date
    if baseline is None:
        baseline = person.created_at.date() if person.created_at else today
    return (today - baseline).days >= person.checkin_cadence_days


def overdue_people(db: Session) -> list[tuple[Person, int]]:
    """Returns (person, days_overdue) for people past their check-in cadence,
    skipping anyone currently snoozed. Non-punitive by design: this is a gentle
    nudge list, not a red-alert list."""
    today = dt.date.today()
    out = []
    people = (
        db.query(Person)
        .filter(Person.archived.is_(False))
        .filter(Person.checkin_cadence_days.isnot(None))
        .all()
    )
    for p in people:
        if is_overdue(p, today):
            baseline = p.last_contact_date or (p.created_at.date() if p.created_at else today)
            days_since = (today - baseline).days
            out.append((p, days_since - p.checkin_cadence_days))
    return sorted(out, key=lambda t: -t[1])


def touch_last_contact(db: Session, person: Person, entry_date: dt.date):
    if person.last_contact_date is None or entry_date > person.last_contact_date:
        person.last_contact_date = entry_date
        db.add(person)
