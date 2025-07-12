# routes/leads.py

import os
import uuid
from typing import Optional, List, Any
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DisconnectionError
from pydantic import BaseModel, EmailStr, constr, validator
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


# Pydantic Schemas
class LeadBase(BaseModel):
    full_name: Optional[str] = None
    father_name: Optional[str] = None
    email: Optional[EmailStr] = None
    mobile: Optional[str] = None
    alternate_mobile: Optional[str] = None
    aadhaar: Optional[constr(min_length=12, max_length=12)] = None
    pan: Optional[constr(min_length=10, max_length=10)] = None
    gstin: Optional[constr(max_length=15)] = None
    
    state: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    
    dob: Optional[date] = None
    occupation: Optional[str] = None
    segment: Optional[List[str]] = None
    experience: Optional[str] = None
    investment: Optional[str] = None
    
    lead_response_id: Optional[int] = None
    lead_source_id: Optional[int] = None
    
    comment: Optional[dict] = None
    branch_id: Optional[int] = None


class LeadCreate(LeadBase):
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None


class LeadUpdate(BaseModel):
    full_name: Optional[str] = None
    father_name: Optional[str] = None
    email: Optional[EmailStr] = None
    mobile: Optional[str] = None
    alternate_mobile: Optional[str] = None
    aadhaar: Optional[constr(min_length=12, max_length=12)] = None
    pan: Optional[constr(min_length=10, max_length=10)] = None
    gstin: Optional[constr(max_length=15)] = None
    
    state: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    
    dob: Optional[date] = None
    occupation: Optional[str] = None
    segment: Optional[List[str]] = None
    experience: Optional[str] = None
    investment: Optional[str] = None
    
    lead_response_id: Optional[int] = None
    lead_source_id: Optional[int] = None
    
    comment: Optional[dict] = None
    lead_status: Optional[str] = None
    call_back_date: Optional[datetime] = None
    kyc: Optional[bool] = None


class LeadOut(BaseModel):
    id: int
    full_name: Optional[str] = None
    father_name: Optional[str] = None
    email: Optional[EmailStr] = None
    mobile: Optional[str] = None
    alternate_mobile: Optional[str] = None
    aadhaar: Optional[str] = None
    pan: Optional[str] = None
    gstin: Optional[str] = None
    
    state: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    
    dob: Optional[date] = None
    occupation: Optional[str] = None
    segment: Optional[List[str]] = None
    experience: Optional[str] = None
    investment: Optional[str] = None
    
    lead_response_id: Optional[int] = None
    lead_source_id: Optional[int] = None
    comment: Optional[dict] = None
    branch_id: Optional[int] = None
    
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None
    
    aadhar_front_pic: Optional[str] = None
    aadhar_back_pic: Optional[str] = None
    pan_pic: Optional[str] = None
    kyc: Optional[bool] = False
    kyc_id: Optional[int] = None
    
    is_old_lead: Optional[bool] = False
    call_back_date: Optional[datetime] = None
    lead_status: Optional[str] = None
    created_at: datetime
    
    @validator('segment', pre=True)
    def parse_segment(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            try:
                import json
                return json.loads(v)
            except:
                return [v]  # If it's a single string, make it a list
        if isinstance(v, list):
            return v
        return None
    
    @validator('comment', pre=True)
    def parse_comment(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            try:
                import json
                return json.loads(v)
            except:
                return {"note": v}  # If it's a string, wrap in dict
        if isinstance(v, dict):
            return v
        return None
    
    class Config:
        from_attributes = True


class LeadStoryCreate(BaseModel):
    title: Optional[str] = None
    msg: str
    lead_response_id: Optional[int] = None


class LeadStoryOut(BaseModel):
    id: int
    title: Optional[str] = None
    msg: str
    timestamp: datetime
    user_id: str
    lead_response_id: Optional[int] = None
    
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


def safe_convert_lead_to_dict(lead) -> dict:
    """Safely convert Lead model to dictionary, handling potential type mismatches"""
    try:
        lead_dict = {}
        
        # Get all attributes from the lead object
        for column in lead.__table__.columns:
            value = getattr(lead, column.name, None)
            lead_dict[column.name] = value
        
        return lead_dict
    except Exception as e:
        # If there's an error, return basic info
        return {
            "id": getattr(lead, 'id', None),
            "full_name": getattr(lead, 'full_name', None),
            "email": getattr(lead, 'email', None),
            "mobile": getattr(lead, 'mobile', None),
            "created_at": getattr(lead, 'created_at', datetime.now()),
            "lead_status": getattr(lead, 'lead_status', None),
            "kyc": getattr(lead, 'kyc', False),
        }


# API Endpoints

@router.post("/", response_model=LeadOut, status_code=status.HTTP_201_CREATED)
def create_lead(
    lead_in: LeadCreate,
    db: Session = Depends(get_db),
):
    """Create a new lead - all fields are optional"""
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
        if lead_in.lead_response_id:
            lead_response = db.query(LeadResponse).filter_by(id=lead_in.lead_response_id).first()
            if not lead_response:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Lead response with ID {lead_in.lead_response_id} not found"
                )
        
        # Validate branch if provided
        if lead_in.branch_id:
            branch = db.query(BranchDetails).filter_by(id=lead_in.branch_id).first()
            if not branch:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Branch with ID {lead_in.branch_id} not found"
                )
        
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
        
        # Create lead
        lead_data = lead_in.dict(exclude_none=True)
        
        # Handle segment field - convert to JSON string if it's a list
        if 'segment' in lead_data and isinstance(lead_data['segment'], list):
            import json
            lead_data['segment'] = json.dumps(lead_data['segment'])
        
        # Handle comment field - convert to JSON string if it's a dict
        if 'comment' in lead_data and isinstance(lead_data['comment'], dict):
            import json
            lead_data['comment'] = json.dumps(lead_data['comment'])
        
        lead = Lead(**lead_data)
        
        db.add(lead)
        db.commit()
        db.refresh(lead)
        
        return lead
        
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
        
        leads = query.order_by(Lead.created_at.desc()).offset(skip).limit(limit).all()
        
        # Convert to list of dictionaries and let Pydantic handle validation
        result = []
        for lead in leads:
            try:
                lead_dict = safe_convert_lead_to_dict(lead)
                result.append(LeadOut(**lead_dict))
            except Exception as e:
                # Log the error but continue with other leads
                print(f"Error converting lead {lead.id}: {str(e)}")
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
        
        # Convert to dict and let Pydantic handle validation
        lead_dict = safe_convert_lead_to_dict(lead)
        return LeadOut(**lead_dict)
        
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
            detail=f"Error fetching lead: {str(e)}"
        )


# Continue with the rest of your endpoints...
# (I'll include the remaining endpoints in the same pattern)

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
        
        # Update only provided fields
        update_data = lead_in.dict(exclude_unset=True)
        
        # Handle segment field
        if 'segment' in update_data and isinstance(update_data['segment'], list):
            import json
            update_data['segment'] = json.dumps(update_data['segment'])
        
        # Handle comment field
        if 'comment' in update_data and isinstance(update_data['comment'], dict):
            import json
            update_data['comment'] = json.dumps(update_data['comment'])
        
        # Validate references if being updated
        if "lead_source_id" in update_data:
            lead_source = db.query(LeadSource).filter_by(id=update_data["lead_source_id"]).first()
            if not lead_source:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Lead source with ID {update_data['lead_source_id']} not found"
                )
        
        if "lead_response_id" in update_data:
            lead_response = db.query(LeadResponse).filter_by(id=update_data["lead_response_id"]).first()
            if not lead_response:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Lead response with ID {update_data['lead_response_id']} not found"
                )
        
        # Check for duplicate email or mobile if being updated
        if "email" in update_data or "mobile" in update_data:
            query = db.query(Lead).filter(Lead.id != lead_id)
            conditions = []
            
            if "email" in update_data and update_data["email"]:
                conditions.append(Lead.email == update_data["email"])
            if "mobile" in update_data and update_data["mobile"]:
                conditions.append(Lead.mobile == update_data["mobile"])
            
            if conditions:
                from sqlalchemy import or_
                existing = query.filter(or_(*conditions)).first()
                if existing:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Another lead with this email or mobile already exists"
                    )
        
        # Apply updates
        for field, value in update_data.items():
            setattr(lead, field, value)
        
        db.commit()
        db.refresh(lead)
        
        # Convert to dict and let Pydantic handle validation
        lead_dict = safe_convert_lead_to_dict(lead)
        return LeadOut(**lead_dict)
        
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
            detail=f"Error updating lead: {str(e)}"
        )


# Add the remaining endpoints following the same pattern...
# (Including create_lead_with_files, upload_lead_documents, etc.)

@router.post("/form", response_model=LeadOut, status_code=status.HTTP_201_CREATED)
async def create_lead_with_files(
    # Basic Info (all optional)
    full_name: Optional[str] = Form(None),
    email: Optional[EmailStr] = Form(None),
    mobile: Optional[str] = Form(None),
    father_name: Optional[str] = Form(None),
    alternate_mobile: Optional[str] = Form(None),
    
    # Documents
    aadhaar: Optional[str] = Form(None),
    pan: Optional[str] = Form(None),
    gstin: Optional[str] = Form(None),
    
    # Location
    state: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    district: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    
    # Additional Info
    dob: Optional[date] = Form(None),
    occupation: Optional[str] = Form(None),
    experience: Optional[str] = Form(None),
    investment: Optional[str] = Form(None),
    
    # Lead Details
    lead_response_id: Optional[int] = Form(None),
    lead_source_id: Optional[int] = Form(None),
    branch_id: Optional[int] = Form(None),
    created_by: Optional[str] = Form(None),
    created_by_name: Optional[str] = Form(None),
    
    # File Uploads
    aadhar_front_pic: Optional[UploadFile] = File(None),
    aadhar_back_pic: Optional[UploadFile] = File(None),
    pan_pic: Optional[UploadFile] = File(None),
    
    db: Session = Depends(get_db),
):
    """Create lead with file uploads - all fields optional"""
    try:
        # Validate lead source if provided
        if lead_source_id:
            lead_source = db.query(LeadSource).filter_by(id=lead_source_id).first()
            if not lead_source:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Lead source with ID {lead_source_id} not found"
                )
        
        # Validate lead response if provided
        if lead_response_id:
            lead_response = db.query(LeadResponse).filter_by(id=lead_response_id).first()
            if not lead_response:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Lead response with ID {lead_response_id} not found"
                )
        
        # Check for duplicates if email or mobile provided
        if email or mobile:
            query = db.query(Lead)
            conditions = []
            
            if email:
                conditions.append(Lead.email == email)
            if mobile:
                conditions.append(Lead.mobile == mobile)
            
            if conditions:
                from sqlalchemy import or_
                existing_lead = query.filter(or_(*conditions)).first()
                if existing_lead:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Lead with this email or mobile already exists"
                    )
        
        # Create lead with only non-None values
        lead_data = {}
        for field, value in {
            'full_name': full_name,
            'father_name': father_name,
            'email': email,
            'mobile': mobile,
            'alternate_mobile': alternate_mobile,
            'aadhaar': aadhaar,
            'pan': pan,
            'gstin': gstin,
            'state': state,
            'city': city,
            'district': district,
            'address': address,
            'dob': dob,
            'occupation': occupation,
            'experience': experience,
            'investment': investment,
            'lead_response_id': lead_response_id,
            'lead_source_id': lead_source_id,
            'branch_id': branch_id,
            'created_by': created_by,
            'created_by_name': created_by_name,
        }.items():
            if value is not None:
                lead_data[field] = value
        
        lead = Lead(**lead_data)
        
        db.add(lead)
        db.commit()
        db.refresh(lead)
        
        # Save uploaded files if provided
        if aadhar_front_pic:
            lead.aadhar_front_pic = save_uploaded_file(aadhar_front_pic, lead.id, "aadhar_front")
        
        if aadhar_back_pic:
            lead.aadhar_back_pic = save_uploaded_file(aadhar_back_pic, lead.id, "aadhar_back")
        
        if pan_pic:
            lead.pan_pic = save_uploaded_file(pan_pic, lead.id, "pan")
        
        # Update KYC status if all documents uploaded
        if aadhar_front_pic and aadhar_back_pic and pan_pic:
            lead.kyc = True
        
        db.commit()
        db.refresh(lead)
        
        # Convert to dict and let Pydantic handle validation
        lead_dict = safe_convert_lead_to_dict(lead)
        return LeadOut(**lead_dict)
        
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
            detail=f"Error creating lead: {str(e)}"
        )


# Add remaining endpoints...
# (Include all other endpoints from your original file with similar fixes)

@router.patch("/{lead_id}/documents")
async def upload_lead_documents(
    lead_id: int,
    aadhar_front_pic: Optional[UploadFile] = File(None),
    aadhar_back_pic: Optional[UploadFile] = File(None),
    pan_pic: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    """Upload documents for a lead"""
    try:
        lead = db.query(Lead).filter_by(id=lead_id).first()
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
        
        uploaded_files = {}
        
        # Upload files
        if aadhar_front_pic:
            # Delete old file if exists
            if lead.aadhar_front_pic and os.path.exists(lead.aadhar_front_pic.lstrip('/')):
                os.remove(lead.aadhar_front_pic.lstrip('/'))
            
            lead.aadhar_front_pic = save_uploaded_file(aadhar_front_pic, lead_id, "aadhar_front")
            uploaded_files["aadhar_front_pic"] = lead.aadhar_front_pic
        
        if aadhar_back_pic:
            if lead.aadhar_back_pic and os.path.exists(lead.aadhar_back_pic.lstrip('/')):
                os.remove(lead.aadhar_back_pic.lstrip('/'))
            
            lead.aadhar_back_pic = save_uploaded_file(aadhar_back_pic, lead_id, "aadhar_back")
            uploaded_files["aadhar_back_pic"] = lead.aadhar_back_pic
        
        if pan_pic:
            if lead.pan_pic and os.path.exists(lead.pan_pic.lstrip('/')):
                os.remove(lead.pan_pic.lstrip('/'))
            
            lead.pan_pic = save_uploaded_file(pan_pic, lead_id, "pan")
            uploaded_files["pan_pic"] = lead.pan_pic
        
        # Update KYC status
        if lead.aadhar_front_pic and lead.aadhar_back_pic and lead.pan_pic:
            lead.kyc = True
        
        db.commit()
        
        return {
            "message": "Documents uploaded successfully",
            "lead_id": lead_id,
            "uploaded_files": uploaded_files,
            "kyc_status": lead.kyc
        }
        
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
            detail=f"Error uploading documents: {str(e)}"
        )


@router.post("/{lead_id}/stories", response_model=LeadStoryOut)
def add_lead_story(
    lead_id: int,
    story_in: LeadStoryCreate,
    user_id: str,  # This should come from JWT token in real implementation
    db: Session = Depends(get_db),
):
    """Add a story/comment to a lead"""
    try:
        # Check if lead exists
        lead = db.query(Lead).filter_by(id=lead_id).first()
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
        
        # Create story
        story = LeadStory(
            lead_id=lead_id,
            user_id=user_id,
            title=story_in.title,
            msg=story_in.msg,
            lead_response_id=story_in.lead_response_id,
        )
        
        db.add(story)
        db.commit()
        db.refresh(story)
        
        return story
        
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
            detail=f"Error adding story: {str(e)}"
        )


@router.get("/{lead_id}/stories", response_model=List[LeadStoryOut])
def get_lead_stories(
    lead_id: int,
    db: Session = Depends(get_db),
):
    """Get all stories for a lead"""
    try:
        # Check if lead exists
        lead = db.query(Lead).filter_by(id=lead_id).first()
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
        
        stories = db.query(LeadStory).filter_by(lead_id=lead_id).order_by(LeadStory.timestamp.desc()).all()
        return stories
        
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
            detail=f"Error fetching stories: {str(e)}"
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
            detail=f"Error deleting lead: {str(e)}"
        )


@router.post("/quick", response_model=LeadOut, status_code=status.HTTP_201_CREATED)
def create_quick_lead(
    name: Optional[str] = None,
    email: Optional[str] = None,
    mobile: Optional[str] = None,
    source: Optional[str] = "website",  # Default source
    db: Session = Depends(get_db),
):
    """Create a quick lead with minimal information"""
    try:
        # Create lead with minimal data
        lead_data = {}
        
        if name:
            lead_data['full_name'] = name
        if email:
            lead_data['email'] = email
        if mobile:
            lead_data['mobile'] = mobile
        
        # Find default lead source or create one
        if source:
            lead_source = db.query(LeadSource).filter_by(name=source).first()
            if lead_source:
                lead_data['lead_source_id'] = lead_source.id
        
        # Check for duplicates if email or mobile provided
        if email or mobile:
            query = db.query(Lead)
            conditions = []
            
            if email:
                conditions.append(Lead.email == email)
            if mobile:
                conditions.append(Lead.mobile == mobile)
            
            if conditions:
                from sqlalchemy import or_
                existing_lead = query.filter(or_(*conditions)).first()
                if existing_lead:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Lead with this email or mobile already exists"
                    )
        
        lead = Lead(**lead_data)
        
        db.add(lead)
        db.commit()
        db.refresh(lead)
        
        # Convert to dict and let Pydantic handle validation
        lead_dict = safe_convert_lead_to_dict(lead)
        return LeadOut(**lead_dict)
        
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
            detail=f"Error creating quick lead: {str(e)}"
        )


# Helper endpoints for dropdowns

@router.get("/sources/", response_model=List[dict])
def get_lead_sources(db: Session = Depends(get_db)):
    """Get all lead sources"""
    try:
        sources = db.query(LeadSource).all()
        return [{"id": s.id, "name": s.name, "description": s.description} for s in sources]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching lead sources: {str(e)}"
        )


@router.get("/responses/", response_model=List[dict])
def get_lead_responses(db: Session = Depends(get_db)):
    """Get all lead responses"""
    try:
        responses = db.query(LeadResponse).all()
        return [{"id": r.id, "name": r.name, "lead_limit": r.lead_limit} for r in responses]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching lead responses: {str(e)}"
        )


# Debug endpoint to help identify the issue
@router.get("/debug/{lead_id}")
def debug_lead(lead_id: int, db: Session = Depends(get_db)):
    """Debug endpoint to see raw lead data"""
    try:
        lead = db.query(Lead).filter_by(id=lead_id).first()
        if not lead:
            return {"error": "Lead not found"}
        
        # Return raw data as dict
        raw_data = {}
        for column in lead.__table__.columns:
            value = getattr(lead, column.name, None)
            raw_data[column.name] = {
                "value": str(value) if value is not None else None,
                "type": str(type(value)),
                "column_type": str(column.type)
            }
        
        return {
            "lead_id": lead_id,
            "raw_data": raw_data,
            "model_dict": safe_convert_lead_to_dict(lead)
        }
        
    except Exception as e:
        return {"error": f"Debug error: {str(e)}"}


# Debug endpoint for all leads
@router.get("/debug/")
def debug_all_leads(db: Session = Depends(get_db)):
    """Debug endpoint to see what's causing the validation error"""
    try:
        leads = db.query(Lead).limit(5).all()
        
        debug_info = []
        for lead in leads:
            try:
                # Try to convert to LeadOut
                lead_dict = safe_convert_lead_to_dict(lead)
                lead_out = LeadOut(**lead_dict)
                debug_info.append({
                    "lead_id": lead.id,
                    "status": "success",
                    "data": lead_dict
                })
            except Exception as e:
                debug_info.append({
                    "lead_id": lead.id,
                    "status": "error",
                    "error": str(e),
                    "raw_data": safe_convert_lead_to_dict(lead)
                })
        
        return {"debug_info": debug_info}
        
    except Exception as e:
        return {"error": f"Debug error: {str(e)}"}
    

# Additional helper endpoint to check database schema
@router.get("/schema/")
def get_lead_schema(db: Session = Depends(get_db)):
    """Get the actual database schema for Lead table"""
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.bind)
        columns = inspector.get_columns('leads')  # Assuming table name is 'leads'
        
        schema_info = {}
        for column in columns:
            schema_info[column['name']] = {
                'type': str(column['type']),
                'nullable': column['nullable'],
                'default': column.get('default'),
                'autoincrement': column.get('autoincrement', False)
            }
        
        return {"schema": schema_info}
        
    except Exception as e:
        return {"error": f"Schema error: {str(e)}"}
    

# Test endpoint to verify fix
@router.get("/test/")
def test_response_model():
    """Test endpoint to verify the response model works"""
    from datetime import datetime
    
    sample_data = {
        "id": 1,
        "full_name": "Test User",
        "email": "test@example.com",
        "mobile": "1234567890",
        "created_at": datetime.now(),
        "kyc": False,
        "segment": ["segment1", "segment2"],
        "comment": {"note": "test comment"}
    }
    
    try:
        lead_out = LeadOut(**sample_data)
        return {"status": "success", "data": lead_out}
    except Exception as e:
        return {"status": "error", "error": str(e)}