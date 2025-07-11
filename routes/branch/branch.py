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

from db.connection import get_db
from db.models import BranchDetails
from db.Schema.branch import BranchCreate, BranchUpdate, BranchOut

router = APIRouter(
    prefix="/branches",
    tags=["branches"],
)

SAVE_DIR = "static/agreements"


@router.post("/", response_model=BranchOut, status_code=status.HTTP_201_CREATED)
async def create_branch(
    name: constr(strip_whitespace=True, min_length=1, max_length=100) = Form(...),
    address: str                                                   = Form(...),
    authorized_person: constr(strip_whitespace=True, min_length=1, max_length=100) = Form(...),
    pan: constr(strip_whitespace=True, min_length=1, max_length=10)           = Form(...),
    aadhaar: constr(strip_whitespace=True, min_length=12, max_length=12)      = Form(...),
    active: bool                                             = Form(True),
    agreement_pdf: UploadFile                                = File(...),
    db: Session                                              = Depends(get_db),
):
    # uniqueness check
    if db.query(BranchDetails).filter_by(name=name).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Branch with this name already exists"
        )

    # save PDF
    os.makedirs(SAVE_DIR, exist_ok=True)
    filename = f"{uuid.uuid4().hex}_{agreement_pdf.filename}"
    path = os.path.join(SAVE_DIR, filename)
    with open(path, "wb") as buf:
        buf.write(await agreement_pdf.read())

    agreement_url = f"/{SAVE_DIR}/{filename}"

    branch = BranchDetails(
        name=name,
        address=address,
        authorized_person=authorized_person,
        pan=pan,
        aadhaar=aadhaar,
        agreement_url=agreement_url,
        active=active,
    )
    db.add(branch)
    db.commit()
    db.refresh(branch)
    return branch


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
    db: Session = Depends(get_db),
):
    branch = db.query(BranchDetails).get(branch_id)
    if not branch:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Branch not found")

    # Check name uniqueness if name is being updated
    if name and name != branch.name:
        other = db.query(BranchDetails).filter_by(name=name).first()
        if other and other.id != branch_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Another branch with this name already exists"
            )

    # Handle agreement PDF update
    agreement_url = branch.agreement_url  # Keep existing URL by default
    if agreement_pdf:
        # Delete old file if it exists
        if branch.agreement_url:
            old_file_path = branch.agreement_url.lstrip('/')
            if os.path.exists(old_file_path):
                try:
                    os.remove(old_file_path)
                except OSError:
                    pass  # File might be in use or already deleted

        # Save new PDF
        os.makedirs(SAVE_DIR, exist_ok=True)
        filename = f"{uuid.uuid4().hex}_{agreement_pdf.filename}"
        path = os.path.join(SAVE_DIR, filename)
        with open(path, "wb") as buf:
            buf.write(await agreement_pdf.read())
        
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
    if agreement_pdf:  # Only update URL if new file was uploaded
        branch.agreement_url = agreement_url

    db.commit()
    db.refresh(branch)
    return branch


@router.put("/{branch_id}/json", response_model=BranchOut)
def update_branch_json(
    branch_id: int,
    branch_in: BranchUpdate,
    db: Session = Depends(get_db),
):
    """Update branch using JSON payload (without file upload)"""
    branch = db.query(BranchDetails).get(branch_id)
    if not branch:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Branch not found")

    data = branch_in.dict(exclude_unset=True)
    if "name" in data:
        other = db.query(BranchDetails).filter_by(name=data["name"]).first()
        if other and other.id != branch_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Another branch with this name already exists"
            )

    for k, v in data.items():
        setattr(branch, k, v)

    db.commit()
    db.refresh(branch)
    return branch


@router.patch("/{branch_id}/agreement")
async def update_agreement_only(
    branch_id: int,
    agreement_pdf: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Update only the agreement PDF for a branch"""
    branch = db.query(BranchDetails).get(branch_id)
    if not branch:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Branch not found")

    # Delete old file if it exists
    if branch.agreement_url:
        old_file_path = branch.agreement_url.lstrip('/')
        if os.path.exists(old_file_path):
            try:
                os.remove(old_file_path)
            except OSError:
                pass  # File might be in use or already deleted

    # Save new PDF
    os.makedirs(SAVE_DIR, exist_ok=True)
    filename = f"{uuid.uuid4().hex}_{agreement_pdf.filename}"
    path = os.path.join(SAVE_DIR, filename)
    with open(path, "wb") as buf:
        buf.write(await agreement_pdf.read())

    agreement_url = f"/{SAVE_DIR}/{filename}"
    branch.agreement_url = agreement_url

    db.commit()
    db.refresh(branch)
    
    return {
        "message": "Agreement updated successfully", 
        "agreement_url": agreement_url
    }


@router.get("/", response_model=list[BranchOut])
def get_all_branches(
    skip: int = 0,
    limit: int = 100,
    active_only: bool = False,
    db: Session = Depends(get_db),
):
    """Get all branches with pagination and filtering"""
    query = db.query(BranchDetails)
    
    if active_only:
        query = query.filter(BranchDetails.active == True)
    
    branches = query.offset(skip).limit(limit).all()
    return branches


@router.get("/{branch_id}", response_model=BranchOut)
def get_branch(
    branch_id: int,
    db: Session = Depends(get_db),
):
    """Get a specific branch by ID"""
    branch = db.query(BranchDetails).get(branch_id)
    if not branch:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Branch not found")
    return branch


@router.delete("/{branch_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_branch(
    branch_id: int,
    db: Session = Depends(get_db),
):
    branch = db.query(BranchDetails).get(branch_id)
    if not branch:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Branch not found")

    # Delete associated agreement file
    if branch.agreement_url:
        file_path = branch.agreement_url.lstrip('/')
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass  # File might be in use or already deleted

    db.delete(branch)
    db.commit()
    return None