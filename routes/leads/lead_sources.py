from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DisconnectionError, IntegrityError
from pydantic import BaseModel, constr

from db.connection import get_db
from db.models import LeadSource, UserDetails, Lead
from routes.auth.auth_dependency import get_current_user
from sqlalchemy import or_, UniqueConstraint  # or_ used below
# ...

def is_superadmin(user: UserDetails) -> bool:
    # Prefer role if available; fall back to your legacy code only if needed
    return getattr(user, "role", None) == "SUPERADMIN" or getattr(user, "employee_code", "") == "Admin001"

router = APIRouter(
    prefix="/lead-config",
    tags=["lead-sources"],
)

# -------------------- Schemas --------------------
class LeadSourceBase(BaseModel):
    name: constr(strip_whitespace=True, min_length=1, max_length=100)
    description: Optional[str] = None
    branch_id: Optional[int] = None  # stays optional

class LeadSourceCreate(LeadSourceBase):
    # no created_by here (server-controlled)
    pass

class LeadSourceUpdate(BaseModel):
    name: Optional[constr(strip_whitespace=True, min_length=1, max_length=100)] = None
    description: Optional[str] = None
    branch_id: Optional[int] = None  # updatable if you allow

class LeadSourceOut(LeadSourceBase):
    id: int
    # You may expose created_by if you want it in responses:
    # created_by: Optional[str] = None

    class Config:
        from_attributes = True

# -------------------- Endpoints --------------------
@router.post("/sources/", response_model=LeadSourceOut, status_code=status.HTTP_201_CREATED)
def create_lead_source(
    source_in: LeadSourceCreate,
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user),
):
    """Create a new lead source (created_by set from current_user)."""
    try:
        # Enforce unique name
        existing = db.query(LeadSource).filter_by(name=source_in.name).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Lead source with name '{source_in.name}' already exists",
            )

        payload = source_in.dict()
        payload["created_by"] = current_user.employee_code   # ✅ set from current_user

        source = LeadSource(**payload)
        db.add(source)
        db.commit()
        db.refresh(source)
        return source

    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lead source name must be unique",
        )
    except (OperationalError, DisconnectionError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again.",
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating lead source: {str(e)}",
        )

@router.get("/sources/", response_model=List[LeadSourceOut])
def get_all_lead_sources(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user),
):
    """Get all lead sources with optional search"""
    
    try:
        query = db.query(LeadSource)
        if search:
            query = query.filter(
                LeadSource.name.ilike(f"%{search}%")
                | LeadSource.description.ilike(f"%{search}%")
            )
        if not is_superadmin(current_user):
            query = query.filter(LeadSource.branch_id == current_user.branch_id)
        return query.offset(skip).limit(limit).all()
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching lead sources: {str(e)}",
        )

@router.get("/sources/{source_id}", response_model=LeadSourceOut)
def get_lead_source(
    source_id: int,
    db: Session = Depends(get_db),
):
    """Get a specific lead source by ID"""
    try:
        source = db.query(LeadSource).filter_by(id=source_id).first()
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Lead source not found"
            )
        return source
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching lead source: {str(e)}",
        )

@router.put("/sources/{source_id}", response_model=LeadSourceOut)
def update_lead_source(
    source_id: int,
    source_in: LeadSourceUpdate,
    db: Session = Depends(get_db),
):
    """Update a lead source (created_by remains untouched)."""
    try:
        source = db.query(LeadSource).filter_by(id=source_id).first()
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Lead source not found"
            )

        update_data = source_in.dict(exclude_unset=True)

        if "name" in update_data:
            existing = (
                db.query(LeadSource)
                .filter(LeadSource.name == update_data["name"], LeadSource.id != source_id)
                .first()
            )
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Another lead source with name '{update_data['name']}' already exists",
                )

        for field, value in update_data.items():
            setattr(source, field, value)

        db.commit()
        db.refresh(source)
        return source

    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lead source name must be unique",
        )
    except (OperationalError, DisconnectionError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again.",
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating lead source: {str(e)}",
        )

@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lead_source(
    source_id: int,
    force: bool = False,
    db: Session = Depends(get_db),
):
    """Delete a lead source"""
    try:
        source = db.query(LeadSource).filter_by(id=source_id).first()
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Lead source not found"
            )

        leads_count = db.query(Lead).filter_by(lead_source_id=source_id).count()
        if leads_count > 0 and not force:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot delete lead source. It is being used by {leads_count} leads. Use force=true to delete anyway.",
            )

        db.delete(source)
        db.commit()
        return None

    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again.",
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting lead source: {str(e)}",
        )
