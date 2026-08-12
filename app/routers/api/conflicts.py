"""API v1 — conflict resolution."""
import json
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import Person, ConflictLog, ConflictStatus
from ...services.ai_client import get_support_client_from_settings, AIError
from .deps import get_current_api_user

router = APIRouter(prefix="/api/v1/conflicts", tags=["conflicts"])


class ConflictCreate(BaseModel):
    person_id: int
    summary: str


class ChatMessage(BaseModel):
    message: str


def _conflict_response(c: ConflictLog) -> dict:
    return {
        "id": c.id,
        "person_id": c.person_id,
        "person_name": c.person.name if c.person else None,
        "summary": c.summary,
        "status": c.status.value,
        "resolution_notes": c.resolution_notes,
        "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "plan_generated_at": c.plan_generated_at.isoformat() if c.plan_generated_at else None,
        "resolution_plan": json.loads(c.resolution_plan_json) if c.resolution_plan_json else None,
    }


@router.get("")
def list_conflicts(db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    conflicts = db.query(ConflictLog).order_by(ConflictLog.created_at.desc()).all()
    return [_conflict_response(c) for c in conflicts]


@router.post("", status_code=201)
def create_conflict(body: ConflictCreate, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    p = db.get(Person, body.person_id)
    if not p:
        raise HTTPException(status_code=404, detail="Person not found")
    c = ConflictLog(person_id=p.id, summary=body.summary, status=ConflictStatus.unresolved)
    db.add(c)
    db.commit()
    db.refresh(c)
    return _conflict_response(c)


@router.get("/{conflict_id}")
def get_conflict(conflict_id: int, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    c = db.get(ConflictLog, conflict_id)
    if not c:
        raise HTTPException(status_code=404, detail="Conflict not found")
    return _conflict_response(c)


@router.get("/{conflict_id}/chat")
def get_chat(conflict_id: int, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    c = db.get(ConflictLog, conflict_id)
    if not c:
        raise HTTPException(status_code=404, detail="Conflict not found")
    msgs = sorted(c.chat_messages or [], key=lambda m: m.created_at or "")
    return [
        {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat() if m.created_at else None}
        for m in msgs
    ]


@router.post("/{conflict_id}/chat")
async def send_chat(conflict_id: int, body: ChatMessage, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    c = db.get(ConflictLog, conflict_id)
    if not c:
        raise HTTPException(status_code=404, detail="Conflict not found")
    try:
        ai = get_support_client_from_settings(db)
        if not ai:
            raise HTTPException(status_code=400, detail="AI support chat not configured")
    except Exception:
        raise HTTPException(status_code=400, detail="AI support chat not configured")
    from ...models import ConflictChatMessage
    db.add(ConflictChatMessage(conflict_id=c.id, role="user", content=body.message))
    db.commit()
    messages = [{"role": m.role, "content": m.content} for m in sorted(c.chat_messages, key=lambda m: m.created_at or "")]
    return StreamingResponse(
        _stream_chat(ai, c, db, messages),
        media_type="text/event-stream",
    )


async def _stream_chat(ai, conflict, db, messages):
    import json as _json
    try:
        full = ""
        for delta in ai.support_chat(messages):
            full += delta
            yield f"data: {_json.dumps({'delta': delta})}\n\n"
        from ...models import ConflictChatMessage
        db.add(ConflictChatMessage(conflict_id=conflict.id, role="assistant", content=full))
        db.commit()
        yield f"data: {_json.dumps({'done': True})}\n\n"
    except Exception as e:
        yield f"data: {_json.dumps({'error': str(e), 'done': True})}\n\n"


@router.put("/{conflict_id}/resolve")
def resolve_conflict(conflict_id: int, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    c = db.get(ConflictLog, conflict_id)
    if not c:
        raise HTTPException(status_code=404, detail="Conflict not found")
    c.status = ConflictStatus.resolved
    db.commit()
    return _conflict_response(c)
