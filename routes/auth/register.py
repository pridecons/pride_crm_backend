# routes/auth/register.py - Complete User CRUD API (role->department auto mapping)

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
import hashlib
import bcrypt
from typing import Optional

from db.connection import get_db
from db.models import UserDetails, ProfileRole, PermissionDetails, BranchDetails
from db.Schema.register import UserCreate, UserUpdate
from utils.validation_utils import validate_user_data
from sqlalchemy.exc import IntegrityError
from routes.auth.auth_dependency import get_current_user

router = APIRouter(
    prefix="/users",
    tags=["users"],
)

# ---------------- Password Utils ----------------
def hash_password(password: str) -> str:
    """Hash password with bcrypt - fixed version"""
    try:
        salt = bcrypt.gensalts()
    except AttributeError:
        salt = bcrypt.gensalt()
    try:
        hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
        return hashed.decode("utf-8")
    except Exception as e:
        print(f"Bcrypt error, falling back to SHA-256: {e}")
        return hashlib.sha256(password.encode()).hexdigest()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password with bcrypt - fixed version"""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception as e:
        print(f"Bcrypt verify error, falling back to SHA-256: {e}")
        return hashlib.sha256(plain_password.encode()).hexdigest() == hashed_password

# ---------------- Small helper ----------------
def _department_id_for_role(db: Session, role_id: int) -> Optional[int]:
    """
    Return department_id for a given ProfileRole id.
    If role has no department, returns None.
    """
    role = db.query(ProfileRole).filter(ProfileRole.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail=f"ProfileRole {role_id} not found")
    # Assumes ProfileRole has a department_id column/relationship
    return getattr(role, "department_id", None)

# ---------------- Serializers ----------------
def serialize_user(user: UserDetails) -> dict:
    """Serialize user object to dictionary with proper enum handling"""
    return {
        "employee_code": user.employee_code,
        "phone_number": user.phone_number,
        "email": user.email,
        "name": user.name,
        "role_id": user.role_id.value if hasattr(user.role_id, "value") else str(user.role_id),
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
        "department_id": user.department_id,
        "profile_role": (
            {
                "id": int(user.role_id),
                "name": getattr(user, "role_name", None) or getattr(user.profile_role, "name", None),
                "hierarchy_level": getattr(user.profile_role, "hierarchy_level", None),
            }
            if user.role_id is not None
            else None
        ),
        "department": (
            {"id": user.department_id, "name": getattr(user.department, "name", None)}
            if user.department_id is not None
            else None
        ),
    }

# ---------------- CREATE ----------------
@router.post("/", status_code=status.HTTP_201_CREATED)
def create_user(user_in: UserCreate, db: Session = Depends(get_db)):
    """Create user with hierarchy validation. department_id is derived from role_id."""
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

    # Validate role_id and derive department_id from role
    try:
        role_id_val = int(user_in.role_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="role_id must be an integer")
    department_id_val = _department_id_for_role(db, role_id_val)

    hashed_pw = hash_password(user_in.password)

    user = UserDetails(
        employee_code=emp_code,
        phone_number=user_in.phone_number,
        email=user_in.email,
        name=user_in.name,
        password=hashed_pw,
        role_id=role_id_val,
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
        # 🔽 Always derived from role_id:
        department_id=department_id_val,
    )

    try:
        db.add(user)
        db.commit()
        db.refresh(user)
        return serialize_user(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating user: {str(e)}")

# ---------------- Helpers for visibility ----------------
def _manager_branch_id(u: UserDetails) -> Optional[int]:
    """Prefer managed branch; fallback to own branch_id."""
    if u.manages_branch:
        return u.manages_branch.id
    return u.branch_id

# ---------------- LIST (scoped by role) ----------------
@router.get("/")
def get_all_users(
    skip: int = 0,
    limit: int = 100,
    active_only: bool = False,
    branch_id: Optional[int] = None,
    role_id: Optional[str] = None,
    senior_profile_id: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user),
):
    """
    Get all users with filtering options.

    Visibility:
      - SUPERADMIN: sees all users (no branch restriction).
      - BRANCH_MANAGER: sees ONLY users in their branch (managed branch preferred).
      - HR: sees ONLY users in their own branch.
      - Others: unchanged (no extra restriction beyond provided filters).
    """
    try:
        query = db.query(UserDetails)

        # ---------- Role-based visibility ----------
        role_name = (getattr(current_user, "role_name", None) or "").upper()

        if role_name == "SUPERADMIN":
            pass
        elif role_name == "BRANCH_MANAGER":
            b_id = _manager_branch_id(current_user)
            if b_id is None:
                query = query.filter(UserDetails.employee_code == "__none__")
            else:
                query = query.filter(UserDetails.branch_id == b_id)
        elif role_name == "HR":
            if current_user.branch_id is None:
                query = query.filter(UserDetails.employee_code == "__none__")
            else:
                query = query.filter(UserDetails.branch_id == current_user.branch_id)

        # ---------- Existing filters ----------
        if active_only:
            query = query.filter(UserDetails.is_active.is_(True))

        if branch_id is not None:
            query = query.filter(UserDetails.branch_id == branch_id)

        if role_id:
            query = query.filter(UserDetails.role_id == role_id)

        if senior_profile_id is not None:
            query = query.filter(UserDetails.senior_profile_id == senior_profile_id)

        if search:
            ilike = f"%{search}%"
            query = query.filter(
                (UserDetails.name.ilike(ilike))
                | (UserDetails.email.ilike(ilike))
                | (UserDetails.phone_number.ilike(ilike))
                | (UserDetails.employee_code.ilike(ilike))
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
                "pages": (total_count + limit - 1) // limit,
            },
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
    Update user details.

    Key behavior:
      - department_id is ALWAYS derived from role_id (if role_id is updated).
      - If role_id is not changed, department_id remains as-is.
      - Any department_id sent in payload is ignored.
    """
    try:
        user = db.query(UserDetails).filter_by(employee_code=employee_code).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # ---------- 1) Validate formats + uniqueness for the fields being changed ----------
        validate_payload = {}
        if user_update.email is not None:
            validate_payload["email"] = user_update.email
        if user_update.phone_number is not None:
            validate_payload["phone_number"] = user_update.phone_number
        if user_update.pan is not None:
            validate_payload["pan"] = user_update.pan

        if validate_payload:
            validate_user_data(db, validate_payload, exclude_user_id=employee_code)

        # ---------- 2) Role validation & department mapping ----------
        if user_update.role_id is not None:
            try:
                role_id_val = int(user_update.role_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="role_id must be an integer")
            # validate role exists and derive department
            dept_id_val = _department_id_for_role(db, role_id_val)
            user.role_id = role_id_val
            user.department_id = dept_id_val  # 🔽 auto-set from role

        # ---------- 3) Branch ----------
        if user_update.branch_id is not None:
            user.branch_id = user_update.branch_id

        # ---------- 4) Senior profile validation ----------
        if user_update.senior_profile_id is not None:
            senior_code = str(user_update.senior_profile_id)
            if senior_code == employee_code:
                raise HTTPException(status_code=400, detail="senior_profile_id cannot be self")
            senior = db.query(UserDetails).filter(UserDetails.employee_code == senior_code).first()
            if not senior:
                raise HTTPException(status_code=404, detail=f"senior_profile_id '{senior_code}' not found")
            user.senior_profile_id = senior_code

        # ---------- 5) Permissions ----------
        if user_update.permissions is not None:
            valid = {p.value for p in PermissionDetails}
            invalid = [p for p in (user_update.permissions or []) if p not in valid]
            if invalid:
                raise HTTPException(status_code=400, detail=f"Invalid permission(s): {invalid}")
            seen, cleaned = set(), []
            for p in (user_update.permissions or []):
                if p not in seen:
                    seen.add(p)
                    cleaned.append(p)
            user.permissions = cleaned

        # ---------- 6) Generic field updates ----------
        field_names = (
            "phone_number",
            "email",
            "name",
            "father_name",
            "is_active",
            "experience",
            "date_of_joining",
            "date_of_birth",
            "pan",
            "aadhaar",
            "address",
            "city",
            "state",
            "pincode",
            "comment",
            "vbc_extension_id",
            "vbc_user_username",
            "vbc_user_password",
        )
        for fname in field_names:
            value = getattr(user_update, fname, None)
            if value is not None:
                setattr(user, fname, value)

        # 🔒 Ignore any department_id coming from payload on purpose:
        # if getattr(user_update, "department_id", None) is not None: pass

        # ---------- 7) Password ----------
        if getattr(user_update, "password", None):
            user.password = hash_password(user_update.password)

        db.commit()
        db.refresh(user)
        return serialize_user(user)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating user: {str(e)}")

@router.delete("/{employee_code}")
def delete_user(
    employee_code: str,
    hard: bool = False,
    force_unassign: bool = False,
    db: Session = Depends(get_db),
):
    """
    Delete a user.

    - Soft delete (default): sets is_active=False.
    - Hard delete: removes the row from DB.
      * If referenced as Branch Manager or as senior_profile_id by others,
        pass force_unassign=true to null those references automatically.
    """
    try:
        user = db.query(UserDetails).filter_by(employee_code=employee_code).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if not hard:
            user.is_active = False
            user.updated_at = datetime.utcnow()
            db.commit()
            return {
                "message": f"User {employee_code} has been deactivated successfully",
                "employee_code": employee_code,
                "deleted_at": user.updated_at,
                "mode": "soft",
            }

        branches_managed = db.query(BranchDetails).filter(BranchDetails.manager_id == employee_code).all()
        subordinates = db.query(UserDetails).filter(UserDetails.senior_profile_id == employee_code).all()

        if (branches_managed or subordinates) and not force_unassign:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Cannot hard delete: user is referenced by other records. "
                    "Reassign/clear references or call with force_unassign=true."
                ),
            )

        if force_unassign:
            for b in branches_managed:
                b.manager_id = None
            for s in subordinates:
                s.senior_profile_id = None

        db.delete(user)
        db.commit()
        return {
            "message": f"User {employee_code} has been hard-deleted successfully",
            "employee_code": employee_code,
            "mode": "hard",
            "force_unassign": force_unassign,
            "cleared_refs": {
                "branches_managed": len(branches_managed),
                "subordinates": len(subordinates),
            },
        }

    except HTTPException:
        raise
    except IntegrityError as ie:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Integrity error while deleting user; reassign or clear related records first. {ie}",
        )
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

        new_password = password_data.get("new_password")
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
            "updated_at": user.updated_at,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error resetting password: {str(e)}")
