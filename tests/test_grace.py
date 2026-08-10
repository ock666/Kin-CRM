"""Tests for grace mode ("stepping back for now") - a calm, no-reason one-week pause on the
gentle nudges, reminders, and push notifications."""
import datetime as dt

from app.services import grace as grace_service
from app.settings_store import get_setting, set_setting


def test_grace_inactive_by_default(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        assert grace_service.is_grace_active(db) is False
        assert grace_service.remaining_days(db) is None
    finally:
        db.close()


def test_start_grace_for_one_week(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        until = grace_service.start_grace(db)
        assert until == dt.date.today() + dt.timedelta(days=6)
        assert grace_service.is_grace_active(db) is True
        assert grace_service.remaining_days(db) == 7
        assert get_setting(db, "grace_until") == until.isoformat()
    finally:
        db.close()


def test_grace_expires_after_week(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        today = dt.date(2026, 1, 1)
        grace_service.start_grace(db, days=7, today=today)
        assert grace_service.is_grace_active(db, today=today) is True
        # Next day 7 days later, grace is over.
        later = today + dt.timedelta(days=8)
        assert grace_service.is_grace_active(db, today=later) is False
        assert grace_service.remaining_days(db, today=later) is None
    finally:
        db.close()


def test_end_grace_clears(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        grace_service.start_grace(db)
        assert grace_service.is_grace_active(db) is True
        grace_service.end_grace(db)
        assert grace_service.is_grace_active(db) is False
        assert get_setting(db, "grace_until") == ""
    finally:
        db.close()


def test_push_silenced_during_grace(app):
    """Push notifications must not send while grace mode is active, regardless of config."""
    from app.database import SessionLocal
    from app.models import Person, PushSubscription
    from app.services import push as push_service
    db = SessionLocal()
    try:
        # Setup: push enabled + a subscription + an overdue cadence that would trigger.
        set_setting(db, "push_enabled", "1")
        set_setting(db, "push_cadence", "1")
        db.add(PushSubscription(endpoint="https://push/dummy", p256dh="x", auth="y", user_id=None))
        over = Person(name="Overdue", archived=False, checkin_cadence_days=30,
                      last_contact_date=dt.date.today() - dt.timedelta(days=90))
        db.add(over)
        db.commit()

        # No grace: would attempt to send (messages built). We just assert it doesn't error and
        # actually builds messages / touches the send path. (Real delivery is mocked elsewhere.)
        assert push_service._build_messages(db)  # something to send exists

        # With grace active, send_push_notifications must short-circuit to 0.
        grace_service.start_grace(db)
        assert push_service.send_push_notifications(db) == 0
    finally:
        db.close()


def test_dashboard_hides_nudges_during_grace(logged_in_client):
    """The dashboard must not surface overdue/conflicts while grace is active."""
    from app.database import SessionLocal
    from app.models import Person
    db = SessionLocal()
    try:
        over = Person(name="Maya", archived=False, checkin_cadence_days=30,
                      last_contact_date=dt.date.today() - dt.timedelta(days=90))
        db.add(over)
        db.commit()
    finally:
        db.close()

    # Without grace, the overdue person appears.
    html = logged_in_client.get("/", follow_redirects=True).text
    assert "Maya" in html
    assert "Time to reach out" in html

    # Start grace via the UI endpoint.
    resp = logged_in_client.post("/grace/start", follow_redirects=True)
    assert resp.status_code == 200
    assert "Stepping back" in resp.text
    assert "Maya" not in resp.text
    assert "Time to reach out" in resp.text  # card still present, but no entries


def test_grace_start_end_via_api(logged_in_client):
    resp = logged_in_client.post("/grace/start", follow_redirects=True)
    assert resp.status_code == 200
    # Banner heading + the "paused" text are unique to grace-active state.
    assert "nudges and reminders are paused" in resp.text
    assert "more day" in resp.text

    resp2 = logged_in_client.post("/grace/end", follow_redirects=True)
    assert resp2.status_code == 200
    assert "nudges and reminders are paused" not in resp2.text
