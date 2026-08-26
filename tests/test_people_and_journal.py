import re


def _extract_person_id_from_redirect(location: str) -> int:
    match = re.search(r"/people/(\d+)", location)
    assert match, f"expected a /people/<id> redirect, got {location}"
    return int(match.group(1))


def test_create_person_minimal(logged_in_client):
    resp = logged_in_client.post("/people/new", data={"name": "Ada Lovelace"}, follow_redirects=False)
    assert resp.status_code == 303
    person_id = _extract_person_id_from_redirect(resp.headers["location"])

    detail = logged_in_client.get(f"/people/{person_id}")
    assert detail.status_code == 200
    assert "Ada Lovelace" in detail.text


def test_gap_questions_regenerate_button_shown_when_present(logged_in_client):
    from app.database import SessionLocal
    from app.models import Person

    resp = logged_in_client.post("/people/new", data={"name": "Gap Person"}, follow_redirects=False)
    person_id = _extract_person_id_from_redirect(resp.headers["location"])

    db = SessionLocal()
    try:
        p = db.get(Person, person_id)
        p.ai_starters_json = '["What do you do for work?", "Any siblings?"]'
        db.commit()
    finally:
        db.close()

    detail = logged_in_client.get(f"/people/{person_id}")
    assert "Regenerate" in detail.text
    assert "What do you do for work?" in detail.text


def test_people_list_shows_created_person(logged_in_client):
    logged_in_client.post("/people/new", data={"name": "Grace Hopper"})
    resp = logged_in_client.get("/people")
    assert resp.status_code == 200
    assert "Grace Hopper" in resp.text


def test_edit_person_updates_fields(logged_in_client):
    create = logged_in_client.post("/people/new", data={"name": "Original Name"}, follow_redirects=False)
    person_id = _extract_person_id_from_redirect(create.headers["location"])

    resp = logged_in_client.post(
        f"/people/{person_id}/edit",
        data={"name": "Updated Name", "relationship_label": "close friend"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    detail = logged_in_client.get(f"/people/{person_id}")
    assert "Updated Name" in detail.text
    assert "close friend" in detail.text


def test_archive_person_toggles(logged_in_client):
    create = logged_in_client.post("/people/new", data={"name": "Archivable Person"}, follow_redirects=False)
    person_id = _extract_person_id_from_redirect(create.headers["location"])

    resp = logged_in_client.post(f"/people/{person_id}/archive", follow_redirects=False)
    assert resp.status_code == 303

    # archived people shouldn't show in the default (non-archived) list...
    default_list = logged_in_client.get("/people")
    assert "Archivable Person" not in default_list.text

    # ...but should show up when explicitly requesting archived people.
    archived_list = logged_in_client.get("/people?show_archived=true")
    assert "Archivable Person" in archived_list.text


def test_add_tag_to_person(logged_in_client):
    create = logged_in_client.post("/people/new", data={"name": "Tagged Person"}, follow_redirects=False)
    person_id = _extract_person_id_from_redirect(create.headers["location"])

    resp = logged_in_client.post(f"/people/{person_id}/tags", data={"tag_name": "climbing buddy"}, follow_redirects=False)
    assert resp.status_code == 303

    detail = logged_in_client.get(f"/people/{person_id}")
    assert "climbing buddy" in detail.text


def test_add_notable_date(logged_in_client):
    create = logged_in_client.post("/people/new", data={"name": "Anniversary Person"}, follow_redirects=False)
    person_id = _extract_person_id_from_redirect(create.headers["location"])

    resp = logged_in_client.post(
        f"/people/{person_id}/notable-dates",
        data={"label": "Anniversary", "month": 6, "day": 15},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    detail = logged_in_client.get(f"/people/{person_id}")
    assert "Anniversary" in detail.text
    assert "6/15" in detail.text


def test_journal_entry_cross_tagging_shows_on_both_profiles(logged_in_client):
    p1 = _extract_person_id_from_redirect(
        logged_in_client.post("/people/new", data={"name": "Alice"}, follow_redirects=False).headers["location"]
    )
    p2 = _extract_person_id_from_redirect(
        logged_in_client.post("/people/new", data={"name": "Bob"}, follow_redirects=False).headers["location"]
    )

    resp = logged_in_client.post(
        "/journal/new",
        data={
            "body": "Hung out with both of them at the park.",
            "entry_date": "2024-06-01",
            "event_type": "hangout",
            "person_ids": [p1, p2],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    alice_page = logged_in_client.get(f"/people/{p1}")
    bob_page = logged_in_client.get(f"/people/{p2}")
    assert "Hung out with both of them at the park." in alice_page.text
    assert "Hung out with both of them at the park." in bob_page.text
    # Each profile's timeline should mention the *other* tagged person too.
    assert "Bob" in alice_page.text
    assert "Alice" in bob_page.text


def test_journal_entry_with_no_people_still_saves(logged_in_client):
    resp = logged_in_client.post(
        "/journal/new",
        data={"body": "Just a personal thought, not about anyone specific.", "entry_date": "2024-06-01",
              "event_type": "note"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_quick_create_person_endpoint_returns_checkbox_partial(logged_in_client):
    resp = logged_in_client.post("/people/quick-create", data={"quick_name": "Instant Person"})
    assert resp.status_code == 200
    assert "Instant Person" in resp.text

    # And the person should now actually exist in the full list.
    people_list = logged_in_client.get("/people")
    assert "Instant Person" in people_list.text


def test_delete_journal_entry(logged_in_client):
    person_id = _extract_person_id_from_redirect(
        logged_in_client.post("/people/new", data={"name": "Deletable Entry Person"}, follow_redirects=False).headers["location"]
    )
    logged_in_client.post(
        "/journal/new",
        data={"body": "Temporary entry", "entry_date": "2024-06-01", "event_type": "note",
              "person_ids": [person_id]},
    )
    detail = logged_in_client.get(f"/people/{person_id}")
    assert "Temporary entry" in detail.text

    match = re.search(r"/journal/(\d+)/delete", detail.text)
    assert match, "expected a delete form action for the journal entry"
    entry_id = match.group(1)

    resp = logged_in_client.post(f"/journal/{entry_id}/delete", follow_redirects=False)
    assert resp.status_code == 303

    detail_after = logged_in_client.get(f"/people/{person_id}")
    assert "Temporary entry" not in detail_after.text
