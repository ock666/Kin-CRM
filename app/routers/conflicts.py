"""AuDHD-safe conflict resolution & AI-assisted approach suggestions.

Design principle threaded through every route here: the user is ALWAYS in control. AI only ever
*suggests* things to try (see services/conflict_resolution.py) - available immediately, with no
waiting period - every status change requires an explicit human click, and "doing nothing"
(Option D - Release) is treated as a first-class, fully valid outcome, not a fallback.
"""
from __future__ import annotations

import datetime as dt
import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi import UploadFile, File
from fastapi.responses import RedirectResponse, StreamingResponse, JSONResponse, FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import ConflictLog, ConflictChatMessage, ConflictStatus, JournalEntry, EventType, utcnow
from ..services import conflict_resolution, gamification
from ..services.ai_client import (
    get_client_from_settings as ai_from_settings,
    get_support_client_from_settings as support_ai_from_settings,
    AIError,
)

router = APIRouter()


def _retention_expired(db: Session, conflict: ConflictLog, today: dt.datetime | None = None) -> bool:
    if not conflict.chat_messages:
        return False
    from ..settings_store import get_setting
    try:
        days = int(get_setting(db, "chat_retention_days", "14") or 14)
    except ValueError:
        days = 14
    now = today if today else dt.datetime.utcnow()
    last = conflict.chat_messages[-1]
    if last.created_at and last.created_at < now - dt.timedelta(days=days):
        return True
    return False


def _build_support_system_prompt(conflict_summary: str, person_name: str,
                                  relationship_context: str = "") -> str:
    return (
        "You are a calm, warm, non-judgmental support worker / counsellor (support worker, "
        "mental-health-nurse-adjacent, psychologist) for someone with AuDHD (Autism/ADHD), "
        "Rejection Sensitive Dysphoria (RSD), and social anxiety.\n\n"
        "Your role is to help the user work through the feelings about a specific interpersonal "
        "conflict and arrive at a clear, logical understanding of the situation.\n\n"
        "Guidelines:\n"
        "- Validate first — acknowledge their feelings unconditionally.\n"
        "- Never assign blame to either party unless the user clearly states who did what.\n"
        "- Never pressure them to act; there is no urgency and no wrong answer.\n"
        "- Never invalidate or minimize their emotional response.\n"
        "- Gently challenge catastrophic or RSD-driven interpretations with curiosity rather "
        "than correction — e.g. 'What would you tell a friend in this situation?' or 'Is "
        "there another way to read what happened?'\n"
        "- Help them separate observable facts from the story anxiety is telling them about "
        "what it means.\n"
        "- Help them reach their own conclusions about what, if anything, they want to do.\n"
        "- Keep responses concise, grounded, and concrete — no long paragraphs or lectures.\n"
        "- The tone is warm peer-support, not clinical or diagnostic.\n"
        "- If the user seems to be in genuine crisis, gently encourage reaching out to a real "
        "person or a crisis line — but never as the first or only response.\n\n"
        "Important: You are not a licensed therapist or doctor. This is an AI support chat, "
        f"not a substitute for professional mental health care.\n\n"
        f"The specific situation:\n"
        f"Person: {person_name}\n"
        f"What happened (in the user's own words): {conflict_summary}\n"
        f"Additional relationship context: {relationship_context or 'Not available'}"
    )


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

    gamification.award_and_flash(request, db, "CONFLICT_RELEASED")
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


@router.get("/conflicts/{conflict_id}/chat")
def get_chat_messages(conflict_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    conflict = db.get(ConflictLog, conflict_id)
    if not conflict:
        return JSONResponse({"error": "not found"}, status_code=404)
    if _retention_expired(db, conflict):
        return JSONResponse({"retention_expired": True, "messages": []})
    msgs = (
        db.query(ConflictChatMessage)
        .filter_by(conflict_id=conflict_id)
        .order_by(ConflictChatMessage.created_at)
        .all()
    )
    return JSONResponse([{
        "role": m.role,
        "content": m.content,
        "audio_url": m.audio_url,
        "transcript": m.transcript,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    } for m in msgs])


@router.post("/conflicts/{conflict_id}/chat")
async def conflict_chat(conflict_id: int, request: Request, db: Session = Depends(get_db),
                         user=Depends(current_user)):
    conflict = db.get(ConflictLog, conflict_id)
    if not conflict:
        return JSONResponse({"error": "not found"}, status_code=404)

    body = await request.json()
    message = (body.get("message") or "").strip()

    if _retention_expired(db, conflict):
        return JSONResponse({"error": "chat_archived", "message": "This conversation is water under the bridge — archived."}, status_code=410)

    person_name = conflict.person.name if conflict.person else "someone"
    relation_ctx = conflict_resolution.build_relationship_context(conflict.person) if conflict.person else ""
    system = _build_support_system_prompt(conflict.summary, person_name, relation_ctx)

    prior = (
        db.query(ConflictChatMessage)
        .filter_by(conflict_id=conflict_id)
        .order_by(ConflictChatMessage.created_at)
        .all()
    )

    messages: list[dict] = [{"role": "system", "content": system}]
    for m in prior:
        messages.append({"role": m.role, "content": m.content})

    if message and message != "__open__":
        user_msg = ConflictChatMessage(conflict_id=conflict_id, role="user", content=message)
        db.add(user_msg)
        db.commit()
        messages.append({"role": "user", "content": message})
    elif not prior:
        messages.append({
            "role": "user",
            "content": f"I'm here to talk about what happened with {person_name}.",
        })

    ai = support_ai_from_settings(db)
    if not ai:
        return JSONResponse(
            {"error": "AI isn't configured yet. Add an API key and set a support chat model in Settings."},
            status_code=400,
        )

    from ..database import SessionLocal

    def generate():
        full: list[str] = []
        try:
            for delta in ai.support_chat(messages):
                full.append(delta)
                yield f"data: {json.dumps({'delta': delta})}\n\n"

            reply = "".join(full).strip()
            if reply:
                db2 = SessionLocal()
                try:
                    msg = ConflictChatMessage(conflict_id=conflict_id, role="assistant", content=reply)
                    db2.add(msg)
                    db2.commit()
                    # Attempt voice synth if enabled; ignore failures silently
                    try:
                        from ..services.tts_client import synthesize_from_settings, should_reply_with_voice
                        reply_default, mirror_mode = should_reply_with_voice(db2)
                        do_voice = reply_default
                        if mirror_mode and prior:
                            do_voice = do_voice or any((pm.audio_url for pm in prior if pm.role == 'user'))
                        if do_voice:
                            audio_bytes = synthesize_from_settings(db2, reply)
                            from ..config import settings as app_settings
                            import uuid, os
                            voice_dir = app_settings.UPLOAD_DIR / "voice"
                            voice_dir.mkdir(parents=True, exist_ok=True)
                            fname = f"bot_{uuid.uuid4().hex}.mp3"
                            fpath = voice_dir / fname
                            fpath.write_bytes(audio_bytes)
                            msg.audio_url = f"/uploads/voice/{fname}"
                            msg.transcript = reply
                            db2.commit()
                            yield f"data: {json.dumps({'audio_url': msg.audio_url})}\n\n"
                    except Exception:
                        pass
                finally:
                    db2.close()

            yield f"data: {json.dumps({'done': True})}\n\n"
        except AIError as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/conflicts/{conflict_id}/chat/voice")
async def conflict_chat_voice(conflict_id: int, db: Session = Depends(get_db), user=Depends(current_user),
                              audio_file: UploadFile = File(...)):
    conflict = db.get(ConflictLog, conflict_id)
    if not conflict:
        return JSONResponse({"error": "not found"}, status_code=404)
    if audio_file.content_type and not audio_file.content_type.startswith("audio/"):
        return JSONResponse({"error": "Please upload an audio file."}, status_code=400)
    raw = await audio_file.read()
    if len(raw) > 25 * 1024 * 1024:
        return JSONResponse({"error": "Audio too large (limit 25 MB)."}, status_code=413)
    # Save user audio to uploads/voice (keep original container type)
    from ..config import settings as app_settings
    import uuid, os
    voice_dir = app_settings.UPLOAD_DIR / "voice"
    voice_dir.mkdir(parents=True, exist_ok=True)
    ext = os.path.splitext(audio_file.filename or "voice")[1] or ".webm"
    fname = f"user_{uuid.uuid4().hex}{ext}"
    fpath = voice_dir / fname
    fpath.write_bytes(raw)
    audio_url = f"/uploads/voice/{fname}"

    # Transcribe
    from ..services.whisper_client import transcribe_from_settings, WhisperError
    import io as _io
    try:
        text = transcribe_from_settings(db, _io.BytesIO(raw), audio_file.filename or "audio")
    except WhisperError as e:
        text = ""

    # Record user message (with audio + transcript)
    msg = ConflictChatMessage(conflict_id=conflict_id, role="user", content=(text or "(voice note)"),
                              audio_url=audio_url, transcript=text or None)
    db.add(msg)
    db.commit()
    return JSONResponse({"ok": True, "text": text or "", "audio_url": audio_url})


@router.get("/uploads/voice/{filename}")
def serve_voice_upload(filename: str, db: Session = Depends(get_db), user=Depends(current_user)):
    # Auth-gated simple file server for voice uploads
    from ..config import settings as app_settings
    fpath = app_settings.UPLOAD_DIR / "voice" / filename
    if not fpath.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(str(fpath))


@router.post("/conflicts/{conflict_id}/chat/insight")
async def chat_insight(conflict_id: int, request: Request, db: Session = Depends(get_db),
                        user=Depends(current_user)):
    conflict = db.get(ConflictLog, conflict_id)
    if not conflict:
        return JSONResponse({"error": "not found"}, status_code=404)
    if _retention_expired(db, conflict):
        return JSONResponse({"error": "chat_archived"}, status_code=410)
    messages = (
        db.query(ConflictChatMessage)
        .filter_by(conflict_id=conflict_id)
        .order_by(ConflictChatMessage.created_at)
        .all()
    )
    if not messages:
        return JSONResponse({"error": "no messages yet"}, status_code=400)
    ai = support_ai_from_settings(db)
    if not ai:
        return JSONResponse({"error": "AI not configured"}, status_code=400)
    try:
        insight = ai.chat_insight([{"role": m.role, "content": m.content} for m in messages])
        return JSONResponse({"insight": insight})
    except AIError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/conflicts/{conflict_id}/chat/insight/save")
async def save_chat_insight(conflict_id: int, request: Request, db: Session = Depends(get_db),
                             user=Depends(current_user)):
    conflict = db.get(ConflictLog, conflict_id)
    if not conflict:
        return JSONResponse({"error": "not found"}, status_code=404)
    body = await request.json()
    text = (body.get("insight") or "").strip()
    if not text:
        return JSONResponse({"error": "empty insight"}, status_code=400)
    entry = JournalEntry(
        author_user_id=user.id if user else None,
        body=text,
        event_type=EventType.note,
        source="ai",
    )
    entry.people.append(conflict.person)
    db.add(entry)
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/conflicts/{conflict_id}/plan/generate")
def generate_plan(conflict_id: int, request: Request, db: Session = Depends(get_db),
                   user=Depends(current_user)):
    from ..services import resolution_plans as plan_service
    ok = plan_service.generate_plan_for_conflict(db, conflict_id)
    conflict = db.get(ConflictLog, conflict_id)
    pid = conflict.person_id if conflict else None
    if ok:
        request.session["notice_flash"] = "Resolution plan ready. 📋"
    else:
        request.session["notice_flash"] = "Couldn't generate a plan yet — ensure AI is configured and the chat has been idle for a bit."
    return RedirectResponse(f"/people/{pid}" if pid else "/", status_code=303)


@router.post("/conflicts/{conflict_id}/chat/clear")
def clear_chat(conflict_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    conflict = db.get(ConflictLog, conflict_id)
    if conflict:
        db.query(ConflictChatMessage).filter_by(conflict_id=conflict_id).delete()
        db.commit()
        return JSONResponse({"ok": True})
    return JSONResponse({"error": "not found"}, status_code=404)
