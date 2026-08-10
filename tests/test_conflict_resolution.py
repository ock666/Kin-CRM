"""Tests for the conflict log lifecycle — create, resolve, release, dismiss, delete.

AI-specific path (generate_approach_suggestions) is tested at the pure-function level
without requiring a real AI endpoint, covering the cache-hit and fallback branches.
"""
import datetime as dt
import json

from app.models import (
    ConflictLog, ConflictStatus, Person,
)
from app.services import conflict_resolution, gamification


def test_create_conflict(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = Person(name="Test Friend")
        db.add(p)
        db.commit()

        conflict = ConflictLog(
            person_id=p.id,
            summary="We had an argument about plans.",
            status=ConflictStatus.unresolved,
        )
        db.add(conflict)
        db.commit()

        assert conflict.id is not None
        assert conflict.status == ConflictStatus.unresolved
        assert conflict.reminder_dismissed is False
        assert conflict.person.name == "Test Friend"
    finally:
        db.close()


def test_resolve_conflict(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = Person(name="Resolved Friend")
        db.add(p)
        db.commit()

        conflict = ConflictLog(person_id=p.id, summary="Argument", status=ConflictStatus.unresolved)
        db.add(conflict)
        db.commit()

        conflict.status = ConflictStatus.resolved
        conflict.resolved_at = dt.datetime.utcnow()
        conflict.resolution_notes = "We talked it out."
        db.commit()

        assert conflict.status == ConflictStatus.resolved
        assert conflict.resolution_notes == "We talked it out."
        assert conflict.resolved_at is not None
    finally:
        db.close()


def test_release_conflict(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = Person(name="Let Go Friend")
        db.add(p)
        db.commit()

        conflict = ConflictLog(person_id=p.id, summary="Misunderstanding", status=ConflictStatus.unresolved)
        db.add(conflict)
        db.commit()

        conflict.status = ConflictStatus.released
        conflict.resolved_at = dt.datetime.utcnow()
        db.commit()

        assert conflict.status == ConflictStatus.released
        assert conflict.resolved_at is not None
    finally:
        db.close()


def test_dismiss_reminder(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = Person(name="Dismissed Reminder")
        db.add(p)
        db.commit()

        conflict = ConflictLog(person_id=p.id, summary="Minor thing", status=ConflictStatus.unresolved)
        db.add(conflict)
        db.commit()

        conflict.reminder_dismissed = True
        db.commit()

        assert conflict.reminder_dismissed is True
        assert conflict.status == ConflictStatus.unresolved
    finally:
        db.close()


def test_delete_conflict(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = Person(name="Delete Me")
        db.add(p)
        db.commit()

        conflict = ConflictLog(person_id=p.id, summary="Irrelevant", status=ConflictStatus.unresolved)
        db.add(conflict)
        db.commit()

        cid = conflict.id
        db.delete(conflict)
        db.commit()

        assert db.get(ConflictLog, cid) is None
    finally:
        db.close()


def test_get_cached_suggestions_none():
    conflict = ConflictLog(person_id=1, summary="Test", status=ConflictStatus.unresolved)
    conflict.ai_approach_json = None
    assert conflict_resolution.get_cached_suggestions(conflict) is None


def test_get_cached_suggestions_valid_json():
    conflict = ConflictLog(person_id=1, summary="Test", status=ConflictStatus.unresolved)
    data = {
        "reflection": "That makes sense.",
        "approach_casual": "Hey, just checking in.",
        "approach_direct": "Can we talk about what happened?",
        "boundary_script": "I need some space right now.",
    }
    conflict.ai_approach_json = json.dumps(data)
    result = conflict_resolution.get_cached_suggestions(conflict)
    assert result == data
    assert result["reflection"] == "That makes sense."


def test_get_cached_suggestions_bad_json():
    conflict = ConflictLog(person_id=1, summary="Test", status=ConflictStatus.unresolved)
    conflict.ai_approach_json = "not valid json {{{"
    result = conflict_resolution.get_cached_suggestions(conflict)
    assert result is None


def test_generate_approach_suggestions_without_ai(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        conflict = ConflictLog(person_id=1, summary="Test", status=ConflictStatus.unresolved)
        result = conflict_resolution.generate_approach_suggestions(db, None, conflict, "Alice")
        assert result is None
        assert conflict.ai_approach_json is None
    finally:
        db.close()


def test_conflict_status_enum():
    assert ConflictStatus.unresolved.value == "UNRESOLVED"
    assert ConflictStatus.resolved.value == "RESOLVED"
    assert ConflictStatus.released.value == "RELEASED"


def test_conflict_open_unresolved_filter(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = Person(name="Filter Test")
        db.add(p)
        db.commit()

        unresolved = ConflictLog(
            person_id=p.id, summary="Still open", status=ConflictStatus.unresolved
        )
        resolved = ConflictLog(
            person_id=p.id, summary="Done", status=ConflictStatus.resolved
        )
        db.add_all([unresolved, resolved])
        db.commit()

        open_conflicts = (
            db.query(ConflictLog)
            .filter(ConflictLog.status == ConflictStatus.unresolved)
            .filter(ConflictLog.reminder_dismissed.is_(False))
            .all()
        )
        assert len(open_conflicts) == 1
        assert open_conflicts[0].summary == "Still open"
    finally:
        db.close()
