# routes/leads/lead_navigation.py

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from db.connection import get_db
from db.models import Lead, LeadAssignment, UserDetails
from routes.auth.auth_dependency import get_current_user
from utils.AddLeadStory import AddLeadStory

router = APIRouter(
    prefix="/leads",
    tags=["lead navigation"],
)


class LeadNavigationResponse(BaseModel):
    id: int
    full_name: Optional[str] = None
    email: Optional[str] = None
    mobile: Optional[str] = None
    city: Optional[str] = None
    occupation: Optional[str] = None
    investment: Optional[str] = None
    created_at: datetime
    lead_source_id: Optional[int] = None
    lead_response_id: Optional[int] = None
    is_call: bool
    assignment_id: int
    position: int        # Current position in sequence
    total_count: int     # Total assigned leads
    has_next: bool
    has_previous: bool


class LeadPositionResponse(BaseModel):
    position: int
    total_count: int
    has_next: bool
    has_previous: bool

@router.put(
    "/navigation/mark-called/{assignment_id}",
    summary="Mark a lead as called"
)
async def mark_lead_called(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """
    Mark a lead as called (is_call = true)
    """
    assignment = db.query(LeadAssignment).filter(
        and_(
            LeadAssignment.id == assignment_id,
            LeadAssignment.user_id == current_user.employee_code
        )
    ).first()
    
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    
    assignment.is_call = True
    # Note: called_at field doesn't exist in the model, removed this line
    db.commit()

    # Audit
    AddLeadStory(
        assignment.lead_id,
        current_user.employee_code,
        f"{current_user.name} marked lead as called (assignment {assignment_id})"
    )

    return {"message": "Lead marked as called", "assignment_id": assignment_id}


@router.get("/navigation/uncalled-count")
async def get_uncalled_leads_count(
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user),
):
    """
    Returns how many assigned leads are still uncalled.
    """
    # Use timezone-aware datetime
    now = datetime.now(timezone.utc)  # Fixed timezone issue
    expiry_cutoff = now - timedelta(hours=24)
    
    uncalled_count = db.query(LeadAssignment).filter(
        and_(
            LeadAssignment.user_id == current_user.employee_code,
            LeadAssignment.fetched_at >= expiry_cutoff,
            LeadAssignment.is_call == False
        )
    ).count()
    
    total_count = db.query(LeadAssignment).filter(
        and_(
            LeadAssignment.user_id == current_user.employee_code,
            LeadAssignment.fetched_at >= expiry_cutoff
        )
    ).count()
    
    return {
        "uncalled_count": uncalled_count,
        "total_count": total_count,
        "called_count": total_count - uncalled_count
    }

