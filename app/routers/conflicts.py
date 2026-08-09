"""AuDHD-safe conflict resolution & implicit repair detection routes.

Design principle threaded through every route here: the user is ALWAYS in control. AI can only
ever suggest a resolution (see services/conflict_resolution.py) - every status change requires an
explicit human click, and "doing nothing" (Option D - Release) is treated as a first-class, fully
valid outcome, not a fallback.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import ConflictLog, ConflictStatus
from ..services import gamification

router = APIRouter()


@router.post("/people/{person_id}/conflicts")
def add_conflict(person_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                  summary: str = Form(...)):
    summary = summary.strip()
    if summary:
        db.add(ConflictLog(person_id=person_id, summary=summary, status=ConflictStatus.unresolved))
        db.commit()
    return RedirectResponse(f"/people/{person_id}", status_code=303)


@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict(conflict_id: int, request: Request, db: Session = Depends(get_db),
                      user=Depends(current_user), resolution_notes: str = Form("")):
    conflict = db.get(ConflictLog, conflict_id)
    if not conflict:
        return RedirectResponse("/", status_code=303)
    conflict.status = ConflictStatus.resolved
    conflict.resolved_at = dt.datetime.utcnow()
    conflict.resolution_notes = resolution_notes.strip() or None
    db.commit()

    gamification.award_and_flash(request, db, "CONFLICT_RESOLVED")
    request.session["notice_flash"] = "Marked resolved. Glad that one's settled. 🕊️"
    return RedirectResponse(f"/people/{conflict.person_id}", status_code=303)


@router.post("/conflicts/{conflict_id}/release")
def release_conflict(conflict_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    """Option D - "Letting This Go". A first-class, equally valid resolution path, not a
    fallback: choosing to release pressure around something is treated the same as an explicit
    repair for gamification/XP purposes."""
    conflict = db.get(ConflictLog, conflict_id)
    if not conflict:
        return RedirectResponse("/", status_code=303)
    conflict.status = ConflictStatus.released
    conflict.resolved_at = dt.datetime.utcnow()
    db.commit()

    gamification.award_and_flash(request, db, "CONFLICT_RESOLVED")
    request.session["notice_flash"] = "Closed. Choosing peace and releasing pressure is a valid path. 🕊️"
    return RedirectResponse(f"/people/{conflict.person_id}", status_code=303)


@router.post("/conflicts/{conflict_id}/dismiss-ai-suggestion")
def dismiss_ai_suggestion(conflict_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    """"Still Working on It" - hides the AI's suggestion banner without changing status, and
    without ever nagging about the same suggestion again (we keep `ai_suggested_resolution=True`
    so the detector skips this conflict in future checks; only the visible prompt is cleared)."""
    conflict = db.get(ConflictLog, conflict_id)
    if conflict:
        conflict.ai_suggested_prompt = None
        db.commit()
        return RedirectResponse(f"/people/{conflict.person_id}", status_code=303)
    return RedirectResponse("/", status_code=303)


@router.post("/conflicts/{conflict_id}/delete")
def delete_conflict(conflict_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    conflict = db.get(ConflictLog, conflict_id)
    if conflict:
        person_id = conflict.person_id
        db.delete(conflict)
        db.commit()
        return RedirectResponse(f"/people/{person_id}", status_code=303)
    return RedirectResponse("/", status_code=303)
