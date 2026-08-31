"""'Your Year' - Kin's gentle, positive year-in-review (a private Spotify-Wrapped-style card).

Design notes:
  - Covers the CURRENT calendar year (Jan 1 -> generation date), so it fires naturally around
    mid-December and the Dec 2026 card covers Jan-Dec 2026. Posts outside that year are ignored.
  - Entirely positive by design: conflict entries and ConflictLog data are excluded outright -
    the card never looks back at negatives, drift, or unresolved stress. It celebrates who the
    user showed up for and the real moments shared.
  - Deterministic scoring first (event-type weight x photos x text length) so short, photo-less
    notes naturally drop out; AI narration is optional and only enriches the card when AI is
    configured - the card is fully functional without it.
  - Generated ONCE per year by the scheduler (mid-December), never by a button. Cards are pruned
    ~4 weeks later so long-running installs don't accumulate them and shared links don't live
    forever. A settings flag records that this year's card was already generated so an expired
    card is never silently regenerated mid-season.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
import secrets

from sqlalchemy.orm import Session

from ..models import (
    WrappedCard, WrappedPersonShare, Person, JournalEntry, JournalImage,
    GiftIdea, GiftStatus, UnlockedAchievement, EventType,
)
from ..settings_store import get_setting, set_setting

logger = logging.getLogger(__name__)

WRAPPED_MONTH, WRAPPED_DAY = 12, 16   # season starts here (aligned with Spotify-Wrapped timing)
CARD_TTL_DAYS = 28                     # cards (and their share links) live for ~4 weeks

MAX_MOMENTS = 8
MAX_PEOPLE = 5
MIN_PEOPLE_INTERACTIONS = 2            # a person needs this many scored entries to count as "close this year"
MIN_PERSON_SHARE_MOMENTS = 3           # a person needs this many journal entries this year to be shareable
MAX_PERSON_MOMENTS = 6                 # moments shown on a per-person share card
MAX_MONTH_MOMENTS = 100                # month drill-down carousel shows everything (practical cap)
MONTH_SUMMARY_CAP = 20                 # AI-summarise at most this many per month (the photo-rich lead)

_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# How big each kind of moment feels. Conflicts are deliberately absent - the card is positive-only.
EVENT_WEIGHTS = {
    EventType.milestone: 5,
    EventType.hangout: 4,
    EventType.gift: 3,
    EventType.call: 2,
    EventType.message: 2,
    EventType.instagram: 2,
    EventType.note: 1,
    EventType.other: 1,
}


def _generated_flag(year: int) -> str:
    return f"wrapped_generated_{year}"


def _friendly_date(d: dt.date) -> str:
    """Human-friendly date, e.g. 'Jun 14' instead of '2026-06-14'."""
    if not d:
        return ""
    return f"{d.strftime('%b')} {d.day}"


def _moment_score(entry) -> float:
    weight = EVENT_WEIGHTS.get(entry.event_type, 1) if entry.event_type else 1
    photo_bonus = 1 + min(len(entry.images or []), 3)
    length = len((entry.body or "").strip())
    return weight * photo_bonus * (1 + math.log10(length + 1))


def _first_image(entry) -> dict:
    """Best single image for a moment: prefer an Immich asset (served through Kin's proxy),
    then a direct external URL (e.g. an Instagram media link)."""
    images = entry.images or []
    for img in images:
        if img.immich_asset_id:
            return {"asset_id": img.immich_asset_id}
        if img.upload_path and img.upload_path.startswith("http"):
            return {"url": img.upload_path}
    return {}


def _year_entries(db: Session, year: int):
    start = dt.date(year, 1, 1)
    end = dt.date(year, 12, 31)
    return (
        db.query(JournalEntry)
        .filter(JournalEntry.entry_date >= start, JournalEntry.entry_date <= end)
        .filter(JournalEntry.event_type.is_(None) | (JournalEntry.event_type != EventType.conflict))
        .all()
    )


def build_payload(db: Session, year: int) -> dict:
    """Compute the deterministic 'Your Year' payload for a calendar year. No AI here - the
    caller may enrich it with narration afterwards."""
    entries = _year_entries(db, year)

    scored = []
    for e in entries:
        score = _moment_score(e)
        if score >= 2.0:
            scored.append((score, e))
    scored.sort(key=lambda t: -t[0])

    moments = []
    for score, e in scored[:MAX_MOMENTS]:
        img = _first_image(e)
        moment = {
            "id": e.id,
            "title": e.title or "",
            "body_preview": (e.body or "").strip()[:160],
            "date": e.entry_date.isoformat() if e.entry_date else None,
            "date_display": _friendly_date(e.entry_date) if e.entry_date else None,
            "event_type": e.event_type.value if e.event_type else "note",
            "people": [p.name for p in e.people],
            "score": round(score, 1),
        }
        moment.update(img)
        moments.append(moment)

    # Top people by activity this year - who the user was closest to, purely positive.
    person_scores: dict[int, dict] = {}
    for _score, e in scored:
        for p in e.people:
            row = person_scores.setdefault(p.id, {
                "id": p.id, "name": p.name, "score": 0.0, "moments": 0, "months": set(),
                "label": p.relationship_label or "",
                "hangouts": 0, "calls": 0, "messages": 0, "milestones": 0,
                "immich_id": p.immich_person_id or "",
            })
            row["score"] += _score
            row["moments"] += 1
            if e.entry_date:
                row["months"].add(e.entry_date.month)
            key = e.event_type.value if e.event_type else "note"
            if key in ("hangout", "call", "message", "milestone"):
                row[key + "s"] += 1
    people = sorted(
        (r for r in person_scores.values() if r["moments"] >= MIN_PEOPLE_INTERACTIONS),
        key=lambda r: -r["score"],
    )[:MAX_PEOPLE]
    for p in people:
        p["score"] = round(p["score"], 1)
        p["months"] = sorted(p["months"])

    # Stats - countable, positive milestones from this year.
    by_type: dict[str, int] = {}
    for e in entries:
        key = e.event_type.value if e.event_type else "note"
        by_type[key] = by_type.get(key, 0) + 1

    photo_count = (
        db.query(JournalImage.id)
        .join(JournalEntry, JournalEntry.id == JournalImage.journal_entry_id)
        .filter(JournalEntry.entry_date >= dt.date(year, 1, 1),
                JournalEntry.entry_date <= dt.date(year, 12, 31))
        .count()
    )
    gifts_given = (
        db.query(GiftIdea.id)
        .filter(GiftIdea.year == year, GiftIdea.status == GiftStatus.given)
        .count()
    )
    achievements = (
        db.query(UnlockedAchievement.id)
        .filter(UnlockedAchievement.unlocked_at >= dt.datetime(year, 1, 1),
                UnlockedAchievement.unlocked_at <= dt.datetime(year, 12, 31, 23, 59, 59))
        .count()
    )
    people_ids = {p.id for e in entries for p in e.people}

    # Monthly rhythm - entry count per month, for the pure-CSS bar chart. Also groups the
    # month's moments so a month bar can be clicked to peek at what happened that month.
    by_month: dict[int, list] = {m: [] for m in range(1, 13)}
    for e in entries:
        if e.entry_date:
            by_month[e.entry_date.month].append(e)
    rhythm = [len(by_month[m]) for m in range(1, 13)]
    peak_count = max(rhythm) if rhythm else 0
    peak_month = (rhythm.index(peak_count) + 1) if peak_count else None

    months_detail = []
    for m in range(1, 13):
        month_entries = by_month[m]
        # Photo-rich, longer entries first - they're most likely the notable ones.
        month_items = []
        for e in month_entries:
            month_items.append((1 if _first_image(e) else 0, _moment_score(e), e))
        month_items.sort(key=lambda t: (-t[0], -t[1]))
        month_moments = []
        for _has_img, _score, e in month_items[:MAX_MONTH_MOMENTS]:
            mo = {
                "title": e.title or "",
                "date_display": _friendly_date(e.entry_date) if e.entry_date else None,
                "event_type": e.event_type.value if e.event_type else "note",
                "body_preview": (e.body or "").strip()[:140],
                "people": [p.name for p in e.people],
            }
            mo.update(_first_image(e))
            month_moments.append(mo)
        months_detail.append({"month": m, "count": len(month_entries), "moments": month_moments})

    # Photos across the whole year (not just the standout moments) for richer sections.
    # Distinct assets only, spread across as many months as possible (one per month first, then
    # extras) so the collage reflects the whole year rather than one busy patch.
    photos_by_month: dict[int, list[str]] = {}
    for e in entries:
        if not e.entry_date:
            continue
        bucket = photos_by_month.setdefault(e.entry_date.month, [])
        for img in (e.images or []):
            if img.immich_asset_id and img.immich_asset_id not in bucket:
                bucket.append(img.immich_asset_id)
    all_photos: list[str] = []
    for m in range(1, 13):                       # one photo per month -> spans the year
        if photos_by_month.get(m):
            all_photos.append(photos_by_month[m][0])
    for m in range(1, 13):                       # fill with extras (still distinct)
        for aid in photos_by_month.get(m, [])[1:]:
            if len(all_photos) >= 12:
                break
            if aid not in all_photos:
                all_photos.append(aid)
        if len(all_photos) >= 12:
            break

    # Fun facts - bookends + flavour, all positive and deterministic.
    dated = sorted((e for e in entries if e.entry_date), key=lambda e: e.entry_date)
    weekday_counts: dict[int, int] = {}
    total_words = 0
    for e in entries:
        total_words += len((e.body or "").split())
        if e.entry_date:
            weekday_counts.setdefault(e.entry_date.weekday(), 0)
            weekday_counts[e.entry_date.weekday()] += 1
    fun_facts = {
        "first_title": (dated[0].title or "the first moment") if dated else None,
        "first_date_display": _friendly_date(dated[0].entry_date) if dated else None,
        "last_title": (dated[-1].title or "the latest moment") if dated else None,
        "last_date_display": _friendly_date(dated[-1].entry_date) if dated else None,
        "total_words": total_words,
        "top_weekday": max(weekday_counts, key=weekday_counts.get) if weekday_counts else None,
        "top_type": (max(by_type, key=by_type.get) if by_type else None),
    }

    # Badges unlocked this year (emoji tiles from the gamification catalogue).
    from .gamification import ACHIEVEMENTS as ACH
    badge_rows = (
        db.query(UnlockedAchievement)
        .filter(UnlockedAchievement.unlocked_at >= dt.datetime(year, 1, 1),
                UnlockedAchievement.unlocked_at <= dt.datetime(year, 12, 31, 23, 59, 59))
        .order_by(UnlockedAchievement.unlocked_at.asc())
        .all()
    )
    badges = []
    for row in badge_rows:
        meta = ACH.get(row.slug)
        if meta:
            badges.append({
                "emoji": meta[0], "label": meta[1], "desc": meta[2],
                "date_display": (
                    f"{row.unlocked_at.day} {row.unlocked_at.strftime('%b')} {row.unlocked_at.year}"
                    if row.unlocked_at else None
                ),
            })

    # Photo mosaic for the hero band - asset ids from the standout moments.
    mosaic = []
    for m in moments:
        if m.get("asset_id") and m["asset_id"] not in mosaic:
            mosaic.append(m["asset_id"])
        if len(mosaic) >= 9:
            break

    return {
        "year": year,
        "summary": None,
        "stats": {
            "entries": len(entries),
            "hangouts": by_type.get("hangout", 0),
            "calls": by_type.get("call", 0),
            "messages": by_type.get("message", 0),
            "gifts": by_type.get("gift", 0),
            "milestones": by_type.get("milestone", 0),
            "photos": photo_count,
            "gifts_given": gifts_given,
            "achievements": achievements,
            "people_count": len(people_ids),
        },
        "rhythm": rhythm,
        "peak_month": peak_month,
        "peak_count": peak_count,
        "months_detail": months_detail,
        "fun_facts": fun_facts,
        "badges": badges,
        "mosaic": mosaic,
        "all_photos": all_photos,
        "people": people,
        "moments": moments,
    }


def _narrate(db: Session, payload: dict) -> dict:
    """Add the optional warm AI summary + per-person blurbs. Returns the payload unchanged (but
    narrated) on success; on any AI failure the card simply stays deterministic-only."""
    try:
        from .ai_client import get_client_from_settings, AIError
        client = get_client_from_settings(db)
        if not client:
            return payload
        stats = payload["stats"]
        stats_lines = "\n".join(
            f"- {k.replace('_', ' ')}: {v}" for k, v in stats.items() if v
        )
        people_lines = "\n".join(
            f"- {p['name']}: {p['moments']} logged moments together"
            for p in payload["people"]
        )
        moment_lines = "\n".join(
            f"- {m['date'] or 'sometime'}: {m['title'] or '(untitled)'}"
            + (f" with {', '.join(m['people'])}" if m["people"] else "")
            for m in payload["moments"]
        )
        data = client.year_in_review(payload["year"], stats_lines, people_lines, moment_lines)
        if data.get("summary"):
            payload["summary"] = data["summary"]
        blurbs = {b.get("name", "").strip(): b.get("blurb", "") for b in data.get("people", []) if isinstance(b, dict)}
        if blurbs:
            for p in payload["people"]:
                p["blurb"] = blurbs.get(p["name"].strip()) or None

        # Short AI summaries for the month drill-down moments, so the text always fits
        # regardless of how long the original journal entry was. Only the photo-rich lead
        # (the most notable) get narrated; the rest keep their text preview.
        for month in payload.get("months_detail", []):
            if not month.get("moments"):
                continue
            lead = month["moments"][:MONTH_SUMMARY_CAP]
            summaries = client.month_summaries(_MONTH_NAMES[month["month"] - 1], lead)
            if summaries:
                for mo, s in zip(lead, summaries):
                    if s:
                        mo["summary"] = s
    except Exception as e:
        logger.warning("Wrapped AI narration skipped: %s", e)
    return payload


def _enrich_faces(db: Session, payload: dict) -> dict:
    """Best-effort face-aware cropping for standout moments: asks Immich where the faces are and
    stores object-position percentages so the browser keeps people front and centre in the crop.
    Never breaks the card - any failure just leaves the default centre crop."""
    for m in payload.get("moments", []):
        aid = m.get("asset_id")
        if not aid:
            continue
        try:
            from .immich_client import get_client_from_settings as immich_client
            client = immich_client(db)
            center = client.asset_face_center(aid)
        except Exception:
            center = None
        if center:
            m["face_x"], m["face_y"] = center
    return payload


def _enrich_person_photos(db: Session, payload: dict) -> dict:
    """Give each 'people you were closest to' card a photo: preferably a 'together' photo (the
    person's face appearing in a photo from this year), else their Kin avatar (their Immich face
    thumbnail), else nothing. Best-effort - never breaks the card. The photo is served through the
    card's image base so it works on both the private page and the token-gated share card."""
    try:
        from .immich_client import (
            get_client_from_settings as immich_client,
            _parse_asset_datetime,
        )
    except Exception:
        return payload
    try:
        client = immich_client(db)
    except Exception:
        return payload

    year = payload["year"]
    pad = dt.timedelta(hours=24)
    start_utc = (dt.datetime(year, 1, 1) - pad).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_utc = (dt.datetime(year, 12, 31, 23, 59, 59) + pad).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    for person in payload.get("people", []):
        immich_id = person.get("immich_id")
        if not immich_id:
            continue
        # Fallback first: their Kin avatar (Immich face thumbnail).
        photo = {"kind": "person", "id": immich_id}
        try:
            assets = client.search_by_person(immich_id, taken_after=start_utc, taken_before=end_utc, size=12)
            assets = [
                a for a in assets
                if a.get("id") and (_parse_asset_datetime(a) or dt.datetime.min).year == year
            ]
            assets.sort(key=lambda a: (_parse_asset_datetime(a) or dt.datetime.min), reverse=True)
            if assets:
                photo = {"kind": "asset", "id": assets[0]["id"]}
                center = client.asset_face_center(assets[0]["id"])
                if center:
                    photo["face_x"], photo["face_y"] = center
        except Exception:
            pass
        person["photo"] = photo
    return payload


def generate_card(db: Session, year: int, today: dt.date | None = None,
                  record_generation: bool = True) -> tuple[WrappedCard, bool]:
    """Build (or refresh) this year's card, optionally narrated, and persist it. Returns
    (card, created). Idempotent per year - a fresh card replaces the old one, never duplicates.

    `record_generation` sets the once-per-year flag. The developer/preview hook passes False so
    previewing early doesn't consume the real mid-December generation."""
    today = today or dt.date.today()
    payload = build_payload(db, year)
    _narrate(db, payload)
    _enrich_faces(db, payload)
    _enrich_person_photos(db, payload)

    existing = db.query(WrappedCard).filter(WrappedCard.year == year).first()
    if existing:
        existing.data_json = json.dumps(payload)
        existing.token = secrets.token_urlsafe(16)
        existing.created_at = dt.datetime.utcnow()
        db.commit()
        return existing, False

    card = WrappedCard(
        token=secrets.token_urlsafe(16),
        year=year,
        data_json=json.dumps(payload),
        created_at=dt.datetime.utcnow(),
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    if record_generation:
        set_setting(db, _generated_flag(year), "1")
    return card, True


def get_fresh_card(db: Session, year: int | None = None, today: dt.date | None = None) -> WrappedCard | None:
    """The current year's card, or None if none exists yet or it has expired."""
    today = today or dt.date.today()
    year = year or today.year
    card = db.query(WrappedCard).filter(WrappedCard.year == year).order_by(WrappedCard.id.desc()).first()
    if card is None:
        return None
    created = card.created_at.date() if card.created_at else today
    if (today - created).days > CARD_TTL_DAYS:
        return None
    return card


def generate_if_due(db: Session, today: dt.date | None = None) -> tuple[WrappedCard | None, bool]:
    """Scheduler hook: auto-generate this year's card once, when the season arrives.

    Returns (card_or_None, generated). Guarded by a settings flag so an expired card is never
    silently regenerated later in the same year - generation happens exactly once per year."""
    today = today or dt.date.today()
    if (today.month, today.day) < (WRAPPED_MONTH, WRAPPED_DAY):
        return None, False
    year = today.year
    if get_setting(db, _generated_flag(year), "0") == "1":
        return None, False
    card, created = generate_card(db, year, today)
    return card, created


def cleanup_expired(db: Session, today: dt.date | None = None) -> int:
    """Prune cards and per-person shares older than the TTL so long-running installs never
    accumulate wrapped cards or share links. Returns the number deleted."""
    today = today or dt.date.today()
    cutoff = dt.datetime.combine(today - dt.timedelta(days=CARD_TTL_DAYS), dt.time.min)
    count = 0
    for card in db.query(WrappedCard).filter(WrappedCard.created_at < cutoff).all():
        db.delete(card)
        count += 1
    for share in db.query(WrappedPersonShare).filter(WrappedPersonShare.created_at < cutoff).all():
        db.delete(share)
        count += 1
    if count:
        db.commit()
    return count


# ---------------------------------------------------------------------------
# Per-person "Our year with {Name}" share cards
# ---------------------------------------------------------------------------


def season_active(db: Session, today: dt.date | None = None) -> bool:
    """True while the wrapped season is live (a fresh card exists for the current year). Per-person
    shares are only available during the season - they disappear when it ends."""
    return get_fresh_card(db, today=today) is not None


def is_person_share_eligible(db: Session, person, year: int) -> bool:
    """A person is shareable when they're not archived and have at least a few moments logged
    this year (so the card isn't an empty shell)."""
    if not person or person.archived:
        return False
    count = 0
    for e in person.journal_entries:
        if (e.entry_date and e.entry_date.year == year
                and (e.event_type is None or e.event_type != EventType.conflict)):
            count += 1
    return count >= MIN_PERSON_SHARE_MOMENTS


def build_person_payload(db: Session, person, year: int) -> dict:
    """The deterministic per-person card: ONLY this person's moments + small shared stats. No
    other people's names, no aggregate stats, no gifts, no conflicts - ever."""
    entries = [
        e for e in person.journal_entries
        if e.entry_date and e.entry_date.year == year
        and (e.event_type is None or e.event_type != EventType.conflict)
    ]
    scored = sorted(((_moment_score(e), e) for e in entries), key=lambda t: -t[0])

    moments = []
    for _score, e in scored[:MAX_PERSON_MOMENTS]:
        m = {
            "id": e.id,
            "title": e.title or "",
            "body_preview": (e.body or "").strip()[:160],
            "date": e.entry_date.isoformat() if e.entry_date else None,
            "date_display": _friendly_date(e.entry_date) if e.entry_date else None,
            "event_type": e.event_type.value if e.event_type else "note",
        }
        m.update(_first_image(e))
        moments.append(m)

    by_type: dict[str, int] = {}
    months: set[int] = set()
    for e in entries:
        key = e.event_type.value if e.event_type else "note"
        by_type[key] = by_type.get(key, 0) + 1
        if e.entry_date:
            months.add(e.entry_date.month)

    photo_count = sum(len(e.images or []) for e in entries)
    dated = sorted((e for e in entries if e.entry_date), key=lambda e: e.entry_date)

    return {
        "person_id": person.id,
        "name": person.name,
        "nickname": person.nickname or "",
        "year": year,
        "note": None,
        "stats": {
            "entries": len(entries),
            "hangouts": by_type.get("hangout", 0),
            "calls": by_type.get("call", 0),
            "messages": by_type.get("message", 0),
            "photos": photo_count,
            "months_together": len(months),
            "first_date": dated[0].entry_date.isoformat() if dated else None,
            "last_date": dated[-1].entry_date.isoformat() if dated else None,
        },
        "moments": moments,
    }


def _person_note(db: Session, payload: dict) -> str:
    """Optional warm AI note for a per-person card. Returns '' when AI isn't configured or fails,
    so callers fall back to a gentle template."""
    try:
        from .ai_client import get_client_from_settings
        client = get_client_from_settings(db)
        if not client:
            return ""
        stats_lines = "\n".join(
            f"- {k.replace('_', ' ')}: {v}" for k, v in payload["stats"].items() if v
        )
        moment_lines = "\n".join(
            f"- {m['date'] or 'sometime'}: {m['title'] or '(untitled)'}" for m in payload["moments"]
        )
        return client.person_year_note(payload["name"], stats_lines, moment_lines)
    except Exception as e:
        logger.warning("Person share note skipped: %s", e)
        return ""


def generate_person_share(db: Session, person, year: int) -> tuple[WrappedPersonShare, bool]:
    """Build (or refresh) the per-person share for a person+year. Idempotent - one row per person
    per year; refreshing rotates the token and re-snapshots the data."""
    payload = build_person_payload(db, person, year)
    note = _person_note(db, payload)
    if note:
        payload["note"] = note

    existing = db.query(WrappedPersonShare).filter_by(person_id=person.id, year=year).first()
    if existing:
        existing.data_json = json.dumps(payload)
        existing.token = secrets.token_urlsafe(16)
        existing.created_at = dt.datetime.utcnow()
        db.commit()
        return existing, False

    share = WrappedPersonShare(
        person_id=person.id,
        year=year,
        token=secrets.token_urlsafe(16),
        data_json=json.dumps(payload),
        created_at=dt.datetime.utcnow(),
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    return share, True


def get_person_share(db: Session, person_id: int, year: int) -> WrappedPersonShare | None:
    return db.query(WrappedPersonShare).filter_by(person_id=person_id, year=year).first()
