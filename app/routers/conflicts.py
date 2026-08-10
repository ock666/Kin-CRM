"""AuDHD-safe conflict resolution & AI-assisted approach suggestions.

Design principle threaded through every route here: the user is ALWAYS in control. AI only ever
*suggests* things to try (see services/conflict_resolution.py) - available immediately, with no
waiting period - every status change requires an explicit human click, and "doing nothing"
(Option D - Release) is treated as a first-class, fully valid outcome, not a fallback.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import ConflictLog, ConflictStatus, utcnow
from ..services import conflict_resolution, gamification
from ..services.ai_client import get_client_from_settings as ai_from_settings, AIError

router = APIRouter()


@router.post("/people/{person_id}/conflicts")
def add_conflict(person_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                  summary: str = Form(...)):
    summary = summary.strip()
    if not summary:
        return RedirectResponse(f"/people/{person_id}", status_code=303)

    conflict = ConflictLog(person_id=person_id, summary=summary, status=ConflictStatus.unresolved)
    db.add(conflict)
    db.commit()

    # Generate conflict-specific approach suggestions right away, if AI is configured - available
    # immediately, no waiting period, no requirement to interact with the person first. Falls
    # back gracefully to generic scripts in the template if this isn't configured or fails.
    try:
        ai = ai_from_settings(db)
        if ai:
            conflict_resolution.generate_approach_suggestions(db, ai, conflict, conflict.person)
    except AIError:
        pass

    return RedirectResponse(f"/people/{person_id}", status_code=303)


@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict(conflict_id: int, request: Request, db: Session = Depends(get_db),
                      user=Depends(current_user), resolution_notes: str = Form("")):
    conflict = db.get(ConflictLog, conflict_id)
    if not conflict:
        return RedirectResponse("/", status_code=303)
    conflict.status = ConflictStatus.resolved
    conflict.resolved_at = utcnow()
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
    conflict.resolved_at = utcnow()
    db.commit()

    gamification.award_and_flash(request, db, "CONFLICT_RESOLVED")
    request.session["notice_flash"] = "Closed. Choosing peace and releasing pressure is a valid path. 🕊️"
    return RedirectResponse(f"/people/{conflict.person_id}", status_code=303)


@router.post("/conflicts/{conflict_id}/dismiss-reminder")
def dismiss_reminder(conflict_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    """Quietly hides this conflict from the dashboard's gentle reminder list without resolving or
    releasing it - it still shows on the person's own profile either way, ready whenever."""
    conflict = db.get(ConflictLog, conflict_id)
    if conflict:
        conflict.reminder_dismissed = True
        db.commit()
    return RedirectResponse("/", status_code=303)


@router.post("/conflicts/{conflict_id}/generate-approach")
def generate_approach(conflict_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    """Manually (re)generate the AI's conflict-specific approach suggestions - used both for the
    first generation (if AI wasn't configured yet when the conflict was logged) and for "try
    different suggestions" if the first pass doesn't feel right."""
    conflict = db.get(ConflictLog, conflict_id)
    if not conflict:
        return RedirectResponse("/", status_code=303)
    try:
        ai = ai_from_settings(db)
        if ai:
            conflict_resolution.generate_approach_suggestions(db, ai, conflict, conflict.person)
        else:
            request.session["notice_flash"] = "Add an AI provider in Settings to get personalized suggestions."
    except AIError:
        request.session["notice_flash"] = "Couldn't generate suggestions right now - the generic scripts below still work fine."
    return RedirectResponse(f"/people/{conflict.person_id}", status_code=303)


@router.post("/conflicts/{conflict_id}/delete")
def delete_conflict(conflict_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    conflict = db.get(ConflictLog, conflict_id)
    if conflict:
        person_id = conflict.person_id
        db.delete(conflict)
        db.commit()
        return RedirectResponse(f"/people/{person_id}", status_code=303)
    return RedirectResponse("/", status_code=303)
