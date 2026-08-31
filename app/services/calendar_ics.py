"""Calendar sync - an ICS feed served by Kin that any external calendar can subscribe to.

Birthdays and notable dates become all-day VEVENTs (DATE values, so no timezone/DST drift).
Birthdays recur yearly (RRULE); notable dates recur only when flagged recurring. Reminders are
attached as VALARM DISPLAY triggers (best-effort: Apple/Outlook honor these; Google Calendar
applies its own notification settings to subscribed feeds). The feed is generated live from the
DB with stable UIDs, so re-subscribing / re-fetching never duplicates events.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from ..models import Person, NotableDate
from ..settings_store import get_setting


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _safe_date(year: int, month: int, day: int) -> dt.date | None:
    try:
        return dt.date(year, month, day)
    except ValueError:
        if month == 2 and day == 29:
            return dt.date(year, 3, 1)
        return None


def _vevent(uid: str, summary: str, start: dt.date, recurring: bool,
            reminder_days: int) -> list[str]:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}",
    ]
    if recurring:
        lines.append("RRULE:FREQ=YEARLY")
    lines.append(f"SUMMARY:{_escape(summary)}")
    if reminder_days and reminder_days > 0:
        lines += [
            "BEGIN:VALARM",
            f"TRIGGER:-P{reminder_days}D",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_escape(summary)}",
            "END:VALARM",
        ]
    lines.append("END:VEVENT")
    return lines


def build_ics(db: Session, birthday_reminder_days: int = 14,
              notable_reminder_days: int = 1,
              include_birthdays: bool = True,
              include_notable_dates: bool = True) -> str:
    today = dt.date.today()
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Kin//Personal Relationship Manager//EN",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:Kin",
    ]

    if include_birthdays:
        people = (
            db.query(Person)
            .filter(Person.archived.is_(False))
            .filter(Person.birthday_month.isnot(None), Person.birthday_day.isnot(None))
            .order_by(Person.name)
            .all()
        )
        for p in people:
            start = _safe_date(today.year, p.birthday_month, p.birthday_day)
            if start is None:
                continue
            lines += _vevent(
                uid=f"kin-birthday-{p.id}@kin",
                summary=f"{p.name}'s birthday",
                start=start,
                recurring=True,
                reminder_days=birthday_reminder_days,
            )

    if include_notable_dates:
        notable_dates = db.query(NotableDate).order_by(NotableDate.label).all()
        for nd in notable_dates:
            start = _safe_date(nd.year or today.year, nd.month, nd.day)
            if start is None:
                continue
            label = nd.label or "Notable date"
            if nd.person:
                label = f"{label} — {nd.person.name}"
            lines += _vevent(
                uid=f"kin-notable-{nd.id}@kin",
                summary=label,
                start=start,
                recurring=bool(nd.recurring),
                reminder_days=notable_reminder_days,
            )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
