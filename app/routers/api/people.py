"""API v1 — people CRUD."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import Person, Tag, JournalEntry, ConflictLog
from ...schemas.people import PersonCreate, PersonUpdate, PersonResponse, TagResponse
from ...services import friend_rank, checkins
from .deps import get_current_api_user

router = APIRouter(prefix="/api/v1/people", tags=["people"])


def _safe_int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _safe_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _person_response(p: Person) -> dict:
    rank = friend_rank.compute_friend_rank(p)
    return {
        "id": p.id,
        "name": p.name,
        "nickname": p.nickname,
        "pronouns": p.pronouns,
        "relationship_label": p.relationship_label,
        "birthday_month": p.birthday_month,
        "birthday_day": p.birthday_day,
        "birthday_year": p.birthday_year,
        "how_we_met": p.how_we_met,
        "met_date": p.met_date.isoformat() if p.met_date else None,
        "location": p.location,
        "phone": p.phone,
        "email": p.email,
        "notes": p.notes,
        "occupation": p.occupation,
        "hobbies": p.hobbies,
        "bio": p.bio,
        "ai_summary": p.ai_summary,
        "checkin_cadence_days": p.checkin_cadence_days,
        "last_contact_date": p.last_contact_date.isoformat() if p.last_contact_date else None,
        "relationship_state": p.relationship_state.value if p.relationship_state else "none",
        "archived": p.archived,
        "tags": [t.name for t in p.tags],
        "friend_rank": rank.get("score", 0),
    }


@router.get("")
def list_people(
    q: str = Query(""),
    tag: str = Query(""),
    show_archived: bool = Query(False),
    db: Session = Depends(get_db),
    user=Depends(get_current_api_user),
):
    query = db.query(Person).filter(Person.archived.is_(show_archived))
    if q:
        query = query.filter(Person.name.ilike(f"%{q}%"))
    people = query.order_by(Person.name).all()
    if tag:
        people = [p for p in people if any(t.name == tag for t in p.tags)]
    return [_person_response(p) for p in people]


@router.post("", status_code=201)
def create_person(body: PersonCreate, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    p = Person(
        name=body.name.strip(),
        nickname=body.nickname,
        pronouns=body.pronouns,
        relationship_label=body.relationship_label,
        birthday_month=_safe_int(body.birthday_month),
        birthday_day=_safe_int(body.birthday_day),
        birthday_year=_safe_int(body.birthday_year),
        how_we_met=body.how_we_met,
        met_date=_safe_date(body.met_date),
        location=body.location,
        phone=body.phone,
        email=body.email,
        notes=body.notes,
        occupation=body.occupation,
        hobbies=body.hobbies,
        bio=body.bio,
        checkin_cadence_days=_safe_int(body.checkin_cadence_days),
        archived=body.archived,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _person_response(p)


@router.get("/{person_id}")
def get_person(person_id: int, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    p = db.get(Person, person_id)
    if not p:
        raise HTTPException(status_code=404, detail="Person not found")
    return _person_response(p)


@router.put("/{person_id}")
def update_person(person_id: int, body: PersonUpdate, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    p = db.get(Person, person_id)
    if not p:
        raise HTTPException(status_code=404, detail="Person not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        if k in ("birthday_month", "birthday_day", "birthday_year", "checkin_cadence_days"):
            setattr(p, k, _safe_int(v))
        elif k == "met_date":
            setattr(p, k, _safe_date(v))
        elif k == "name":
            setattr(p, k, v.strip())
        else:
            setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return _person_response(p)


@router.delete("/{person_id}", status_code=204)
def delete_person(person_id: int, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    p = db.get(Person, person_id)
    if not p:
        raise HTTPException(status_code=404, detail="Person not found")
    db.delete(p)
    db.commit()


@router.get("/tags/all", response_model=list[TagResponse])
def list_tags(db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    return [TagResponse(name=t.name) for t in db.query(Tag).order_by(Tag.name).all()]


@router.get("/{person_id}/journal")
def get_person_journal(person_id: int, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    p = db.get(Person, person_id)
    if not p:
        raise HTTPException(status_code=404, detail="Person not found")
    entries = sorted(p.journal_entries, key=lambda e: e.entry_date or dt.date.min, reverse=True)
    return [{
        "id": e.id, "title": e.title, "body": e.body,
        "entry_date": e.entry_date.isoformat() if e.entry_date else None,
        "event_type": e.event_type.value if e.event_type else "note",
        "energy_cost": e.energy_cost.value if e.energy_cost else None,
        "location": e.location, "source": e.source,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "people": [pp.name for pp in e.people],
    } for e in entries]


@router.get("/{person_id}/conflicts")
def get_person_conflicts(person_id: int, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    p = db.get(Person, person_id)
    if not p:
        raise HTTPException(status_code=404, detail="Person not found")
    return [{
        "id": c.id, "summary": c.summary, "status": c.status.value,
        "resolution_notes": c.resolution_notes,
        "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "person_name": c.person.name if c.person else None,
    } for c in p.conflict_logs]


@router.get("/{person_id}/notable-dates")
def get_person_notable_dates(person_id: int, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    p = db.get(Person, person_id)
    if not p:
        raise HTTPException(status_code=404, detail="Person not found")
    return {
        "notable_dates": [{
            "id": nd.id, "label": nd.label, "month": nd.month,
            "day": nd.day, "year": nd.year, "recurring": nd.recurring,
            "notes": nd.notes,
        } for nd in p.notable_dates],
        "scratchpad_items": [{"id": s.id, "text": s.text} for s in p.scratchpad_items],
        "notable_people": [{"id": np.id, "name": np.name, "relation": np.relation} for np in p.notable_people_refs],
    }
