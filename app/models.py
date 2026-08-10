import enum
from datetime import datetime, date, timezone

from sqlalchemy import (
    Column, Integer, String, Text, Date, DateTime, Boolean, ForeignKey,
    Table, Enum, UniqueConstraint
)
from sqlalchemy.orm import relationship

from .database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False, default="")
    hashed_password = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)

    journal_entries = relationship("JournalEntry", back_populates="author")


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

person_tags = Table(
    "person_tags",
    Base.metadata,
    Column("person_id", Integer, ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    color = Column(String(20), default="#6366f1")

    people = relationship("Person", secondary=person_tags, back_populates="tags")


# ---------------------------------------------------------------------------
# Journal <-> Person association (cross-tagging: one entry, many people)
# ---------------------------------------------------------------------------

journal_entry_people = Table(
    "journal_entry_people",
    Base.metadata,
    Column("journal_entry_id", Integer, ForeignKey("journal_entries.id", ondelete="CASCADE"), primary_key=True),
    Column("person_id", Integer, ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
)


class EnergyCost(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class EventType(str, enum.Enum):
    note = "note"
    hangout = "hangout"
    call = "call"
    message = "message"
    gift = "gift"
    milestone = "milestone"
    conflict = "conflict"
    instagram = "instagram"
    other = "other"


class Person(Base):
    __tablename__ = "people"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    nickname = Column(String(255), nullable=True)
    pronouns = Column(String(50), nullable=True)
    relationship_label = Column(String(100), nullable=True)  # e.g. "close friend", "sibling"

    birthday_month = Column(Integer, nullable=True)
    birthday_day = Column(Integer, nullable=True)
    birthday_year = Column(Integer, nullable=True)  # optional, may be unknown

    how_we_met = Column(Text, nullable=True)
    met_date = Column(Date, nullable=True)
    location = Column(String(255), nullable=True)  # where they live / are based
    phone = Column(String(100), nullable=True)
    email = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)  # free-form persistent notes / AI summary lives here too
    ai_summary = Column(Text, nullable=True)

    occupation = Column(String(255), nullable=True)
    hobbies = Column(Text, nullable=True)  # comma-separated free text, e.g. "climbing, baking"

    avatar_url = Column(String(500), nullable=True)  # local upload path or immich proxy url

    # Immich linkage
    immich_person_id = Column(String(100), nullable=True, index=True)

    # Instagram linkage
    instagram_username = Column(String(255), nullable=True)
    instagram_enabled = Column(Boolean, default=False)
    instagram_last_checked = Column(DateTime, nullable=True)
    instagram_last_error = Column(Text, nullable=True)

    # Check-in cadence (AuDHD-friendly nudges)
    checkin_cadence_days = Column(Integer, nullable=True)  # None = no reminder
    checkin_snoozed_until = Column(Date, nullable=True)
    last_contact_date = Column(Date, nullable=True)

    archived = Column(Boolean, default=False)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    tags = relationship("Tag", secondary=person_tags, back_populates="people")
    notable_dates = relationship("NotableDate", back_populates="person", cascade="all, delete-orphan")
    instagram_posts = relationship("InstagramPost", back_populates="person", cascade="all, delete-orphan")
    birthday_drafts = relationship("BirthdayMessageDraft", back_populates="person", cascade="all, delete-orphan")
    scratchpad_items = relationship(
        "ScratchpadItem", back_populates="person", cascade="all, delete-orphan",
        order_by="ScratchpadItem.created_at"
    )
    notable_people_refs = relationship(
        "NotablePersonRef", back_populates="person", cascade="all, delete-orphan"
    )
    gift_ideas = relationship(
        "GiftIdea", back_populates="person", cascade="all, delete-orphan",
        order_by="GiftIdea.created_at.desc()"
    )
    conflict_logs = relationship(
        "ConflictLog", back_populates="person", cascade="all, delete-orphan",
        order_by="ConflictLog.created_at.desc()"
    )

    journal_entries = relationship(
        "JournalEntry", secondary=journal_entry_people, back_populates="people",
        order_by="JournalEntry.entry_date.desc()"
    )


class ScratchpadItem(Base):
    """Fleeting 'bring up next time' reminders - e.g. "ask how her vet visit went".
    Implemented as its own table (rather than a JSON column on Person) so items can be
    added/removed individually without juggling array indices."""
    __tablename__ = "scratchpad_items"

    id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey("people.id", ondelete="CASCADE"), nullable=False)
    text = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=utcnow)

    person = relationship("Person", back_populates="scratchpad_items")


class NotablePersonRef(Base):
    """A lightweight reference to someone in a person's life who doesn't need (or have) their
    own full CRM profile or Immich link - e.g. {"name": "Sarah", "relation": "Mum"}."""
    __tablename__ = "notable_person_refs"

    id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey("people.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    relation = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    person = relationship("Person", back_populates="notable_people_refs")


class GiftStatus(str, enum.Enum):
    suggested = "suggested"
    given = "given"
    dismissed = "dismissed"


class GiftIdea(Base):
    """AI-suggested (or manually noted) gift ideas for a person, tracked over time so future
    suggestions can avoid repeating something already given."""
    __tablename__ = "gift_ideas"

    id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey("people.id", ondelete="CASCADE"), nullable=False)
    year = Column(Integer, nullable=True)
    description = Column(Text, nullable=False)
    status = Column(Enum(GiftStatus), default=GiftStatus.suggested)
    created_at = Column(DateTime, default=utcnow)

    person = relationship("Person", back_populates="gift_ideas")


class NotableDate(Base):
    __tablename__ = "notable_dates"

    id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey("people.id", ondelete="CASCADE"), nullable=False)
    label = Column(String(255), nullable=False)  # e.g. "Anniversary", "Kid's birthday: Milo"
    month = Column(Integer, nullable=False)
    day = Column(Integer, nullable=False)
    year = Column(Integer, nullable=True)
    recurring = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)

    person = relationship("Person", back_populates="notable_dates")


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id = Column(Integer, primary_key=True)
    author_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    title = Column(String(255), nullable=True)
    body = Column(Text, nullable=False)
    entry_date = Column(Date, default=date.today, nullable=False)
    event_type = Column(Enum(EventType), default=EventType.note)
    location = Column(String(255), nullable=True)
    energy_cost = Column(Enum(EnergyCost), nullable=True)

    ai_processed = Column(Boolean, default=False)
    ai_suggestions_json = Column(Text, nullable=True)  # pending AI-extracted fact suggestions

    source = Column(String(50), default="manual")  # manual | instagram | ai

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    author = relationship("User", back_populates="journal_entries")
    people = relationship("Person", secondary=journal_entry_people, back_populates="journal_entries")
    images = relationship("JournalImage", back_populates="entry", cascade="all, delete-orphan")


class JournalImage(Base):
    __tablename__ = "journal_images"

    id = Column(Integer, primary_key=True)
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False)
    immich_asset_id = Column(String(100), nullable=True)
    upload_path = Column(String(500), nullable=True)  # for directly-uploaded (non-Immich) images
    caption = Column(String(500), nullable=True)

    entry = relationship("JournalEntry", back_populates="images")


class ReviewStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    dismissed = "dismissed"
    sent = "sent"
    skipped = "skipped"


class InstagramPost(Base):
    __tablename__ = "instagram_posts"

    id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey("people.id", ondelete="CASCADE"), nullable=False)
    ig_post_id = Column(String(100), nullable=False, index=True)
    caption = Column(Text, nullable=True)
    media_url = Column(String(1000), nullable=True)
    permalink = Column(String(500), nullable=True)
    post_type = Column(String(50), nullable=True)
    posted_at = Column(DateTime, nullable=True)
    fetched_at = Column(DateTime, default=utcnow)
    status = Column(Enum(ReviewStatus), default=ReviewStatus.pending)
    imported_as_journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)

    person = relationship("Person", back_populates="instagram_posts")

    __table_args__ = (UniqueConstraint("person_id", "ig_post_id", name="uq_person_ig_post"),)


class BirthdayMessageDraft(Base):
    __tablename__ = "birthday_message_drafts"

    id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey("people.id", ondelete="CASCADE"), nullable=False)
    year = Column(Integer, nullable=False)
    draft_text = Column(Text, nullable=False)
    status = Column(Enum(ReviewStatus), default=ReviewStatus.pending)
    generated_at = Column(DateTime, default=utcnow)
    sent_at = Column(DateTime, nullable=True)

    person = relationship("Person", back_populates="birthday_drafts")

    __table_args__ = (UniqueConstraint("person_id", "year", name="uq_person_year_bday"),)


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Gamification (v1.2) - a shared/household-wide progression state (singleton row,
# id fixed at 1) rather than per-login-user, matching this app's shared-workspace model.
# All logic lives in app/services/gamification.py - pure Python, zero AI calls at runtime.
# ---------------------------------------------------------------------------

class UserStats(Base):
    __tablename__ = "user_stats"

    id = Column(Integer, primary_key=True, default=1)
    total_xp = Column(Integer, default=0, nullable=False)
    current_level = Column(Integer, default=1, nullable=False)
    streak_days = Column(Integer, default=0, nullable=False)
    last_active_date = Column(String(10), nullable=True)  # "YYYY-MM-DD"


class UnlockedAchievement(Base):
    __tablename__ = "unlocked_achievements"

    id = Column(Integer, primary_key=True)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    unlocked_at = Column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# Conflict resolution / RSD-aware repair tracking (v1.3) - low-demand, never-nagging by design.
# AI only ever *suggests* a resolution (with a confidence gate) - status changes always require
# an explicit human click. See app/services/conflict_ai.py for the analysis logic.
# ---------------------------------------------------------------------------

class ConflictStatus(str, enum.Enum):
    unresolved = "UNRESOLVED"
    resolved = "RESOLVED"
    released = "RELEASED"  # "let it go" - a first-class, equally valid resolution path


class ConflictLog(Base):
    __tablename__ = "conflict_logs"

    id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey("people.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=utcnow)
    summary = Column(Text, nullable=False)
    status = Column(Enum(ConflictStatus), default=ConflictStatus.unresolved, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)
    # AI-generated, conflict-specific approach suggestions (reflection + tailored scripts),
    # cached as JSON so they're generated once and reused rather than re-calling the AI every
    # time the card is viewed. Available immediately - no waiting period, no requirement to
    # interact with the person first (see app/services/conflict_resolution.py).
    ai_approach_json = Column(Text, nullable=True)
    # Lets the user quietly dismiss the gentle dashboard reminder for this conflict without
    # resolving/releasing it - it still shows on the person's own profile either way.
    reminder_dismissed = Column(Boolean, default=False)

    person = relationship("Person", back_populates="conflict_logs")


# ---------------------------------------------------------------------------
# Web Push subscriptions (PWA). One row per browser/device the user has enabled
# notifications on. On every daily job, due birthday/overdue-cadence notifications
# are pushed to these endpoints. Subscriptions are opt-in and removable at any time.
# ---------------------------------------------------------------------------

class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True)
    endpoint = Column(Text, unique=True, nullable=False)
    p256dh = Column(Text, nullable=False)
    auth = Column(Text, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
