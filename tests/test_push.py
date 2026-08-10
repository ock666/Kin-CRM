"""Tests for the Web Push service - key generation, message aggregation, and the
calm/no-op behavior. Actual HTTP delivery to a push service is NOT tested (no network);
we test everything up to and including message construction."
"""
import datetime as dt

from app.models import Person, PushSubscription
from app.services import push as push_service


def make_person(db, **kwargs):
    p = Person(**kwargs)
    db.add(p)
    db.commit()
    return p


def test_vapid_keys_generated_and_persisted(app):
    from app.database import SessionLocal
    from app.settings_store import get_setting, set_setting
    db = SessionLocal()
    try:
        keys = push_service.ensure_vapid_keys(db)
        assert keys is not None
        assert keys["public_key"] and keys["private_key"]
        # Persisted - a second call returns the same keys, no regeneration.
        keys2 = push_service.ensure_vapid_keys(db)
        assert keys2 == keys
        assert get_setting(db, "vapid_public_key") == keys["public_key"]
    finally:
        db.close()


def test_build_messages_birthday(caplog, app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        bday = make_person(
            db, name="Dana", archived=False,
            birthday_month=dt.date.today().month,
            birthday_day=dt.date.today().day,
        )
        messages = push_service._build_messages(db)
        assert any(m["tag"] == "birthdays" for m in messages)
    finally:
        db.close()


def test_build_messages_respects_disabled_triggers(app):
    from app.database import SessionLocal
    from app.settings_store import set_setting
    db = SessionLocal()
    try:
        make_person(
            db, name="Dana", archived=False,
            birthday_month=dt.date.today().month,
            birthday_day=dt.date.today().day,
        )
        set_setting(db, "push_birthdays", "0")
        messages = push_service._build_messages(db)
        assert all(m["tag"] != "birthdays" for m in messages)
    finally:
        db.close()


def test_send_push_noop_when_disabled(app):
    from app.database import SessionLocal
    from app.settings_store import set_setting
    db = SessionLocal()
    try:
        set_setting(db, "push_enabled", "0")
        db.add(PushSubscription(
            endpoint="https://push/dummy", p256dh="x", auth="y", user_id=None
        ))
        db.commit()
        assert push_service.send_push_notifications(db) == 0
    finally:
        db.close()


def test_send_push_noop_when_no_subscriptions(app):
    from app.database import SessionLocal
    from app.settings_store import set_setting
    db = SessionLocal()
    try:
        set_setting(db, "push_enabled", "1")
        assert push_service.send_push_notifications(db) == 0
    finally:
        db.close()


def test_get_public_vapid_key_empty_until_generated(app):
    db = None
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        key = push_service.get_public_vapid_key(db)
        assert key  # generates on demand
    finally:
        db.close()


def test_subscribe_and_vapid_key_via_api(logged_in_client):
    """End-to-end: an authenticated client can fetch the VAPID key and subscribe."""
    r = logged_in_client.get("/api/push/vapid-key")
    assert r.status_code == 200
    assert r.json()["public_key"]

    r2 = logged_in_client.post(
        "/api/push/subscribe",
        json={"endpoint": "https://push.example/abc", "keys": {"p256dh": "abc", "auth": "xyz"}},
    )
    assert r2.status_code == 200
    assert r2.json()["ok"] is True

    r3 = logged_in_client.post(
        "/api/push/unsubscribe",
        json={"endpoint": "https://push.example/abc"},
    )
    assert r3.status_code == 200
    assert r3.json()["ok"] is True


def test_subscribe_requires_auth(client):
    r = client.post(
        "/api/push/subscribe",
        json={"endpoint": "https://push.example/abc", "keys": {"p256dh": "a", "auth": "b"}},
        follow_redirects=False,
    )
    assert r.status_code == 303  # redirected to login by the auth gate

