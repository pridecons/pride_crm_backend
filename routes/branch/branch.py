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
from db.models import BranchDetails, UserDetails, PermissionDetails, ProfileRole
from passlib.context import CryptContext

# Import validation functions
def validate_user_data(db: Session, user_data: dict):
    """Validate user data - implement as needed"""
    pass

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    return pwd_context.hash(password)

# Response Models
class BranchBase(BaseModel):
    name: constr(strip_whitespace=True, min_length=1, max_length=100)
    address: str
    authorized_person: constr(strip_whitespace=True, min_length=1, max_length=100)
    pan: Optional[constr(strip_whitespace=True, min_length=10, max_length=10)] = None
    aadhaar: Optional[constr(strip_whitespace=True, min_length=12, max_length=12)] = None
    active: bool = True

class BranchOut(BaseModel):
    id: int
    name: str
    address: str
    authorized_person: str
    pan: Optional[str] = None
    aadhaar: Optional[str] = None
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

def handle_db_error(func):
    """Decorator to handle database connection errors"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (OperationalError, DisconnectionError) as e:
            if "server closed the connection unexpectedly" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Database connection lost. Please restart the application and try again."
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unexpected error: {str(e)}"
            )
    return wrapper

@router.get("/", response_model=List[BranchOut])
@handle_db_error
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
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please restart the application and try again."
        )
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
        # Get BRANCH_MANAGER role users who are not currently managing any branch
        # Support both legacy role field and new role_id system
        branch_manager_profile = db.query(ProfileRole).filter_by(name="BRANCH_MANAGER").first()
        
        query = db.query(UserDetails).filter(
            UserDetails.is_active == True,
            ~UserDetails.employee_code.in_(
                db.query(BranchDetails.manager_id).filter(BranchDetails.manager_id.isnot(None))
            )
        )
        
        # Filter by role - support both systems
        if branch_manager_profile:
            # New ProfileRole system
            query = query.filter(UserDetails.role_id == branch_manager_profile.id)
        else:
            # Fallback to legacy enum system
            query = query.filter(UserDetails.role == "BRANCH_MANAGER")
        
        available_managers = query.all()
        
        return [
            {
                "employee_code": manager.employee_code,
                "name": manager.name,
                "email": manager.email,
                "phone_number": manager.phone_number,
                "role_name": getattr(manager, 'role_name', None) or str(manager.role if hasattr(manager, 'role') else 'Unknown')
            }
            for manager in available_managers
        ]
        
    except (OperationalError, DisconnectionError) as e:
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
def get_branch(
    branch_id: int,
    db: Session = Depends(get_db),
):
    """Get a specific branch by ID"""
    try:
        branch = db.query(BranchDetails).filter_by(id=branch_id).first()
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Branch not found"
            )
        return branch
        
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching branch: {str(e)}"
        )

@router.get("/{branch_id}/details", response_model=BranchDetailsOut)
def get_branch_details(
    branch_id: int,
    db: Session = Depends(get_db),
):
    """Get detailed branch information including manager and users"""
    try:
        branch = db.query(BranchDetails).filter_by(id=branch_id).first()
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Branch not found"
            )

        # Prepare branch data
        branch_data = {
            "id": branch.id,
            "name": branch.name,
            "address": branch.address,
            "authorized_person": branch.authorized_person,
            "pan": branch.pan,
            "aadhaar": branch.aadhaar,
            "agreement_url": branch.agreement_url,
            "active": branch.active,
            "manager_id": branch.manager_id,
            "created_at": branch.created_at,
            "updated_at": branch.updated_at,
        }

        # Get branch manager details
        manager_info = None
        if branch.manager_id:
            manager = db.query(UserDetails).filter_by(employee_code=branch.manager_id).first()
            if manager:
                manager_info = {
                    "employee_code": manager.employee_code,
                    "name": manager.name,
                    "email": manager.email,
                    "phone_number": manager.phone_number
                }

        # Get all users in this branch
        branch_users = db.query(UserDetails).filter_by(branch_id=branch_id).all()
        users_info = [
            {
                "employee_code": user.employee_code,
                "name": user.name,
                "role": str(user.role) if hasattr(user, 'role') else 'Unknown',
                "role_id": getattr(user, 'role_id', None),
                "role_name": getattr(user, 'role_name', None),
                "email": user.email,
                "is_active": user.is_active
            }
            for user in branch_users
        ]

        return {
            "branch": branch_data,
            "manager": manager_info,
            "users": users_info,
            "total_users": len(users_info)
        }
        
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching branch details: {str(e)}"
        )

@router.post("/", response_model=BranchOut, status_code=status.HTTP_201_CREATED)
async def create_branch(
    name: constr(strip_whitespace=True, min_length=1, max_length=100) = Form(...),
    address: str = Form(...),
    authorized_person: constr(strip_whitespace=True, min_length=1, max_length=100) = Form(...),
    pan: Optional[constr(strip_whitespace=True, min_length=10, max_length=10)] = Form(None),
    aadhaar: Optional[constr(strip_whitespace=True, min_length=12, max_length=12)] = Form(None),
    active: bool = Form(True),
    agreement_pdf: UploadFile = File(...),
    manager_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Create a new branch"""
    try:
        # Check for unique name
        existing = db.query(BranchDetails).filter_by(name=name).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Branch with this name already exists"
            )

        # Validate manager if provided
        if manager_id:
            manager = db.query(UserDetails).filter_by(employee_code=manager_id).first()
            if not manager:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Manager not found"
                )
            
            # Check if user is a branch manager - support both systems
            is_branch_manager = False
            if hasattr(manager, 'role_name') and manager.role_name == "BRANCH_MANAGER":
                is_branch_manager = True
            elif hasattr(manager, 'role') and str(manager.role) == "BRANCH_MANAGER":
                is_branch_manager = True
                
            if not is_branch_manager:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Selected user is not a branch manager"
                )

        # Create directories if they don't exist
        os.makedirs(SAVE_DIR, exist_ok=True)
        
        # Generate unique filename and save agreement
        file_extension = os.path.splitext(agreement_pdf.filename)[1]
        unique_filename = f"{uuid.uuid4().hex}{file_extension}"
        agreement_path = os.path.join(SAVE_DIR, unique_filename)
        
        with open(agreement_path, "wb") as buffer:
            content = await agreement_pdf.read()
            buffer.write(content)

        # Create branch
        branch = BranchDetails(
            name=name,
            address=address,
            authorized_person=authorized_person,
            pan=pan,
            aadhaar=aadhaar,
            agreement_url=f"/static/agreements/{unique_filename}",
            active=active,
            manager_id=manager_id
        )

        db.add(branch)
        db.commit()
        db.refresh(branch)

        # Update manager's branch_id if manager assigned
        if manager_id:
            manager = db.query(UserDetails).filter_by(employee_code=manager_id).first()
            if manager:
                manager.branch_id = branch.id
                db.commit()

        return branch

    except HTTPException:
        raise
    except Exception as e:
        # Clean up uploaded file on error
        if 'agreement_path' in locals() and os.path.exists(agreement_path):
            try:
                os.remove(agreement_path)
            except OSError:
                pass
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating branch: {str(e)}"
        )

@router.post("/create-with-manager", response_model=BranchWithManagerResponse, status_code=status.HTTP_201_CREATED)
async def create_branch_with_manager(
    # Branch Details
    branch_name: constr(strip_whitespace=True, min_length=1, max_length=100) = Form(...),
    branch_address: str = Form(...),
    authorized_person: constr(strip_whitespace=True, min_length=1, max_length=100) = Form(...),
    branch_pan: Optional[constr(strip_whitespace=True, min_length=10, max_length=10)] = Form(None),
    branch_aadhaar: Optional[constr(strip_whitespace=True, min_length=12, max_length=12)] = Form(None),
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
    
    db: Session = Depends(get_db),
):
    """Create a new branch along with its branch manager in a single transaction"""
    
    def validate_email(email: str):
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None

    try:
        # Validate email
        if not validate_email(manager_email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid email format"
            )

        # Check for unique constraints
        if db.query(BranchDetails).filter_by(name=branch_name).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Branch with this name already exists"
            )

        if db.query(UserDetails).filter_by(phone_number=manager_phone).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Manager phone number already registered"
            )

        if db.query(UserDetails).filter_by(email=manager_email).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Manager email already registered"
            )

        # Create directories and save agreement file
        os.makedirs(SAVE_DIR, exist_ok=True)
        file_extension = os.path.splitext(agreement_pdf.filename)[1]
        unique_filename = f"{uuid.uuid4().hex}{file_extension}"
        agreement_path = os.path.join(SAVE_DIR, unique_filename)
        
        with open(agreement_path, "wb") as buffer:
            content = await agreement_pdf.read()
            buffer.write(content)

        # Generate employee code for manager
        count = db.query(UserDetails).count() or 0
        emp_code = f"EMP{count+1:03d}"
        
        while db.query(UserDetails).filter_by(employee_code=emp_code).first():
            count += 1
            emp_code = f"EMP{count+1:03d}"

        # Get or create BRANCH_MANAGER profile role
        branch_manager_profile = db.query(ProfileRole).filter_by(name="BRANCH_MANAGER").first()
        if not branch_manager_profile:
            # Create default profiles if they don't exist
            ProfileRole.create_default_profiles(db)
            branch_manager_profile = db.query(ProfileRole).filter_by(name="BRANCH_MANAGER").first()
        
        if not branch_manager_profile:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="BRANCH_MANAGER profile role not found"
            )

        # Create branch first
        branch = BranchDetails(
            name=branch_name,
            address=branch_address,
            authorized_person=authorized_person,
            pan=branch_pan,
            aadhaar=branch_aadhaar,
            agreement_url=f"/static/agreements/{unique_filename}",
            active=branch_active,
            manager_id=emp_code  # Set manager_id to the employee code
        )

        db.add(branch)
        db.flush()  # Get branch ID

        # Create manager user
        manager = UserDetails(
            employee_code=emp_code,
            phone_number=manager_phone,
            email=manager_email,
            name=manager_name,
            password=hash_password(manager_password),
            role_id=branch_manager_profile.id,  # Use ProfileRole ID
            father_name=manager_father_name,
            is_active=True,
            experience=manager_experience,
            date_of_joining=date.today(),
            date_of_birth=manager_dob,
            pan=manager_pan,
            aadhaar=manager_aadhaar,
            address=manager_address,
            city=manager_city,
            state=manager_state,
            pincode=manager_pincode,
            comment=manager_comment,
            branch_id=branch.id  # Set branch_id
        )

        db.add(manager)
        db.flush()

        # Create default permissions for manager
        default_perms = PermissionDetails.get_default_permissions("BRANCH_MANAGER")
        permissions = PermissionDetails(
            user_id=manager.employee_code,
            **default_perms
        )
        db.add(permissions)

        # Commit all changes
        db.commit()
        
        # Refresh to get updated data
        db.refresh(branch)
        db.refresh(manager)
        
        # Prepare response
        branch_out = {
            "id": branch.id,
            "name": branch.name,
            "address": branch.address,
            "authorized_person": branch.authorized_person,
            "pan": branch.pan,
            "aadhaar": branch.aadhaar,
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
            "role_name": getattr(manager, 'role_name', 'BRANCH_MANAGER')
        }
        
        return {
            "message": f"Branch '{branch.name}' and Branch Manager '{manager.name}' created successfully",
            "branch": branch_out,
            "manager": manager_response,
            "login_credentials": login_credentials
        }
        
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError) as e:
        db.rollback()
        # Clean up uploaded file
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
        # Clean up uploaded file
        if 'agreement_path' in locals() and os.path.exists(agreement_path):
            try:
                os.remove(agreement_path)
            except OSError:
                pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating branch with manager: {str(e)}"
        )

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
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Branch not found"
            )

        # Check name uniqueness if name is being updated
        if name and name != branch.name:
            other = db.query(BranchDetails).filter_by(name=name).first()
            if other and other.id != branch_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Another branch with this name already exists"
                )

        # Validate manager if provided
        if manager_id is not None:
            if manager_id:  # Not empty string
                manager = db.query(UserDetails).filter_by(employee_code=manager_id).first()
                if not manager:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Manager not found"
                    )
                
                # Check if user is a branch manager - support both systems
                is_branch_manager = False
                if hasattr(manager, 'role_name') and manager.role_name == "BRANCH_MANAGER":
                    is_branch_manager = True
                elif hasattr(manager, 'role') and str(manager.role) == "BRANCH_MANAGER":
                    is_branch_manager = True
                    
                if not is_branch_manager:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Selected user is not a branch manager"
                    )

        # Handle agreement file update
        if agreement_pdf:
            # Remove old file
            if branch.agreement_url and os.path.exists(f"static{branch.agreement_url}"):
                try:
                    os.remove(f"static{branch.agreement_url}")
                except OSError:
                    pass

            # Save new file
            os.makedirs(SAVE_DIR, exist_ok=True)
            file_extension = os.path.splitext(agreement_pdf.filename)[1]
            unique_filename = f"{uuid.uuid4().hex}{file_extension}"
            agreement_path = os.path.join(SAVE_DIR, unique_filename)
            
            with open(agreement_path, "wb") as buffer:
                content = await agreement_pdf.read()
                buffer.write(content)
                
            branch.agreement_url = f"/static/agreements/{unique_filename}"

        # Update branch fields
        if name is not None:
            branch.name = name
        if address is not None:
            branch.address = address
        if authorized_person is not None:
            branch.authorized_person = authorized_person
        if pan is not None:
            branch.pan = pan
        if aadhaar is not None:
            branch.aadhaar = aadhaar
        if active is not None:
            branch.active = active
        if manager_id is not None:
            # Handle manager change
            old_manager_id = branch.manager_id
            branch.manager_id = manager_id if manager_id else None
            
            # Update old manager's branch_id to None
            if old_manager_id:
                old_manager = db.query(UserDetails).filter_by(employee_code=old_manager_id).first()
                if old_manager:
                    old_manager.branch_id = None
            
            # Update new manager's branch_id
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating branch: {str(e)}"
        )

@router.delete("/{branch_id}")
def delete_branch(
    branch_id: int,
    db: Session = Depends(get_db),
):
    """Delete a branch (soft delete by setting active=False)"""
    try:
        branch = db.query(BranchDetails).filter_by(id=branch_id).first()
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Branch not found"
            )

        # Check if branch has users (prevent deletion if users exist)
        users_count = db.query(UserDetails).filter_by(branch_id=branch_id).count()
        if users_count > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot delete branch. {users_count} users are assigned to this branch. Please reassign users first."
            )

        # Soft delete by setting active=False
        branch.active = False
        
        # Also unassign manager
        if branch.manager_id:
            manager = db.query(UserDetails).filter_by(employee_code=branch.manager_id).first()
            if manager:
                manager.branch_id = None
            branch.manager_id = None

        db.commit()

        return {"message": f"Branch '{branch.name}' has been deactivated successfully"}

    except HTTPException:
        raise
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting branch: {str(e)}"
        )

        