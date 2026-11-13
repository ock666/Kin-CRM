import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..database import SessionLocal
from ..models import User, Household
from ..settings_store import get_setting
from . import birthdays, push as push_service, resolution_plans, wrapped as wrapped_service

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def _household_reps(db):
    """One representative user per household, so household-wide jobs run exactly once."""
    reps = []
    for h in db.query(Household).all():
        u = db.query(User).filter(User.household_id == h.id).first()
        if u is not None:
            reps.append(u)
    return reps


def _all_users(db):
    return db.query(User).all()


def run_daily_jobs():
    db = SessionLocal()
    try:
        for rep in _household_reps(db):
            try:
                n = birthdays.generate_birthday_drafts(db, rep)
                if n:
                    logger.info("Generated %d birthday draft(s) for household %s", n, rep.household_id)
            except Exception:
                logger.exception("Birthday draft generation failed for household %s", rep.household_id)

            # Kin Wrapped season: generate the card once when it's due (mid-December), nudge the
            # household that it's ready, and prune stale cards so nothing accumulates.
            try:
                card, generated = wrapped_service.generate_if_due(db, rep)
                if generated:
                    try:
                        push_service.push_notification(
                            db, rep,
                            title="Kin Wrapped is ready",
                            body=f"Your {card.year} in review is waiting for you. 🎉",
                            url="/wrapped",
                            tag="wrapped",
                        )
                    except Exception:
                        logger.exception("Wrapped-ready push failed for household %s", rep.household_id)
            except Exception:
                logger.exception("Wrapped generation failed for household %s", rep.household_id)
            try:
                wrapped_service.cleanup_expired(db, rep)
            except Exception:
                logger.exception("Wrapped cleanup failed for household %s", rep.household_id)

        # Push goes to each member's own devices (about their shared household data).
        for member in _all_users(db):
            try:
                push_service.send_push_notifications(db, member)
            except Exception:
                logger.exception("Push notification send failed for user %s", member.id)
    finally:
        db.close()


def run_plan_job():
    db = SessionLocal()
    try:
        for rep in _household_reps(db):
            try:
                resolution_plans.generate_plans_for_idle(db, rep)
            except Exception:
                logger.exception("Resolution plan generation failed for household %s", rep.household_id)
    finally:
        db.close()


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    db = SessionLocal()
    try:
        hour = int(get_setting(db, "daily_job_hour", "8") or 8)
    finally:
        db.close()

    # Hotfix: a container that (re)starts after the daily 8am run would otherwise leave in-window
    # birthdays without a draft for up to ~24h. Generate birthday drafts once on startup so new
    # or edited birthdays always have a message ready, no matter when the container came up.
    db = SessionLocal()
    try:
        for rep in _household_reps(db):
            try:
                n = birthdays.generate_birthday_drafts(db, rep)
                if n:
                    logger.info("Startup: generated %d birthday draft(s) for household %s", n, rep.household_id)
            except Exception:
                logger.exception("Startup birthday draft generation failed for household %s", rep.household_id)
    finally:
        db.close()

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_daily_jobs,
        trigger=CronTrigger(hour=hour, minute=0),
        id="daily_jobs",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.add_job(
        run_plan_job,
        trigger=CronTrigger(minute="*/15"),
        id="plan_job",
        replace_existing=True,
        misfire_grace_time=900,
    )
    _scheduler.start()
    logger.info("Scheduler started - daily jobs run at %02d:00", hour)
    return _scheduler


def shutdown_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
