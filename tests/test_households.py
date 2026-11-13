"""Households — a household of one is an individual account; linking merges accounts into a
shared household (the original shared-workspace behaviour)."""
import pytest
from starlette.testclient import TestClient


def _second_user(db, name="Second", email="second@example.com"):
    from app.services.households import create_user
    u = create_user(db, name=name, email=email, password="SecondPass123")
    db.commit()
    db.refresh(u)
    return u


def _login_second():
    from app.main import app as fastapi_app
    c2 = TestClient(fastapi_app)
    r = c2.post(
        "/login",
        data={"email": "second@example.com", "password": "SecondPass123", "next": "/"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    c2.get("/mfa/verify")
    return c2


def test_individual_households_are_isolated(logged_in_client):
    from app.database import SessionLocal
    from app.models import Person
    db = SessionLocal()
    try:
        db.add(Person(household_id=1, name="Private Person"))
        _second_user(db)  # gets its own household
        db.commit()
    finally:
        db.close()

    with _login_second() as c2:
        assert "Private Person" not in c2.get("/people").text


def test_linked_users_share_data(logged_in_client):
    from app.database import SessionLocal
    from app.models import Person
    from app.services.households import link_user
    db = SessionLocal()
    try:
        db.add(Person(household_id=1, name="Shared Person"))
        second = _second_user(db)
        db.commit()
        db.add(Person(household_id=second.household_id, name="Second's Person"))
        db.commit()
        assert link_user(db, second, 1) is True
        db.refresh(second)
        assert second.household_id == 1
        names = {p.name for p in db.query(Person).filter(Person.household_id == 1).all()}
        assert names == {"Shared Person", "Second's Person"}
    finally:
        db.close()


def test_merge_dedups_tags(logged_in_client):
    from app.database import SessionLocal
    from app.models import Tag
    from app.services.households import link_user
    db = SessionLocal()
    try:
        second = _second_user(db)
        db.commit()
        db.add(Tag(household_id=1, name="friends"))
        db.add(Tag(household_id=second.household_id, name="friends"))
        db.commit()
        link_user(db, second, 1)
        tags = db.query(Tag).filter(Tag.household_id == 1, Tag.name == "friends").all()
        assert len(tags) == 1
    finally:
        db.close()


def test_household_config_is_shared(logged_in_client):
    """Both members of a household read the same Immich/AI config."""
    from app.database import SessionLocal
    from app.settings_store import set_household_setting, get_household_setting
    from app.services.households import link_user
    db = SessionLocal()
    try:
        second = _second_user(db)
        set_household_setting(db, 1, "immich_url", "http://shared-immich.local:2283")
        link_user(db, second, 1)
        db.refresh(second)
        assert get_household_setting(db, second.household_id, "immich_url") == "http://shared-immich.local:2283"
    finally:
        db.close()


def test_invite_accept_merges(logged_in_client):
    from app.database import SessionLocal
    from app.models import User
    from app.services.households import generate_invite, accept_invite
    db = SessionLocal()
    try:
        second = _second_user(db)
        admin = db.get(User, 1)
        inv = generate_invite(db, admin)
        result = accept_invite(db, second, inv.token)
        assert result is not None
        db.refresh(second)
        assert second.household_id == 1
        assert inv.used_at is not None and inv.accepted_by_user_id == second.id
    finally:
        db.close()


def test_invite_register_creates_account_and_joins(logged_in_client):
    from app.database import SessionLocal
    from app.models import User
    from app.services.households import generate_invite
    db = SessionLocal()
    try:
        inv = generate_invite(db, db.get(User, 1))
        token = inv.token
    finally:
        db.close()

    resp = logged_in_client.post(
        f"/household/invite/{token}/register",
        data={
            "name": "Newbie", "email": "newbie@example.com",
            "password": "NewbiePass123", "password_confirm": "NewbiePass123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == "newbie@example.com").first()
        assert u is not None and u.household_id == 1
    finally:
        db.close()


def test_invite_is_single_use_and_expiring(logged_in_client):
    from app.database import SessionLocal
    from app.models import User
    from app.services.households import generate_invite, accept_invite
    db = SessionLocal()
    try:
        second = _second_user(db)
        third = _second_user(db, name="Third", email="third@example.com")
        inv = generate_invite(db, db.get(User, 1))
        assert accept_invite(db, second, inv.token) is not None
        # a second accept with the same token must fail
        assert accept_invite(db, third, inv.token) is None
    finally:
        db.close()
