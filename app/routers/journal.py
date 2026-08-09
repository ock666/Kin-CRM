import datetime as dt
import json

from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import JournalEntry, JournalImage, Person, EventType, EnergyCost, Tag, NotableDate
from ..render import render
from ..services import checkins as checkin_service
from ..services.ai_client import get_client_from_settings as ai_from_settings, AIError

router = APIRouter()


@router.get("/journal/new")
def journal_new(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                 person_id: int | None = Query(None)):
    if not user:
        return RedirectResponse("/login")
    people = db.query(Person).filter(Person.archived.is_(False)).order_by(Person.name).all()
    scratchpad_person = db.get(Person, person_id) if person_id else None
    return render(request, "journal_form.html", db=db, user=user, active="journal",
                  people=people, preselect_person_id=person_id, today=dt.date.today().isoformat(),
                  entry=None, scratchpad_person=scratchpad_person)


@router.post("/people/quick-create")
def quick_create_person(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                         quick_name: str = Form(...)):
    name = quick_name.strip()
    person = None
    if name:
        person = Person(name=name)
        db.add(person)
        db.commit()
    return render(request, "partials/person_checkbox.html", db=db, user=user, person=person, checked=True)


@router.post("/journal/new")
def journal_create(
    request: Request, db: Session = Depends(get_db), user=Depends(current_user),
    title: str = Form(""), body: str = Form(...), entry_date: str = Form(...),
    event_type: str = Form("note"), energy_cost: str = Form(""), location: str = Form(""),
    person_ids: list[int] = Form([]), immich_asset_ids: list[str] = Form([]),
):
    if not user:
        return RedirectResponse("/login")
    entry = JournalEntry(
        author_user_id=user.id,
        title=title or None,
        body=body,
        entry_date=dt.date.fromisoformat(entry_date),
        event_type=EventType(event_type) if event_type else EventType.note,
        energy_cost=EnergyCost(energy_cost) if energy_cost else None,
        location=location or None,
        source="manual",
    )
    for pid in person_ids:
        p = db.get(Person, pid)
        if p:
            entry.people.append(p)
            checkin_service.touch_last_contact(db, p, entry.entry_date)
    db.add(entry)
    db.flush()

    for asset_id in immich_asset_ids:
        db.add(JournalImage(journal_entry_id=entry.id, immich_asset_id=asset_id))

    db.commit()

    # AI-assisted profile building: extract structured suggestions for human review.
    # Never applied automatically - see /journal/{id}/suggestions.
    try:
        ai = ai_from_settings(db)
        if ai and entry.people:
            names = ", ".join(p.name for p in entry.people)
            suggestions = ai.extract_facts(names, entry.body)
            if suggestions:
                entry.ai_suggestions_json = json.dumps(suggestions)
                entry.ai_processed = True
                db.commit()
    except AIError:
        pass

    if entry.people:
        return RedirectResponse(f"/people/{entry.people[0].id}", status_code=303)
    return RedirectResponse("/", status_code=303)


@router.get("/journal/{entry_id}/edit")
def journal_edit(entry_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    entry = db.get(JournalEntry, entry_id)
    if not entry:
        return RedirectResponse("/")
    people = db.query(Person).filter(Person.archived.is_(False)).order_by(Person.name).all()
    return render(request, "journal_form.html", db=db, user=user, active="journal",
                  people=people, entry=entry, today=entry.entry_date.isoformat(),
                  preselect_person_id=None, scratchpad_person=None)


@router.post("/journal/{entry_id}/edit")
def journal_update(
    entry_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user),
    title: str = Form(""), body: str = Form(...), entry_date: str = Form(...),
    event_type: str = Form("note"), energy_cost: str = Form(""), location: str = Form(""),
    person_ids: list[int] = Form([]),
):
    entry = db.get(JournalEntry, entry_id)
    if not entry:
        return RedirectResponse("/")
    entry.title = title or None
    entry.body = body
    entry.entry_date = dt.date.fromisoformat(entry_date)
    entry.event_type = EventType(event_type) if event_type else EventType.note
    entry.energy_cost = EnergyCost(energy_cost) if energy_cost else None
    entry.location = location or None
    entry.people = [db.get(Person, pid) for pid in person_ids if db.get(Person, pid)]
    db.commit()
    if entry.people:
        return RedirectResponse(f"/people/{entry.people[0].id}", status_code=303)
    return RedirectResponse("/", status_code=303)


@router.post("/journal/{entry_id}/delete")
def journal_delete(entry_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    entry = db.get(JournalEntry, entry_id)
    person_id = entry.people[0].id if entry and entry.people else None
    if entry:
        db.delete(entry)
        db.commit()
    return RedirectResponse(f"/people/{person_id}" if person_id else "/", status_code=303)


@router.get("/journal/{entry_id}/suggestions")
def journal_suggestions(entry_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    entry = db.get(JournalEntry, entry_id)
    if not entry or not entry.ai_suggestions_json:
        return RedirectResponse("/")
    suggestions = json.loads(entry.ai_suggestions_json)
    return render(request, "journal_suggestions.html", db=db, user=user, active="journal",
                  entry=entry, suggestions=suggestions)


@router.post("/journal/{entry_id}/suggestions/apply")
def apply_suggestions(entry_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                       tags: list[str] = Form([]), notable_dates: list[str] = Form([])):
    entry = db.get(JournalEntry, entry_id)
    if not entry:
        return RedirectResponse("/")
    suggestions = json.loads(entry.ai_suggestions_json or "{}")

    for tag_name in tags:
        tag = db.query(Tag).filter(Tag.name == tag_name).first()
        if not tag:
            tag = Tag(name=tag_name)
            db.add(tag)
            db.flush()
        for p in entry.people:
            if tag not in p.tags:
                p.tags.append(tag)

    for nd_index in notable_dates:
        idx = int(nd_index)
        items = suggestions.get("notable_dates", [])
        if 0 <= idx < len(items):
            nd = items[idx]
            for p in entry.people:
                db.add(NotableDate(person_id=p.id, label=nd.get("label", "Notable date"),
                                    month=nd.get("month"), day=nd.get("day"), year=nd.get("year")))

    entry.ai_suggestions_json = None
    db.commit()
    person_id = entry.people[0].id if entry.people else None
    return RedirectResponse(f"/people/{person_id}" if person_id else "/", status_code=303)


@router.post("/journal/{entry_id}/suggestions/dismiss")
def dismiss_suggestions(entry_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    entry = db.get(JournalEntry, entry_id)
    if entry:
        person_id = entry.people[0].id if entry.people else None
        entry.ai_suggestions_json = None
        db.commit()
        return RedirectResponse(f"/people/{person_id}" if person_id else "/", status_code=303)
    return RedirectResponse("/", status_code=303)
