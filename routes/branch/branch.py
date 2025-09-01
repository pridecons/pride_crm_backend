# routes/branch/branch.py

import os
import uuid
from typing import Optional, List
from datetime import date, datetime

from fastapi import (
    APIRouter, Depends, HTTPException, status,
    File, UploadFile, Form
)
from pydantic import constr, BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DisconnectionError

from db.connection import get_db
from db.models import BranchDetails, UserDetails, ProfileRole
from passlib.context import CryptContext
import re

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    return pwd_context.hash(password)

# ----------------- Simple Validators -----------------
PAN_REGEX = re.compile(r'^[A-Z]{5}[0-9]{4}[A-Z]$')
AADHAAR_REGEX = re.compile(r'^[0-9]{12}$')
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

def validate_pan_or_400(pan: str):
    if not pan or not PAN_REGEX.match(pan.strip().upper()):
        raise HTTPException(status_code=400, detail="Invalid PAN format (expected: ABCDE1234F)")
    return pan.strip().upper()

def validate_aadhaar_or_400(aadhaar: str):
    if not aadhaar or not AADHAAR_REGEX.match(aadhaar.strip()):
        raise HTTPException(status_code=400, detail="Invalid Aadhaar format (12 digits)")
    return aadhaar.strip()

def validate_email_or_400(email: str):
    if not EMAIL_REGEX.match(email.strip()):
        raise HTTPException(status_code=400, detail="Invalid email format")
    return email.strip()

# ----------------- Response Models -----------------
class BranchBase(BaseModel):
    name: constr(strip_whitespace=True, min_length=1, max_length=100)
    address: str
    authorized_person: constr(strip_whitespace=True, min_length=1, max_length=100)
    pan: constr(strip_whitespace=True, min_length=10, max_length=10)
    aadhaar: constr(strip_whitespace=True, min_length=12, max_length=12)
    active: bool = True

class BranchOut(BaseModel):
    id: int
    name: str
    address: str
    authorized_person: str
    agreement_url: Optional[str] = None
    active: bool
    manager_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ManagerInfo(BaseModel):
    employee_code: str
    name: str
    email: str
    phone_number: str

class UserInfo(BaseModel):
    employee_code: str
    name: str
    role: str
    role_id: Optional[int] = None
    role_name: Optional[str] = None
    email: str
    is_active: bool

class BranchDetailsOut(BaseModel):
    branch: BranchOut
    manager: Optional[ManagerInfo] = None
    users: List[UserInfo]
    total_users: int

class BranchWithManagerResponse(BaseModel):
    message: str
    branch: BranchOut
    manager: dict
    login_credentials: dict

router = APIRouter(
    prefix="/branches",
    tags=["branches"],
)

SAVE_DIR = "static/agreements"

@router.get("/", response_model=List[BranchOut])
def get_all_branches(
    skip: int = 0,
    limit: int = 100,
    active_only: bool = False,
    db: Session = Depends(get_db),
):
    """Get all branches with pagination and filtering"""
    try:
        query = db.query(BranchDetails)
        if active_only:
            query = query.filter(BranchDetails.active == True)
        branches = query.offset(skip).limit(limit).all()
        return branches
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching branches: {str(e)}"
        )

@router.get("/available-managers")
def get_available_managers(db: Session = Depends(get_db)):
    """Get list of users who can be branch managers"""
    try:
        branch_manager_profile = db.query(ProfileRole).filter_by(name="BRANCH_MANAGER").first()

        query = db.query(UserDetails).filter(
            UserDetails.is_active == True,
            ~UserDetails.employee_code.in_(
                db.query(BranchDetails.manager_id).filter(BranchDetails.manager_id.isnot(None))
            )
        )

        if branch_manager_profile:
            query = query.filter(UserDetails.role_id == branch_manager_profile.id)
        else:
            # Fallback if legacy attribute exists
            query = query.filter(getattr(UserDetails, "role", None) == "BRANCH_MANAGER")

        available_managers = query.all()

        return [
            {
                "employee_code": m.employee_code,
                "name": m.name,
                "email": m.email,
                "phone_number": m.phone_number,
                "role_name": getattr(m, 'role_name', None) or str(getattr(m, 'role', 'Unknown'))
            }
            for m in available_managers
        ]
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching available managers: {str(e)}"
        )

@router.get("/{branch_id}", response_model=BranchOut)
def get_branch(branch_id: int, db: Session = Depends(get_db)):
    """Get a specific branch by ID"""
    try:
        branch = db.query(BranchDetails).filter_by(id=branch_id).first()
        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")
        return branch
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching branch: {str(e)}")

@router.get("/{branch_id}/details", response_model=BranchDetailsOut)
def get_branch_details(branch_id: int, db: Session = Depends(get_db)):
    """Get detailed branch information including manager and users"""
    try:
        branch = db.query(BranchDetails).filter_by(id=branch_id).first()
        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")

        branch_data = {
            "id": branch.id,
            "name": branch.name,
            "address": branch.address,
            "authorized_person": branch.authorized_person,
            "agreement_url": branch.agreement_url,
            "active": branch.active,
            "manager_id": branch.manager_id,
            "created_at": branch.created_at,
            "updated_at": branch.updated_at,
        }

        manager_info = None
        if branch.manager_id:
            manager = db.query(UserDetails).filter_by(employee_code=branch.manager_id).first()
            if manager:
                manager_info = {
                    "employee_code": manager.employee_code,
                    "name": manager.name,
                    "email": manager.email,
                    "phone_number": manager.phone_number,
                }

        branch_users = db.query(UserDetails).filter_by(branch_id=branch_id).all()
        users_info = [
            {
                "employee_code": u.employee_code,
                "name": u.name,
                "role": str(getattr(u, 'role', 'Unknown')),
                "role_id": getattr(u, 'role_id', None),
                "role_name": getattr(u, 'role_name', None),
                "email": u.email,
                "is_active": u.is_active
            }
            for u in branch_users
        ]

        return {
            "branch": branch_data,
            "manager": manager_info,
            "users": users_info,
            "total_users": len(users_info)
        }
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching branch details: {str(e)}")

@router.post("/", response_model=BranchOut, status_code=status.HTTP_201_CREATED)
async def create_branch(
    name: constr(strip_whitespace=True, min_length=1, max_length=100) = Form(...),
    address: str = Form(...),
    authorized_person: constr(strip_whitespace=True, min_length=1, max_length=100) = Form(...),
    pan: constr(strip_whitespace=True, min_length=10, max_length=10) = Form(...),     # REQUIRED (NOT NULL IN DB)
    aadhaar: constr(strip_whitespace=True, min_length=12, max_length=12) = Form(...), # REQUIRED (NOT NULL IN DB)
    active: bool = Form(True),
    agreement_pdf: UploadFile = File(...),
    manager_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Create a new branch"""
    try:
        # Uniqueness: branch name
        existing = db.query(BranchDetails).filter_by(name=name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Branch with this name already exists")

        # Validate PAN/Aadhaar
        pan = validate_pan_or_400(pan)
        aadhaar = validate_aadhaar_or_400(aadhaar)

        # Validate manager if provided
        if manager_id:
            manager = db.query(UserDetails).filter_by(employee_code=manager_id).first()
            if not manager:
                raise HTTPException(status_code=404, detail="Manager not found")

            # Ensure user is a BRANCH_MANAGER (new/legacy)
            is_branch_manager = False
            if getattr(manager, 'role_name', None) == "BRANCH_MANAGER":
                is_branch_manager = True
            elif str(getattr(manager, 'role', '')) == "BRANCH_MANAGER":
                is_branch_manager = True
            else:
                # Try via ProfileRole id if we have it
                bm_role = db.query(ProfileRole).filter_by(name="BRANCH_MANAGER").first()
                if bm_role and manager.role_id == bm_role.id:
                    is_branch_manager = True

            if not is_branch_manager:
                raise HTTPException(status_code=400, detail="Selected user is not a branch manager")

        # Save agreement
        os.makedirs(SAVE_DIR, exist_ok=True)
        file_ext = os.path.splitext(agreement_pdf.filename)[1]
        unique_filename = f"{uuid.uuid4().hex}{file_ext}"
        agreement_path = os.path.join(SAVE_DIR, unique_filename)
        with open(agreement_path, "wb") as buffer:
            buffer.write(await agreement_pdf.read())

        # Create branch
        branch = BranchDetails(
            name=name,
            address=address,
            authorized_person=authorized_person,
            pan=pan,
            aadhaar=aadhaar,
            agreement_url=f"/{SAVE_DIR}/{unique_filename}",
            active=active,
            manager_id=manager_id
        )
        db.add(branch)
        db.commit()
        db.refresh(branch)

        # Update manager's branch_id if assigned
        if manager_id:
            manager = db.query(UserDetails).filter_by(employee_code=manager_id).first()
            if manager:
                manager.branch_id = branch.id
                db.commit()

        return branch

    except HTTPException:
        raise
    except Exception as e:
        # Cleanup file on error
        if 'agreement_path' in locals() and os.path.exists(agreement_path):
            try:
                os.remove(agreement_path)
            except OSError:
                pass
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating branch: {str(e)}")

@router.post("/create-with-manager", response_model=BranchWithManagerResponse, status_code=status.HTTP_201_CREATED)
async def create_branch_with_manager(
    # Branch Details
    branch_name: constr(strip_whitespace=True, min_length=1, max_length=100) = Form(...),
    branch_address: str = Form(...),
    authorized_person: constr(strip_whitespace=True, min_length=1, max_length=100) = Form(...),
    branch_active: bool = Form(True),
    agreement_pdf: UploadFile = File(...),

    # Manager Details
    manager_name: constr(strip_whitespace=True, min_length=1, max_length=100) = Form(...),
    manager_email: str = Form(...),
    manager_phone: constr(strip_whitespace=True, min_length=10, max_length=10) = Form(...),
    manager_father_name: constr(strip_whitespace=True, min_length=1, max_length=100) = Form(...),
    manager_experience: float = Form(...),
    manager_dob: date = Form(...),
    manager_password: constr(min_length=6) = Form(...),

    # Optional Manager Details
    manager_pan: Optional[constr(strip_whitespace=True, min_length=10, max_length=10)] = Form(None),
    manager_aadhaar: Optional[constr(strip_whitespace=True, min_length=12, max_length=12)] = Form(None),
    manager_address: Optional[str] = Form(None),
    manager_city: Optional[str] = Form(None),
    manager_state: Optional[str] = Form(None),
    manager_pincode: Optional[constr(strip_whitespace=True, min_length=6, max_length=6)] = Form(None),
    manager_comment: Optional[str] = Form(None),
    permissions: Optional[List[str]] = Form(None),

    db: Session = Depends(get_db),
):
    """Create a branch and its branch manager atomically, respecting the FK on manager_id."""
    try:
        # Basic validations
        validate_email_or_400(manager_email)
        if not (manager_phone.isdigit() and len(manager_phone) == 10):
            raise HTTPException(status_code=400, detail="Manager phone must be 10 digits")

        # Uniqueness checks
        if db.query(BranchDetails).filter_by(name=branch_name).first():
            raise HTTPException(status_code=400, detail="Branch with this name already exists")
        if db.query(UserDetails).filter_by(phone_number=manager_phone).first():
            raise HTTPException(status_code=400, detail="Manager phone number already registered")
        if db.query(UserDetails).filter_by(email=manager_email).first():
            raise HTTPException(status_code=400, detail="Manager email already registered")

        # Save agreement file
        os.makedirs(SAVE_DIR, exist_ok=True)
        file_ext = os.path.splitext(agreement_pdf.filename)[1]
        unique_filename = f"{uuid.uuid4().hex}{file_ext}"
        agreement_path = os.path.join(SAVE_DIR, unique_filename)
        with open(agreement_path, "wb") as buffer:
            buffer.write(await agreement_pdf.read())

        # Ensure BRANCH_MANAGER role exists
        branch_manager_profile = db.query(ProfileRole).filter_by(name="BRANCH_MANAGER").first()
        if not branch_manager_profile:
            ProfileRole.create_default_profiles(db)
            branch_manager_profile = db.query(ProfileRole).filter_by(name="BRANCH_MANAGER").first()
        if not branch_manager_profile:
            raise HTTPException(status_code=500, detail="BRANCH_MANAGER profile role not found")

        # Generate a unique employee_code
        count = db.query(UserDetails).count() or 0
        emp_code = f"EMP{count+1:03d}"
        while db.query(UserDetails).filter_by(employee_code=emp_code).first():
            count += 1
            emp_code = f"EMP{count+1:03d}"

        # 1) Create branch WITHOUT manager_id (avoid FK violation)
        branch = BranchDetails(
            name=branch_name,
            address=branch_address,
            authorized_person=authorized_person,
            agreement_url=f"/{SAVE_DIR}/{unique_filename}",
            active=branch_active,
            manager_id=None,  # important: keep null here
        )
        db.add(branch)
        db.flush()  # get branch.id

        # 2) Create manager user
        manager = UserDetails(
            employee_code=emp_code,
            phone_number=manager_phone,
            email=manager_email,
            name=manager_name,
            password=hash_password(manager_password),
            role_id=branch_manager_profile.id,
            father_name=manager_father_name,
            is_active=True,
            experience=manager_experience,
            date_of_joining=date.today(),
            date_of_birth=manager_dob,
            pan=(manager_pan.upper() if manager_pan else None),
            aadhaar=(manager_aadhaar if manager_aadhaar else None),
            address=manager_address,
            city=manager_city,
            state=manager_state,
            pincode=(manager_pincode if manager_pincode else None),
            comment=manager_comment,
            branch_id=branch.id,  # link manager to branch
            permissions=permissions
        )
        db.add(manager)
        db.flush()

        # 3) Now safely assign manager to branch (FK will pass)
        branch.manager_id = emp_code

        db.commit()
        db.refresh(branch)
        db.refresh(manager)

        branch_out = {
            "id": branch.id,
            "name": branch.name,
            "address": branch.address,
            "authorized_person": branch.authorized_person,
            "agreement_url": branch.agreement_url,
            "active": branch.active,
            "manager_id": branch.manager_id,
            "created_at": branch.created_at,
            "updated_at": branch.updated_at,
        }

        manager_response = {
            "employee_code": manager.employee_code,
            "name": manager.name,
            "email": manager.email,
            "phone_number": manager.phone_number,
            "role_id": manager.role_id,
            "role_name": getattr(manager, 'role_name', 'BRANCH_MANAGER'),
            "branch_id": manager.branch_id,
            "is_active": manager.is_active,
            "date_of_joining": manager.date_of_joining,
            "created_at": manager.created_at,
        }

        login_credentials = {
            "employee_code": manager.employee_code,
            "email": manager.email,
            "password": manager_password,
            "role_id": manager.role_id,
            "role_name": getattr(manager, 'role_name', 'BRANCH_MANAGER'),
        }

        return {
            "message": f"Branch '{branch.name}' and Branch Manager '{manager.name}' created successfully",
            "branch": branch_out,
            "manager": manager_response,
            "login_credentials": login_credentials,
        }

    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        db.rollback()
        if 'agreement_path' in locals() and os.path.exists(agreement_path):
            try:
                os.remove(agreement_path)
            except OSError:
                pass
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        if 'agreement_path' in locals() and os.path.exists(agreement_path):
            try:
                os.remove(agreement_path)
            except OSError:
                pass
        raise HTTPException(status_code=500, detail=f"Error creating branch with manager: {str(e)}")


@router.put("/{branch_id}", response_model=BranchOut)
async def update_branch(
    branch_id: int,
    name: Optional[constr(strip_whitespace=True, min_length=1, max_length=100)] = Form(None),
    address: Optional[str] = Form(None),
    authorized_person: Optional[constr(strip_whitespace=True, min_length=1, max_length=100)] = Form(None),
    pan: Optional[constr(strip_whitespace=True, min_length=10, max_length=10)] = Form(None),
    aadhaar: Optional[constr(strip_whitespace=True, min_length=12, max_length=12)] = Form(None),
    active: Optional[bool] = Form(None),
    agreement_pdf: Optional[UploadFile] = File(None),
    manager_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Update branch with manager assignment support"""
    try:
        branch = db.query(BranchDetails).filter_by(id=branch_id).first()
        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")

        # Name uniqueness
        if name and name != branch.name:
            other = db.query(BranchDetails).filter_by(name=name).first()
            if other and other.id != branch_id:
                raise HTTPException(status_code=400, detail="Another branch with this name already exists")

        # Validate manager if provided (including empty string meaning unassign)
        if manager_id is not None and manager_id != "":
            manager = db.query(UserDetails).filter_by(employee_code=manager_id).first()
            if not manager:
                raise HTTPException(status_code=404, detail="Manager not found")

            is_branch_manager = False
            if getattr(manager, 'role_name', None) == "BRANCH_MANAGER":
                is_branch_manager = True
            elif str(getattr(manager, 'role', '')) == "BRANCH_MANAGER":
                is_branch_manager = True
            else:
                bm_role = db.query(ProfileRole).filter_by(name="BRANCH_MANAGER").first()
                if bm_role and manager.role_id == bm_role.id:
                    is_branch_manager = True

            if not is_branch_manager:
                raise HTTPException(status_code=400, detail="Selected user is not a branch manager")

        # Agreement file update
        if agreement_pdf:
            if branch.agreement_url:
                old_path = branch.agreement_url.lstrip("/")  # fix path join
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass

            os.makedirs(SAVE_DIR, exist_ok=True)
            file_ext = os.path.splitext(agreement_pdf.filename)[1]
            unique_filename = f"{uuid.uuid4().hex}{file_ext}"
            agreement_path = os.path.join(SAVE_DIR, unique_filename)
            with open(agreement_path, "wb") as buffer:
                buffer.write(await agreement_pdf.read())
            branch.agreement_url = f"/{SAVE_DIR}/{unique_filename}"

        # Update fields (respect NOT NULL for pan/aadhaar)
        if name is not None:
            branch.name = name
        if address is not None:
            branch.address = address
        if authorized_person is not None:
            branch.authorized_person = authorized_person
        if pan is not None:
            branch.pan = validate_pan_or_400(pan)
        if aadhaar is not None:
            branch.aadhaar = validate_aadhaar_or_400(aadhaar)
        if active is not None:
            branch.active = active

        if manager_id is not None:
            old_manager_id = branch.manager_id
            branch.manager_id = manager_id if manager_id != "" else None

            # detach old
            if old_manager_id and old_manager_id != manager_id:
                old_manager = db.query(UserDetails).filter_by(employee_code=old_manager_id).first()
                if old_manager:
                    old_manager.branch_id = None

            # attach new
            if manager_id:
                new_manager = db.query(UserDetails).filter_by(employee_code=manager_id).first()
                if new_manager:
                    new_manager.branch_id = branch_id

        db.commit()
        db.refresh(branch)
        return branch

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating branch: {str(e)}")

@router.delete("/{branch_id}")
def delete_branch(branch_id: int, db: Session = Depends(get_db)):
    """Delete a branch (soft delete by setting active=False)"""
    try:
        branch = db.query(BranchDetails).filter_by(id=branch_id).first()
        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")

        users_count = db.query(UserDetails).filter_by(branch_id=branch_id).count()
        if users_count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete branch. {users_count} users are assigned to this branch. Please reassign users first."
            )

        branch.active = False

        if branch.manager_id:
            manager = db.query(UserDetails).filter_by(employee_code=branch.manager_id).first()
            if manager:
                manager.branch_id = None
            branch.manager_id = None

        db.commit()
        return {"message": f"Branch '{branch.name}' has been deactivated successfully"}

    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting branch: {str(e)}")

