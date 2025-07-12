# routes/auth/register.py - Fixed version with proper serialization

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from passlib.context import CryptContext
import hashlib
from typing import List

from db.connection import get_db
from db.models import UserDetails, BranchDetails, PermissionDetails, UserRoleEnum
from db.Schema.register import UserBase, UserCreate, UserUpdate, UserOut

router = APIRouter(
    prefix="/users",
    tags=["users"],
)

# Password hashing
try:
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
except ImportError:
    pwd_context = None


def hash_password(password: str) -> str:
    """Hash password with bcrypt or fallback to SHA-256"""
    if pwd_context:
        return pwd_context.hash(password)
    else:
        return hashlib.sha256(password.encode()).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password with bcrypt or fallback method"""
    if pwd_context:
        return pwd_context.verify(plain_password, hashed_password)
    else:
        return hashlib.sha256(plain_password.encode()).hexdigest() == hashed_password


def validate_hierarchy_and_manager(role: UserRoleEnum, manager_id: str = None, branch_id: int = None, db: Session = None):
    """Validate user hierarchy and manager assignment based on flowchart"""
    
    # SUPERADMIN doesn't need manager or branch
    if role == UserRoleEnum.SUPERADMIN:
        return None, None
    
    # BRANCH MANAGER needs SUPERADMIN as manager
    if role == UserRoleEnum.BRANCH_MANAGER:
        if not branch_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Branch Manager must be assigned to a branch"
            )
        
        # Find SUPERADMIN as manager
        superadmin = db.query(UserDetails).filter_by(role=UserRoleEnum.SUPERADMIN).first()
        if not superadmin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No SUPERADMIN found. Create SUPERADMIN first."
            )
        return superadmin.employee_code, branch_id
    
    # For other roles, validate manager exists and has correct role
    if not manager_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Manager is required for role {role.value}"
        )
    
    manager = db.query(UserDetails).filter_by(employee_code=manager_id).first()
    if not manager:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Manager with employee_code '{manager_id}' does not exist"
        )
    
    # Validate manager role based on hierarchy
    required_manager_role = {
        UserRoleEnum.SALES_MANAGER: UserRoleEnum.BRANCH_MANAGER,
        UserRoleEnum.HR: UserRoleEnum.BRANCH_MANAGER,
        UserRoleEnum.TL: UserRoleEnum.SALES_MANAGER,
        UserRoleEnum.BA: UserRoleEnum.TL,
        UserRoleEnum.SBA: UserRoleEnum.TL
    }
    
    expected_role = required_manager_role.get(role)
    if expected_role and manager.role != expected_role:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{role.value} must report to {expected_role.value}, but manager is {manager.role.value}"
        )
    
    # Inherit branch from manager if not specified
    if not branch_id:
        branch_id = manager.branch_id
    
    return manager_id, branch_id


def serialize_user(user: UserDetails) -> dict:
    """Serialize user object to dictionary with proper enum handling"""
    return {
        "employee_code": user.employee_code,
        "phone_number": user.phone_number,
        "email": user.email,
        "name": user.name,
        "role": user.role.value if hasattr(user.role, 'value') else str(user.role),
        "father_name": user.father_name,
        "is_active": user.is_active,
        "experience": user.experience,
        "date_of_joining": user.date_of_joining,
        "date_of_birth": user.date_of_birth,
        "pan": user.pan,
        "aadhaar": user.aadhaar,
        "address": user.address,
        "city": user.city,
        "state": user.state,
        "pincode": user.pincode,
        "comment": user.comment,
        "branch_id": user.branch_id,
        "manager_id": user.manager_id,
        "sales_manager_id": user.sales_manager_id,
        "tl_id": user.tl_id,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_user(user_in: UserCreate, db: Session = Depends(get_db)):
    """Create user with automatic hierarchy validation"""
    
    # Ensure unique constraints
    if db.query(UserDetails).filter_by(phone_number=user_in.phone_number).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number already registered"
        )
    if db.query(UserDetails).filter_by(email=user_in.email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Validate role and hierarchy
    try:
        role_enum = UserRoleEnum(user_in.role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Valid roles: {[r.value for r in UserRoleEnum]}"
        )
    
    # Validate hierarchy and get correct manager/branch
    manager_id, branch_id = validate_hierarchy_and_manager(
        role_enum, 
        user_in.manager_id, 
        user_in.branch_id, 
        db
    )
    
    # Validate branch exists if specified
    if branch_id:
        branch = db.query(BranchDetails).filter_by(id=branch_id).first()
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Branch does not exist"
            )

    # Auto-generate employee_code
    count = db.query(UserDetails).count() or 0
    emp_code = f"EMP{count+1:03d}"
    
    # Check if employee code already exists (rare edge case)
    while db.query(UserDetails).filter_by(employee_code=emp_code).first():
        count += 1
        emp_code = f"EMP{count+1:03d}"

    # Hash password
    hashed_pw = hash_password(user_in.password)
    
    # Create user
    user = UserDetails(
        employee_code=emp_code,
        phone_number=user_in.phone_number,
        email=user_in.email,
        name=user_in.name,
        password=hashed_pw,
        role=role_enum,
        father_name=user_in.father_name,
        is_active=user_in.is_active,
        experience=user_in.experience,
        date_of_joining=user_in.date_of_joining,
        date_of_birth=user_in.date_of_birth,
        pan=user_in.pan,
        aadhaar=user_in.aadhaar,
        address=user_in.address,
        city=user_in.city,
        state=user_in.state,
        pincode=user_in.pincode,
        comment=user_in.comment,
        branch_id=branch_id,
        manager_id=manager_id,
    )
    
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
        
        # Create default permissions based on role
        default_perms = PermissionDetails.get_default_permissions(role_enum)
        permission = PermissionDetails(
            user_id=user.employee_code,
            **default_perms
        )
        db.add(permission)
        db.commit()
        
        return serialize_user(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating user: {str(e)}"
        )


@router.post("/superadmin", status_code=status.HTTP_201_CREATED)
def create_superadmin(user_in: UserCreate, db: Session = Depends(get_db)):
    """Create SUPERADMIN - special endpoint for first user"""
    
    # Check if SUPERADMIN already exists
    existing_superadmin = db.query(UserDetails).filter_by(role=UserRoleEnum.SUPERADMIN).first()
    if existing_superadmin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SUPERADMIN already exists"
        )
    
    # Ensure unique constraints
    if db.query(UserDetails).filter_by(phone_number=user_in.phone_number).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number already registered"
        )
    if db.query(UserDetails).filter_by(email=user_in.email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Auto-generate employee_code
    emp_code = "EMP001"  # SUPERADMIN gets EMP001
    
    # Hash password
    hashed_pw = hash_password(user_in.password)
    
    # Create SUPERADMIN
    user = UserDetails(
        employee_code=emp_code,
        phone_number=user_in.phone_number,
        email=user_in.email,
        name=user_in.name,
        password=hashed_pw,
        role=UserRoleEnum.SUPERADMIN,
        father_name=user_in.father_name,
        is_active=user_in.is_active,
        experience=user_in.experience,
        date_of_joining=user_in.date_of_joining,
        date_of_birth=user_in.date_of_birth,
        pan=user_in.pan,
        aadhaar=user_in.aadhaar,
        address=user_in.address,
        city=user_in.city,
        state=user_in.state,
        pincode=user_in.pincode,
        comment=user_in.comment,
        branch_id=None,  # SUPERADMIN doesn't belong to any branch
        manager_id=None,  # SUPERADMIN has no manager
    )
    
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
        
        # Create SUPERADMIN permissions
        superadmin_perms = PermissionDetails.get_default_permissions(UserRoleEnum.SUPERADMIN)
        permission = PermissionDetails(
            user_id=user.employee_code,
            **superadmin_perms
        )
        db.add(permission)
        db.commit()
        
        return serialize_user(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating SUPERADMIN: {str(e)}"
        )


@router.get("/")
def get_all_users(
    skip: int = 0,
    limit: int = 100,
    active_only: bool = False,
    branch_id: int = None,
    role: str = None,
    db: Session = Depends(get_db),
):
    """Get all users with filtering options"""
    try:
        query = db.query(UserDetails)
        
        if active_only:
            query = query.filter(UserDetails.is_active == True)
        
        if branch_id:
            query = query.filter(UserDetails.branch_id == branch_id)
        
        if role:
            try:
                role_enum = UserRoleEnum(role)
                query = query.filter(UserDetails.role == role_enum)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid role. Valid roles: {[r.value for r in UserRoleEnum]}"
                )
        
        users = query.offset(skip).limit(limit).all()
        
        # Serialize users manually to handle enum properly
        serialized_users = [serialize_user(user) for user in users]
        
        return serialized_users
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching users: {str(e)}"
        )


@router.get("/hierarchy/{employee_code}")
def get_user_hierarchy(employee_code: str, db: Session = Depends(get_db)):
    """Get user's complete hierarchy (manager and subordinates)"""
    user = db.query(UserDetails).filter_by(employee_code=employee_code).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Get manager chain
    manager_chain = []
    current_user = user
    while current_user.manager:
        manager_chain.append({
            "employee_code": current_user.manager.employee_code,
            "name": current_user.manager.name,
            "role": current_user.manager.role.value if hasattr(current_user.manager.role, 'value') else str(current_user.manager.role)
        })
        current_user = current_user.manager
    
    # Get direct subordinates
    subordinates = [
        {
            "employee_code": sub.employee_code,
            "name": sub.name,
            "role": sub.role.value if hasattr(sub.role, 'value') else str(sub.role)
        }
        for sub in user.subordinates
    ]
    
    return {
        "user": {
            "employee_code": user.employee_code,
            "name": user.name,
            "role": user.role.value if hasattr(user.role, 'value') else str(user.role)
        },
        "manager_chain": manager_chain,
        "subordinates": subordinates
    }


@router.get("/roles")
def get_available_roles():
    """Get all available user roles"""
    return {
        "roles": [
            {
                "value": role.value,
                "name": role.value.replace("_", " "),
                "hierarchy_level": {
                    UserRoleEnum.SUPERADMIN: 1,
                    UserRoleEnum.BRANCH_MANAGER: 2,
                    UserRoleEnum.SALES_MANAGER: 3,
                    UserRoleEnum.HR: 3,
                    UserRoleEnum.TL: 4,
                    UserRoleEnum.BA: 5,
                    UserRoleEnum.SBA: 5
                }.get(role, 6)
            }
            for role in UserRoleEnum
        ]
    }


@router.get("/{employee_code}")
def get_user(employee_code: str, db: Session = Depends(get_db)):
    """Get a specific user by employee code"""
    user = db.query(UserDetails).filter_by(employee_code=employee_code).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return serialize_user(user)


@router.put("/{employee_code}")
def update_user(
    employee_code: str,
    user_in: UserUpdate,
    db: Session = Depends(get_db),
):
    """Update user with hierarchy validation"""
    user = db.query(UserDetails).filter_by(employee_code=employee_code).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Update only provided fields
    data = user_in.dict(exclude_unset=True)
    
    # If role is being changed, validate hierarchy
    if "role" in data:
        try:
            new_role = UserRoleEnum(data["role"])
            # Validate manager based on new role
            manager_id, branch_id = validate_hierarchy_and_manager(
                new_role, 
                data.get("manager_id", user.manager_id), 
                data.get("branch_id", user.branch_id), 
                db
            )
            data["manager_id"] = manager_id
            data["branch_id"] = branch_id
            data["role"] = new_role
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid role. Valid roles: {[r.value for r in UserRoleEnum]}"
            )
    
    # Validate branch if being updated
    if "branch_id" in data and data["branch_id"]:
        branch = db.query(BranchDetails).filter_by(id=data["branch_id"]).first()
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Branch does not exist"
            )
    
    # Check uniqueness for phone and email if being updated
    if "phone_number" in data:
        existing = db.query(UserDetails).filter_by(phone_number=data["phone_number"]).first()
        if existing and existing.employee_code != employee_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone number already exists"
            )
    
    if "email" in data:
        existing = db.query(UserDetails).filter_by(email=data["email"]).first()
        if existing and existing.employee_code != employee_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already exists"
            )
    
    # Hash password if being updated
    if "password" in data:
        data["password"] = hash_password(data["password"])
    
    # Apply updates
    for field, value in data.items():
        setattr(user, field, value)

    try:
        db.commit()
        db.refresh(user)
        return serialize_user(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating user: {str(e)}"
        )


@router.patch("/{employee_code}/status")
def toggle_user_status(
    employee_code: str,
    active: bool,
    db: Session = Depends(get_db),
):
    """Toggle user active/inactive status"""
    user = db.query(UserDetails).filter_by(employee_code=employee_code).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    user.is_active = active
    db.commit()
    db.refresh(user)
    
    return {
        "message": f"User {'activated' if active else 'deactivated'} successfully",
        "employee_code": employee_code,
        "is_active": active
    }


@router.delete("/{employee_code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    employee_code: str,
    db: Session = Depends(get_db),
):
    """Delete user (with cascade to subordinates)"""
    user = db.query(UserDetails).filter_by(employee_code=employee_code).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Don't allow deleting SUPERADMIN if other users exist
    if user.role == UserRoleEnum.SUPERADMIN:
        other_users = db.query(UserDetails).filter(
            UserDetails.employee_code != employee_code
        ).first()
        if other_users:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete SUPERADMIN while other users exist"
            )
    
    try:
        db.delete(user)
        db.commit()
        return None
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting user: {str(e)}"
        )