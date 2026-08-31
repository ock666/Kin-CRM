import datetime as dt

from app.database import SessionLocal
from app.models import Person, NotableDate
from app.settings_store import set_setting
from app.services.calendar_ics import build_ics


def _enable_feed(db, token="sekret-token"):
    set_setting(db, "calendar_ics_enabled", "1")
    set_setting(db, "calendar_ics_token", token)


def test_ics_404_when_disabled(logged_in_client):
    assert logged_in_client.get("/calendar.ics?token=sekret-token").status_code == 404


def test_ics_404_wrong_or_missing_token(logged_in_client):
    db = SessionLocal()
    try:
        _enable_feed(db)
    finally:
        db.close()
    assert logged_in_client.get("/calendar.ics?token=wrong").status_code == 404
    assert logged_in_client.get("/calendar.ics").status_code == 404


def test_ics_contains_birthdays_notable_dates_and_reminders(logged_in_client):
    db = SessionLocal()
    try:
        p = Person(name="Ada Lovelace", birthday_month=12, birthday_day=10)
        db.add(p)
        db.commit()
        db.refresh(p)
        db.add(NotableDate(person_id=p.id, label="Our anniversary", month=6, day=1, recurring=True))
        db.add(NotableDate(person_id=p.id, label="One-off thing", month=3, day=3,
                           recurring=False, year=2026))
        db.commit()
        _enable_feed(db)
    finally:
        db.close()

    resp = logged_in_client.get("/calendar.ics?token=sekret-token")
    assert resp.status_code == 200
    text = resp.text
    assert text.startswith("BEGIN:VCALENDAR")
    assert "kin-birthday-" in text
    assert "kin-notable-" in text
    assert "Ada Lovelace's birthday" in text
    assert "Our anniversary" in text
    # birthdays + recurring notable date recur yearly; the one-off does not
    assert text.count("RRULE:FREQ=YEARLY") == 2
    assert text.count("BEGIN:VEVENT") == 3
    # default reminders: 14 days for birthdays, 1 day for notable dates
    assert "TRIGGER:-P14D" in text
    assert "TRIGGER:-P1D" in text


def test_ics_reminder_days_configurable(logged_in_client):
    db = SessionLocal()
    try:
        p = Person(name="Bob", birthday_month=1, birthday_day=5)
        db.add(p)
        db.commit()
        db.refresh(p)
        db.add(NotableDate(person_id=p.id, label="Bob day", month=4, day=2, recurring=True))
        db.commit()
        _enable_feed(db)
        set_setting(db, "calendar_birthday_reminder_days", "7")
        set_setting(db, "calendar_notable_reminder_days", "2")
    finally:
        db.close()
    text = logged_in_client.get("/calendar.ics?token=sekret-token").text
    assert "TRIGGER:-P7D" in text
    assert "TRIGGER:-P2D" in text


def test_ics_escapes_summary_text(logged_in_client):
    db = SessionLocal()
    try:
        p = Person(name="Mum, Carol", birthday_month=4, birthday_day=1)
        db.add(p)
        db.commit()
        db.refresh(p)
        db.add(NotableDate(person_id=p.id, label="Gotcha; day", month=1, day=1, recurring=True))
        db.commit()
        _enable_feed(db)
    finally:
        db.close()
    text = logged_in_client.get("/calendar.ics?token=sekret-token").text
    assert "Mum\\, Carol's birthday" in text
    assert "Gotcha\\; day" in text


def test_build_ics_handles_feb_29_in_non_leap_year():
    db = SessionLocal()
    try:
        db.add(Person(name="Leap Baby", birthday_month=2, birthday_day=29))
        db.commit()
        text = build_ics(db, birthday_reminder_days=14)
        # non-leap current year -> Feb 29 collapses to Mar 1 rather than erroring
        assert "0301" in text
    finally:
        db.close()


def test_calendar_settings_saves_token_on_enable(logged_in_client):
    resp = logged_in_client.post(
        "/settings/calendar",
        data={
            "calendar_ics_enabled": "1",
            "calendar_sync_birthdays": "1",
            "calendar_sync_notable_dates": "1",
            "calendar_birthday_reminder_days": "14",
            "calendar_notable_reminder_days": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db = SessionLocal()
    try:
        from app.settings_store import get_setting
        assert get_setting(db, "calendar_ics_enabled") == "1"
        assert get_setting(db, "calendar_ics_token")  # auto-generated
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Two-week birthday lead (Kin-wide)
# ---------------------------------------------------------------------------


def test_birthday_lead_default_is_two_weeks():
    from app.settings_store import DEFAULTS
    assert DEFAULTS["birthday_lead_days"] == "14"


def test_startup_migration_bumps_stored_three_to_14(app):
    db = SessionLocal()
    try:
        set_setting(db, "birthday_lead_days", "3")
    finally:
        db.close()

    from app.migrations import run_startup_migrations
    run_startup_migrations()

    db = SessionLocal()
    try:
        from app.settings_store import get_setting
        assert get_setting(db, "birthday_lead_days") == "14"
    finally:
        db.close()
