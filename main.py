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
from routes.Permission import permissions
from routes.leads import leads, lead_sources, bulk_leads, leads_fetch, fetch_config, lead_responses, assignments, lead_navigation, lead_recordings, clients, lead_analytics, old_leads_fetch
# from routes.auth.create_admin import create_admin
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
from db.complete_initialization import setup_complete_system

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("🚀 Starting CRM Backend...")
    
    try:
        lead_scheduler.start()
        # Initialize FastAPI Cache
        FastAPICache.init(
            backend=InMemoryBackend(),
            prefix="fastapi-cache"
        )
        logger.info("✅ Cache initialized")
        
        # Check database connection
        if not check_database_connection():
            logger.error("❌ Database connection failed!")
            raise Exception("Database connection failed")
        logger.info("✅ Database connection verified")
        
        # Create database tables
        models.Base.metadata.create_all(engine)
        logger.info("✅ Database tables created/verified")
        
        # SINGLE FUNCTION CALL - This will create everything
        if setup_complete_system():
            logger.info("✅ Complete system setup successful!")
        else:
            logger.error("❌ System setup failed!")
        
        # Create static directories
        os.makedirs("static/agreements", exist_ok=True)
        os.makedirs("static/lead_documents", exist_ok=True)
        logger.info("✅ Static directories created")
        
        logger.info("🎉 Application startup completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Application startup failed: {str(e)}")
        raise e
    
    yield
    
    # Shutdown
    lead_scheduler.stop()
    logger.info("🛑 Shutting down CRM Backend...")



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

# Register all your existing routes
try:
    app.include_router(ProfileRole.departments_router, prefix="/api/v1")
    app.include_router(ProfileRole.profiles_router, prefix="/api/v1")
    app.include_router(register.router, prefix="/api/v1")
    app.include_router(login.router, prefix="/api/v1")
    app.include_router(payment.router, prefix="/api/v1")
    app.include_router(Get_Invoice.router, prefix="/api/v1")
    app.include_router(Rational.router, prefix="/api/v1")
    app.include_router(old_leads_fetch.router, prefix="/api/v1")
    app.include_router(sms_templates.router, prefix="/api/v1")
    app.include_router(lead_analytics.router, prefix="/api/v1")
    app.include_router(clients.router, prefix="/api/v1")
    app.include_router(lead_recordings.router, prefix="/api/v1")
    app.include_router(View_Agreement.router, prefix="/api/v1")
    app.include_router(Client_mail_service.router, prefix="/api/v1")
    app.include_router(send_notification.router, prefix="/api/v1")
    app.include_router(notifiaction_websocket.router, prefix="/api/v1")
    app.include_router(Cashfree.router, prefix="/api/v1")
    # Authentication routes
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

