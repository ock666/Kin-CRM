import datetime as dt

from sqlalchemy.orm import Session

from ..models import Person


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
        if p.checkin_snoozed_until and p.checkin_snoozed_until >= today:
            continue
        baseline = p.last_contact_date
        if baseline is None:
            # never logged contact - treat account creation as baseline
            baseline = p.created_at.date() if p.created_at else today
        days_since = (today - baseline).days
        if days_since >= p.checkin_cadence_days:
            out.append((p, days_since - p.checkin_cadence_days))
    return sorted(out, key=lambda t: -t[1])


def touch_last_contact(db: Session, person: Person, entry_date: dt.date):
    if person.last_contact_date is None or entry_date > person.last_contact_date:
        person.last_contact_date = entry_date
        db.add(person)
