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
    p = Person(household_id=1, name=name, **kw)
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
        a_tags = {t.name for t in db.query(Tag).filter(Tag.household_id == 1).all()}
        b_tags = {t.name for t in db.query(Tag).filter(Tag.household_id == 2).all()}
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


# ---------------------------------------------------------------------------
# Settings / config bleed — per-user Immich/AI/Whisper and preferences.
# ---------------------------------------------------------------------------


def test_per_user_settings_are_isolated(logged_in_client, second_client):
    from app.database import SessionLocal
    from app.settings_store import get_user_setting, set_user_setting
    db = SessionLocal()
    try:
        set_user_setting(db, 1, "immich_url", "http://a-immich.local:2283")
        set_user_setting(db, 1, "ai_api_key", "sk-a-secret")
        set_user_setting(db, 2, "immich_url", "http://b-immich.local:2283")
        set_user_setting(db, 1, "birthday_lead_days", "30")
    finally:
        db.close()

    db = SessionLocal()
    try:
        # Each user reads back only their own values.
        assert get_user_setting(db, 1, "immich_url") == "http://a-immich.local:2283"
        assert get_user_setting(db, 2, "immich_url") == "http://b-immich.local:2283"
        # A's secrets and prefs never leak into B's view.
        assert get_user_setting(db, 2, "ai_api_key") == ""
        assert get_user_setting(db, 2, "birthday_lead_days") == "14"  # B keeps the default
    finally:
        db.close()


def test_settings_page_shows_only_own_config(logged_in_client, second_client):
    from app.database import SessionLocal
    from app.settings_store import set_user_setting
    db = SessionLocal()
    try:
        set_user_setting(db, 1, "immich_url", "http://a-immich.local:2283")
        set_user_setting(db, 1, "ai_api_key", "sk-a-secret")
        set_user_setting(db, 2, "immich_url", "http://b-immich.local:2283")
    finally:
        db.close()

    page_a = logged_in_client.get("/settings").text
    assert "http://a-immich.local:2283" in page_a
    assert "sk-a-secret" not in page_a  # masked even for the owner

    page_b = second_client.get("/settings").text
    assert "http://a-immich.local:2283" not in page_b
    assert "http://b-immich.local:2283" in page_b


def test_immich_client_uses_own_household_config(logged_in_client, second_client):
    from app.database import SessionLocal
    from app.models import User
    from app.settings_store import set_household_setting
    from app.services.immich_client import get_client_from_settings
    db = SessionLocal()
    try:
        # user 1 is in household 1, user 2 in household 2 (each their own individual household)
        set_household_setting(db, 1, "immich_url", "http://a-immich.local:2283")
        set_household_setting(db, 1, "immich_api_key", "a-key")
        set_household_setting(db, 2, "immich_url", "http://b-immich.local:2283")
        set_household_setting(db, 2, "immich_api_key", "b-key")
        a = db.get(User, 1)
        b = db.get(User, 2)
        assert get_client_from_settings(db, a).base_url == "http://a-immich.local:2283/api"
        assert get_client_from_settings(db, b).base_url == "http://b-immich.local:2283/api"
    finally:
        db.close()


def test_non_admin_cannot_manage_users(logged_in_client, second_client):
    from app.database import SessionLocal
    from app.models import User
    resp = second_client.post(
        "/settings/users/new",
        data={"name": "Sneaky", "email": "sneaky@example.com", "password": "SneakyPass123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db = SessionLocal()
    try:
        assert db.query(User).filter(User.email == "sneaky@example.com").count() == 0
    finally:
        db.close()


def test_voice_uploads_are_scoped(logged_in_client, second_client):
    import uuid
    from app.config import settings as app_settings
    a_dir = app_settings.UPLOAD_DIR / "voice" / "1"
    a_dir.mkdir(parents=True, exist_ok=True)
    fname = f"user_{uuid.uuid4().hex}.webm"
    (a_dir / fname).write_bytes(b"fake audio")

    assert logged_in_client.get(f"/uploads/voice/{fname}").status_code == 200
    assert second_client.get(f"/uploads/voice/{fname}").status_code == 404
