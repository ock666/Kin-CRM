import datetime as dt

from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import Person, Tag, NotableDate, ScratchpadItem, NotablePersonRef, ConflictStatus, RelationshipState
from ..render import render
from ..services import birthdays as bday_service
from ..services import checkins, friend_rank, gamification, states as state_service
from ..settings_store import get_setting

router = APIRouter()


def _month_names():
    return [
        (1, "January"), (2, "February"), (3, "March"), (4, "April"),
        (5, "May"), (6, "June"), (7, "July"), (8, "August"),
        (9, "September"), (10, "October"), (11, "November"), (12, "December"),
    ]


@router.get("/people")
def people_list(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                 q: str = Query(""), tag: str = Query(""), show_archived: bool = Query(False),
                 view: str = Query("grid")):
    if not user:
        return RedirectResponse("/login")
    query = db.query(Person).filter(Person.archived.is_(show_archived))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Person.name.ilike(like), Person.nickname.ilike(like)))
    people = query.order_by(Person.name).all()
    if tag:
        people = [p for p in people if any(t.name == tag for t in p.tags)]
    all_tags = db.query(Tag).order_by(Tag.name).all()
    ranks = {p.id: friend_rank.compute_friend_rank(p) for p in people}
    watermeters = {p.id: checkins.compute_cadence_watermeter(p) for p in people}

    circles = None
    if view == "circles":
        circles_dict: dict[str, list[Person]] = {}
        untagged = []
        for p in people:
            if not p.tags:
                untagged.append(p)
            else:
                for t in p.tags:
                    circles_dict.setdefault(t.name, []).append(p)
        circles = [(tag_name, tag_people) for tag_name, tag_people in circles_dict.items()]
        circles.sort(key=lambda t: t[0])
        if untagged:
            circles.append(("Uncircled", untagged))

    return render(request, "people_list.html", db=db, user=user, active="people",
                  people=people, all_tags=all_tags, q=q, active_tag=tag, show_archived=show_archived,
                  ranks=ranks, watermeters=watermeters, view=view, circles=circles)


@router.get("/people/new")
def people_new(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    default_cadence = get_setting(db, "checkin_default_cadence_days", "60")
    return render(request, "person_form.html", db=db, user=user, active="people",
                  person=None, months=_month_names(), default_cadence=default_cadence)


@router.post("/people/new")
def people_create(
    request: Request, db: Session = Depends(get_db), user=Depends(current_user),
    name: str = Form(...), nickname: str = Form(""), pronouns: str = Form(""),
    relationship_label: str = Form(""), birthday_month: str = Form(""), birthday_day: str = Form(""),
    birthday_year: str = Form(""), how_we_met: str = Form(""), met_date: str = Form(""),
    location: str = Form(""), phone: str = Form(""), email: str = Form(""), notes: str = Form(""),
    occupation: str = Form(""), hobbies: str = Form(""), bio: str = Form(""),
    checkin_cadence_days: str = Form(""),
):
    if not user:
        return RedirectResponse("/login")
    clean_name = name.strip()
    person = Person(
        name=clean_name, nickname=(nickname.strip() or clean_name), pronouns=pronouns or None,
        relationship_label=relationship_label or None,
        birthday_month=int(birthday_month) if birthday_month else None,
        birthday_day=int(birthday_day) if birthday_day else None,
        birthday_year=int(birthday_year) if birthday_year else None,
        how_we_met=how_we_met or None,
        met_date=dt.date.fromisoformat(met_date) if met_date else None,
        location=location or None, phone=phone or None, email=email or None, notes=notes or None,
        occupation=occupation.strip() or None, hobbies=hobbies.strip() or None,
        bio=bio.strip() or None,
        checkin_cadence_days=int(checkin_cadence_days) if checkin_cadence_days else None,
    )
    db.add(person)
    db.commit()
    gamification.award_and_flash(request, db, "PROFILE_UPDATED")
    return RedirectResponse(f"/people/{person.id}", status_code=303)


@router.get("/people/{person_id}")
def person_detail(person_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    person = db.get(Person, person_id)
    if not person:
        return RedirectResponse("/people")
    entries = person.journal_entries
    rank = friend_rank.compute_friend_rank(person)
    watermeter = checkins.compute_cadence_watermeter(person)
    open_conflicts = [c for c in person.conflict_logs if c.status == ConflictStatus.unresolved]
    today = dt.date.today()
    bday_days = bday_service.days_until_birthday(person)
    try:
        bday_lead = int(get_setting(db, "birthday_lead_days", "3") or 3)
    except ValueError:
        bday_lead = 3

    person_state = state_service.effective_state(person, today)
    suggestions = state_service.suggest_states(db, today=today)
    person_suggestion = next((s for p, s, r in suggestions if p.id == person.id), None)
    return render(request, "person_detail.html", db=db, user=user, active="people",
                  person=person, entries=entries, today=today, rank=rank,
                  watermeter=watermeter, open_conflicts=open_conflicts,
                  bday_days=bday_days, bday_lead=bday_lead,
                  person_state=person_state, person_suggestion=person_suggestion)


@router.get("/people/{person_id}/edit")
def person_edit(person_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    person = db.get(Person, person_id)
    if not person:
        return RedirectResponse("/people")
    return render(request, "person_form.html", db=db, user=user, active="people",
                  person=person, months=_month_names())


@router.post("/people/{person_id}/edit")
def person_update(
    person_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user),
    name: str = Form(...), nickname: str = Form(""), pronouns: str = Form(""),
    relationship_label: str = Form(""), birthday_month: str = Form(""), birthday_day: str = Form(""),
    birthday_year: str = Form(""), how_we_met: str = Form(""), met_date: str = Form(""),
    location: str = Form(""), phone: str = Form(""), email: str = Form(""), notes: str = Form(""),
    occupation: str = Form(""), hobbies: str = Form(""), bio: str = Form(""),
    checkin_cadence_days: str = Form(""), instagram_username: str = Form(""),
    instagram_enabled: str = Form(""),
):
    if not user:
        return RedirectResponse("/login")
    person = db.get(Person, person_id)
    if not person:
        return RedirectResponse("/people")
    clean_name = name.strip()
    person.name = clean_name
    person.nickname = nickname.strip() or clean_name
    person.pronouns = pronouns or None
    person.relationship_label = relationship_label or None
    person.birthday_month = int(birthday_month) if birthday_month else None
    person.birthday_day = int(birthday_day) if birthday_day else None
    person.birthday_year = int(birthday_year) if birthday_year else None
    person.how_we_met = how_we_met or None
    person.met_date = dt.date.fromisoformat(met_date) if met_date else None
    person.location = location or None
    person.phone = phone or None
    person.email = email or None
    person.notes = notes or None
    person.occupation = occupation.strip() or None
    person.hobbies = hobbies.strip() or None
    person.bio = bio.strip() or None
    person.checkin_cadence_days = int(checkin_cadence_days) if checkin_cadence_days else None
    person.instagram_username = instagram_username.strip().lstrip("@") or None
    person.instagram_enabled = bool(instagram_enabled)
    db.commit()
    gamification.award_and_flash(request, db, "PROFILE_UPDATED")
    return RedirectResponse(f"/people/{person.id}", status_code=303)


@router.post("/people/{person_id}/archive")
def person_archive(person_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    person = db.get(Person, person_id)
    if person:
        person.archived = not person.archived
        db.commit()
    return RedirectResponse(f"/people/{person_id}", status_code=303)


@router.post("/people/{person_id}/delete")
def person_delete(person_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    person = db.get(Person, person_id)
    if person:
        db.delete(person)
        db.commit()
    return RedirectResponse("/people", status_code=303)


@router.post("/people/{person_id}/tags")
def add_tag(person_id: int, db: Session = Depends(get_db), user=Depends(current_user), tag_name: str = Form(...)):
    person = db.get(Person, person_id)
    if not person:
        return RedirectResponse("/people")
    tag_name = tag_name.strip()
    if tag_name:
        tag = db.query(Tag).filter(Tag.name == tag_name).first()
        if not tag:
            tag = Tag(name=tag_name)
            db.add(tag)
            db.flush()
        if tag not in person.tags:
            person.tags.append(tag)
        db.commit()
    return RedirectResponse(f"/people/{person_id}", status_code=303)


@router.post("/people/{person_id}/tags/{tag_id}/remove")
def remove_tag(person_id: int, tag_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    person = db.get(Person, person_id)
    tag = db.get(Tag, tag_id)
    if person and tag and tag in person.tags:
        person.tags.remove(tag)
        db.commit()
    return RedirectResponse(f"/people/{person_id}", status_code=303)


@router.post("/people/{person_id}/notable-dates")
def add_notable_date(
    person_id: int, db: Session = Depends(get_db), user=Depends(current_user),
    label: str = Form(...), month: int = Form(...), day: int = Form(...), year: str = Form(""),
):
    nd = NotableDate(person_id=person_id, label=label.strip(), month=month, day=day,
                      year=int(year) if year else None)
    db.add(nd)
    db.commit()
    return RedirectResponse(f"/people/{person_id}", status_code=303)


@router.post("/notable-dates/{nd_id}/delete")
def delete_notable_date(nd_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    nd = db.get(NotableDate, nd_id)
    if nd:
        person_id = nd.person_id
        db.delete(nd)
        db.commit()
        return RedirectResponse(f"/people/{person_id}", status_code=303)
    return RedirectResponse("/people", status_code=303)


@router.post("/people/{person_id}/link-immich")
def link_immich(person_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                 immich_person_id: str = Form(...)):
    person = db.get(Person, person_id)
    if person:
        person.immich_person_id = immich_person_id
        person.avatar_url = f"/immich/person/{immich_person_id}/thumbnail"
        db.commit()
        gamification.check_only(request, db)
    return RedirectResponse(f"/people/{person_id}", status_code=303)


@router.post("/people/{person_id}/unlink-immich")
def unlink_immich(person_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    person = db.get(Person, person_id)
    if person:
        person.immich_person_id = None
        person.avatar_url = None
        db.commit()
    return RedirectResponse(f"/people/{person_id}", status_code=303)


@router.post("/people/{person_id}/scratchpad")
def add_scratchpad_item(person_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                         text: str = Form(...)):
    text = text.strip()
    if text:
        db.add(ScratchpadItem(person_id=person_id, text=text))
        db.commit()
        gamification.check_only(request, db)
    return RedirectResponse(f"/people/{person_id}", status_code=303)


@router.post("/scratchpad/{item_id}/delete")
def delete_scratchpad_item(item_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    item = db.get(ScratchpadItem, item_id)
    if item:
        person_id = item.person_id
        db.delete(item)
        db.commit()
        gamification.check_only(request, db, context={"scratchpad_cleared": True})
        return RedirectResponse(f"/people/{person_id}", status_code=303)
    return RedirectResponse("/people", status_code=303)


@router.post("/people/{person_id}/notable-people")
def add_notable_person(person_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                        name: str = Form(...), relation: str = Form("")):
    name = name.strip()
    if name:
        db.add(NotablePersonRef(person_id=person_id, name=name, relation=relation.strip() or None))
        db.commit()
        gamification.check_only(request, db)
    return RedirectResponse(f"/people/{person_id}", status_code=303)


@router.post("/notable-people/{ref_id}/delete")
def delete_notable_person(ref_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    ref = db.get(NotablePersonRef, ref_id)
    if ref:
        person_id = ref.person_id
        db.delete(ref)
        db.commit()
        return RedirectResponse(f"/people/{person_id}", status_code=303)
    return RedirectResponse("/people", status_code=303)


@router.post("/people/{person_id}/state")
def set_relationship_state(person_id: int, request: Request, db: Session = Depends(get_db),
                            user=Depends(current_user), state: str = Form("")):
    person = db.get(Person, person_id)
    if person and state in ("none", "wants_space", "drifted"):
        person.relationship_state = RelationshipState(state)
        db.commit()
        labels = {"none": "cleared", "wants_space": "set to 'wants space'", "drifted": "marked as drifted"}
        request.session["notice_flash"] = f"Relationship state {labels[state]}. 🕊️"
    return RedirectResponse(f"/people/{person_id}", status_code=303)


@router.post("/people/{person_id}/state-suggestion/apply")
def apply_state_suggestion(person_id: int, request: Request, db: Session = Depends(get_db),
                            user=Depends(current_user)):
    person = db.get(Person, person_id)
    if person:
        suggestions = state_service.suggest_states(db)
        for p, suggested, reason in suggestions:
            if p.id == person.id:
                person.relationship_state = suggested
                db.commit()
                request.session["notice_flash"] = f"Marked as '{suggested.value.replace('_', ' ')}'. Gentle reminders softened. 🕊️"
                break
    return RedirectResponse(f"/people/{person_id}", status_code=303)


@router.post("/people/{person_id}/state-suggestion/dismiss")
def dismiss_state_suggestion(person_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    return RedirectResponse(f"/people/{person_id}", status_code=303)


@router.post("/tags/{tag_id}/color")
def set_tag_color(tag_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                   color: str = Form(...)):
    tag = db.get(Tag, tag_id)
    if tag and color:
        tag.color = color
        db.commit()
    return RedirectResponse("/people", status_code=303)
