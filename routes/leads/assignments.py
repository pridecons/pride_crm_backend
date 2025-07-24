# routes/leads/assignments.py - Fixed version with proper route ordering

from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, validator
from sqlalchemy import and_
from sqlalchemy.orm import Session

from db.connection import get_db
from db.models import Lead, LeadAssignment, UserDetails
from routes.auth.auth_dependency import require_permission
from routes.leads.leads_fetch import load_fetch_config
from utils.AddLeadStory import AddLeadStory
import json
from datetime import datetime, date

# Create a separate router with a specific prefix to avoid conflicts
router = APIRouter(
    prefix="/leads/assignments",  # Changed to more specific prefix
    tags=["lead assignments"],
)

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


class AssignmentResponse(BaseModel):
    assignment_id: int
    lead_id: int
    lead : LeadOut
    fetched_at: datetime
    expires_at: datetime
    hours_remaining: float

class MyAssignmentsResponse(BaseModel):
    assignments: List[AssignmentResponse]
    total_count: int
    assignment_ttl_hours: int
    can_fetch_new: bool
    last_fetch_limit: int


@router.get("/my", response_model=MyAssignmentsResponse)  # Changed from "/my-assignments" to "/my"
def get_my_assignments(
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(require_permission("fetch_lead")),
):
    """Get current user's active lead assignments"""
    try:
        config, _ = load_fetch_config(db, current_user)
        
        # Get non-expired assignments - use timezone-aware datetime
        now = datetime.now(timezone.utc)  # Changed from datetime.utcnow()
        expiry_cutoff = now - timedelta(hours=config.assignment_ttl_hours)
        
        assignments = db.query(LeadAssignment).join(Lead).filter(
            and_(
                LeadAssignment.user_id == current_user.employee_code,
                LeadAssignment.fetched_at >= expiry_cutoff
            )
        ).all()
        
        assignment_data = []
        for assignment in assignments:
            expires_at = assignment.fetched_at + timedelta(hours=config.assignment_ttl_hours)
            hours_remaining = (expires_at - now).total_seconds() / 3600

            # ─── Audit ───────────────────────────────────────
            AddLeadStory(
                assignment.lead_id,
                current_user.employee_code,
                f"{current_user.name} fetched assignment {assignment.id}"
            )
            # ────────────────────────────────────────────────
            
            assignment_data.append(AssignmentResponse(
                assignment_id=assignment.id,
                lead_id=assignment.lead_id,
                lead_name=assignment.lead.full_name,
                lead_mobile=assignment.lead.mobile,
                lead_email=assignment.lead.email,
                lead_city=assignment.lead.city,
                fetched_at=assignment.fetched_at,
                expires_at=expires_at,
                hours_remaining=max(0, hours_remaining)
            ))
        
        # Check if user can fetch new leads
        can_fetch_new = len(assignment_data) <= config.last_fetch_limit
        
        return MyAssignmentsResponse(
            assignments=assignment_data,
            total_count=len(assignment_data),
            assignment_ttl_hours=config.assignment_ttl_hours,
            can_fetch_new=can_fetch_new,
            last_fetch_limit=config.last_fetch_limit
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching assignments: {str(e)}"
        )


@router.delete("/{assignment_id}")  # Changed from "/assignment/{assignment_id}" to "/{assignment_id}"
def complete_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(require_permission("fetch_lead")),
):
    """Mark an assignment as completed (delete it) to free up space for new fetches"""
    try:
        assignment = db.query(LeadAssignment).filter(
            and_(
                LeadAssignment.id == assignment_id,
                LeadAssignment.user_id == current_user.employee_code
            )
        ).first()
        
        if not assignment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Assignment not found or not owned by you"
            )
        
        lead_id = assignment.lead_id
        
        db.delete(assignment)
        db.commit()

        # ─── Audit ─────────────────────────────────────
        AddLeadStory(
            lead_id,
            current_user.employee_code,
            f"{current_user.name} completed assignment {assignment_id}"
        )
        # ─────────────────────────────────────────────

        return {
            "message": "Assignment completed successfully",
            "assignment_id": assignment_id,
            "lead_id": lead_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error completing assignment: {str(e)}"
        )


@router.post("/complete-multiple")  # Changed from "/complete-multiple-assignments"
def complete_multiple_assignments(
    assignment_ids: List[int],
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(require_permission("fetch_lead")),
):
    """Mark multiple assignments as completed"""
    try:
        if not assignment_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Assignment IDs list cannot be empty"
            )
        
        assignments = db.query(LeadAssignment).filter(
            and_(
                LeadAssignment.id.in_(assignment_ids),
                LeadAssignment.user_id == current_user.employee_code
            )
        ).all()
        
        if len(assignments) != len(assignment_ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Some assignments not found or not owned by you"
            )
        
        completed_ids = []
        for assignment in assignments:
            completed_ids.append(assignment.id)
            lead_id = assignment.lead_id

            # ─── Audit ─────────────────────────────────────
            AddLeadStory(
                lead_id,
                current_user.employee_code,
                f"{current_user.name} completed assignment {assignment.id}"
            )
            # ─────────────────────────────────────────────

            db.delete(assignment)
        
        db.commit()
        
        return {
            "message": f"Successfully completed {len(completed_ids)} assignments",
            "completed_assignment_ids": completed_ids
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error completing assignments: {str(e)}"
        )
