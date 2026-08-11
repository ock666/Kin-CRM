"""Tests for template_quick_replies fallback generator and /ai quick-replies endpoint."""
import datetime as dt

from app.models import Person, ScratchpadItem, NotablePersonRef, NotableDate
from app.services.replies import template_quick_replies, GENERIC


def test_template_quick_replies_empty_profile():
    p = Person(name="Empty Person")
    p.scratchpad_items = []
    p.notable_people_refs = []
    p.notable_dates = []
    scripts = template_quick_replies(p)
    assert len(scripts) == 3
    assert all(s in GENERIC for s in scripts)


def test_template_quick_replies_scratchpad():
    p = Person(name="Scratch Person")
    p.scratchpad_items = [ScratchpadItem(text="Ask how her vet visit went", person_id=1)]
    p.notable_people_refs = []
    p.notable_dates = []
    scripts = template_quick_replies(p)
    assert len(scripts) == 3
    assert any("vet visit" in s.lower() for s in scripts)


def test_template_quick_replies_scratchpad_strips_ask_prefix():
    p = Person(name="Prefix Person")
    p.scratchpad_items = [ScratchpadItem(text="ask how the interview went", person_id=1)]
    p.notable_people_refs = []
    p.notable_dates = []
    scripts = template_quick_replies(p)
    assert len(scripts) == 3
    assert any("interview" in s.lower() for s in scripts)
    assert not any("ask how" in s for s in scripts)


def test_template_quick_replies_hobbies():
    p = Person(name="Hobby Person", hobbies="climbing, baking")
    p.scratchpad_items = []
    p.notable_people_refs = []
    p.notable_dates = []
    scripts = template_quick_replies(p)
    assert len(scripts) == 3
    assert any("climbing" in s.lower() for s in scripts)


def test_template_quick_replies_how_we_met():
    p = Person(name="Met Person", how_we_met="at a concert")
    p.scratchpad_items = []
    p.notable_people_refs = []
    p.notable_dates = []
    scripts = template_quick_replies(p)
    assert len(scripts) == 3
    assert any("concert" in s.lower() for s in scripts)


def test_template_quick_replies_notable_people():
    p = Person(name="Notable Person")
    p.notable_people_refs = [NotablePersonRef(name="Sarah", relation="Mum", person_id=1)]
    p.scratchpad_items = []
    p.notable_dates = []
    scripts = template_quick_replies(p)
    assert len(scripts) == 3
    assert any("Sarah" in s for s in scripts)
    assert any("Mum" in s for s in scripts)


def test_template_quick_replies_notable_dates():
    p = Person(name="Notable Date Person")
    p.notable_dates = [NotableDate(label="Anniversary", month=dt.date.today().month,
                                    day=dt.date.today().day, person_id=1)]
    p.scratchpad_items = []
    p.notable_people_refs = []
    scripts = template_quick_replies(p)
    assert any("Anniversary" in s for s in scripts)


def test_template_quick_replies_days_since_over_30():
    p = Person(name="Long Person")
    p.scratchpad_items = []
    p.notable_people_refs = []
    p.notable_dates = []
    scripts = template_quick_replies(p, days_since_contact=60)
    assert len(scripts) == 3
    assert any("been a while" in s.lower() for s in scripts)


def test_template_quick_replies_caps_at_3():
    p = Person(name="Full Person", hobbies="a, b, c, d, e", how_we_met="school")
    p.scratchpad_items = [ScratchpadItem(text="ask about the trip", person_id=1)]
    p.notable_people_refs = [NotablePersonRef(name="Bob", relation="Brother", person_id=1)]
    p.notable_dates = []
    scripts = template_quick_replies(p)
    assert len(scripts) == 3


def test_quick_replies_endpoint_no_ai(logged_in_client):
    """When AI is not configured, the endpoint returns template-based scripts."""
    create = logged_in_client.post("/people/new", data={"name": "QR Person"}, follow_redirects=False)
    assert create.status_code == 303
    import re
    match = re.search(r"/people/(\d+)", create.headers["location"])
    person_id = int(match.group(1))

    resp = logged_in_client.get(f"/ai/people/{person_id}/quick-replies")
    assert resp.status_code == 200
    assert "Copy" in resp.text or "btn btn-sm" in resp.text


def test_quick_replies_endpoint_unknown_person(logged_in_client):
    resp = logged_in_client.get("/ai/people/99999/quick-replies")
    assert resp.status_code == 200
    assert "Person not found" in resp.text
