"""API v1 — push notification subscriptions."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import PushSubscription
from ...services import push as push_service
from .deps import get_current_api_user

router = APIRouter(prefix="/api/v1/push", tags=["push"])


class SubscribeRequest(BaseModel):
    endpoint: str
    keys: dict


@router.get("/vapid-key")
def vapid_key(db: Session = Depends(get_db)):
    return {"public_key": push_service.get_public_vapid_key(db)}


@router.post("/subscribe")
async def subscribe(body: SubscribeRequest, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    keys = body.keys or {}
    p256dh = (keys.get("p256dh") or "").strip()
    auth = (keys.get("auth") or "").strip()
    endpoint = body.endpoint.strip()
    if not endpoint or not p256dh or not auth:
        return JSONResponse({"error": "missing subscription details"}, status_code=400)
    existing = db.query(PushSubscription).filter_by(endpoint=endpoint).first()
    if existing:
        existing.p256dh = p256dh
        existing.auth = auth
        existing.user_id = user.id
    else:
        db.add(PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth, user_id=user.id))
    db.commit()
    return {"ok": True}


@router.post("/unsubscribe")
async def unsubscribe(body: dict, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    endpoint = (body.get("endpoint") or "").strip()
    if not endpoint:
        return JSONResponse({"error": "missing endpoint"}, status_code=400)
    for s in db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).all():
        db.delete(s)
    db.commit()
    return {"ok": True}


@router.post("/test")
def send_test(db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    vapid = push_service.ensure_vapid_keys(db)
    if not vapid:
        return JSONResponse({"error": "push not configured"}, status_code=400)
    subs = db.query(PushSubscription).all()
    if not subs:
        return JSONResponse({"error": "no subscriptions"}, status_code=400)
    sent = push_service.send_test(db)
    return {"ok": True, "sent": sent}
