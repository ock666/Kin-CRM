"""Tests for Immich hangout detection: the service, the dashboard card, and the
auto-credit that clears a check-in nudge when a face was photographed recently."""
import datetime as dt

import pytest

from app.models import Person, JournalEntry, JournalImage
from app.services.hangouts import detect_recent_hangouts
from app.services.immich_client import ImmichError


class FakeImmichClient:
    """Stand-in for ImmichClient exposing only what hangout detection uses."""

    def __init__(self, by_person=None):
        self.by_person = by_person or {}

    def search_by_person(self, person_id, taken_after=None, taken_before=None, size=100):
        if isinstance(self.by_person.get(person_id), Exception):
            raise self.by_person[person_id]
        return self.by_person.get(person_id, [])


def _asset(asset_id, local_dt, year=None):
    # year mirrors what Immich returns; only localDateTime is used for filtering
    return {"id": asset_id, "localDateTime": local_dt, "year": year}


def _person(db, name, immich_id="face-1", **kw):
    defaults = dict(name=name, immich_person_id=immich_id, archived=False)
    defaults.update(kw)
    p = Person(**defaults)
    db.add(p)
    db.commit()
    return p


def _run(db, client, **kw):
    from app.database import SessionLocal
    s = SessionLocal()
    try:
        return detect_recent_hangouts(s, client, **kw)
    finally:
        s.close()


# --- Service-level -------------------------------------------------------------

def test_detects_hangout_and_uses_local_datetime(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = _person(db, "Alex", "face-1")
        now = dt.datetime.now(dt.timezone.utc)
        client = FakeImmichClient({
            "face-1": [
                _asset("a1", "2020-01-01T12:00:00"),
                _asset("a2", (now - dt.timedelta(days=2)).strftime("%Y-%m-%dT18:00:00")),
            ]
        })
        hangouts, err = detect_recent_hangouts(db, client)
        assert err is None
        assert len(hangouts) == 1
        assert hangouts[0]["person"].id == p.id
        assert hangouts[0]["label"] == "2 days ago"
        assert hangouts[0]["thumbnails"][0] == "a2"
    finally:
        db.close()


def test_ignores_assets_older_than_window(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        _person(db, "Old Face", "face-old")
        client = FakeImmichClient({
            "face-old": [_asset("old", (dt.date.today() - dt.timedelta(days=40)).strftime("%Y-%m-%dT12:00:00"))]
        })
        hangouts, err = detect_recent_hangouts(db, client)
        assert hangouts == []
        assert err is None
    finally:
        db.close()


def test_skips_person_without_face_link_and_unlinked(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        _person(db, "No Face", immich_id=None)
        _person(db, "Linked", "face-1")
        now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT12:00:00")
        client = FakeImmichClient({"face-1": [_asset("a1", now)]})
        hangouts, _ = detect_recent_hangouts(db, client)
        assert [h["person"].name for h in hangouts] == ["Linked"]
    finally:
        db.close()


def test_skips_archived_people(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        _person(db, "Gone", "face-gone", archived=True)
        client = FakeImmichClient({"face-gone": [_asset("a1", dt.date.today().strftime("%Y-%m-%dT12:00:00"))]})
        hangouts, _ = detect_recent_hangouts(db, client)
        assert hangouts == []
    finally:
        db.close()


def test_tolerates_per_person_errors(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        _person(db, "Broken", "face-broken")
        _person(db, "Fine", "face-fine")
        client = FakeImmichClient({
            "face-broken": ImmichError("boom"),
            "face-fine": [_asset("a1", dt.date.today().strftime("%Y-%m-%dT12:00:00"))],
        })
        hangouts, err = detect_recent_hangouts(db, client)
        assert err is None
        assert [h["person"].name for h in hangouts] == ["Fine"]
    finally:
        db.close()


def test_sorts_newest_first_and_caps_thumbnails(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        _person(db, "Newer", "face-new")
        _person(db, "Older", "face-old")
        client = FakeImmichClient({
            "face-new": [_asset(f"n{i}", dt.date.today().strftime("%Y-%m-%dT12:00:00")) for i in range(8)],
            "face-old": [_asset("o1", (dt.date.today() - dt.timedelta(days=20)).strftime("%Y-%m-%dT12:00:00"))],
        })
        hangouts, _ = detect_recent_hangouts(db, client)
        assert [h["person"].name for h in hangouts] == ["Newer", "Older"]
        assert len(hangouts[0]["thumbnails"]) == 6
    finally:
        db.close()


def test_relative_labels(app):
    from app.database import SessionLocal
    from app.services.hangouts import _relative_label
    db = SessionLocal()
    try:
        today = dt.date(2026, 8, 25)
        assert _relative_label(today, today) == "today"
        assert _relative_label(today - dt.timedelta(days=1), today) == "yesterday"
        assert _relative_label(today - dt.timedelta(days=5), today) == "5 days ago"
        assert _relative_label(today - dt.timedelta(days=14), today) == "2 weeks ago"
        assert _relative_label(today - dt.timedelta(days=40), today) == "2026-07-16"
    finally:
        db.close()


# --- Dashboard integration -----------------------------------------------------

@pytest.fixture()
def fake_dashboard(monkeypatch):
    """Point the dashboard's Immich hooks at fake implementations."""
    from app.routers import dashboard

    class _Client:
        def on_this_day_with_fallback(self):
            return []

    monkeypatch.setattr(dashboard, "immich_from_settings", lambda db: _Client())
    return monkeypatch


def _make_overdue_person(db, name="Alex", immich_id="face-1", hangout_days_ago=3):
    p = Person(
        name=name,
        immich_person_id=immich_id,
        checkin_cadence_days=30,
        last_contact_date=dt.date.today() - dt.timedelta(days=60),
        checkin_snoozed_until=dt.date.today() + dt.timedelta(days=7),
    )
    db.add(p)
    db.commit()
    return p


def test_dashboard_renders_hangout_card_and_credits(app, logged_in_client, fake_dashboard):
    from app.routers import dashboard
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = _make_overdue_person(db)
        hangout_date = dt.date.today() - dt.timedelta(days=3)
        fake_dashboard.setattr(dashboard, "get_recent_hangouts_cached",
                               lambda db_, client: ([{
                                   "person": db_.get(Person, p.id),
                                   "latest_date": hangout_date,
                                   "label": "3 days ago",
                                   "thumbnails": ["thumb-1"],
                                   "new_asset_ids": ["thumb-1"],
                                   "all_logged": False,
                                   "existing_entry": None,
                                   "dismissed": False,
                               }], None))

        resp = logged_in_client.get("/")
        assert resp.status_code == 200
        assert "Looks like you hung out" in resp.text
        assert "Alex" in resp.text

        db.refresh(p)
        assert p.last_contact_date == hangout_date
        assert p.checkin_snoozed_until is None
    finally:
        db.close()


def test_dashboard_replaces_overdue_row(app, logged_in_client, fake_dashboard):
    from app.routers import dashboard
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = _make_overdue_person(db)
        # Hangout older than the person's cadence: still removes them from the nudge list
        hangout_date = dt.date.today() - dt.timedelta(days=20)
        fake_dashboard.setattr(dashboard, "get_recent_hangouts_cached",
                               lambda db_, client: ([{
                                   "person": db_.get(Person, p.id),
                                   "latest_date": hangout_date,
                                   "label": "2 weeks ago",
                                   "thumbnails": [],
                                   "new_asset_ids": [],
                                   "all_logged": False,
                                   "existing_entry": None,
                                   "dismissed": False,
                               }], None))

        resp = logged_in_client.get("/")
        page = resp.text
        # Person appears in the hangout card but not in the "Time to reach out" list
        assert "Looks like you hung out" in page
        assert "Time to reach out" in page
        assert page.count(">Alex<") == 1
        assert "Caught up" not in page
    finally:
        db.close()


def test_dashboard_does_not_regress_last_contact(app, logged_in_client, fake_dashboard):
    from app.routers import dashboard
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = _make_overdue_person(db)
        p.last_contact_date = dt.date.today() - dt.timedelta(days=1)
        db.commit()
        hangout_date = dt.date.today() - dt.timedelta(days=3)
        fake_dashboard.setattr(dashboard, "get_recent_hangouts_cached",
                               lambda db_, client: ([{
                                   "person": db_.get(Person, p.id),
                                   "latest_date": hangout_date,
                                   "label": "3 days ago",
                                   "thumbnails": [],
                                   "new_asset_ids": [],
                                   "all_logged": False,
                                   "existing_entry": None,
                                   "dismissed": False,
                               }], None))

        logged_in_client.get("/")
        db.refresh(p)
        assert p.last_contact_date == dt.date.today() - dt.timedelta(days=1)
    finally:
        db.close()


def test_dashboard_without_immich_shows_no_hangout_error(app, logged_in_client):
    """When Immich isn't configured the dashboard still loads; no hangout card, no crash."""
    resp = logged_in_client.get("/")
    assert resp.status_code == 200
    assert "Looks like you hung out" not in resp.text


# --- Dedup detection (the Paige case: photo already on the person's timeline) ---

def _attach(db, person, entry_date, asset_ids, title=None):
    e = JournalEntry(title=title, body="Hung out.", entry_date=entry_date)
    e.people.append(person)
    db.add(e)
    db.flush()
    for aid in asset_ids:
        db.add(JournalImage(journal_entry_id=e.id, immich_asset_id=aid))
    db.commit()
    return e


def test_marks_already_logged_when_all_photos_on_profile(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = _person(db, "Paige", "face-paige")
        _attach(db, p, dt.date.today() - dt.timedelta(days=7), ["a6d60f47"], title="Date Night with Paige")
        client = FakeImmichClient({
            "face-paige": [_asset("a6d60f47", (dt.date.today() - dt.timedelta(days=7)).strftime("%Y-%m-%dT17:21:00"))]
        })
        hangouts, _ = detect_recent_hangouts(db, client)
        assert len(hangouts) == 1
        h = hangouts[0]
        assert h["all_logged"] is True
        assert h["new_asset_ids"] == []
        assert h["existing_entry"]["title"] == "Date Night with Paige"
        assert h["existing_entry"]["id"] == 1
    finally:
        db.close()


def test_partial_logging_keeps_unattached_photos(app):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = _person(db, "Casey", "face-casey")
        _attach(db, p, dt.date.today() - dt.timedelta(days=5), ["old-photo"], title="Past hangout")
        now = dt.date.today().strftime("%Y-%m-%dT12:00:00")
        client = FakeImmichClient({
            "face-casey": [_asset("old-photo", (dt.date.today() - dt.timedelta(days=5)).strftime("%Y-%m-%dT12:00:00")),
                           _asset("new-photo", now)]
        })
        hangouts, _ = detect_recent_hangouts(db, client)
        h = hangouts[0]
        assert h["all_logged"] is False
        assert h["new_asset_ids"] == ["new-photo"]
        assert h["existing_entry"]["title"] == "Past hangout"
    finally:
        db.close()


def test_unattached_asset_ids_helper(app):
    from app.database import SessionLocal
    from app.services.hangouts import unattached_asset_ids
    db = SessionLocal()
    try:
        p = _person(db, "Sam", "face-sam")
        _attach(db, p, dt.date.today(), ["dup-1"])
        result = unattached_asset_ids(db, p, ["dup-1", "fresh-1", "fresh-2"])
        assert result == ["fresh-1", "fresh-2"]
    finally:
        db.close()


# --- Log-a-hangout route -------------------------------------------------------

def test_log_hangout_creates_entry(app, logged_in_client):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = _person(db, "Alex", "face-1")
        resp = logged_in_client.post("/hangouts/log", data={
            "person_id": str(p.id),
            "entry_date": "2026-08-07",
            "asset_ids": ["photo-a", "photo-b"],
        }, follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/people/{p.id}"

        entry = db.query(JournalEntry).one()
        assert entry.event_type.value == "hangout"
        assert entry.entry_date == dt.date(2026, 8, 7)
        assert entry.body == "Hung out with Alex."
        assert [img.immich_asset_id for img in entry.images] == ["photo-a", "photo-b"]
        assert [pp.name for pp in entry.people] == ["Alex"]

        db.refresh(p)
        assert p.last_contact_date == dt.date(2026, 8, 7)
    finally:
        db.close()


def test_log_hangout_skips_duplicate_assets(app, logged_in_client):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = _person(db, "Alex", "face-1")
        _attach(db, p, dt.date.today() - dt.timedelta(days=3), ["already-there"], title="Old entry")

        logged_in_client.post("/hangouts/log", data={
            "person_id": str(p.id),
            "entry_date": "2026-08-07",
            "asset_ids": ["already-there", "brand-new"],
        }, follow_redirects=False)

        new_entry = db.query(JournalEntry).filter(JournalEntry.title.is_(None)).one()
        assert [img.immich_asset_id for img in new_entry.images] == ["brand-new"]
        assert db.query(JournalImage).filter_by(immich_asset_id="already-there").count() == 1
    finally:
        db.close()


def test_log_hangout_requires_person(app, logged_in_client):
    resp = logged_in_client.post("/hangouts/log", data={
        "person_id": "99999", "entry_date": "2026-08-07", "asset_ids": ["x"],
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


# --- Dashboard card states -----------------------------------------------------

def test_dashboard_shows_already_logged_instead_of_buttons(app, logged_in_client, fake_dashboard):
    from app.routers import dashboard
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = _make_overdue_person(db)
        hangout_date = dt.date.today() - dt.timedelta(days=7)
        fake_dashboard.setattr(dashboard, "get_recent_hangouts_cached",
                               lambda db_, client: ([{
                                   "person": db_.get(Person, p.id),
                                   "latest_date": hangout_date,
                                   "label": "1 week ago",
                                   "thumbnails": ["photo-a"],
                                   "new_asset_ids": [],
                                    "all_logged": True,
                                    "existing_entry": {"id": 6, "title": "Date Night with Alex", "entry_date": hangout_date},
                                    "dismissed": False,
                                }], None))

        page = logged_in_client.get("/").text
        assert "Already logged" in page
        assert "Date Night with Alex" in page
        assert "Quick log" not in page
        assert "Write about it" not in page
    finally:
        db.close()


def test_dashboard_shows_quick_log_and_write_buttons(app, logged_in_client, fake_dashboard):
    from app.routers import dashboard
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = _make_overdue_person(db)
        hangout_date = dt.date.today() - dt.timedelta(days=3)
        fake_dashboard.setattr(dashboard, "get_recent_hangouts_cached",
                               lambda db_, client: ([{
                                   "person": db_.get(Person, p.id),
                                   "latest_date": hangout_date,
                                   "label": "3 days ago",
                                   "thumbnails": ["photo-a"],
                                   "new_asset_ids": ["photo-a"],
                                   "all_logged": False,
                                   "existing_entry": None,
                                   "dismissed": False,
                               }], None))

        page = logged_in_client.get("/").text
        assert "Quick log" in page
        assert "Write about it" in page
        assert "/journal/new?person_id=" in page
        assert f"action=\"/hangouts/log\"" in page
    finally:
        db.close()


# --- Journal form prefill ------------------------------------------------------

def test_journal_new_prefills_hangout(app, logged_in_client):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = _person(db, "Paige", "face-paige")
        resp = logged_in_client.get(
            f"/journal/new?person_id={p.id}&event_type=hangout&entry_date=2026-08-07"
            "&immich_asset_ids=photo-a&immich_asset_ids=photo-b"
        )
        assert resp.status_code == 200
        page = " ".join(resp.text.split())  # normalize template whitespace
        assert 'name="immich_asset_ids" value="photo-a" checked' in page
        assert 'name="immich_asset_ids" value="photo-b" checked' in page
        assert '<option value="hangout" selected>' in page
        assert 'value="2026-08-07"' in page
        assert f'name="person_ids" value="{p.id}" style="width:auto;" checked' in page
    finally:
        db.close()


# --- Dismissing hangouts -------------------------------------------------------

def test_detection_marks_dismissed(app):
    from app.database import SessionLocal
    from app.models import HangoutDismissal
    db = SessionLocal()
    try:
        p = _person(db, "Alex", "face-1")
        now = dt.date.today()
        db.add(HangoutDismissal(person_id=p.id, dismissed_for_date=now))
        db.commit()
        client = FakeImmichClient({
            "face-1": [_asset("a1", now.strftime("%Y-%m-%dT12:00:00"))]
        })
        hangouts, _ = detect_recent_hangouts(db, client)
        assert hangouts[0]["dismissed"] is True
    finally:
        db.close()


def test_dashboard_hides_dismissed_hangout(app, logged_in_client, fake_dashboard):
    from app.routers import dashboard
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = _make_overdue_person(db)
        hangout_date = dt.date.today() - dt.timedelta(days=3)
        fake_dashboard.setattr(dashboard, "get_recent_hangouts_cached",
                               lambda db_, client: ([{
                                   "person": db_.get(Person, p.id),
                                   "latest_date": hangout_date,
                                   "label": "3 days ago",
                                   "thumbnails": ["photo-a"],
                                   "new_asset_ids": ["photo-a"],
                                   "all_logged": False,
                                   "existing_entry": None,
                                   "dismissed": True,
                               }], None))

        page = logged_in_client.get("/").text
        assert "Looks like you hung out" not in page
        assert "Quick log" not in page
    finally:
        db.close()


def test_dismiss_hangout_creates_dismissal(app, logged_in_client):
    from app.database import SessionLocal
    from app.models import HangoutDismissal
    db = SessionLocal()
    try:
        p = _person(db, "Alex", "face-1")
        resp = logged_in_client.post("/hangouts/dismiss", data={
            "person_id": str(p.id),
            "entry_date": "2026-08-07",
        }, follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"
        row = db.query(HangoutDismissal).one()
        assert row.person_id == p.id
        assert row.dismissed_for_date == dt.date(2026, 8, 7)
    finally:
        db.close()


def test_dismiss_is_idempotent(app, logged_in_client):
    from app.database import SessionLocal
    from app.models import HangoutDismissal
    db = SessionLocal()
    try:
        p = _person(db, "Alex", "face-1")
        logged_in_client.post("/hangouts/dismiss", data={"person_id": str(p.id), "entry_date": "2026-08-07"})
        logged_in_client.post("/hangouts/dismiss", data={"person_id": str(p.id), "entry_date": "2026-08-07"})
        assert db.query(HangoutDismissal).count() == 1
    finally:
        db.close()


# --- Review fixes: caching, nudge interplay, input validation ------------------

def test_cached_detection_reuses_immich_calls(app):
    from app.database import SessionLocal
    from app.services.hangouts import get_recent_hangouts_cached, invalidate_hangout_cache
    db = SessionLocal()
    try:
        invalidate_hangout_cache()
        _person(db, "Alex", "face-1")
        now = dt.date.today().strftime("%Y-%m-%dT12:00:00")

        class CountingClient(FakeImmichClient):
            def __init__(self):
                super().__init__({"face-1": [_asset("a1", now)]})
                self.calls = 0

            def search_by_person(self, *a, **kw):
                self.calls += 1
                return super().search_by_person(*a, **kw)

        client = CountingClient()
        h1, _ = get_recent_hangouts_cached(db, client)
        h2, _ = get_recent_hangouts_cached(db, client)
        assert client.calls == 1, "second call should hit the cache"
        assert len(h1) == 1 and len(h2) == 1
        invalidate_hangout_cache()
        h3, _ = get_recent_hangouts_cached(db, client)
        assert client.calls == 2, "invalidate should force a re-fetch"
        assert len(h3) == 1
    finally:
        db.close()


def test_log_hangout_clamps_future_date(app, logged_in_client):
    from app.database import SessionLocal
    from app.models import JournalEntry
    db = SessionLocal()
    try:
        p = _person(db, "Alex", "face-1")
        tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        logged_in_client.post("/hangouts/log", data={
            "person_id": str(p.id),
            "entry_date": tomorrow,
            "asset_ids": ["photo-a"],
        }, follow_redirects=False)
        entry = db.query(JournalEntry).one()
        assert entry.entry_date == dt.date.today()
        db.refresh(p)
        assert p.last_contact_date == dt.date.today()
    finally:
        db.close()


def test_log_hangout_requires_face_link(app, logged_in_client):
    from app.database import SessionLocal
    from app.models import JournalEntry
    db = SessionLocal()
    try:
        p = _person(db, "No Face", immich_id=None)
        resp = logged_in_client.post("/hangouts/log", data={
            "person_id": str(p.id),
            "entry_date": "2026-08-07",
            "asset_ids": ["photo-a"],
        }, follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"
        assert db.query(JournalEntry).count() == 0
    finally:
        db.close()


def test_dismissed_hangout_does_not_suppress_overdue_nudge(app, logged_in_client, fake_dashboard):
    from app.routers import dashboard
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = _make_overdue_person(db, name="Alex")
        p.checkin_cadence_days = 14
        p.checkin_snoozed_until = None
        db.commit()
        hangout_date = dt.date.today() - dt.timedelta(days=20)
        fake_dashboard.setattr(dashboard, "get_recent_hangouts_cached",
                               lambda db_, client: ([{
                                   "person": db_.get(Person, p.id),
                                   "latest_date": hangout_date,
                                   "label": "2 weeks ago",
                                   "thumbnails": [],
                                   "new_asset_ids": [],
                                   "all_logged": False,
                                   "existing_entry": None,
                                   "dismissed": True,
                               }], None))

        page = logged_in_client.get("/").text
        assert "Looks like you hung out" not in page
        assert "Time to reach out" in page
        assert "Caught up" in page  # dismissed hangout must not hide the overdue nudge
    finally:
        db.close()
