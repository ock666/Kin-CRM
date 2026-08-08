def test_unauthenticated_root_redirects_to_setup(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/setup"


def test_setup_wizard_creates_admin_and_logs_in(client, admin_credentials):
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
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    # Session cookie should now grant access to the dashboard.
    dashboard = client.get("/", follow_redirects=False)
    assert dashboard.status_code == 200
    assert "Today" in dashboard.text


def test_setup_rejects_mismatched_passwords(client):
    resp = client.post(
        "/setup",
        data={
            "name": "Someone",
            "email": "someone@example.com",
            "password": "testpassword123",
            "password_confirm": "different-password",
        },
    )
    assert resp.status_code == 200
    assert "must match" in resp.text.lower()


def test_second_visit_to_setup_redirects_once_admin_exists(logged_in_client):
    resp = logged_in_client.get("/setup", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_login_with_wrong_password_shows_error(client, admin_credentials):
    client.post(
        "/setup",
        data={
            "name": admin_credentials["name"],
            "email": admin_credentials["email"],
            "password": admin_credentials["password"],
            "password_confirm": admin_credentials["password"],
        },
    )
    client.get("/logout")
    resp = client.post(
        "/login", data={"email": admin_credentials["email"], "password": "wrong-password"}
    )
    assert resp.status_code == 200
    assert "incorrect" in resp.text.lower()


def test_logout_requires_login_again(logged_in_client):
    logged_in_client.get("/logout")
    resp = logged_in_client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login")
