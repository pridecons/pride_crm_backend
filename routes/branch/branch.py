# routes/branch.py

import os
import uuid
from typing import Optional

from fastapi import (
    APIRouter, Depends, HTTPException, status,
    File, UploadFile, Form
)
from pydantic import constr
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DisconnectionError

from db.connection import get_db
from db.models import BranchDetails, UserDetails, UserRoleEnum
from db.Schema.branch import BranchCreate, BranchUpdate, BranchOut, BranchDetailsOut, ManagerInfo, UserInfo

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
                    detail="Database connection lost. Please try again."
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


@router.post("/", response_model=BranchOut, status_code=status.HTTP_201_CREATED)
async def create_branch(
    name: constr(strip_whitespace=True, min_length=1, max_length=100) = Form(...),
    address: str = Form(...),
    authorized_person: constr(strip_whitespace=True, min_length=1, max_length=100) = Form(...),
    pan: constr(strip_whitespace=True, min_length=1, max_length=10) = Form(...),
    aadhaar: constr(strip_whitespace=True, min_length=12, max_length=12) = Form(...),
    active: bool = Form(True),
    agreement_pdf: UploadFile = File(...),
    manager_id: Optional[str] = Form(None),  # Branch Manager employee_code
    db: Session = Depends(get_db),
):
    """Create a new branch with optional manager assignment"""
    try:
        # Uniqueness check
        existing_branch = db.query(BranchDetails).filter_by(name=name).first()
        if existing_branch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Branch with this name already exists"
            )

        # Validate manager if provided
        if manager_id:
            manager = db.query(UserDetails).filter_by(employee_code=manager_id).first()
            if not manager:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Manager with employee_code '{manager_id}' does not exist"
                )
            if manager.role != UserRoleEnum.BRANCH_MANAGER:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Only users with BRANCH MANAGER role can manage branches"
                )
            # Check if manager is already managing another branch
            existing_managed_branch = db.query(BranchDetails).filter_by(manager_id=manager_id).first()
            if existing_managed_branch:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Manager is already managing branch: {existing_managed_branch.name}"
                )

        # Save PDF file
        os.makedirs(SAVE_DIR, exist_ok=True)
        filename = f"{uuid.uuid4().hex}_{agreement_pdf.filename}"
        path = os.path.join(SAVE_DIR, filename)
        
        with open(path, "wb") as buf:
            content = await agreement_pdf.read()
            buf.write(content)

        agreement_url = f"/{SAVE_DIR}/{filename}"

        # Create branch
        branch = BranchDetails(
            name=name,
            address=address,
            authorized_person=authorized_person,
            pan=pan,
            aadhaar=aadhaar,
            agreement_url=agreement_url,
            active=active,
            manager_id=manager_id,
        )
        
        db.add(branch)
        db.commit()
        db.refresh(branch)
        
        # Update manager's branch_id if manager assigned
        if manager_id:
            manager.branch_id = branch.id
            db.commit()
        
        return branch
        
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError) as e:
        db.rollback()
        if "server closed the connection unexpectedly" in str(e):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database connection lost. Please try again."
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )
    except Exception as e:
        db.rollback()
        # Clean up uploaded file if branch creation failed
        if 'path' in locals() and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating branch: {str(e)}"
        )


@router.put("/{branch_id}", response_model=BranchOut)
async def update_branch(
    branch_id: int,
    name: Optional[constr(strip_whitespace=True, min_length=1, max_length=100)] = Form(None),
    address: Optional[str] = Form(None),
    authorized_person: Optional[constr(strip_whitespace=True, min_length=1, max_length=100)] = Form(None),
    pan: Optional[constr(strip_whitespace=True, min_length=1, max_length=10)] = Form(None),
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

        # Validate new manager if provided
        if manager_id is not None:  # Allow setting to None
            if manager_id:  # If not empty string
                manager = db.query(UserDetails).filter_by(employee_code=manager_id).first()
                if not manager:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Manager with employee_code '{manager_id}' does not exist"
                    )
                if manager.role != UserRoleEnum.BRANCH_MANAGER:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Only users with BRANCH MANAGER role can manage branches"
                    )
                # Check if manager is already managing another branch
                existing_managed = db.query(BranchDetails).filter(
                    BranchDetails.manager_id == manager_id,
                    BranchDetails.id != branch_id
                ).first()
                if existing_managed:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Manager is already managing branch: {existing_managed.name}"
                    )

        # Handle agreement PDF update
        agreement_url = branch.agreement_url
        if agreement_pdf:
            # Delete old file if it exists
            if branch.agreement_url:
                old_file_path = branch.agreement_url.lstrip('/')
                if os.path.exists(old_file_path):
                    try:
                        os.remove(old_file_path)
                    except OSError:
                        pass

            # Save new PDF
            os.makedirs(SAVE_DIR, exist_ok=True)
            filename = f"{uuid.uuid4().hex}_{agreement_pdf.filename}"
            path = os.path.join(SAVE_DIR, filename)
            
            with open(path, "wb") as buf:
                content = await agreement_pdf.read()
                buf.write(content)
            
            agreement_url = f"/{SAVE_DIR}/{filename}"

        # Update fields
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
        if agreement_pdf:
            branch.agreement_url = agreement_url
        if manager_id is not None:
            # Update old manager's branch_id to None
            if branch.manager_id:
                old_manager = db.query(UserDetails).filter_by(employee_code=branch.manager_id).first()
                if old_manager:
                    old_manager.branch_id = None
            
            branch.manager_id = manager_id if manager_id else None
            
            # Update new manager's branch_id
            if manager_id:
                new_manager = db.query(UserDetails).filter_by(employee_code=manager_id).first()
                if new_manager:
                    new_manager.branch_id = branch.id

        db.commit()
        db.refresh(branch)
        return branch
        
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError) as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating branch: {str(e)}"
        )


@router.patch("/{branch_id}/agreement")
async def update_agreement_only(
    branch_id: int,
    agreement_pdf: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Update only the agreement PDF for a branch"""
    try:
        branch = db.query(BranchDetails).filter_by(id=branch_id).first()
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Branch not found"
            )

        # Delete old file if it exists
        if branch.agreement_url:
            old_file_path = branch.agreement_url.lstrip('/')
            if os.path.exists(old_file_path):
                try:
                    os.remove(old_file_path)
                except OSError:
                    pass

        # Save new PDF
        os.makedirs(SAVE_DIR, exist_ok=True)
        filename = f"{uuid.uuid4().hex}_{agreement_pdf.filename}"
        path = os.path.join(SAVE_DIR, filename)
        
        with open(path, "wb") as buf:
            content = await agreement_pdf.read()
            buf.write(content)

        agreement_url = f"/{SAVE_DIR}/{filename}"
        branch.agreement_url = agreement_url

        db.commit()
        db.refresh(branch)
        
        return {
            "message": "Agreement updated successfully", 
            "agreement_url": agreement_url
        }
        
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError) as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        # Clean up uploaded file if update failed
        if 'path' in locals() and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating agreement: {str(e)}"
        )


@router.patch("/{branch_id}/manager")
def assign_manager(
    branch_id: int,
    manager_id: str,
    db: Session = Depends(get_db),
):
    """Assign or change branch manager"""
    try:
        branch = db.query(BranchDetails).filter_by(id=branch_id).first()
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Branch not found"
            )

        # Validate manager
        manager = db.query(UserDetails).filter_by(employee_code=manager_id).first()
        if not manager:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Manager with employee_code '{manager_id}' does not exist"
            )
        if manager.role != UserRoleEnum.BRANCH_MANAGER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only users with BRANCH MANAGER role can manage branches"
            )

        # Check if manager is already managing another branch
        existing_managed = db.query(BranchDetails).filter(
            BranchDetails.manager_id == manager_id,
            BranchDetails.id != branch_id
        ).first()
        if existing_managed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Manager is already managing branch: {existing_managed.name}"
            )

        # Update old manager's branch_id to None
        if branch.manager_id:
            old_manager = db.query(UserDetails).filter_by(employee_code=branch.manager_id).first()
            if old_manager:
                old_manager.branch_id = None

        # Assign new manager
        branch.manager_id = manager_id
        manager.branch_id = branch.id

        db.commit()
        
        return {
            "message": f"Manager {manager.name} assigned to branch {branch.name} successfully",
            "branch_id": branch.id,
            "manager_id": manager_id
        }
        
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError) as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error assigning manager: {str(e)}"
        )


@router.get("/", response_model=list[BranchOut])
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
        
        # Convert to dict to ensure proper serialization
        branch_list = []
        for branch in branches:
            branch_dict = {
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
            branch_list.append(branch_dict)
        
        return branch_list
        
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
            detail=f"Error fetching branches: {str(e)}"
        )


@router.get("/available-managers")
def get_available_managers(db: Session = Depends(get_db)):
    """Get list of users who can be branch managers"""
    try:
        # Get BRANCH MANAGER role users who are not currently managing any branch
        available_managers = db.query(UserDetails).filter(
            UserDetails.role == UserRoleEnum.BRANCH_MANAGER,
            UserDetails.is_active == True,
            ~UserDetails.employee_code.in_(
                db.query(BranchDetails.manager_id).filter(BranchDetails.manager_id.isnot(None))
            )
        ).all()
        
        return [
            {
                "employee_code": manager.employee_code,
                "name": manager.name,
                "email": manager.email,
                "phone_number": manager.phone_number
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


@router.get("/{branch_id}/details")
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
                "role": user.role.value if hasattr(user.role, 'value') else str(user.role),
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


@router.delete("/{branch_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_branch(
    branch_id: int,
    force: bool = False,  # Force delete even if users exist
    db: Session = Depends(get_db),
):
    """Delete branch"""
    try:
        branch = db.query(BranchDetails).filter_by(id=branch_id).first()
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Branch not found"
            )

        # Check if branch has users
        branch_users = db.query(UserDetails).filter_by(branch_id=branch_id).first()
        if branch_users and not force:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete branch with active users. Use force=true to delete anyway."
            )

        # Update manager's branch_id to None if exists
        if branch.manager_id:
            manager = db.query(UserDetails).filter_by(employee_code=branch.manager_id).first()
            if manager:
                manager.branch_id = None

        # Delete associated agreement file
        if branch.agreement_url:
            file_path = branch.agreement_url.lstrip('/')
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass

        db.delete(branch)
        db.commit()
        return None
        
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError) as e:
        db.rollback()
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

     