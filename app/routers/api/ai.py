"""API v1 — AI features (bio, starters, quick replies, summary)."""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import Person
from ...services.ai_client import get_client_from_settings, build_person_context, AIError
from ...services import friend_rank
from .deps import get_current_api_user

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


def _journal_snippets(person: Person) -> list[str]:
    return [f"[{e.entry_date}] {e.title or ''} {e.body}".strip() for e in person.journal_entries]


@router.post("/people/{person_id}/bio")
def generate_bio(person_id: int, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    p = db.get(Person, person_id)
    if not p:
        raise HTTPException(status_code=404, detail="Person not found")
    try:
        ai = get_client_from_settings(db)
        if not ai:
            raise HTTPException(status_code=400, detail="AI not configured")
        bio = ai.bio_blurb(p.name, build_person_context(p))
        p.bio = bio
        db.commit()
        return {"bio": bio}
    except AIError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/people/{person_id}/starters")
def get_starters(person_id: int, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    p = db.get(Person, person_id)
    if not p:
        raise HTTPException(status_code=404, detail="Person not found")
    try:
        ai = get_client_from_settings(db)
        if not ai:
            raise HTTPException(status_code=400, detail="AI not configured")
        snippets = _journal_snippets(p)
        items = ai.conversation_starters(p.name, snippets, build_person_context(p))
        return {"starters": items}
    except AIError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/people/{person_id}/quick-replies")
def get_quick_replies(person_id: int, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    import datetime as dt
    p = db.get(Person, person_id)
    if not p:
        raise HTTPException(status_code=404, detail="Person not found")
    today = dt.date.today()
    days_since = (today - p.last_contact_date).days if p.last_contact_date else None
    try:
        ai = get_client_from_settings(db)
        if ai:
            snippets = _journal_snippets(p)
            context = build_person_context(p)
            replies = ai.icebreaker_scripts(p.name, context, snippets, days_since or 0)
            if replies:
                return {"replies": replies}
    except AIError:
        pass
    from ...services.replies import template_quick_replies
    replies = template_quick_replies(p, days_since)
    return {"replies": replies}


@router.post("/people/{person_id}/summary")
def generate_summary(person_id: int, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    p = db.get(Person, person_id)
    if not p:
        raise HTTPException(status_code=404, detail="Person not found")
    snippets = _journal_snippets(p)
    if not snippets:
        raise HTTPException(status_code=400, detail="No journal entries to summarize")
    try:
        ai = get_client_from_settings(db)
        if not ai:
            raise HTTPException(status_code=400, detail="AI not configured")
        summary = ai.profile_summary(p.name, snippets, build_person_context(p))
        p.ai_summary = summary
        db.commit()
        return {"summary": summary}
    except AIError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/people/{person_id}/gap-questions")
def get_gap_questions(person_id: int, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    p = db.get(Person, person_id)
    if not p:
        raise HTTPException(status_code=404, detail="Person not found")
    try:
        ai = get_client_from_settings(db)
        if not ai:
            raise HTTPException(status_code=400, detail="AI not configured")
        gaps = friend_rank.compute_friend_rank(p).get("gaps", [])
        items = ai.conversation_gap_questions(p.name, build_person_context(p), gaps)
        return {"questions": items}
    except AIError as e:
        raise HTTPException(status_code=500, detail=str(e))
