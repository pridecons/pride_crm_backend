# routes/permissions.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DisconnectionError

from db.connection import get_db
from db.models import PermissionDetails, UserDetails
from db.Schema.permissions import PermissionUpdate

router = APIRouter(
    prefix="/permissions",
    tags=["permissions"],
)


# API Endpoints

@router.get("/")
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


@router.get("/user/{employee_code}")
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


@router.put("/user/{employee_code}")
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
             # LEAD/[id]
                'lead_recording_view' , 'lead_recording_upload',
                'lead_story_view' , 'lead_transfer' ,"lead_branch_view"

                # LEAD SOURCE
                'create_lead' , 'edit_lead' , 'delete_lead'  ,

                # LEAD RESPONSE
                'create_new_lead_response' , 'edit_response' , 'delete_response' ,

                # USER 
                'user_add_user' , 'user_all_roles' , 'user_all_branches' ,
                'user_view_user_details' , 'user_edit_user' , 'user_delete_user' ,

                # FETCH LIMIT
                'fetch_limit_create_new' , 'fetch_limit_edit' , 'fetch_limit_delete' ,

                # PLANS
                'plans_create' , 'edit_plan' , 'delete_plane' ,

                # CLIENT
                'client_select_branch' , 'client_invoice' , 'client_story' , 'client_comments' ,

                # SIDEBAR
                'lead_manage_page' , 'plane_page' , 'attandance_page' ,
                'client_page' , 'lead_source_page' , 'lead_response_page' ,
                'user_page' , 'permission_page' , 'lead_upload_page' , 'fetch_limit_page' ,

                'add_lead_page' , 'payment_page' , 'messanger_page' , 'template' ,
                'sms_page' , 'email_page' , 'branch_page' , 'old_lead_page' , 'new_lead_page' ,

                # MESSANGER
                'rational_download' , 'rational_pdf_model_download' , 'rational_pdf_model_view' ,
                'rational_graf_model_view' , 'rational_status' , 'rational_edit' , 'rational_add_recommadation' ,

                # EMAIL
                'email_add_temp' , 'email_view_temp' , 'email_edit_temp' , 'email_delete_temp' ,

                # SMS
                'sms_add' , 'sms_edit' , 'sms_delete' ,

                # BRANCH
                'branch_add' , 'branch_edit' , 'branch_details' , 'branch_agreement_view'
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
    """Reset user permissions to role_id defaults"""
    try:
        # Get user to determine role_id
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

        # Get default permissions for role_id
        default_perms = PermissionDetails.get_default_permissions(user.role_id)

        # Update all permissions to defaults
        for perm_name, perm_value in default_perms.items():
            setattr(permission, perm_name, perm_value)

        db.commit()
        db.refresh(permission)

        return {
            "message": f"Permissions reset to {user.role_id.value} defaults for user {employee_code}",
            "user_id": employee_code,
            "role_id": user.role_id.value,
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

