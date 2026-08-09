"""Standalone gamification overlay (v1.2).

Design goals (deliberately cost-conscious, per the architecture we agreed on):
  - Zero AI/LLM calls at runtime - this is pure Python math + simple SQLite queries.
  - Isolated in this one file - existing routes only need a single extra line calling
    `award_and_flash(...)` (or `check_only(...)` for achievement-only triggers with no XP)
    right before their normal redirect, no rewriting of existing logic.
  - Shared/household-wide progression (one singleton UserStats row, id=1) rather than
    per-login-user, matching this app's shared-workspace model (see models.py).
  - "Reward cadence over spam": plain XP gains accumulate silently (visible any time on the
    dashboard "Your progress" card); a toast notice only appears for something genuinely
    noteworthy - a level-up or a new badge - never for routine +15 XP notifications.

NOTE ON SCOPE: a handful of achievements from the original wishlist are NOT implemented here
because they depend on Phase B features that haven't been built yet (no underlying data exists
to check against): `screenshot_sleuth` (needs image_type categorization on attachments),
`co_occurrence` (needs the Immich "auto-hangout" co-occurrence radar), and the relationship-graph
achievements `graph_weaver`/`social_architect`/`bridge_builder`/`six_degrees` (need the
relationship-network-graph feature). If those features get built later, add their achievements
here at the same time.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    UserStats, UnlockedAchievement, JournalEntry, JournalImage, Person,
    NotablePersonRef, ScratchpadItem, GiftIdea, journal_entry_people,
)

# 1. Hardcoded XP rules - tune freely, no migration needed since these aren't stored in the DB.
XP_EVENTS = {
    "NOTE_ADDED": 15,
    "PROFILE_UPDATED": 30,
    "PHOTO_ATTACHED": 50,
    "OVERDUE_CHECKIN": 100,
    "CONFLICT_RESOLVED": 50,
}

# Metadata for display purposes only - kept separate from the pure unlock-condition logic in
# `check_achievements()` below. Format: slug -> (emoji, label, description, hidden).
# `hidden=True` achievements are easter eggs - their name/description are masked on the
# /progress page until unlocked, so they stay a surprise.
ACHIEVEMENTS: dict[str, tuple[str, str, str, bool]] = {
    # --- Early habit builders ---
    "first_step": ("🌱", "First Step", "Logged your very first journal entry", False),
    "circle_builder": ("⭕", "Circle Builder", "Created 3 person profiles", False),
    "social_network": ("🌐", "Social Network", "Created 10 person profiles", False),
    "face_to_name": ("📸", "Face to Name", "Linked an Immich photo to a person profile", False),
    "details_matter": ("🏷️", "Details Matter", "Added a birthday, occupation, or hobby to a profile", False),
    "well_connected": ("🔗", "Well Connected", "Added contact info to a profile", False),
    # --- Streaks & consistency ---
    "3_day_streak": ("⚡", "Momentum", "Logged an activity 3 days in a row", False),
    "7_day_streak": ("🔥", "Consistent", "Logged an activity 7 days in a row", False),
    "14_day_streak": ("🚀", "Dedicated", "Logged an activity 14 days in a row", False),
    "30_day_streak": ("🔥🔥", "Unstoppable", "Logged an activity 30 days in a row", False),
    "100_day_streak": ("👑", "Century Club", "Logged an activity 100 days in a row", False),
    "weekend_warrior": ("🍻", "Weekend Warrior", "Logged entries on both Saturday and Sunday of the same weekend", False),
    # --- Breadth & cadence ---
    "social_butterfly": ("🦋", "Social Butterfly", "Tagged 5+ different people in the last 30 days", False),
    "the_connector": ("🕸️", "The Connector", "Tagged 10+ different people in the last 30 days", False),
    "the_revivalist": ("⚡", "The Revivalist", "Checked in with someone whose cadence was overdue", False),
    "no_friend_left_behind": ("🛡️", "No Friend Left Behind", "Cleared every overdue check-in at once", False),
    "party_planner": ("🎉", "Party Planner", "Tagged 4+ people together in a single log", False),
    "check_in_champ": ("💬", "Check-in Champ", "Logged 5+ entries in a single week", False),
    "cadence_master": ("⏱️", "Cadence Master", "Assigned a check-in cadence to 5+ people", False),
    # --- Depth & attention ---
    "inner_circle": ("💎", "Inner Circle", "Logged 10+ entries with a single person", False),
    "besties": ("🤝", "Besties", "Logged 25+ entries with a single person", False),
    "notable_mentions": ("⭐", "VIP Table", "Added a notable person (e.g. their partner or mum) to a profile", False),
    "deep_listener": ("👂", "Deep Listener", "Wrote a journal entry over 100 words long", False),
    "scratchpad_user": ("📝", "Bring It Up", "Added an item to someone's scratchpad", False),
    "scratchpad_clearer": ("✅", "Followed Through", "Cleared an item from a scratchpad", False),
    # --- Immich, media & archives ---
    "the_historian": ("📜", "The Historian", "Logged 10+ backdated memories", False),
    "memory_keeper": ("🖼️", "Memory Keeper", "Attached 5+ photos across your journal entries", False),
    "photo_album": ("📚", "Photo Album", "Attached 25+ photos across your journal entries", False),
    "on_this_day": ("🗓️", "On This Day", "Viewed an 'On This Day' Immich memory on the dashboard", False),
    "peace_maker": ("🕊️", "Peace Maker", "Resolved or mindfully released an interpersonal conflict", False),
    # --- Hidden easter eggs ---
    "night_owl": ("🦉", "Night Owl", "Logged an entry between 1am and 5am", True),
    "birthday_hero": ("🎂", "Birthday Hero", "Logged an entry on someone's actual birthday", True),
    "gift_giver": ("🎁", "Thoughtful Giver", "Got an AI gift suggestion for someone's birthday", True),
    "time_traveler": ("⏳", "Time Traveler", "Logged a backdated memory from more than 5 years ago", True),
    "new_years_toast": ("🥂", "Auld Lang Syne", "Logged an entry on New Year's Eve or Day", True),
    "completionist": ("🏆", "The Completionist", "Unlocked 30 other achievements", True),
}


def calculate_level(total_xp: int) -> int:
    """Smooth quadratic-ish leveling curve - each level requires progressively more XP."""
    level = 1
    while total_xp >= int(100 * (level ** 1.5)):
        level += 1
    return level


def _get_or_create_stats(db: Session) -> UserStats:
    stats = db.get(UserStats, 1)
    if not stats:
        stats = UserStats(id=1, total_xp=0, current_level=1, streak_days=0)
        db.add(stats)
        db.flush()
    return stats


def award_xp(db: Session, event_type: str, context: dict | None = None) -> dict:
    """Award XP for one event, update the daily streak, check for newly-unlocked achievements,
    and commit. Safe to call multiple times per day - the streak only increments once/day
    regardless of how many events fire. `context` carries optional event-specific details (e.g.
    how many people were tagged in the entry that triggered this) used by a handful of
    achievement checks that can't be derived from aggregate DB state alone."""
    stats = _get_or_create_stats(db)

    xp_gained = XP_EVENTS.get(event_type, 10)
    stats.total_xp += xp_gained
    new_level = calculate_level(stats.total_xp)

    level_up = new_level > stats.current_level
    if level_up:
        stats.current_level = new_level

    today = dt.date.today().isoformat()
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    if stats.last_active_date == yesterday:
        stats.streak_days += 1
    elif stats.last_active_date != today:
        stats.streak_days = 1
    stats.last_active_date = today

    new_badges = check_achievements(db, stats, event_type=event_type, context=context)

    db.commit()
    db.refresh(stats)

    return {
        "xp_gained": xp_gained,
        "total_xp": stats.total_xp,
        "current_level": stats.current_level,
        "level_up": level_up,
        "streak_days": stats.streak_days,
        "unlocked_badges": new_badges,
    }


def check_achievements(db: Session, stats: UserStats, event_type: str | None = None,
                        context: dict | None = None) -> list[str]:
    """Pure-Python/SQL achievement checks - no AI calls. Returns slugs newly unlocked this call.

    Most checks are cheap aggregate queries re-derived fresh from current DB state each time
    (and skipped entirely once already unlocked, so the cost only ever goes down over time as
    more things get permanently unlocked). A handful genuinely need to know something about the
    specific action that just happened (e.g. "was this entry over 100 words?") - those read from
    the optional `context` dict, which callers populate on a best-effort basis; a missing key
    just means that particular check is skipped this call, not an error.
    """
    context = context or {}
    newly_unlocked: list[str] = []
    already = {row.slug for row in db.query(UnlockedAchievement.slug).all()}

    def _unlock(slug: str):
        if slug not in already:
            db.add(UnlockedAchievement(slug=slug))
            newly_unlocked.append(slug)
            already.add(slug)

    def _locked(slug: str) -> bool:
        return slug not in already

    # --- Streak-based (cheap, use the live `stats` object we already have) ---
    if stats.streak_days >= 3:
        _unlock("3_day_streak")
    if stats.streak_days >= 7:
        _unlock("7_day_streak")
    if stats.streak_days >= 14:
        _unlock("14_day_streak")
    if stats.streak_days >= 30:
        _unlock("30_day_streak")
    if stats.streak_days >= 100:
        _unlock("100_day_streak")

    # --- Simple aggregate counts (one cheap COUNT query each, skipped if already unlocked) ---
    if _locked("first_step") and db.query(JournalEntry).count() >= 1:
        _unlock("first_step")
    if _locked("circle_builder") and db.query(Person).count() >= 3:
        _unlock("circle_builder")
    if _locked("social_network") and db.query(Person).count() >= 10:
        _unlock("social_network")
    if _locked("face_to_name") and db.query(Person).filter(Person.immich_person_id.isnot(None)).count() >= 1:
        _unlock("face_to_name")
    if _locked("notable_mentions") and db.query(NotablePersonRef).count() >= 1:
        _unlock("notable_mentions")
    if _locked("scratchpad_user") and db.query(ScratchpadItem).count() >= 1:
        _unlock("scratchpad_user")
    if _locked("memory_keeper") and db.query(JournalImage).count() >= 5:
        _unlock("memory_keeper")
    if _locked("photo_album") and db.query(JournalImage).count() >= 25:
        _unlock("photo_album")
    if _locked("gift_giver") and db.query(GiftIdea).count() >= 1:
        _unlock("gift_giver")
    if _locked("cadence_master") and db.query(Person).filter(Person.checkin_cadence_days.isnot(None)).count() >= 5:
        _unlock("cadence_master")
    if _locked("details_matter"):
        has_details = db.query(Person).filter(
            (Person.birthday_month.isnot(None)) | (Person.occupation.isnot(None)) | (Person.hobbies.isnot(None))
        ).count() >= 1
        if has_details:
            _unlock("details_matter")
    if _locked("well_connected"):
        has_contact = db.query(Person).filter(
            (Person.email.isnot(None)) | (Person.phone.isnot(None)) | (Person.instagram_username.isnot(None))
        ).count() >= 1
        if has_contact:
            _unlock("well_connected")

    # --- Distinct-people-in-last-30-days (shared query for two thresholds) ---
    if _locked("social_butterfly") or _locked("the_connector"):
        cutoff = dt.date.today() - dt.timedelta(days=30)
        distinct_people = (
            db.query(journal_entry_people.c.person_id)
            .join(JournalEntry, JournalEntry.id == journal_entry_people.c.journal_entry_id)
            .filter(JournalEntry.entry_date >= cutoff)
            .distinct()
            .count()
        )
        if distinct_people >= 5:
            _unlock("social_butterfly")
        if distinct_people >= 10:
            _unlock("the_connector")

    # --- Per-person entry counts (inner_circle / besties) ---
    if _locked("inner_circle") or _locked("besties"):
        max_count = (
            db.query(func.count(journal_entry_people.c.journal_entry_id))
            .group_by(journal_entry_people.c.person_id)
            .order_by(func.count(journal_entry_people.c.journal_entry_id).desc())
            .limit(1)
            .scalar()
        ) or 0
        if max_count >= 10:
            _unlock("inner_circle")
        if max_count >= 25:
            _unlock("besties")

    # --- Full-table scans (only needed while still locked - naturally gets cheaper over time) ---
    if _locked("the_historian"):
        backdated = sum(
            1 for e in db.query(JournalEntry).all()
            if e.created_at and e.entry_date < e.created_at.date()
        )
        if backdated >= 10:
            _unlock("the_historian")

    if _locked("weekend_warrior"):
        entry_dates = {e.entry_date for e in db.query(JournalEntry.entry_date).all()}
        if any(d.weekday() == 5 and (d + dt.timedelta(days=1)) in entry_dates for d in entry_dates):
            _unlock("weekend_warrior")

    if _locked("check_in_champ"):
        week_counts: dict[tuple[int, int], int] = {}
        for e in db.query(JournalEntry.entry_date).all():
            key = e.entry_date.isocalendar()[:2]  # (iso_year, iso_week)
            week_counts[key] = week_counts.get(key, 0) + 1
        if any(c >= 5 for c in week_counts.values()):
            _unlock("check_in_champ")

    # --- Event-specific (need `context` from the caller - skipped gracefully if absent) ---
    if event_type == "OVERDUE_CHECKIN":
        _unlock("the_revivalist")
        if context.get("all_overdue_cleared"):
            _unlock("no_friend_left_behind")

    if event_type == "CONFLICT_RESOLVED":
        _unlock("peace_maker")

    if context.get("entry_people_count", 0) >= 4:
        _unlock("party_planner")
    if context.get("entry_word_count", 0) > 100:
        _unlock("deep_listener")
    if context.get("scratchpad_cleared"):
        _unlock("scratchpad_clearer")
    if context.get("viewed_on_this_day"):
        _unlock("on_this_day")

    entry_hour = context.get("entry_hour")
    if entry_hour is not None and 1 <= entry_hour < 5:
        _unlock("night_owl")
    if context.get("entry_matches_birthday"):
        _unlock("birthday_hero")
    if context.get("entry_years_back", 0) > 5:
        _unlock("time_traveler")
    if context.get("entry_is_new_year"):
        _unlock("new_years_toast")

    # --- Meta achievement - checked last so it sees this call's other unlocks too ---
    if _locked("completionist") and len(already) >= 30:
        _unlock("completionist")

    return newly_unlocked


def award_and_flash(request, db: Session, *event_types: str, context: dict | None = None) -> dict:
    """The one-line hook for existing routes: awards XP for one or more events (e.g. logging a
    journal entry that also had a photo attached fires both NOTE_ADDED and PHOTO_ATTACHED), then
    stashes a "flash" notice in the session ONLY if something toast-worthy happened (a level-up
    or a new badge) - routine XP gains accumulate silently, surfaced only on the progress page/
    dashboard card, to avoid notification spam."""
    results = [award_xp(db, event_type, context=context) for event_type in event_types]
    total_gained = sum(r["xp_gained"] for r in results)
    level_up = any(r["level_up"] for r in results)
    badges: list[str] = []
    for r in results:
        badges.extend(r["unlocked_badges"])
    final = results[-1]

    if level_up or badges:
        request.session["gamification_flash"] = {
            "xp_gained": total_gained,
            "level_up": level_up,
            "current_level": final["current_level"],
            "unlocked_badges": badges,
        }
    return final


def check_only(request, db: Session, context: dict | None = None) -> list[str]:
    """For achievement-only triggers that don't earn XP (e.g. viewing an 'On This Day' memory,
    or linking an Immich face) - checks/unlocks achievements and flashes a toast on a new badge,
    without touching XP/level/streak state at all."""
    stats = _get_or_create_stats(db)
    new_badges = check_achievements(db, stats, context=context)
    if new_badges:
        db.commit()
        request.session["gamification_flash"] = {
            "xp_gained": 0, "level_up": False, "current_level": stats.current_level,
            "unlocked_badges": new_badges,
        }
    return new_badges


def get_stats_and_achievements(db: Session) -> dict:
    """For the dashboard widget / progress page - current stats plus the full achievement
    catalog annotated with unlocked/locked status. Hidden (easter-egg) achievements that are
    still locked have their name/description masked so they stay a surprise."""
    stats = _get_or_create_stats(db)
    db.commit()  # persist a freshly-created row immediately so the page has something to show
    unlocked_slugs = {row.slug for row in db.query(UnlockedAchievement.slug).all()}

    next_level_threshold = int(100 * (stats.current_level ** 1.5))
    prev_level_threshold = int(100 * ((stats.current_level - 1) ** 1.5)) if stats.current_level > 1 else 0
    span = max(next_level_threshold - prev_level_threshold, 1)
    progress_pct = max(0, min(100, round((stats.total_xp - prev_level_threshold) / span * 100)))

    achievements = []
    for slug, (emoji, label, desc, hidden) in ACHIEVEMENTS.items():
        unlocked = slug in unlocked_slugs
        if hidden and not unlocked:
            achievements.append({"slug": slug, "emoji": "❓", "label": "???",
                                  "description": "A hidden achievement - keep exploring.",
                                  "unlocked": False})
        else:
            achievements.append({"slug": slug, "emoji": emoji, "label": label,
                                  "description": desc, "unlocked": unlocked})

    return {
        "stats": stats,
        "next_level_threshold": next_level_threshold,
        "progress_pct": progress_pct,
        "achievements": achievements,
        "unlocked_count": len(unlocked_slugs),
        "total_count": len(ACHIEVEMENTS),
    }
