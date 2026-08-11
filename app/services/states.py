"""Relationship state — system-suggests, user-confirms, nudge-affecting.

Design (v2.0): a dedicated RelationshipState column on Person (none/wants_space/drifted),
with 'in_conflict' derived automatically from unresolved ConflictLogs (the user already
logged the conflict — no extra click needed). The system suggests 'drifted' when someone
is overdue *and* last contact was 90+ days ago; the user confirms or dismisses.
'wants_space' is a direct user choice with no date bound — persists until cleared.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from ..models import ConflictLog, ConflictStatus, Person, RelationshipState

DRIFT_THRESHOLD_DAYS = 90


def effective_state(person: Person, today: dt.date | None = None) -> RelationshipState:
    """Return the effective relationship state for a person, combining auto-derived
    in_conflict (from unresolved ConflictLogs) with stored wants_space / drifted."""
    today = today or dt.date.today()

    conflicts = getattr(person, "conflict_logs", []) or []
    if any(c.status == ConflictStatus.unresolved for c in conflicts):
        return RelationshipState.in_conflict

    return person.relationship_state or RelationshipState.none


def suggest_states(db: Session, today: dt.date | None = None) -> list[tuple[Person, RelationshipState, str]]:
    """Find people with a suggestible state and return (person, suggested_state, reason).
    Currently suggests drifted for people with state 'none', no unresolved conflict,
    a cadence set, they're overdue, and last contact was 90+ days ago."""
    today = today or dt.date.today()
    suggestions: list[tuple[Person, RelationshipState, str]] = []

    people = (
        db.query(Person)
        .filter(Person.archived.is_(False))
        .filter(Person.relationship_state == RelationshipState.none)
        .filter(Person.checkin_cadence_days.isnot(None))
        .all()
    )

    conflict_ids = {
        c.person_id for c in
        db.query(ConflictLog.person_id)
        .filter(ConflictLog.status == ConflictStatus.unresolved)
        .all()
    }

    for p in people:
        if p.id in conflict_ids:
            continue
        baseline = p.last_contact_date or (p.created_at.date() if p.created_at else today)
        days_since = (today - baseline).days
        if days_since >= DRIFT_THRESHOLD_DAYS and p.checkin_snoozed_until is None and p.checkin_snoozed_until is None:
            suggestions.append((p, RelationshipState.drifted,
                                f"Last contact was {days_since} days ago (cadence: every {p.checkin_cadence_days}d)"))
    return suggestions
