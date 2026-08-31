"""API v1 — data export."""
import csv
import datetime as dt
import io
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import Person, JournalEntry
from .deps import get_current_api_user

router = APIRouter(prefix="/api/v1/export", tags=["export"])


@router.post("/json")
def export_json(db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    people = db.query(Person).order_by(Person.name).all()
    data = {
        "format": "kin-api-export",
        "version": 2,
        "exported_at": dt.datetime.utcnow().isoformat(),
        "exported_people": [],
    }
    for p in people:
        data["exported_people"].append({
            "name": p.name, "nickname": p.nickname, "pronouns": p.pronouns,
            "relationship_label": p.relationship_label,
            "birthday": f"{p.birthday_month}/{p.birthday_day}/{p.birthday_year or ''}" if p.birthday_month else None,
            "how_we_met": p.how_we_met,
            "met_date": p.met_date.isoformat() if p.met_date else None,
            "location": p.location, "phone": p.phone, "email": p.email, "notes": p.notes,
            "occupation": p.occupation, "hobbies": p.hobbies, "bio": p.bio,
            "ai_summary": p.ai_summary,
            "archived": p.archived,
            "checkin_cadence_days": p.checkin_cadence_days,
            "last_contact_date": p.last_contact_date.isoformat() if p.last_contact_date else None,
            "relationship_state": p.relationship_state.value if p.relationship_state else "none",
            "tags": [t.name for t in p.tags],
            "journal_entries": [{
                "date": e.entry_date.isoformat(), "title": e.title, "body": e.body,
                "event_type": e.event_type.value if e.event_type else None,
                "energy_cost": e.energy_cost.value if e.energy_cost else None,
                "location": e.location, "source": e.source,
                "with": [pp.name for pp in e.people],
            } for e in p.journal_entries],
        })
    payload = json.dumps(data, indent=2, default=str)
    return StreamingResponse(
        io.StringIO(payload), media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=kin_export.json"},
    )


@router.post("/csv/people")
def export_csv_people(db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    people = db.query(Person).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["name", "nickname", "relationship_label", "birthday_month", "birthday_day",
                      "birthday_year", "how_we_met", "met_date", "location", "phone", "email",
                      "occupation", "hobbies", "notes", "tags"])
    for p in people:
        writer.writerow([
            p.name, p.nickname or "", p.relationship_label or "", p.birthday_month or "",
            p.birthday_day or "", p.birthday_year or "", p.how_we_met or "",
            p.met_date.isoformat() if p.met_date else "", p.location or "", p.phone or "",
            p.email or "", p.occupation or "", p.hobbies or "",
            (p.notes or "").replace("\n", " "), ", ".join(t.name for t in p.tags),
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=kin_people.csv"},
    )


@router.post("/csv/journal")
def export_csv_journal(db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    entries = db.query(JournalEntry).order_by(JournalEntry.entry_date.desc()).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "title", "body", "event_type", "energy_cost", "location",
                      "people", "image_count", "source", "created_at"])
    for e in entries:
        writer.writerow([
            e.entry_date.isoformat(), e.title or "", e.body or "",
            e.event_type.value if e.event_type else "",
            e.energy_cost.value if e.energy_cost else "", e.location or "",
            ", ".join(p.name for p in e.people), len(e.images), e.source or "manual",
            e.created_at.isoformat() if e.created_at else "",
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=kin_journal.csv"},
    )
