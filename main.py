from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from contextlib import asynccontextmanager
import uvicorn
import logging
import os
from datetime import datetime, timedelta
# Import database
from db.connection import engine, check_database_connection
from db import models

# Import routes
from routes.auth import login, register
from routes.branch import branch

from scheduler import lead_scheduler

# Import for manual cleanup endpoint
from routes.auth.auth_dependency import get_current_user
from db.models import UserRoleEnum
from routes.Permission import permissions
from routes.leads import leads, lead_sources, bulk_leads, leads_fetch, fetch_config, lead_responses, assignments, lead_navigation, lead_recordings, lead_sharing, clients, lead_analytics, old_leads_fetch
from routes.auth.create_admin import create_admin
from routes.services import services
from routes.payments import Cashfree, Cashfree_webhook
from routes.Pan_verification import PanVerification
from routes.KYC import kyc_verification, redirect, View_Agreement
from routes.profile_role import ProfileRole
from routes.attendance import attendance
from routes.Rational import Rational
from routes.notification import notifiaction_websocket, send_notification
from routes.Send_client_message import Client_mail_service, sms_templates
from routes.notification.notification_scheduler import start_scheduler
from routes.payments import Get_Invoice, payment

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Starting CRM Backend...")
    
    try:
        # Start lead cleanup scheduler
        lead_scheduler.start()
        logger.info("✅ Lead cleanup scheduler started")
        logger.info("📅 Scheduled cleanup: Daily at 2:00 AM UTC")
        logger.info("📅 Scheduled old lead marking: Weekly Sunday at 3:00 AM UTC")
        
    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down CRM Backend...")
    lead_scheduler.stop()
    logger.info("✅ Shutdown completed")

# Initialize FastAPI app with lifespan
app = FastAPI(
    title="Pride CRM Backend API",
    description="Complete CRM Backend with User Management, Leads, and Branch Operations",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup():
    start_scheduler()

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Root endpoint
@app.get("/")
def read_root():
    return {
        "message": "Welcome to Pride CRM Backend API v1.0",
        "status": "active",
        "scheduler_running": lead_scheduler.scheduler.running,
        "docs": "/docs",
        "health": "/health"
    }

# Health check endpoint
@app.get("/health")
def health_check():
    try:
        db_status = check_database_connection()
        return {
            "status": "healthy" if db_status else "unhealthy",
            "database": "connected" if db_status else "disconnected",
            "scheduler_running": lead_scheduler.scheduler.running,
            "version": "1.0.0"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")

# Manual cleanup endpoints
@app.post("/api/v1/admin/cleanup-leads-now")
def cleanup_leads_manually(
    current_user = Depends(get_current_user)
):
    """Manual lead cleanup trigger - Admin only"""
    
    if current_user.role != UserRoleEnum.SUPERADMIN:
        raise HTTPException(403, "Only SUPERADMIN can trigger manual cleanup")
    
    try:
        result = lead_scheduler.run_cleanup_now()
        return {
            "message": result,
            "triggered_by": current_user.name,
            "triggered_at": datetime.utcnow(),
            "status": "success"
        }
    except Exception as e:
        logger.error(f"Manual cleanup failed: {e}")
        raise HTTPException(500, f"Cleanup failed: {str(e)}")

@app.get("/api/v1/admin/scheduler-status")
def get_scheduler_status(
    current_user = Depends(get_current_user)
):
    """Get scheduler status - Admin/Manager only"""
    
    if current_user.role not in [UserRoleEnum.SUPERADMIN, UserRoleEnum.BRANCH_MANAGER]:
        raise HTTPException(403, "Insufficient permissions")
    
    jobs_info = []
    for job in lead_scheduler.scheduler.get_jobs():
        jobs_info.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger)
        })
    
    return {
        "scheduler_running": lead_scheduler.scheduler.running,
        "total_jobs": len(jobs_info),
        "jobs": jobs_info,
        "current_time": datetime.utcnow().isoformat()
    }

# Register all your existing routes
try:
    app.include_router(payment.router, prefix="/api/v1")
    app.include_router(Get_Invoice.router, prefix="/api/v1")
    app.include_router(Rational.router, prefix="/api/v1")
    app.include_router(old_leads_fetch.router, prefix="/api/v1")
    app.include_router(sms_templates.router, prefix="/api/v1")
    app.include_router(lead_analytics.router, prefix="/api/v1")
    app.include_router(clients.router, prefix="/api/v1")
    app.include_router(lead_sharing.router, prefix="/api/v1")
    app.include_router(lead_recordings.router, prefix="/api/v1")
    app.include_router(View_Agreement.router, prefix="/api/v1")
    app.include_router(Client_mail_service.router, prefix="/api/v1")
    app.include_router(send_notification.router, prefix="/api/v1")
    app.include_router(notifiaction_websocket.router, prefix="/api/v1")
    app.include_router(Cashfree.router, prefix="/api/v1")
    # Authentication routes
    app.include_router(login.router, prefix="/api/v1")
    app.include_router(register.router, prefix="/api/v1")
    logger.info("✅ Auth routes registered")
    
    # Core business routes
    app.include_router(branch.router, prefix="/api/v1")
    app.include_router(permissions.router, prefix="/api/v1")
    logger.info("✅ Core business routes registered")
    
    # Lead management routes
    app.include_router(lead_sources.router, prefix="/api/v1")
    app.include_router(lead_responses.router, prefix="/api/v1")
    app.include_router(leads.router, prefix="/api/v1")
    app.include_router(bulk_leads.router, prefix="/api/v1")
    app.include_router(fetch_config.router, prefix="/api/v1")
    app.include_router(leads_fetch.router, prefix="/api/v1")
    app.include_router(assignments.router, prefix="/api/v1")
    app.include_router(lead_navigation.router, prefix="/api/v1")
    app.include_router(services.router, prefix="/api/v1")
    app.include_router(ProfileRole.router, prefix="/api/v1")
    app.include_router(PanVerification.router, prefix="/api/v1")
    app.include_router(kyc_verification.router, prefix="/api/v1")
    app.include_router(redirect.router, prefix="/api/v1")
    app.include_router(attendance.router, prefix="/api/v1")
    app.include_router(Cashfree_webhook.router, prefix="/api/v1")
    logger.info("✅ Lead management routes registered")
    
    # Add other routes...
    
except Exception as e:
    logger.error(f"Failed to register routes: {e}")
    raise

try:
    models.Base.metadata.create_all(engine)
    logger.info("Tables created successfully!")
except Exception as e:
    logger.error(f"Error creating tables: {e}", exc_info=True)

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Global exception: {exc}")
    return {
        "error": "Internal server error",
        "detail": str(exc) if app.debug else "Something went wrong"
    }

# Run the application
if __name__ == "__main__":
    logger.info("🚀 Starting server with Uvicorn...")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

