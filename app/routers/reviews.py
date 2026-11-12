import datetime as dt

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..scoping import get_owned_child
from ..deps import current_user
from ..models import (
    BirthdayMessageDraft, GiftIdea, GiftStatus, ReviewStatus, Person,
)
from ..render import render
from ..services import birthdays as bday_service
from ..services.ai_client import get_client_from_settings, build_person_context, AIError

router = APIRouter()


@router.get("/reviews")
def reviews_page(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    bday_drafts = (
        db.query(BirthdayMessageDraft)
        .join(Person, Person.id == BirthdayMessageDraft.person_id)
        .filter(Person.user_id == user.id, BirthdayMessageDraft.status == ReviewStatus.pending)
        .all()
    )
    approved_bday = (
        db.query(BirthdayMessageDraft)
        .join(Person, Person.id == BirthdayMessageDraft.person_id)
        .filter(Person.user_id == user.id, BirthdayMessageDraft.status == ReviewStatus.approved)
        .all()
    )

    # Map (person_id, year) -> pending gift idea, so each birthday draft card can show its
    # matching gift suggestion (generated together, always human-reviewed before acting on it).
    gift_ideas = (
        db.query(GiftIdea)
        .join(Person, Person.id == GiftIdea.person_id)
        .filter(Person.user_id == user.id, GiftIdea.status == GiftStatus.suggested)
        .all()
    )
    gifts_by_key = {(g.person_id, g.year): g for g in gift_ideas}

    return render(request, "reviews.html", db=db, user=user, active="reviews",
                  bday_drafts=bday_drafts, approved_bday=approved_bday,
                  gifts_by_key=gifts_by_key)


@router.post("/reviews/run-now")
def run_now(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    bday_service.generate_birthday_drafts(db, user)
    return RedirectResponse("/reviews", status_code=303)


@router.post("/reviews/birthday/{draft_id}/approve")
def approve_birthday(draft_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                      draft_text: str = Form(...)):
    draft = get_owned_child(db, user, BirthdayMessageDraft, draft_id)
    if draft:
        draft.draft_text = draft_text
        draft.status = ReviewStatus.approved
        db.commit()
    return RedirectResponse("/reviews", status_code=303)


@router.post("/reviews/birthday/{draft_id}/sent")
def mark_birthday_sent(draft_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    draft = get_owned_child(db, user, BirthdayMessageDraft, draft_id)
    if draft:
        draft.status = ReviewStatus.sent
        draft.sent_at = dt.datetime.utcnow()
        db.commit()
    return RedirectResponse("/reviews", status_code=303)


@router.post("/reviews/birthday/{draft_id}/dismiss")
def dismiss_birthday(draft_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    draft = get_owned_child(db, user, BirthdayMessageDraft, draft_id)
    if draft:
        draft.status = ReviewStatus.skipped
        db.commit()
    return RedirectResponse("/reviews", status_code=303)


@router.post("/reviews/birthday/{draft_id}/regenerate")
def regenerate_birthday(draft_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    draft = get_owned_child(db, user, BirthdayMessageDraft, draft_id)
    if draft:
        try:
            ai = get_client_from_settings(db)
            if ai:
                person = draft.person
                draft.draft_text = ai.draft_birthday_message(
                    person.name, person.relationship_label or "", build_person_context(person)
                )
                db.commit()
        except AIError:
            pass
    return RedirectResponse("/reviews", status_code=303)


@router.post("/reviews/gift/{gift_id}/given")
def mark_gift_given(gift_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    gift = get_owned_child(db, user, GiftIdea, gift_id)
    if gift:
        gift.status = GiftStatus.given
        db.commit()
    return RedirectResponse("/reviews", status_code=303)


@router.post("/reviews/gift/{gift_id}/dismiss")
def dismiss_gift(gift_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    gift = get_owned_child(db, user, GiftIdea, gift_id)
    if gift:
        gift.status = GiftStatus.dismissed
        db.commit()
    return RedirectResponse("/reviews", status_code=303)


@router.post("/reviews/gift/{gift_id}/regenerate")
def regenerate_gift(gift_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    gift = get_owned_child(db, user, GiftIdea, gift_id)
    if gift:
        try:
            ai = get_client_from_settings(db)
            if ai:
                person = gift.person
                previous = [g.description for g in person.gift_ideas if g.id != gift.id]
                gift.description = ai.suggest_gift(person.name, build_person_context(person), previous)
                db.commit()
        except AIError:
            pass
    return RedirectResponse("/reviews", status_code=303)
