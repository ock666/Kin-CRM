"""Lightweight startup migration helper.

We intentionally avoid Alembic to keep this a single simple container. On
startup we run `Base.metadata.create_all()` (creates any new tables) and then
this function patches in any columns that were added to models.py after a
user's database was first created, so upgrades don't require manual SQL or
wiping data. Add a new `_ensure_column(...)` call here whenever a column is
added to an existing table in models.py.
"""
import logging

from sqlalchemy import inspect, text

from .database import engine

logger = logging.getLogger(__name__)


def _ensure_column(table: str, column: str, ddl_type: str, default_sql: str | None = None):
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns(table)}
    if column in existing:
        return
    with engine.begin() as conn:
        stmt = f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"
        if default_sql is not None:
            stmt += f" DEFAULT {default_sql}"
        conn.execute(text(stmt))
        logger.info("Migration: added column %s.%s", table, column)


def _backfill_owner(table: str):
    """Assign every existing row of `table` to the first-created user (the instance's
    original admin), since prior versions were single-workspace and all data belonged to them."""
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return
    with engine.begin() as conn:
        n = conn.execute(
            text(f"UPDATE {table} SET user_id = (SELECT MIN(id) FROM users) WHERE user_id IS NULL")
        ).rowcount
        if n:
            logger.info("Migration: backfilled %d %s row(s) to the first user", n, table)


def _rebuild_tags_for_per_user_names():
    """The original `tags` table enforced a *global* unique name. Rebuild it so the same tag
    name can exist for different users (unique per (user_id, name))."""
    insp = inspect(engine)
    if "tags" not in insp.get_table_names():
        return
    with engine.begin() as conn:
        idx_rows = conn.execute(text("PRAGMA index_list('tags')")).fetchall()
        if not any(r[1] == "sqlite_autoindex_tags_1" for r in idx_rows):
            return  # already rebuilt
        conn.execute(text("""
            CREATE TABLE tags_new (
                id INTEGER NOT NULL PRIMARY KEY,
                user_id INTEGER,
                name VARCHAR(100) NOT NULL,
                color VARCHAR(20),
                CONSTRAINT uq_tags_user_name UNIQUE (user_id, name)
            )
        """))
        conn.execute(text("""
            INSERT INTO tags_new (id, user_id, name, color)
            SELECT id, (SELECT MIN(id) FROM users), name, color FROM tags
        """))
        conn.execute(text("DROP TABLE tags"))
        conn.execute(text("ALTER TABLE tags_new RENAME TO tags"))
        logger.info("Migration: rebuilt tags table for per-user name scoping")


def _replace_achievement_unique_index():
    """The original `unlocked_achievements.slug` was globally unique. Swap it for a
    per-user composite unique index so two users can each unlock the same achievement."""
    insp = inspect(engine)
    if "unlocked_achievements" not in insp.get_table_names():
        return
    with engine.begin() as conn:
        idx_rows = conn.execute(text("PRAGMA index_list('unlocked_achievements')")).fetchall()
        if any(r[1] == "ix_unlocked_achievements_slug" for r in idx_rows):
            conn.execute(text("DROP INDEX ix_unlocked_achievements_slug"))
            logger.info("Migration: dropped global unique index on unlocked_achievements.slug")
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_achievements_user_slug "
            "ON unlocked_achievements (user_id, slug)"
        ))


def _migrate_per_user_settings():
    """Copy any per-user preference keys that still live in the old global `settings` table into
    the new `user_settings` table for the first (original) user, so existing installs keep their
    birthday lead days, grace state, notification toggles, etc."""
    insp = inspect(engine)
    if "settings" not in insp.get_table_names() or "user_settings" not in insp.get_table_names():
        return
    from .settings_store import PER_USER_KEYS
    with engine.begin() as conn:
        first_user = conn.execute(text("SELECT MIN(id) FROM users")).scalar()
        if first_user is None:
            return
        for key in sorted(PER_USER_KEYS):
            value = conn.execute(
                text("SELECT value FROM settings WHERE key = :k"), {"k": key}
            ).scalar()
            if value is None:
                continue
            already = conn.execute(
                text("SELECT 1 FROM user_settings WHERE user_id = :u AND key = :k"),
                {"u": first_user, "k": key},
            ).scalar()
            if already is None:
                conn.execute(
                    text("INSERT INTO user_settings (user_id, key, value) VALUES (:u, :k, :v)"),
                    {"u": first_user, "k": key, "v": value},
                )
    logger.info("Migration: migrated per-user settings to the first user")


def run_startup_migrations():
    # v1.2: occupation/hobbies added to an existing `people` table - new tables (scratchpad_items,
    # notable_person_refs, gift_ideas) don't need migration since create_all() creates any missing
    # table automatically; only new *columns* on already-existing tables need this treatment.
    _ensure_column("people", "occupation", "VARCHAR(255)")
    _ensure_column("people", "hobbies", "TEXT")
    # v1.5: bio blurb (short AI/manual one-liner) and cached conversation-gap questions (JSON).
    _ensure_column("people", "bio", "TEXT")
    _ensure_column("people", "ai_starters_json", "TEXT")

    # v1.3: conflict_logs columns reworked from "wait 48h + AI-detect implicit repair" to
    # "immediate, conflict-specific AI approach suggestions" - anyone who ran the earlier version
    # of this feature needs these two new columns added to their existing table.
    _ensure_column("conflict_logs", "ai_approach_json", "TEXT")
    _ensure_column("conflict_logs", "reminder_dismissed", "BOOLEAN", default_sql="0")

    # v2.0: relationship state column on people (system-suggests, user-confirms,
    # affects check-in nudges and push notifications).
    _ensure_column("people", "relationship_state", "VARCHAR(20)", default_sql="'none'")
    _ensure_column("conflict_logs", "resolution_plan_json", "TEXT")
    _ensure_column("conflict_logs", "plan_generated_at", "DATETIME")

    # MFA (TOTP two-factor auth)
    _ensure_column("users", "totp_secret", "VARCHAR(255)")
    _ensure_column("users", "totp_enabled", "BOOLEAN", default_sql="0")
    _ensure_column("users", "mfa_recovery_codes", "TEXT")

    # v2.x: quiet a person's gentle reminders ("revisit when ready") without archiving them
    _ensure_column("people", "reminders_dismissed", "BOOLEAN", default_sql="0")

    # v2.1: voice chat support (store audio URL + transcript on conflict chat messages)
    _ensure_column("conflict_chat_messages", "audio_url", "TEXT")
    _ensure_column("conflict_chat_messages", "transcript", "TEXT")

    # v2.2: birthday reminders expanded from 3 days to 2 weeks (more grace time to plan a gift).
    # The default changed in settings_store; bump any existing installs still on the old default.
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE settings SET value='14' WHERE key='birthday_lead_days' AND value='3'"
        ))

    # v3.0: per-user isolation. Add an owner column to every root entity, backfill all existing
    # rows to the original admin, and relax the two global-unique constraints so the same tag name
    # / achievement slug can now exist once *per user*.
    _ensure_column("people", "user_id", "INTEGER")
    _ensure_column("wrapped_cards", "user_id", "INTEGER")
    _ensure_column("unlocked_achievements", "user_id", "INTEGER")
    _ensure_column("user_stats", "user_id", "INTEGER")
    _backfill_owner("people")
    _backfill_owner("wrapped_cards")
    _backfill_owner("unlocked_achievements")
    _backfill_owner("user_stats")
    _rebuild_tags_for_per_user_names()
    _replace_achievement_unique_index()
    _migrate_per_user_settings()
