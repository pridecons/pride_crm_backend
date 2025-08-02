# routes/notification/notification_scheduler.py
import asyncio
from datetime import datetime
import logging
from urllib.parse import quote_plus
from config import DB_HOST, DB_PORT, DB_NAME, DB_USERNAME, DB_PASSWORD

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from routes.notification.notification_service import notification_service

logger = logging.getLogger(__name__)


pw_quoted = quote_plus(str(DB_PASSWORD))

# Configure jobstore to persist across restarts; adjust connection string to match your DB config
JOBSTORE_URL = f"postgresql+psycopg2://{DB_USERNAME}:{pw_quoted}@{DB_HOST}:{DB_PORT}/{DB_NAME}"  # replace with your actual DSN

jobstores = {
    "default": SQLAlchemyJobStore(url=JOBSTORE_URL)
}
scheduler = AsyncIOScheduler(jobstores=jobstores)


async def send_callback_reminder(user_id: str, lead_id: int, mobile: str):
    """
    The actual task that runs at call_back_date to notify the employee.
    """
    title = "Call Back Reminder"
    message = f"Lead {mobile} के लिए call back का समय आ गया है। कृपया कॉल करें।"
    try:
        await notification_service.notify(user_id=user_id, title=title, message=message)
        logger.info("Sent callback reminder to user %s for lead %s", user_id, lead_id)
    except Exception as e:
        logger.exception("Failed to send callback reminder to %s for lead %s: %s", user_id, lead_id, e)


def schedule_callback(user_id: str, lead_id: int, callback_dt: datetime, mobile: str):
    """
    Schedule (or reschedule) the reminder job.
    Uses a deterministic job id so updating replaces existing.
    """
    job_id = f"callback_notify_{lead_id}"
    # Remove existing if any (replace_existing=True also works, but explicit is safer)
    if scheduler.get_job(job_id):
        try:
            scheduler.remove_job(job_id)
        except Exception:
            logger.warning("Failed to remove existing job %s before rescheduling", job_id)

    scheduler.add_job(
        send_callback_reminder,
        trigger="date",
        run_date=callback_dt,
        args=[user_id, lead_id, mobile],
        id=job_id,
        replace_existing=True,
        misfire_grace_time=300,  # if a little late, still attempt within 5 minutes
    )
    logger.info("Scheduled callback reminder job %s at %s for user %s", job_id, callback_dt.isoformat(), user_id)


def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        logger.info("Callback scheduler started")
