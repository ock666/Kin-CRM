"""AI-assisted conflict approach suggestions (v1.3.1).

Design note: the original version of this feature made the AI passively watch for a NEW journal
entry with the person (after a 48-hour "cooling off" buffer) to detect whether a conflict seemed
to have naturally healed. Real-world feedback: Rejection Sensitive Dysphoria (RSD) commonly drives
*avoidance* of the person involved, so gating any help behind "wait for a future interaction to
go well" was actively unhelpful - it required the very contact the user may be anxious about
before offering any support at all.

This version instead generates conflict-SPECIFIC approach suggestions immediately from the
conflict description itself - no waiting period, no requirement to interact with the person
first. The user can act on them right away or come back to them whenever they feel ready; this
only provides structure, safety, and a jumping-off point, never a verdict or an auto-action.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from ..models import ConflictLog
from .ai_client import AIError, build_person_context

logger = logging.getLogger(__name__)


def build_relationship_context(person) -> str:
    """Assemble a compact, warm free-text block describing the user's relationship with this
    person, so the AI can tailor conflict scripts to THIS relationship rather than generically.
    Combines profile context (via build_person_context) with the person's closeness/rank and a
    brief note about other unresolved conflicts on record - the latter matters a lot for RSD,
    since a pattern of friction vs. a one-off are very different to navigate.
    Tolerates being handed a plain string (no usable object), returning an empty string then.
    Duck-typed on `person`, so it also works in tests with minimal stub people."""
    parts = []

    ctx = build_person_context(person)
    if ctx:
        parts.append(ctx)

    try:
        from .friend_rank import compute_friend_rank
        rank = compute_friend_rank(person)
        parts.append(f"Closeness (from logged history): {rank.get('tier', '')} {rank.get('emoji', '')}")
    except Exception:
        pass

    unresolved = [c for c in (getattr(person, "conflict_logs", None) or [])
                  if c.status.name == "unresolved"]
    if unresolved:
        parts.append(f"{len(unresolved)} other unresolved conflict(s) are also logged with this "
                     f"person - consider whether a pattern is building, not just this one.")

    return "\n".join(parts)


def generate_approach_suggestions(db: Session, ai, conflict: ConflictLog, person) -> dict | None:
    """Ask AI for conflict-specific approach/boundary and navigation scripts (tailored to the
    relationship and this specific conflict via relational context) and cache them on the conflict
    (so viewing the card again doesn't re-call the API). Returns the suggestions dict, or None if
    AI isn't configured or the call fails - callers/templates fall back to generic scripts in
    that case, so this never blocks the core feature.
    `person` may be a Person object (richer relational context) or a plain name string."""
    if ai is None:
        return None
    person_name = getattr(person, "name", None) or str(person)
    relation_ctx = "" if isinstance(person, str) else build_relationship_context(person)
    try:
        suggestions = ai.suggest_conflict_approach(person_name, conflict.summary,
                                                   relationship_context=relation_ctx)
    except AIError as e:
        logger.info("Conflict approach suggestion failed for conflict %s: %s", conflict.id, e)
        return None

    data = suggestions.__dict__ if hasattr(suggestions, "__dict__") else dict(suggestions)
    conflict.ai_approach_json = json.dumps(data)
    db.add(conflict)
    db.commit()
    return data


def get_cached_suggestions(conflict: ConflictLog) -> dict | None:
    if not conflict.ai_approach_json:
        return None
    try:
        return json.loads(conflict.ai_approach_json)
    except (TypeError, ValueError):
        return None
