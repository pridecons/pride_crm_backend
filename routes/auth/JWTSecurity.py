# routes/auth/JWTSecurity.py - Fixed token saving error

from datetime import datetime, timedelta
import uuid
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from db.models import UserDetails, TokenDetails
from config import JWT_SECRET_KEY, logger

# JWT configuration
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 540
REFRESH_TOKEN_EXPIRE_DAYS = 540


def create_access_token(data: dict, expires_delta: timedelta = None):
    """
    Generates an access token with an expiration time.
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "token_type": "access"})
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: str):
    """
    Generates a refresh token with a longer expiration time.
    """
    expires = timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": user_id, "exp": datetime.utcnow() + expires, "token_type": "refresh"},
        JWT_SECRET_KEY,
        algorithm=ALGORITHM
    )


def verify_token(token: str, db: Session = None):
    """
    Verifies a JWT (access or refresh).
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
        token_type = payload.get("token_type")
        user_id = payload.get("sub")
        if token_type not in ["access", "refresh"]:
            raise JWTError("Invalid token type")
        if not user_id:
            raise JWTError("Invalid token payload: missing user ID")
        return payload
    except JWTError as e:
        logger.error(f"Token verification failed: {str(e)}")
        return None


def save_refresh_token(db: Session, user_id: str, refresh_token: str):
    """
    Saves the refresh token in the database - FIXED VERSION
    """
    try:
        # Find user by employee_code (not phone_number)
        user = db.query(UserDetails).filter(UserDetails.employee_code == user_id).first()
        if not user:
            logger.error(f"Cannot save refresh token: User with employee_code {user_id} does not exist.")
            return

        # Check if token already exists for this user
        existing_token = db.query(TokenDetails).filter(TokenDetails.user_id == user_id).first()
        if existing_token:
            # Update existing token
            existing_token.refresh_token = refresh_token
            existing_token.created_at = datetime.utcnow()
        else:
            # Create new token
            new_token = TokenDetails(
                id=str(uuid.uuid4()), 
                user_id=user_id, 
                refresh_token=refresh_token
            )
            db.add(new_token)
        
        db.commit()
        logger.info(f"Refresh token saved successfully for user: {user_id}")
        
    except Exception as e:
        logger.error(f"Error saving refresh token: {str(e)}")
        db.rollback()


def revoke_refresh_token(db: Session, refresh_token: str):
    """
    Revokes (invalidates) the refresh token by deleting it from the database.
    """
    try:
        deleted_count = db.query(TokenDetails).filter(TokenDetails.refresh_token == refresh_token).delete()
        db.commit()
        logger.info(f"Revoked {deleted_count} refresh token(s)")
    except Exception as e:
        logger.error(f"Error revoking refresh token: {str(e)}")
        db.rollback()