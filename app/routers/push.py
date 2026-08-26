"""Web Push subscription API - opt-in endpoints used by the PWA client (static/js/pwa.js).

These manage the browser's PushSubscription for the logged-in user. Everything is opt-in and
removable; nothing user-facing is stored beyond the endpoint/keys needed to send. The public
VAPID key endpoint is read-only and returns the key the client needs to subscribe.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import PushSubscription
from ..services import push as push_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/push", tags=["push"])


@router.get("/vapid-key")
def vapid_key(db: Session = Depends(get_db)):
    return {"public_key": push_service.get_public_vapid_key(db)}


@router.post("/test")
async def send_test(db: Session = Depends(get_db)):
    """Send a sample push to all subscriptions so the user can confirm notifications work
    (used by the 'Send a test notification' button in Settings)."""
    vapid = push_service.ensure_vapid_keys(db)
    if not vapid:
        logger.warning("Push test: VAPID keys unavailable")
        return JSONResponse({"error": "push not configured"}, status_code=400)
    subs = db.query(PushSubscription).all()
    logger.info("Push test: %d subscription(s)", len(subs))
    if not subs:
        return JSONResponse({"error": "no subscriptions - enable notifications on a device first"}, status_code=400)
    sent = push_service.send_test(db)
    logger.info("Push test: sent to %d subscription(s)", sent)
    return {"ok": True, "sent": sent}


@router.post("/subscribe")
async def subscribe(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return JSONResponse({"error": "not authenticated"}, status_code=401)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid body"}, status_code=400)

    endpoint = (data.get("endpoint") or "").strip()
    keys = data.get("keys") or {}
    p256dh = (keys.get("p256dh") or "").strip()
    auth = (keys.get("auth") or "").strip()
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
    logger.info("Push subscribe: saved subscription for user %s (endpoint %s…)", user.id, endpoint[:50])
    return {"ok": True}


@router.post("/unsubscribe")
async def unsubscribe(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
    except Exception:
        data = {}
    endpoint = (data.get("endpoint") or "").strip()
    if endpoint:
        subs = db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).all()
    else:
        return JSONResponse({"error": "missing endpoint"}, status_code=400)
    for s in subs:
        db.delete(s)
    db.commit()
    return {"ok": True}
