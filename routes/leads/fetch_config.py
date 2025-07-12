# routes/leads/fetch_config.py - Lead Fetch Configuration API (Branch & Role based)

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
    role: Optional[UserRoleEnum] = None
    branch_id: Optional[int] = None
    per_request_limit: Optional[int] = None
    daily_call_limit: Optional[int] = None
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

    @validator('assignment_ttl_hours')
    def validate_assignment_ttl_hours(cls, v):
        if v is not None:
            if v <= 0:
                raise ValueError('assignment_ttl_hours must be greater than 0')
            if v > 24 * 30:
                raise ValueError('assignment_ttl_hours cannot exceed 720 hours (30 days)')
        return v


class LeadFetchConfigOut(BaseModel):
    id: int
    role: Optional[str] = None  # String representation of enum
    branch_id: Optional[int] = None
    per_request_limit: int
    daily_call_limit: int
    assignment_ttl_hours: int

    @validator('role', pre=True)
    def serialize_role(cls, v):
        if hasattr(v, 'value'):
            return v.value
        return v

    class Config:
        from_attributes = True


class LeadFetchConfigDetails(LeadFetchConfigOut):
    branch_name: Optional[str] = None
    branch_address: Optional[str] = None


# API Endpoints

@router.post("/", response_model=LeadFetchConfigOut, status_code=status.HTTP_201_CREATED)
def create_fetch_config(
    config_in: LeadFetchConfigCreate,
    db: Session = Depends(get_db),
):
    """Create a new lead fetch configuration"""
    try:
        # Validate that either role or branch_id is provided
        if not config_in.role and not config_in.branch_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either role or branch_id must be specified"
            )
        
        # Validate branch exists if branch_id is provided
        if config_in.branch_id:
            branch = db.query(BranchDetails).filter_by(id=config_in.branch_id).first()
            if not branch:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Branch with ID '{config_in.branch_id}' does not exist"
                )
        
        # Check for existing configuration
        existing_config = None
        if config_in.role and config_in.branch_id:
            # Check for role + branch combination
            existing_config = db.query(LeadFetchConfig).filter_by(
                role=config_in.role, 
                branch_id=config_in.branch_id
            ).first()
            if existing_config:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Configuration for role '{config_in.role.value}' in branch '{config_in.branch_id}' already exists"
                )
        elif config_in.role:
            # Global role configuration
            existing_config = db.query(LeadFetchConfig).filter_by(
                role=config_in.role, 
                branch_id=None
            ).first()
            if existing_config:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Global configuration for role '{config_in.role.value}' already exists"
                )
        elif config_in.branch_id:
            # Global branch configuration
            existing_config = db.query(LeadFetchConfig).filter_by(
                role=None, 
                branch_id=config_in.branch_id
            ).first()
            if existing_config:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Global configuration for branch '{config_in.branch_id}' already exists"
                )
        
        # Create configuration
        config = LeadFetchConfig(**config_in.dict())
        db.add(config)
        db.commit()
        db.refresh(config)
        
        return config
        
    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Configuration already exists for this role or branch"
        )
    except (OperationalError, DisconnectionError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating fetch configuration: {str(e)}"
        )


@router.get("/", response_model=List[LeadFetchConfigDetails])
def get_all_fetch_configs(
    skip: int = 0,
    limit: int = 100,
    role: Optional[str] = None,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Get all lead fetch configurations with optional filtering"""
    try:
        query = db.query(LeadFetchConfig)
        
        if role:
            try:
                role_enum = UserRoleEnum(role)
                query = query.filter(LeadFetchConfig.role == role_enum)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid role. Valid roles: {[r.value for r in UserRoleEnum]}"
                )
        
        if branch_id:
            query = query.filter(LeadFetchConfig.branch_id == branch_id)
        
        configs = query.offset(skip).limit(limit).all()
        
        # Enhance with branch details
        result = []
        for config in configs:
            config_dict = {
                "id": config.id,
                "role": config.role.value if config.role else None,
                "branch_id": config.branch_id,
                "per_request_limit": config.per_request_limit,
                "daily_call_limit": config.daily_call_limit,
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


@router.put("/{config_id}", response_model=LeadFetchConfigOut)
def update_fetch_config(
    config_id: int,
    config_in: LeadFetchConfigUpdate,
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
        
        # Get update data
        update_data = config_in.dict(exclude_unset=True)
        
        # Validate branch exists if branch_id is being updated
        if "branch_id" in update_data and update_data["branch_id"]:
            branch = db.query(BranchDetails).filter_by(id=update_data["branch_id"]).first()
            if not branch:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Branch with ID '{update_data['branch_id']}' does not exist"
                )
        
        # Check for conflicts if role or branch_id is being changed
        new_role = update_data.get("role", config.role)
        new_branch_id = update_data.get("branch_id", config.branch_id)
        
        if new_role or new_branch_id:
            existing = db.query(LeadFetchConfig).filter(
                LeadFetchConfig.role == new_role,
                LeadFetchConfig.branch_id == new_branch_id,
                LeadFetchConfig.id != config_id
            ).first()
            if existing:
                role_str = new_role.value if new_role else "None"
                branch_str = str(new_branch_id) if new_branch_id else "None"
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Configuration for role '{role_str}' and branch '{branch_str}' already exists"
                )
        
        # Apply updates
        for field, value in update_data.items():
            setattr(config, field, value)
        
        db.commit()
        db.refresh(config)
        
        return config
        
    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Configuration already exists for this role and branch combination"
        )
    except (OperationalError, DisconnectionError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating configuration: {str(e)}"
        )


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
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
        return None
        
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting configuration: {str(e)}"
        )

