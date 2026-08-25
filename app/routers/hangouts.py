"""Log-a-hangout actions surfaced from the dashboard's hangout card.

The card offers two paths for a detected hangout, tuned to emotional energy:
  - "Quick log": one click, creates a journal entry right away with the photo(s) auto-attached.
  - "Write about it": jumps to the normal journal form pre-filled with the person, hangout date,
    `hangout` event type and the photos so the user can add context before saving.

Both only ever attach photos that aren't already on the person's timeline (see
`hangouts.unattached_asset_ids`) - if the image was already logged, the card shows
"Already logged" instead of offering to re-log it.
"""
import datetime as dt

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import HangoutDismissal, JournalEntry, JournalImage, Person, EventType
from ..services import checkins as checkin_service
from ..services import gamification
from ..services.hangouts import unattached_asset_ids

router = APIRouter()


def _safe_date(value: str) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


@router.post("/hangouts/log")
def log_hangout(
    request: Request, db: Session = Depends(get_db), user=Depends(current_user),
    person_id: int = Form(...), entry_date: str = Form(""), asset_ids: list[str] = Form([]),
):
    """One-click hangout log: creates a journal entry with the hangout photos auto-attached."""
    if not user:
        return RedirectResponse("/login")
    person = db.get(Person, person_id)
    if not person:
        return RedirectResponse("/", status_code=303)

    new_asset_ids = unattached_asset_ids(db, person, asset_ids)
    entry = JournalEntry(
        author_user_id=user.id,
        title=None,
        body=f"Hung out with {person.name}.",
        entry_date=_safe_date(entry_date) or dt.date.today(),
        event_type=EventType.hangout,
        source="manual",
    )
    entry.people.append(person)
    checkin_service.touch_last_contact(db, person, entry.entry_date)
    db.add(entry)
    db.flush()

    for asset_id in new_asset_ids:
        db.add(JournalImage(journal_entry_id=entry.id, immich_asset_id=asset_id))

    db.commit()

    events = ["NOTE_ADDED"]
    if new_asset_ids:
        events.append("PHOTO_ATTACHED")
    gamification.award_and_flash(request, db, *events, context={
        "entry_people_count": 1,
        "entry_word_count": len(entry.body.split()),
        "entry_hour": (entry.created_at or dt.datetime.utcnow()).hour,
    })

    return RedirectResponse(f"/people/{person.id}", status_code=303)


@router.post("/hangouts/dismiss")
def dismiss_hangout(
    request: Request, db: Session = Depends(get_db), user=Depends(current_user),
    person_id: int = Form(...), entry_date: str = Form(""),
):
    """Dismiss a hangout suggestion so its row (and the whole card, once all are dismissed)
    stops showing. Keyed on (person, hangout date), so a genuinely new hangout later can still
    resurface. Dismissing only hides the suggestion - the check-in credit still applies."""
    if not user:
        return RedirectResponse("/login")
    person = db.get(Person, person_id)
    if not person:
        return RedirectResponse("/", status_code=303)

    d = _safe_date(entry_date) or dt.date.today()
    exists = (
        db.query(HangoutDismissal)
        .filter_by(person_id=person.id, dismissed_for_date=d)
        .first()
    )
    if not exists:
        db.add(HangoutDismissal(person_id=person.id, dismissed_for_date=d))
        db.commit()
    return RedirectResponse("/", status_code=303)
