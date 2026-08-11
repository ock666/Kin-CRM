"""Resolution plan generation from idle conflict support chats.

When a support chat for an unresolved conflict has been inactive for a configured
number of minutes (default 15), generate a structured resolution plan via AI and
cache it on the conflict for display on the person's profile card.
"""
from __future__ import annotations

import datetime as dt
import json
import logging

from sqlalchemy.orm import Session

from ..models import ConflictLog, ConflictChatMessage, ConflictStatus

logger = logging.getLogger(__name__)


def _idle_minutes(db: Session) -> int:
    from ..settings_store import get_setting
    try:
        return int(get_setting(db, "conflict_plan_idle_minutes", "15") or 15)
    except ValueError:
        return 15


def find_plannable_conflicts(db: Session, today: dt.datetime | None = None) -> list[ConflictLog]:
    """Conflicts with: unresolved, has chat messages, no plan yet, last chat message
    older than the idle threshold."""
    now = today if today else dt.datetime.utcnow()
    idle = _idle_minutes(db)
    cutoff = now - dt.timedelta(minutes=idle)

    conflicts = (
        db.query(ConflictLog)
        .filter(ConflictLog.status == ConflictStatus.unresolved)
        .filter(ConflictLog.resolution_plan_json.is_(None))
        .all()
    )

    result = []
    for c in conflicts:
        if not c.chat_messages:
            continue
        last_msg = c.chat_messages[-1]
        if last_msg.created_at and last_msg.created_at <= cutoff:
            result.append(c)
    return result


def generate_plans_for_idle(db: Session) -> int:
    """Run by scheduler: find idle conflicts and generate plans. Returns count."""
    from .ai_client import get_support_client_from_settings, AIError

    ai = None
    try:
        ai = get_support_client_from_settings(db)
    except AIError:
        ai = None
    if not ai:
        return 0

    conflicts = find_plannable_conflicts(db)
    count = 0
    for c in conflicts:
        try:
            _generate_plan_for_conflict(db, ai, c)
            count += 1
        except AIError:
            logger.info("Plan generation failed for conflict %s", c.id)
        except Exception:
            logger.exception("Unexpected error generating plan for conflict %s", c.id)

    if count:
        db.commit()
        logger.info("Generated %d resolution plan(s)", count)
    return count


def generate_plan_for_conflict(db: Session, conflict_id: int) -> bool:
    """Generate a plan for a single conflict (called from conflict card load)."""
    from .ai_client import get_support_client_from_settings, AIError
    from ..models import ConflictLog

    conflict = db.get(ConflictLog, conflict_id)
    if not conflict or conflict.resolution_plan_json:
        return False

    # Check idle threshold
    idle = _idle_minutes(db)
    cutoff = dt.datetime.utcnow() - dt.timedelta(minutes=idle)
    if conflict.chat_messages:
        last = conflict.chat_messages[-1]
        if last.created_at and last.created_at > cutoff:
            return False  # Not idle yet

    ai = None
    try:
        ai = get_support_client_from_settings(db)
    except AIError:
        return False
    if not ai:
        return False

    try:
        _generate_plan_for_conflict(db, ai, conflict)
        db.commit()
        return True
    except AIError:
        return False


def _generate_plan_for_conflict(db: Session, ai, conflict: ConflictLog):
    person_name = conflict.person.name if conflict.person else "someone"
    from .conflict_resolution import build_relationship_context
    context = build_relationship_context(conflict.person) if conflict.person else ""

    transcript = "\n".join(
        f"{m.role}: {m.content}" for m in conflict.chat_messages
    )

    plan = ai.suggest_resolution_plan(
        conflict.summary, transcript, person_name, context,
    )
    data = plan.dict()
    conflict.resolution_plan_json = json.dumps(data)
    conflict.plan_generated_at = dt.datetime.utcnow()
