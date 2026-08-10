"""Tests for birthday calculation, Feb 29 edge case, and draft generation."""
import datetime as dt

from app.models import Person, BirthdayMessageDraft
from app.services.birthdays import (
    _next_birthday,
    people_with_upcoming_birthdays,
    generate_birthday_drafts,
    _safe_int,
)


class FakePerson:
    birthday_month = None
    birthday_day = None
    birthday_year = None
    archived = False


def test_next_birthday_no_birthday():
    p = FakePerson()
    assert _next_birthday(p, dt.date(2026, 8, 11)) is None


def test_next_birthday_today():
    p = FakePerson()
    p.birthday_month = 8
    p.birthday_day = 11
    today = dt.date(2026, 8, 11)
    result = _next_birthday(p, today)
    assert result == today


def test_next_birthday_later_this_year():
    p = FakePerson()
    p.birthday_month = 12
    p.birthday_day = 25
    today = dt.date(2026, 8, 11)
    result = _next_birthday(p, today)
    assert result == dt.date(2026, 12, 25)


def test_next_birthday_next_year():
    p = FakePerson()
    p.birthday_month = 2
    p.birthday_day = 1
    today = dt.date(2026, 8, 11)
    result = _next_birthday(p, today)
    assert result == dt.date(2027, 2, 1)


def test_next_birthday_feb29_leap_year():
    p = FakePerson()
    p.birthday_month = 2
    p.birthday_day = 29
    today = dt.date(2024, 1, 1)
    result = _next_birthday(p, today)
    assert result == dt.date(2024, 2, 29)


def test_next_birthday_feb29_non_leap_year():
    p = FakePerson()
    p.birthday_month = 2
    p.birthday_day = 29
    today = dt.date(2025, 8, 11)
    result = _next_birthday(p, today)
    assert result == dt.date(2026, 3, 1)


def test_next_birthday_feb29_before_march():
    p = FakePerson()
    p.birthday_month = 2
    p.birthday_day = 29
    today = dt.date(2025, 1, 15)
    result = _next_birthday(p, today)
    assert result == dt.date(2025, 3, 1)


def test_next_birthday_feb29_in_leap_year_later():
    p = FakePerson()
    p.birthday_month = 2
    p.birthday_day = 29
    today = dt.date(2028, 1, 1)
    result = _next_birthday(p, today)
    assert result == dt.date(2028, 2, 29)


def test_next_birthday_invalid_date():
    p = FakePerson()
    p.birthday_month = 2
    p.birthday_day = 30
    today = dt.date(2026, 8, 11)
    assert _next_birthday(p, today) is None


def test_safe_int_valid():
    assert _safe_int("3", 10) == 3
    assert _safe_int(5, 10) == 5


def test_safe_int_invalid():
    assert _safe_int("abc", 10) == 10
    assert _safe_int(None, 5) == 5
    assert _safe_int("", 7) == 7


def test_people_with_upcoming_birthdays(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        today = dt.date.today()
        # Person with birthday tomorrow
        tomorrow = today + dt.timedelta(days=1)
        p = Person(
            name="Tomorrow Bday",
            birthday_month=tomorrow.month,
            birthday_day=tomorrow.day,
        )
        db.add(p)
        db.commit()

        result = people_with_upcoming_birthdays(db, lead_days=3)
        assert len(result) == 1
        assert result[0][0].name == "Tomorrow Bday"
        assert result[0][1] == 1  # days until
    finally:
        db.close()


def test_people_with_upcoming_birthdays_none_soon(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        far = dt.date.today() + dt.timedelta(days=100)
        p = Person(
            name="Far Bday",
            birthday_month=far.month,
            birthday_day=far.day,
        )
        db.add(p)
        db.commit()

        result = people_with_upcoming_birthdays(db, lead_days=3)
        assert len(result) == 0
    finally:
        db.close()


def test_generate_birthday_drafts_creates_drafts(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        today = dt.date.today()
        tomorrow = today + dt.timedelta(days=1)
        p = Person(
            name="Draft Person",
            birthday_month=tomorrow.month,
            birthday_day=tomorrow.day,
        )
        db.add(p)
        db.commit()

        created = generate_birthday_drafts(db)
        assert created >= 1

        draft = db.query(BirthdayMessageDraft).filter_by(person_id=p.id).first()
        assert draft is not None
        assert draft.draft_text is not None
        assert len(draft.draft_text) > 10
    finally:
        db.close()


def test_generate_birthday_drafts_skips_existing(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        today = dt.date.today()
        tomorrow = today + dt.timedelta(days=1)
        target_year = tomorrow.year
        p = Person(
            name="Existing Draft",
            birthday_month=tomorrow.month,
            birthday_day=tomorrow.day,
        )
        db.add(p)
        db.commit()

        first = generate_birthday_drafts(db)
        assert first >= 1

        second = generate_birthday_drafts(db)
        assert second == 0  # Should skip, draft already exists for this year
    finally:
        db.close()
