"""Per-user data scoping helpers.

Every entity that carries a user's relationship data must be fetched through one of these
helpers, so one user can never read or mutate another user's rows. The rule is simple:

- `people`, `tags`, `wrapped_cards`, `user_stats`, `unlocked_achievements` carry a `user_id`.
- Child rows (gift ideas, notable dates, scratchpad items, conflicts, drafts, etc.) are owned
  through their parent `Person`.
- Journal entries are owned through `author_user_id`.

If you add a new query against a user-scoped model, route it through here first.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Person, Tag, JournalEntry, UserStats, UnlockedAchievement, WrappedCard


# --- root entity: people ---------------------------------------------------
def owned_people(db: Session, user):
    """Base query for the current user's people."""
    return db.query(Person).filter(Person.user_id == user.id)


def get_person(db: Session, user, person_id: int) -> Person | None:
    return db.query(Person).filter(Person.id == person_id, Person.user_id == user.id).first()


def count_people(db: Session, user) -> int:
    return owned_people(db, user).count()


# --- tags ------------------------------------------------------------------
def owned_tags(db: Session, user):
    return db.query(Tag).filter(Tag.user_id == user.id)


def get_tag(db: Session, user, tag_id: int) -> Tag | None:
    return db.query(Tag).filter(Tag.id == tag_id, Tag.user_id == user.id).first()


def get_tag_by_name(db: Session, user, name: str) -> Tag | None:
    return db.query(Tag).filter(Tag.user_id == user.id, Tag.name == name).first()


# --- journal entries -------------------------------------------------------
def owned_journal_entries(db: Session, user):
    return db.query(JournalEntry).filter(JournalEntry.author_user_id == user.id)


def get_journal_entry(db: Session, user, entry_id: int) -> JournalEntry | None:
    entry = db.get(JournalEntry, entry_id)
    if entry is not None and entry.author_user_id == user.id:
        return entry
    return None


# --- child rows owned via their parent Person ------------------------------
_CHILD_VIA_PERSON = (
    "ConflictLog", "GiftIdea", "BirthdayMessageDraft", "ScratchpadItem",
    "NotablePersonRef", "NotableDate", "HangoutDismissal", "WrappedPersonShare",
)


def get_owned_child(db: Session, user, model, obj_id: int):
    """Fetch a child row only if its parent Person belongs to `user`."""
    obj = db.get(model, obj_id)
    if obj is None:
        return None
    person = obj.person
    if person is None or person.user_id != user.id:
        return None
    return obj


# --- gamification / wrapped ------------------------------------------------
def get_stats(db: Session, user) -> UserStats | None:
    return db.query(UserStats).filter(UserStats.user_id == user.id).first()


def owned_achievements(db: Session, user):
    return db.query(UnlockedAchievement).filter(UnlockedAchievement.user_id == user.id)


def owned_wrapped_cards(db: Session, user):
    return db.query(WrappedCard).filter(WrappedCard.user_id == user.id)


def get_wrapped_card(db: Session, user, card_id: int) -> WrappedCard | None:
    return db.query(WrappedCard).filter(WrappedCard.id == card_id, WrappedCard.user_id == user.id).first()
