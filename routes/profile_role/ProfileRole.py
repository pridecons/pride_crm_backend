# routes/profile_role/ProfileRole.py - Profile Role Management Routes

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, OperationalError, DisconnectionError
from sqlalchemy import and_, or_
from pydantic import BaseModel, ConfigDict, validator
from datetime import datetime

from db.connection import get_db
from db.models import ProfileRole, Department, UserDetails, PermissionDetails
from routes.auth.auth_dependency import get_current_user

router = APIRouter(
    prefix="/profile-roles",
    tags=["Profile Role Management"],
)


# Pydantic Models
class ProfileRoleBase(BaseModel):
    name: str
    department_id: int
    parent_profile_id: Optional[int] = None
    hierarchy_level: int
    default_permissions: Optional[List[str]] = []
    description: Optional[str] = None
    is_active: bool = True


class ProfileRoleCreate(ProfileRoleBase):
    @validator('name')
    def validate_name(cls, v):
        return v.upper().strip()


class ProfileRoleUpdate(BaseModel):
    name: Optional[str] = None
    department_id: Optional[int] = None
    parent_profile_id: Optional[int] = None
    hierarchy_level: Optional[int] = None
    default_permissions: Optional[List[str]] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    
    @validator('name')
    def validate_name(cls, v):
        if v:
            return v.upper().strip()
        return v


class ProfileRoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    name: str
    department_id: int
    department_name: str
    parent_profile_id: Optional[int]
    parent_profile_name: Optional[str]
    hierarchy_level: int
    default_permissions: Optional[List[str]]
    description: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]
    
    # Statistics
    user_count: Optional[int] = 0
    child_profiles_count: Optional[int] = 0


class ProfilePermissionUpdate(BaseModel):
    default_permissions: List[str]


class ProfileHierarchyOut(BaseModel):
    id: int
    name: str
    hierarchy_level: int
    parent_profile_id: Optional[int]
    children: List['ProfileHierarchyOut'] = []
    user_count: int


class ProfileListResponse(BaseModel):
    data: List[ProfileRoleOut]
    pagination: dict
    total_count: int


# Helper Functions
def check_profile_permissions(current_user: UserDetails):
    """Check if user has permission to manage profiles"""
    if not current_user.profile_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: No profile assigned"
        )
    
    # Only SUPERADMIN and BRANCH_MANAGER can manage profiles
    allowed_profiles = ["SUPERADMIN", "BRANCH_MANAGER"]
    if current_user.profile_role.name not in allowed_profiles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Insufficient permissions to manage profiles"
        )


def validate_hierarchy(profile_data: dict, db: Session, exclude_profile_id: int = None):
    """Validate profile hierarchy rules"""
    department_id = profile_data.get('department_id')
    parent_profile_id = profile_data.get('parent_profile_id')
    hierarchy_level = profile_data.get('hierarchy_level')
    
    # Check if department exists
    department = db.query(Department).filter_by(id=department_id).first()
    if not department:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Department with ID {department_id} not found"
        )
    
    # If parent profile is specified, validate it
    if parent_profile_id:
        parent = db.query(ProfileRole).filter_by(id=parent_profile_id).first()
        if not parent:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Parent profile with ID {parent_profile_id} not found"
            )
        
        # Parent must have lower hierarchy level (closer to 1)
        if hierarchy_level <= parent.hierarchy_level:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Profile hierarchy level ({hierarchy_level}) must be greater than parent's level ({parent.hierarchy_level})"
            )
        
        # Check for circular dependency
        current_parent = parent
        while current_parent and current_parent.parent_profile_id:
            if current_parent.parent_profile_id == exclude_profile_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Circular hierarchy dependency detected"
                )
            current_parent = db.query(ProfileRole).filter_by(id=current_parent.parent_profile_id).first()
    
    return department


def validate_permissions(permissions: List[str], department: Department):
    """Validate that permissions are available in the department"""
    if not permissions:
        return
    
    available_perms = department.available_permissions or []
    invalid_perms = [p for p in permissions if p not in available_perms]
    
    if invalid_perms:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Permissions {invalid_perms} are not available in department '{department.name}'. Available: {available_perms}"
        )


def serialize_profile(profile: ProfileRole, db: Session) -> dict:
    """Serialize profile with additional information"""
    user_count = db.query(UserDetails).filter_by(profile_role_id=profile.id, is_active=True).count()
    child_profiles_count = db.query(ProfileRole).filter_by(parent_profile_id=profile.id, is_active=True).count()
    
    department_name = profile.department.name if profile.department else None
    parent_profile_name = profile.parent_profile.name if profile.parent_profile else None
    
    return {
        "id": profile.id,
        "name": profile.name,
        "department_id": profile.department_id,
        "department_name": department_name,
        "parent_profile_id": profile.parent_profile_id,
        "parent_profile_name": parent_profile_name,
        "hierarchy_level": profile.hierarchy_level,
        "default_permissions": profile.default_permissions or [],
        "description": profile.description,
        "is_active": profile.is_active,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
        "user_count": user_count,
        "child_profiles_count": child_profiles_count
    }


# CRUD Operations

@router.post("/", response_model=ProfileRoleOut)
def create_profile_role(
    profile_in: ProfileRoleCreate,
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """Create a new profile role"""
    try:
        check_profile_permissions(current_user)
        
        # Validate hierarchy and get department
        department = validate_hierarchy(profile_in.dict(), db)
        
        # Validate permissions
        validate_permissions(profile_in.default_permissions, department)
        
        # Check if profile name already exists
        existing = db.query(ProfileRole).filter_by(name=profile_in.name).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Profile '{profile_in.name}' already exists"
            )
        
        # Create profile
        profile = ProfileRole(
            name=profile_in.name,
            department_id=profile_in.department_id,
            parent_profile_id=profile_in.parent_profile_id,
            hierarchy_level=profile_in.hierarchy_level,
            default_permissions=profile_in.default_permissions or [],
            description=profile_in.description,
            is_active=profile_in.is_active
        )
        
        db.add(profile)
        db.commit()
        db.refresh(profile)
        
        return serialize_profile(profile, db)
        
    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Profile with name '{profile_in.name}' already exists"
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
            detail=f"Error creating profile: {str(e)}"
        )


@router.get("/", response_model=ProfileListResponse)
def get_all_profile_roles(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    department_id: Optional[int] = Query(None),
    parent_profile_id: Optional[int] = Query(None),
    hierarchy_level: Optional[int] = Query(None),
    active_only: bool = Query(True),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """Get all profile roles with filtering and pagination"""
    try:
        query = db.query(ProfileRole)
        
        if active_only:
            query = query.filter(ProfileRole.is_active == True)
        
        if department_id:
            query = query.filter(ProfileRole.department_id == department_id)
        
        if parent_profile_id:
            query = query.filter(ProfileRole.parent_profile_id == parent_profile_id)
        
        if hierarchy_level:
            query = query.filter(ProfileRole.hierarchy_level == hierarchy_level)
        
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    ProfileRole.name.ilike(search_term),
                    ProfileRole.description.ilike(search_term)
                )
            )
        
        # Order by hierarchy level and name
        query = query.order_by(ProfileRole.hierarchy_level, ProfileRole.name)
        
        # Get total count
        total_count = query.count()
        
        # Apply pagination
        profiles = query.offset(skip).limit(limit).all()
        
        # Serialize profiles
        serialized_profiles = [serialize_profile(profile, db) for profile in profiles]
        
        return {
            "data": serialized_profiles,
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
            detail=f"Error fetching profiles: {str(e)}"
        )


@router.get("/{profile_id}", response_model=ProfileRoleOut)
def get_profile_role_by_id(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """Get profile role by ID"""
    try:
        profile = db.query(ProfileRole).filter_by(id=profile_id).first()
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile with ID {profile_id} not found"
            )
        
        return serialize_profile(profile, db)
        
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
            detail=f"Error fetching profile: {str(e)}"
        )


@router.put("/{profile_id}", response_model=ProfileRoleOut)
def update_profile_role(
    profile_id: int,
    profile_update: ProfileRoleUpdate,
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """Update profile role"""
    try:
        check_profile_permissions(current_user)
        
        profile = db.query(ProfileRole).filter_by(id=profile_id).first()
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile with ID {profile_id} not found"
            )
        
        # Prevent modification of default profiles
        default_profiles = ["SUPERADMIN", "COMPLIANCE", "BRANCH_MANAGER", "HR", "SALES_MANAGER", "TL", "SBA", "BA", "RESEARCHER"]
        if profile.name in default_profiles and profile_update.name and profile_update.name != profile.name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot rename default profile '{profile.name}'"
            )
        
        # Prepare update data
        update_data = profile_update.dict(exclude_unset=True)
        
        # If hierarchy or parent is being changed, validate
        if any(key in update_data for key in ['department_id', 'parent_profile_id', 'hierarchy_level']):
            validation_data = {
                'department_id': update_data.get('department_id', profile.department_id),
                'parent_profile_id': update_data.get('parent_profile_id', profile.parent_profile_id),
                'hierarchy_level': update_data.get('hierarchy_level', profile.hierarchy_level)
            }
            department = validate_hierarchy(validation_data, db, exclude_profile_id=profile_id)
        else:
            department = profile.department
        
        # Validate permissions if being updated
        if 'default_permissions' in update_data:
            validate_permissions(update_data['default_permissions'], department)
        
        # Check name uniqueness if name is being updated
        if 'name' in update_data and update_data['name'] != profile.name:
            existing = db.query(ProfileRole).filter_by(name=update_data['name']).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Profile '{update_data['name']}' already exists"
                )
        
        # Update fields
        for field, value in update_data.items():
            setattr(profile, field, value)
        
        db.commit()
        db.refresh(profile)
        
        return serialize_profile(profile, db)
        
    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Profile name already exists or hierarchy constraint violated"
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
            detail=f"Error updating profile: {str(e)}"
        )


@router.delete("/{profile_id}")
def delete_profile_role(
    profile_id: int,
    force_delete: bool = Query(False, description="Force delete even if profile has users"),
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """Delete profile role"""
    try:
        check_profile_permissions(current_user)
        
        profile = db.query(ProfileRole).filter_by(id=profile_id).first()
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile with ID {profile_id} not found"
            )
        
        # Prevent deletion of default profiles
        default_profiles = ["SUPERADMIN", "COMPLIANCE", "BRANCH_MANAGER", "HR", "SALES_MANAGER", "TL", "SBA", "BA", "RESEARCHER"]
        if profile.name in default_profiles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot delete default profile '{profile.name}'"
            )
        
        # Check if profile has users
        user_count = db.query(UserDetails).filter_by(profile_role_id=profile_id).count()
        if user_count > 0 and not force_delete:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot delete profile. It has {user_count} users. Use force_delete=true to override."
            )
        
        # Check if profile has child profiles
        child_count = db.query(ProfileRole).filter_by(parent_profile_id=profile_id).count()
        if child_count > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot delete profile. It has {child_count} child profiles. Remove child profiles first."
            )
        
        # If force delete, reassign users to a default profile
        if force_delete and user_count > 0:
            # Find a suitable default profile in the same department
            default_profile = db.query(ProfileRole).filter(
                and_(
                    ProfileRole.department_id == profile.department_id,
                    ProfileRole.name.in_(["BA", "SBA", "TL"])  # Safe default profiles
                )
            ).first()
            
            if default_profile:
                db.query(UserDetails).filter_by(profile_role_id=profile_id).update({
                    "profile_role_id": default_profile.id
                })
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot force delete: No suitable default profile found for user reassignment"
                )
        
        db.delete(profile)
        db.commit()
        
        return {
            "message": f"Profile '{profile.name}' deleted successfully",
            "profile_id": profile_id
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
            detail=f"Error deleting profile: {str(e)}"
        )


# Hierarchy Management

@router.get("/hierarchy/tree")
def get_profile_hierarchy_tree(
    department_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """Get profile hierarchy as a tree structure"""
    try:
        query = db.query(ProfileRole).filter(ProfileRole.is_active == True)
        
        if department_id:
            query = query.filter(ProfileRole.department_id == department_id)
        
        profiles = query.order_by(ProfileRole.hierarchy_level, ProfileRole.name).all()
        
        def build_tree(parent_id=None):
            children = []
            for profile in profiles:
                if profile.parent_profile_id == parent_id:
                    user_count = db.query(UserDetails).filter_by(
                        profile_role_id=profile.id, is_active=True
                    ).count()
                    
                    node = {
                        "id": profile.id,
                        "name": profile.name,
                        "hierarchy_level": profile.hierarchy_level,
                        "parent_profile_id": profile.parent_profile_id,
                        "user_count": user_count,
                        "children": build_tree(profile.id)
                    }
                    children.append(node)
            return children
        
        tree = build_tree()
        
        return {
            "hierarchy_tree": tree,
            "total_profiles": len(profiles)
        }
        
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching hierarchy tree: {str(e)}"
        )


# Permission Management

@router.put("/{profile_id}/permissions")
def update_profile_permissions(
    profile_id: int,
    permission_update: ProfilePermissionUpdate,
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """Update default permissions for a profile"""
    try:
        check_profile_permissions(current_user)
        
        profile = db.query(ProfileRole).filter_by(id=profile_id).first()
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile with ID {profile_id} not found"
            )
        
        # Validate permissions against department
        validate_permissions(permission_update.default_permissions, profile.department)
        
        # Update profile permissions
        profile.default_permissions = permission_update.default_permissions
        db.commit()
        db.refresh(profile)
        
        # Update existing users with this profile to have new default permissions
        users = db.query(UserDetails).filter_by(profile_role_id=profile_id).all()
        updated_users = 0
        
        for user in users:
            if user.permission:
                # Update user permissions with new defaults
                for perm in permission_update.default_permissions:
                    if hasattr(user.permission, perm):
                        setattr(user.permission, perm, True)
                updated_users += 1
        
        db.commit()
        
        return {
            "message": f"Permissions updated for profile '{profile.name}'",
            "profile_id": profile_id,
            "default_permissions": permission_update.default_permissions,
            "updated_users": updated_users
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
            detail=f"Error updating profile permissions: {str(e)}"
        )


@router.get("/{profile_id}/users")
def get_profile_users(
    profile_id: int,
    active_only: bool = Query(True),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """Get all users with a specific profile"""
    try:
        profile = db.query(ProfileRole).filter_by(id=profile_id).first()
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile with ID {profile_id} not found"
            )
        
        query = db.query(UserDetails).filter_by(profile_role_id=profile_id)
        if active_only:
            query = query.filter(UserDetails.is_active == True)
        
        total_count = query.count()
        users = query.offset(skip).limit(limit).all()
        
        users_data = []
        for user in users:
            users_data.append({
                "employee_code": user.employee_code,
                "name": user.name,
                "email": user.email,
                "phone_number": user.phone_number,
                "is_active": user.is_active,
                "branch_id": user.branch_id,
                "date_of_joining": user.date_of_joining,
                "created_at": user.created_at
            })
        
        return {
            "profile": {
                "id": profile.id,
                "name": profile.name,
                "department_name": profile.department.name if profile.department else None
            },
            "users": users_data,
            "pagination": {
                "total": total_count,
                "skip": skip,
                "limit": limit,
                "pages": (total_count + limit - 1) // limit if limit > 0 else 1
            }
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
            detail=f"Error fetching profile users: {str(e)}"
        )


# Utility Endpoints

@router.get("/hierarchy-levels/available")
def get_available_hierarchy_levels(
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """Get available hierarchy levels and their typical roles"""
    hierarchy_info = {
        1: {
            "level": 1,
            "description": "Super Administrator",
            "typical_roles": ["SUPERADMIN"],
            "permissions": "Full system access"
        },
        2: {
            "level": 2,
            "description": "Senior Management",
            "typical_roles": ["COMPLIANCE", "BRANCH_MANAGER"],
            "permissions": "Department and branch management"
        },
        3: {
            "level": 3,
            "description": "Department Heads",
            "typical_roles": ["HR", "SALES_MANAGER"],
            "permissions": "Team management and operations"
        },
        4: {
            "level": 4,
            "description": "Team Leaders",
            "typical_roles": ["TL", "RESEARCHER"],
            "permissions": "Team coordination and specialized tasks"
        },
        5: {
            "level": 5,
            "description": "Senior Associates",
            "typical_roles": ["SBA"],
            "permissions": "Advanced operational tasks"
        },
        6: {
            "level": 6,
            "description": "Associates",
            "typical_roles": ["BA"],
            "permissions": "Basic operational tasks"
        }
    }
    
    return {
        "hierarchy_levels": hierarchy_info,
        "max_level": 6,
        "min_level": 1
    }

# Legacy Support (for backward compatibility)
@router.get("/legacy/user-roles", deprecated=True)
def get_legacy_user_roles(db: Session = Depends(get_db)):
    """
    Legacy endpoint for backward compatibility.
    Returns profile names instead of UserRoleEnum values.
    """
    try:
        profiles = db.query(ProfileRole).filter(ProfileRole.is_active == True).all()
        role_names = [profile.name for profile in profiles]
        
        return {
            "roles": role_names,
            "message": "This endpoint is deprecated. Use /profile-roles/ instead.",
            "migration_note": "UserRoleEnum has been replaced with ProfileRole system"
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching legacy roles: {str(e)}"
        )


@router.get("/legacy/recommendation-type")
def get_recommendation_types(db: Session = Depends(get_db)):
    """Get recommendation types (unchanged from original)"""
    from db.models import RecommendationType
    return [role.value for role in RecommendationType]



