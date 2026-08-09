"""Implicit conflict-repair detection (v1.3).

Low-demand, AuDHD-safe by design: this NEVER changes a conflict's status automatically. It only
ever sets `ai_suggested_resolution` + `ai_suggested_prompt` as a dismissible suggestion - a human
always has to click "Yes, Mark Resolved" (or "Still Working on It" to dismiss without nagging
again) for anything to actually change. See models.ConflictLog for the schema and
app/services/ai_client.py's `analyze_conflict_resolution` for the actual LLM call.
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy.orm import Session

from ..models import ConflictLog, ConflictStatus, JournalEntry
from .ai_client import AIError

logger = logging.getLogger(__name__)

BUFFER_HOURS = 48  # nervous-system buffer - never surface a resolution banner before this
CONFIDENCE_THRESHOLD = 0.75  # safety gate - see PART 3 of the spec this implements


def check_for_implicit_resolution(db: Session, ai, entry: JournalEntry) -> None:
    """Called after a new journal entry is saved. For each person tagged in the entry, look for
    an open (UNRESOLVED) conflict logged more than 48 hours ago that hasn't already been flagged,
    and ask the AI whether this new entry reads like a repair. Only ever *suggests* - never
    changes status itself. Safe to call with ai=None (a no-op, matches every other AI feature in
    this app degrading gracefully when AI isn't configured)."""
    if ai is None or not entry.people:
        return

    cutoff = dt.datetime.utcnow() - dt.timedelta(hours=BUFFER_HOURS)

    for person in entry.people:
        open_conflicts = (
            db.query(ConflictLog)
            .filter(ConflictLog.person_id == person.id)
            .filter(ConflictLog.status == ConflictStatus.unresolved)
            .filter(ConflictLog.ai_suggested_resolution.is_(False))
            .filter(ConflictLog.created_at <= cutoff)
            .all()
        )
        for conflict in open_conflicts:
            try:
                analysis = ai.analyze_conflict_resolution(person.name, conflict.summary, entry.body)
            except AIError as e:
                logger.info("Conflict resolution analysis failed for person %s: %s", person.id, e)
                continue

            if analysis.is_resolved and analysis.confidence_score >= CONFIDENCE_THRESHOLD:
                conflict.ai_suggested_resolution = True
                conflict.ai_suggested_prompt = analysis.suggested_ui_prompt or (
                    f"Your recent log with {person.nickname or person.name} felt warm and "
                    "relaxed. Did that resolve the earlier tension?"
                )
                db.add(conflict)

    db.commit()
