"""Households — the unit that owns relationship data.

A household of one member is an "individual" (private) account; several members share one Kin.
This module handles creating households, linking accounts (merging their data), and the
single-use invite links that let someone join — or register into — a household.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import (
    Household, HouseholdInvite, HouseholdSetting, User, Person, Tag, JournalEntry,
    WrappedCard, UnlockedAchievement, UserStats, person_tags,
)


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


INVITE_TTL_DAYS = 7


def create_household(db: Session, name: str | None = None) -> Household:
    h = Household(name=name)
    db.add(h)
    db.flush()
    return h


def create_user(db: Session, name: str, email: str, password: str, *, is_admin: bool = False,
                household_id: int | None = None) -> User:
    """Create a user, assigning them a fresh individual household unless `household_id` is given."""
    from ..auth import hash_password
    if household_id is None:
        household_id = create_household(db, name=name).id
    u = User(
        name=name, email=email.lower().strip(),
        hashed_password=hash_password(password),
        is_admin=is_admin, household_id=household_id,
    )
    db.add(u)
    db.flush()
    return u


def household_members(db: Session, household_id: int) -> list[User]:
    return db.query(User).filter(User.household_id == household_id).all()


# ---------------------------------------------------------------------------
# Linking / merging
# ---------------------------------------------------------------------------

def merge_households(db: Session, source_id: int, target_id: int) -> None:
    """Move all of `source` household's data into `target`, dedup tags/achievements, merge
    gamification, and delete the source household. Target's household config wins."""
    if source_id == target_id:
        return

    # Root entities: re-own to target.
    db.query(Person).filter(Person.household_id == source_id).update({"household_id": target_id})
    db.query(JournalEntry).filter(JournalEntry.household_id == source_id).update({"household_id": target_id})
    db.query(WrappedCard).filter(WrappedCard.household_id == source_id).update({"household_id": target_id})

    # Tags: dedup by name (target keeps its copy, source's people re-point to it).
    target_tags = {t.name: t for t in db.query(Tag).filter(Tag.household_id == target_id).all()}
    for tag in db.query(Tag).filter(Tag.household_id == source_id).all():
        keep = target_tags.get(tag.name)
        if keep is not None:
            db.execute(
                person_tags.update().where(person_tags.c.tag_id == tag.id).values(tag_id=keep.id)
            )
            db.delete(tag)
        else:
            tag.household_id = target_id
            target_tags[tag.name] = tag

    # Achievements: dedup by slug.
    target_slugs = {a.slug for a in db.query(UnlockedAchievement).filter(UnlockedAchievement.household_id == target_id).all()}
    for a in db.query(UnlockedAchievement).filter(UnlockedAchievement.household_id == source_id).all():
        if a.slug in target_slugs:
            db.delete(a)
        else:
            a.household_id = target_id
            target_slugs.add(a.slug)

    # Gamification: merge XP into the target, keep the higher streak.
    src_stats = db.query(UserStats).filter(UserStats.household_id == source_id).first()
    tgt_stats = db.query(UserStats).filter(UserStats.household_id == target_id).first()
    if src_stats is not None:
        if tgt_stats is not None:
            tgt_stats.total_xp += src_stats.total_xp
            tgt_stats.streak_days = max(tgt_stats.streak_days or 0, src_stats.streak_days or 0)
            tgt_stats.last_active_date = src_stats.last_active_date or tgt_stats.last_active_date
            db.delete(src_stats)
        else:
            src_stats.household_id = target_id

    # Household config: target wins, drop source's.
    db.query(HouseholdSetting).filter(HouseholdSetting.household_id == source_id).delete()

    # Re-point the source's members, then delete the source household.
    db.query(User).filter(User.household_id == source_id).update({"household_id": target_id})
    hh = db.get(Household, source_id)
    if hh is not None:
        db.delete(hh)
    db.commit()


def link_user(db: Session, user: User, target_household_id: int) -> bool:
    """Link `user` (and their whole household) into `target_household_id`. Returns False if they
    are already in that household."""
    if user.household_id == target_household_id:
        return False
    merge_households(db, user.household_id, target_household_id)
    db.refresh(user)
    return True


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------

def generate_invite(db: Session, user: User) -> HouseholdInvite:
    inv = HouseholdInvite(
        household_id=user.household_id,
        token=secrets.token_urlsafe(24),
        created_by_user_id=user.id,
        expires_at=utcnow() + timedelta(days=INVITE_TTL_DAYS),
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


def get_valid_invite(db: Session, token: str) -> HouseholdInvite | None:
    inv = db.query(HouseholdInvite).filter(HouseholdInvite.token == token).first()
    if inv is None or inv.used_at is not None or inv.expires_at < utcnow():
        return None
    return inv


def latest_active_invite(db: Session, household_id: int) -> HouseholdInvite | None:
    """The most recent unexpired, unused invite for a household (for the management page)."""
    now = utcnow()
    return (
        db.query(HouseholdInvite)
        .filter(HouseholdInvite.household_id == household_id)
        .filter(HouseholdInvite.used_at.is_(None))
        .filter(HouseholdInvite.expires_at >= now)
        .order_by(HouseholdInvite.created_at.desc())
        .first()
    )


def accept_invite(db: Session, user: User, token: str) -> HouseholdInvite | None:
    """Link `user` into the invite's household. Returns the invite on success, None if invalid
    or already a member."""
    inv = get_valid_invite(db, token)
    if inv is None or user.household_id == inv.household_id:
        return None
    link_user(db, user, inv.household_id)
    inv.used_at = utcnow()
    inv.accepted_by_user_id = user.id
    db.commit()
    return inv
