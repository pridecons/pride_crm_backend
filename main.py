from fastapi import FastAPI
import uvicorn
import logging
import threading
import time
import schedule
from fastapi.middleware.cors import CORSMiddleware
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from db.connection import engine
from db import models
from fastapi.staticfiles import StaticFiles

#routes
from routes.auth import login, register
from routes.branch import branch
from routes.Permission import permissions
from routes.leads import leads, lead_sources, bulk_leads
from routes.auth.create_admin import create_admin


# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Allowed Origins for CORS
origins = [
    "*"
]

# Initialize FastAPI app
app = FastAPI()

# Add CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins= origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.on_event("startup")
async def on_startup():
    FastAPICache.init(
        backend=InMemoryBackend(),     # or RedisBackend(...) if you prefer
        prefix="fastapi-cache"         # optional; used to namespace your keys
    )
    create_admin()

# Root API Endpoint
@app.get("/")
def read_root():
    return {"message": "Welcome to Pride Backend API v1"}


# Registering Routes
app.include_router(login.router)
app.include_router(register.router)
app.include_router(branch.router)
app.include_router(permissions.router)
app.include_router(leads.router)
app.include_router(lead_sources.router)
app.include_router(bulk_leads.router)


# Database Table Creation
try:
    models.Base.metadata.create_all(engine)
    logger.info("Tables created successfully!")
except Exception as e:
    logger.error(f"Error creating tables: {e}", exc_info=True)


# Run FastAPI with Uvicorn
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)





