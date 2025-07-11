# routes/branch.py

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, constr
from sqlalchemy.orm import Session

from db.connection import get_db
from db.models import BranchDetails

router = APIRouter(
    prefix="/branches",
    tags=["branches"],
)


# --- Pydantic Schemas --------------------------------

class BranchBase(BaseModel):
    name: constr(strip_whitespace=True, min_length=1, max_length=100)
    address: str
    authorized_person: constr(strip_whitespace=True, min_length=1, max_length=100)
    pan: constr(strip_whitespace=True, min_length=1, max_length=10)
    aadhaar: constr(strip_whitespace=True, min_length=12, max_length=12)
    agreement_url: Optional[str] = None
    active: Optional[bool] = True


class BranchCreate(BranchBase):
    pass


class BranchUpdate(BaseModel):
    name: Optional[constr(strip_whitespace=True, min_length=1, max_length=100)]
    address: Optional[str]
    authorized_person: Optional[constr(strip_whitespace=True, min_length=1, max_length=100)]
    pan: Optional[constr(strip_whitespace=True, min_length=1, max_length=10)]
    aadhaar: Optional[constr(strip_whitespace=True, min_length=12, max_length=12)]
    agreement_url: Optional[str]
    active: Optional[bool]


class BranchOut(BranchBase):
    id: int

    class Config:
        orm_mode = True


# --- CRUD Endpoints ---------------------------------

@router.post("/", response_model=BranchOut, status_code=status.HTTP_201_CREATED)
def create_branch(
    branch_in: BranchCreate,
    db: Session = Depends(get_db),
):
    # Ensure unique branch name
    existing = db.query(BranchDetails).filter_by(name=branch_in.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Branch with this name already exists"
        )

    branch = BranchDetails(
        name=branch_in.name,
        address=branch_in.address,
        authorized_person=branch_in.authorized_person,
        pan=branch_in.pan,
        aadhaar=branch_in.aadhaar,
        agreement_url=branch_in.agreement_url,
        active=branch_in.active,
    )
    db.add(branch)
    db.commit()
    db.refresh(branch)
    return branch


@router.put("/{branch_id}", response_model=BranchOut)
def update_branch(
    branch_id: int,
    branch_in: BranchUpdate,
    db: Session = Depends(get_db),
):
    branch = db.query(BranchDetails).filter_by(id=branch_id).first()
    if not branch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch not found"
        )

    data = branch_in.dict(exclude_unset=True)
    # If updating name, ensure uniqueness
    if "name" in data:
        other = db.query(BranchDetails).filter_by(name=data["name"]).first()
        if other and other.id != branch_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Another branch with this name already exists"
            )

    for field, value in data.items():
        setattr(branch, field, value)

    db.commit()
    db.refresh(branch)
    return branch


@router.delete("/{branch_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_branch(
    branch_id: int,
    db: Session = Depends(get_db),
):
    branch = db.query(BranchDetails).filter_by(id=branch_id).first()
    if not branch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch not found"
        )

    db.delete(branch)
    db.commit()
    return None
