# routes/notification/notification_scheduler.py
import asyncio
import logging
import os
from datetime import datetime, timezone
from urllib.parse import quote_plus

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.util import utc

from routes.notification.notification_service import notification_service
from config import DB_HOST, DB_PORT, DB_NAME, DB_USERNAME, DB_PASSWORD

logger = logging.getLogger(__name__)

pw_quoted = quote_plus(str(DB_PASSWORD))
JOBSTORE_URL = f"postgresql+psycopg2://{DB_USERNAME}:{pw_quoted}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

jobstores = {"default": SQLAlchemyJobStore(url=JOBSTORE_URL)}

# IMPORTANT: force UTC timezone so run_date with tz-aware UTC works predictably
scheduler = AsyncIOScheduler(jobstores=jobstores, timezone=utc)


async def send_callback_reminder(user_id: str, lead_id: int, mobile: str):
    """
    The actual task that runs at call_back_date to notify the employee.
    """
    title = "Call Back Reminder"
    message = f"The callback time for lead {mobile} has arrived. Please call now."
    try:
        await notification_service.notify(user_id=user_id, title=title, message=message, lead_id=lead_id)
        logger.info("Sent callback reminder to user %s for lead %s", user_id, lead_id)
    except Exception as e:
        logger.exception("Failed to send callback reminder to %s for lead %s: %s",
                        user_id, lead_id, e)


def schedule_callback(user_id: str, lead_id: int, callback_dt: datetime, mobile: str):
    """
    Schedule (or reschedule) the reminder job.
    Uses deterministic job id so updating replaces existing.
    """
    # Normalize to aware UTC
    if callback_dt.tzinfo is None:
        callback_dt = callback_dt.replace(tzinfo=timezone.utc)
    else:
        callback_dt = callback_dt.astimezone(timezone.utc)

    job_id = f"callback_notify_{lead_id}"

    # Remove existing job if present
    try:
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
    except Exception:
        logger.warning("Failed to remove existing job %s before rescheduling", job_id)

    # NOTE: AsyncIOScheduler can run coroutine functions directly
    scheduler.add_job(
        send_callback_reminder,
        trigger="date",
        run_date=callback_dt,
        args=[user_id, lead_id, mobile],
        id=job_id,
        replace_existing=True,
        misfire_grace_time=600,  # 10 mins grace
        coalesce=True,
        max_instances=1,
    )
    logger.info("Scheduled callback job %s at %s for user %s",
                job_id, callback_dt.isoformat(), user_id)


def start_scheduler():
    """
    Start once per process. Safe to call multiple times.
    """
    if not scheduler.running:
        # Optional: more verbose logging to see scheduling clearly
        logging.getLogger('apscheduler').setLevel(logging.INFO)
        scheduler.start()
        logger.info("Callback scheduler started (UTC timezone).")


async def shutdown_scheduler():
    """
    Clean shutdown on app exit.
    """
    try:
        if scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("Callback scheduler stopped.")
    except Exception:
        logger.exception("Error while stopping scheduler")

def is_scheduler_running() -> bool:
    return scheduler.running

