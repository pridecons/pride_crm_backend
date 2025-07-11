# routes/auth/login.py

from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DisconnectionError
from passlib.context import CryptContext
import hashlib

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

# Password context with fallback
try:
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
except ImportError:
    pwd_context = None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password with bcrypt or fallback method"""
    if pwd_context:
        return pwd_context.verify(plain_password, hashed_password)
    else:
        # Fallback verification
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

        # Create tokens
        access_token = create_access_token({
            "sub": user.employee_code,
            "role": user.role.value,
            "branch_id": user.branch_id
        })
        refresh_token = create_refresh_token(user.employee_code)

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
            "manager_name": user.manager.name if user.manager else None,
            "permissions": {}
        }

        # Get user permissions
        if user.permission:
            user_info["permissions"] = {
                "add_user": user.permission.add_user,
                "edit_user": user.permission.edit_user,
                "delete_user": user.permission.delete_user,
                "add_lead": user.permission.add_lead,
                "edit_lead": user.permission.edit_lead,
                "delete_lead": user.permission.delete_lead,
                "view_users": user.permission.view_users,
                "view_lead": user.permission.view_lead,
                "view_branch": user.permission.view_branch,
                "view_accounts": user.permission.view_accounts,
                "view_research": user.permission.view_research,
                "view_client": user.permission.view_client,
                "view_payment": user.permission.view_payment,
                "view_invoice": user.permission.view_invoice,
                "view_kyc": user.permission.view_kyc,
                "approval": user.permission.approval,
                "internal_mailing": user.permission.internal_mailing,
                "chatting": user.permission.chatting,
                "targets": user.permission.targets,
                "reports": user.permission.reports,
                "fetch_lead": user.permission.fetch_lead,
            }

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


@router.post("/login/json", response_model=TokenResponse)
def login_json(
    login_data: LoginRequest,
    db: Session = Depends(get_db),
):
    """
    Authenticate user with JSON payload instead of form data.
    """
    try:
        # Try to find user by phone number first, then by email
        user = None
        
        # Check if username looks like email
        if "@" in login_data.username:
            user = db.query(UserDetails).filter(
                UserDetails.email == login_data.username
            ).first()
        else:
            # Try phone number
            user = db.query(UserDetails).filter(
                UserDetails.phone_number == login_data.username
            ).first()
        
        # If not found by phone, try email as fallback
        if not user:
            user = db.query(UserDetails).filter(
                UserDetails.email == login_data.username
            ).first()

        # Validate user and password
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )

        if not verify_password(login_data.password, user.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )

        # Check if user is active
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is deactivated. Contact administrator."
            )

        # Create tokens
        access_token = create_access_token({
            "sub": user.employee_code,
            "role": user.role.value,
            "branch_id": user.branch_id
        })
        refresh_token = create_refresh_token(user.employee_code)

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
            "manager_name": user.manager.name if user.manager else None,
        }

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


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(
    body: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    """
    Given a valid refresh token, issue a new access + refresh pair.
    """
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
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Token refresh failed: {str(e)}"
        )


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(
    body: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    """
    Revoke a refresh token (log the user out).
    """
    try:
        revoke_refresh_token(db, body.refresh_token)
        return {
            "message": "Successfully logged out",
            "status": "success"
        }

    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Logout failed: {str(e)}"
        )


@router.post("/logout-all")
def logout_all_devices(
    employee_code: str,
    db: Session = Depends(get_db),
):
    """
    Revoke all refresh tokens for a user (logout from all devices).
    """
    try:
        # Delete all refresh tokens for the user
        deleted_count = db.query(TokenDetails).filter(
            TokenDetails.user_id == employee_code
        ).delete()
        
        db.commit()
        
        return {
            "message": f"Successfully logged out from {deleted_count} devices",
            "status": "success",
            "devices_logged_out": deleted_count
        }

    except (OperationalError, DisconnectionError) as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Logout all failed: {str(e)}"
        )


@router.get("/me", response_model=UserInfoResponse)
def get_current_user(
    current_user: UserDetails = Depends(get_db),
):
    """
    Get current user information from access token.
    """
    return UserInfoResponse(
        employee_code=current_user.employee_code,
        name=current_user.name,
        email=current_user.email,
        phone_number=current_user.phone_number,
        role=current_user.role.value,
        branch_id=current_user.branch_id,
        is_active=current_user.is_active
    )


@router.post("/change-password")
def change_password(
    old_password: str,
    new_password: str,
    current_user: UserDetails = Depends(get_db),
    db: Session = Depends(get_db),
):
    """
    Change user password.
    """
    try:
        # Verify old password
        if not verify_password(old_password, current_user.password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid current password"
            )

        # Validate new password
        if len(new_password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must be at least 6 characters long"
            )

        # Hash new password
        if pwd_context:
            hashed_password = pwd_context.hash(new_password)
        else:
            hashed_password = hashlib.sha256(new_password.encode()).hexdigest()

        # Update password
        current_user.password = hashed_password
        db.commit()

        # Revoke all existing refresh tokens (force re-login)
        db.query(TokenDetails).filter(
            TokenDetails.user_id == current_user.employee_code
        ).delete()
        db.commit()

        return {
            "message": "Password changed successfully. Please login again.",
            "status": "success"
        }

    except HTTPException:
        raise
    except (OperationalError, DisconnectionError) as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Password change failed: {str(e)}"
        )


@router.get("/health")
def auth_health_check(db: Session = Depends(get_db)):
    """
    Health check for auth service.
    """
    try:
        # Test database connection
        db.execute("SELECT 1")
        return {
            "status": "healthy",
            "service": "authentication",
            "database": "connected"
        }
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection failed"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Health check failed: {str(e)}"
        )