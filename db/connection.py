# Update your db/connection.py to handle special characters in passwords

import os
import urllib.parse
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool
import logging

logger = logging.getLogger(__name__)

def url_encode_password(password):
    """URL encode password to handle special characters"""
    if password:
        return urllib.parse.quote(password)
    return password

def construct_database_url():
    """Construct database URL with proper password encoding"""
    try:
        DB_HOST = os.getenv('DB_HOST', '194.238.18.167')
        DB_PORT = int(os.getenv('DB_PORT', 5432))
        DB_USER = os.getenv('DB_USER', 'pridecons')
        DB_PASSWORD = os.getenv('DB_PASSWORD')
        DB_NAME = os.getenv('DB_NAME', 'pridedb')

        if not DB_PASSWORD:
            raise ValueError("DB_PASSWORD environment variable is required")

        # Check if password is already URL encoded
        if '%' in DB_PASSWORD:
            # Password is already encoded
            encoded_password = DB_PASSWORD
            logger.info("Using pre-encoded password from environment")
        else:
            # Encode the password
            encoded_password = url_encode_password(DB_PASSWORD)
            logger.info("URL-encoded password for database connection")

        # Construct database URL
        database_url = f"postgresql://{DB_USER}:{encoded_password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        
        logger.info(f"Database URL constructed for: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
        return database_url

    except Exception as e:
        logger.error(f"Failed to construct database URL: {e}")
        raise

# Initialize database connection
try:
    DATABASE_URL = construct_database_url()

    # Create engine with robust connection settings
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

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()

    logger.info("✅ Database engine initialized successfully")

except Exception as e:
    logger.error(f"❌ Failed to initialize database engine: {e}")
    engine = None
    SessionLocal = None
    Base = declarative_base()

def get_db():
    """Get database session with error handling"""
    if not engine:
        raise Exception("Database engine not initialized")
    
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        db.rollback()
        logger.error(f"Database session error: {e}")
        raise
    finally:
        db.close()

def check_database_connection(retry_count=3, retry_delay=5):
    """Check database connection with retries"""
    if not engine:
        logger.error("Database engine not initialized")
        return False
    
    import time
    
    for attempt in range(retry_count):
        try:
            with engine.connect() as connection:
                result = connection.execute(text("SELECT 1"))
                logger.info("✅ Database connection successful")
                return True
                
        except Exception as e:
            logger.error(f"❌ Database connection attempt {attempt + 1} failed: {e}")
            if attempt < retry_count - 1:
                logger.info(f"⏳ Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
    
    logger.error(f"❌ Database connection failed after {retry_count} attempts")
    return False

# Alternative connection method using individual parameters (no URL encoding needed)
def create_engine_with_params():
    """Alternative method: Create engine using individual connection parameters"""
    try:
        from sqlalchemy.engine.url import URL
        
        url = URL.create(
            drivername="postgresql",
            username=os.getenv('DB_USER', 'pridecons'),
            password=os.getenv('DB_PASSWORD'),  # Raw password, no encoding needed
            host=os.getenv('DB_HOST', '194.238.18.167'),
            port=int(os.getenv('DB_PORT', 5432)),
            database=os.getenv('DB_NAME', 'pridedb')
        )
        
        return create_engine(
            url,
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
        
    except Exception as e:
        logger.error(f"Failed to create engine with params: {e}")
        return None