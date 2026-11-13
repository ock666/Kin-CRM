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
        # Rebuild only when the unique constraint is still the original single-column `name`.
        needs_rebuild = False
        for r in conn.execute(text("PRAGMA index_list('tags')")).fetchall():
            if r[2] == 1:  # unique
                icols = [c[2] for c in conn.execute(text(f"PRAGMA index_info('{r[1]}')")).fetchall()]
                if icols == ["name"]:
                    needs_rebuild = True
        if not needs_rebuild:
            return  # already per-user or per-household
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
        # Only drop the old index if it's actually a *unique* index on slug (the original global
        # unique). On fresh installs `ix_unlocked_achievements_slug` is a harmless non-unique index.
        for r in idx_rows:
            if r[1] == "ix_unlocked_achievements_slug" and r[2] == 1:
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

    # v4.0: households — every user belongs to a household (a household of one = individual).
    _migrate_to_households()


def _migrate_to_households():
    insp = inspect(engine)
    tables = insp.get_table_names()
    if "users" not in tables or "households" not in tables:
        return
    with engine.begin() as conn:
        # One household per existing user (same id), so individual installs are unchanged.
        hh_count = conn.execute(text("SELECT COUNT(*) FROM households")).scalar()
        if hh_count == 0:
            conn.execute(text("INSERT INTO households (id, name) SELECT id, name FROM users"))
    _ensure_column("users", "household_id", "INTEGER")
    with engine.begin() as conn:
        conn.execute(text("UPDATE users SET household_id = id WHERE household_id IS NULL"))

    _ensure_column("people", "household_id", "INTEGER")
    _ensure_column("wrapped_cards", "household_id", "INTEGER")
    _ensure_column("unlocked_achievements", "household_id", "INTEGER")
    _ensure_column("user_stats", "household_id", "INTEGER")
    _ensure_column("journal_entries", "household_id", "INTEGER")

    with engine.begin() as conn:
        conn.execute(text("UPDATE people SET household_id = user_id WHERE household_id IS NULL"))
        conn.execute(text("UPDATE wrapped_cards SET household_id = user_id WHERE household_id IS NULL"))
        conn.execute(text("UPDATE unlocked_achievements SET household_id = user_id WHERE household_id IS NULL"))
        conn.execute(text("UPDATE user_stats SET household_id = user_id WHERE household_id IS NULL"))
        conn.execute(text("UPDATE journal_entries SET household_id = author_user_id WHERE household_id IS NULL"))

    _migrate_household_settings()
    _rebuild_tags_for_households()
    _replace_achievement_index_for_households()
    logger.info("Migration: households created and backfilled")


def _migrate_household_settings():
    """Move Immich/AI/Whisper creds from per-user (or global) settings into household_settings."""
    from .settings_store import HOUSEHOLD_DEFAULTS
    tables = inspect(engine).get_table_names()
    if "household_settings" not in tables:
        return
    with engine.begin() as conn:
        users = conn.execute(text("SELECT id, household_id FROM users WHERE household_id IS NOT NULL")).fetchall()
        for user_id, household_id in users:
            for key in sorted(HOUSEHOLD_DEFAULTS):
                value = conn.execute(
                    text("SELECT value FROM user_settings WHERE user_id = :u AND key = :k"),
                    {"u": user_id, "k": key},
                ).scalar()
                if value is None and "settings" in tables:
                    value = conn.execute(
                        text("SELECT value FROM settings WHERE key = :k"), {"k": key}
                    ).scalar()
                if value is None:
                    continue
                already = conn.execute(
                    text("SELECT 1 FROM household_settings WHERE household_id = :h AND key = :k"),
                    {"h": household_id, "k": key},
                ).scalar()
                if already is None:
                    conn.execute(
                        text("INSERT INTO household_settings (household_id, key, value) VALUES (:h, :k, :v)"),
                        {"h": household_id, "k": key, "v": value},
                    )


def _rebuild_tags_for_households():
    """Rebuild tags so name uniqueness is per household (was per user, before that global)."""
    insp = inspect(engine)
    if "tags" not in insp.get_table_names():
        return
    with engine.begin() as conn:
        cols = {c["name"] for c in insp.get_columns("tags")}
        already_ok = "household_id" in cols
        if already_ok:
            for r in conn.execute(text("PRAGMA index_list('tags')")).fetchall():
                if r[2] == 1:
                    icols = [c[2] for c in conn.execute(text(f"PRAGMA index_info('{r[1]}')")).fetchall()]
                    if icols == ["household_id", "name"]:
                        return  # already household-scoped
        conn.execute(text("""
            CREATE TABLE tags_new (
                id INTEGER NOT NULL PRIMARY KEY,
                household_id INTEGER,
                user_id INTEGER,
                name VARCHAR(100) NOT NULL,
                color VARCHAR(20),
                CONSTRAINT uq_tags_household_name UNIQUE (household_id, name)
            )
        """))
        conn.execute(text(
            "INSERT INTO tags_new (id, household_id, user_id, name, color) "
            "SELECT id, user_id, user_id, name, color FROM tags"
        ))
        conn.execute(text("DROP TABLE tags"))
        conn.execute(text("ALTER TABLE tags_new RENAME TO tags"))
        logger.info("Migration: rebuilt tags table for per-household name scoping")


def _replace_achievement_index_for_households():
    insp = inspect(engine)
    if "unlocked_achievements" not in insp.get_table_names():
        return
    with engine.begin() as conn:
        for r in conn.execute(text("PRAGMA index_list('unlocked_achievements')")).fetchall():
            if r[1] == "uq_achievements_user_slug":
                conn.execute(text("DROP INDEX uq_achievements_user_slug"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_achievements_household_slug "
            "ON unlocked_achievements (household_id, slug)"
        ))
