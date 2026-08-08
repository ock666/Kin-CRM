def test_settings_page_loads(logged_in_client):
    resp = logged_in_client.get("/settings")
    assert resp.status_code == 200
    assert "Immich" in resp.text
    assert "AI assistant" in resp.text
    assert "Instagram" in resp.text


def test_save_immich_settings_persist(logged_in_client):
    resp = logged_in_client.post(
        "/settings/immich",
        data={"immich_url": "http://immich.local:2283", "immich_api_key": "test-key-123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    page = logged_in_client.get("/settings")
    assert "http://immich.local:2283" in page.text
    assert "test-key-123" in page.text


def test_save_ai_settings_persist(logged_in_client):
    resp = logged_in_client.post(
        "/settings/ai",
        data={"ai_base_url": "http://ollama:11434/v1", "ai_api_key": "unused", "ai_model": "llama3.1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    page = logged_in_client.get("/settings")
    assert "http://ollama:11434/v1" in page.text
    assert "llama3.1" in page.text


def test_add_second_user(logged_in_client):
    resp = logged_in_client.post(
        "/settings/users/new",
        data={"name": "Second User", "email": "second@example.com", "password": "anotherpassword123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    page = logged_in_client.get("/settings")
    assert "Second User" in page.text
    assert "second@example.com" in page.text


def test_immich_test_connection_reports_error_when_unreachable(logged_in_client):
    logged_in_client.post(
        "/settings/immich",
        data={"immich_url": "http://127.0.0.1:1", "immich_api_key": "test-key"},
    )
    resp = logged_in_client.post("/settings/immich/test")
    assert resp.status_code == 200
    # Should show a friendly error rather than crash the app.
    assert "notice" in resp.text
