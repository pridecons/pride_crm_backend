# routes/permissions.py

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DisconnectionError

from db.connection import get_db
from db.models import PermissionDetails, UserDetails, ProfileRole, Department

# NOTE: Your schema can define a model like:
# class PermissionUpdate(BaseModel):
#     permissions: Optional[List[str]] = None  # full replace
#     add: Optional[List[str]] = None          # additive update
#     remove: Optional[List[str]] = None       # subtractive update
from db.Schema.permissions import PermissionUpdate

from pydantic import BaseModel, Field

router = APIRouter(
    prefix="/permissions",
    tags=["permissions"],
)

class PermissionReplace(BaseModel):
    # Full replacement list. Required.
    permissions: List[str] = Field(default_factory=list)
# ---------- helpers -----------------------------------------------------------

def _all_permission_values() -> List[str]:
    """All valid permission strings from the Enum."""
    return [p.value for p in PermissionDetails]

def _validate_permissions_or_400(perms: List[str]) -> None:
    valid = set(_all_permission_values())
    invalid = [p for p in perms if p not in valid]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid permission(s): {invalid}. See /permissions/ for valid values."
        )


# ---------- API Endpoints -----------------------------------------------------

@router.get("/", response_model=List[str])
def get_all_permissions(
    db: Session = Depends(get_db),
):
    """
    Return the canonical list of available permission keys (Enum values).
    No DB query is needed; this is sourced from the Enum.
    """
    try:
        return _all_permission_values()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching permissions: {str(e)}"
        )


@router.get("/user/{employee_code}")
def get_user_permissions(
    employee_code: str,
    db: Session = Depends(get_db),
):
    """
    Get the permissions array stored on the user record.
    """
    try:
        user = db.query(UserDetails).filter(UserDetails.employee_code == employee_code).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User {employee_code} not found"
            )
        return {
            "employee_code": employee_code,
            "permissions": user.permissions or []
        }
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching user permissions: {str(e)}"
        )


@router.put("/user/{employee_code}")
def update_user_permissions(
    employee_code: str,
    permission_in: PermissionReplace,  # now = PermissionReplace
    db: Session = Depends(get_db),
):
    """
    Replace a user's permissions with the provided list.
    The client MUST send the full, final list in `permissions`.
    """
    try:
        user = db.query(UserDetails).filter(UserDetails.employee_code == employee_code).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User {employee_code} not found"
            )

        # Require the field and validate
        if permission_in.permissions is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="`permissions` is required and must be a list of permission keys."
            )

        # De-dupe while preserving order
        new_perms = list(dict.fromkeys(permission_in.permissions))
        _validate_permissions_or_400(new_perms)

        user.permissions = new_perms
        db.commit()
        db.refresh(user)

        return {
            "message": f"Permissions updated for {employee_code}",
            "employee_code": employee_code,
            "permissions": user.permissions or []
        }

    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating permissions: {str(e)}"
        )


@router.patch("/user/{employee_code}/toggle/{permission_name}")
def toggle_single_permission(
    employee_code: str,
    permission_name: str,
    db: Session = Depends(get_db),
):
    """
    Toggle a single permission in the user's permissions ARRAY.
    If present → remove; if absent → add.
    """
    try:
        # Validate permission name
        if permission_name not in _all_permission_values():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid permission name: {permission_name}"
            )

        user = db.query(UserDetails).filter(UserDetails.employee_code == employee_code).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User {employee_code} not found"
            )

        current = set(user.permissions or [])
        if permission_name in current:
            current.remove(permission_name)
            new_value = False
        else:
            current.add(permission_name)
            new_value = True

        user.permissions = list(current)
        db.commit()
        db.refresh(user)

        return {
            "message": f"Permission '{permission_name}' {'enabled' if new_value else 'disabled'} for user {employee_code}",
            "permission": permission_name,
            "new_value": new_value,
            "employee_code": employee_code,
            "permissions": user.permissions or []
        }

    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error toggling permission: {str(e)}"
        )


@router.post("/user/{employee_code}/reset-defaults")
def reset_to_default_permissions(
    employee_code: str,
    db: Session = Depends(get_db),
):
    """
    Reset user's permissions to their role's default_permissions
    (from ProfileRole.default_permissions).
    """
    try:
        user = db.query(UserDetails).filter(UserDetails.employee_code == employee_code).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User {employee_code} not found"
            )

        role = db.query(ProfileRole).filter(ProfileRole.id == user.role_id).first()
        if not role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ProfileRole id {user.role_id} not found for user {employee_code}"
            )

        # Sanitize against current valid Enum values (in case defaults drifted)
        valid = set(_all_permission_values())
        defaults = [p for p in (role.default_permissions or []) if p in valid]

        user.permissions = defaults
        db.commit()
        db.refresh(user)

        return {
            "message": f"Permissions reset to role defaults for user {employee_code}",
            "employee_code": employee_code,
            "role_id": user.role_id,
            "permissions": user.permissions or []
        }

    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error resetting permissions: {str(e)}"
        )
