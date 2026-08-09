import csv
import io
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import Person
from ..render import render

router = APIRouter()


@router.get("/export")
def export_page(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    return render(request, "export.html", db=db, user=user, active="export")


@router.get("/export/json")
def export_json(db: Session = Depends(get_db), user=Depends(current_user)):
    people = db.query(Person).all()
    data = []
    for p in people:
        data.append({
            "name": p.name, "nickname": p.nickname, "pronouns": p.pronouns,
            "relationship_label": p.relationship_label,
            "birthday": f"{p.birthday_month}/{p.birthday_day}/{p.birthday_year or ''}" if p.birthday_month else None,
            "how_we_met": p.how_we_met,
            "met_date": p.met_date.isoformat() if p.met_date else None,
            "location": p.location, "phone": p.phone, "email": p.email, "notes": p.notes,
            "occupation": p.occupation, "hobbies": p.hobbies,
            "ai_summary": p.ai_summary,
            "tags": [t.name for t in p.tags],
            "notable_dates": [{"label": nd.label, "month": nd.month, "day": nd.day, "year": nd.year}
                               for nd in p.notable_dates],
            "notable_people": [{"name": np.name, "relation": np.relation} for np in p.notable_people_refs],
            "scratchpad_items": [s.text for s in p.scratchpad_items],
            "gift_ideas": [{"year": g.year, "description": g.description, "status": g.status.value}
                            for g in p.gift_ideas],
            "journal_entries": [{
                "date": e.entry_date.isoformat(), "title": e.title, "body": e.body,
                "event_type": e.event_type.value, "with": [pp.name for pp in e.people],
            } for e in p.journal_entries],
        })
    payload = json.dumps({"exported_people": data}, indent=2, default=str)
    return StreamingResponse(io.StringIO(payload), media_type="application/json",
                              headers={"Content-Disposition": "attachment; filename=kin_export.json"})


@router.get("/export/csv")
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
