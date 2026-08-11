"""Tests for the conflict support chat — model, endpoints, streaming, settings."""
from app.models import ConflictLog, ConflictChatMessage, ConflictStatus, Person


def test_chat_message_model(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = Person(name="Chat Test Person")
        db.add(p)
        db.commit()
        conflict = ConflictLog(person_id=p.id, summary="Argument", status=ConflictStatus.unresolved)
        db.add(conflict)
        db.commit()

        user_msg = ConflictChatMessage(conflict_id=conflict.id, role="user", content="Hello")
        db.add(user_msg)
        db.commit()

        ai_msg = ConflictChatMessage(conflict_id=conflict.id, role="assistant", content="Hi there")
        db.add(ai_msg)
        db.commit()

        msgs = db.query(ConflictChatMessage).filter_by(conflict_id=conflict.id).order_by(ConflictChatMessage.created_at).all()
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[1].role == "assistant"
        assert msgs[0].content == "Hello"
    finally:
        db.close()


def test_chat_messages_cascade_delete(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = Person(name="Cascade Person")
        db.add(p)
        db.commit()
        conflict = ConflictLog(person_id=p.id, summary="Test", status=ConflictStatus.unresolved)
        db.add(conflict)
        db.commit()

        db.add(ConflictChatMessage(conflict_id=conflict.id, role="user", content="msg"))
        db.commit()

        assert db.query(ConflictChatMessage).filter_by(conflict_id=conflict.id).count() == 1
        db.delete(conflict)
        db.commit()
        assert db.query(ConflictChatMessage).filter_by(conflict_id=conflict.id).count() == 0
    finally:
        db.close()


def test_get_chat_messages_empty(logged_in_client):
    create = logged_in_client.post("/people/new", data={"name": "Empty Chat"}, follow_redirects=False)
    assert create.status_code == 303
    import re
    pid = int(re.search(r"/people/(\d+)", create.headers["location"]).group(1))
    logged_in_client.post(f"/people/{pid}/conflicts", data={"summary": "Test conflict"})

    resp = logged_in_client.post("/people/new", data={"name": "Temp Person"}, follow_redirects=False)
    pid2 = int(re.search(r"/people/(\d+)", resp.headers["location"]).group(1))
    logged_in_client.post(f"/people/{pid2}/conflicts", data={"summary": "Test conflict 2"})

    from app.database import SessionLocal
    db = SessionLocal()
    try:
        conflict = db.query(ConflictLog).filter(ConflictLog.person_id == pid).first()
        cid = conflict.id
    finally:
        db.close()

    resp = logged_in_client.get(f"/conflicts/{cid}/chat")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 0


def test_clear_chat(logged_in_client):
    create = logged_in_client.post("/people/new", data={"name": "Clear Chat"}, follow_redirects=False)
    import re
    pid = int(re.search(r"/people/(\d+)", create.headers["location"]).group(1))
    logged_in_client.post(f"/people/{pid}/conflicts", data={"summary": "Clear test"})

    from app.database import SessionLocal
    db = SessionLocal()
    try:
        conflict = db.query(ConflictLog).filter(ConflictLog.person_id == pid).first()
        cid = conflict.id
        db.add(ConflictChatMessage(conflict_id=cid, role="user", content="test"))
        db.commit()
    finally:
        db.close()

    resp = logged_in_client.post(f"/conflicts/{cid}/chat/clear")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    db2 = SessionLocal()
    try:
        assert db2.query(ConflictChatMessage).filter_by(conflict_id=cid).count() == 0
    finally:
        db2.close()


def test_chat_endpoint_no_ai(logged_in_client):
    create = logged_in_client.post("/people/new", data={"name": "No AI Chat"}, follow_redirects=False)
    import re
    pid = int(re.search(r"/people/(\d+)", create.headers["location"]).group(1))
    logged_in_client.post(f"/people/{pid}/conflicts", data={"summary": "No AI test"})

    from app.database import SessionLocal
    db = SessionLocal()
    try:
        conflict = db.query(ConflictLog).filter(ConflictLog.person_id == pid).first()
    finally:
        db.close()

    resp = logged_in_client.post(
        f"/conflicts/{conflict.id}/chat",
        json={"message": "Hello"},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert "AI" in data.get("error", "")


def test_chat_endpoint_unknown_conflict(logged_in_client):
    resp = logged_in_client.get("/conflicts/99999/chat")
    assert resp.status_code == 404


def test_support_chat_model_setting(logged_in_client):
    resp = logged_in_client.post("/settings/ai", data={
        "ai_base_url": "http://test",
        "ai_api_key": "sk-test",
        "ai_model": "gpt-4o-mini",
        "support_chat_model": "gpt-4o",
    }, follow_redirects=False)
    assert resp.status_code == 303

    page = logged_in_client.get("/settings")
    assert page.status_code == 200
    assert "gpt-4o" in page.text
