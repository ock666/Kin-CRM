"""API v1 — stats and reviews."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import InstagramPost, BirthdayMessageDraft, ReviewStatus
from ...services import gamification
from .deps import get_current_api_user

router = APIRouter(prefix="/api/v1", tags=["stats"])


@router.get("/reviews")
def get_reviews(db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    ig = db.query(InstagramPost).filter_by(status=ReviewStatus.pending).order_by(
        InstagramPost.posted_at.desc()).all()
    bd = db.query(BirthdayMessageDraft).filter_by(status=ReviewStatus.pending).order_by(
        BirthdayMessageDraft.created_at.desc()).all()
    return {
        "instagram_posts": [
            {"id": p.id, "person_name": p.person.name if p.person else "", "caption": p.caption,
             "media_url": p.media_url, "permalink": p.permalink, "post_type": p.post_type,
             "posted_at": p.posted_at.isoformat() if p.posted_at else None}
            for p in ig
        ],
        "birthday_drafts": [
            {"id": d.id, "person_name": d.person.name if d.person else "", "message": d.message,
             "created_at": d.created_at.isoformat() if d.created_at else None}
            for d in bd
        ],
    }


@router.get("/gamification")
def get_gamification(db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    data = gamification.get_stats_and_achievements(db)
    return {
        "xp": data["stats"].total_xp,
        "level": data["stats"].current_level,
        "next_level_threshold": data["next_level_threshold"],
        "progress_pct": data["progress_pct"],
        "unlocked_count": data["unlocked_count"],
        "achievements": data["achievements"],
    }
