from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from urllib.parse import quote_plus
from dotenv import load_dotenv
import os

# load .env into os.environ
load_dotenv()

# Fetch with sensible defaults
DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = os.getenv("DB_PORT", "5432")
DB_NAME     = os.getenv("DB_NAME", "")
DB_USERNAME = os.getenv("DB_USERNAME", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

# If somehow loaded as bytes, decode to str
if isinstance(DB_PASSWORD, (bytes, bytearray)):
    DB_PASSWORD = DB_PASSWORD.decode("utf-8")

# Quote the password for URL safety
pw_quoted = quote_plus(DB_PASSWORD)

# Build the SQLAlchemy URL
DATABASE_URL = (
    f"postgresql://{DB_USERNAME}:{pw_quoted}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# Create engine
engine = create_engine(DATABASE_URL, echo=True)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()

# Dependency for FastAPI routes
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
