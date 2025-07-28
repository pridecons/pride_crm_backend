from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from contextlib import asynccontextmanager
import uvicorn
import logging
import os

# Import database
from db.connection import engine, check_database_connection
from db import models

# Import routes
from routes.auth import login, register
from routes.branch import branch
from routes.Permission import permissions
from routes.leads import leads, lead_sources, bulk_leads, leads_fetch, fetch_config, lead_responses, assignments, lead_navigation, lead_recordings, lead_sharing, clients, lead_analytics
from routes.auth.create_admin import create_admin
from routes.services import services
from routes.payments import Cashfree
from routes.Pan_verification import PanVerification
from routes.KYC import kyc_verification, redirect, View_Agreement
from routes.profile_role import ProfileRole
from routes.attendance import attendance
from routes.Rational import Rational
from routes.notification import notifiaction_websocket, send_notification
from routes.Send_client_message import Client_mail_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# CORS origins
origins = [
    "http://localhost:3000",
    "http://localhost:3001", 
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "*"  # Remove this in production
]

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting CRM Backend...")
    
    try:
        # Initialize cache
        FastAPICache.init(InMemoryBackend(), prefix="fastapi-cache")
        logger.info("✅ Cache initialized")
        
        # Try database connection but don't fail if it doesn't work
        try:
            if check_database_connection():
                logger.info("✅ Database connection verified")
                models.Base.metadata.create_all(engine)
                create_admin()
                logger.info("✅ Database setup completed")
            else:
                logger.warning("⚠️ Database connection failed - starting anyway")
        except Exception as db_error:
            logger.error(f"Database error: {db_error}")
            logger.warning("⚠️ Starting without database connection")
        
        # Create directories
        os.makedirs("static/agreements", exist_ok=True)
        os.makedirs("static/lead_documents", exist_ok=True)
        
        logger.info("🎉 Application startup completed!")
        yield
        
    except Exception as e:
        logger.error(f"Startup error: {e}")
        yield  # Start anyway
        
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

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Root endpoint
@app.get("/")
def read_root():
    """Root endpoint with API information"""
    return {
        "message": "Welcome to Pride CRM Backend API v1.0",
        "status": "active",
        "docs": "/docs",
        "health": "/health"
    }

# Health check endpoint
@app.get("/health")
def health_check():
    """Health check endpoint"""
    try:
        db_status = check_database_connection()
        return {
            "status": "healthy" if db_status else "unhealthy",
            "database": "connected" if db_status else "disconnected",
            "version": "1.0.0"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")

# Register all routes with proper error handling
try:
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
    app.include_router(Rational.router, prefix="/api/v1")
    app.include_router(attendance.router, prefix="/api/v1")
    logger.info("✅ Lead management routes registered")
    
except Exception as e:
    logger.error(f"❌ Error registering routes: {e}")
    raise

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

