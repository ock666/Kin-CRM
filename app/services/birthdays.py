import datetime as dt
import logging

from sqlalchemy.orm import Session

from ..models import Person, BirthdayMessageDraft, GiftIdea, GiftStatus, ReviewStatus
from ..settings_store import get_setting
from .ai_client import get_client_from_settings, build_person_context, AIError

logger = logging.getLogger(__name__)


def _safe_int(val: str | int | None, fallback: int) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return fallback


def _next_birthday(person: Person, today: dt.date) -> dt.date | None:
    if not person.birthday_month or not person.birthday_day:
        return None
    year = today.year
    try:
        candidate = dt.date(year, person.birthday_month, person.birthday_day)
    except ValueError:
        if person.birthday_month == 2 and person.birthday_day == 29:
            candidate = dt.date(year, 3, 1)
        else:
            return None
    if candidate < today:
        try:
            candidate = dt.date(year + 1, person.birthday_month, person.birthday_day)
        except ValueError:
            if person.birthday_month == 2 and person.birthday_day == 29:
                candidate = dt.date(year + 1, 3, 1)
            else:
                return None
    return candidate


def days_until_birthday(person: Person, today: dt.date | None = None) -> int | None:
    """Days until a person's next birthday (0 = today). None when they have no birthday set."""
    nb = _next_birthday(person, today or dt.date.today())
    if nb is None:
        return None
    return (nb - (today or dt.date.today())).days


def people_with_upcoming_birthdays(db: Session, lead_days: int) -> list[tuple[Person, int]]:
    """Returns (person, days_until) for people whose birthday falls within lead_days."""
    today = dt.date.today()
    out = []
    for p in db.query(Person).filter(Person.archived.is_(False)).all():
        nb = _next_birthday(p, today)
        if nb is None:
            continue
        delta = (nb - today).days
        if 0 <= delta <= lead_days:
            out.append((p, delta))
    return sorted(out, key=lambda t: t[1])


def generate_birthday_drafts(db: Session) -> int:
    """Create pending BirthdayMessageDraft rows for people whose birthday is coming up
    soon, if one doesn't already exist for this year. Always human-in-the-loop -
    nothing is sent automatically. Returns number of drafts created."""
    lead_days = _safe_int(get_setting(db, "birthday_lead_days", "3"), 3)
    today = dt.date.today()
    created = 0

    ai = None
    try:
        ai = get_client_from_settings(db)
    except AIError:
        ai = None

    for person, days_until in people_with_upcoming_birthdays(db, lead_days):
        target_year = (today + dt.timedelta(days=days_until)).year
        existing = db.query(BirthdayMessageDraft).filter_by(person_id=person.id, year=target_year).first()
        if existing:
            continue

        context = build_person_context(person)
        text = None
        if ai:
            try:
                text = ai.draft_birthday_message(person.name, person.relationship_label or "", context)
            except AIError as e:
                logger.info("AI birthday draft failed for %s: %s", person.name, e)

        if not text:
            text = (
                f"Happy birthday, {person.nickname or person.name}! 🎉 Hope you have a wonderful day - "
                f"thinking of you and would love to catch up soon."
            )

        draft = BirthdayMessageDraft(
            person_id=person.id, year=target_year, draft_text=text, status=ReviewStatus.pending
        )
        db.add(draft)
        created += 1

        # Gift suggestion (<$40) alongside the birthday draft - only when AI is configured,
        # since there's no sensible non-AI fallback for a *specific* gift idea. Always lands as
        # a pending suggestion for review, never auto-bought/sent, and avoids repeating anything
        # already suggested/given to this person before.
        if ai:
            existing_gift = db.query(GiftIdea).filter_by(person_id=person.id, year=target_year).first()
            if not existing_gift:
                previous = [g.description for g in person.gift_ideas]
                try:
                    gift_text = ai.suggest_gift(person.name, context, previous)
                    if gift_text:
                        db.add(GiftIdea(
                            person_id=person.id, year=target_year, description=gift_text,
                            status=GiftStatus.suggested,
                        ))
                except AIError as e:
                    logger.info("AI gift suggestion failed for %s: %s", person.name, e)

    db.commit()
    return created
