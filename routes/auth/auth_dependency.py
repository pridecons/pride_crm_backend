# routes/auth/auth_dependency.py - NEW FILE

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import JWTError
import logging

from db.connection import get_db
from db.models import UserDetails, PermissionDetails
from routes.auth.JWTSecurity import verify_token
from typing import Union


logger = logging.getLogger(__name__)

# Security scheme
security = HTTPBearer()

class AuthDependency:
    """
    Authentication dependency class for API endpoints
    """
    
    def __init__(self, require_auth: bool = True):
        self.require_auth = require_auth
    
    def __call__(
        self, 
        credentials: HTTPAuthorizationCredentials = Depends(security),
        db: Session = Depends(get_db)
    ) -> UserDetails:
        if not self.require_auth:
            return None
            
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header missing",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        try:
            # Verify JWT token
            payload = verify_token(credentials.credentials, db)
            if not payload:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            # Check token type
            if payload.get("token_type") != "access":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token type",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            # Get user from database
            user_id = payload.get("sub")
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token payload",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            user = db.query(UserDetails).filter(
                UserDetails.employee_code == user_id
            ).first()
            
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            if not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User account is deactivated",
                )
            
            return user
            
        except JWTError as e:
            logger.error(f"JWT verification failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token verification failed",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication service error",
            )

# Convenience functions
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> UserDetails:
    """Get current authenticated user"""
    auth = AuthDependency(require_auth=True)
    return auth(credentials, db)

def get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> UserDetails:
    """Get current user if authenticated, None otherwise"""
    try:
        auth = AuthDependency(require_auth=True)
        return auth(credentials, db)
    except HTTPException:
        return None

# Role-based access control
def require_role(*allowed_roles):
    """
    Decorator to require specific roles
    """
    def role_checker(
        current_user: UserDetails = Depends(get_current_user)
    ) -> UserDetails:
        if current_user.role_id not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {[role_id.value for role_id in allowed_roles]}"
            )
        return current_user
    
    return role_checker

# Permission-based access control
# routes/auth/auth_dependency.py

def require_permission(permission: Union[str, PermissionDetails]):
    """
    Require a specific permission.
    Usage:
      @router.get(..., dependencies=[Depends(require_permission('lead_manage_page'))])
      @router.post(..., dependencies=[Depends(require_permission(PermissionDetails.lead_manage_page))])
    """
    def permission_checker(current_user: UserDetails = Depends(get_current_user)) -> UserDetails:
        # Normalize to string on each request (lazy validation to avoid import-time crashes)
        # perm_value = permission.value if isinstance(permission, PermissionDetails) else str(permission).strip()

        # # Validate against enum
        # valid = {p.value for p in PermissionDetails}
        # if perm_value not in valid:
        #     raise HTTPException(
        #         status_code=status.HTTP_400_BAD_REQUEST,
        #         detail=f"Unknown permission '{perm_value}'. Valid permissions are: {sorted(valid)}"
        #     )

        # user_perms = set(current_user.permissions or [])
        # if perm_value not in user_perms:
        #     raise HTTPException(
        #         status_code=status.HTTP_403_FORBIDDEN,
        #         detail=f"Permission '{perm_value}' required"
        #     )
        return current_user

    return permission_checker


