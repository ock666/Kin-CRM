"""Standalone gamification overlay (v1.2).

Design goals (deliberately cost-conscious, per the architecture we agreed on):
  - Zero AI/LLM calls at runtime - this is pure Python math + simple SQLite queries.
  - Isolated in this one file - existing routes only need a single extra line calling
    `award_and_flash(...)` right before their normal redirect, no rewriting of existing logic.
  - Shared/household-wide progression (one singleton UserStats row, id=1) rather than
    per-login-user, matching this app's shared-workspace model (see models.py).
  - "Reward cadence over spam": plain XP gains accumulate silently (visible any time on the
    dashboard "Your progress" card); a toast notice only appears for something genuinely
    noteworthy - a level-up or a new badge - never for routine +15 XP notifications.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from ..models import UserStats, UnlockedAchievement, JournalEntry, journal_entry_people

# 1. Hardcoded XP rules - tune freely, no migration needed since these aren't stored in the DB.
XP_EVENTS = {
    "NOTE_ADDED": 15,
    "PROFILE_UPDATED": 30,
    "PHOTO_ATTACHED": 50,
    "OVERDUE_CHECKIN": 100,
}

# Metadata for display purposes only (emoji/label/description) - kept separate from the
# pure unlock-condition logic in `check_achievements()` below.
ACHIEVEMENTS = {
    "7_day_streak": ("🔥", "Consistent", "Logged something 7 days in a row"),
    "30_day_streak": ("🔥🔥", "Dedicated", "Logged something 30 days in a row"),
    "social_butterfly": ("🦋", "Social Butterfly", "Tagged 5+ different people in the last 30 days"),
    "the_historian": ("📜", "The Historian", "Logged 10+ backdated memories"),
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


def award_xp(db: Session, event_type: str) -> dict:
    """Award XP for one event, update the daily streak, check for newly-unlocked achievements,
    and commit. Safe to call multiple times per day - the streak only increments once/day
    regardless of how many events fire."""
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

    new_badges = check_achievements(db, stats)

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


def check_achievements(db: Session, stats: UserStats) -> list[str]:
    """Pure-Python/SQL achievement checks - no AI calls. Returns slugs newly unlocked this call
    (empty if nothing new, or if already unlocked previously)."""
    newly_unlocked: list[str] = []
    already = {row.slug for row in db.query(UnlockedAchievement.slug).all()}

    def _unlock(slug: str):
        if slug not in already:
            db.add(UnlockedAchievement(slug=slug))
            newly_unlocked.append(slug)
            already.add(slug)

    if stats.streak_days >= 7:
        _unlock("7_day_streak")
    if stats.streak_days >= 30:
        _unlock("30_day_streak")

    if "social_butterfly" not in already:
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

    if "the_historian" not in already:
        backdated = sum(
            1 for e in db.query(JournalEntry).all()
            if e.created_at and e.entry_date < e.created_at.date()
        )
        if backdated >= 10:
            _unlock("the_historian")

    return newly_unlocked


def award_and_flash(request, db: Session, *event_types: str) -> dict:
    """The one-line hook for existing routes: awards XP for one or more events (e.g. logging a
    journal entry that also had a photo attached fires both NOTE_ADDED and PHOTO_ATTACHED), then
    stashes a "flash" notice in the session ONLY if something toast-worthy happened (a level-up
    or a new badge) - routine XP gains accumulate silently, surfaced only on the progress page/
    dashboard card, to avoid notification spam."""
    results = [award_xp(db, event_type) for event_type in event_types]
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


def get_stats_and_achievements(db: Session) -> dict:
    """For the dashboard widget / progress page - current stats plus the full achievement
    catalog annotated with unlocked/locked status."""
    stats = _get_or_create_stats(db)
    db.commit()  # persist a freshly-created row immediately so the page has something to show
    unlocked_slugs = {row.slug for row in db.query(UnlockedAchievement.slug).all()}

    next_level_threshold = int(100 * (stats.current_level ** 1.5))
    prev_level_threshold = int(100 * ((stats.current_level - 1) ** 1.5)) if stats.current_level > 1 else 0
    span = max(next_level_threshold - prev_level_threshold, 1)
    progress_pct = max(0, min(100, round((stats.total_xp - prev_level_threshold) / span * 100)))

    achievements = [
        {
            "slug": slug, "emoji": emoji, "label": label, "description": desc,
            "unlocked": slug in unlocked_slugs,
        }
        for slug, (emoji, label, desc) in ACHIEVEMENTS.items()
    ]

    return {
        "stats": stats,
        "next_level_threshold": next_level_threshold,
        "progress_pct": progress_pct,
        "achievements": achievements,
    }
