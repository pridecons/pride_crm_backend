# routes/leads/leads.py - COMPLETE FIXED VERSION ACCORDING TO LEAD MODEL
import os
import uuid
import json
from typing import Optional, List, Any, Dict, Union
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DisconnectionError
from pydantic import BaseModel, constr, validator
from fastapi.responses import JSONResponse

from db.connection import get_db
from db.models import (
    Lead, LeadSource, LeadResponse, BranchDetails, 
    UserDetails, LeadStory, Payment
)

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
        
        # Convert to response format
        lead_dict = safe_convert_lead_to_dict(lead)
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
):
    """Get a specific lead by ID"""
    try:
        lead = db.query(Lead).filter_by(id=lead_id).first()
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
        
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
):
    """Update a lead"""
    try:
        lead = db.query(Lead).filter_by(id=lead_id).first()
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
        
        # Apply updates
        for field, value in prepared_data.items():
            if hasattr(lead, field):
                setattr(lead, field, value)

        if is_old:
           lead.is_old_lead  = True
        
        db.commit()
        db.refresh(lead)
        
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


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lead(
    lead_id: int,
    db: Session = Depends(get_db),
):
    """Delete a lead"""
    try:
        lead = db.query(Lead).filter_by(id=lead_id).first()
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
        
        # Delete associated files
        for file_path in [lead.aadhar_front_pic, lead.aadhar_back_pic, lead.pan_pic]:
            if file_path and os.path.exists(file_path.lstrip('/')):
                try:
                    os.remove(file_path.lstrip('/'))
                except OSError:
                    pass
        
        db.delete(lead)
        db.commit()
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting lead: {str(e)}"
        )


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
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead {lead_id} not found"
        )

    # 2️⃣ Save each uploaded file and update the model
    if aadhar_front:
        path = save_uploaded_file(aadhar_front, lead_id, "aadhar_front")
        lead.aadhar_front_pic = path

    if aadhar_back:
        path = save_uploaded_file(aadhar_back, lead_id, "aadhar_back")
        lead.aadhar_back_pic = path

    if pan_pic:
        path = save_uploaded_file(pan_pic, lead_id, "pan_pic")
        lead.pan_pic = path

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


@router.get("/mobile/{mobile}")
def get_lead_by_mobile(
    mobile: str,
    db: Session = Depends(get_db),
):
    """Get lead by mobile number"""
    try:
        lead = db.query(Lead).filter(
            (Lead.mobile == mobile) | (Lead.alternate_mobile == mobile)
        ).first()
        
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found with this mobile number"
            )
        
        lead_dict = safe_convert_lead_to_dict(lead)
        return LeadOut(**lead_dict)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching lead by mobile: {str(e)}"
        )


@router.get("/email/{email}")
def get_lead_by_email(
    email: str,
    db: Session = Depends(get_db),
):
    """Get lead by email"""
    try:
        lead = db.query(Lead).filter(Lead.email == email).first()
        
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found with this email"
            )
        
        lead_dict = safe_convert_lead_to_dict(lead)
        return LeadOut(**lead_dict)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching lead by email: {str(e)}"
        )
    
    