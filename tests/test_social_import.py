"""Tests for the social-data import pipeline (Instagram direct messages first).

Covers: zip parsing + layout detection, the upload -> match -> suggest flow with AI
unconfigured (must degrade gracefully and never write without an accept), and the
accept/reject fact review gate.
"""
import datetime as dt
import io
import json
import zipfile
from datetime import date

OWN = "skye_test"
DAY_MS = 86_400_000


def _ts(y, m, d):
    return int(dt.datetime(y, m, d, tzinfo=dt.timezone.utc).timestamp() * 1000)


def _conv(thread_dir, peer, msgs):
    """message_1.json-style conversation, relative to the IG export root."""
    path = f"instagram-{OWN}-2026-09-01/direct/messages/inbox/{thread_dir}/message_1.json"
    payload = {
        "participants": [OWN, peer],
        "thread_path": thread_dir,
        "title": peer,
        "messages": [
            {"sender_name": sender, "timestamp_ms": ts, "content": text}
            for sender, ts, text in msgs
        ],
    }
    return path, payload


def _group(thread_dir, members):
    path = f"instagram-{OWN}-2026-09-01/direct/messages/inbox/{thread_dir}/message_1.json"
    payload = {
        "participants": members,
        "thread_title": "Weekend plans",
        "messages": [{"sender_name": members[0], "timestamp_ms": _ts(2026, 1, 1), "content": "hey gang"}],
    }
    return path, payload


def make_zip(convs):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, payload in convs:
            zf.writestr(path, json.dumps(payload))
    return buf.getvalue()


FIXTURE_CONVS = [
    _conv("alex", "alex_johnson", [
        (OWN, _ts(2024, 3, 12), "hey! glad you got the job"),
        ("alex_johnson", _ts(2024, 3, 12), "thanks!! I start as a vet nurse Monday"),
        (OWN, _ts(2026, 8, 20), "happy you moved to Brisbane btw"),
        ("alex_johnson", _ts(2026, 8, 20), "yeah settled now, love the climbing gym here"),
    ]),
    _conv("sam", "sam_k", [
        ("sam_k", _ts(2026, 1, 5), "can't make Friday sadly"),
        (OWN, _ts(2026, 1, 6), "no worries! another time"),
    ]),
    _group("weekend", [OWN, "alex_johnson", "sam_k"]),
]


def _upload(client, payload):
    return client.post(
        "/import/social/upload",
        files={"file": (f"instagram-{OWN}-2026.zip", payload, "application/zip")},
        follow_redirects=False,
    )


def test_parse_zip_finds_direct_conversations(app):
    from app.services import social_import as svc
    import tempfile
    from pathlib import Path

    payload = make_zip(FIXTURE_CONVS)
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(payload)
        tmp_path = tmp.name
    try:
        parsed = svc.parse_instagram_zip(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    assert parsed["account_handle"] == OWN
    assert parsed["group_chats"] == 1
    directs = parsed["conversations"]
    assert len(directs) == 2
    by_peer = {c["peer_handle"]: c for c in directs}
    assert set(by_peer) == {"alex_johnson", "sam_k"}
    alex = by_peer["alex_johnson"]
    assert alex["kind"] == "direct"
    assert alex["msg_count"] == 4
    assert alex["first_ts_ms"] == _ts(2024, 3, 12)
    assert alex["last_ts_ms"] == _ts(2026, 8, 20)
    # transcript excludes nobody; samples are the most recent messages.
    assert alex["transcript"][-1][2].startswith("yeah settled")
    assert alex["samples"][-1][2].startswith("yeah settled")


def test_upload_match_and_link_flow(logged_in_client):
    resp = _upload(logged_in_client, make_zip(FIXTURE_CONVS))
    assert resp.status_code == 303
    assert resp.headers["location"] == "/import/social/matches"

    from app.database import SessionLocal
    from app.models import Person, SocialThread

    matches = logged_in_client.get("/import/social/matches")
    assert matches.status_code == 200
    assert "@alex_johnson" in matches.text
    assert "@sam_k" in matches.text

    # Link the first conversation by creating a new person.
    db = SessionLocal()
    thread = db.query(SocialThread).filter(SocialThread.peer_handle == "alex_johnson").first()
    thread_id = thread.id
    db.close()

    link = logged_in_client.post(
        f"/import/social/thread/{thread_id}/link",
        data={"new_name": "Alex Johnson"},
        follow_redirects=False,
    )
    assert link.status_code == 303

    db = SessionLocal()
    thread = db.get(SocialThread, thread_id)
    person = db.query(Person).filter(Person.name == "Alex Johnson").first()
    assert thread is not None and thread.person_id == person.id
    # Linking applies a forward-only last-contact bump from the most recent DM.
    assert person.last_contact_date == date(2026, 8, 20)
    db.close()

    # Review page offers suggestions but AI is unconfigured -> gentle, no crash, nothing written.
    review = logged_in_client.get("/import/social/review")
    assert review.status_code == 200
    assert "AI isn't configured" in review.text

    suggest = logged_in_client.post(
        f"/import/social/thread/{thread_id}/suggest", follow_redirects=False
    )
    assert suggest.status_code == 303
    db = SessionLocal()
    person = db.query(Person).filter(Person.name == "Alex Johnson").first()
    assert person.occupation is None
    db.close()


def test_reimport_is_incremental_no_duplicates(logged_in_client):
    _upload(logged_in_client, make_zip(FIXTURE_CONVS))
    _upload(logged_in_client, make_zip(FIXTURE_CONVS))

    from app.database import SessionLocal
    from app.models import SocialThread

    db = SessionLocal()
    assert db.query(SocialThread).count() == 2  # direct only, group chats are skipped
    db.close()


def test_facts_require_accept_before_write(logged_in_client):
    _upload(logged_in_client, make_zip(FIXTURE_CONVS))

    from app.database import SessionLocal
    from app.models import Person, SocialThread, SocialFact, SocialFactStatus

    db = SessionLocal()
    thread = db.query(SocialThread).filter(SocialThread.peer_handle == "sam_k").first()
    tid = thread.id
    person = Person(name="Sam K")
    db.add(person)
    db.flush()
    thread.person_id = person.id
    thread.status = "linked"
    db.commit()

    acc = SocialFact(thread_id=tid, person_id=person.id, field="occupation",
                     value_text="pottery teacher", kind="ai")
    rej = SocialFact(thread_id=tid, person_id=person.id, field="hobbies",
                     value_text="surfing", kind="ai")
    db.add_all([acc, rej])
    db.commit()
    acc_id, rej_id = acc.id, rej.id
    pid = person.id
    db.close()

    reject = logged_in_client.post(f"/import/social/facts/{rej_id}/reject", follow_redirects=False)
    assert reject.status_code == 303

    accept = logged_in_client.post(f"/import/social/facts/{acc_id}/accept", follow_redirects=False)
    assert accept.status_code == 303

    db = SessionLocal()
    person = db.get(Person, pid)
    assert person.occupation == "pottery teacher"  # accepted -> written
    assert person.hobbies is None  # rejected -> untouched
    rejected = db.get(SocialFact, rej_id)
    accepted = db.get(SocialFact, acc_id)
    assert rejected.status == SocialFactStatus.rejected
    assert accepted.status == SocialFactStatus.accepted
    db.close()


def test_fresh_install_offer_and_dismiss(logged_in_client):
    from app.database import SessionLocal
    from app.settings_store import get_setting

    home = logged_in_client.get("/")
    assert home.status_code == 200
    assert "Let's fill in your people" in home.text

    dismiss = logged_in_client.post("/import/social/dismiss-offer", follow_redirects=False)
    assert dismiss.status_code == 303

    db = SessionLocal()
    assert get_setting(db, "social_offer_dismissed", "") == "1"
    db.close()
    home2 = logged_in_client.get("/")
    assert "Let's fill in your people" not in home2.text


def test_pages_render_after_import(logged_in_client):
    _upload(logged_in_client, make_zip(FIXTURE_CONVS))
    # Landing + settings (settings template also served by many other POST handlers).
    landing = logged_in_client.get("/import/social")
    assert landing.status_code == 200
    assert "alex_johnson" in landing.text

    settings = logged_in_client.get("/settings")
    assert settings.status_code == 200
    assert "Imported social data" in settings.text

    # Review page with nothing linked yet.
    review = logged_in_client.get("/import/social/review")
    assert review.status_code == 200


def test_upload_json_progress_contract(logged_in_client):
    """The progress-bar upload path returns JSON when it asks for it (X-Kin-Json header)."""
    headers = {"X-Kin-Json": "1"}

    ok = logged_in_client.post(
        "/import/social/upload",
        headers=headers,
        files={"file": ("instagram-x.zip", make_zip(FIXTURE_CONVS), "application/zip")},
    )
    assert ok.status_code == 200
    payload = ok.json()
    assert payload["ok"] is True
    assert payload["redirect"] == "/import/social/matches"

    bad = logged_in_client.post(
        "/import/social/upload",
        headers=headers,
        files={"file": ("not-a-zip.zip", b"this is not a zip", "application/zip")},
    )
    assert bad.status_code == 400
    payload = bad.json()
    assert payload["ok"] is False
    assert payload["error"]
