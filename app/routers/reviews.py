import datetime as dt

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import InstagramPost, BirthdayMessageDraft, ReviewStatus, JournalEntry, JournalImage, EventType
from ..render import render
from ..services import birthdays as bday_service
from ..services import instagram_poll
from ..services.ai_client import get_client_from_settings, AIError

router = APIRouter()


@router.get("/reviews")
def reviews_page(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    ig_posts = db.query(InstagramPost).filter_by(status=ReviewStatus.pending).order_by(InstagramPost.posted_at.desc()).all()
    bday_drafts = db.query(BirthdayMessageDraft).filter_by(status=ReviewStatus.pending).all()
    approved_bday = db.query(BirthdayMessageDraft).filter_by(status=ReviewStatus.approved).all()
    return render(request, "reviews.html", db=db, user=user, active="reviews",
                  ig_posts=ig_posts, bday_drafts=bday_drafts, approved_bday=approved_bday)


@router.post("/reviews/run-now")
def run_now(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    bday_service.generate_birthday_drafts(db)
    instagram_poll.poll_all(db)
    return RedirectResponse("/reviews", status_code=303)


@router.post("/reviews/instagram/{post_id}/approve")
def approve_instagram(post_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    post = db.get(InstagramPost, post_id)
    if post:
        entry = JournalEntry(
            author_user_id=user.id if user else None,
            title=f"Instagram post from @{post.person.instagram_username}",
            body=post.caption or "(no caption)",
            entry_date=post.posted_at.date() if post.posted_at else dt.date.today(),
            event_type=EventType.instagram,
            source="instagram",
        )
        entry.people.append(post.person)
        db.add(entry)
        db.flush()
        if post.media_url:
            db.add(JournalImage(journal_entry_id=entry.id, upload_path=post.media_url, caption="From Instagram"))
        post.status = ReviewStatus.approved
        post.imported_as_journal_entry_id = entry.id
        db.commit()
    return RedirectResponse("/reviews", status_code=303)


@router.post("/reviews/instagram/{post_id}/dismiss")
def dismiss_instagram(post_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    post = db.get(InstagramPost, post_id)
    if post:
        post.status = ReviewStatus.dismissed
        db.commit()
    return RedirectResponse("/reviews", status_code=303)


@router.post("/reviews/birthday/{draft_id}/approve")
def approve_birthday(draft_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                      draft_text: str = Form(...)):
    draft = db.get(BirthdayMessageDraft, draft_id)
    if draft:
        draft.draft_text = draft_text
        draft.status = ReviewStatus.approved
        db.commit()
    return RedirectResponse("/reviews", status_code=303)


@router.post("/reviews/birthday/{draft_id}/sent")
def mark_birthday_sent(draft_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    draft = db.get(BirthdayMessageDraft, draft_id)
    if draft:
        draft.status = ReviewStatus.sent
        draft.sent_at = dt.datetime.utcnow()
        db.commit()
    return RedirectResponse("/reviews", status_code=303)


@router.post("/reviews/birthday/{draft_id}/dismiss")
def dismiss_birthday(draft_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    draft = db.get(BirthdayMessageDraft, draft_id)
    if draft:
        draft.status = ReviewStatus.skipped
        db.commit()
    return RedirectResponse("/reviews", status_code=303)


@router.post("/reviews/birthday/{draft_id}/regenerate")
def regenerate_birthday(draft_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    draft = db.get(BirthdayMessageDraft, draft_id)
    if draft:
        try:
            ai = get_client_from_settings(db)
            if ai:
                person = draft.person
                draft.draft_text = ai.draft_birthday_message(
                    person.name, person.relationship_label or "", person.notes or person.ai_summary or ""
                )
                db.commit()
        except AIError:
            pass
    return RedirectResponse("/reviews", status_code=303)
