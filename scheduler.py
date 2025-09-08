# scheduler.py - Complete Lead Cleanup Scheduler

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import sessionmaker
from sqlalchemy import and_

# Import your database models and utilities
from db.connection import engine
from db.models import Lead, LeadAssignment
from utils.AddLeadStory import AddLeadStory

logger = logging.getLogger(__name__)

# Create session factory (no autocommit/autoflush for safety)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class LeadCleanupScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.setup_jobs()

    # ------------------------------------------------------------------------
    # 1) Expired conversion cleanup (Points 8 & 9)
    # ------------------------------------------------------------------------
    def cleanup_expired_conversion_leads(self):
        """
        Clean up expired conversion leads:
        - For leads where assigned_for_conversion is True
        - conversion_deadline has passed
        - lead is not a client and not deleted

        Action:
        - Remove assignment
        - Reset conversion flags
        - Return lead to pool
        - Add story entry
        """
        db = SessionLocal()
        cleanup_count = 0

        try:
            logger.info("🔄 Starting lead cleanup process (expired conversions)...")

            now = datetime.utcnow()

            expired_leads = (
                db.query(Lead)
                .outerjoin(LeadAssignment, LeadAssignment.lead_id == Lead.id)
                .filter(
                    Lead.assigned_for_conversion.is_(True),
                    Lead.conversion_deadline.isnot(None),
                    Lead.conversion_deadline < now,
                    Lead.is_client.is_(False),
                    Lead.is_delete.is_(False),
                )
                .all()
            )

            logger.info("Found %d expired conversion leads", len(expired_leads))

            for lead in expired_leads:
                try:
                    assignment = (
                        db.query(LeadAssignment)
                        .filter(LeadAssignment.lead_id == lead.id)
                        .first()
                    )

                    user_name = "Unknown User"
                    user_code = "SYSTEM"

                    if assignment and assignment.user:
                        user_name = assignment.user.name
                        user_code = assignment.user.employee_code

                    days_assigned = 0
                    if lead.response_changed_at:
                        days_assigned = (now - lead.response_changed_at).days

                    # Add story before removal
                    AddLeadStory(
                        lead.id,
                        "SYSTEM",
                        (
                            f"⏰ Lead removed from {user_name} ({user_code}) due to "
                            f"conversion deadline expiry. Was assigned for {days_assigned} days "
                            f"without client conversion. Lead returned to pool."
                        ),
                    )

                    # Delete assignment if any
                    if assignment:
                        db.delete(assignment)

                    # Reset conversion/assignment fields
                    lead.assigned_for_conversion = False
                    lead.assigned_to_user = None
                    lead.conversion_deadline = None
                    # Keep lead.is_old_lead as-is (your old-lead API logic)

                    cleanup_count += 1
                    logger.info("Cleaned up lead %s from user %s", lead.id, user_name)

                except Exception as e:
                    logger.error("Error cleaning up lead %s: %s", lead.id, e, exc_info=True)
                    continue

            db.commit()
            logger.info("✅ Lead cleanup completed. Cleaned %d expired conversion leads", cleanup_count)
            return cleanup_count

        except Exception as e:
            logger.error("❌ Lead cleanup failed: %s", e, exc_info=True)
            db.rollback()
            return 0
        finally:
            db.close()

    # ------------------------------------------------------------------------
    # 2) Mark very old, never-assigned leads as old leads
    # ------------------------------------------------------------------------
    def cleanup_long_unassigned_leads(self):
        """
        Mark as old those non-client, non-deleted leads that:
        - were created > 6 months ago
        - have NEVER had an assignment
        """
        db = SessionLocal()
        marked_count = 0

        try:
            logger.info("🔄 Starting old lead marking process (6+ months unassigned)...")

            six_months_ago = datetime.utcnow() - timedelta(days=180)

            old_unassigned_leads = (
                db.query(Lead)
                .outerjoin(LeadAssignment, LeadAssignment.lead_id == Lead.id)
                .filter(
                    Lead.created_at < six_months_ago,
                    Lead.is_client.is_(False),
                    Lead.is_delete.is_(False),
                    Lead.is_old_lead.is_(False),
                    LeadAssignment.id.is_(None),  # never assigned
                )
                .all()
            )

            logger.info("Found %d long unassigned leads to mark as old", len(old_unassigned_leads))

            for lead in old_unassigned_leads:
                try:
                    lead.is_old_lead = True

                    AddLeadStory(
                        lead.id,
                        "SYSTEM",
                        (
                            "📅 Lead marked as old due to 6+ months without assignment. "
                            f"Created on: {lead.created_at.strftime('%Y-%m-%d')}"
                        ),
                    )

                    marked_count += 1
                    logger.info("Marked lead %s as old lead", lead.id)

                except Exception as e:
                    logger.error("Error marking lead %s as old: %s", lead.id, e, exc_info=True)
                    continue

            db.commit()
            logger.info("✅ Old lead marking completed. Marked %d leads as old", marked_count)
            return marked_count

        except Exception as e:
            logger.error("❌ Old lead marking failed: %s", e, exc_info=True)
            db.rollback()
            return 0
        finally:
            db.close()

    # ------------------------------------------------------------------------
    # 3) Cleanup very old assignments (hard safety)
    # ------------------------------------------------------------------------
    def cleanup_very_old_assignments(self):
        """
        Clean up assignments older than 30 days (hard cap).
        Adds a story, then deletes the assignment. It does NOT change client status.
        """
        db = SessionLocal()
        cleaned_count = 0

        try:
            logger.info("🔄 Starting very old assignment cleanup (30+ days)...")

            thirty_days_ago = datetime.utcnow() - timedelta(days=30)

            old_assignments = (
                db.query(LeadAssignment)
                .filter(LeadAssignment.fetched_at < thirty_days_ago)
                .all()
            )

            logger.info("Found %d very old assignments", len(old_assignments))

            for assignment in old_assignments:
                try:
                    if assignment.lead and assignment.user:
                        AddLeadStory(
                            assignment.lead_id,
                            "SYSTEM",
                            f"📅 Assignment removed due to 30+ days inactivity. Was assigned to: {assignment.user.name}",
                        )

                    db.delete(assignment)
                    cleaned_count += 1

                except Exception as e:
                    logger.error(
                        "Error cleaning old assignment %s: %s", assignment.id, e, exc_info=True
                    )
                    continue

            db.commit()
            logger.info("✅ Very old assignment cleanup completed. Cleaned %d assignments", cleaned_count)
            return cleaned_count

        except Exception as e:
            logger.error("❌ Very old assignment cleanup failed: %s", e, exc_info=True)
            db.rollback()
            return 0
        finally:
            db.close()

    # ------------------------------------------------------------------------
    # 4) Daily stats
    # ------------------------------------------------------------------------
    def generate_daily_stats(self):
        """
        Generate daily statistics for monitoring.
        """
        db = SessionLocal()

        try:
            now = datetime.utcnow()
            start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

            total_leads = db.query(Lead).filter(Lead.is_delete.is_(False)).count()

            active_assignments = (
                db.query(LeadAssignment)
                .filter(LeadAssignment.fetched_at >= now - timedelta(days=7))
                .count()
            )

            conversion_pending = (
                db.query(Lead)
                .filter(
                    Lead.assigned_for_conversion.is_(True),
                    Lead.is_client.is_(False),
                    Lead.conversion_deadline.isnot(None),
                    Lead.conversion_deadline > now,
                )
                .count()
            )

            # Compare DateTime vs DateTime (not date)
            clients_today = (
                db.query(Lead)
                .filter(
                    Lead.is_client.is_(True),
                    Lead.updated_at >= start_of_today,
                )
                .count()
            )

            result = {
                "date": start_of_today.date().isoformat(),
                "total_leads": total_leads,
                "active_assignments_last_7d": active_assignments,
                "conversion_pending": conversion_pending,
                "new_clients_today": clients_today,
            }

            logger.info(
                "📊 Daily Stats: %s",
                result,
            )
            return result

        except Exception as e:
            logger.error("Error generating daily stats: %s", e, exc_info=True)
            return {}
        finally:
            db.close()

    # ------------------------------------------------------------------------
    # Scheduler config
    # ------------------------------------------------------------------------
    def setup_jobs(self):
        """Setup all scheduled jobs"""
        try:
            # 1. Daily cleanup at 2:00 UTC
            self.scheduler.add_job(
                func=self.cleanup_expired_conversion_leads,
                trigger=CronTrigger(hour=2, minute=0),
                id="cleanup_expired_leads",
                name="Cleanup Expired Conversion Leads",
                replace_existing=True,
                misfire_grace_time=600,  # 10 minutes grace
            )

            # 2. Weekly cleanup on Sunday at 3:00 UTC
            self.scheduler.add_job(
                func=self.cleanup_long_unassigned_leads,
                trigger=CronTrigger(day_of_week="sun", hour=3, minute=0),
                id="cleanup_old_leads",
                name="Mark Long Unassigned Leads as Old",
                replace_existing=True,
                misfire_grace_time=1800,  # 30 minutes grace
            )

            # 3. Monthly cleanup on 1st at 4:00 UTC
            self.scheduler.add_job(
                func=self.cleanup_very_old_assignments,
                trigger=CronTrigger(day="1", hour=4, minute=0),
                id="cleanup_very_old_assignments",
                name="Cleanup Very Old Assignments",
                replace_existing=True,
                misfire_grace_time=1800,
            )

            # 4. Daily stats at 23:59 UTC
            self.scheduler.add_job(
                func=self.generate_daily_stats,
                trigger=CronTrigger(hour=23, minute=59),
                id="daily_stats",
                name="Generate Daily Statistics",
                replace_existing=True,
                misfire_grace_time=300,  # 5 minutes grace
            )

            logger.info("📅 All scheduled jobs configured successfully")

        except Exception as e:
            logger.error("Error setting up scheduled jobs: %s", e, exc_info=True)

    # ------------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------------
    def start(self):
        """Start the scheduler"""
        try:
            self.scheduler.start()
            logger.info("🚀 Lead cleanup scheduler started successfully")

            for job in self.scheduler.get_jobs():
                logger.info("📅 Job '%s' next run: %s", job.name, job.next_run_time)

            # Shutdown scheduler gracefully on process exit
            atexit.register(self.shutdown)

        except Exception as e:
            logger.error("Failed to start scheduler: %s", e, exc_info=True)
            raise

    def stop(self):
        """Stop the scheduler"""
        try:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=True)
                logger.info("🛑 Lead cleanup scheduler stopped")
            else:
                logger.info("🛑 Scheduler was not running")
        except Exception as e:
            logger.error("Error stopping scheduler: %s", e, exc_info=True)

    def shutdown(self):
        """Graceful shutdown"""
        self.stop()

    # ------------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------------
    def run_cleanup_now(self):
        """Run cleanup immediately for testing"""
        logger.info("🔄 Running manual cleanup...")

        try:
            expired_count = self.cleanup_expired_conversion_leads()
            old_count = self.cleanup_long_unassigned_leads()
            assignment_count = self.cleanup_very_old_assignments()
            stats = self.generate_daily_stats()

            result = {
                "manual_cleanup": True,
                "timestamp": datetime.utcnow().isoformat(),
                "results": {
                    "expired_leads_cleaned": expired_count,
                    "leads_marked_old": old_count,
                    "old_assignments_cleaned": assignment_count,
                    "stats": stats,
                },
            }

            logger.info("✅ Manual cleanup completed: %s", result)
            return result

        except Exception as e:
            logger.error("❌ Manual cleanup failed: %s", e, exc_info=True)
            return {
                "manual_cleanup": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }

    def get_status(self):
        """Get scheduler status"""
        try:
            jobs_info = []

            if self.scheduler.running:
                for job in self.scheduler.get_jobs():
                    jobs_info.append(
                        {
                            "id": job.id,
                            "name": job.name,
                            "next_run": job.next_run_time.isoformat()
                            if job.next_run_time
                            else None,
                            "trigger": str(job.trigger),
                            "misfire_grace_time": getattr(job, "misfire_grace_time", None),
                        }
                    )

            return {
                "scheduler_running": self.scheduler.running,
                "total_jobs": len(jobs_info),
                "jobs": jobs_info,
                "current_time": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error("Error getting scheduler status: %s", e, exc_info=True)
            return {
                "scheduler_running": False,
                "error": str(e),
                "current_time": datetime.utcnow().isoformat(),
            }

    def pause_job(self, job_id: str):
        """Pause a specific job"""
        try:
            self.scheduler.pause_job(job_id)
            logger.info("⏸️ Job '%s' paused", job_id)
            return True
        except Exception as e:
            logger.error("Error pausing job %s: %s", job_id, e, exc_info=True)
            return False

    def resume_job(self, job_id: str):
        """Resume a specific job"""
        try:
            self.scheduler.resume_job(job_id)
            logger.info("▶️ Job '%s' resumed", job_id)
            return True
        except Exception as e:
            logger.error("Error resuming job %s: %s", job_id, e, exc_info=True)
            return False


# Global scheduler instance
lead_scheduler = LeadCleanupScheduler()

# Standalone helpers
def manual_cleanup_expired_leads():
    return lead_scheduler.cleanup_expired_conversion_leads()

def manual_mark_old_leads():
    return lead_scheduler.cleanup_long_unassigned_leads()

def get_scheduler_status():
    return lead_scheduler.get_status()


# For quick manual tests
if __name__ == "__main__":
    print("Testing Lead Cleanup Scheduler...")

    print("\n1. Testing expired lead cleanup...")
    expired_count = manual_cleanup_expired_leads()
    print(f"Cleaned up {expired_count} expired leads")

    print("\n2. Testing old lead marking...")
    old_count = manual_mark_old_leads()
    print(f"Marked {old_count} leads as old")

    print("\n3. Testing scheduler status...")
    status = get_scheduler_status()
    print(f"Scheduler status: {status}")

    print("\n4. Testing manual cleanup...")
    result = lead_scheduler.run_cleanup_now()
    print(f"Manual cleanup result: {result}")

    print("\nAll tests completed!")
