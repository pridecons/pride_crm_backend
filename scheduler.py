# scheduler.py - Complete Lead Cleanup Scheduler (timezone-safe, config-aware)

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import sessionmaker
from sqlalchemy import and_, or_

# Import your database models and utilities
from db.connection import engine
from db.models import (
    Lead,
    LeadAssignment,
    LeadFetchConfig,
    UserDetails,
)
from utils.AddLeadStory import AddLeadStory

logger = logging.getLogger(__name__)

# Create session factory (safe defaults)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# -----------------------------
# Time helpers (fix naive/aware issues)
# -----------------------------
def utcnow() -> datetime:
    """Return timezone-aware UTC 'now'."""
    return datetime.now(timezone.utc)

def to_aware_utc(dt: datetime | None) -> datetime | None:
    """Coerce any datetime (possibly naive) to timezone-aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # interpret naive as UTC (most setups use UTC in app/DB)
        return dt.replace(tzinfo=timezone.utc)
    # convert to UTC if it's aware but not UTC
    return dt.astimezone(timezone.utc)

# -----------------------------
# Config resolution helpers
# -----------------------------
def _role_key(role_id):
    """Return a string key for role_id regardless of whether role_id is Enum/int/str/None."""
    if role_id is None:
        return None
    return getattr(role_id, "value", str(role_id))

def load_fetch_config_for_lead(db, lead: Lead):
    """
    Resolve LeadFetchConfig for a given lead using priority:
      1) Current assignee's (role_id + branch_id)
      2) Current assignee's role_id (global)
      3) Lead's branch (branch_global)
      4) In-memory defaults
    """
    cfg = None

    # Try current assignee, if any
    assignee = None
    if lead.assigned_to_user:
        assignee = (
            db.query(UserDetails)
            .filter(UserDetails.employee_code == lead.assigned_to_user)
            .first()
        )

    # 1) role+branch (assignee)
    if assignee and assignee.role_id and assignee.branch_id is not None:
        rk = _role_key(assignee.role_id)
        cfg = (
            db.query(LeadFetchConfig)
            .filter(
                LeadFetchConfig.role_id == rk,
                LeadFetchConfig.branch_id == assignee.branch_id,
            )
            .first()
        )
        if cfg:
            return cfg, "role_branch"

    # 2) role (assignee, global)
    if assignee and assignee.role_id:
        rk = _role_key(assignee.role_id)
        cfg = (
            db.query(LeadFetchConfig)
            .filter(
                LeadFetchConfig.role_id == rk,
                LeadFetchConfig.branch_id.is_(None),
            )
            .first()
        )
        if cfg:
            return cfg, "role_global"

    # 3) branch (lead branch, global)
    if lead.branch_id is not None:
        cfg = (
            db.query(LeadFetchConfig)
            .filter(
                LeadFetchConfig.role_id.is_(None),
                LeadFetchConfig.branch_id == lead.branch_id,
            )
            .first()
        )
        if cfg:
            return cfg, "branch_global"

    # 4) defaults
    class TempConfig:
        def __init__(self):
            self.per_request_limit = 100
            self.daily_call_limit = 50
            self.last_fetch_limit = 10
            self.assignment_ttl_hours = 24
            self.old_lead_remove_days = 30

    return TempConfig(), "default"

# -----------------------------
# Scheduler
# -----------------------------
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
        - assigned_for_conversion = True
        - conversion_deadline passed
        - not a client and not deleted

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

            now = utcnow()

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

                    # Normalize timestamps before math
                    changed_at = to_aware_utc(lead.response_changed_at)
                    days_assigned = ((now - changed_at).days if changed_at else 0)

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

                    # Delete assignment
                    if assignment:
                        db.delete(assignment)

                    # Reset conversion/assignment fields
                    lead.assigned_for_conversion = False
                    lead.assigned_to_user = None
                    lead.conversion_deadline = None

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

            six_months_ago = utcnow() - timedelta(days=180)

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

                    created_at = to_aware_utc(lead.created_at)
                    created_str = created_at.strftime("%Y-%m-%d") if created_at else "unknown"

                    AddLeadStory(
                        lead.id,
                        "SYSTEM",
                        f"📅 Lead marked as old due to 6+ months without assignment. Created on: {created_str}",
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

            thirty_days_ago = utcnow() - timedelta(days=30)

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
            now = utcnow()
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

            logger.info("📊 Daily Stats: %s", result)
            return result

        except Exception as e:
            logger.error("Error generating daily stats: %s", e, exc_info=True)
            return {}
        finally:
            db.close()

    # ------------------------------------------------------------------------
    # 5) Release worked leads after lock window (config-aware)
    # ------------------------------------------------------------------------
    def release_worked_leads_after_lock_window(self):
        """
        Releases worked leads (lead_response_id != NULL) back to the pool
        after the lock window determined by LeadFetchConfig:
          - old_lead_remove_days: keep lead locked for this many days since response_changed_at.
          - assignment_ttl_hours: if a lead is in conversion but has no explicit
            conversion_deadline, use response_changed_at + assignment_ttl_hours
            as an implicit conversion window.

        For eligible leads:
          - delete LeadAssignment (if any)
          - clear assigned_to_user
          - assigned_for_conversion = False
          - conversion_deadline = None
          - add a story
        """
        db = SessionLocal()
        released = 0
        try:
            now = utcnow()

            # Only worked, non-client, non-deleted leads
            candidates = (
                db.query(Lead)
                .outerjoin(LeadAssignment, LeadAssignment.lead_id == Lead.id)
                .filter(
                    Lead.lead_response_id.isnot(None),   # worked
                    Lead.is_client.is_(False),
                    Lead.is_delete.is_(False),
                )
                .all()
            )

            for lead in candidates:
                try:
                    cfg, cfg_src = load_fetch_config_for_lead(db, lead)

                    # Normalize DB timestamps
                    response_changed_at = to_aware_utc(lead.response_changed_at)
                    conversion_deadline = to_aware_utc(lead.conversion_deadline)

                    # Need the moment when the response changed to compute windows
                    if not response_changed_at:
                        continue

                    # Conversion window checks
                    if lead.assigned_for_conversion:
                        if conversion_deadline:
                            # Explicit conversion deadline still in future → skip
                            if conversion_deadline > now:
                                continue
                        else:
                            # Implicit window using assignment_ttl_hours
                            implicit_deadline = response_changed_at + timedelta(
                                hours=getattr(cfg, "assignment_ttl_hours", 24)
                            )
                            if implicit_deadline > now:
                                continue  # still within implicit conversion window

                    # Worked lock window from response change
                    lock_cutoff = response_changed_at + timedelta(
                        days=getattr(cfg, "old_lead_remove_days", 30)
                    )
                    if lock_cutoff > now:
                        continue  # still in lock window

                    # Passed all checks → release to pool
                    assignment = (
                        db.query(LeadAssignment)
                        .filter(LeadAssignment.lead_id == lead.id)
                        .first()
                    )

                    prev_user_name = "Unknown User"
                    prev_user_code = "SYSTEM"
                    if assignment and assignment.user:
                        prev_user_name = assignment.user.name
                        prev_user_code = assignment.user.employee_code

                    if assignment:
                        db.delete(assignment)

                    lead.assigned_to_user = None
                    lead.assigned_for_conversion = False
                    lead.conversion_deadline = None

                    AddLeadStory(
                        lead.id,
                        "SYSTEM",
                        (
                            f"🔓 Lead released back to pool after lock window. "
                            f"(config: {cfg_src}, old_lead_remove_days={getattr(cfg,'old_lead_remove_days', None)}, "
                            f"assignment_ttl_hours={getattr(cfg,'assignment_ttl_hours', None)}). "
                            f"Previously with: {prev_user_name} ({prev_user_code})"
                        ),
                    )

                    released += 1

                except Exception as e:
                    logger.error("Error releasing worked lead %s: %s", lead.id, e, exc_info=True)
                    continue

            db.commit()
            logger.info("✅ Worked-lead release completed. Released %d leads", released)
            return released

        except Exception as e:
            logger.error("❌ Worked-lead release failed: %s", e, exc_info=True)
            db.rollback()
            return 0
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

            # 5. Hourly release of worked leads after lock window (config-aware)
            self.scheduler.add_job(
                func=self.release_worked_leads_after_lock_window,
                trigger=CronTrigger(minute=0),  # every hour at :00
                id="release_worked_leads",
                name="Release Worked Leads After Lock Window",
                replace_existing=True,
                misfire_grace_time=600,
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
            released_count = self.release_worked_leads_after_lock_window()
            stats = self.generate_daily_stats()

            result = {
                "manual_cleanup": True,
                "timestamp": utcnow().isoformat(),
                "results": {
                    "expired_leads_cleaned": expired_count,
                    "leads_marked_old": old_count,
                    "old_assignments_cleaned": assignment_count,
                    "worked_leads_released": released_count,
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
                "timestamp": utcnow().isoformat(),
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
                "current_time": utcnow().isoformat(),
            }

        except Exception as e:
            logger.error("Error getting scheduler status: %s", e, exc_info=True)
            return {
                "scheduler_running": False,
                "error": str(e),
                "current_time": utcnow().isoformat(),
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

    print("\n1. Testing expired conversion cleanup...")
    expired_count = manual_cleanup_expired_leads()
    print(f"Cleaned up {expired_count} expired leads")

    print("\n2. Testing old lead marking...")
    old_count = manual_mark_old_leads()
    print(f"Marked {old_count} leads as old")

    print("\n3. Testing worked-leads release...")
    released = lead_scheduler.release_worked_leads_after_lock_window()
    print(f"Released {released} worked leads")

    print("\n4. Testing scheduler status...")
    status = get_scheduler_status()
    print(f"Scheduler status: {status}")

    print("\n5. Testing manual cleanup...")
    result = lead_scheduler.run_cleanup_now()
    print(f"Manual cleanup result: {result}")

    print("\nAll tests completed!")
