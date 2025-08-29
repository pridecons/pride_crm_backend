# routes/auth/register.py - Complete User CRUD API (with senior_profile_id everywhere)

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
import hashlib
import bcrypt
from typing import Optional

from db.connection import get_db
from db.models import UserDetails, ProfileRole, PermissionDetails 
from db.Schema.register import UserCreate, UserUpdate
from utils.validation_utils import validate_user_data
from sqlalchemy import func

router = APIRouter(
    prefix="/users",
    tags=["users"],
)

# ---------------- Password Utils ----------------
def hash_password(password: str) -> str:
    """Hash password with bcrypt - fixed version"""
    try:
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')
    except Exception as e:
        print(f"Bcrypt error, falling back to SHA-256: {e}")
        return hashlib.sha256(password.encode()).hexdigest()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password with bcrypt - fixed version"""
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception as e:
        print(f"Bcrypt verify error, falling back to SHA-256: {e}")
        return hashlib.sha256(plain_password.encode()).hexdigest() == hashed_password

# ---------------- Serializers ----------------
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
        "permissions": user.permissions,
        "senior_profile_id": getattr(user, "senior_profile_id", None),
        "vbc_extension_id": getattr(user, "vbc_extension_id", None),
        "vbc_user_username": getattr(user, "vbc_user_username", None),
        "vbc_user_password": getattr(user, "vbc_user_password", None),
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }

# ---------------- CREATE ----------------
@router.post("/", status_code=status.HTTP_201_CREATED)
def create_user(user_in: UserCreate, db: Session = Depends(get_db)):
    """Create user with hierarchy validation"""

    # Uniques
    if db.query(UserDetails).filter_by(phone_number=user_in.phone_number).first():
        raise HTTPException(status_code=400, detail="Phone number already registered")
    if db.query(UserDetails).filter_by(email=user_in.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user_data = user_in.model_dump()
    validate_user_data(db, user_data)

    # Auto-generate employee_code
    count = db.query(UserDetails).count() or 0
    emp_code = f"EMP{count+1:03d}"
    while db.query(UserDetails).filter_by(employee_code=emp_code).first():
        count += 1
        emp_code = f"EMP{count+1:03d}"

    hashed_pw = hash_password(user_in.password)

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
        senior_profile_id=user_in.senior_profile_id,
        permissions=user_in.permissions,
        vbc_extension_id=user_in.vbc_extension_id,
        vbc_user_username=user_in.vbc_user_username,
        vbc_user_password=user_in.vbc_user_password,
    )

    try:
        db.add(user)
        db.commit()
        db.refresh(user)
        return serialize_user(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating user: {str(e)}")

# ---------------- LIST ----------------
@router.get("/")
def get_all_users(
    skip: int = 0,
    limit: int = 100,
    active_only: bool = False,
    branch_id: Optional[int] = None,
    role_id: Optional[str] = None,
    senior_profile_id: Optional[int] = None,  # <--- new optional filter
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get all users with filtering options"""
    try:
        query = db.query(UserDetails)

        if active_only:
            query = query.filter(UserDetails.is_active == True)

        if branch_id is not None:
            query = query.filter(UserDetails.branch_id == branch_id)

        if role_id:
            query = query.filter(UserDetails.role_id == role_id)

        if senior_profile_id is not None:
            query = query.filter(UserDetails.senior_profile_id == senior_profile_id)

        if search:
            ilike = f"%{search}%"
            query = query.filter(
                (UserDetails.name.ilike(ilike)) |
                (UserDetails.email.ilike(ilike)) |
                (UserDetails.phone_number.ilike(ilike)) |
                (UserDetails.employee_code.ilike(ilike))
            )

        total_count = query.count()
        users = query.offset(skip).limit(limit).all()
        serialized_users = [serialize_user(u) for u in users]

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
        raise HTTPException(status_code=500, detail=f"Error fetching users: {str(e)}")

# ---------------- GET BY ID ----------------
@router.get("/{employee_code}")
def get_user_by_id(employee_code: str, db: Session = Depends(get_db)):
    """Get user by employee code"""
    try:
        user = db.query(UserDetails).filter_by(employee_code=employee_code).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return serialize_user(user)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching user: {str(e)}")

# ---------------- UPDATE ----------------
@router.put("/{employee_code}")
def update_user(employee_code: str, user_update: UserUpdate, db: Session = Depends(get_db)):
    """
    Update user details with:
      - format + cross-table uniqueness checks via validate_user_data (email/phone_number/pan)
      - role_id existence validation (ProfileRole.id is INT)
      - senior_profile_id existence & not-self check (string FK to employee_code)
      - permissions validated against PermissionDetails enum
      - bcrypt password hashing
    """
    try:
        user = db.query(UserDetails).filter_by(employee_code=employee_code).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # ---------- 1) Validate formats + uniqueness for the fields being changed ----------
        # Only validate fields that were provided in this request
        validate_payload = {}
        if user_update.email is not None:
            validate_payload["email"] = user_update.email
        if user_update.phone_number is not None:
            validate_payload["phone_number"] = user_update.phone_number
        if user_update.pan is not None:
            validate_payload["pan"] = user_update.pan

        if validate_payload:
            # Exclude the current user so updates to their own values don't false-positive
            validate_user_data(db, validate_payload, exclude_user_id=employee_code)

        # ---------- 2) Role validation (ProfileRole.id is INT) ----------
        if user_update.role_id is not None:
            try:
                role_id_val = int(user_update.role_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="role_id must be an integer")
            role = db.query(ProfileRole).filter(ProfileRole.id == role_id_val).first()
            if not role:
                raise HTTPException(status_code=404, detail=f"ProfileRole {role_id_val} not found")
            user.role_id = role_id_val

        # ---------- 3) Branch (int FK) ----------
        if user_update.branch_id is not None:
            user.branch_id = user_update.branch_id

        # ---------- 4) Senior profile validation (string FK to employee_code) ----------
        if user_update.senior_profile_id is not None:
            senior_code = str(user_update.senior_profile_id)
            if senior_code == employee_code:
                raise HTTPException(status_code=400, detail="senior_profile_id cannot be self")
            senior = db.query(UserDetails).filter(UserDetails.employee_code == senior_code).first()
            if not senior:
                raise HTTPException(status_code=404, detail=f"senior_profile_id '{senior_code}' not found")
            user.senior_profile_id = senior_code

        # ---------- 5) Permissions (ARRAY(String)) ----------
        if user_update.permissions is not None:
            valid = {p.value for p in PermissionDetails}
            invalid = [p for p in (user_update.permissions or []) if p not in valid]
            if invalid:
                raise HTTPException(status_code=400, detail=f"Invalid permission(s): {invalid}")
            # de-dupe while preserving order
            seen, cleaned = set(), []
            for p in (user_update.permissions or []):
                if p not in seen:
                    seen.add(p)
                    cleaned.append(p)
            user.permissions = cleaned

        # ---------- 6) Generic field updates ----------
        field_names = (
            'phone_number', 'email', 'name', 'father_name', 'is_active',
            'experience', 'date_of_joining', 'date_of_birth', 'pan', 'aadhaar',
            'address', 'city', 'state', 'pincode', 'comment',
            'vbc_extension_id', 'vbc_user_username', 'vbc_user_password'
        )
        for fname in field_names:
            value = getattr(user_update, fname, None)
            if value is not None:
                setattr(user, fname, value)

        # ---------- 7) Password ----------
        if user_update.password:
            user.password = hash_password(user_update.password)

        # Let onupdate=func.now() on the model set updated_at
        db.commit()
        db.refresh(user)
        return serialize_user(user)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating user: {str(e)}")

# ---------------- SOFT DELETE ----------------
@router.delete("/{employee_code}")
def delete_user(employee_code: str, db: Session = Depends(get_db)):
    """Soft delete user (set is_active to False)"""
    try:
        user = db.query(UserDetails).filter_by(employee_code=employee_code).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

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
        raise HTTPException(status_code=500, detail=f"Error deleting user: {str(e)}")

# ---------------- RESET PASSWORD ----------------
@router.post("/{employee_code}/reset-password")
def reset_user_password(employee_code: str, password_data: dict, db: Session = Depends(get_db)):
    """Reset user password"""
    try:
        user = db.query(UserDetails).filter_by(employee_code=employee_code).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        new_password = password_data.get('new_password')
        if not new_password:
            raise HTTPException(status_code=400, detail="new_password field is required")
        if len(new_password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters long")

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
        raise HTTPException(status_code=500, detail=f"Error resetting password: {str(e)}")


