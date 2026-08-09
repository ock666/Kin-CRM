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


def run_startup_migrations():
    # v1.2: occupation/hobbies added to an existing `people` table - new tables (scratchpad_items,
    # notable_person_refs, gift_ideas) don't need migration since create_all() creates any missing
    # table automatically; only new *columns* on already-existing tables need this treatment.
    _ensure_column("people", "occupation", "VARCHAR(255)")
    _ensure_column("people", "hobbies", "TEXT")
