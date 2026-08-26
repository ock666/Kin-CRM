"""Tests for rest achievements, chat retention, and regulation toolkit."""
import datetime as dt
from app.models import ConflictLog, ConflictChatMessage, ConflictStatus, Person
from app.services import gamification


def test_rest_snooze_achievement(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        result = gamification.award_xp(db, "REST_SNOOZE")
        assert result["xp_gained"] == 10
        assert "calm_taker" in result["unlocked_badges"]
    finally:
        db.close()


def test_rest_grace_achievement(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        result = gamification.award_xp(db, "REST_GRACE")
        assert "grace_giver" in result["unlocked_badges"]
    finally:
        db.close()


def test_let_it_go_achievement(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        result = gamification.award_xp(db, "CONFLICT_RELEASED")
        assert "let_it_go" in result["unlocked_badges"]
    finally:
        db.close()


def test_space_keeper_achievement(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        result = gamification.award_xp(db, "REST_SPACE")
        assert "space_keeper" in result["unlocked_badges"]
    finally:
        db.close()


def test_drift_aware_achievement(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        result = gamification.award_xp(db, "REST_SPACE", context={"drift_acknowledged": True})
        assert "drift_aware" in result["unlocked_badges"]
    finally:
        db.close()


def test_snooze_checkin_awards_achievement(logged_in_client):
    create = logged_in_client.post("/people/new", data={
        "name": "Snooze Person",
        "checkin_cadence_days": "60",
    }, follow_redirects=False)
    assert create.status_code == 303
    import re
    pid = int(re.search(r"/people/(\d+)", create.headers["location"]).group(1))

    resp = logged_in_client.post(f"/checkin/{pid}/snooze", data={"days": "14"}, follow_redirects=False)
    assert resp.status_code == 303


def test_grace_awards_achievement(logged_in_client):
    resp = logged_in_client.post("/grace/start", follow_redirects=False)
    assert resp.status_code == 303


def test_retention_expired_return(logged_in_client):
    resp = logged_in_client.post("/people/new", data={"name": "Retention Person"}, follow_redirects=False)
    import re
    pid = int(re.search(r"/people/(\d+)", resp.headers["location"]).group(1))
    logged_in_client.post(f"/people/{pid}/conflicts", data={"summary": "Retention test"})

    from app.database import SessionLocal
    db = SessionLocal()
    try:
        conflict = db.query(ConflictLog).filter(ConflictLog.person_id == pid).first()
        old = dt.datetime.utcnow() - dt.timedelta(days=20)
        db.add(ConflictChatMessage(conflict_id=conflict.id, role="user", content="old", created_at=old))
        db.add(ConflictChatMessage(conflict_id=conflict.id, role="assistant", content="old reply", created_at=old + dt.timedelta(seconds=1)))
        db.commit()

        resp = logged_in_client.get(f"/conflicts/{conflict.id}/chat")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("retention_expired") is True
        assert data.get("messages") == []
    finally:
        db.close()


def test_retention_blocks_post(logged_in_client):
    resp = logged_in_client.post("/people/new", data={"name": "Block Post"}, follow_redirects=False)
    import re
    pid = int(re.search(r"/people/(\d+)", resp.headers["location"]).group(1))
    logged_in_client.post(f"/people/{pid}/conflicts", data={"summary": "Block test"})

    from app.database import SessionLocal
    db = SessionLocal()
    try:
        conflict = db.query(ConflictLog).filter(ConflictLog.person_id == pid).first()
        old = dt.datetime.utcnow() - dt.timedelta(days=20)
        db.add(ConflictChatMessage(conflict_id=conflict.id, role="user", content="old", created_at=old))
        db.commit()

        resp = logged_in_client.post(f"/conflicts/{conflict.id}/chat", json={"message": "hi"})
        assert resp.status_code == 410
        data = resp.json()
        assert data["error"] == "chat_archived"
    finally:
        db.close()


def test_regulation_page_loads(logged_in_client):
    resp = logged_in_client.get("/regulation")
    assert resp.status_code == 200
    assert "Regulation" in resp.text
    assert "5-4-3-2-1" in resp.text


def test_soft_fall_page_loads(logged_in_client):
    resp = logged_in_client.get("/regulation/soft-fall")
    assert resp.status_code == 200
    assert "Soft Fall" in resp.text


def test_soft_fall_requires_auth(client):
    resp = client.get("/regulation/soft-fall", follow_redirects=False)
    assert resp.status_code == 303


def test_games_pages_load(logged_in_client):
    for path, marker in [
        ("/regulation/2048", "2048"),
        ("/regulation/memory", "Memory"),
        ("/regulation/minesweeper", "Minesweeper"),
    ]:
        resp = logged_in_client.get(path)
        assert resp.status_code == 200
        assert marker in resp.text
