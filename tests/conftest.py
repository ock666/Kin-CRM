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
    return {"name": "Test Admin", "email": "admin@example.com", "password": "testpassword123"}


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
