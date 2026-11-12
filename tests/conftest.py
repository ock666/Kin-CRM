"""Shared pytest fixtures.

Each test gets a fresh SQLite database (tables dropped/recreated) inside a
session-wide temp DATA_DIR, and a fresh Starlette TestClient. The scheduler is
disabled during tests via DISABLE_SCHEDULER=1 so background jobs never fire.

Note: environment variables that app/config.py reads at import time (DATA_DIR,
SESSION_SECRET, DISABLE_SCHEDULER) must be set *before* `app.main` is first
imported anywhere in the test session - the `test_data_dir` fixture below runs
first (autouse, session-scoped) to guarantee that.
"""
import os
import shutil
import tempfile

import pytest


@pytest.fixture(scope="session", autouse=True)
def test_data_dir():
    d = tempfile.mkdtemp(prefix="kin_test_")
    os.environ["DATA_DIR"] = d
    os.environ["DISABLE_SCHEDULER"] = "1"
    os.environ["SESSION_SECRET"] = "test-secret-key-not-for-production-use"
    # The suite creates fresh admin users in many tests; the auth rate limiter would
    # 429 the shared test IP well before the first file finishes. Raise the cap.
    os.environ["RATE_LIMIT_MAX_REQUESTS"] = "10000"
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def app(test_data_dir):
    from app.database import Base, engine
    from app.main import app as fastapi_app

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield fastapi_app


@pytest.fixture()
def client(app):
    from starlette.testclient import TestClient

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def admin_credentials():
    return {"name": "Test Admin", "email": "admin@example.com", "password": "Testpassword123"}


@pytest.fixture()
def logged_in_client(client, admin_credentials):
    """A TestClient that has completed the first-run setup wizard and is logged in."""
    resp = client.post(
        "/setup",
        data={
            "name": admin_credentials["name"],
            "email": admin_credentials["email"],
            "password": admin_credentials["password"],
            "password_confirm": admin_credentials["password"],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"] == "/"
    return client


@pytest.fixture()
def user(app):
    """A persisted User for unit tests that call scoped services directly.

    Returns the *first* existing user (e.g. the admin created by `logged_in_client`) when one is
    already present, so `user.id` is stable at 1 across both pure unit tests and integration
    tests that mix `logged_in_client` with this fixture."""
    from app.database import SessionLocal
    from app.models import User
    from app.auth import hash_password
    db = SessionLocal()
    try:
        u = db.query(User).first()
        if u is None:
            u = User(name="Unit User", email="unit@example.com",
                     hashed_password=hash_password("Password123!"), is_admin=True)
            db.add(u)
            db.commit()
            db.refresh(u)
        return u
    finally:
        db.close()


@pytest.fixture()
def make_person(user):
    """Factory returning a persisted Person owned by `user` (id refreshed)."""
    from app.database import SessionLocal
    from app.models import Person
    db = SessionLocal()

    def _make(**kwargs):
        defaults = dict(name="Test Person", user_id=user.id)
        defaults.update(kwargs)
        p = Person(**defaults)
        db.add(p)
        db.commit()
        db.refresh(p)
        return p

    yield _make
    db.close()
