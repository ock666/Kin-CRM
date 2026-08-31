import csv
import datetime as dt
import io
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import Person, JournalEntry
from ..render import render

router = APIRouter()


@router.get("/export")
def export_page(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    return render(request, "export.html", db=db, user=user, active="export")


@router.post("/export/json")
def export_json(db: Session = Depends(get_db), user=Depends(current_user)):
    people = db.query(Person).order_by(Person.name).all()
    data = {
        "format": "kin-export",
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
            "occupation": p.occupation, "hobbies": p.hobbies,
            "bio": p.bio,
            "ai_summary": p.ai_summary,
            "ai_starters_json": p.ai_starters_json,
            "avatar_url": p.avatar_url,
            "archived": p.archived,
            "checkin_cadence_days": p.checkin_cadence_days,
            "last_contact_date": p.last_contact_date.isoformat() if p.last_contact_date else None,
            "reminders_dismissed": p.reminders_dismissed,
            "relationship_state": p.relationship_state.value if p.relationship_state else "none",
            "tags": [t.name for t in p.tags],
            "notable_dates": [{"label": nd.label, "month": nd.month, "day": nd.day, "year": nd.year,
                               "recurring": nd.recurring, "notes": nd.notes} for nd in p.notable_dates],
            "notable_people": [{"name": np.name, "relation": np.relation} for np in p.notable_people_refs],
            "scratchpad_items": [s.text for s in p.scratchpad_items],
            "gift_ideas": [{"year": g.year, "description": g.description, "status": g.status.value}
                            for g in p.gift_ideas],
            "conflicts": [{
                "summary": c.summary, "status": c.status.value,
                "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
                "resolution_notes": c.resolution_notes,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "reminder_dismissed": c.reminder_dismissed,
                "ai_approach_json": c.ai_approach_json,
                "chat_messages": [{
                    "role": cm.role, "content": cm.content,
                    "created_at": cm.created_at.isoformat() if cm.created_at else None,
                } for cm in (c.chat_messages or [])],
            } for c in p.conflict_logs],
            "journal_entries": [{
                "date": e.entry_date.isoformat(), "title": e.title, "body": e.body,
                "event_type": e.event_type.value if e.event_type else None,
                "energy_cost": e.energy_cost.value if e.energy_cost else None,
                "location": e.location, "source": e.source,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "with": [pp.name for pp in e.people],
            } for e in p.journal_entries],
        })
    payload = json.dumps(data, indent=2, default=str)
    return StreamingResponse(io.StringIO(payload), media_type="application/json",
                              headers={"Content-Disposition": "attachment; filename=kin_export.json"})


@router.post("/export/csv")
def export_csv(db: Session = Depends(get_db), user=Depends(current_user)):
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
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                              headers={"Content-Disposition": "attachment; filename=kin_people.csv"})


@router.post("/export/csv/journal")
def export_csv_journal(db: Session = Depends(get_db), user=Depends(current_user)):
    entries = db.query(JournalEntry).order_by(JournalEntry.entry_date.desc()).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "title", "body", "event_type", "energy_cost", "location",
                      "people", "image_count", "source", "created_at"])
    for e in entries:
        writer.writerow([
            e.entry_date.isoformat(), e.title or "", e.body or "", e.event_type.value if e.event_type else "",
            e.energy_cost.value if e.energy_cost else "", e.location or "",
            ", ".join(p.name for p in e.people), len(e.images), e.source or "manual",
            e.created_at.isoformat() if e.created_at else "",
        ])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                              headers={"Content-Disposition": "attachment; filename=kin_journal.csv"})
