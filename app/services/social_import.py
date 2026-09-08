"""Social-data import (Instagram first) - a gentle, staged, human-in-the-loop pipeline.

Philosophy mirrors the rest of Kin: nothing ever writes to a Person until the user
explicitly decides. Flow:

  1. Parse an Instagram "download your information" zip -> normalised conversations.
     Only direct (1:1) conversations are staged for now; group chats are counted and
     skipped (attribution is too ambiguous to be safe).
  2. The user links each conversation to an existing Person (or creates one) - the
     "who is this?" gate. Linking applies *only* a forward-only last-contact bump.
  3. Optionally, AI reads a compact recent transcript and proposes profile facts
     (occupation, hobbies, notable people/dates, ...). These land in `social_facts`
     as *pending* and are applied one-by-one only when the user accepts them.

Raw messages are never stored wholesale: per thread we keep a small recent
transcript on disk (DATA_DIR/social_import/) plus lightweight signals/samples in
the DB, so re-imports are cheap and incremental.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import zipfile
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    SocialThread, SocialImportStatus, SocialFactStatus, Person, NotablePersonRef, NotableDate,
)

logger = logging.getLogger(__name__)

PLATFORM_INSTAGRAM = "instagram"

# How much recent conversation to keep per thread for AI suggestions / review.
TRANSCRIPT_LIMIT = 400
SAMPLE_LIMIT = 4
MSG_CHAR_LIMIT = 600

_INSTAGRAM_ROOT = re.compile(r"^instagram[-_]?([A-Za-z0-9._]+)")
_USERNAME = re.compile(r"[a-z0-9._]+")

# Message keys that mean "this was media/a share, not plain text".
_MEDIA_KEYS = (
    "photos", "videos", "audio", "gifs", "animated_media", "share", "link",
    "media_share", "reel", "clip", "story_share", "felix_share", "raven_media",
    "voice_media", "xcxp_share",
)


def _social_dir() -> Path:
    d = settings.DATA_DIR / "social_import"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _transcript_path(thread_id: int) -> Path:
    return _social_dir() / f"thread_{thread_id}.jsonl"


# ---------------------------------------------------------------------------
# Parsing an Instagram export zip
# ---------------------------------------------------------------------------

def _iter_group_dicts(data):
    """Tolerantly find {"participants": [...], "messages": [...]} dicts nested anywhere."""
    if isinstance(data, list):
        for item in data:
            yield from _iter_group_dicts(item)
    elif isinstance(data, dict):
        if isinstance(data.get("messages"), list) and isinstance(data.get("participants"), list):
            yield data
        else:
            for v in data.values():
                yield from _iter_group_dicts(v)


def _looks_like_dm_path(path: str) -> bool:
    """Restrict parsing to the DM parts of an export (layouts vary between export eras)."""
    low = path.lower()
    if low.endswith(".json") and "direct_message" in low:
        return True
    parts = low.split("/")
    if "direct" in parts:
        return True
    # messenger-style: .../messages/inbox/<thread>/message_1.json
    return ("messages" in parts and "inbox" in parts)


def _detect_own_handle(zf: zipfile.ZipFile) -> str | None:
    names = zf.namelist()
    for n in names:
        if n.count("/") >= 1:
            root = n.split("/", 1)[0]
            m = _INSTAGRAM_ROOT.match(root)
            if m:
                return m.group(1)
    return None


def _msg_epoch_ms(ts_ms) -> int | None:
    try:
        return int(ts_ms)
    except (TypeError, ValueError):
        return None


def parse_instagram_zip(zip_path: str | Path) -> dict:
    """Parse an Instagram export zip. Returns:
    {"account_handle": str|None, "conversations": [dict...], "group_chats": int,
     "unrecognised": int}
    """
    groups: list[dict] = []
    group_chats = 0
    unrecognised = 0
    with zipfile.ZipFile(zip_path) as zf:
        account_handle = _detect_own_handle(zf)
        for info in zf.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".json"):
                continue
            if not _looks_like_dm_path(info.filename):
                continue
            try:
                raw = zf.read(info)
            except (zipfile.BadZipFile, OSError, RuntimeError):
                unrecognised += 1
                continue
            try:
                data = json.loads(raw.decode("utf-8", errors="replace"))
            except (ValueError, UnicodeDecodeError):
                unrecognised += 1
                continue
            rel_dir = str(Path(info.filename).parent)
            for g in _iter_group_dicts(data):
                conv = _normalise_group(g, rel_dir, account_handle)
                if conv is None:
                    continue
                if conv["kind"] == "group":
                    group_chats += 1
                else:
                    groups.append(conv)
    return {
        "account_handle": account_handle,
        "conversations": groups,
        "group_chats": group_chats,
        "unrecognised": unrecognised,
    }


def _group_summary(g: dict, rel_dir: str, participants: list[str]) -> dict:
    return {
        "kind": "group",
        "key": rel_dir or "unknown",
        "title": g.get("thread_title") or g.get("title") or g.get("conversation_title"),
        "participants": participants,
        "peer_handle": None,
        "msg_count": len(g.get("messages", []) or []),
        "first_ts_ms": None,
        "last_ts_ms": None,
    }


def _normalise_group(g: dict, rel_dir: str, own_handle: str | None) -> dict | None:
    participants = [str(p).strip() for p in g.get("participants", []) if str(p).strip()]
    messages = g.get("messages", []) or []
    if not participants or not isinstance(messages, list):
        return None

    peers = [p for p in participants if p.lower() != (own_handle or "").lower()]

    # Group chats: skip content mining for now (counting only). We only ever stage
    # 1:1 conversations where attribution ("who said what") is unambiguous.
    if own_handle is None:
        if len(participants) > 2:
            return _group_summary(g, rel_dir, participants)
        # Two participants but we can't tell which is "me" -> never fabricate a peer.
        return None
    if len(peers) != 1:
        return _group_summary(g, rel_dir, participants)

    peer = peers[0]

    peer_handle = peer
    text_msgs: list[tuple[int, str, str]] = []
    signals = {"media": 0, "reactions": 0, "unsent": 0, "call_minutes": 0.0}
    ts_min: int | None = None
    ts_max: int | None = None

    for m in messages:
        if not isinstance(m, dict):
            continue
        ts = _msg_epoch_ms(m.get("timestamp_ms"))
        if ts is None:
            continue
        ts_min = ts if ts_min is None else min(ts_min, ts)
        ts_max = ts if ts_max is None else max(ts_max, ts)

        if any(k in m for k in _MEDIA_KEYS):
            signals["media"] += 1
        if m.get("reactions"):
            signals["reactions"] += len(m["reactions"])
        if m.get("is_unsent"):
            signals["unsent"] += 1
        cd = m.get("call_duration")
        if isinstance(cd, (int, float)):
            signals["call_minutes"] += float(cd) / 60000.0

        content = m.get("content") or ""
        if not isinstance(content, str) or not content.strip():
            continue
        sender = str(m.get("sender_name") or "").strip()
        if not sender:
            continue
        text = content.strip()
        if len(text) > MSG_CHAR_LIMIT:
            text = text[:MSG_CHAR_LIMIT] + "…"
        text_msgs.append((ts, sender, text))

    text_msgs.sort(key=lambda t: t[0])
    samples = text_msgs[-SAMPLE_LIMIT:]
    transcript = text_msgs[-TRANSCRIPT_LIMIT:]

    title = g.get("thread_title") or g.get("conversation_title") or g.get("title") or peer_handle
    return {
        "kind": "direct",
        "key": rel_dir or f"{peer_handle}:{ts_min or ''}",
        "title": title,
        "participants": participants,
        "peer_handle": peer_handle,
        "msg_count": len(messages),
        "first_ts_ms": ts_min,
        "last_ts_ms": ts_max,
        "signals": signals,
        "samples": samples,
        "transcript": transcript,
    }


# ---------------------------------------------------------------------------
# Staging conversations into the DB (incremental)
# ---------------------------------------------------------------------------

def upsert_conversations(db: Session, platform: str, account_handle: str | None,
                         conversations: list[dict]) -> dict:
    """Create/refresh SocialThread rows. Returns a summary for the UI.

    Incremental by design: a thread is only "new" when it has messages newer than
    what we already saw, so re-importing a fresh (full-history) export is cheap."""
    summary = {"added": 0, "updated": 0, "new_messages": 0, "already_current": 0}
    for conv in conversations:
        if conv["kind"] != "direct":
            continue
        row = (
            db.query(SocialThread)
            .filter_by(platform=platform, account_handle=account_handle, thread_key=conv["key"])
            .first()
        )
        if row is None:
            row = SocialThread(
                platform=platform, account_handle=account_handle, thread_key=conv["key"],
                thread_title=conv["title"], peer_handle=conv["peer_handle"],
                kind="direct", status=SocialImportStatus.pending,
            )
            db.add(row)
            db.flush()
            summary["added"] += 1

        new_msgs = sum(
            1 for ts, _s, _t in conv["transcript"] if row.last_ts_ms is None or ts > (row.last_ts_ms or 0)
        )
        last_ts = row.last_ts_ms
        if last_ts is not None and conv["last_ts_ms"] is not None and conv["last_ts_ms"] <= last_ts and not new_msgs:
            summary["already_current"] += 1
            continue

        row.first_ts_ms = conv["first_ts_ms"] or row.first_ts_ms
        row.last_ts_ms = conv["last_ts_ms"] or row.last_ts_ms
        row.msg_count = max(row.msg_count or 0, conv["msg_count"] or 0)
        row.new_count = new_msgs
        row.signals_json = json.dumps(conv["signals"])
        row.sample_json = json.dumps(
            [{"sender": s, "ts": t, "text": tx} for t, s, tx in conv["samples"]]
        )
        _write_transcript(row.id, conv["transcript"])
        db.flush()
        if row.status == SocialImportStatus.pending:
            # Once parsed, a previously-linked thread stays linked (fresh messages are
            # picked up on the review page as "new since last import").
            summary["new_messages"] += new_msgs
        summary["updated"] += 1
    db.commit()
    return summary


def _write_transcript(thread_id: int, transcript: list[tuple[int, str, str]]):
    """Persist a compact, recent-only transcript so AI suggestions don't need the original zip."""
    path = _transcript_path(thread_id)
    with open(path, "w", encoding="utf-8") as fh:
        for ts, sender, text in transcript:
            fh.write(json.dumps({"ts": ts, "sender": sender, "text": text}) + "\n")


def load_transcript(thread_id: int) -> list[dict]:
    path = _transcript_path(thread_id)
    if not path.exists():
        return []
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except (OSError, ValueError):
        return []
    return out


def delete_transcript(thread_id: int):
    try:
        _transcript_path(thread_id).unlink(missing_ok=True)
    except OSError:
        pass


def delete_source(db: Session, thread_ids: list[int]):
    """Delete staged threads + transcripts (applied facts stay on the Person)."""
    for tid in thread_ids:
        row = db.get(SocialThread, tid)
        if row:
            delete_transcript(tid)
            db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# Matching: "which Person is this?"
# ---------------------------------------------------------------------------

def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def suggest_matches(db: Session, peer_handle: str, thread_title: str | None,
                    limit: int = 3) -> list[dict]:
    """Rank existing (non-archived) people as candidates for a conversation peer.

    Heuristic and cheap: handle/title tokens against name/nickname tokens plus an
    email/phone grep across profiles. The user always makes the final call."""
    hay = {
        "handle": peer_handle or "",
        "title": thread_title or "",
    }
    candidates: list[dict] = []
    handle_tokens = _tokens(peer_handle) | _tokens(thread_title)
    email_hint = None
    m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", hay["title"] or "")
    if m:
        email_hint = m.group(0)

    for p in db.query(Person).filter(Person.archived.is_(False)).all():
        score = 0
        name_tokens = _tokens(p.name) | _tokens(p.nickname or "")
        if handle_tokens and name_tokens:
            overlap = len(handle_tokens & name_tokens)
            if overlap:
                score += 10 * overlap
        # A username that literally IS the person's name or nickname.
        if peer_handle and (p.name or "").lower().replace(" ", "") == peer_handle.lower():
            score += 40
        if peer_handle and p.nickname and p.nickname.lower().replace(" ", "") == peer_handle.lower():
            score += 40
        if email_hint and email_hint.lower() == (p.email or "").lower():
            score += 60
        if email_hint and p.email and email_hint.lower() in p.email.lower():
            score += 30
        # People we DM'd a lot are likely tracked already - no penalty for empty profiles.
        if score > 0:
            candidates.append({"person_id": p.id, "name": p.name, "score": score,
                               "nickname": p.nickname, "label": p.relationship_label})

    candidates.sort(key=lambda c: c["score"], reverse=True)
    seen, out = set(), []
    for c in candidates:
        if c["name"] not in seen:
            seen.add(c["name"])
            out.append({"person_id": c["person_id"], "name": c["name"],
                        "nickname": c["nickname"], "label": c["relationship_label"]})
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Applying staged facts (always after an explicit accept)
# ---------------------------------------------------------------------------

def ts_ms_to_date(ts_ms: int | None) -> dt.date | None:
    if not ts_ms:
        return None
    try:
        return dt.datetime.fromtimestamp(ts_ms / 1000, tz=dt.timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None


def apply_fact(db: Session, thread: SocialThread, person: Person, fact) -> bool:
    """Write one accepted fact onto a Person. Returns True when something changed."""
    if fact.status.value == "accepted":
        return False
    changed = False
    field = fact.field

    if field in ("occupation", "hobbies", "location", "how_we_met", "bio", "notes"):
        val = (fact.value_text or "").strip()
        if val:
            setattr(person, field, val)
            changed = True
    elif field == "notable_person":
        try:
            payload = json.loads(fact.value_json or "{}")
        except ValueError:
            payload = {}
        name = (payload.get("name") or fact.value_text or "").strip()
        relation = (payload.get("relation") or "").strip() or None
        if name and not any(r.name == name for r in person.notable_people_refs):
            db.add(NotablePersonRef(person_id=person.id, name=name, relation=relation))
            changed = True
    elif field == "notable_date":
        try:
            payload = json.loads(fact.value_json or "{}")
        except ValueError:
            payload = {}
        label = (payload.get("label") or fact.value_text or "Notable date").strip()
        month, day = payload.get("month"), payload.get("day")
        year = payload.get("year")
        try:
            dt.date(year if year else 2000, int(month), int(day))
        except (ValueError, TypeError):
            return False
        duplicate = any(
            nd.label == label and nd.month == int(month) and nd.day == int(day)
            for nd in person.notable_dates
        )
        if not duplicate:
            db.add(NotableDate(
                person_id=person.id, label=label,
                month=int(month), day=int(day),
                year=int(year) if year else None, recurring=True,
            ))
            changed = True
    elif field == "scratchpad":
        from ..models import ScratchpadItem
        val = (fact.value_text or "").strip()
        if val:
            db.add(ScratchpadItem(person_id=person.id, text=val))
            changed = True

    if changed:
        fact.status = SocialFactStatus.accepted
    return changed
