"""Per-user isolation — two users on one instance must never see or touch each other's data.

These are the tests that make multi-user *trustworthy*: they create data for user A, then assert
that user B (a second account on the same instance) cannot list, read, or mutate any of it — via
the web UI and the token-authed API alike.
"""
import pytest
from starlette.testclient import TestClient


SECOND = {"name": "Second User", "email": "second@example.com", "password": "SecondPass123"}


@pytest.fixture()
def second_client(logged_in_client, client):
    """A fresh TestClient logged in as a second, non-admin user on the same instance."""
    logged_in_client.post(
        "/settings/users/new",
        data={"name": SECOND["name"], "email": SECOND["email"], "password": SECOND["password"]},
        follow_redirects=False,
    )
    from app.main import app as fastapi_app
    with TestClient(fastapi_app) as c2:
        r = c2.post(
            "/login",
            data={"email": SECOND["email"], "password": SECOND["password"], "next": "/"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        c2.get("/mfa/verify")  # no MFA -> completes login
        yield c2


def _add_person(db, name, **kw):
    from app.models import Person
    p = Person(user_id=1, name=name, **kw)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_people_are_isolated(logged_in_client, second_client):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        alice = _add_person(db, "Alice Private Friend", birthday_month=6, birthday_day=15)
    finally:
        db.close()

    # User A sees their person...
    assert "Alice Private Friend" in logged_in_client.get("/people").text
    # ...user B does not.
    assert "Alice Private Friend" not in second_client.get("/people").text


def test_person_detail_blocks_cross_user_access(logged_in_client, second_client):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        pid = _add_person(db, "Secret Person").id
    finally:
        db.close()

    assert logged_in_client.get(f"/people/{pid}").status_code == 200
    # B cannot open A's person detail — redirected back to the people list.
    resp = second_client.get(f"/people/{pid}", follow_redirects=False)
    assert resp.status_code in (303, 307)
    assert resp.headers["location"] == "/people"


def test_tags_are_isolated(logged_in_client, second_client):
    from app.database import SessionLocal
    from app.models import Person, Tag
    db = SessionLocal()
    try:
        p = _add_person(db, "Tagged Person")
        db.commit()
        pid = p.id
    finally:
        db.close()

    # A tags their person with a name B will also use.
    logged_in_client.post(f"/people/{pid}/tags", data={"tag_name": "friends"}, follow_redirects=False)

    db = SessionLocal()
    try:
        a_tags = {t.name for t in db.query(Tag).filter(Tag.user_id == 1).all()}
        b_tags = {t.name for t in db.query(Tag).filter(Tag.user_id == 2).all()}
    finally:
        db.close()
    assert "friends" in a_tags
    assert "friends" not in b_tags


def test_cross_user_write_is_blocked(logged_in_client, second_client):
    from app.database import SessionLocal
    from app.models import ConflictLog
    db = SessionLocal()
    try:
        pid = _add_person(db, "Alice Person").id
    finally:
        db.close()

    # B tries to write a conflict onto A's person — must be silently ignored.
    resp = second_client.post(
        f"/people/{pid}/conflicts", data={"summary": "sneaky"}, follow_redirects=False
    )
    assert resp.status_code == 303
    db = SessionLocal()
    try:
        assert db.query(ConflictLog).filter(ConflictLog.person_id == pid).count() == 0
    finally:
        db.close()


def test_api_isolation(logged_in_client, second_client):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        pid = _add_person(db, "API Secret Person").id
    finally:
        db.close()

    # B gets an API token.
    r = second_client.post("/api/v1/auth/login", json={"email": SECOND["email"], "password": SECOND["password"]})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # B's people list must not contain A's person.
    listed = second_client.get("/api/v1/people", headers=headers).json()
    assert all(item["id"] != pid for item in listed)
    # Direct fetch is a 404.
    assert second_client.get(f"/api/v1/people/{pid}", headers=headers).status_code == 404
