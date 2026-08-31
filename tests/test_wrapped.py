import datetime as dt
import json

from app.database import SessionLocal
from app.models import Person, JournalEntry, EventType, JournalImage, WrappedCard
from app.services import wrapped as wrapped_service

LONG_BODY = (
    "A rich, detailed account of a shared afternoon - the walk, the detour for coffee, "
    "the thing we kept laughing about hours later. Worth remembering."
)


def _mk_person(name: str, birthday=(6, 15)) -> int:
    db = SessionLocal()
    try:
        p = Person(name=name, birthday_month=birthday[0], birthday_day=birthday[1])
        db.add(p)
        db.commit()
        db.refresh(p)
        return p.id
    finally:
        db.close()


def _mk_entry(person_ids, year: int, month: int = 1, day: int = 1,
              title: str = "Moment", body: str = LONG_BODY,
              event_type=EventType.hangout, with_image: bool = False):
    db = SessionLocal()
    try:
        e = JournalEntry(title=title, body=body, entry_date=dt.date(year, month, day),
                         event_type=event_type)
        e.people = [db.get(Person, pid) for pid in person_ids]
        db.add(e)
        db.commit()
        db.refresh(e)
        if with_image:
            db.add(JournalImage(journal_entry_id=e.id, immich_asset_id=f"asset-{e.id}"))
            db.commit()
        return e.id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Payload computation
# ---------------------------------------------------------------------------


def test_payload_excludes_conflicts(app):
    p1 = _mk_person("Ava")
    _mk_entry([p1], 2026, event_type=EventType.conflict, body="A tense thing happened " * 5)
    _mk_entry([p1], 2026, event_type=EventType.hangout, title="Nice lunch")
    db = SessionLocal()
    try:
        payload = wrapped_service.build_payload(db, 2026)
        assert payload["stats"]["entries"] == 1
        assert payload["stats"]["hangouts"] == 1
        assert "conflict" not in payload["stats"]
        assert all(m["event_type"] != "conflict" for m in payload["moments"])
    finally:
        db.close()


def test_payload_ignores_other_years(app):
    p1 = _mk_person("Ava")
    _mk_entry([p1], 2025, title="Last year")
    _mk_entry([p1], 2026, title="This year")
    db = SessionLocal()
    try:
        payload = wrapped_service.build_payload(db, 2026)
        titles = [m["title"] for m in payload["moments"]]
        assert "This year" in titles
        assert "Last year" not in titles
    finally:
        db.close()


def test_moment_scoring_filters_short_photo_less_notes(app):
    p1 = _mk_person("Ava")
    _mk_entry([p1], 2026, title="tiny", body="", event_type=EventType.note)
    _mk_entry([p1], 2026, title="big", event_type=EventType.milestone, with_image=True)
    db = SessionLocal()
    try:
        payload = wrapped_service.build_payload(db, 2026)
        titles = [m["title"] for m in payload["moments"]]
        assert "big" in titles
        assert "tiny" not in titles
    finally:
        db.close()


def test_top_people_ranked_by_activity(app):
    p1 = _mk_person("Close Friend")
    p2 = _mk_person("Distant")
    for i in range(4):
        _mk_entry([p1], 2026, month=(i % 12) + 1, title=f"with close friend {i}")
    _mk_entry([p2], 2026, title="only one with distant")
    db = SessionLocal()
    try:
        payload = wrapped_service.build_payload(db, 2026)
        assert payload["people"], "expected at least one person ranked"
        assert payload["people"][0]["name"] == "Close Friend"
        assert all(p["name"] != "Distant" for p in payload["people"])
        assert payload["stats"]["people_count"] == 2
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Card lifecycle
# ---------------------------------------------------------------------------


def test_generate_card_idempotent_with_fresh_token(app):
    p1 = _mk_person("Ava")
    _mk_entry([p1], 2026)
    db = SessionLocal()
    try:
        card1, created1 = wrapped_service.generate_card(db, 2026, today=dt.date(2026, 12, 16))
        assert created1 is True
        assert card1.token
        old_token = card1.token
        data1 = json.loads(card1.data_json)
        assert data1["year"] == 2026
        assert data1["summary"] is None  # deterministic-only when no AI configured

        card2, created2 = wrapped_service.generate_card(db, 2026, today=dt.date(2026, 12, 20))
        assert created2 is False
        assert db.query(WrappedCard).filter_by(year=2026).count() == 1
        assert card2.token != old_token  # refreshing rotates the share token
    finally:
        db.close()


def test_generate_if_due_respects_season_and_flag(app):
    db = SessionLocal()
    try:
        card, gen = wrapped_service.generate_if_due(db, today=dt.date(2026, 12, 15))
        assert card is None and gen is False

        card, gen = wrapped_service.generate_if_due(db, today=dt.date(2026, 12, 16))
        assert gen is True and card is not None

        _, gen2 = wrapped_service.generate_if_due(db, today=dt.date(2026, 12, 20))
        assert gen2 is False  # flagged, never regenerated in the same year
    finally:
        db.close()


def test_fresh_card_expires(app):
    db = SessionLocal()
    try:
        wrapped_service.generate_card(db, 2026, today=dt.date(2026, 12, 16))
        # anchor created_at to the season so the expiry math is deterministic
        card = db.query(WrappedCard).filter_by(year=2026).first()
        card.created_at = dt.datetime(2026, 12, 16)
        db.commit()
        assert wrapped_service.get_fresh_card(db, 2026, today=dt.date(2026, 12, 25)) is not None

        card.created_at = dt.datetime(2026, 11, 1)
        db.commit()
        assert wrapped_service.get_fresh_card(db, 2026, today=dt.date(2026, 12, 16)) is None
    finally:
        db.close()


def test_cleanup_expired_deletes_old_cards(app):
    db = SessionLocal()
    try:
        wrapped_service.generate_card(db, 2026, today=dt.date(2026, 12, 16))
        card = db.query(WrappedCard).filter_by(year=2026).first()
        card.created_at = dt.datetime.utcnow() - dt.timedelta(days=40)
        db.commit()
        assert wrapped_service.cleanup_expired(db, today=dt.date(2026, 12, 20)) == 1
        assert db.query(WrappedCard).filter_by(year=2026).count() == 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Web routes
# ---------------------------------------------------------------------------


def test_wrapped_page_empty_state(logged_in_client):
    resp = logged_in_client.get("/wrapped")
    assert resp.status_code == 200
    assert "Kin Wrapped" in resp.text
    # sidebar link is hidden until a card actually exists
    assert 'href="/wrapped"' not in resp.text


def test_nav_shows_after_generation(logged_in_client):
    db = SessionLocal()
    try:
        p = Person(name="Ada")
        db.add(p)
        db.commit()
        db.refresh(p)
        e = JournalEntry(title="Big day", body=LONG_BODY, entry_date=dt.date.today(),
                         event_type=EventType.milestone)
        e.people = [p]
        db.add(e)
        db.commit()
        wrapped_service.generate_card(db, dt.date.today().year, today=dt.date.today())
    finally:
        db.close()
    resp = logged_in_client.get("/wrapped")
    assert resp.status_code == 200
    assert 'href="/wrapped"' in resp.text
    assert "Kin Wrapped" in resp.text


def test_dev_generate_hook(logged_in_client):
    resp = logged_in_client.post("/wrapped/generate", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/wrapped"

    page = logged_in_client.get("/wrapped")
    assert "Share this card" in page.text

    # regenerating keeps a single card and never sets the once-per-year flag
    logged_in_client.post("/wrapped/generate", follow_redirects=False)
    db = SessionLocal()
    try:
        assert db.query(WrappedCard).filter_by(year=dt.date.today().year).count() == 1
        from app.settings_store import get_setting
        from app.services.wrapped import _generated_flag
        assert get_setting(db, _generated_flag(dt.date.today().year), "0") == "0"
    finally:
        db.close()


def test_wrapped_page_shows_card(logged_in_client):
    db = SessionLocal()
    try:
        p = Person(name="Ada Lovelace")
        db.add(p)
        db.commit()
        db.refresh(p)
        e = JournalEntry(title="Big day", body=LONG_BODY,
                         entry_date=dt.date.today(), event_type=EventType.milestone)
        e.people = [p]
        db.add(e)
        db.commit()
        wrapped_service.generate_card(db, dt.date.today().year, today=dt.date.today())
    finally:
        db.close()
    resp = logged_in_client.get("/wrapped")
    assert resp.status_code == 200
    assert "Big day" in resp.text
    assert "Share this card" in resp.text


def test_share_link_public_and_content(logged_in_client):
    db = SessionLocal()
    try:
        p = Person(name="Grace Hopper")
        db.add(p)
        db.commit()
        db.refresh(p)
        e = JournalEntry(title="Camping trip", body="spent a weekend camping together " * 4,
                         entry_date=dt.date.today(), event_type=EventType.hangout)
        e.people = [p]
        db.add(e)
        db.commit()
        card, _ = wrapped_service.generate_card(db, dt.date.today().year)
        token = card.token
    finally:
        db.close()
    resp = logged_in_client.get(f"/wrapped/share/{token}")
    assert resp.status_code == 200
    assert "Camping trip" in resp.text
    assert "Save as image" in resp.text
    # share page must not expose the app shell
    assert "Log out" not in resp.text


def test_share_link_404_when_expired(logged_in_client):
    db = SessionLocal()
    try:
        p = Person(name="Ada")
        db.add(p)
        db.commit()
        db.refresh(p)
        e = JournalEntry(title="Old", body=LONG_BODY, entry_date=dt.date.today(),
                         event_type=EventType.milestone)
        e.people = [p]
        db.add(e)
        db.commit()
        card, _ = wrapped_service.generate_card(db, dt.date.today().year)
        token = card.token
        card.created_at = dt.datetime.utcnow() - dt.timedelta(days=40)
        db.commit()
    finally:
        db.close()
    assert logged_in_client.get(f"/wrapped/share/{token}").status_code == 404


def test_share_link_bad_token_404(logged_in_client):
    assert logged_in_client.get("/wrapped/share/not-a-real-token").status_code == 404


def test_share_asset_proxy_404_without_immich(logged_in_client):
    db = SessionLocal()
    try:
        p = Person(name="Ada")
        db.add(p)
        db.commit()
        db.refresh(p)
        e = JournalEntry(title="With photo", body=LONG_BODY, entry_date=dt.date.today(),
                         event_type=EventType.milestone)
        e.people = [p]
        db.add(e)
        db.commit()
        db.add(JournalImage(journal_entry_id=e.id, immich_asset_id="abc123"))
        db.commit()
        card, _ = wrapped_service.generate_card(db, dt.date.today().year)
        token = card.token
    finally:
        db.close()
    # valid token + valid-looking asset, but no Immich configured -> 404, not an auth error
    resp = logged_in_client.get(f"/wrapped/share/{token}/asset/abc123/thumbnail")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Per-person "Our year with {Name}" shares
# ---------------------------------------------------------------------------


def _mk_person_entries(name: str, count: int) -> int:
    p_id = _mk_person(name)
    db = SessionLocal()
    try:
        p = db.get(Person, p_id)
        for i in range(count):
            e = JournalEntry(title=f"{name} moment {i + 1}", body=LONG_BODY,
                             entry_date=dt.date(dt.date.today().year, (i % 6) + 1, 3),
                             event_type=EventType.hangout)
            e.people = [p]
            db.add(e)
        db.commit()
    finally:
        db.close()
    return p_id


def test_person_share_eligibility_requires_three_moments(app):
    two = _mk_person_entries("Two Moments", 2)
    three = _mk_person_entries("Three Moments", 3)
    db = SessionLocal()
    try:
        year = dt.date.today().year
        assert wrapped_service.is_person_share_eligible(db, db.get(Person, two), year) is False
        assert wrapped_service.is_person_share_eligible(db, db.get(Person, three), year) is True
    finally:
        db.close()


def test_generate_person_share_idempotent_and_rotates_token(app):
    p_id = _mk_person_entries("Ada", 3)
    db = SessionLocal()
    try:
        year = dt.date.today().year
        person = db.get(Person, p_id)
        share1, created1 = wrapped_service.generate_person_share(db, person, year)
        assert created1 is True
        old_token = share1.token
        share2, created2 = wrapped_service.generate_person_share(db, person, year)
        assert created2 is False
        assert share2.token != old_token
        from app.models import WrappedPersonShare
        assert db.query(WrappedPersonShare).filter_by(person_id=p_id, year=year).count() == 1
        payload = json.loads(share2.data_json)
        assert payload["name"] == "Ada"
        assert all(m["title"].startswith("Ada") for m in payload["moments"])
    finally:
        db.close()


def test_person_preview_requires_season(logged_in_client):
    p_id = _mk_person_entries("Ada", 3)
    # no wrapped card yet -> not in season -> preview bounces away
    resp = logged_in_client.get(f"/wrapped/person/{p_id}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/wrapped"


def test_person_preview_shows_card_and_link(logged_in_client):
    p_id = _mk_person_entries("Ada", 3)
    db = SessionLocal()
    try:
        wrapped_service.generate_card(db, dt.date.today().year, today=dt.date.today())
    finally:
        db.close()
    resp = logged_in_client.get(f"/wrapped/person/{p_id}")
    assert resp.status_code == 200
    assert "Our year with Ada" in resp.text
    assert "Share this card" in resp.text


def test_person_share_public_card_only_that_person(logged_in_client):
    p_id = _mk_person_entries("Ada", 3)
    _mk_person_entries("Bob", 3)
    db = SessionLocal()
    try:
        wrapped_service.generate_card(db, dt.date.today().year, today=dt.date.today())
        person = db.get(Person, p_id)
        share, _ = wrapped_service.generate_person_share(db, person, dt.date.today().year)
        token = share.token
    finally:
        db.close()
    resp = logged_in_client.get(f"/wrapped/share/person/{token}")
    assert resp.status_code == 200
    assert "Ada" in resp.text
    assert "Ada moment 1" in resp.text
    assert "Moments we shared" in resp.text
    assert "Bob" not in resp.text  # never leaks other people
    assert "Log out" not in resp.text  # standalone card, no app shell


def test_person_share_404_after_season_ends(logged_in_client):
    p_id = _mk_person_entries("Ada", 3)
    db = SessionLocal()
    try:
        card, _ = wrapped_service.generate_card(db, dt.date.today().year, today=dt.date.today())
        person = db.get(Person, p_id)
        share, _ = wrapped_service.generate_person_share(db, person, dt.date.today().year)
        token = share.token
        # season over: main card expires
        card.created_at = dt.datetime.utcnow() - dt.timedelta(days=40)
        db.commit()
    finally:
        db.close()
    assert logged_in_client.get(f"/wrapped/share/person/{token}").status_code == 404
    assert logged_in_client.get(f"/wrapped/person/{p_id}", follow_redirects=False).status_code == 303


def test_person_profile_button_season_and_eligibility(logged_in_client):
    eligible = _mk_person_entries("Ada", 3)
    db = SessionLocal()
    try:
        wrapped_service.generate_card(db, dt.date.today().year, today=dt.date.today())
    finally:
        db.close()
    assert "Share our year" in logged_in_client.get(f"/people/{eligible}").text


def test_person_profile_button_hidden_without_eligibility(logged_in_client):
    too_few = _mk_person_entries("Mia", 2)
    db = SessionLocal()
    try:
        wrapped_service.generate_card(db, dt.date.today().year, today=dt.date.today())
    finally:
        db.close()
    assert "Share our year" not in logged_in_client.get(f"/people/{too_few}").text


def test_cleanup_prunes_person_shares(app):
    p_id = _mk_person_entries("Ada", 3)
    db = SessionLocal()
    try:
        wrapped_service.generate_card(db, dt.date.today().year, today=dt.date.today())
        wrapped_service.generate_person_share(db, db.get(Person, p_id), dt.date.today().year)
        from app.models import WrappedPersonShare
        share = db.query(WrappedPersonShare).first()
        share.created_at = dt.datetime.utcnow() - dt.timedelta(days=40)
        db.commit()
        assert wrapped_service.cleanup_expired(db, today=dt.date.today()) == 1
        assert db.query(WrappedPersonShare).count() == 0
    finally:
        db.close()
