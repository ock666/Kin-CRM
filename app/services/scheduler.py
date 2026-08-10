import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..database import SessionLocal
from ..settings_store import get_setting
from . import birthdays, instagram_poll, push as push_service

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def run_daily_jobs():
    db = SessionLocal()
    try:
        try:
            n = birthdays.generate_birthday_drafts(db)
            if n:
                logger.info("Generated %d birthday draft(s)", n)
        except Exception:
            logger.exception("Birthday draft generation failed")

        try:
            summary = instagram_poll.poll_all(db)
            if summary["new_posts"]:
                logger.info("Instagram poll found %d new post(s)", summary["new_posts"])
            if summary["errors"]:
                logger.info("Instagram poll errors: %s", summary["errors"])
        except Exception:
            logger.exception("Instagram poll failed")

        # Web Push: after generating drafts, notify opted-in devices about due birthdays and
        # overdue cadences - aggregated and quiet, a no-op if push isn't configured.
        try:
            push_service.send_push_notifications(db)
        except Exception:
            logger.exception("Push notification send failed")
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

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_daily_jobs,
        trigger=CronTrigger(hour=hour, minute=0),
        id="daily_jobs",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    logger.info("Scheduler started - daily jobs run at %02d:00", hour)
    return _scheduler


def shutdown_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
