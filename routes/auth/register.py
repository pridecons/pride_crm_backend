# routes/auth/register.py - Complete User CRUD API

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
import hashlib
from typing import List
import bcrypt

from db.connection import get_db
from db.models import UserDetails, BranchDetails, PermissionDetails, UserRoleEnum
from db.Schema.register import UserBase, UserCreate, UserUpdate, UserOut

router = APIRouter(
    prefix="/users",
    tags=["users"],
)

# Password hashing - Fixed bcrypt handling
def hash_password(password: str) -> str:
    """Hash password with bcrypt - fixed version"""
    try:
        # Use bcrypt directly
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')
    except Exception as e:
        # Fallback to SHA-256
        print(f"Bcrypt error, falling back to SHA-256: {e}")
        return hashlib.sha256(password.encode()).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password with bcrypt - fixed version"""
    try:
        # Try bcrypt first
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception as e:
        # Fallback to SHA-256
        print(f"Bcrypt verify error, falling back to SHA-256: {e}")
        return hashlib.sha256(plain_password.encode()).hexdigest() == hashed_password


def validate_hierarchy_requirements(role: UserRoleEnum, branch_id: int = None, 
                                   sales_manager_id: str = None, tl_id: str = None, db: Session = None):
    """Validate hierarchy requirements based on role"""
    
    # SUPERADMIN doesn't need anything
    if role == UserRoleEnum.SUPERADMIN:
        return None, None, None
    
    if role == UserRoleEnum.RESEARCHER:
        return None, None, None
    
    # BRANCH MANAGER needs only branch_id
    if role == UserRoleEnum.BRANCH_MANAGER:
        if not branch_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Branch Manager requires branch_id"
            )
        # Validate branch exists
        branch = db.query(BranchDetails).filter_by(id=branch_id).first()
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Branch does not exist"
            )
        return branch_id, None, None
    
    # HR and SALES_MANAGER need only branch_id
    if role == UserRoleEnum.HR or role == UserRoleEnum.SALES_MANAGER:
        if not branch_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{role.value} requires branch_id"
            )
        # Validate branch exists
        branch = db.query(BranchDetails).filter_by(id=branch_id).first()
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Branch does not exist"
            )
        return branch_id, None, None
    
    # TL needs branch_id and sales_manager_id
    if role == UserRoleEnum.TL:
        if not branch_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TL requires branch_id"
            )
        if not sales_manager_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TL requires sales_manager_id"
            )
        
        # Validate branch exists
        branch = db.query(BranchDetails).filter_by(id=branch_id).first()
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Branch does not exist"
            )
        
        # Validate sales manager exists and has correct role
        sales_manager = db.query(UserDetails).filter_by(employee_code=sales_manager_id).first()
        if not sales_manager:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sales Manager not found"
            )
        if sales_manager.role != UserRoleEnum.SALES_MANAGER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="sales_manager_id must be a SALES_MANAGER"
            )
        if sales_manager.branch_id != branch_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sales Manager must be in the same branch"
            )
        
        return branch_id, sales_manager_id, None
    
    # SBA and BA need branch_id, sales_manager_id, and tl_id
    if role == UserRoleEnum.SBA or role == UserRoleEnum.BA:
        if not branch_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{role.value} requires branch_id"
            )
        if not sales_manager_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{role.value} requires sales_manager_id"
            )
        if not tl_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{role.value} requires tl_id"
            )
        
        # Validate branch exists
        branch = db.query(BranchDetails).filter_by(id=branch_id).first()
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Branch does not exist"
            )
        
        # Validate sales manager
        sales_manager = db.query(UserDetails).filter_by(employee_code=sales_manager_id).first()
        if not sales_manager:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sales Manager not found"
            )
        if sales_manager.role != UserRoleEnum.SALES_MANAGER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="sales_manager_id must be a SALES_MANAGER"
            )
        if sales_manager.branch_id != branch_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sales Manager must be in the same branch"
            )
        
        # Validate TL
        tl = db.query(UserDetails).filter_by(employee_code=tl_id).first()
        if not tl:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TL not found"
            )
        if tl.role != UserRoleEnum.TL:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tl_id must be a TL"
            )
        if tl.branch_id != branch_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TL must be in the same branch"
            )
        if tl.sales_manager_id != sales_manager_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TL must report to the same Sales Manager"
            )
        
        return branch_id, sales_manager_id, tl_id
    
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unknown role: {role.value}"
    )


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
        "sales_manager_id": user.sales_manager_id,
        "tl_id": user.tl_id,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


# CREATE USER
@router.post("/", status_code=status.HTTP_201_CREATED)
def create_user(user_in: UserCreate, db: Session = Depends(get_db)):
    """Create user with hierarchy validation"""
    
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

    # Validate role
    try:
        role_enum = UserRoleEnum(user_in.role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Valid roles: {[r.value for r in UserRoleEnum]}"
        )
    
    # Validate hierarchy requirements
    branch_id, sales_manager_id, tl_id = validate_hierarchy_requirements(
        role_enum, 
        user_in.branch_id,
        user_in.sales_manager_id,
        user_in.tl_id,
        db
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
        sales_manager_id=sales_manager_id,
        tl_id=tl_id,
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


# GET ALL USERS
@router.get("/")
def get_all_users(
    skip: int = 0,
    limit: int = 100,
    active_only: bool = False,
    branch_id: int = None,
    role: str = None,
    search: str = None,
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
        
        if search:
            query = query.filter(
                UserDetails.name.ilike(f"%{search}%") |
                UserDetails.email.ilike(f"%{search}%") |
                UserDetails.phone_number.ilike(f"%{search}%") |
                UserDetails.employee_code.ilike(f"%{search}%")
            )
        
        total_count = query.count()
        users = query.offset(skip).limit(limit).all()
        
        # Serialize users manually to handle enum properly
        serialized_users = [serialize_user(user) for user in users]
        
        return {
            "data": serialized_users,
            "pagination": {
                "total": total_count,
                "skip": skip,
                "limit": limit,
                "pages": (total_count + limit - 1) // limit
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching users: {str(e)}"
        )


# GET USER BY ID
@router.get("/{employee_code}")
def get_user_by_id(employee_code: str, db: Session = Depends(get_db)):
    """Get user by employee code"""
    try:
        user = db.query(UserDetails).filter_by(employee_code=employee_code).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        return serialize_user(user)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching user: {str(e)}"
        )


# UPDATE USER
@router.put("/{employee_code}")
def update_user(employee_code: str, user_update: UserUpdate, db: Session = Depends(get_db)):
    """Update user details with hierarchy validation"""
    try:
        # Find user
        user = db.query(UserDetails).filter_by(employee_code=employee_code).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Check unique constraints (excluding current user)
        if user_update.phone_number and user_update.phone_number != user.phone_number:
            existing_phone = db.query(UserDetails).filter(
                UserDetails.phone_number == user_update.phone_number,
                UserDetails.employee_code != employee_code
            ).first()
            if existing_phone:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Phone number already exists"
                )
        
        if user_update.email and user_update.email != user.email:
            existing_email = db.query(UserDetails).filter(
                UserDetails.email == user_update.email,
                UserDetails.employee_code != employee_code
            ).first()
            if existing_email:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already exists"
                )
        
        # Validate role change if provided
        if user_update.role:
            try:
                new_role_enum = UserRoleEnum(user_update.role)
                
                # Validate hierarchy requirements for new role
                branch_id, sales_manager_id, tl_id = validate_hierarchy_requirements(
                    new_role_enum,
                    user_update.branch_id or user.branch_id,
                    user_update.sales_manager_id or user.sales_manager_id,
                    user_update.tl_id or user.tl_id,
                    db
                )
                
                # Update hierarchy fields
                user.role = new_role_enum
                user.branch_id = branch_id
                user.sales_manager_id = sales_manager_id
                user.tl_id = tl_id
                
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid role. Valid roles: {[r.value for r in UserRoleEnum]}"
                )
        
        # Update other fields
        update_fields = {
            'phone_number', 'email', 'name', 'father_name', 'is_active',
            'experience', 'date_of_joining', 'date_of_birth', 'pan', 'aadhaar',
            'address', 'city', 'state', 'pincode', 'comment'
        }
        
        for field in update_fields:
            if hasattr(user_update, field):
                value = getattr(user_update, field)
                if value is not None:
                    setattr(user, field, value)
        
        # Update password if provided
        if user_update.password:
            user.password = hash_password(user_update.password)
        
        # Update timestamp
        user.updated_at = datetime.utcnow()
        
        db.commit()
        db.refresh(user)
        
        return serialize_user(user)
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating user: {str(e)}"
        )


# DELETE USER (Soft Delete)
@router.delete("/{employee_code}")
def delete_user(employee_code: str, db: Session = Depends(get_db)):
    """Soft delete user (set is_active to False)"""
    try:
        user = db.query(UserDetails).filter_by(employee_code=employee_code).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Soft delete - set is_active to False
        user.is_active = False
        user.updated_at = datetime.utcnow()
        
        db.commit()
        
        return {
            "message": f"User {employee_code} has been deactivated successfully",
            "employee_code": employee_code,
            "deleted_at": user.updated_at
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting user: {str(e)}"
        )


# RESET PASSWORD
@router.post("/{employee_code}/reset-password")
def reset_user_password(employee_code: str, password_data: dict, db: Session = Depends(get_db)):
    """Reset user password"""
    try:
        user = db.query(UserDetails).filter_by(employee_code=employee_code).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        new_password = password_data.get('new_password')
        if not new_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="new_password field is required"
            )
        
        if len(new_password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 6 characters long"
            )
        
        user.password = hash_password(new_password)
        user.updated_at = datetime.utcnow()
        
        db.commit()
        
        return {
            "message": f"Password for user {employee_code} has been reset successfully",
            "employee_code": employee_code,
            "updated_at": user.updated_at
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error resetting password: {str(e)}"
        )

