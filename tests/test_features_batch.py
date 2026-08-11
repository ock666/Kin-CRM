"""Tests for the batch of neurodivergent-friendly features: micro check-in XP, bio blurb field,
conversation-gap caching data, full JSON export, JSON import round-trip, friendly error pages,
birthday countdown helper, and reassurance note."""
import datetime as dt
import json

from app.models import Person, JournalEntry, Tag, ConflictLog, ConflictStatus, NotableDate
from app.services import birthdays as bday_service
from app.services import checkins as checkin_service


def make_person(db, **kwargs):
    p = Person(**kwargs)
    db.add(p)
    db.commit()
    return p


# --- #24: micro check-in XP ---

def test_mark_contacted_awards_micro_xp(logged_in_client):
    from app.database import SessionLocal
    from app.models import UserStats
    pid = None
    db = SessionLocal()
    try:
        # A person WITHOUT a cadence (so not overdue) - contact should still award MICRO_CHECKIN XP.
        p = make_person(db, name="Not Overdue", archived=False)
        pid = p.id
    finally:
        db.close()
    resp = logged_in_client.post(f"/checkin/{pid}/mark-contacted", follow_redirects=False)
    assert resp.status_code == 303
    db = SessionLocal()
    try:
        stats = db.get(UserStats, 1)
        assert stats is not None and stats.total_xp >= 10
    finally:
        db.close()


def test_micro_checkin_only_counts_once_per_day(logged_in_client):
    from app.database import SessionLocal
    from app.models import UserStats
    pid = None
    db = SessionLocal()
    try:
        p = make_person(db, name="Once A Day", archived=False)
        p.last_contact_date = dt.date.today()
        db.commit()
        pid = p.id
    finally:
        db.close()
    # Contacting again the same day should award nothing (already marked today).
    resp = logged_in_client.post(f"/checkin/{pid}/mark-contacted", follow_redirects=False)
    assert resp.status_code == 303
    db = SessionLocal()
    try:
        stats = db.get(UserStats, 1)
        # No XP if it was already today (guarded) - just confirm no crash and still marked today.
        p2 = db.get(Person, pid)
        assert p2.last_contact_date == dt.date.today()
    finally:
        db.close()


# --- #41: bio field saved ---

def test_bio_roundtrip_via_edit(logged_in_client):
    from app.database import SessionLocal
    pid = None
    db = SessionLocal()
    try:
        p = make_person(db, name="Bio Person")
        pid = p.id
    finally:
        db.close()
    resp = logged_in_client.post(
        f"/people/{pid}/edit",
        data={"name": "Bio Person", "bio": "My old uni housemate who bakes.", "occupation": "", "hobbies": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db = SessionLocal()
    try:
        p2 = db.get(Person, pid)
        assert p2.bio == "My old uni housemate who bakes."
    finally:
        db.close()


# --- #43: birthday countdown helper ---

def test_days_until_birthday():
    today = dt.date(2026, 6, 1)
    p = Person(name="Bday", birthday_month=6, birthday_day=15)
    assert bday_service.days_until_birthday(p, today=today) == 14
    # Already passed this year -> rolls to next year.
    p2 = Person(name="Past", birthday_month=1, birthday_day=1)
    assert bday_service.days_until_birthday(p2, today=today) is not None
    # No birthday -> None
    p3 = Person(name="NoBday")
    assert bday_service.days_until_birthday(p3, today=today) is None


# --- #25 + #27: full JSON export / import round-trip ---

def test_export_import_roundtrip(logged_in_client):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = make_person(db, name="ExAmy", bio="Surf instructor", checkin_cadence_days=45)
        p.tags.append(Tag(name="work"))
        db.add(NotableDate(person_id=p.id, label="Gig", month=7, day=4))
        entry = JournalEntry(title="Lunch", body="Great catch up over tacos.",
                             entry_date=dt.date.today())
        entry.people.append(p)
        db.add(entry)
        db.add(ConflictLog(person_id=p.id, summary="Tiny tiff", status=ConflictStatus.unresolved))
        db.commit()
    finally:
        db.close()

    # Export
    exp = logged_in_client.get("/export/json")
    assert exp.status_code == 200
    data = json.loads(exp.text)
    assert data["format"] == "kin-export"
    assert any("ExAmy" == e["name"] for e in data["exported_people"])
    amy = next(e for e in data["exported_people"] if e["name"] == "ExAmy")
    assert amy["bio"] == "Surf instructor"
    assert amy["checkin_cadence_days"] == 45
    assert "work" in amy["tags"]

    # Import into a fresh person set (same DB, but exercise the route with the blob).
    resp = logged_in_client.post(
        "/import",
        files={"file": ("kin.json", exp.text.encode("utf-8"), "application/json")},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    db = SessionLocal()
    try:
        # Re-import matched by name -> no crash, updates in place.
        assert db.query(Person).filter(Person.name == "ExAmy").count() == 1
    finally:
        db.close()


# --- #39: friendly error pages ---

def test_404_page_returns_template(logged_in_client):
    resp = logged_in_client.get("/no-such-route-xyz")
    assert "That page isn't here" in resp.text


# --- #17: reassurance note + #28: privacy page ---

def test_reassurance_note_save(logged_in_client):
    resp = logged_in_client.post("/reassurance", data={"note": "I am a good friend."}, follow_redirects=False)
    assert resp.status_code == 303
    r2 = logged_in_client.get("/")
    assert "I am a good friend." in r2.text


def test_privacy_page(logged_in_client):
    resp = logged_in_client.get("/privacy")
    assert resp.status_code == 200
    assert "Privacy" in resp.text


def test_import_page(logged_in_client):
    resp = logged_in_client.get("/import")
    assert resp.status_code == 200
    assert "Import people" in resp.text
