"""Tests for relationship states, circles view, and tag color endpoints."""
import datetime as dt

from app.models import (
    Person, ConflictLog, ConflictStatus, RelationshipState, Tag,
)
from app.services import states as state_service


def test_effective_state_none(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = Person(name="No State", relationship_state=RelationshipState.none)
        assert state_service.effective_state(p) == RelationshipState.none
    finally:
        db.close()


def test_effective_state_in_conflict_from_log(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = Person(name="Has Conflict", relationship_state=RelationshipState.none)
        db.add(p)
        db.commit()
        db.add(ConflictLog(person_id=p.id, summary="Argument", status=ConflictStatus.unresolved))
        db.commit()
        p2 = db.get(Person, p.id)
        assert state_service.effective_state(p2) == RelationshipState.in_conflict
    finally:
        db.close()


def test_effective_state_wants_space_overrides(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = Person(name="Wants Space", relationship_state=RelationshipState.wants_space)
        assert state_service.effective_state(p) == RelationshipState.wants_space
    finally:
        db.close()


def test_effective_state_in_conflict_takes_precedence(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = Person(name="Conflict + Drifted", relationship_state=RelationshipState.drifted)
        db.add(p)
        db.commit()
        db.add(ConflictLog(person_id=p.id, summary="Fight", status=ConflictStatus.unresolved))
        db.commit()
        p2 = db.get(Person, p.id)
        assert state_service.effective_state(p2) == RelationshipState.in_conflict
    finally:
        db.close()


def test_suggest_states_no_suggestions_for_recent_contact(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = Person(
            name="Recent Contact", relationship_state=RelationshipState.none,
            checkin_cadence_days=60, last_contact_date=dt.date.today(),
        )
        db.add(p)
        db.commit()
        suggestions = state_service.suggest_states(db)
        assert not any(p2.id == p.id for p2, s, r in suggestions)
    finally:
        db.close()


def test_suggest_states_drifted_when_90_days(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = Person(
            name="Very Old Contact", relationship_state=RelationshipState.none,
            checkin_cadence_days=60,
            last_contact_date=dt.date.today() - dt.timedelta(days=100),
        )
        db.add(p)
        db.commit()
        suggestions = state_service.suggest_states(db)
        matches = [(s, r) for p2, s, r in suggestions if p2.id == p.id]
        assert len(matches) == 1
        assert matches[0][0] == RelationshipState.drifted
    finally:
        db.close()


def test_suggest_states_excludes_with_conflict(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = Person(
            name="Old + Conflict", relationship_state=RelationshipState.none,
            checkin_cadence_days=60,
            last_contact_date=dt.date.today() - dt.timedelta(days=100),
        )
        db.add(p)
        db.commit()
        db.add(ConflictLog(person_id=p.id, summary="Unresolved", status=ConflictStatus.unresolved))
        db.commit()
        suggestions = state_service.suggest_states(db)
        assert not any(p2.id == p.id for p2, s, r in suggestions)
    finally:
        db.close()


def test_suggest_states_excludes_already_drifted(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = Person(
            name="Already Drifted", relationship_state=RelationshipState.drifted,
            checkin_cadence_days=60,
            last_contact_date=dt.date.today() - dt.timedelta(days=100),
        )
        db.add(p)
        db.commit()
        suggestions = state_service.suggest_states(db)
        assert not any(p2.id == p.id for p2, s, r in suggestions)
    finally:
        db.close()


def test_set_state_endpoint(logged_in_client):
    create = logged_in_client.post("/people/new", data={"name": "State Setter"}, follow_redirects=False)
    assert create.status_code == 303
    import re
    match = re.search(r"/people/(\d+)", create.headers["location"])
    pid = int(match.group(1))

    resp = logged_in_client.post(f"/people/{pid}/state", data={"state": "wants_space"}, follow_redirects=False)
    assert resp.status_code == 303

    detail = logged_in_client.get(f"/people/{pid}")
    assert "Wants Space" in detail.text


def test_circles_view(logged_in_client):
    from app.database import get_db
    logged_in_client.post("/people/new", data={"name": "Circle Alice"})
    logged_in_client.post("/people/new", data={"name": "Circle Bob"})

    import re
    resp_a = logged_in_client.post("/people/new", data={"name": "Family Alice"}, follow_redirects=False)
    pa_id = int(re.search(r"/people/(\d+)", resp_a.headers["location"]).group(1))
    resp_b = logged_in_client.post("/people/new", data={"name": "Family Bob"}, follow_redirects=False)
    pb_id = int(re.search(r"/people/(\d+)", resp_b.headers["location"]).group(1))

    logged_in_client.post(f"/people/{pa_id}/tags", data={"tag_name": "Family"})
    logged_in_client.post(f"/people/{pb_id}/tags", data={"tag_name": "Family"})

    circles = logged_in_client.get("/people?view=circles")
    assert circles.status_code == 200
    assert "Family" in circles.text
    assert "Uncircled" in circles.text


def test_tag_color_endpoint(logged_in_client):
    from app.database import get_db, SessionLocal
    resp = logged_in_client.post("/people/new", data={"name": "Color Test"}, follow_redirects=False)
    import re
    pid = int(re.search(r"/people/(\d+)", resp.headers["location"]).group(1))
    logged_in_client.post(f"/people/{pid}/tags", data={"tag_name": "ColorTag"})

    db = SessionLocal()
    try:
        tag = db.query(Tag).filter(Tag.name == "ColorTag").first()
        tag_id = tag.id
    finally:
        db.close()

    resp = logged_in_client.post(f"/tags/{tag_id}/color", data={"color": "#ff0000"}, follow_redirects=False)
    assert resp.status_code == 303

    db2 = SessionLocal()
    try:
        tag2 = db2.get(Tag, tag_id)
        assert tag2.color == "#ff0000"
    finally:
        db2.close()


def test_apply_state_suggestion(logged_in_client):
    from app.database import SessionLocal
    today = dt.date.today()
    old = today - dt.timedelta(days=100)

    db = SessionLocal()
    try:
        p = Person(
            name="Suggestable", relationship_state=RelationshipState.none,
            checkin_cadence_days=60, last_contact_date=old,
        )
        db.add(p)
        db.commit()
        pid = p.id
    finally:
        db.close()

    resp = logged_in_client.post(f"/people/{pid}/state-suggestion/apply", follow_redirects=False)
    assert resp.status_code == 303

    db2 = SessionLocal()
    try:
        p2 = db2.get(Person, pid)
        assert p2.relationship_state == RelationshipState.drifted
    finally:
        db2.close()
