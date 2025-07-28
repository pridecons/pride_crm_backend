# db/connection.py - FIXED for SQLAlchemy 2.0

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.engine import Engine
from urllib.parse import quote_plus
from dotenv import load_dotenv
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Database configuration with defaults
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "crm_db")
DB_USERNAME = os.getenv("DB_USERNAME", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")

# Ensure password is string and quote it properly
if isinstance(DB_PASSWORD, (bytes, bytearray)):
    DB_PASSWORD = DB_PASSWORD.decode("utf-8")

# Quote password for URL safety
pw_quoted = quote_plus(str(DB_PASSWORD))

# Build DATABASE_URL with proper error handling
try:
    DATABASE_URL = (
        f"postgresql://{DB_USERNAME}:{pw_quoted}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}?sslmode=disable"
    )
    logger.info(f"Database URL constructed for: {DB_USERNAME}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
except Exception as e:
    logger.error(f"Error constructing database URL: {e}")
    raise

# Create engine with proper configuration
engine = create_engine(
    DATABASE_URL,
    echo=False,  # Set to True for SQL debugging
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Validate connections before use
    pool_recycle=3600,   # Recycle connections every hour
    connect_args={
        "application_name": "CRM_Backend",
        "connect_timeout": 10,
    }
)

# Add connection event listeners for better error handling
@event.listens_for(Engine, "connect")
def set_connection_settings(dbapi_connection, connection_record):
    """Configure connection settings"""
    try:
        # Set timezone to UTC
        with dbapi_connection.cursor() as cursor:
            cursor.execute("SET timezone TO 'UTC'")
            dbapi_connection.commit()
    except Exception as e:
        logger.warning(f"Could not set timezone: {e}")

@event.listens_for(Engine, "checkout")
def receive_checkout(dbapi_connection, connection_record, connection_proxy):
    """Log when connection is checked out"""
    logger.debug("Connection checked out from pool")

# Session factory
SessionLocal = sessionmaker(
    autocommit=False, 
    autoflush=False, 
    bind=engine
)

# Base class for models
Base = declarative_base()

# Improved dependency for FastAPI routes
def get_db():
    """
    Database dependency with proper error handling
    """
    db = None
    try:
        db = SessionLocal()
        yield db
    except Exception as e:
        logger.error(f"Database session error: {e}")
        if db:
            db.rollback()
        raise
    finally:
        if db:
            db.close()

# Health check function - FIXED for SQLAlchemy 2.0
def check_database_connection():
    """
    Check if database connection is working
    """
    try:
        db = SessionLocal()
        # Use text() for raw SQL in SQLAlchemy 2.0
        result = db.execute(text("SELECT 1 as test"))
        test_value = result.fetchone()
        db.close()
        
        if test_value and test_value[0] == 1:
            logger.info("✅ Database connection successful")
            return True
        else:
            logger.error("❌ Database query returned unexpected result")
            return False
            
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False

# Alternative health check using engine directly
def check_database_connection_engine():
    """
    Alternative database health check using engine directly
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1 as test"))
            test_value = result.fetchone()
            
        if test_value and test_value[0] == 1:
            logger.info("✅ Database engine connection successful")
            return True
        else:
            logger.error("❌ Database engine query returned unexpected result")
            return False
            
    except Exception as e:
        logger.error(f"Database engine health check failed: {e}")
        return False

# Test database with detailed error info
def test_database_connection():
    """
    Detailed database connection test
    """
    logger.info("🔍 Testing database connection...")
    
    try:
        # Test 1: Basic connection
        logger.info("Test 1: Basic engine connection...")
        with engine.connect() as conn:
            logger.info("✅ Engine connection successful")
        
        # Test 2: Simple query
        logger.info("Test 2: Simple query test...")
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.fetchone()
            logger.info(f"✅ Database version: {version[0][:50]}...")
        
        # Test 3: Session test
        logger.info("Test 3: Session test...")
        db = SessionLocal()
        result = db.execute(text("SELECT current_database(), current_user"))
        db_info = result.fetchone()
        logger.info(f"✅ Connected to database: {db_info[0]} as user: {db_info[1]}")
        db.close()
        
        logger.info("🎉 All database tests passed!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Database test failed: {e}")
        logger.error(f"Database URL: postgresql://{DB_USERNAME}:***@{DB_HOST}:{DB_PORT}/{DB_NAME}")
        return False


import os
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
import socket

# Force IPv4 resolution
def force_ipv4_connection():
    """Force IPv4 connection by resolving hostname"""
    hostname = os.getenv('DB_HOST', '194.238.18.167')
    try:
        # Get IPv4 address explicitly
        ipv4_addr = socket.getaddrinfo(hostname, None, socket.AF_INET)[0][4][0]
        return ipv4_addr
    except:
        return hostname

# Database configuration with forced IPv4
DB_HOST = force_ipv4_connection()
DB_PORT = os.getenv('DB_PORT', 5432)
DB_USER = os.getenv('DB_USER', 'pridecons')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_NAME = os.getenv('DB_NAME', 'pridedb')

# Construct database URL with explicit IPv4
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Create engine with connection pooling and IPv4 settings
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=3600,
    pool_pre_ping=True,
    connect_args={
        "connect_timeout": 15,
        "application_name": "pride_crm_backend",
        "options": "-c timezone=UTC"
    },
    echo=False
)

def check_database_connection(retry_count=3, retry_delay=5):
    """Check database connection with retries"""
    import time
    import logging
    
    logger = logging.getLogger(__name__)
    
    for attempt in range(retry_count):
        try:
            with engine.connect() as connection:
                result = connection.execute(text("SELECT 1"))
                logger.info(f"✅ Database connection successful on attempt {attempt + 1}")
                return True
                
        except Exception as e:
            logger.error(f"❌ Database connection attempt {attempt + 1} failed: {str(e)}")
            if attempt < retry_count - 1:
                logger.info(f"⏳ Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.error(f"❌ All {retry_count} connection attempts failed")
                return False
    
    return False

import psycopg2
import socket
import os

# Force IPv4 resolution
def get_ipv4_address(hostname):
    try:
        return socket.getaddrinfo(hostname, None, socket.AF_INET)[0][4][0]
    except:
        return hostname

db_host = get_ipv4_address('194.238.18.167')
print(f"Connecting to IPv4 address: {db_host}")

try:
    conn = psycopg2.connect(
        host=db_host,
        port=5432,
        user='pridecons',
        password='your_password',  # Replace with actual password
        database='pridedb',
        connect_timeout=10
    )
    print("✅ Direct Python connection successful!")
    
    cursor = conn.cursor()
    cursor.execute("SELECT version();")
    result = cursor.fetchone()
    print(f"Database version: {result[0]}")
    
    conn.close()
    
except Exception as e:
    print(f"❌ Direct Python connection failed: {e}")

    