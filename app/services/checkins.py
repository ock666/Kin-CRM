import datetime as dt

from sqlalchemy.orm import Session

from ..models import Person, RelationshipState


def is_overdue(person: Person, today: dt.date | None = None) -> bool:
    """Single-person version of the same logic used by `overdue_people()` - used by the
    gamification hook to check "was this actually overdue?" before awarding bonus XP for
    clearing it (so casually clicking 'mark caught up' on someone who wasn't overdue doesn't
    farm XP). Skips anyone with an active relationship-state that suppresses nudges."""
    if not person.checkin_cadence_days:
        return False
    today = today or dt.date.today()
    if person.checkin_snoozed_until and person.checkin_snoozed_until >= today:
        return False
    from .states import effective_state
    state = effective_state(person, today)
    if state in (RelationshipState.wants_space, RelationshipState.in_conflict, RelationshipState.drifted):
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


def compute_cadence_watermeter(person: Person, today: dt.date | None = None) -> dict:
    """A calm, non-punitive "needs watering" cadence meter for a person.

    Returns a dict describing how close the person is to their check-in interval elapsing,
    as a plant-wilting metaphor (matches the 'needs watering' framing):
      state    one of "healthy" | "getting_dry" | "wilting" | "dormant"
      label    short human label for the state
      emoji    a small visual cue (leaf/watering can)
      pct      how far through the interval they are (0-100+), for a visual fill bar
      overdue  True when past their interval

    Why the metaphor: "plants need watering, not scolding" - a leaf dropping slightly as a
    cadence creeps up is gentler and far less triggering than a "OVERDUE!" red-alert list for
    someone managing RSD/anxiety. There is never shame in a low meter: it's just information,
    and the user can snooze or mark contacted whenever they feel ready.

    Users WITHOUT a cadence set are "dormant" - no bar, no pressure, treated as intentionally
    on-hold rather than broken.
    """
    today = today or dt.date.today()

    if not person.checkin_cadence_days:
        return {"state": "dormant", "label": "On hold", "emoji": "💤", "pct": 0, "overdue": False}

    if person.checkin_snoozed_until and person.checkin_snoozed_until >= today:
        return {"state": "dormant", "label": "Snoozed", "emoji": "💤", "pct": 0, "overdue": False}

    cadence = person.checkin_cadence_days
    baseline = person.last_contact_date or (person.created_at.date() if person.created_at else today)
    days_since = max(0, (today - baseline).days)
    pct = round((days_since / cadence) * 100) if cadence else 0

    if pct < 60:
        return {"state": "healthy", "label": "Healthy", "emoji": "🪴", "pct": pct, "overdue": False}
    if pct < 100:
        return {"state": "getting_dry", "label": "Getting dry", "emoji": "🥀", "pct": pct, "overdue": False}
    return {"state": "wilting", "label": "Needs watering", "emoji": "💧", "pct": min(pct, 200), "overdue": True}
