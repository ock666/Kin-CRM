"""Import people (and nested data) into Kin from a JSON export or a compatible CSV.

Design: careful and non-destructive. Every entity is created, never overwrites unrelated data.
People are matched by name (get-or-create); tags are matched by name; journal entries reference
people by name (resolved after people are created). Import does NOT fire gamification hooks so
it can't inflate XP/achievements. A single malformed row is skipped with a note rather than
aborting the whole import - the user always gets a calm summary of what was created vs skipped.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import (
    Person, Tag, NotableDate, NotablePersonRef, ScratchpadItem,
    GiftIdea, GiftStatus, ConflictLog, ConflictStatus, JournalEntry, EventType, EnergyCost,
)
from ..render import render

router = APIRouter()


@router.get("/import")
def import_page(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    return render(request, "import.html", db=db, user=user, active="import")


def _get_or_create_tag(db: Session, name: str) -> Tag:
    tag = db.query(Tag).filter(Tag.name == name).first()
    if not tag:
        tag = Tag(name=name)
        db.add(tag)
        db.flush()
    return tag


def _upsert_person(db: Session, name: str, fields: dict) -> Person:
    person = db.query(Person).filter(Person.name == name).first()
    if person is None:
        person = Person(name=name)
        db.add(person)
    for k, v in fields.items():
        if v is None:
            continue
        if k in ("birthday_month", "birthday_day", "birthday_year", "checkin_cadence_days"):
            setattr(person, k, int(v))
        elif k == "met_date":
            try:
                setattr(person, k, dt.date.fromisoformat(v))
            except (ValueError, TypeError):
                pass
        elif k == "last_contact_date":
            try:
                setattr(person, k, dt.date.fromisoformat(v))
            except (ValueError, TypeError):
                pass
        else:
            setattr(person, k, v)
    db.flush()
    return person


def _import_json(db: Session, data: dict, summary: dict):
    people = data.get("exported_people", data if isinstance(data, list) else [])
    for raw in people:
        if not isinstance(raw, dict) or not raw.get("name"):
            continue
        try:
            name = raw["name"].strip()
            fields = {
                "nickname": raw.get("nickname"),
                "pronouns": raw.get("pronouns"),
                "relationship_label": raw.get("relationship_label"),
                "birthday_month": raw.get("birthday"),
                "how_we_met": raw.get("how_we_met"),
                "met_date": raw.get("met_date"),
                "location": raw.get("location"),
                "phone": raw.get("phone"),
                "email": raw.get("email"),
                "notes": raw.get("notes"),
                "occupation": raw.get("occupation"),
                "hobbies": raw.get("hobbies"),
                "bio": raw.get("bio"),
                "ai_summary": raw.get("ai_summary"),
                "ai_starters_json": raw.get("ai_starters_json"),
                "relationship_state": raw.get("relationship_state", "none"),
                "archived": raw.get("archived"),
                "checkin_cadence_days": raw.get("checkin_cadence_days"),
                "last_contact_date": raw.get("last_contact_date"),
            }
            # Normalize birthday "M/D/Y" into month/day/year.
            bday = raw.get("birthday")
            if bday and isinstance(bday, str):
                parts = [int(x) if x else None for x in bday.split("/")]
                fields["birthday_month"] = len(parts) > 0 and parts[0]
                fields["birthday_day"] = len(parts) > 1 and parts[1]
                fields["birthday_year"] = len(parts) > 2 and parts[2]
            person = _upsert_person(db, name, fields)

            # Tags
            for tname in raw.get("tags", []) or []:
                tname = tname.strip()
                if not tname:
                    continue
                tag = _get_or_create_tag(db, tname)
                if tag not in person.tags:
                    person.tags.append(tag)

            # Notable dates
            for nd in raw.get("notable_dates", []) or []:
                if nd.get("month") and nd.get("day"):
                    db.add(NotableDate(
                        person_id=person.id, label=nd.get("label") or "Notable date",
                        month=int(nd["month"]), day=int(nd["day"]),
                        year=int(nd["year"]) if nd.get("year") else None,
                        recurring=nd.get("recurring", True), notes=nd.get("notes"),
                    ))

            # Notable people
            for np in raw.get("notable_people", []) or []:
                if np.get("name"):
                    db.add(NotablePersonRef(person_id=person.id, name=np["name"].strip(),
                                            relation=np.get("relation")))

            # Scratchpad
            for s in raw.get("scratchpad_items", []) or []:
                if s:
                    db.add(ScratchpadItem(person_id=person.id, text=s))

            # Gift ideas
            for g in raw.get("gift_ideas", []) or []:
                if g.get("description"):
                    db.add(GiftIdea(person_id=person.id, year=int(g["year"]) if g.get("year") else None,
                                    description=g["description"],
                                    status=GiftStatus(g.get("status", "suggested"))))

            # Conflicts
            for c in raw.get("conflicts", []) or []:
                if c.get("summary"):
                    status = c.get("status", "unresolved")
                    try:
                        cs = ConflictStatus(status.lower())
                    except ValueError:
                        cs = ConflictStatus.unresolved
                    db.add(ConflictLog(
                        person_id=person.id, summary=c["summary"], status=cs,
                        resolution_notes=c.get("resolution_notes"),
                        reminder_dismissed=c.get("reminder_dismissed", False),
                        ai_approach_json=c.get("ai_approach_json"),
                    ))

            # Journal entries (deferred so names resolve after all people exist)
            for e in raw.get("journal_entries", []) or []:
                if e.get("body"):
                    try:
                        et = EventType(e.get("event_type", "note"))
                    except ValueError:
                        et = EventType.note
                    ec = None
                    if e.get("energy_cost"):
                        try:
                            ec = EnergyCost(e.get("energy_cost"))
                        except ValueError:
                            ec = None
                    entry = JournalEntry(
                        title=e.get("title"), body=e["body"],
                        entry_date=dt.date.fromisoformat(e["date"]) if e.get("date") else dt.date.today(),
                        event_type=et, energy_cost=ec, location=e.get("location"),
                        source=e.get("source") or "import",
                    )
                    db.add(entry)
                    db.flush()
                    # Resolve "with" names to Person objects (M2M journal_entry_people).
                    for wname in e.get("with", []) or []:
                        wp = db.query(Person).filter(Person.name == wname.strip()).first()
                        if wp:
                            entry.people.append(wp)

            summary["created_people"] += 1
        except Exception:  # skip a bad row, don't abort the import
            summary["skipped"] += 1

    db.commit()


def _parse_csv_text(text: str) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(text)))
    return rows


def _import_csv(db: Session, text: str, summary: dict):
    rows = _parse_csv_text(text)
    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            summary["skipped"] += 1
            continue
        try:
            fields = {
                "nickname": (row.get("nickname") or "").strip() or None,
                "relationship_label": (row.get("relationship_label") or "").strip() or None,
                "birthday_month": (row.get("birthday_month") or "").strip() or None,
                "birthday_day": (row.get("birthday_day") or "").strip() or None,
                "birthday_year": (row.get("birthday_year") or "").strip() or None,
                "how_we_met": (row.get("how_we_met") or "").strip() or None,
                "met_date": (row.get("met_date") or "").strip() or None,
                "location": (row.get("location") or "").strip() or None,
                "phone": (row.get("phone") or "").strip() or None,
                "email": (row.get("email") or "").strip() or None,
                "occupation": (row.get("occupation") or "").strip() or None,
                "hobbies": (row.get("hobbies") or "").strip() or None,
                "notes": (row.get("notes") or "").strip() or None,
            }
            person = _upsert_person(db, name, fields)
            tag_str = (row.get("tags") or "").strip()
            for tname in [t.strip() for t in tag_str.split(",") if t.strip()]:
                tag = _get_or_create_tag(db, tname)
                if tag not in person.tags:
                    person.tags.append(tag)
            summary["created_people"] += 1
        except Exception:
            summary["skipped"] += 1
    db.commit()


@router.post("/import")
async def do_import(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                    file: UploadFile = File(..., max_size=50 * 1024 * 1024)):
    if not user:
        return RedirectResponse("/login")
    raw = (await file.read()).decode("utf-8", errors="replace")
    filename = file.filename or ""
    summary = {"created_people": 0, "skipped": 0}
    try:
        if filename.lower().endswith(".csv") or raw.lstrip().startswith("name,"):
            _import_csv(db, raw, summary)
        else:
            _import_json(db, json.loads(raw), summary)
    except Exception:
        return render(request, "import.html", db=db, user=user, active="import",
                      error="Couldn't read that file. Check the format and try again.")
    return render(request, "import.html", db=db, user=user, active="import",
                  message=f"Imported {summary['created_people']} people" +
                          (f" ({summary['skipped']} rows skipped)" if summary["skipped"] else "") + ".")
