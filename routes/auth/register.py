# routes/auth/register.py - Complete User CRUD API

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
import hashlib
from typing import List
import bcrypt

from db.connection import get_db
from db.models import UserDetails, BranchDetails, PermissionDetails
from db.Schema.register import UserBase, UserCreate, UserUpdate, UserOut
from utils.validation_utils import validate_user_data

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


def serialize_user(user: UserDetails) -> dict:
    """Serialize user object to dictionary with proper enum handling"""
    return {
        "employee_code": user.employee_code,
        "phone_number": user.phone_number,
        "email": user.email,
        "name": user.name,
        "role_id": user.role_id.value if hasattr(user.role_id, 'value') else str(user.role_id),
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
    
    user_data = user_in.dict()
    validate_user_data(db, user_data)    

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
        role_id=user_in.role_id,
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
        branch_id=user_in.branch_id,
    )
    
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
        
        # Create default permissions based on role_id
        default_perms = PermissionDetails.get_default_permissions(user_in.role_id)
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
    role_id: str = None,
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
        
        if role_id:
            try:
                role_enum = role_id
                query = query.filter(UserDetails.role_id == role_enum)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid role_id. Valid roles"
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
        
        # user_data = {
        #     'email': user_update.email,
        #     'phone_number': user_update.phone_number,
        #     'pan':
        # }
        # validate_user_data(db, user_data)
        
        # Validate role_id change if provided
        if user_update.role_id:
            try:
                # Update hierarchy fields
                user.role_id = user_update.role_id
                user.branch_id = user_update.branch_id or user.branch_id,
                
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid role_id. Valid roles"
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

