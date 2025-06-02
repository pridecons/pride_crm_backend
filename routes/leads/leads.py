import os
import uuid
import json
from typing import Optional, List, Any, Dict, Union, Literal, Tuple
from datetime import datetime, date, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DisconnectionError
from pydantic import BaseModel, constr, validator
from sqlalchemy import and_, or_, select, literal  # <— add and_, select, literal
from sqlalchemy.sql import exists  # optional if you prefer sqlalchemy.exists()
from db.connection import get_db
from db.models import (
    Lead, LeadSource, LeadResponse, BranchDetails, 
    UserDetails, Payment, LeadComment, LeadStory, LeadAssignment, LeadFetchConfig, ClientConsent
)
from utils.AddLeadStory import AddLeadStory
from routes.auth.auth_dependency import get_current_user
from routes.notification.notification_scheduler import schedule_callback
from routes.leads.leads_fetch import load_fetch_config
from utils.validation_utils import validate_lead_data, UniquenessValidator, FormatValidator
from utils.user_tree import get_subordinate_users, get_subordinate_ids  # <— add this import
from services.mail_with_file import send_mail_by_client_with_file
from zoneinfo import ZoneInfo

from datetime import datetime, timezone, timedelta
import json
import re
import logging

IST = timezone(timedelta(hours=5, minutes=30))

def parse_utc_flex(ts) -> datetime:
    """
    Accepts a datetime or string in common UTC forms:
    - '2025-09-02 17:17:42.204086+00'
    - '2025-09-02 17:17:42.204086+00:00'
    - '2025-09-02 17:17:42.204086Z'
    - naive -> assume UTC
    Returns an aware UTC datetime.
    """
    if ts is None:
        raise ValueError("Timestamp is None")

    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)

    s = str(ts).strip()

    # Normalize timezone suffixes
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # match +HH or -HH at end and make it +HH:MM
    if re.search(r"([+-]\d{2})$", s):
        s = s + ":00"
    # specifically fix trailing +00
    if s.endswith("+00"):
        s = s[:-3] + "+00:00"

    try:
        return datetime.fromisoformat(s)
    except Exception as e:
        raise ValueError(f"Unsupported timestamp format: {ts!r}") from e

def to_ist_ampm_from_utc(utc_value) -> str:
    dt_utc = parse_utc_flex(utc_value)
    dt_ist = dt_utc.astimezone(IST)
    return dt_ist.strftime("%d-%m-%Y %I:%M:%S %p")


router = APIRouter(
    prefix="/leads",
    tags=["leads"],
)


UPLOAD_DIR = "static/lead_documents"

# ----------------- NEW: Filters + Response wrappers -----------------
class FiltersMeta(BaseModel):
    view: Literal["self", "other", "all"]
    available_views: List[str]
    available_team_members: List[Dict[str, str]] = []
    selected_team_member: Optional[str] = None

class LeadsListResponse(BaseModel):
    leads: List["LeadOut"]
    filters: Optional[FiltersMeta] = None

# ----------------- Models (unchanged from your code) -----------------
class LeadBase(BaseModel):
    # ... (same as your current LeadBase)
    full_name: Optional[str] = None
    director_name: Optional[str] = None
    father_name: Optional[str] = None
    gender: Optional[str] = None
    marital_status: Optional[str] = None
    email: Optional[str] = None
    mobile: Optional[str] = None
    alternate_mobile: Optional[str] = None
    aadhaar: Optional[str] = None
    pan: Optional[str] = None
    gstin: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = None
    dob: Optional[date] = None
    occupation: Optional[str] = None
    segment: Optional[List[str]] = None
    experience: Optional[str] = None
    investment: Optional[str] = None
    ft_service_type: Optional[str] = None
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
    # ... (same as your current LeadUpdate)
    full_name: Optional[str] = None
    director_name: Optional[str] = None
    father_name: Optional[str] = None
    gender: Optional[str] = None
    marital_status: Optional[str] = None
    email: Optional[str] = None
    mobile: Optional[str] = None
    alternate_mobile: Optional[str] = None
    aadhaar: Optional[str] = None
    pan: Optional[str] = None
    gstin: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = None
    dob: Optional[date] = None
    occupation: Optional[str] = None
    segment: Optional[List[str]] = None
    experience: Optional[str] = None
    investment: Optional[str] = None
    ft_service_type: Optional[str] = None
    lead_response_id: Optional[int] = None
    lead_source_id: Optional[int] = None
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
    # ... (same as your current LeadOut)
    id: int
    full_name: Optional[str] = None
    director_name: Optional[str] = None
    father_name: Optional[str] = None
    gender: Optional[str] = None
    marital_status: Optional[str] = None
    email: Optional[str] = None
    mobile: Optional[str] = None
    alternate_mobile: Optional[str] = None
    aadhaar: Optional[str] = None
    pan: Optional[str] = None
    gstin: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = None
    dob: Optional[date] = None
    occupation: Optional[str] = None
    segment: Optional[List[str]] = None
    experience: Optional[str] = None
    investment: Optional[str] = None
    ft_service_type: Optional[str] = None
    lead_response_id: Optional[int] = None
    lead_source_id: Optional[int] = None
    branch_id: Optional[int] = None
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None
    aadhar_front_pic: Optional[str] = None
    aadhar_back_pic: Optional[str] = None
    pan_pic: Optional[str] = None
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
    created_at: datetime

    @validator('segment', pre=True, always=True)
    def parse_segment(cls, v):
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

# ----------------- Helpers (unchanged + new visibility helpers) -----------------
def save_uploaded_file(file: UploadFile, lead_id: int, file_type: str) -> str:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_extension = file.filename.split('.')[-1] if '.' in file.filename else 'jpg'
    filename = f"lead_{lead_id}_{file_type}_{uuid.uuid4().hex}.{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    with open(file_path, "wb") as buffer:
        content = file.file.read()
        buffer.write(content)
    return f"/{UPLOAD_DIR}/{filename}"

def prepare_lead_data_for_db(data: dict) -> dict:
    if 'segment' in data and isinstance(data['segment'], list):
        data['segment'] = json.dumps(data['segment'])
    if 'pan' in data and data['pan']:
        data['pan'] = data['pan'].upper()
    return data

def safe_convert_lead_to_dict(lead) -> dict:
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
    except Exception:
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
            "ft_service_type": getattr(lead, 'ft_service_type', None),
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

def _branch_id_for_manager(u: UserDetails) -> Optional[int]:
    if getattr(u, "manages_branch", None):
        return u.manages_branch.id
    return u.branch_id

def _exists_assignment_for_users(allowed_codes: List[str]):
    """
    Correlated EXISTS(LeadAssignment...) for allowed user codes.
    """
    if not allowed_codes:
        # produce FALSE condition if empty
        return literal(False)
    return (
        select(literal(1))
        .select_from(LeadAssignment)
        .where(
            and_(
                LeadAssignment.lead_id == Lead.id,
                LeadAssignment.user_id.in_(allowed_codes),
            )
        )
        .correlate(Lead)
        .exists()
    )

def apply_visibility_to_leads_list(
    db: Session,
    current_user: UserDetails,
    base_q,
    *,
    view: Literal["self", "other", "all"] = "all",
    team_member: Optional[str] = None,
) -> Tuple[Any, Optional[FiltersMeta]]:
    """
    Apply role-based visibility on Lead list:
    - SUPERADMIN: no restriction
    - BRANCH_MANAGER: branch filter
    - Others: self/other/all by assignment (Lead.assigned_to_user OR LeadAssignment)
    Returns (scoped_query, filters_meta|None)
    """
    role = (getattr(current_user, "role_name", "") or "").upper()

    # SUPERADMIN
    if role == "SUPERADMIN":
        return base_q, None

    # BRANCH_MANAGER
    if role == "BRANCH_MANAGER":
        b_id = _branch_id_for_manager(current_user)
        if not b_id:
            return base_q.filter(Lead.id == -1), None
        return base_q.filter(Lead.branch_id == b_id), None

    # OTHER EMPLOYEES
    subs: List[str] = get_subordinate_ids(db, current_user.employee_code)

    if view == "self":
        allowed = [current_user.employee_code]
    elif view == "other":
        # If team_member specified and is under this user, restrict to that
        if team_member and team_member in subs:
            allowed = [team_member]
        else:
            allowed = subs
    else:  # "all"
        allowed = [current_user.employee_code] + subs

    # Assigned via column OR via LeadAssignment mapping
    assignment_exists = _exists_assignment_for_users(allowed)

    scoped = base_q.filter(
        or_(
            Lead.assigned_to_user.in_(allowed),
            assignment_exists
        )
    )

    # Build filters meta for UI (list of direct subordinates)
    subs_users = get_subordinate_users(db, current_user.employee_code)
    filters_meta = FiltersMeta(
        view=view,
        available_views=["self", "other", "all"],
        available_team_members=[
            {"employee_code": u.employee_code, "name": u.name, "role_id": str(u.role_id)}
            for u in subs_users
        ],
        selected_team_member=team_member if view == "other" else None,
    )
    return scoped, filters_meta

# ----------------- API Endpoint (UPDATED) -----------------
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
                existing_lead = query.filter(or_(*conditions)).first()
                if existing_lead:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Lead with this email or mobile already exists"
                    )
        
        # Prepare data for database
        lead_data = prepare_lead_data_for_db(lead_in.dict(exclude_none=True))
        validate_lead_data(db, lead_data)
        if is_old:
           lead_data["is_old_lead"] = True
        if current_user.branch_id:
            lead_data["branch_id"] = current_user.branch_id
        
        # Create lead
        lead = Lead(**lead_data)
        
        db.add(lead)
        db.commit()
        db.refresh(lead)
                
        # If lead has response (is_old = True), also set additional old lead fields
        if is_old:
            # Get user's config for timeout calculation
            
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

@router.get("/", response_model=LeadsListResponse)  # <— changed response model
def get_all_leads(
    # Pagination
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, gt=0, description="Max number of records to return"),

    # Existing filters
    branch_id:      Optional[int]  = Query(None),
    lead_status:    Optional[str]  = Query(None, description="old, new, client"),
    lead_source_id: Optional[int]  = Query(None),
    created_by:     Optional[str]  = Query(None),
    kyc_only:       bool           = Query(False, description="Only leads with kyc=True"),
    gender:         Optional[str]  = Query(None),
    city:           Optional[str]  = Query(None),
    state:          Optional[str]  = Query(None),

    # New/extra filters
    from_date:           Optional[date]          = Query(None, description="created_at ≥ this date (YYYY-MM-DD)"),
    to_date:             Optional[date]          = Query(None, description="created_at ≤ this date (YYYY-MM-DD)"),
    search:              Optional[str]           = Query(None, description="global search on name/email/mobile"),
    response_id:         Optional[int]           = Query(None, description="Filter by lead_response_id"),
    assigned_to_user:    Optional[str]           = Query(None, description="Filter by assigned_to_user"),
    assigned_roles:      Optional[List[str]]     = Query(None, description="Filter by role_id of assigned_to_user; e.g. ['3','4']"),

    # Visibility controls for non-admin employees
    view: Literal["self", "other", "all"] = Query("all", description="For employees: restrict to self/other/all"),
    team_member: Optional[str] = Query(None, description="When view='other', choose a specific subordinate"),

    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all leads with extended filtering options + role-based visibility."""
    try:
        base_q = db.query(Lead).filter(Lead.is_delete.is_(False))

        # ----- Role-based visibility -----
        scoped_q, filters_meta = apply_visibility_to_leads_list(
            db=db,
            current_user=current_user,
            base_q=base_q,
            view=view,
            team_member=team_member,
        )

        # ----- Core filters -----
        if branch_id:
            scoped_q = scoped_q.filter(Lead.branch_id == branch_id)

        if lead_status == "client":
            scoped_q = scoped_q.filter(Lead.is_client.is_(True))
        elif lead_status == "old":
            scoped_q = scoped_q.filter(Lead.is_old_lead.is_(True), Lead.is_client.is_(False))
        elif lead_status == "new":
            scoped_q = scoped_q.filter(Lead.is_old_lead.is_(False), Lead.is_client.is_(False))

        if lead_source_id:
            scoped_q = scoped_q.filter(Lead.lead_source_id == lead_source_id)
        if created_by:
            scoped_q = scoped_q.filter(Lead.created_by == created_by)
        if kyc_only:
            scoped_q = scoped_q.filter(Lead.kyc.is_(True))
        if gender:
            scoped_q = scoped_q.filter(Lead.gender == gender)
        if city:
            scoped_q = scoped_q.filter(Lead.city.ilike(f"%{city}%"))
        if state:
            scoped_q = scoped_q.filter(Lead.state.ilike(f"%{state}%"))

        # Date range
        if from_date:
            scoped_q = scoped_q.filter(Lead.created_at.cast(date) >= from_date)
        if to_date:
            scoped_q = scoped_q.filter(Lead.created_at.cast(date) <= to_date)

        # Global search
        if search:
            term = f"%{search.strip()}%"
            scoped_q = scoped_q.filter(
                or_(
                    Lead.full_name.ilike(term),
                    Lead.email.ilike(term),
                    Lead.mobile.ilike(term),
                )
            )

        # Response-wise
        if response_id is not None:
            scoped_q = scoped_q.filter(Lead.lead_response_id == response_id)

        # Assigned-to specific
        if assigned_to_user:
            scoped_q = scoped_q.filter(Lead.assigned_to_user == assigned_to_user)

        # Role filter of assignee (join to UserDetails)
        if assigned_roles:
            scoped_q = scoped_q.join(
                UserDetails, Lead.assigned_to_user == UserDetails.employee_code
            ).filter(UserDetails.role_id.in_(assigned_roles))

        # ----- Ordering + Pagination -----
        leads = (
            scoped_q
            .order_by(Lead.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

        # Pydantic conversion
        result_leads: List[LeadOut] = []
        for lead in leads:
            lead_dict = safe_convert_lead_to_dict(lead)
            result_leads.append(LeadOut(**lead_dict))

        return LeadsListResponse(leads=result_leads, filters=filters_meta)

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
        if update_data['lead_source_id']:
            lead_source = db.query(LeadSource).filter_by(id=update_data["lead_source_id"]).first()
            if not lead_source:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Lead source with ID {update_data['lead_source_id']} not found"
                )
        is_old = False
        if update_data['lead_response_id']:
            lead_response = db.query(LeadResponse).filter_by(id=update_data["lead_response_id"]).first()
            is_old = True
            if not lead_response:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Lead response with ID {update_data['lead_response_id']} not found"
                )
        
        validate_lead_data(db, update_data, exclude_lead_id=lead_id)
        
        # Check for duplicates if updating email or mobile
        if "email" in update_data and update_data["email"]:

            client_consent = (
                db.query(ClientConsent)
                .filter(
                    ClientConsent.lead_id == lead_id,
                    ClientConsent.mail_sent.is_(False)
                )
                .first()
            )

            if client_consent:
                try:
                    formatted = to_ist_ampm_from_utc(client_consent.consented_at_utc)
                except Exception as e:
                    logging.exception("Failed to convert consent time to IST")
                    formatted = "N/A"
                # call your mailer with the correct signature
                send_mail_by_client_with_file(
                    to_email=update_data["email"],
                    subject="Pre Payment Consent",
                    # html_content=client_consent.consent_text,
                     html_content=f"""
                        <h2>Pre Payment Consent Confirmation</h2>
                        <p>{client_consent.consent_text}</p>

                        <h3>Consent Details</h3>
                        <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">
                        <tr><td><b>Channel</b></td><td>{client_consent.channel}</td></tr>
                        <tr><td><b>Purpose</b></td><td>{client_consent.purpose}</td></tr>
                        <tr><td><b>IP Address</b></td><td>{client_consent.ip_address}</td></tr>
                        <tr><td><b>User Agent</b></td><td>{client_consent.user_agent}</td></tr>
                        <tr><td><b>Device Info</b></td><td><pre>{client_consent.device_info or {} }</pre></td></tr>
                        <tr><td><b>Timezone Offset (minutes)</b></td><td>{client_consent.tz_offset_minutes}</td></tr>
                        <tr><td><b>Consented At (UTC)</b></td><td>{client_consent.consented_at_utc}</td></tr>
                        <tr><td><b>Consented At (IST)</b></td><td>{formatted}</td></tr>
                        <tr><td><b>Reference ID</b></td><td>{client_consent.ref_id}</td></tr>
                        </table>
                        """,
                    show_pdf=False
                )

                # ORM attribute assignment (not dict-style)
                client_consent.email = update_data["email"]
                client_consent.mail_sent = True
                # if you have timestamps:
                # client_consent.updated_at = datetime.utcnow()

                db.add(client_consent)  # optional but fine
                db.commit()
                db.refresh(client_consent)


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

from routes.notification.notification_service import notification_service

class ChangeResponse(BaseModel):
    lead_response_id: int
    ft_to_date: Optional[str] = None
    ft_from_date: Optional[str] = None
    call_back_date: Optional[datetime] = None
    segment: Optional[str] = None
    ft_service_type: Optional[str] = None

from datetime import datetime, timedelta, timezone

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
        

    # 3) Response change + retention logic
    timeout_days = None
    now = datetime.now(timezone.utc)
    if old_response_id != payload.lead_response_id:
        lead.lead_response_id = payload.lead_response_id
        lead.is_old_lead = True  # mark as old lead
        lead.response_changed_at = now
        lead.assigned_for_conversion = True
        lead.assigned_to_user = current_user.employee_code

        # Get timeout from config
        config, _ = load_fetch_config(db, current_user)
        timeout_days = getattr(config, "old_lead_remove_days", None) or 30
        lead.conversion_deadline = now + timedelta(days=timeout_days)

        # Ensure lead stays with current user
        assignment = db.query(LeadAssignment).filter_by(lead_id=lead_id).first()
        if assignment:
            assignment.user_id = current_user.employee_code
            assignment.fetched_at = now
        else:
            new_assignment = LeadAssignment(
                lead_id=lead_id,
                user_id=current_user.employee_code,
                fetched_at=now
            )
            db.add(new_assignment)

    # 4) Handle call_back_date with timezone normalization
    if payload.call_back_date:
        try:
            if isinstance(payload.call_back_date, str):
                # Accept ISO with Z or offset
                iso_str = payload.call_back_date
                if iso_str.endswith("Z"):
                    cb_dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
                else:
                    cb_dt = datetime.fromisoformat(iso_str)
            elif isinstance(payload.call_back_date, datetime):
                cb_dt = payload.call_back_date
            else:
                raise ValueError("Unsupported type for call_back_date")

            # Normalize to aware UTC
            if cb_dt.tzinfo is None:
                cb_dt = cb_dt.replace(tzinfo=timezone.utc)
            else:
                cb_dt = cb_dt.astimezone(timezone.utc)

            # Immediate vs scheduled
            if cb_dt <= now:
                await notification_service.notify(
                    user_id=current_user.employee_code,
                    title="Call Back Reminder (Immediate)",
                    message=(
                        f"Lead {lead.mobile} का call back समय पहले का है "
                        f"({cb_dt.isoformat()}); तुरंत संपर्क करें।"
                    )
                )
            else:
                schedule_callback(
                    user_id=current_user.employee_code,
                    lead_id=lead_id,
                    callback_dt=cb_dt,
                    mobile=lead.mobile,
                )
            lead.call_back_date = cb_dt
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid call_back_date: {e}")

    # 5) Update ft dates if provided
    if payload.ft_to_date:
        lead.ft_to_date = payload.ft_to_date
    if payload.ft_from_date:
        lead.ft_from_date = payload.ft_from_date
    if payload.segment:
        lead.segment = payload.segment
    if payload.ft_service_type:
        lead.ft_service_type = payload.ft_service_type

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

