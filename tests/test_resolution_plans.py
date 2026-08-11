"""Tests for resolution plans and chat insight features."""
from app.models import (
    ConflictLog, ConflictChatMessage, ConflictStatus, Person,
)


def test_find_plannable_conflicts_no_messages(app):
    from app.database import SessionLocal
    from app.services.resolution_plans import find_plannable_conflicts
    db = SessionLocal()
    try:
        p = Person(name="No Chat Person")
        db.add(p); db.commit()
        c = ConflictLog(person_id=p.id, summary="No messages", status=ConflictStatus.unresolved)
        db.add(c); db.commit()
        result = find_plannable_conflicts(db)
        assert all(r.id != c.id for r in result)
    finally:
        db.close()


def test_find_plannable_conflicts_idle(app):
    from app.database import SessionLocal
    from app.services.resolution_plans import find_plannable_conflicts
    import datetime as dt
    db = SessionLocal()
    try:
        p = Person(name="Idle Chat")
        db.add(p); db.commit()
        c = ConflictLog(person_id=p.id, summary="Idle", status=ConflictStatus.unresolved)
        db.add(c); db.commit()
        old = dt.datetime.utcnow() - dt.timedelta(minutes=30)
        db.add(ConflictChatMessage(conflict_id=c.id, role="user", content="hello", created_at=old))
        db.add(ConflictChatMessage(conflict_id=c.id, role="assistant", content="hi", created_at=old + dt.timedelta(seconds=10)))
        db.commit()
        result = find_plannable_conflicts(db)
        assert any(r.id == c.id for r in result)
    finally:
        db.close()


def test_find_plannable_conflicts_too_recent(app):
    from app.database import SessionLocal
    from app.services.resolution_plans import find_plannable_conflicts
    import datetime as dt
    db = SessionLocal()
    try:
        p = Person(name="Recent Chat")
        db.add(p); db.commit()
        c = ConflictLog(person_id=p.id, summary="Recent", status=ConflictStatus.unresolved)
        db.add(c); db.commit()
        recent = dt.datetime.utcnow() - dt.timedelta(minutes=2)
        db.add(ConflictChatMessage(conflict_id=c.id, role="user", content="hello", created_at=recent))
        db.commit()
        result = find_plannable_conflicts(db)
        assert not any(r.id == c.id for r in result)
    finally:
        db.close()


def test_find_plannable_conflicts_already_has_plan(app):
    from app.database import SessionLocal
    from app.services.resolution_plans import find_plannable_conflicts
    import datetime as dt
    db = SessionLocal()
    try:
        p = Person(name="Has Plan")
        db.add(p); db.commit()
        c = ConflictLog(person_id=p.id, summary="Plan exists", status=ConflictStatus.unresolved,
                        resolution_plan_json='{"summary":"test"}')
        db.add(c); db.commit()
        old = dt.datetime.utcnow() - dt.timedelta(minutes=30)
        db.add(ConflictChatMessage(conflict_id=c.id, role="user", content="hello", created_at=old))
        db.commit()
        result = find_plannable_conflicts(db)
        assert not any(r.id == c.id for r in result)
    finally:
        db.close()


def test_insight_endpoint_mocked(app, logged_in_client, monkeypatch):
    import json as j
    from app.services import ai_client

    class MockAI:
        def chat_insight(self, messages):
            return "Key insight: I should approach this calmly."

    monkeypatch.setattr("app.routers.conflicts.support_ai_from_settings", lambda db: MockAI())

    resp = logged_in_client.post("/people/new", data={"name":"Insight Person"}, follow_redirects=False)
    import re
    pid = int(re.search(r"/people/(\d+)", resp.headers["location"]).group(1))
    logged_in_client.post(f"/people/{pid}/conflicts", data={"summary":"Insight conflict"})

    from app.database import SessionLocal
    db = SessionLocal()
    try:
        c = db.query(ConflictLog).filter(ConflictLog.person_id == pid).first()
        db.add(ConflictChatMessage(conflict_id=c.id, role="user", content="help"))
        db.commit()

        resp = logged_in_client.post(f"/conflicts/{c.id}/chat/insight")
        assert resp.status_code == 200
        data = resp.json()
        assert "insight" in data
    finally:
        db.close()


def test_generate_plan_endpoint_mocked(app, logged_in_client, monkeypatch):
    import json as j
    from app.services import ai_client
    from app.services.ai_client import ResolutionPlan

    plan = ResolutionPlan(
        summary="Test summary",
        feelings="Validated.",
        goal="Clear the air.",
        steps=["Step 1", "Step 2"],
        approach_messages=["msg1", "msg2"],
        boundary_script="boundary",
        release_option="Let go.",
    )

    class MockAI:
        def suggest_resolution_plan(self, *a, **kw):
            return plan

    monkeypatch.setattr("app.services.ai_client.get_support_client_from_settings", lambda db: MockAI())

    resp = logged_in_client.post("/people/new", data={"name":"Plan Person"}, follow_redirects=False)
    import re
    pid = int(re.search(r"/people/(\d+)", resp.headers["location"]).group(1))
    logged_in_client.post(f"/people/{pid}/conflicts", data={"summary":"Plan conflict"})

    from app.database import SessionLocal
    import datetime as dt
    db = SessionLocal()
    try:
        c = db.query(ConflictLog).filter(ConflictLog.person_id == pid).first()
        old = dt.datetime.utcnow() - dt.timedelta(minutes=30)
        db.add(ConflictChatMessage(conflict_id=c.id, role="user", content="hello", created_at=old))
        db.commit()

        resp = logged_in_client.post(f"/conflicts/{c.id}/plan/generate", follow_redirects=False)
        assert resp.status_code == 303

        db.refresh(c)
        assert c.resolution_plan_json is not None
        loaded = j.loads(c.resolution_plan_json)
        assert loaded["summary"] == "Test summary"
    finally:
        db.close()
