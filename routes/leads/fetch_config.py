# routes/leads/fetch_config.py - Updated with last_fetch_limit

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DisconnectionError, IntegrityError
from pydantic import BaseModel, validator

from db.connection import get_db
from db.models import LeadFetchConfig, UserRoleEnum, BranchDetails

router = APIRouter(
    prefix="/lead-fetch-config",
    tags=["lead-fetch-config"],
)


# Pydantic Schemas
class LeadFetchConfigBase(BaseModel):
    role: Optional[UserRoleEnum] = None
    branch_id: Optional[int] = None
    per_request_limit: int
    daily_call_limit: int
    last_fetch_limit: int  # NEW FIELD
    assignment_ttl_hours: int = 24 * 7  # Default 7 days

    @validator('per_request_limit')
    def validate_per_request_limit(cls, v):
        if v <= 0:
            raise ValueError('per_request_limit must be greater than 0')
        if v > 1000:
            raise ValueError('per_request_limit cannot exceed 1000')
        return v

    @validator('daily_call_limit')
    def validate_daily_call_limit(cls, v):
        if v <= 0:
            raise ValueError('daily_call_limit must be greater than 0')
        if v > 100:
            raise ValueError('daily_call_limit cannot exceed 100')
        return v

    @validator('last_fetch_limit')  # NEW VALIDATOR
    def validate_last_fetch_limit(cls, v):
        if v < 0:
            raise ValueError('last_fetch_limit must be 0 or greater')
        if v > 100:
            raise ValueError('last_fetch_limit cannot exceed 100')
        return v

    @validator('assignment_ttl_hours')
    def validate_assignment_ttl_hours(cls, v):
        if v <= 0:
            raise ValueError('assignment_ttl_hours must be greater than 0')
        if v > 24 * 30:  # Max 30 days
            raise ValueError('assignment_ttl_hours cannot exceed 720 hours (30 days)')
        return v


class LeadFetchConfigCreate(LeadFetchConfigBase):
    pass


class LeadFetchConfigUpdate(BaseModel):
    per_request_limit: Optional[int] = None
    daily_call_limit: Optional[int] = None
    last_fetch_limit: Optional[int] = None  # NEW FIELD
    assignment_ttl_hours: Optional[int] = None

    @validator('per_request_limit')
    def validate_per_request_limit(cls, v):
        if v is not None:
            if v <= 0:
                raise ValueError('per_request_limit must be greater than 0')
            if v > 1000:
                raise ValueError('per_request_limit cannot exceed 1000')
        return v

    @validator('daily_call_limit')
    def validate_daily_call_limit(cls, v):
        if v is not None:
            if v <= 0:
                raise ValueError('daily_call_limit must be greater than 0')
            if v > 100:
                raise ValueError('daily_call_limit cannot exceed 100')
        return v

    @validator('last_fetch_limit')  # NEW VALIDATOR
    def validate_last_fetch_limit(cls, v):
        if v is not None:
            if v < 0:
                raise ValueError('last_fetch_limit must be 0 or greater')
            if v > 100:
                raise ValueError('last_fetch_limit cannot exceed 100')
        return v

    @validator('assignment_ttl_hours')
    def validate_assignment_ttl_hours(cls, v):
        if v is not None:
            if v <= 0:
                raise ValueError('assignment_ttl_hours must be greater than 0')
            if v > 24 * 30:
                raise ValueError('assignment_ttl_hours cannot exceed 720 hours (30 days)')
        return v


class LeadFetchConfigResponse(BaseModel):
    id: int
    role: Optional[str] = None
    branch_id: Optional[int] = None
    per_request_limit: int
    daily_call_limit: int
    last_fetch_limit: int  # NEW FIELD
    assignment_ttl_hours: int

    class Config:
        from_attributes = True


class LeadFetchConfigDetails(LeadFetchConfigResponse):
    branch_name: Optional[str] = None
    branch_address: Optional[str] = None


@router.post("/", response_model=LeadFetchConfigResponse)
def create_fetch_config(
    config: LeadFetchConfigCreate,
    db: Session = Depends(get_db),
):
    """Create a new lead fetch configuration"""
    try:
        # Check if configuration already exists for this role/branch combination
        existing_config = db.query(LeadFetchConfig).filter_by(
            role=config.role,
            branch_id=config.branch_id
        ).first()
        
        if existing_config:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Configuration already exists for this role/branch combination"
            )
        
        # Validate branch exists if branch_id is provided
        if config.branch_id:
            branch = db.query(BranchDetails).filter_by(id=config.branch_id).first()
            if not branch:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Branch not found"
                )
        
        new_config = LeadFetchConfig(
            role=config.role,
            branch_id=config.branch_id,
            per_request_limit=config.per_request_limit,
            daily_call_limit=config.daily_call_limit,
            last_fetch_limit=config.last_fetch_limit,  # NEW FIELD
            assignment_ttl_hours=config.assignment_ttl_hours
        )
        
        db.add(new_config)
        db.commit()
        db.refresh(new_config)
        
        return LeadFetchConfigResponse(
            id=new_config.id,
            role=new_config.role.value if new_config.role else None,
            branch_id=new_config.branch_id,
            per_request_limit=new_config.per_request_limit,
            daily_call_limit=new_config.daily_call_limit,
            last_fetch_limit=new_config.last_fetch_limit,
            assignment_ttl_hours=new_config.assignment_ttl_hours
        )
        
    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Configuration already exists for this role/branch combination"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating fetch configuration: {str(e)}"
        )


@router.get("/", response_model=List[LeadFetchConfigDetails])
def get_all_fetch_configs(
    db: Session = Depends(get_db),
):
    """Get all lead fetch configurations"""
    try:
        configs = db.query(LeadFetchConfig).all()
        
        result = []
        for config in configs:
            config_dict = {
                "id": config.id,
                "role": config.role.value if config.role else None,
                "branch_id": config.branch_id,
                "per_request_limit": config.per_request_limit,
                "daily_call_limit": config.daily_call_limit,
                "last_fetch_limit": config.last_fetch_limit,
                "assignment_ttl_hours": config.assignment_ttl_hours,
                "branch_name": None,
                "branch_address": None
            }
            
            # Get branch details if branch_id is set
            if config.branch_id:
                branch = db.query(BranchDetails).filter_by(id=config.branch_id).first()
                if branch:
                    config_dict["branch_name"] = branch.name
                    config_dict["branch_address"] = branch.address
            
            result.append(LeadFetchConfigDetails(**config_dict))
        
        return result
        
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching configurations: {str(e)}"
        )


@router.get("/{config_id}", response_model=LeadFetchConfigDetails)
def get_fetch_config(
    config_id: int,
    db: Session = Depends(get_db),
):
    """Get a specific lead fetch configuration by ID"""
    try:
        config = db.query(LeadFetchConfig).filter_by(id=config_id).first()
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fetch configuration not found"
            )
        
        # Prepare response with branch details
        config_dict = {
            "id": config.id,
            "role": config.role.value if config.role else None,
            "branch_id": config.branch_id,
            "per_request_limit": config.per_request_limit,
            "daily_call_limit": config.daily_call_limit,
            "last_fetch_limit": config.last_fetch_limit,
            "assignment_ttl_hours": config.assignment_ttl_hours,
            "branch_name": None,
            "branch_address": None
        }
        
        # Get branch details if branch_id is set
        if config.branch_id:
            branch = db.query(BranchDetails).filter_by(id=config.branch_id).first()
            if branch:
                config_dict["branch_name"] = branch.name
                config_dict["branch_address"] = branch.address
        
        return LeadFetchConfigDetails(**config_dict)
        
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching configuration: {str(e)}"
        )


@router.put("/{config_id}", response_model=LeadFetchConfigResponse)
def update_fetch_config(
    config_id: int,
    updates: LeadFetchConfigUpdate,
    db: Session = Depends(get_db),
):
    """Update a lead fetch configuration"""
    try:
        config = db.query(LeadFetchConfig).filter_by(id=config_id).first()
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fetch configuration not found"
            )
        
        # Update only provided fields
        update_data = updates.dict(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(config, field):
                setattr(config, field, value)
        
        db.commit()
        db.refresh(config)
        
        return LeadFetchConfigResponse(
            id=config.id,
            role=config.role.value if config.role else None,
            branch_id=config.branch_id,
            per_request_limit=config.per_request_limit,
            daily_call_limit=config.daily_call_limit,
            last_fetch_limit=config.last_fetch_limit,
            assignment_ttl_hours=config.assignment_ttl_hours
        )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating fetch configuration: {str(e)}"
        )


@router.delete("/{config_id}")
def delete_fetch_config(
    config_id: int,
    db: Session = Depends(get_db),
):
    """Delete a lead fetch configuration"""
    try:
        config = db.query(LeadFetchConfig).filter_by(id=config_id).first()
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fetch configuration not found"
            )
        
        db.delete(config)
        db.commit()
        
        return {"message": "Fetch configuration deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting fetch configuration: {str(e)}"
        )
    
    