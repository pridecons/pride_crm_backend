# routes/auth/login.py - Fixed version with proper password verification

from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DisconnectionError
import hashlib
import bcrypt

from db.connection import get_db
from db.models import UserDetails, TokenDetails, UserRoleEnum
from db.Schema.login import TokenResponse, RefreshTokenRequest, LoginRequest, UserInfoResponse
from routes.auth.JWTSecurity import (
    create_access_token,
    create_refresh_token,
    save_refresh_token,
    revoke_refresh_token,
    verify_token,
)

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password with bcrypt or fallback method"""
    try:
        # Try bcrypt first
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception as e:
        # Fallback to SHA-256
        print(f"Bcrypt verify error, falling back to SHA-256: {e}")
        return hashlib.sha256(plain_password.encode()).hexdigest() == hashed_password


@router.post("/login", response_model=TokenResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """
    Authenticate user and issue access + refresh tokens.
    Username can be phone_number or email.
    """
    try:
        # Try to find user by phone number first, then by email
        user = None
        
        # Check if username looks like email
        if "@" in form_data.username:
            user = db.query(UserDetails).filter(
                UserDetails.email == form_data.username
            ).first()
        else:
            # Try phone number
            user = db.query(UserDetails).filter(
                UserDetails.phone_number == form_data.username
            ).first()
        
        # If not found by phone, try email as fallback
        if not user:
            user = db.query(UserDetails).filter(
                UserDetails.email == form_data.username
            ).first()

        # Validate user and password
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not verify_password(form_data.password, user.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Check if user is active
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is deactivated. Contact administrator.",
            )

        # Create tokens - use employee_code as user identifier
        access_token = create_access_token({
            "sub": user.employee_code,  # Use employee_code instead of phone
            "role": user.role.value,
            "branch_id": user.branch_id
        })
        refresh_token = create_refresh_token(user.employee_code)  # Use employee_code

        # Persist refresh token
        save_refresh_token(db, user.employee_code, refresh_token)

        # Prepare user info
        user_info = {
            "employee_code": user.employee_code,
            "name": user.name,
            "email": user.email,
            "phone_number": user.phone_number,
            "role": user.role.value,
            "branch_id": user.branch_id,
            "is_active": user.is_active,
            "branch_name": user.branch.name if user.branch else None,
            "permissions": {}
        }

        # Get user permissions
        if user.permission:
            user_info["permissions"] = (
                {key: getattr(user.permission, key) for key in vars(user.permission) if not key.startswith("_")}
                if user.permission else {}
            )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user_info=user_info
        )

    except HTTPException:
        raise
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login failed: {str(e)}"
        )


# Keep all other endpoints the same...
@router.post("/refresh", response_model=TokenResponse)
def refresh_token(
    body: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    """Given a valid refresh token, issue a new access + refresh pair."""
    try:
        payload = verify_token(body.refresh_token, db=db)
        if not payload or payload.get("token_type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            )

        # Check if refresh token exists in database
        token_in_db = (
            db.query(TokenDetails)
            .filter(TokenDetails.refresh_token == body.refresh_token)
            .first()
        )
        if not token_in_db:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token revoked or not found",
            )

        # Get user info
        user_id = payload.get("sub")
        user = db.query(UserDetails).filter(
            UserDetails.employee_code == user_id
        ).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is deactivated",
            )

        # Create new tokens
        access_token = create_access_token({
            "sub": user.employee_code,
            "role": user.role.value,
            "branch_id": user.branch_id
        })
        new_refresh_token = create_refresh_token(user_id)
        
        # Save new refresh token and revoke old one
        revoke_refresh_token(db, body.refresh_token)
        save_refresh_token(db, user_id, new_refresh_token)

        # Prepare user info
        user_info = {
            "employee_code": user.employee_code,
            "name": user.name,
            "email": user.email,
            "phone_number": user.phone_number,
            "role": user.role.value,
            "branch_id": user.branch_id,
            "is_active": user.is_active,
        }

        return TokenResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            user_info=user_info
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Token refresh failed: {str(e)}"
        )
    
    