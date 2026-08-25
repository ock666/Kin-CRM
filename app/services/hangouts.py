"""Hangout detection via Immich.

If a CRM person has an Immich face linked (`Person.immich_person_id`) and that face appears in a
photo taken within the last ~30 days, we know you two actually saw each other recently - so the
dashboard can surface it ("hey! looks like you guys hung out") and credit it against their
check-in cadence instead of nudging you to reach out.

Design notes:
  - One failing person is skipped rather than aborting the whole card; only a fatal setup problem
    (Immich not configured / unreachable) surfaces as an error message.
  - The Immich search window is padded by 24h either side and filtered precisely on the asset's
    `localDateTime` (same reasoning as `immich_client.assets_on_date_across_years`), so a photo
    taken in the user's local evening isn't clipped by Immich's UTC storage.
  - This module performs no DB writes - the dashboard route decides how to credit a hangout.
"""
from __future__ import annotations

import datetime as dt
import time

from sqlalchemy.orm import Session

from ..models import HangoutDismissal, JournalEntry, JournalImage, Person, journal_entry_people
from ..services.immich_client import ImmichError, _parse_asset_datetime


def _attached_entries_for_assets(db: Session, person: Person, asset_ids: list[str]):
    """Newest-first JournalEntries tagged with `person` that already have any of these Immich
    assets attached. Used to avoid offering to re-log a hangout whose photo is already on the
    person's timeline."""
    if not asset_ids:
        return []
    attached_ids = [
        r[0] for r in db.query(JournalImage.journal_entry_id)
        .filter(JournalImage.immich_asset_id.in_(asset_ids)).all()
    ]
    if not attached_ids:
        return []
    return (
        db.query(JournalEntry)
        .join(journal_entry_people, journal_entry_people.c.journal_entry_id == JournalEntry.id)
        .filter(journal_entry_people.c.person_id == person.id)
        .filter(JournalEntry.id.in_(attached_ids))
        .order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc())
        .all()
    )


def attached_asset_ids(db: Session, person: Person, asset_ids: list[str]) -> set[str]:
    """Subset of `asset_ids` already attached to a journal entry tagged with `person`."""
    if not asset_ids:
        return set()
    rows = (
        db.query(JournalImage.immich_asset_id)
        .join(JournalEntry, JournalEntry.id == JournalImage.journal_entry_id)
        .join(journal_entry_people, journal_entry_people.c.journal_entry_id == JournalEntry.id)
        .filter(journal_entry_people.c.person_id == person.id)
        .filter(JournalImage.immich_asset_id.in_(asset_ids))
        .all()
    )
    return {r[0] for r in rows}


def unattached_asset_ids(db: Session, person: Person, asset_ids: list[str]) -> list[str]:
    """`asset_ids` that are NOT yet attached to any entry tagged with `person` - the safe set to
    log when the user confirms a hangout."""
    return [a for a in asset_ids if a not in attached_asset_ids(db, person, asset_ids)]


def is_dismissed(db: Session, person: Person, date: dt.date) -> bool:
    """True when the user dismissed this person's hangout for `date` on the dashboard."""
    return (
        db.query(HangoutDismissal.id)
        .filter_by(person_id=person.id, dismissed_for_date=date)
        .first() is not None
    )


def _relative_label(date: dt.date, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    delta = (today - date).days
    if delta <= 0:
        return "today"
    if delta == 1:
        return "yesterday"
    if delta < 7:
        return f"{delta} days ago"
    weeks = delta // 7
    if weeks < 5:
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    return date.isoformat()


def detect_recent_hangouts(db: Session, client, window_days: int = 31,
                           max_people: int = 20) -> tuple[list[dict], str | None]:
    """Return (hangouts, error).

    `hangouts` is a list of dicts, newest first:
        {"person": Person, "latest_date": dt.date, "label": str,
         "thumbnails": [asset_id, ...], "new_asset_ids": [asset_id, ...],
         "all_logged": bool, "existing_entry": {"id", "title", "entry_date"} | None}
    for every non-archived person with an Immich face link who appears in a photo within the last
    `window_days` days. `thumbnails` holds up to 6 recent asset ids for the dashboard card;
    `new_asset_ids` is the subset not yet attached to an entry tagged with this person; if every
    photo is already logged (`all_logged`) `existing_entry` points at the newest matching entry.
    `dismissed` is True when the user dismissed this (person, date) hangout; the dashboard hides
    dismissed rows but still credits them.
    """
    if window_days <= 0:
        return [], None

    cutoff = dt.date.today() - dt.timedelta(days=window_days)
    people = (
        db.query(Person)
        .filter(Person.archived.is_(False))
        .filter(Person.immich_person_id.isnot(None))
        .order_by(Person.id)
        .limit(max_people)
        .all()
    )
    if not people:
        return [], None

    # Immich's search/metadata filters `takenAfter`/`takenBefore` on UTC, so pad 24h either side
    # and filter precisely on localDateTime below.
    window_start = dt.datetime.combine(cutoff, dt.time.min) - dt.timedelta(hours=24)
    window_end = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=24)

    hangouts = []
    for person in people:
        try:
            assets = client.search_by_person(
                person.immich_person_id,
                taken_after=window_start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                taken_before=window_end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                size=100,
            )
        except ImmichError:
            continue

        recent = []
        for asset in assets:
            local_dt = _parse_asset_datetime(asset)
            if local_dt and local_dt.date() >= cutoff:
                recent.append((local_dt, asset))
        if not recent:
            continue

        recent.sort(key=lambda t: t[0], reverse=True)
        latest_date = recent[0][0].date()
        thumbnails = [a["id"] for _, a in recent[:6]]
        attached = attached_asset_ids(db, person, thumbnails)
        new_asset_ids = [a for a in thumbnails if a not in attached]
        existing = _attached_entries_for_assets(db, person, thumbnails)
        existing_entry = None
        if existing:
            e = existing[0]
            existing_entry = {
                "id": e.id,
                "title": e.title,
                "entry_date": e.entry_date,
            }
        hangouts.append({
            "person": person,
            "latest_date": latest_date,
            "label": _relative_label(latest_date),
            "thumbnails": thumbnails,
            "new_asset_ids": new_asset_ids,
            "all_logged": not new_asset_ids,
            "existing_entry": existing_entry,
            "dismissed": is_dismissed(db, person, latest_date),
        })

    hangouts.sort(key=lambda h: h["latest_date"], reverse=True)
    return hangouts, None


# --- Detection cache -----------------------------------------------------------
# Each dashboard load runs up to `max_people` sequential Immich searches. That's fine once, but
# not on every page view, so we cache the raw detection and rehydrate fresh Person objects per
# request. Invalidated whenever the user logs or dismisses a hangout so those actions show up
# immediately; otherwise the card can be up to CACHE_TTL seconds stale (Immich photos change far
# less often than the dashboard is opened).

CACHE_TTL_SECONDS = 15 * 60
_detection_cache: dict = {"ts": None, "items": None, "error": None}


def invalidate_hangout_cache():
    _detection_cache["ts"] = None
    _detection_cache["items"] = None
    _detection_cache["error"] = None


def _serialize_hangouts(hangouts: list[dict], error: str | None) -> tuple[list[dict], str | None]:
    items = [{
        "person_id": h["person"].id,
        "latest_date": h["latest_date"].isoformat(),
        "label": h["label"],
        "thumbnails": h["thumbnails"],
        "new_asset_ids": h["new_asset_ids"],
        "all_logged": h["all_logged"],
        "existing_entry": h["existing_entry"],
        "dismissed": h["dismissed"],
    } for h in hangouts]
    return items, error


def _rehydrate_hangouts(db: Session, items: list[dict]) -> list[dict]:
    hangouts = []
    for it in items:
        person = db.get(Person, it["person_id"])
        if person is None:
            continue
        hangouts.append({
            "person": person,
            "latest_date": dt.date.fromisoformat(it["latest_date"]),
            "label": it["label"],
            "thumbnails": it["thumbnails"],
            "new_asset_ids": it["new_asset_ids"],
            "all_logged": it["all_logged"],
            "existing_entry": it["existing_entry"],
            "dismissed": it["dismissed"],
        })
    return hangouts


def get_recent_hangouts_cached(db: Session, client, window_days: int = 31,
                                max_people: int = 20) -> tuple[list[dict], str | None]:
    """`detect_recent_hangouts` with a short TTL cache so the dashboard doesn't hammer Immich on
    every load. On a cache hit, Person rows are re-fetched so they belong to the current request
    session; logging or dismissing a hangout calls `invalidate_hangout_cache()` first."""
    now = time.time()
    if _detection_cache["ts"] is not None and now - _detection_cache["ts"] < CACHE_TTL_SECONDS:
        return _rehydrate_hangouts(db, _detection_cache["items"]), _detection_cache["error"]
    hangouts, error = detect_recent_hangouts(db, client, window_days=window_days, max_people=max_people)
    _detection_cache["ts"] = now
    _detection_cache["items"], _detection_cache["error"] = _serialize_hangouts(hangouts, error)
    return hangouts, error
