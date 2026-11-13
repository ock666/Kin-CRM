"""Per-household data scoping helpers.

Every entity that carries relationship data must be fetched through one of these helpers, so one
household can never read or mutate another household's rows. The rule is simple:

- `people`, `tags`, `wrapped_cards`, `user_stats`, `unlocked_achievements`, and `journal_entries`
  carry a `household_id`.
- Child rows (gift ideas, notable dates, scratchpad items, conflicts, drafts, etc.) are owned
  through their parent `Person`.
- Journal entries carry a `household_id` (visibility) plus an `author_user_id` (who wrote it).

If you add a new query against a household-scoped model, route it through here first.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import (
    Person, Tag, JournalEntry, UserStats, UnlockedAchievement, WrappedCard, User,
)


# --- household membership --------------------------------------------------
def household_member_ids(db: Session, user) -> list[int]:
    """The user ids of every member of `user`'s household (includes `user`)."""
    if user.household_id is None:
        return [user.id]
    return [u.id for u in db.query(User.id).filter(User.household_id == user.household_id).all()]


# --- root entity: people ---------------------------------------------------
def owned_people(db: Session, user):
    """Base query for the current user's household's people."""
    return db.query(Person).filter(Person.household_id == user.household_id)


def get_person(db: Session, user, person_id: int) -> Person | None:
    return db.query(Person).filter(
        Person.id == person_id, Person.household_id == user.household_id
    ).first()


def count_people(db: Session, user) -> int:
    return owned_people(db, user).count()


# --- tags ------------------------------------------------------------------
def owned_tags(db: Session, user):
    return db.query(Tag).filter(Tag.household_id == user.household_id)


def get_tag(db: Session, user, tag_id: int) -> Tag | None:
    return db.query(Tag).filter(Tag.id == tag_id, Tag.household_id == user.household_id).first()


def get_tag_by_name(db: Session, user, name: str) -> Tag | None:
    return db.query(Tag).filter(Tag.household_id == user.household_id, Tag.name == name).first()


# --- journal entries -------------------------------------------------------
def owned_journal_entries(db: Session, user):
    return db.query(JournalEntry).filter(JournalEntry.household_id == user.household_id)


def get_journal_entry(db: Session, user, entry_id: int) -> JournalEntry | None:
    entry = db.get(JournalEntry, entry_id)
    if entry is not None and entry.household_id == user.household_id:
        return entry
    return None


# --- child rows owned via their parent Person ------------------------------
def get_owned_child(db: Session, user, model, obj_id: int):
    """Fetch a child row only if its parent Person belongs to `user`'s household."""
    obj = db.get(model, obj_id)
    if obj is None:
        return None
    person = obj.person
    if person is None or person.household_id != user.household_id:
        return None
    return obj


# --- gamification / wrapped ------------------------------------------------
def get_stats(db: Session, user) -> UserStats | None:
    return db.query(UserStats).filter(UserStats.household_id == user.household_id).first()


def owned_achievements(db: Session, user):
    return db.query(UnlockedAchievement).filter(UnlockedAchievement.household_id == user.household_id)


def owned_wrapped_cards(db: Session, user):
    return db.query(WrappedCard).filter(WrappedCard.household_id == user.household_id)


def get_wrapped_card(db: Session, user, card_id: int) -> WrappedCard | None:
    return db.query(WrappedCard).filter(
        WrappedCard.id == card_id, WrappedCard.household_id == user.household_id
    ).first()
