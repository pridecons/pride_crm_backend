import os
import uuid
import json
from typing import Optional, List, Any, Dict, Union
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DisconnectionError
from pydantic import BaseModel, constr, validator
from db.connection import get_db
from db.models import (
    Lead, LeadSource, LeadResponse, BranchDetails, 
    UserDetails, Payment, LeadComment, LeadStory, LeadAssignment, LeadFetchConfig
)
from utils.AddLeadStory import AddLeadStory
from db.connection import get_db
from routes.auth.auth_dependency import get_current_user
from routes.notification.notification_scheduler import schedule_callback


router = APIRouter(
    prefix="/leads",
    tags=["leads"],
)

UPLOAD_DIR = "static/lead_documents"

class LeadBase(BaseModel):
    # Personal Information
    full_name: Optional[str] = None
    director_name: Optional[str] = None
    father_name: Optional[str] = None
    gender: Optional[str] = None
    marital_status: Optional[str] = None
    
    # Contact Information
    email: Optional[str] = None
    mobile: Optional[str] = None
    alternate_mobile: Optional[str] = None
    
    # Documents
    aadhaar: Optional[str] = None
    pan: Optional[str] = None
    gstin: Optional[str] = None
    
    # Address Information
    state: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = None
    
    # Additional Information
    dob: Optional[date] = None
    occupation: Optional[str] = None
    segment: Optional[List[str]] = None
    experience: Optional[str] = None
    investment: Optional[str] = None
    profile: Optional[str] = None
    
    # Lead Management
    lead_response_id: Optional[int] = None
    lead_source_id: Optional[int] = None
    
    branch_id: Optional[int] = None
    ft_to_date: Optional[str] = None
    ft_from_date: Optional[str] = None
    is_client: Optional[bool] = None
    assigned_to_user: Optional[str] = None
    response_changed_at: Optional[datetime] = None
    assigned_for_conversion: Optional[bool] = False
    conversion_deadline: Optional[datetime] = None


class LeadCreate(LeadBase):
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None


class LeadUpdate(BaseModel):
    # Personal Information
    full_name: Optional[str] = None
    director_name: Optional[str] = None
    father_name: Optional[str] = None
    gender: Optional[str] = None
    marital_status: Optional[str] = None
    
    # Contact Information
    email: Optional[str] = None
    mobile: Optional[str] = None
    alternate_mobile: Optional[str] = None
    
    # Documents
    aadhaar: Optional[str] = None
    pan: Optional[str] = None
    gstin: Optional[str] = None
    
    # Address Information
    state: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = None
    
    # Additional Information
    dob: Optional[date] = None
    occupation: Optional[str] = None
    segment: Optional[List[str]] = None
    experience: Optional[str] = None
    investment: Optional[str] = None
    profile: Optional[str] = None
    
    # Lead Management
    lead_response_id: Optional[int] = None
    lead_source_id: Optional[int] = None
    
    # Status Management
    lead_status: Optional[str] = None
    call_back_date: Optional[datetime] = None
    kyc: Optional[bool] = None
    is_old_lead: Optional[bool] = None
    ft_to_date: Optional[str] = None
    ft_from_date: Optional[str] = None
    is_client: Optional[bool] = None
    assigned_to_user: Optional[str] = None
    response_changed_at: Optional[datetime] = None
    assigned_for_conversion: Optional[bool] = False
    conversion_deadline: Optional[datetime] = None


class LeadOut(BaseModel):
    id: int
    
    # Personal Information
    full_name: Optional[str] = None
    director_name: Optional[str] = None
    father_name: Optional[str] = None
    gender: Optional[str] = None
    marital_status: Optional[str] = None
    
    # Contact Information
    email: Optional[str] = None
    mobile: Optional[str] = None
    alternate_mobile: Optional[str] = None
    
    # Documents
    aadhaar: Optional[str] = None
    pan: Optional[str] = None
    gstin: Optional[str] = None
    
    # Address Information
    state: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = None
    
    # Additional Information
    dob: Optional[date] = None
    occupation: Optional[str] = None
    segment: Optional[List[str]] = None
    experience: Optional[str] = None
    investment: Optional[str] = None
    profile: Optional[str] = None
    
    # Lead Management
    lead_response_id: Optional[int] = None
    lead_source_id: Optional[int] = None
    branch_id: Optional[int] = None
    
    # Metadata
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None
    
    # File uploads
    aadhar_front_pic: Optional[str] = None
    aadhar_back_pic: Optional[str] = None
    pan_pic: Optional[str] = None
    
    # Status fields
    kyc: Optional[bool] = False
    kyc_id: Optional[str] = None
    is_old_lead: Optional[bool] = False
    call_back_date: Optional[datetime] = None
    lead_status: Optional[str] = None
    ft_to_date: Optional[str] = None
    ft_from_date: Optional[str] = None
    is_client: Optional[bool] = None
    assigned_to_user: Optional[str] = None
    response_changed_at: Optional[datetime] = None
    assigned_for_conversion: Optional[bool] = False
    conversion_deadline: Optional[datetime] = None
    
    # Timestamps
    created_at: datetime
    
    @validator('segment', pre=True, always=True)
    def parse_segment(cls, v):
        """Parse segment field safely"""
        if v is None:
            return None
        
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return parsed if isinstance(parsed, list) else [parsed]
            except json.JSONDecodeError:
                return [v] if v.strip() else None
        
        if isinstance(v, list):
            return v
        
        return [str(v)] if v is not None else None
    
    class Config:
        from_attributes = True

class CommentOut(BaseModel):
    id: int
    lead_id: int
    user_id: str
    timestamp: datetime
    comment: str

    class Config:
        from_attributes = True

# Utility Functions
def save_uploaded_file(file: UploadFile, lead_id: int, file_type: str) -> str:
    """Save uploaded file and return file path"""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    # Generate unique filename
    file_extension = file.filename.split('.')[-1] if '.' in file.filename else 'jpg'
    filename = f"lead_{lead_id}_{file_type}_{uuid.uuid4().hex}.{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    # Save file
    with open(file_path, "wb") as buffer:
        content = file.file.read()
        buffer.write(content)
    
    return f"/{UPLOAD_DIR}/{filename}"


def prepare_lead_data_for_db(lead_data: dict) -> dict:
    """Prepare lead data for database insertion"""
    prepared_data = lead_data.copy()
    
    # Handle segment field - always convert to JSON string
    if 'segment' in prepared_data and prepared_data['segment'] is not None:
        if isinstance(prepared_data['segment'], list):
            prepared_data['segment'] = json.dumps(prepared_data['segment'])
        elif isinstance(prepared_data['segment'], str):
            try:
                parsed = json.loads(prepared_data['segment'])
                if not isinstance(parsed, list):
                    parsed = [parsed]
                prepared_data['segment'] = json.dumps(parsed)
            except json.JSONDecodeError:
                prepared_data['segment'] = json.dumps([prepared_data['segment']])
        else:
            prepared_data['segment'] = json.dumps([str(prepared_data['segment'])])

    
    return prepared_data


def safe_convert_lead_to_dict(lead) -> dict:
    """Safely convert Lead model to dictionary with proper JSON handling"""
    try:
        lead_dict = {}
        for column in lead.__table__.columns:
            value = getattr(lead, column.name, None)
            
            if column.name == 'segment':
                if value is not None:
                    try:
                        parsed = json.loads(value)
                        lead_dict[column.name] = parsed if isinstance(parsed, list) else [parsed]
                    except (json.JSONDecodeError, TypeError):
                        lead_dict[column.name] = [value] if value else []
                else:
                    lead_dict[column.name] = None
                    
            else:
                lead_dict[column.name] = value
        
        return lead_dict
        
    except Exception as e:
        print(f"Error converting lead to dict: {str(e)}")
        # Return minimal safe data
        return {
            "id": getattr(lead, 'id', None),
            "full_name": getattr(lead, 'full_name', None),
            "director_name": getattr(lead, 'director_name', None),
            "father_name": getattr(lead, 'father_name', None),
            "gender": getattr(lead, 'gender', None),
            "marital_status": getattr(lead, 'marital_status', None),
            "email": getattr(lead, 'email', None),
            "mobile": getattr(lead, 'mobile', None),
            "alternate_mobile": getattr(lead, 'alternate_mobile', None),
            "aadhaar": getattr(lead, 'aadhaar', None),
            "pan": getattr(lead, 'pan', None),
            "gstin": getattr(lead, 'gstin', None),
            "state": getattr(lead, 'state', None),
            "city": getattr(lead, 'city', None),
            "district": getattr(lead, 'district', None),
            "address": getattr(lead, 'address', None),
            "pincode": getattr(lead, 'pincode', None),
            "country": getattr(lead, 'country', None),
            "dob": getattr(lead, 'dob', None),
            "occupation": getattr(lead, 'occupation', None),
            "experience": getattr(lead, 'experience', None),
            "investment": getattr(lead, 'investment', None),
            "profile": getattr(lead, 'profile', None),
            "created_at": getattr(lead, 'created_at', datetime.now()),
            "lead_status": getattr(lead, 'lead_status', None),
            "kyc": getattr(lead, 'kyc', False),
            "segment": None,
            "lead_response_id": getattr(lead, 'lead_response_id', None),
            "lead_source_id": getattr(lead, 'lead_source_id', None),
            "branch_id": getattr(lead, 'branch_id', None),
            "created_by": getattr(lead, 'created_by', None),
            "created_by_name": getattr(lead, 'created_by_name', None),
            "aadhar_front_pic": getattr(lead, 'aadhar_front_pic', None),
            "aadhar_back_pic": getattr(lead, 'aadhar_back_pic', None),
            "pan_pic": getattr(lead, 'pan_pic', None),
            "kyc_id": getattr(lead, 'kyc_id', None),
            "is_old_lead": getattr(lead, 'is_old_lead', False),
            "call_back_date": getattr(lead, 'call_back_date', None),
        }


# API Endpoints

@router.post("/", response_model=LeadOut, status_code=status.HTTP_201_CREATED)
def create_lead(
    lead_in: LeadCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create a new lead"""
    try:
        # Validate lead source if provided
        if lead_in.lead_source_id:
            lead_source = db.query(LeadSource).filter_by(id=lead_in.lead_source_id).first()
            if not lead_source:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Lead source with ID {lead_in.lead_source_id} not found"
                )
        
        # Validate lead response if provided
        is_old = False
        if lead_in.lead_response_id:
            lr = db.query(LeadResponse).filter_by(id=lead_in.lead_response_id).first()
            if not lr:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Lead response with ID {lead_in.lead_response_id} not found"
                )
            is_old = True
        
        # Check for duplicate email or mobile if provided
        if lead_in.email or lead_in.mobile:
            query = db.query(Lead)
            conditions = []
            
            if lead_in.email:
                conditions.append(Lead.email == lead_in.email)
            if lead_in.mobile:
                conditions.append(Lead.mobile == lead_in.mobile)
            
            if conditions:
                from sqlalchemy import or_
                existing_lead = query.filter(or_(*conditions)).first()
                if existing_lead:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Lead with this email or mobile already exists"
                    )
        
        # Prepare data for database
        lead_data = prepare_lead_data_for_db(lead_in.dict(exclude_none=True))
        if is_old:
           lead_data["is_old_lead"] = True
        
        # Create lead
        lead = Lead(**lead_data)
        
        db.add(lead)
        db.commit()
        db.refresh(lead)
                
        # If lead has response (is_old = True), also set additional old lead fields
        if is_old:
            # Get user's config for timeout calculation
            from routes.leads.fetch_config import load_fetch_config
            
            config, _ = load_fetch_config(db, current_user)
            timeout_days = config.old_lead_remove_days or 30
            
            # Set conversion deadline and assignment fields
            lead.assigned_for_conversion = True
            lead.assigned_to_user = current_user.employee_code
            lead.conversion_deadline = datetime.utcnow() + timedelta(days=timeout_days)
            lead.response_changed_at = datetime.utcnow()
        
        # Commit assignment and any additional changes
        db.commit()
        db.refresh(lead)
        # ===== END NEW CODE =====
        
        # Convert to response format
        lead_dict = safe_convert_lead_to_dict(lead)
        msg = f"Lead created by {current_user.name} ({current_user.employee_code})"
        
        # Add assignment info to story if lead was assigned
        if is_old:
            msg += " and automatically assigned for conversion"
        else:
            msg += " and assigned to creator"
            
        AddLeadStory(lead.id, current_user.employee_code, msg)
        return LeadOut(**lead_dict)
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating lead: {str(e)}"
        )

@router.get("/", response_model=List[LeadOut])
def get_all_leads(
    skip: int = 0,
    limit: int = 100,
    branch_id: Optional[int] = None,
    lead_status: Optional[str] = None,
    lead_source_id: Optional[int] = None,
    created_by: Optional[str] = None,
    kyc_only: bool = False,
    gender: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get all leads with filtering options"""
    try:
        query = db.query(Lead)
        
        if branch_id:
            query = query.filter(Lead.branch_id == branch_id)
        
        if lead_status:
            query = query.filter(Lead.lead_status == lead_status)
        
        if lead_source_id:
            query = query.filter(Lead.lead_source_id == lead_source_id)
        
        if created_by:
            query = query.filter(Lead.created_by == created_by)
        
        if kyc_only:
            query = query.filter(Lead.kyc == True)
        
        if gender:
            query = query.filter(Lead.gender == gender)
        
        if city:
            query = query.filter(Lead.city.ilike(f"%{city}%"))
        
        if state:
            query = query.filter(Lead.state.ilike(f"%{state}%"))

        query = query.filter(Lead.is_delete == False)
        
        leads = query.order_by(Lead.created_at.desc()).offset(skip).limit(limit).all()
        
        # Convert to list with proper error handling
        result = []
        for lead in leads:
            try:
                lead_dict = safe_convert_lead_to_dict(lead)
                lead_out = LeadOut(**lead_dict)
                result.append(lead_out)
            except Exception as e:
                print(f"Failed to convert lead {lead.id}: {str(e)}")
                continue
        
        return result
        
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching leads: {str(e)}"
        )


@router.get("/{lead_id}", response_model=LeadOut)
def get_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get a specific lead by ID"""
    try:
        lead = db.query(Lead).filter_by(id=lead_id).first()
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
        msg = f"Lead viewed by {current_user.name}"
        AddLeadStory(lead.id, current_user.employee_code, msg)
        
        lead_dict = safe_convert_lead_to_dict(lead)
        return LeadOut(**lead_dict)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching lead: {str(e)}"
        )


@router.put("/{lead_id}", response_model=LeadOut)
def update_lead(
    lead_id: int,
    lead_in: LeadUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Update a lead"""
    try:
        lead = db.query(Lead).filter_by(id=lead_id).first()
        before = {f: getattr(lead, f) for f in lead_in.dict(exclude_unset=True).keys()}
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
        
        # Prepare update data
        update_data = prepare_lead_data_for_db(lead_in.dict(exclude_unset=True))
        
        # Validate references if being updated
        if "lead_source_id" in update_data:
            lead_source = db.query(LeadSource).filter_by(id=update_data["lead_source_id"]).first()
            if not lead_source:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Lead source with ID {update_data['lead_source_id']} not found"
                )
        is_old = False
        if "lead_response_id" in update_data:
            lead_response = db.query(LeadResponse).filter_by(id=update_data["lead_response_id"]).first()
            is_old = True
            if not lead_response:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Lead response with ID {update_data['lead_response_id']} not found"
                )
        
        # Check for duplicates if updating email or mobile
        if "email" in update_data and update_data["email"]:
            existing_lead = db.query(Lead).filter(
                Lead.email == update_data["email"],
                Lead.id != lead_id
            ).first()
            if existing_lead:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Another lead with this email already exists"
                )
        
        if "mobile" in update_data and update_data["mobile"]:
            existing_lead = db.query(Lead).filter(
                Lead.mobile == update_data["mobile"],
                Lead.id != lead_id
            ).first()
            if existing_lead:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Another lead with this mobile already exists"
                )
        
        # Apply updates
        for field, value in update_data.items():
            setattr(lead, field, value)
        if is_old:
           lead.is_old_lead = True
        
        db.commit()
        db.refresh(lead)

        diffs = []
        for k, old in before.items():
            new = getattr(lead, k)
            if old != new:
                diffs.append(f"{k} → '{old}' ➔ '{new}'")
        msg = "Lead updated by " + current_user.name + ": " + "; ".join(diffs)
        AddLeadStory(lead.id, current_user.employee_code, msg)
        
        lead_dict = safe_convert_lead_to_dict(lead)
        return LeadOut(**lead_dict)
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating lead: {str(e)}"
        )


@router.patch("/{lead_id}", response_model=LeadOut)
def patch_lead(
    lead_id: int,
    lead_updates: LeadUpdate,
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user),
):
    """Patch/Update specific fields of a lead"""
    try:
        lead = db.query(Lead).filter_by(id=lead_id).first()
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
        
        update_data = lead_updates.dict(exclude_unset=True)
        
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields provided for update"
            )
        
        # Validate references
        if "lead_source_id" in update_data and update_data["lead_source_id"]:
            lead_source = db.query(LeadSource).filter_by(id=update_data["lead_source_id"]).first()
            if not lead_source:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Lead source with ID {update_data['lead_source_id']} not found"
                )
        is_old = False
        if "lead_response_id" in update_data and update_data["lead_response_id"]:
            lead_response = db.query(LeadResponse).filter_by(id=update_data["lead_response_id"]).first()
            is_old = True
            if not lead_response:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Lead response with ID {update_data['lead_response_id']} not found"
                )
        
        # Check for duplicates
        if "email" in update_data and update_data["email"]:
            existing_lead = db.query(Lead).filter(
                Lead.email == update_data["email"],
                Lead.id != lead_id
            ).first()
            if existing_lead:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Another lead with this email already exists"
                )
        
        if "mobile" in update_data and update_data["mobile"]:
            existing_lead = db.query(Lead).filter(
                Lead.mobile == update_data["mobile"],
                Lead.id != lead_id
            ).first()
            if existing_lead:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Another lead with this mobile already exists"
                )
        
        # Prepare update data for database
        prepared_data = prepare_lead_data_for_db(update_data)
        
        old_vals = {field: getattr(lead, field) for field in prepared_data}
        # Apply updates
        for field, value in prepared_data.items():
            if hasattr(lead, field):
                setattr(lead, field, value)

        if is_old:
           lead.is_old_lead  = True

        if "lead_response_id" in prepared_data:
           lead.is_old_lead = True
        
        db.commit()
        db.refresh(lead)

        changes = []
        for field, old in old_vals.items():
            new = getattr(lead, field)
            if old != new:
                changes.append(f"{field}: '{old}'→'{new}'")

        if changes:
            msg = (
                f"{current_user.name} ({current_user.employee_code}) "
                f"updated lead: " + "; ".join(changes)
            )
            AddLeadStory(lead.id, current_user.employee_code, msg)
        
        lead_dict = safe_convert_lead_to_dict(lead)
        return LeadOut(**lead_dict)
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating lead: {str(e)}"
        )


@router.delete(
    "/{lead_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete (soft by default) or hard-delete a lead"
)
def delete_lead(
    lead_id: int,
    hard_delete: bool = Query(
        False,
        description="Perform soft delete by default; set false for hard delete"
    ),
    db: Session = Depends(get_db),
):
    """Delete a lead—soft by default, hard if `hard_delete=True`."""
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found"
        )

    if not hard_delete:
        # Soft delete: just flip the flag & save
        lead.is_delete = True
        db.commit()
        return {"message": "Lead deleted successfully"}

    # Hard delete: remove files, then the record
    for file_path in (lead.aadhar_front_pic, lead.aadhar_back_pic, lead.pan_pic):
        if file_path:
            p = file_path.lstrip('/')
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass

    db.delete(lead)
    db.commit()
    return {"message": "Lead deleted"}


@router.post(
    "/{lead_id}/upload-documents",
    response_model=LeadOut,
    status_code=status.HTTP_200_OK,
    summary="Upload Aadhar & PAN for a lead",
)
def upload_lead_documents(
    lead_id: int,
    aadhar_front: UploadFile = File(None),
    aadhar_back: UploadFile = File(None),
    pan_pic: UploadFile    = File(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Upload one or more of:
    - aadhar_front: front image of Aadhar card
    - aadhar_back: back image of Aadhar card
    - pan_pic:       image of PAN card

    Any missing file will be skipped.
    """
    # 1️⃣ Fetch lead
    lead = db.query(Lead).filter_by(id=lead_id).first()
    changes = []
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead {lead_id} not found"
        )

    # 2️⃣ Save each uploaded file and update the model
    if aadhar_front:
        path = save_uploaded_file(aadhar_front, lead_id, "aadhar_front")
        lead.aadhar_front_pic = path
        changes.append("Aadhar front uploaded")

    if aadhar_back:
        path = save_uploaded_file(aadhar_back, lead_id, "aadhar_back")
        lead.aadhar_back_pic = path
        changes.append("Aadhar back uploaded")

    if pan_pic:
        path = save_uploaded_file(pan_pic, lead_id, "pan_pic")
        lead.pan_pic = path
        changes.append("Pan Card uploaded")

    if changes:
        msg = f"{current_user.name} uploaded: " + ", ".join(changes)
        AddLeadStory(lead.id, current_user.employee_code, msg)

    # 3️⃣ Persist changes
    db.commit()
    db.refresh(lead)

    # 4️⃣ Return updated lead
    lead_dict = safe_convert_lead_to_dict(lead)
    return LeadOut(**lead_dict)

# Search endpoints

@router.get("/search/")
def search_leads(
    q: str,
    search_type: str = "all",  # all, name, mobile, email, pan, aadhaar
    db: Session = Depends(get_db),
):
    """Search leads by various criteria"""
    try:
        if not q or len(q.strip()) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Search query must be at least 2 characters long"
            )
        
        query = db.query(Lead)
        search_term = f"%{q.strip()}%"
        
        if search_type == "name":
            query = query.filter(
                Lead.full_name.ilike(search_term) |
                Lead.father_name.ilike(search_term) |
                Lead.director_name.ilike(search_term)
            )
        elif search_type == "mobile":
            query = query.filter(
                Lead.mobile.ilike(search_term) |
                Lead.alternate_mobile.ilike(search_term)
            )
        elif search_type == "email":
            query = query.filter(Lead.email.ilike(search_term))
        elif search_type == "pan":
            query = query.filter(Lead.pan.ilike(search_term))
        elif search_type == "aadhaar":
            query = query.filter(Lead.aadhaar.ilike(search_term))
        else:  # search_type == "all"
            query = query.filter(
                Lead.full_name.ilike(search_term) |
                Lead.father_name.ilike(search_term) |
                Lead.director_name.ilike(search_term) |
                Lead.mobile.ilike(search_term) |
                Lead.alternate_mobile.ilike(search_term) |
                Lead.email.ilike(search_term) |
                Lead.pan.ilike(search_term) |
                Lead.aadhaar.ilike(search_term) |
                Lead.city.ilike(search_term) |
                Lead.state.ilike(search_term)
            )

        query = query.filter(Lead.is_delete == False)
        
        leads = query.limit(50).all()
        
        result = []
        for lead in leads:
            try:
                lead_dict = safe_convert_lead_to_dict(lead)
                lead_out = LeadOut(**lead_dict)
                result.append(lead_out)
            except Exception as e:
                print(f"Failed to convert lead {lead.id}: {str(e)}")
                continue
        
        return {
            "search_query": q,
            "search_type": search_type,
            "total_results": len(result),
            "leads": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error searching leads: {str(e)}"
        )

def load_fetch_config(db: Session, user: UserDetails):
    """Load fetch config for user - same as in leads_fetch.py"""
    cfg = None
    source = "default"

    # Try role+branch first
    if user.role and user.branch_id:
        cfg = db.query(LeadFetchConfig).filter_by(
            role=user.role, 
            branch_id=user.branch_id
        ).first()
        if cfg:
            source = "role_branch"

    # Try role global
    if not cfg and user.role:
        cfg = db.query(LeadFetchConfig).filter_by(
            role=user.role, 
            branch_id=None
        ).first()
        if cfg:
            source = "role_global"

    # Try branch global
    if not cfg and user.branch_id:
        cfg = db.query(LeadFetchConfig).filter_by(
            role=None, 
            branch_id=user.branch_id
        ).first()
        if cfg:
            source = "branch_global"

    # Default fallback
    if not cfg:
        defaults = {
            "SUPERADMIN": dict(old_lead_remove_days=15),
            "BRANCH_MANAGER": dict(old_lead_remove_days=20),
            "SALES_MANAGER": dict(old_lead_remove_days=25),
            "TL": dict(old_lead_remove_days=30),
            "BA": dict(old_lead_remove_days=30),
            "SBA": dict(old_lead_remove_days=25),
        }
        role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
        cfg_values = defaults.get(role_str, {"old_lead_remove_days": 30})

        class TempConfig:
            def __init__(self, **kw):
                for k, v in kw.items():
                    setattr(self, k, v)

        cfg = TempConfig(**cfg_values)

    return cfg, source


from routes.notification.notification_service import notification_service

class ChangeResponse(BaseModel):
    lead_response_id: int
    ft_to_date: Optional[str] = None
    ft_from_date: Optional[str] = None
    call_back_date: Optional[datetime] = None

@router.patch(
    "/{lead_id}/response",
    response_model=LeadOut,
    summary="Change the LeadResponse on a lead with retention logic"
)
async def change_lead_response(
    lead_id: int,
    payload: ChangeResponse,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 1) Fetch lead
    lead = db.query(Lead).filter_by(id=lead_id, is_delete=False).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # 2) Validate new response
    new_response = db.query(LeadResponse).filter_by(id=payload.lead_response_id).first()
    if not new_response:
        raise HTTPException(
            status_code=400,
            detail=f"LeadResponse with ID {payload.lead_response_id} not found"
        )
    
    # Store old response for logging
    old_response_id = lead.lead_response_id
    old_response_name = "None"
    if old_response_id:
        old_resp = db.query(LeadResponse).filter_by(id=old_response_id).first()
        old_response_name = old_resp.name if old_resp else "Unknown"

    # 2) Check if response is actually changing
    if old_response_id != payload.lead_response_id:
        # Response changed - implement retention logic (Point 8)
        lead.lead_response_id = payload.lead_response_id
        lead.is_old_lead = True  # Point 11: Mark as old lead
        lead.response_changed_at = datetime.utcnow()
        lead.assigned_for_conversion = True
        lead.assigned_to_user = current_user.employee_code
        
        # Get timeout from config (Point 9)
        config, _ = load_fetch_config(db, current_user)
        timeout_days = config.old_lead_remove_days or 30
        lead.conversion_deadline = datetime.utcnow() + timedelta(days=timeout_days)
        
        # Ensure lead stays with current user (Point 8)
        assignment = db.query(LeadAssignment).filter_by(lead_id=lead_id).first()
        if assignment:
            assignment.user_id = current_user.employee_code
            assignment.fetched_at = datetime.utcnow()
        else:
            # Create exclusive assignment
            new_assignment = LeadAssignment(
                lead_id=lead_id,
                user_id=current_user.employee_code,
                fetched_at=datetime.utcnow()
            )
            db.add(new_assignment)

    if payload.call_back_date:
        try:
            # If incoming is naive string, assume ISO and parse; adapt if format differs
            if isinstance(payload.call_back_date, str):
                cb_dt = datetime.fromisoformat(payload.call_back_date)
            else:
                cb_dt = payload.call_back_date  # if already datetime

            if cb_dt <= datetime.utcnow():
                # अगर past date है तो तुरंत notify कर दो
                await notification_service.notify(
                    user_id=current_user.employee_code,
                    title="Call Back Reminder (Immediate)",
                    message=f"Lead {lead.mobile} का call back समय पहले का है ({cb_dt.isoformat()}); तुरंत संपर्क करें।"
                )
            else:
                # future में reminder schedule करो
                schedule_callback(
                    user_id=current_user.employee_code,
                    lead_id=lead_id,
                    callback_dt=cb_dt,
                    mobile=lead.mobile,
                )
            lead.call_back_date = cb_dt
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid call_back_date: {e}")


    # 4) Update ft dates if provided
    if payload.ft_to_date:
        lead.ft_to_date = payload.ft_to_date

    if payload.ft_from_date:
        lead.ft_from_date = payload.ft_from_date

    # 6) Commit changes
    db.commit()
    db.refresh(lead)

    # 7) Add detailed story
    story_msg = (
        f"Response changed by {current_user.name} ({current_user.employee_code}): "
        f"'{old_response_name}' ➔ '{new_response.name}'. "
    )
    
    if old_response_id != payload.lead_response_id:
        story_msg += (
            f"Lead assigned for conversion with {timeout_days} days deadline "
            f"(expires: {lead.conversion_deadline.strftime('%Y-%m-%d %H:%M')}). "
            f"Marked as old lead."
        )
    
    AddLeadStory(lead.id, current_user.employee_code, story_msg)
    
    return LeadOut(**safe_convert_lead_to_dict(lead))


# ─── 2) Add a comment to a lead ────────────────────────────────────────────────

@router.post(
    "/{lead_id}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new comment/story on a lead"
)
def create_lead_comment(
    lead_id: int,
    comment: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 1) ensure lead exists
    lead = db.query(Lead).filter_by(id=lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # 2) ensure user exists
    user = db.query(UserDetails).filter_by(employee_code=current_user.employee_code).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 3) create comment
    comment = LeadComment(
        lead_id=lead_id,
        user_id=current_user.employee_code,
        comment=comment
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)

    return CommentOut.from_orm(comment)


# ─── 3) Get all comments for a lead ───────────────────────────────────────────

@router.get(
    "/{lead_id}/comments",
    response_model=List[CommentOut],
    summary="Fetch all comments for a lead"
)
def list_lead_comments(
    lead_id: int,
    db: Session = Depends(get_db),
):
    # 1) ensure lead exists
    if not db.query(Lead).filter_by(id=lead_id).first():
        raise HTTPException(status_code=404, detail="Lead not found")

    # 2) fetch and return
    comments = (
        db.query(LeadComment)
          .filter_by(lead_id=lead_id)
          .order_by(LeadComment.timestamp)
          .all()
    )
    return [CommentOut.from_orm(c) for c in comments]  
    

@router.post("/{lead_id}/stories")
def post_story(
    lead_id: int,
    user_id: str,
    msg: str,
    db: Session = Depends(get_db),
):
    # (optional) validate lead + user exist
    if not db.query(Lead).filter_by(id=lead_id).first():
        raise HTTPException(404, "Lead not found")
    if not db.query(UserDetails).filter_by(employee_code=user_id).first():
        raise HTTPException(404, "User not found")

    # this uses the standalone helper, which opens its own session
    story = AddLeadStory(lead_id, user_id, msg)
    return {"id": story.id, "timestamp": story.timestamp, "msg": story.msg}

@router.get("/{lead_id}/stories")
def get_story(
    lead_id: int,
    db: Session = Depends(get_db),
):
    if not db.query(Lead).filter_by(id=lead_id).first():
        raise HTTPException(404, "Lead not found")
    
    story = db.query(LeadStory).filter_by(lead_id=lead_id).order_by(LeadStory.timestamp).all()

    return story

