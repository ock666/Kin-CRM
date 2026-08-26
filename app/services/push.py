"""Web Push notifications for Kin's PWA.

Design: calm, opt-in, never nagging. Notifications are only sent to browsers the user
explicitly enabled notifications on, and only for the triggers they selected (birthdays,
overdue cadence). Messages are AGGREGATED - e.g. one "3 people could use a nudge" instead of
three separate noisy pings. Sending is a total no-op if no VAPID keys or no subscriptions
exist, so everything degrades gracefully whether or not push is configured.

Push is delivered by the browser's push service when the app is NOT open in a focused tab;
the served page (static/sw.js) decides whether to surface the notification based on focus.
The server always sends - the client decides. Live in-app surfacing is handled separately
via the existing gamification-style toasts on the pages themselves.
"""
from __future__ import annotations

import base64
import json
import logging
import os

from cryptography.hazmat.primitives import serialization
from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session

from ..models import PushSubscription
from ..settings_store import get_setting, set_setting
from . import birthdays, checkins
from . import grace as grace_service

logger = logging.getLogger(__name__)

# VAPID 'sub' claim — identifies the push sender to the browser's push service. Must be a
# mailto: or https: URL. Override with the VAPID_SUBJECT env var if your push service rejects
# the default (some services want a real reachable address).
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:kin@localhost")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def ensure_vapid_keys(db: Session) -> dict | None:
    """Return {public_key, private_key}. Generates and persists a VAPID keypair (public =
    base64url uncompressed point; private = base64url of the 32-byte EC scalar) on first use.
    Returns None if generation fails (push then stays disabled)."""
    public_key = get_setting(db, "vapid_public_key")
    private_key = get_setting(db, "vapid_private_key")
    if public_key and private_key:
        return {"public_key": public_key, "private_key": private_key}

    try:
        from py_vapid import Vapid01
        v = Vapid01()
        v.generate_keys()
        pub = v.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        scalar = v.private_key.private_numbers().private_value.to_bytes(32, "big")
    except Exception as e:
        logger.warning("Could not generate VAPID keys: %s", e)
        return None

    public_b64 = _b64url(pub)
    private_b64 = _b64url(scalar)
    set_setting(db, "vapid_public_key", public_b64)
    set_setting(db, "vapid_private_key", private_b64)
    return {"public_key": public_b64, "private_key": private_b64}


def get_public_vapid_key(db: Session) -> str:
    keys = ensure_vapid_keys(db)
    return keys["public_key"] if keys else ""


def _send(sub: PushSubscription, payload: dict, vapid: dict) -> bool | str:
    """Send one push. Returns True on success, "gone" if the subscription is dead (404/410),
    or False on other failures - never raises."""
    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=json.dumps(payload),  # sw.js event.data.json() parses this
            vapid_private_key=vapid["private_key"],
            vapid_claims={"sub": VAPID_SUBJECT},
            ttl=0,
        )
        return True
    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        if status in (404, 410):
            return "gone"
        logger.warning("Push failed for %s: %s", sub.endpoint[:40], e)
        return False


def _build_messages(db: Session) -> list[dict]:
    """Aggregate due notifications into a small list of quiet message dicts, honoring the
    user's per-trigger preferences (push_birthdays / push_cadence)."""
    messages = []

    if get_setting(db, "push_birthdays", "1") != "0":
        try:
            lead_days = int(get_setting(db, "birthday_lead_days", "3") or 3)
        except ValueError:
            lead_days = 3
        upcoming = birthdays.people_with_upcoming_birthdays(db, lead_days)
        if upcoming:
            names = ", ".join(p.name for p, _ in upcoming[:3])
            more = f" and {len(upcoming) - 3} more" if len(upcoming) > 3 else ""
            verb = "has" if len(upcoming) == 1 else "have"
            messages.append({
                "title": "A birthday is coming up",
                "body": f"{names}{more} {verb} a birthday soon 🎂",
                "url": "/",
                "tag": "birthdays",
            })

    if get_setting(db, "push_cadence", "1") != "0":
        overdue = checkins.overdue_people(db)
        if overdue:
            by_days = sorted(overdue, key=lambda t: -t[1])[:5]
            names = ", ".join(p.name for p, _ in by_days)
            more = f" and {len(overdue) - 5} more" if len(overdue) > 5 else ""
            messages.append({
                "title": "Gentle nudge",
                "body": f"💧 {names}{more} could use a hello when you feel up to it. No rush.",
                "url": "/people",
                "tag": "cadence",
            })

    return messages


def send_test(db: Session) -> int:
    """Send a single test notification to all subscriptions. Returns count sent."""
    vapid = ensure_vapid_keys(db)
    if not vapid:
        return 0
    subs = db.query(PushSubscription).all()
    payload = {
        "title": "Kin test",
        "body": "Notifications are working 🎉 You can turn these off in Settings anytime.",
        "url": "/",
        "tag": "test",
    }
    sent = 0
    for sub in list(subs):
        result = _send(sub, payload, vapid)
        if result == "gone":
            db.delete(sub)
            try:
                db.commit()
            except Exception:
                db.rollback()
        elif result:
            sent += 1
    return sent


def send_push_notifications(db: Session) -> int:
    """Send aggregated push notifications to all opted-in subscriptions. Returns the number of
    subscriptions successfully notified, or 0 if push isn't configured / disabled / nothing to
    send. Never raises - failures are logged and dead subscriptions are pruned. Silence applies
    during grace mode (stepping back) so the user gets a true break."""
    if get_setting(db, "push_enabled", "0") == "0":
        return 0
    if grace_service.is_grace_active(db):
        return 0
    vapid = ensure_vapid_keys(db)
    if not vapid:
        return 0
    subs = db.query(PushSubscription).all()
    if not subs:
        return 0
    messages = _build_messages(db)
    if not messages:
        return 0

    sent = 0
    for msg in messages:
        for sub in list(subs):
            result = _send(sub, msg, vapid)
            if result == "gone":
                db.delete(sub)
                try:
                    db.commit()
                except Exception:
                    db.rollback()
            elif result:
                sent += 1
    return sent
