import logging
import json
from pathlib import Path

import markdown2
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .database import Base, engine, SessionLocal
from .render import templates
from .models import User
from .migrations import run_startup_migrations
from .services.scheduler import start_scheduler, shutdown_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.APP_NAME)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _initials(name: str) -> str:
    if not name:
        return "?"
    parts = [p for p in name.strip().split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _parse_json(raw):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


templates.env.filters["markdown"] = lambda text: markdown2.markdown(text or "", extras=["break-on-newline", "linkify"])
templates.env.filters["initials"] = _initials
templates.env.filters["parse_json"] = _parse_json

OPEN_PATHS = {"/login", "/setup", "/health", "/sw.js", "/manifest.webmanifest", "/static/offline.html"}


# PWA assets served from the root so the service worker can control the whole site scope,
# and so they remain reachable before/without authentication (browser install & offline need
# this). The SW must be served with Service-Worker-Allowed: / to override its /static/ scope.
@app.get("/sw.js")
def service_worker():
    return Response(
        (STATIC_DIR / "sw.js").read_bytes(),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/manifest.webmanifest")
def manifest():
    return Response(
        (STATIC_DIR / "manifest.webmanifest").read_bytes(),
        media_type="application/manifest+json",
    )



@app.middleware("http")
async def auth_gate(request: Request, call_next):
    path = request.url.path
    if path.startswith("/static") or path in OPEN_PATHS:
        return await call_next(request)

    db = SessionLocal()
    try:
        any_user = db.query(User).first()
        if any_user is None and path != "/setup":
            return RedirectResponse("/setup", status_code=303)
        if any_user is not None:
            user_id = request.session.get("user_id")
            if not user_id or db.get(User, user_id) is None:
                request.session.clear()
                return RedirectResponse(f"/login?next={path}", status_code=303)
    finally:
        db.close()

    return await call_next(request)


# IMPORTANT: registered *after* auth_gate above so that SessionMiddleware ends up as the
# outer layer (Starlette wraps middleware in reverse-registration order - the most recently
# added middleware runs first). SessionMiddleware must run before auth_gate so that
# `request.session` is actually available by the time auth_gate reads it.
app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET, same_site="lax", max_age=60 * 60 * 24 * 30)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    run_startup_migrations()
    if not settings.DISABLE_SCHEDULER:
        start_scheduler()
    logger.info("Kin started. Data dir: %s", settings.DATA_DIR)


@app.on_event("shutdown")
def on_shutdown():
    shutdown_scheduler()


@app.get("/health")
def health():
    return {"status": "ok"}


from .routers import auth as auth_router  # noqa: E402
from .routers import dashboard as dashboard_router  # noqa: E402
from .routers import people as people_router  # noqa: E402
from .routers import journal as journal_router  # noqa: E402
from .routers import immich as immich_router  # noqa: E402
from .routers import settings as settings_router  # noqa: E402
from .routers import reviews as reviews_router  # noqa: E402
from .routers import export as export_router  # noqa: E402
from .routers import ai as ai_router  # noqa: E402
from .routers import conflicts as conflicts_router  # noqa: E402
from .routers import push as push_router  # noqa: E402
from .routers import data_import as import_router  # noqa: E402

app.include_router(auth_router.router)
app.include_router(dashboard_router.router)
app.include_router(people_router.router)
app.include_router(journal_router.router)
app.include_router(immich_router.router)
app.include_router(settings_router.router)
app.include_router(reviews_router.router)
app.include_router(export_router.router)
app.include_router(ai_router.router)
app.include_router(conflicts_router.router)
app.include_router(push_router.router)
app.include_router(import_router.router)


# Calm, on-brand error pages - never a bare stack trace, never more alarming than the moment
# deserves. The 404 page adapts its frame to auth state via the same base template.
@app.exception_handler(404)
async def not_found(request: Request, exc):
    db = SessionLocal()
    any_user = None
    try:
        any_user = db.query(User).first()
    finally:
        db.close()
    user = None
    if any_user is not None:
        user_id = request.session.get("user_id")
        if user_id:
            db2 = SessionLocal()
            try:
                user = db2.get(User, user_id)
            finally:
                db2.close()
    return templates.TemplateResponse(
        request, "404.html",
        {"request": request, "user": user, "active": "", "app_name": settings.APP_NAME},
        status_code=404,
    )


@app.exception_handler(500)
async def server_error(request: Request, exc):
    return templates.TemplateResponse(
        request, "500.html",
        {"request": request, "user": None, "active": "", "app_name": settings.APP_NAME},
        status_code=500,
    )
