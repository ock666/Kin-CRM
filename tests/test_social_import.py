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


def test_import_from_server_drop_folder(logged_in_client):
    """A zip placed in DATA_DIR/social_incoming can be imported without an upload."""
    from pathlib import Path

    from app.config import settings as kin_settings

    drop = Path(kin_settings.DATA_DIR) / "social_incoming"
    drop.mkdir(parents=True, exist_ok=True)
    (drop / "instagram-local.zip").write_bytes(make_zip(FIXTURE_CONVS))

    # Landing page advertises the file.
    page = logged_in_client.get("/import/social")
    assert page.status_code == 200
    assert "instagram-local.zip" in page.text

    resp = logged_in_client.post("/import/social/import-local", data={"filename": "instagram-local.zip"},
                                 follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/import/social/matches"

    from app.database import SessionLocal
    from app.models import SocialThread
    db = SessionLocal()
    assert db.query(SocialThread).filter_by(peer_handle="alex_johnson").count() == 1
    db.close()


def make_folderless_zip():
    """Mirrors the real Accounts-Center export: no `instagram-<user>` root folder, participants
    are objects like {"name": "…"}, and the owner ("skye~") appears in every 2-person thread."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        base = "your_instagram_activity/messages/inbox"
        convs = [
            ("paige_1", [{"name": "skye~"}, {"name": "paige"}], [
                ("paige", _ts(2025, 6, 1), "the rescue cat is settling in!"),
                ("skye~", _ts(2025, 6, 1), "omg so happy for you"),
            ]),
            ("milo_1", [{"name": "skye~"}, {"name": "Milo Green"}], [
                ("Milo Green", _ts(2026, 2, 14), "started the pottery class"),
            ]),
            ("gang_1", [{"name": "skye~"}, {"name": "paige"}, {"name": "Milo Green"}], [
                ("paige", _ts(2026, 3, 1), "weekend plans?"),
            ]),
        ]
        for thread, parts, msgs in convs:
            payload = {
                "participants": parts,
                "title": parts[1]["name"] if len(parts) == 2 else "Gang",
                "thread_path": thread,
                "messages": [
                    {"sender_name": s, "timestamp_ms": ts, "content": c}
                    for s, ts, c in msgs
                ],
            }
            zf.writestr(f"{base}/{thread}/message_1.json", json.dumps(payload))
    return buf.getvalue()


def test_parse_recent_folderless_export_style(app):
    """The current IG export (no root folder, object participants) must still resolve the owner
    by majority presence and stage 1:1 conversations only."""
    import tempfile
    from pathlib import Path
    from app.services import social_import as svc

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(make_folderless_zip())
        tmp_path = tmp.name
    try:
        parsed = svc.parse_instagram_zip(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    assert parsed["account_handle"] == "skye~"
    assert parsed["group_chats"] == 1
    by_peer = {c["peer_handle"]: c for c in parsed["conversations"]}
    assert set(by_peer) == {"paige", "Milo Green"}
    assert by_peer["paige"]["msg_count"] == 2


def test_folderless_export_ui_flow(logged_in_client):
    resp = logged_in_client.post(
        "/import/social/upload",
        files={"file": ("instagram-skye_j.io.zip", make_folderless_zip(), "application/zip")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/import/social/matches"

    from app.database import SessionLocal
    from app.models import SocialThread

    db = SessionLocal()
    peers = {t.peer_handle for t in db.query(SocialThread).all()}
    assert {"paige", "Milo Green"} <= peers
    assert db.query(SocialThread).filter_by(peer_handle=None).count() == 0
    db.close()


def test_matches_page_with_candidate_suggestion(logged_in_client):
    """When a conversation peer matches someone already in Kin, the matches page must render
    (this previously raised KeyError: 'relationship_label') and allow a one-click link."""
    from app.database import SessionLocal
    from app.models import Person, SocialThread

    db = SessionLocal()
    db.add(Person(name="Paige"))
    db.commit()
    db.close()

    resp = logged_in_client.post(
        "/import/social/upload",
        files={"file": ("instagram-skye_j.io.zip", make_folderless_zip(), "application/zip")},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    page = logged_in_client.get("/import/social/matches")
    assert page.status_code == 200
    assert "✓ Paige" in page.text  # the suggested one-click link

    db = SessionLocal()
    t = db.query(SocialThread).filter_by(peer_handle="paige").first()
    p = db.query(Person).filter(Person.name == "Paige").first()
    tid, pid = t.id, p.id
    db.close()

    r = logged_in_client.post(f"/import/social/thread/{tid}/link", data={"person_id": str(pid)},
                              follow_redirects=False)
    assert r.status_code == 303
    db = SessionLocal()
    assert db.get(SocialThread, tid).person_id == pid
    db.close()


def test_person_deleted_keeps_review_healthy(logged_in_client):
    """Deleting a person after facts were staged must not break the review page."""
    from app.database import SessionLocal
    from app.models import Person, SocialThread, SocialFact, SocialFactStatus

    logged_in_client.post(
        "/import/social/upload",
        files={"file": ("instagram-skye_j.io.zip", make_folderless_zip(), "application/zip")},
        follow_redirects=False,
    )
    db = SessionLocal()
    t = db.query(SocialThread).filter_by(peer_handle="paige").first()
    tid = t.id
    p = Person(name="Paige")
    db.add(p)
    db.flush()
    t.person_id = p.id
    t.status = "linked"
    db.add(SocialFact(thread_id=tid, person_id=p.id, field="occupation",
                      value_text="vet nurse", kind="ai"))
    db.commit()
    pid = p.id
    db.close()

    deleted = logged_in_client.post(f"/people/{pid}/delete", follow_redirects=False)
    assert deleted.status_code == 303

    review = logged_in_client.get("/import/social/review")
    assert review.status_code == 200
    assert "vet nurse" not in review.text  # orphaned suggestion quietly retired

    db = SessionLocal()
    assert db.query(SocialFact).filter_by(status=SocialFactStatus.rejected).count() == 1
    db.close()
