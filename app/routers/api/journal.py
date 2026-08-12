"""API v1 — journal CRUD."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import JournalEntry, JournalImage, Person, EventType, EnergyCost
from ...schemas.journal import JournalCreate, JournalUpdate, JournalEntryResponse
from ...services import checkins, gamification as gm
from .deps import get_current_api_user

router = APIRouter(prefix="/api/v1/journal", tags=["journal"])


def _safe_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _safe_enum(enum_cls, value, default):
    try:
        return enum_cls(value) if value else default
    except ValueError:
        return default


def _entry_response(e: JournalEntry) -> dict:
    return {
        "id": e.id,
        "title": e.title,
        "body": e.body,
        "entry_date": e.entry_date.isoformat() if e.entry_date else None,
        "event_type": e.event_type.value if e.event_type else "note",
        "energy_cost": e.energy_cost.value if e.energy_cost else None,
        "location": e.location,
        "source": e.source,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "people": [p.name for p in e.people],
    }


@router.post("", status_code=201)
def create_entry(body: JournalCreate, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    entry = JournalEntry(
        author_user_id=user.id,
        title=body.title,
        body=body.body,
        entry_date=_safe_date(body.entry_date) or dt.date.today(),
        event_type=_safe_enum(EventType, body.event_type, EventType.note),
        energy_cost=_safe_enum(EnergyCost, body.energy_cost, None),
        location=body.location,
        source="api",
    )
    for pid in body.person_ids:
        p = db.get(Person, pid)
        if p:
            entry.people.append(p)
            checkins.touch_last_contact(db, p, entry.entry_date)
    db.add(entry)
    db.flush()
    gm.award_xp(db, "NOTE_ADDED")
    db.commit()
    db.refresh(entry)
    return _entry_response(entry)


@router.put("/{entry_id}")
def update_entry(entry_id: int, body: JournalUpdate, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    entry = db.get(JournalEntry, entry_id)
    if not entry or entry.author_user_id != user.id:
        raise HTTPException(status_code=404, detail="Entry not found")
    if body.title is not None:
        entry.title = body.title
    if body.body is not None:
        entry.body = body.body
    if body.entry_date is not None:
        entry.entry_date = _safe_date(body.entry_date) or entry.entry_date
    if body.event_type is not None:
        entry.event_type = _safe_enum(EventType, body.event_type, entry.event_type)
    if body.energy_cost is not None:
        entry.energy_cost = _safe_enum(EnergyCost, body.energy_cost, entry.energy_cost)
    if body.location is not None:
        entry.location = body.location
    if body.person_ids is not None:
        entry.people = [p for pid in body.person_ids if (p := db.get(Person, pid))]
    db.commit()
    db.refresh(entry)
    return _entry_response(entry)


@router.delete("/{entry_id}", status_code=204)
def delete_entry(entry_id: int, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    entry = db.get(JournalEntry, entry_id)
    if not entry or entry.author_user_id != user.id:
        raise HTTPException(status_code=404, detail="Entry not found")
    db.delete(entry)
    db.commit()
