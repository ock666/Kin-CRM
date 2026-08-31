"""Small helper to render Jinja2 templates with common context (current user,
pending review counts for the sidebar badge, etc.) injected automatically so
individual routes don't have to repeat themselves."""
import datetime as dt
import json
from pathlib import Path

from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from sqlalchemy.orm import Session

from .config import settings
from .models import InstagramPost, BirthdayMessageDraft, ReviewStatus
from .services import whatsnew

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _pending_review_count(db: Session | None) -> int:
    if db is None:
        return 0
    ig = db.query(InstagramPost).filter_by(status=ReviewStatus.pending).count()
    bd = db.query(BirthdayMessageDraft).filter_by(status=ReviewStatus.pending).count()
    return ig + bd


def _wrapped_ready(db: Session | None) -> bool:
    """Whether a fresh Kin Wrapped card exists for the current year (drives the sidebar link
    and dashboard banner). Only computed when a DB session is available."""
    if db is None:
        return False
    try:
        from .services import wrapped as wrapped_service
        return wrapped_service.get_fresh_card(db) is not None
    except Exception:
        return False


def render(request: Request, template: str, db: Session = None, user=None, active: str = "", **ctx):
    try:
        gamification_flash = request.session.pop("gamification_flash", None)
        notice_flash = request.session.pop("notice_flash", None)
    except AssertionError:
        gamification_flash = None
        notice_flash = None

    headers = ctx.pop("_headers", None)
    context = {
        "request": request,
        "app_name": settings.APP_NAME,
        "app_version": settings.APP_VERSION,
        "whats_new": whatsnew.WHATS_NEW,
        "user": user,
        "active": active,
        "pending_review_count": _pending_review_count(db),
        "current_year": dt.date.today().year,
        "wrapped_ready": _wrapped_ready(db),
        "gamification_flash": gamification_flash,
        "notice_flash": notice_flash,
        **ctx,
    }
    return templates.TemplateResponse(request, template, context, headers=headers)
