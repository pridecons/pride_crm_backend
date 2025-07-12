# routes/permissions.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DisconnectionError

from db.connection import get_db
from db.models import PermissionDetails, UserDetails, UserRoleEnum
from db.Schema.permissions import PermissionBase, PermissionCreate, PermissionUpdate, PermissionOut, BulkPermissionUpdate

router = APIRouter(
    prefix="/permissions",
    tags=["permissions"],
)


# API Endpoints

@router.get("/", response_model=list[PermissionOut])
def get_all_permissions(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """Get all user permissions"""
    try:
        permissions = db.query(PermissionDetails).offset(skip).limit(limit).all()
        return permissions
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching permissions: {str(e)}"
        )


@router.get("/user/{employee_code}", response_model=PermissionOut)
def get_user_permissions(
    employee_code: str,
    db: Session = Depends(get_db),
):
    """Get permissions for a specific user"""
    try:
        permission = db.query(PermissionDetails).filter_by(user_id=employee_code).first()
        if not permission:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Permissions not found for user {employee_code}"
            )
        return permission
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


@router.put("/user/{employee_code}", response_model=PermissionOut)
def update_user_permissions(
    employee_code: str,
    permission_in: PermissionUpdate,
    db: Session = Depends(get_db),
):
    """Update permissions for a specific user"""
    try:
        # Get existing permissions
        permission = db.query(PermissionDetails).filter_by(user_id=employee_code).first()
        if not permission:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Permissions not found for user {employee_code}"
            )

        # Update only provided fields
        update_data = permission_in.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(permission, field, value)

        db.commit()
        db.refresh(permission)
        return permission

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
    """Toggle a single permission on/off"""
    try:
        # Validate permission name
        valid_permissions = {
            'add_user', 'edit_user', 'delete_user', 'add_lead', 'edit_lead', 'delete_lead',
            'view_users', 'view_lead', 'view_branch', 'view_accounts', 'view_research',
            'view_client', 'view_payment', 'view_invoice', 'view_kyc', 'approval',
            'internal_mailing', 'chatting', 'targets', 'reports', 'fetch_lead'
        }

        if permission_name not in valid_permissions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid permission name: {permission_name}"
            )

        # Get existing permissions
        permission = db.query(PermissionDetails).filter_by(user_id=employee_code).first()
        if not permission:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Permissions not found for user {employee_code}"
            )

        # Toggle the permission
        current_value = getattr(permission, permission_name)
        new_value = not current_value
        setattr(permission, permission_name, new_value)

        db.commit()

        return {
            "message": f"Permission '{permission_name}' {'enabled' if new_value else 'disabled'} for user {employee_code}",
            "permission": permission_name,
            "old_value": current_value,
            "new_value": new_value,
            "user_id": employee_code
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
    """Reset user permissions to role defaults"""
    try:
        # Get user to determine role
        user = db.query(UserDetails).filter_by(employee_code=employee_code).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User {employee_code} not found"
            )

        # Get existing permissions
        permission = db.query(PermissionDetails).filter_by(user_id=employee_code).first()
        if not permission:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Permissions not found for user {employee_code}"
            )

        # Get default permissions for role
        default_perms = PermissionDetails.get_default_permissions(user.role)

        # Update all permissions to defaults
        for perm_name, perm_value in default_perms.items():
            setattr(permission, perm_name, perm_value)

        db.commit()
        db.refresh(permission)

        return {
            "message": f"Permissions reset to {user.role.value} defaults for user {employee_code}",
            "user_id": employee_code,
            "role": user.role.value,
            "default_permissions": default_perms
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

