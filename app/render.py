"""Small helper to render Jinja2 templates with common context (current user,
pending review counts for the sidebar badge, etc.) injected automatically so
individual routes don't have to repeat themselves."""
from pathlib import Path

from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from sqlalchemy.orm import Session

from .config import settings
from .models import InstagramPost, BirthdayMessageDraft, ReviewStatus

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _pending_review_count(db: Session | None) -> int:
    if db is None:
        return 0
    ig = db.query(InstagramPost).filter_by(status=ReviewStatus.pending).count()
    bd = db.query(BirthdayMessageDraft).filter_by(status=ReviewStatus.pending).count()
    return ig + bd


def render(request: Request, template: str, db: Session = None, user=None, active: str = "", **ctx):
    # One-shot "flash" notice for gamification level-ups/badge unlocks (see
    # app/services/gamification.py) - popped from the session so it only ever displays once,
    # right after the redirect that triggered it.
    try:
        gamification_flash = request.session.pop("gamification_flash", None)
    except AssertionError:
        # SessionMiddleware not present on this request scope (shouldn't happen in practice,
        # but fail quietly rather than breaking the page render over a toast notice).
        gamification_flash = None

    context = {
        "request": request,
        "app_name": settings.APP_NAME,
        "user": user,
        "active": active,
        "pending_review_count": _pending_review_count(db),
        "gamification_flash": gamification_flash,
        **ctx,
    }
    return templates.TemplateResponse(request, template, context)
