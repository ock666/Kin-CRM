"""API v1 — stats and reviews."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import BirthdayMessageDraft, ReviewStatus
from ...services import gamification
from .deps import get_current_api_user

router = APIRouter(prefix="/api/v1", tags=["stats"])


@router.get("/reviews")
def get_reviews(db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    bd = db.query(BirthdayMessageDraft).filter_by(status=ReviewStatus.pending).order_by(
        BirthdayMessageDraft.generated_at.desc()).all()
    return {
        "birthday_drafts": [
            {"id": d.id, "person_name": d.person.name if d.person else "",
             "message": d.draft_text,
             "created_at": d.generated_at.isoformat() if d.generated_at else None}
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
