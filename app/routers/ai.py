from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import Person
from ..render import render
from ..services.ai_client import get_client_from_settings, build_person_context, AIError

router = APIRouter(prefix="/ai", tags=["ai"])


def _journal_snippets(person: Person) -> list[str]:
    return [f"[{e.entry_date}] {e.title or ''} {e.body}".strip() for e in person.journal_entries]


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
