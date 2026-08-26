import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import Person
from ..render import render
from ..services.ai_client import get_client_from_settings, build_person_context, AIError
from ..services import friend_rank

router = APIRouter(prefix="/ai", tags=["ai"])


def _journal_snippets(person: Person) -> list[str]:
    return [f"[{e.entry_date}] {e.title or ''} {e.body}".strip() for e in person.journal_entries]


@router.post("/people/{person_id}/bio")
def generate_bio(person_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    person = db.get(Person, person_id)
    if not person:
        return render(request, "partials/ai_text.html", db=db, user=user, text=None,
                      error="Person not found.")
    try:
        ai = get_client_from_settings(db)
        if not ai:
            return render(request, "partials/ai_text.html", db=db, user=user, text=None,
                          error="AI isn't configured yet. Add an API key in Settings.")
        bio = ai.bio_blurb(person.name, build_person_context(person))
        person.bio = bio
        db.commit()
        return render(request, "partials/ai_text.html", db=db, user=user, text=bio, error=None)
    except AIError as e:
        return render(request, "partials/ai_text.html", db=db, user=user, text=None, error=str(e))


@router.post("/people/{person_id}/gap-questions")
def generate_gap_questions(person_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    person = db.get(Person, person_id)
    if not person:
        return render(request, "partials/ai_gap_questions.html", db=db, user=user, items=[],
                      person_id=person_id, error="Person not found.")
    try:
        ai = get_client_from_settings(db)
        if not ai:
            return render(request, "partials/ai_gap_questions.html", db=db, user=user, items=[],
                          person_id=person_id,
                          error="AI isn't configured yet. Add an API key in Settings.")
        gaps = friend_rank.compute_friend_rank(person).get("gaps", [])
        items = ai.conversation_gap_questions(person.name, build_person_context(person), gaps)
        person.ai_starters_json = json.dumps(items)
        db.commit()
        return render(request, "partials/ai_gap_questions.html", db=db, user=user, items=items,
                      person_id=person_id, error=None)
    except AIError as e:
        return render(request, "partials/ai_gap_questions.html", db=db, user=user, items=[],
                      person_id=person_id, error=str(e))


@router.post("/people/{person_id}/summary")
def generate_summary(person_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    person = db.get(Person, person_id)
    if not person:
        return render(request, "partials/ai_text.html", db=db, user=user, text=None,
                      error="Person not found.")
    try:
        ai = get_client_from_settings(db)
        if not ai:
            return render(request, "partials/ai_text.html", db=db, user=user, text=None,
                          error="AI isn't configured yet. Add an API key in Settings.")
        snippets = _journal_snippets(person)
        if not snippets:
            return render(request, "partials/ai_text.html", db=db, user=user, text=None,
                          error="Add a few journal entries first so there's something to summarize.")
        summary = ai.profile_summary(person.name, snippets, build_person_context(person))
        person.ai_summary = summary
        db.commit()
        return render(request, "partials/ai_text.html", db=db, user=user, text=summary, error=None)
    except AIError as e:
        return render(request, "partials/ai_text.html", db=db, user=user, text=None, error=str(e))


@router.get("/people/{person_id}/starters")
def conversation_starters(person_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    person = db.get(Person, person_id)
    if not person:
        return render(request, "partials/ai_list.html", db=db, user=user, items=[], error="Person not found.")
    try:
        ai = get_client_from_settings(db)
        if not ai:
            return render(request, "partials/ai_list.html", db=db, user=user, items=[],
                          error="AI isn't configured yet. Add an API key in Settings.")
        snippets = _journal_snippets(person)
        items = ai.conversation_starters(person.name, snippets, build_person_context(person))
        return render(request, "partials/ai_list.html", db=db, user=user, items=items, error=None)
    except AIError as e:
        return render(request, "partials/ai_list.html", db=db, user=user, items=[], error=str(e))


@router.get("/people/{person_id}/quick-replies")
def quick_replies(person_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    person = db.get(Person, person_id)
    if not person:
        return render(request, "partials/quick_replies.html", db=db, user=user, replies=[],
                      error="Person not found.")

    import datetime as dt
    today = dt.date.today()
    days_since = None
    if person.last_contact_date:
        days_since = (today - person.last_contact_date).days

    try:
        ai = get_client_from_settings(db)
        if ai:
            snippets = _journal_snippets(person)
            context = build_person_context(person)
            replies = ai.icebreaker_scripts(person.name, context, snippets, days_since or 0)
            if replies:
                return render(request, "partials/quick_replies.html", db=db, user=user,
                              replies=replies, error=None)
    except AIError:
        pass

    from ..services.replies import template_quick_replies
    replies = template_quick_replies(person, days_since)
    return render(request, "partials/quick_replies.html", db=db, user=user, replies=replies, error=None)
