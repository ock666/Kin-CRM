"""Roles — instance owners, household owners, and per-user settings locks."""
from starlette.testclient import TestClient


def _login(email):
    from app.main import app as fastapi_app
    c = TestClient(fastapi_app)
    r = c.post("/login", data={"email": email, "password": "SecondPass123", "next": "/"}, follow_redirects=False)
    assert r.status_code == 303
    c.get("/mfa/verify")
    return c


def _second_member(db, email="second@example.com"):
    """Create a second user and link them into household 1 as a regular (non-owner) member."""
    from app.services.households import create_user, link_user
    u = create_user(db, name="Second", email=email, password="SecondPass123")
    db.commit()
    link_user(db, u, 1)
    db.refresh(u)
    return u


def test_household_owner_can_promote_member(logged_in_client):
    from app.database import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        second = _second_member(db)
        assert second.is_household_owner is False
        second_id = second.id
    finally:
        db.close()
    resp = logged_in_client.post(f"/household/members/{second_id}/promote", follow_redirects=False)
    assert resp.status_code == 303
    db = SessionLocal()
    try:
        assert db.get(User, second_id).is_household_owner is True
    finally:
        db.close()


def test_cannot_demote_last_owner(logged_in_client):
    from app.database import SessionLocal
    from app.models import User
    from app.services.households import demote_owner
    db = SessionLocal()
    try:
        admin = db.get(User, 1)
        assert demote_owner(db, admin) is False
        assert admin.is_household_owner is True
    finally:
        db.close()


def test_remove_member_moves_to_own_household(logged_in_client):
    from app.database import SessionLocal
    from app.services.households import remove_member
    db = SessionLocal()
    try:
        second = _second_member(db)
        assert remove_member(db, second) is True
        db.refresh(second)
        assert second.household_id != 1
        assert second.is_household_owner is True
    finally:
        db.close()


def test_settings_hidden_hides_config(logged_in_client):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        second = _second_member(db)
        second.settings_hidden = True
        db.commit()
    finally:
        db.close()

    with _login("second@example.com") as c:
        # Household config no longer lives on the base settings page at all.
        page = c.get("/settings").text
        assert 'action="/settings/immich"' not in page
        # A hidden member cannot open their household's config page either.
        assert c.get("/settings/households/1", follow_redirects=False).status_code == 303
        # And the scoped save route is rejected.
        resp = c.post("/settings/households/1/immich",
                      data={"immich_url": "http://x", "immich_api_key": "y"},
                      follow_redirects=False)
        assert resp.status_code == 303


def test_instance_owner_promotion(logged_in_client):
    from app.database import SessionLocal
    from app.models import User
    from app.services.households import create_user
    db = SessionLocal()
    try:
        second = create_user(db, name="Second", email="second@example.com", password="SecondPass123")
        db.commit()
        second_id = second.id
    finally:
        db.close()
    assert logged_in_client.post(f"/settings/users/{second_id}/make-admin", follow_redirects=False).status_code == 303
    db = SessionLocal()
    try:
        assert db.get(User, second_id).is_admin is True
    finally:
        db.close()


def test_non_owner_cannot_invite(logged_in_client):
    from app.database import SessionLocal
    from app.models import HouseholdInvite
    db = SessionLocal()
    try:
        _second_member(db)
        before = db.query(HouseholdInvite).count()
    finally:
        db.close()
    with _login("second@example.com") as c:
        c.post("/household/invite", follow_redirects=False)
    db = SessionLocal()
    try:
        assert db.query(HouseholdInvite).count() == before
    finally:
        db.close()


def test_owner_can_rename_household(logged_in_client):
    from app.database import SessionLocal
    from app.models import Household
    assert logged_in_client.post("/household/rename", data={"name": "Skye & Chris"},
                                 follow_redirects=False).status_code == 303
    db = SessionLocal()
    try:
        assert db.get(Household, 1).name == "Skye & Chris"
    finally:
        db.close()


def test_non_owner_cannot_rename(logged_in_client):
    from app.database import SessionLocal
    from app.models import Household
    db = SessionLocal()
    try:
        _second_member(db)
    finally:
        db.close()
    with _login("second@example.com") as c:
        c.post("/household/rename", data={"name": "Hacked"}, follow_redirects=False)
    db = SessionLocal()
    try:
        assert db.get(Household, 1).name != "Hacked"
    finally:
        db.close()


def test_instance_owner_edits_another_households_config(logged_in_client):
    from app.database import SessionLocal
    from app.services.households import create_user
    from app.settings_store import get_household_setting
    db = SessionLocal()
    try:
        second = create_user(db, name="Second", email="second@example.com", password="SecondPass123")
        db.commit()
        second_hh = second.household_id
    finally:
        db.close()
    resp = logged_in_client.post(
        f"/settings/households/{second_hh}/immich",
        data={"immich_url": "http://second-immich.local:2283", "immich_api_key": "k"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db = SessionLocal()
    try:
        assert get_household_setting(db, second_hh, "immich_url") == "http://second-immich.local:2283"
    finally:
        db.close()


def test_non_admin_cannot_edit_another_household(logged_in_client):
    from app.database import SessionLocal
    from app.services.households import create_user
    from app.settings_store import get_household_setting
    db = SessionLocal()
    try:
        create_user(db, name="Second", email="second@example.com", password="SecondPass123")
        db.commit()
    finally:
        db.close()
    with _login("second@example.com") as c:
        resp = c.post("/settings/households/1/immich", data={"immich_url": "http://hacked"},
                      follow_redirects=False)
        assert resp.status_code == 303
    db = SessionLocal()
    try:
        assert get_household_setting(db, 1, "immich_url") != "http://hacked"
    finally:
        db.close()


def test_member_can_edit_own_household_config(logged_in_client):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        _second_member(db)  # non-owner, non-hidden member of household 1
    finally:
        db.close()
    with _login("second@example.com") as c:
        resp = c.get("/settings/households/1")
        assert resp.status_code == 200
        assert 'action="/settings/households/1/immich"' in resp.text
