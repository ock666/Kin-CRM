import datetime as dt


def test_reviews_page_loads_empty(logged_in_client):
    resp = logged_in_client.get("/reviews")
    assert resp.status_code == 200
    assert "Review queue" in resp.text


def test_run_now_generates_birthday_draft_for_upcoming_birthday(logged_in_client):
    upcoming = dt.date.today() + dt.timedelta(days=1)
    resp = logged_in_client.post(
        "/people/new",
        data={"name": "Birthday Person", "birthday_month": upcoming.month, "birthday_day": upcoming.day},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    run_resp = logged_in_client.post("/reviews/run-now", follow_redirects=False)
    assert run_resp.status_code == 303

    reviews_page = logged_in_client.get("/reviews")
    assert "Birthday Person" in reviews_page.text
    assert "Happy birthday" in reviews_page.text or "happy birthday" in reviews_page.text.lower()


def test_run_now_does_not_duplicate_drafts(logged_in_client):
    upcoming = dt.date.today() + dt.timedelta(days=1)
    logged_in_client.post(
        "/people/new",
        data={"name": "No Duplicate Person", "birthday_month": upcoming.month, "birthday_day": upcoming.day},
    )
    logged_in_client.post("/reviews/run-now")
    logged_in_client.post("/reviews/run-now")

    reviews_page = logged_in_client.get("/reviews")
    assert reviews_page.text.count("No Duplicate Person") == 1


def test_dismiss_birthday_draft(logged_in_client):
    upcoming = dt.date.today() + dt.timedelta(days=1)
    logged_in_client.post(
        "/people/new",
        data={"name": "Dismissable Person", "birthday_month": upcoming.month, "birthday_day": upcoming.day},
    )
    logged_in_client.post("/reviews/run-now")

    page = logged_in_client.get("/reviews")
    import re
    match = re.search(r"/reviews/birthday/(\d+)/dismiss", page.text)
    assert match, "expected a dismiss action for the generated draft"
    draft_id = match.group(1)

    resp = logged_in_client.post(f"/reviews/birthday/{draft_id}/dismiss", follow_redirects=False)
    assert resp.status_code == 303

    page_after = logged_in_client.get("/reviews")
    assert "Dismissable Person" not in page_after.text
