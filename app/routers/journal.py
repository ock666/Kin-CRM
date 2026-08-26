import datetime as dt
import json

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Form, Query, UploadFile, File
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import JournalEntry, JournalImage, Person, EventType, EnergyCost, Tag, NotableDate, ScratchpadItem
from ..render import render
from ..services import checkins as checkin_service
from ..services import gamification
from ..services.ai_client import get_client_from_settings as ai_from_settings, AIError
from ..services.hangouts import invalidate_hangout_cache

router = APIRouter()


def _safe_date(value: str) -> dt.date | None:
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


def _process_ai_extraction(entry_id: int):
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        entry = db.get(JournalEntry, entry_id)
        if not entry or not entry.people:
            return
        ai = ai_from_settings(db)
        if ai:
            names = ", ".join(p.name for p in entry.people)
            suggestions = ai.extract_facts(names, entry.body)
            if suggestions:
                entry.ai_suggestions_json = json.dumps(suggestions)
                entry.ai_processed = True
                db.commit()
    except (AIError, Exception):
        pass
    finally:
        db.close()


@router.post("/journal/transcribe")
async def journal_transcribe(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(current_user),
    audio_file: UploadFile = File(...),
):
    """Accept an uploaded audio file and return a JSON transcription using a configured
    Whisper provider (OpenAI-compatible or local ASR webservice). Falls back to AI settings
    if dedicated Whisper settings are not provided.
    """
    if not user:
        return RedirectResponse("/login")
    try:
        from ..services.whisper_client import transcribe_from_settings, WhisperError
        import io

        # Basic content-type and size guards (defense-in-depth; UI already restricts)
        ctype = (audio_file.content_type or "").lower()
        if not ctype.startswith("audio/"):
            return JSONResponse({"error": "Please upload an audio file."}, status_code=400)

        raw = await audio_file.read()
        max_bytes = 25 * 1024 * 1024  # 25 MB
        if raw and len(raw) > max_bytes:
            return JSONResponse({"error": "Audio too large (limit 25 MB)."}, status_code=413)
        text = transcribe_from_settings(db, io.BytesIO(raw), audio_file.filename or "audio")
        return JSONResponse({"text": text})
    except WhisperError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception:
        return JSONResponse({"error": "Transcription failed. Check Whisper settings and container."}, status_code=502)


@router.get("/journal/new")
def journal_new(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                 person_id: int | None = Query(None), event_type: str | None = Query(None),
                 entry_date: str | None = Query(None), immich_asset_ids: list[str] = Query([])):
    if not user:
        return RedirectResponse("/login")
    people = db.query(Person).filter(Person.archived.is_(False)).order_by(Person.name).all()
    scratchpad_person = db.get(Person, person_id) if person_id else None
    return render(request, "journal_form.html", db=db, user=user, active="journal",
                  people=people, preselect_person_id=person_id, preselect_event_type=event_type,
                  preselect_entry_date=entry_date, preselect_asset_ids=immich_asset_ids,
                  today=dt.date.today().isoformat(),
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
    request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db),
    user=Depends(current_user),
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
        entry_date=_safe_date(entry_date) or dt.date.today(),
        event_type=_safe_enum(EventType, event_type, EventType.note),
        energy_cost=_safe_enum(EnergyCost, energy_cost, None),
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

    # Gamification hook (pure Python, no AI calls) - reward logging a note, plus a bigger
    # bonus if a photo was attached. Never blocks/slows the actual save above. Context carries
    # a few event-specific details a handful of achievement checks need (see gamification.py).
    events = ["NOTE_ADDED"]
    if immich_asset_ids:
        events.append("PHOTO_ATTACHED")
        # The hangout card caches detection for up to 15 min; a photo attached via the normal
        # form should stop it offering "Quick log" for the same photo immediately.
        invalidate_hangout_cache()

    entry_created_at = entry.created_at or dt.datetime.utcnow()
    years_back = entry_created_at.date().year - entry.entry_date.year
    matches_birthday = any(
        p.birthday_month == entry.entry_date.month and p.birthday_day == entry.entry_date.day
        for p in entry.people
    )
    context = {
        "entry_people_count": len(entry.people),
        "entry_word_count": len(entry.body.split()),
        "entry_hour": entry_created_at.hour,
        "entry_matches_birthday": matches_birthday,
        "entry_years_back": years_back,
        "entry_is_new_year": (entry.entry_date.month, entry.entry_date.day) in {(12, 31), (1, 1)},
    }
    gamification.award_and_flash(request, db, *events, context=context)

    background_tasks.add_task(_process_ai_extraction, entry.id)

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
    entry.entry_date = _safe_date(entry_date) or dt.date.today()
    entry.event_type = _safe_enum(EventType, event_type, EventType.note)
    entry.energy_cost = _safe_enum(EnergyCost, energy_cost, None)
    entry.location = location or None
    entry.people = [p for pid in person_ids if (p := db.get(Person, pid))]
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
                       tags: list[str] = Form([]), notable_dates: list[str] = Form([]),
                       follow_ups: list[str] = Form([])):
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

    for fu_index in follow_ups:
        idx = int(fu_index)
        items = suggestions.get("follow_ups", [])
        if 0 <= idx < len(items):
            for p in entry.people:
                db.add(ScratchpadItem(person_id=p.id, text=items[idx]))

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
