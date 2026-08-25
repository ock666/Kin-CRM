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
from ..services.hangouts import invalidate_hangout_cache, unattached_asset_ids
from ..services.immich_client import get_client_from_settings, ImmichError

router = APIRouter()

MAX_ATTACHED_ASSETS = 6


def _safe_date(value: str) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _clamped_today(value: str) -> dt.date:
    """Parsed date, clamped so it's never in the future (a future last-contact date would
    permanently silence the person's nudges)."""
    d = _safe_date(value) or dt.date.today()
    if d > dt.date.today():
        return dt.date.today()
    return d


def _person_face_assets(db, person: Person) -> set[str]:
    """The asset ids Immich actually tags with this person's face in the recent window.
    Used to reject crafted `asset_ids` (e.g. photos of anyone else on the server). Falls back to
    an empty set if Immich is unreachable - callers treat empty as 'no verification available'."""
    if not person.immich_person_id:
        return set()
    try:
        client = get_client_from_settings(db)
        cutoff = dt.date.today() - dt.timedelta(days=31)
        window_start = dt.datetime.combine(cutoff, dt.time.min) - dt.timedelta(hours=24)
        window_end = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=24)
        assets = client.search_by_person(
            person.immich_person_id,
            taken_after=window_start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            taken_before=window_end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            size=100,
        )
        return {a["id"] for a in assets}
    except ImmichError:
        return set()


@router.post("/hangouts/log")
def log_hangout(
    request: Request, db: Session = Depends(get_db), user=Depends(current_user),
    person_id: int = Form(...), entry_date: str = Form(""), asset_ids: list[str] = Form([]),
):
    """One-click hangout log: creates a journal entry with the hangout photos auto-attached."""
    if not user:
        return RedirectResponse("/login")
    person = db.get(Person, person_id)
    if not person or not person.immich_person_id:
        return RedirectResponse("/", status_code=303)

    # Never accept an arbitrary date or asset list: clamp future dates (a future last-contact
    # would silence nudges forever), cap the asset list, and drop any asset that isn't actually
    # tagged with this person's face in Immich (when Immich is reachable to verify).
    hangout_date = _clamped_today(entry_date)
    asset_ids = asset_ids[:MAX_ATTACHED_ASSETS]
    verified = _person_face_assets(db, person)
    if verified:
        asset_ids = [a for a in asset_ids if a in verified]

    new_asset_ids = unattached_asset_ids(db, person, asset_ids)
    entry = JournalEntry(
        author_user_id=user.id,
        title=None,
        body=f"Hung out with {person.name}.",
        entry_date=hangout_date,
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

    invalidate_hangout_cache()
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

    d = _clamped_today(entry_date)
    exists = (
        db.query(HangoutDismissal)
        .filter_by(person_id=person.id, dismissed_for_date=d)
        .first()
    )
    if not exists:
        db.add(HangoutDismissal(person_id=person.id, dismissed_for_date=d))
        db.commit()
    invalidate_hangout_cache()
    return RedirectResponse("/", status_code=303)
