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
from db.models import Lead, LeadAssignment, UserDetails
from utils.AddLeadStory import AddLeadStory

logger = logging.getLogger(__name__)

# Create session factory
SessionLocal = sessionmaker(bind=engine)

class LeadCleanupScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.setup_jobs()
    
    def cleanup_expired_conversion_leads(self):
        """
        Clean up expired conversion leads (Point 8 & 9)
        Remove leads that exceeded conversion deadline without becoming clients
        """
        db = SessionLocal()
        cleanup_count = 0
        
        try:
            logger.info("🔄 Starting lead cleanup process...")
            
            # Find leads that have exceeded conversion deadline
            expired_leads = db.query(Lead).filter(
                and_(
                    Lead.assigned_for_conversion == True,
                    Lead.conversion_deadline < datetime.utcnow(),
                    Lead.is_client == False,  # Not converted to client
                    Lead.is_delete == False   # Not deleted
                )
            ).all()
            
            logger.info(f"Found {len(expired_leads)} expired conversion leads")
            
            for lead in expired_leads:
                try:
                    # Find assignment
                    assignment = db.query(LeadAssignment).filter_by(
                        lead_id=lead.id
                    ).first()
                    
                    user_name = "Unknown User"
                    user_code = "SYSTEM"
                    
                    if assignment and assignment.user:
                        user_name = assignment.user.name
                        user_code = assignment.user.employee_code
                        
                        # Calculate how many days lead was assigned
                        days_assigned = 0
                        if lead.response_changed_at:
                            days_assigned = (datetime.utcnow() - lead.response_changed_at).days
                        
                        # Add story before removal
                        AddLeadStory(
                            lead.id,
                            "SYSTEM",
                            f"⏰ Lead removed from {user_name} ({user_code}) due to "
                            f"conversion deadline expiry. Was assigned for {days_assigned} days "
                            f"without client conversion. Lead returned to pool."
                        )
                        
                        # Delete assignment
                        db.delete(assignment)
                    
                    # Reset lead conversion fields
                    lead.assigned_for_conversion = False
                    lead.assigned_to_user = None
                    lead.conversion_deadline = None
                    # Keep is_old_lead = True for old lead fetch API
                    
                    cleanup_count += 1
                    logger.info(f"Cleaned up lead {lead.id} from user {user_name}")
                    
                except Exception as e:
                    logger.error(f"Error cleaning up lead {lead.id}: {e}")
                    continue
            
            # Commit all changes
            db.commit()
            
            logger.info(f"✅ Lead cleanup completed successfully. "
                       f"Cleaned up {cleanup_count} expired conversion leads")
            
            return cleanup_count
            
        except Exception as e:
            logger.error(f"❌ Lead cleanup failed: {e}")
            db.rollback()
            return 0
            
        finally:
            db.close()
    
    def cleanup_long_unassigned_leads(self):
        """
        Mark old unassigned leads as old leads
        For leads that haven't been assigned for 6+ months
        """
        db = SessionLocal()
        marked_count = 0
        
        try:
            logger.info("🔄 Starting old lead marking process...")
            
            # Find leads older than 6 months with no assignment
            six_months_ago = datetime.utcnow() - timedelta(days=180)
            
            old_unassigned_leads = db.query(Lead).outerjoin(LeadAssignment).filter(
                and_(
                    Lead.created_at < six_months_ago,
                    Lead.is_client == False,
                    Lead.is_delete == False,
                    Lead.is_old_lead == False,  # Only mark if not already old
                    LeadAssignment.id == None  # No assignment
                )
            ).all()
            
            logger.info(f"Found {len(old_unassigned_leads)} long unassigned leads to mark as old")
            
            for lead in old_unassigned_leads:
                try:
                    # Mark as old lead
                    lead.is_old_lead = True
                    
                    # Add story
                    AddLeadStory(
                        lead.id,
                        "SYSTEM",
                        f"📅 Lead marked as old due to 6+ months without assignment. "
                        f"Created on: {lead.created_at.strftime('%Y-%m-%d')}"
                    )
                    
                    marked_count += 1
                    logger.info(f"Marked lead {lead.id} as old lead")
                    
                except Exception as e:
                    logger.error(f"Error marking lead {lead.id} as old: {e}")
                    continue
            
            db.commit()
            logger.info(f"✅ Old lead marking completed. Marked {marked_count} leads as old")
            
            return marked_count
            
        except Exception as e:
            logger.error(f"❌ Old lead marking failed: {e}")
            db.rollback()
            return 0
        finally:
            db.close()
    
    def cleanup_very_old_assignments(self):
        """
        Optional: Clean up assignments that are very old (30+ days)
        This prevents assignments from staying forever
        """
        db = SessionLocal()
        cleaned_count = 0
        
        try:
            logger.info("🔄 Starting very old assignment cleanup...")
            
            # Find assignments older than 30 days
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            
            old_assignments = db.query(LeadAssignment).filter(
                LeadAssignment.fetched_at < thirty_days_ago
            ).all()
            
            logger.info(f"Found {len(old_assignments)} very old assignments")
            
            for assignment in old_assignments:
                try:
                    # Add story before deleting
                    if assignment.lead and assignment.user:
                        AddLeadStory(
                            assignment.lead_id,
                            "SYSTEM",
                            f"📅 Assignment removed due to 30+ days inactivity. "
                            f"Was assigned to: {assignment.user.name}"
                        )
                    
                    db.delete(assignment)
                    cleaned_count += 1
                    
                except Exception as e:
                    logger.error(f"Error cleaning old assignment {assignment.id}: {e}")
                    continue
            
            db.commit()
            logger.info(f"✅ Very old assignment cleanup completed. Cleaned {cleaned_count} assignments")
            
            return cleaned_count
            
        except Exception as e:
            logger.error(f"❌ Very old assignment cleanup failed: {e}")
            db.rollback()
            return 0
        finally:
            db.close()
    
    def generate_daily_stats(self):
        """
        Optional: Generate daily statistics for monitoring
        """
        db = SessionLocal()
        
        try:
            today = datetime.utcnow().date()
            
            # Count various lead stats
            total_leads = db.query(Lead).filter(Lead.is_delete == False).count()
            
            active_assignments = db.query(LeadAssignment).filter(
                LeadAssignment.fetched_at >= datetime.utcnow() - timedelta(days=7)
            ).count()
            
            conversion_pending = db.query(Lead).filter(
                and_(
                    Lead.assigned_for_conversion == True,
                    Lead.is_client == False,
                    Lead.conversion_deadline > datetime.utcnow()
                )
            ).count()
            
            clients_today = db.query(Lead).filter(
                and_(
                    Lead.is_client == True,
                    Lead.updated_at >= today
                )
            ).count()
            
            logger.info(f"📊 Daily Stats - Total Leads: {total_leads}, "
                       f"Active Assignments: {active_assignments}, "
                       f"Conversion Pending: {conversion_pending}, "
                       f"New Clients Today: {clients_today}")
            
            return {
                "date": today.isoformat(),
                "total_leads": total_leads,
                "active_assignments": active_assignments,
                "conversion_pending": conversion_pending,
                "new_clients_today": clients_today
            }
            
        except Exception as e:
            logger.error(f"Error generating daily stats: {e}")
            return {}
        finally:
            db.close()
    
    def setup_jobs(self):
        """Setup all scheduled jobs"""
        try:
            # 1. Daily cleanup at 2 AM UTC
            self.scheduler.add_job(
                func=self.cleanup_expired_conversion_leads,
                trigger=CronTrigger(hour=2, minute=0),
                id='cleanup_expired_leads',
                name='Cleanup Expired Conversion Leads',
                replace_existing=True,
                misfire_grace_time=600  # 10 minutes grace time
            )
            
            # 2. Weekly cleanup on Sunday at 3 AM UTC
            self.scheduler.add_job(
                func=self.cleanup_long_unassigned_leads,
                trigger=CronTrigger(hour=3, minute=0, day_of_week=0),  # Sunday = 0
                id='cleanup_old_leads',
                name='Mark Long Unassigned Leads as Old',
                replace_existing=True,
                misfire_grace_time=1800  # 30 minutes grace time
            )
            
            # 3. Monthly cleanup on 1st at 4 AM UTC
            self.scheduler.add_job(
                func=self.cleanup_very_old_assignments,
                trigger=CronTrigger(hour=4, minute=0, day=1),  # 1st of month
                id='cleanup_very_old_assignments',
                name='Cleanup Very Old Assignments',
                replace_existing=True,
                misfire_grace_time=1800
            )
            
            # 4. Daily stats at 11:59 PM UTC
            self.scheduler.add_job(
                func=self.generate_daily_stats,
                trigger=CronTrigger(hour=23, minute=59),
                id='daily_stats',
                name='Generate Daily Statistics',
                replace_existing=True,
                misfire_grace_time=300  # 5 minutes grace time
            )
            
            logger.info("📅 All scheduled jobs configured successfully")
            
        except Exception as e:
            logger.error(f"Error setting up scheduled jobs: {e}")
    
    def start(self):
        """Start the scheduler"""
        try:
            self.scheduler.start()
            logger.info("🚀 Lead cleanup scheduler started successfully")
            
            # Log next run times
            jobs = self.scheduler.get_jobs()
            for job in jobs:
                logger.info(f"📅 Job '{job.name}' next run: {job.next_run_time}")
            
            # Shutdown scheduler gracefully on exit
            atexit.register(lambda: self.shutdown())
            
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
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
            logger.error(f"Error stopping scheduler: {e}")
    
    def shutdown(self):
        """Graceful shutdown"""
        self.stop()
    
    def run_cleanup_now(self):
        """Run cleanup immediately for testing"""
        logger.info("🔄 Running manual cleanup...")
        
        try:
            # Run all cleanup tasks
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
                    "stats": stats
                }
            }
            
            logger.info(f"✅ Manual cleanup completed: {result}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Manual cleanup failed: {e}")
            return {
                "manual_cleanup": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    def get_status(self):
        """Get scheduler status"""
        try:
            jobs_info = []
            
            if self.scheduler.running:
                for job in self.scheduler.get_jobs():
                    jobs_info.append({
                        "id": job.id,
                        "name": job.name,
                        "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                        "trigger": str(job.trigger),
                        "misfire_grace_time": getattr(job, 'misfire_grace_time', None)
                    })
            
            return {
                "scheduler_running": self.scheduler.running,
                "total_jobs": len(jobs_info),
                "jobs": jobs_info,
                "current_time": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting scheduler status: {e}")
            return {
                "scheduler_running": False,
                "error": str(e),
                "current_time": datetime.utcnow().isoformat()
            }
    
    def pause_job(self, job_id: str):
        """Pause a specific job"""
        try:
            self.scheduler.pause_job(job_id)
            logger.info(f"⏸️ Job '{job_id}' paused")
            return True
        except Exception as e:
            logger.error(f"Error pausing job {job_id}: {e}")
            return False
    
    def resume_job(self, job_id: str):
        """Resume a specific job"""
        try:
            self.scheduler.resume_job(job_id)
            logger.info(f"▶️ Job '{job_id}' resumed")
            return True
        except Exception as e:
            logger.error(f"Error resuming job {job_id}: {e}")
            return False


# Global scheduler instance
lead_scheduler = LeadCleanupScheduler()


# Standalone functions for direct usage
def manual_cleanup_expired_leads():
    """Direct function to cleanup expired leads"""
    return lead_scheduler.cleanup_expired_conversion_leads()

def manual_mark_old_leads():
    """Direct function to mark old leads"""
    return lead_scheduler.cleanup_long_unassigned_leads()

def get_scheduler_status():
    """Get current scheduler status"""
    return lead_scheduler.get_status()


# For testing purposes
if __name__ == "__main__":
    # Test the scheduler
    print("Testing Lead Cleanup Scheduler...")
    
    # Test cleanup functions
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