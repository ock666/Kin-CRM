def test_settings_page_loads(logged_in_client):
    resp = logged_in_client.get("/settings")
    assert resp.status_code == 200
    assert "Voice Replies" in resp.text
    assert "Calendar sync" in resp.text
    assert 'action="/settings/instagram"' not in resp.text  # feature removed
    assert 'action="/settings/immich"' not in resp.text  # config moved to the household page


def test_settings_page_has_whats_new(logged_in_client):
    resp = logged_in_client.get("/settings")
    assert resp.status_code == 200
    assert "new in Kin" in resp.text
    assert "2026.11.1" in resp.text
    assert "Be gentle with yourself" in resp.text
    assert "Dot Muncher" in resp.text
    assert "Multiple people" in resp.text
    assert "Households" in resp.text
    assert "Kin Wrapped" not in resp.text  # prior release's notes are not in this one


def test_save_immich_settings_persist(logged_in_client):
    resp = logged_in_client.post(
        "/settings/households/1/immich",
        data={"immich_url": "http://immich.local:2283", "immich_api_key": "test-key-123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    page = logged_in_client.get("/settings/households/1")
    assert "http://immich.local:2283" in page.text
    # the key is stored, but never shown back in plaintext
    assert "test-key-123" not in page.text
    from app.database import SessionLocal
    from app.settings_store import get_household_setting
    db = SessionLocal()
    try:
        assert get_household_setting(db, 1, "immich_api_key") == "test-key-123"
    finally:
        db.close()


def test_save_ai_settings_persist(logged_in_client):
    resp = logged_in_client.post(
        "/settings/households/1/ai",
        data={"ai_base_url": "http://ollama:11434/v1", "ai_api_key": "unused", "ai_model": "llama3.1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    page = logged_in_client.get("/settings/households/1")
    assert "http://ollama:11434/v1" in page.text
    assert "llama3.1" in page.text


def test_save_ai_with_blank_key_keeps_existing(logged_in_client):
    # Saving the AI form with a blank key (the "unchanged" password field) must NOT wipe the
    # stored key - previously it silently cleared it, silently disabling AI.
    from app.database import SessionLocal
    from app.settings_store import set_household_setting, get_household_setting

    db = SessionLocal()
    try:
        set_household_setting(db, 1, "ai_base_url", "https://api.openai.com/v1")
        set_household_setting(db, 1, "ai_api_key", "sk-existing-secret")
        set_household_setting(db, 1, "ai_model", "gpt-4o-mini")
        set_household_setting(db, 1, "support_chat_model", "gpt-4o")
    finally:
        db.close()

    logged_in_client.post(
        "/settings/households/1/ai",
        data={"ai_base_url": "https://api.openai.com/v1", "ai_api_key": "",
              "ai_model": "gpt-4o-mini", "support_chat_model": "gpt-4o"},
        follow_redirects=False,
    )
    db = SessionLocal()
    try:
        assert get_household_setting(db, 1, "ai_api_key") == "sk-existing-secret"
    finally:
        db.close()


def test_save_immich_with_blank_key_keeps_existing(logged_in_client):
    from app.database import SessionLocal
    from app.settings_store import set_household_setting, get_household_setting

    db = SessionLocal()
    try:
        set_household_setting(db, 1, "immich_url", "http://immich.local")
        set_household_setting(db, 1, "immich_api_key", "immich-secret")
    finally:
        db.close()

    logged_in_client.post(
        "/settings/households/1/immich",
        data={"immich_url": "http://immich.local", "immich_api_key": ""},
        follow_redirects=False,
    )
    db = SessionLocal()
    try:
        assert get_household_setting(db, 1, "immich_api_key") == "immich-secret"
    finally:
        db.close()


def test_add_second_user(logged_in_client):
    resp = logged_in_client.post(
        "/settings/users/new",
        data={"name": "Second User", "email": "second@example.com", "password": "AnotherPassword123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    page = logged_in_client.get("/settings")
    assert "Second User" in page.text
    assert "second@example.com" in page.text


def test_immich_test_connection_reports_error_when_unreachable(logged_in_client):
    logged_in_client.post(
        "/settings/households/1/immich",
        data={"immich_url": "http://127.0.0.1:1", "immich_api_key": "test-key"},
    )
    resp = logged_in_client.post("/settings/households/1/immich/test")
    assert resp.status_code == 200
    # Should show a friendly error rather than crash the app.
    assert "notice" in resp.text
