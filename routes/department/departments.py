# routes/department/departments.py

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, OperationalError, DisconnectionError
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from db.connection import get_db
from db.models import Department, ProfileRole, UserDetails, PermissionDetails
from routes.auth.auth_dependency import get_current_user

router = APIRouter(
    prefix="/departments",
    tags=["Department Management"],
)


# Pydantic Models
class DepartmentBase(BaseModel):
    name: str
    description: Optional[str] = None
    available_permissions: Optional[List[str]] = []
    is_active: bool = True


class DepartmentCreate(DepartmentBase):
    pass


class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    available_permissions: Optional[List[str]] = None
    is_active: Optional[bool] = None


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    name: str
    description: Optional[str]
    available_permissions: Optional[List[str]]
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]
    
    # Statistics
    profile_count: Optional[int] = 0
    user_count: Optional[int] = 0


class DepartmentPermissionUpdate(BaseModel):
    available_permissions: List[str]


class DepartmentListResponse(BaseModel):
    data: List[DepartmentOut]
    pagination: dict
    total_count: int


# Helper Functions
def check_department_permissions(current_user: UserDetails):
    """Check if user has permission to manage departments"""
    if not current_user.profile_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: No profile assigned"
        )
    
    # Only SUPERADMIN and BRANCH_MANAGER can manage departments
    allowed_profiles = ["SUPERADMIN", "BRANCH_MANAGER"]
    if current_user.profile_role.name not in allowed_profiles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Insufficient permissions to manage departments"
        )


def serialize_department(department: Department, db: Session) -> dict:
    """Serialize department with statistics"""
    profile_count = db.query(ProfileRole).filter_by(department_id=department.id, is_active=True).count()
    user_count = db.query(UserDetails).filter_by(department_id=department.id, is_active=True).count()
    
    return {
        "id": department.id,
        "name": department.name,
        "description": department.description,
        "available_permissions": department.available_permissions or [],
        "is_active": department.is_active,
        "created_at": department.created_at,
        "updated_at": department.updated_at,
        "profile_count": profile_count,
        "user_count": user_count
    }


# CRUD Operations

@router.post("/", response_model=DepartmentOut)
def create_department(
    department_in: DepartmentCreate,
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """Create a new department"""
    try:
        check_department_permissions(current_user)
        
        # Validate available permissions
        if department_in.available_permissions:
            all_permissions = PermissionDetails.get_all_permission_names()
            invalid_perms = [p for p in department_in.available_permissions if p not in all_permissions]
            if invalid_perms:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid permissions: {invalid_perms}"
                )
        
        # Check if department name already exists
        existing = db.query(Department).filter_by(name=department_in.name.upper()).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Department '{department_in.name}' already exists"
            )
        
        # Create department
        department = Department(
            name=department_in.name.upper(),
            description=department_in.description,
            available_permissions=department_in.available_permissions or [],
            is_active=department_in.is_active
        )
        
        db.add(department)
        db.commit()
        db.refresh(department)
        
        return serialize_department(department, db)
        
    except HTTPException:
        raise
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Department with name '{department_in.name}' already exists"
        )
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
            detail=f"Error creating department: {str(e)}"
        )


@router.get("/", response_model=DepartmentListResponse)
def get_all_departments(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    active_only: bool = Query(False),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """Get all departments with filtering and pagination"""
    try:
        query = db.query(Department)
        
        if active_only:
            query = query.filter(Department.is_active == True)
        
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                Department.name.ilike(search_term) |
                Department.description.ilike(search_term)
            )
        
        # Get total count
        total_count = query.count()
        
        # Apply pagination
        departments = query.offset(skip).limit(limit).all()
        
        # Serialize departments
        serialized_departments = [serialize_department(dept, db) for dept in departments]
        
        return {
            "data": serialized_departments,
            "pagination": {
                "total": total_count,
                "skip": skip,
                "limit": limit,
                "pages": (total_count + limit - 1) // limit if limit > 0 else 1
            },
            "total_count": total_count
        }
        
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching departments: {str(e)}"
        )


@router.get("/{department_id}", response_model=DepartmentOut)
def get_department_by_id(
    department_id: int,
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """Get department by ID"""
    try:
        department = db.query(Department).filter_by(id=department_id).first()
        if not department:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Department with ID {department_id} not found"
            )
        
        return serialize_department(department, db)
        
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
            detail=f"Error fetching department: {str(e)}"
        )


@router.put("/{department_id}", response_model=DepartmentOut)
def update_department(
    department_id: int,
    department_update: DepartmentUpdate,
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """Update department"""
    try:
        check_department_permissions(current_user)
        
        department = db.query(Department).filter_by(id=department_id).first()
        if not department:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Department with ID {department_id} not found"
            )
        
        # Validate available permissions if provided
        if department_update.available_permissions is not None:
            all_permissions = PermissionDetails.get_all_permission_names()
            invalid_perms = [p for p in department_update.available_permissions if p not in all_permissions]
            if invalid_perms:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid permissions: {invalid_perms}"
                )
        
        # Check name uniqueness if name is being updated
        if department_update.name and department_update.name.upper() != department.name:
            existing = db.query(Department).filter_by(name=department_update.name.upper()).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Department '{department_update.name}' already exists"
                )
        
        # Update fields
        update_data = department_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            if field == "name" and value:
                setattr(department, field, value.upper())
            else:
                setattr(department, field, value)
        
        db.commit()
        db.refresh(department)
        
        return serialize_department(department, db)
        
    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Department name already exists"
        )
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
            detail=f"Error updating department: {str(e)}"
        )


@router.delete("/{department_id}")
def delete_department(
    department_id: int,
    force_delete: bool = Query(False, description="Force delete even if department has users/profiles"),
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """Delete department"""
    try:
        check_department_permissions(current_user)
        
        department = db.query(Department).filter_by(id=department_id).first()
        if not department:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Department with ID {department_id} not found"
            )
        
        # Prevent deletion of default departments
        default_departments = ["ADMIN", "ACCOUNTING", "HR", "SALES_TEAM"]
        if department.name in default_departments:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot delete default department '{department.name}'"
            )
        
        # Check if department has profiles or users
        profile_count = db.query(ProfileRole).filter_by(department_id=department_id).count()
        user_count = db.query(UserDetails).filter_by(department_id=department_id).count()
        
        if (profile_count > 0 or user_count > 0) and not force_delete:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot delete department. It has {profile_count} profiles and {user_count} users. Use force_delete=true to override."
            )
        
        # If force delete, need to handle cascading deletions
        if force_delete:
            # Update users to move them to a default department or set to null
            admin_dept = db.query(Department).filter_by(name="ADMIN").first()
            if admin_dept:
                db.query(UserDetails).filter_by(department_id=department_id).update({
                    "department_id": admin_dept.id
                })
            
            # Delete associated profiles
            db.query(ProfileRole).filter_by(department_id=department_id).delete()
        
        db.delete(department)
        db.commit()
        
        return {
            "message": f"Department '{department.name}' deleted successfully",
            "department_id": department_id
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
            detail=f"Error deleting department: {str(e)}"
        )


# Permission Management

@router.put("/{department_id}/permissions")
def update_department_permissions(
    department_id: int,
    permission_update: DepartmentPermissionUpdate,
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """Update available permissions for a department"""
    try:
        check_department_permissions(current_user)
        
        department = db.query(Department).filter_by(id=department_id).first()
        if not department:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Department with ID {department_id} not found"
            )
        
        # Validate permissions
        all_permissions = PermissionDetails.get_all_permission_names()
        invalid_perms = [p for p in permission_update.available_permissions if p not in all_permissions]
        if invalid_perms:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid permissions: {invalid_perms}"
            )
        
        # Update department permissions
        department.available_permissions = permission_update.available_permissions
        db.commit()
        db.refresh(department)
        
        # Update existing profiles in this department to only have permissions that are available
        profiles = db.query(ProfileRole).filter_by(department_id=department_id).all()
        for profile in profiles:
            if profile.default_permissions:
                # Filter profile permissions to only include available department permissions
                filtered_perms = [p for p in profile.default_permissions if p in permission_update.available_permissions]
                profile.default_permissions = filtered_perms
        
        db.commit()
        
        return {
            "message": f"Permissions updated for department '{department.name}'",
            "department_id": department_id,
            "available_permissions": permission_update.available_permissions,
            "updated_profiles": len(profiles)
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
            detail=f"Error updating department permissions: {str(e)}"
        )

