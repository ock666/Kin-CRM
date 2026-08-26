"""Tests for the "needs watering" cadence meter (see checkins.compute_cadence_watermeter)."""
import datetime as dt

from app.models import Person
from app.services.checkins import compute_cadence_watermeter, is_overdue


def make_person(db, **kwargs):
    p = Person(**kwargs)
    db.add(p)
    db.commit()
    return p


def test_meter_dormant_when_no_cadence(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = make_person(db, name="No Cadence")
        m = compute_cadence_watermeter(p)
        assert m["state"] == "dormant"
        assert m["overdue"] is False
        assert m["pct"] == 0
        assert m["emoji"] == "💤"
    finally:
        db.close()


def test_meter_healthy_fresh_contact(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = make_person(
            db, name="Fresh", checkin_cadence_days=60,
            last_contact_date=dt.date.today() - dt.timedelta(days=10),
        )
        m = compute_cadence_watermeter(p)
        assert m["state"] == "healthy"
        assert m["overdue"] is False
        assert m["pct"] == round(10 / 60 * 100)
    finally:
        db.close()


def test_meter_getting_dry_near_due(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = make_person(
            db, name="Dry", checkin_cadence_days=60,
            last_contact_date=dt.date.today() - dt.timedelta(days=45),
        )
        m = compute_cadence_watermeter(p)
        assert m["state"] == "getting_dry"
        assert m["overdue"] is False
        # 45/60 = 75% - between 60 and 100
        assert 60 <= m["pct"] < 100
    finally:
        db.close()


def test_meter_wilting_when_overdue(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = make_person(
            db, name="Wilted", checkin_cadence_days=30,
            last_contact_date=dt.date.today() - dt.timedelta(days=60),
        )
        m = compute_cadence_watermeter(p)
        assert m["state"] == "wilting"
        assert m["overdue"] is True
        assert m["label"] == "Needs watering"
        assert m["emoji"] == "💧"
    finally:
        db.close()


def test_meter_snoozed_is_dormant(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = make_person(
            db, name="Snoozed", checkin_cadence_days=30,
            last_contact_date=dt.date.today() - dt.timedelta(days=40),
            checkin_snoozed_until=dt.date.today() + dt.timedelta(days=7),
        )
        m = compute_cadence_watermeter(p)
        assert m["state"] == "dormant"
        assert m["label"] == "Snoozed"
        assert m["overdue"] is False
    finally:
        db.close()


def test_reminders_dismissed_is_not_overdue(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = make_person(
            db, name="Dismissed", checkin_cadence_days=30,
            last_contact_date=dt.date.today() - dt.timedelta(days=40),
            reminders_dismissed=True,
        )
        assert is_overdue(p) is False
        m = compute_cadence_watermeter(p)
        assert m["state"] == "dormant"
        assert m["label"] == "Paused"
        assert m["overdue"] is False
    finally:
        db.close()


def test_meter_consistent_with_is_overdue(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        # The meter's "wilting" should agree with is_overdue for exactly-due people.
        p = make_person(
            db, name="Edge", checkin_cadence_days=30,
            last_contact_date=dt.date.today() - dt.timedelta(days=30),
        )
        m = compute_cadence_watermeter(p)
        assert m["overdue"] == is_overdue(p)
        assert m["state"] == "wilting"
    finally:
        db.close()
