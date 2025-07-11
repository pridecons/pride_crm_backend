from datetime import datetime, timedelta
import uuid
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from db.models import UserDetails, TokenDetails  # Ensure UserDetails now has a 'password' field.e_phone
from config import JWT_SECRET_KEY, logger

# JWT configuration
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 540
REFRESH_TOKEN_EXPIRE_DAYS = 540


# ---------------------------------------
# JWT Helper Functions
# ---------------------------------------

def create_access_token(data: dict, expires_delta: timedelta = None):
    """
    Generates an access token with an expiration time.
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    # Include token type to differentiate access vs refresh
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
    Verifies a JWT (access or refresh). If db is provided, you can additionally check
    for refresh token revocation.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
        token_type = payload.get("token_type")
        user_id = payload.get("sub")
        if token_type not in ["access", "refresh"]:
            raise JWTError("Invalid token type")
        if not user_id:
            raise JWTError("Invalid token payload: missing user ID")
        # Optionally: check in DB if token is revoked (for refresh tokens)
        return payload
    except JWTError as e:
        logger.error(f"Token verification failed: {str(e)}")
        return None


def save_refresh_token(db: Session, user_id: str, refresh_token: str):
    """
    Saves the refresh token in the database. If a token exists, it updates it.
    """
    user = db.query(UserDetails).filter(UserDetails.phone_number == user_id).first()
    if not user:
        logger.error(f"Cannot save refresh token: User with phone {user_id} does not exist.")
        return

    existing_token = db.query(TokenDetails).filter(TokenDetails.user_id == user_id).first()
    if existing_token:
        existing_token.refresh_token = refresh_token
        existing_token.created_at = datetime.utcnow()
    else:
        new_token = TokenDetails(id=str(uuid.uuid4()), user_id=user_id, refresh_token=refresh_token)
        db.add(new_token)
    db.commit()


def revoke_refresh_token(db: Session, refresh_token: str):
    """
    Revokes (invalidates) the refresh token by deleting it from the database.
    """
    db.query(TokenDetails).filter(TokenDetails.refresh_token == refresh_token).delete()
    db.commit()
