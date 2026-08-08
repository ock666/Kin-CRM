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
    context = {
        "request": request,
        "app_name": settings.APP_NAME,
        "user": user,
        "active": active,
        "pending_review_count": _pending_review_count(db),
        **ctx,
    }
    return templates.TemplateResponse(template, context)
