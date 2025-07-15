# routes/leads/lead_navigation.py

from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, asc

from db.connection import get_db
from db.models import Lead, LeadAssignment, UserDetails
from routes.auth.auth_dependency import get_current_user

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
    position: int  # Current position in sequence
    total_count: int  # Total assigned leads
    has_next: bool
    has_previous: bool

class LeadPositionResponse(BaseModel):
    position: int
    total_count: int
    has_next: bool
    has_previous: bool

@router.get("/navigation/current", response_model=LeadNavigationResponse)
async def get_current_lead(
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """
    Get current lead for user - returns first is_call=false lead
    If no is_call=false leads, return first lead
    """
    # Get user's active assignments (within TTL) - use timezone-aware datetime
    now = datetime.now(timezone.utc)  # Fixed timezone issue
    expiry_cutoff = now - timedelta(hours=24)  # 24 hour TTL
    
    # Get all user's assignments with leads - order by fetched_at instead of created_at
    assignments_query = db.query(LeadAssignment).filter(
        and_(
            LeadAssignment.user_id == current_user.employee_code,
            LeadAssignment.fetched_at >= expiry_cutoff
        )
    ).order_by(LeadAssignment.fetched_at)  # Changed from created_at to fetched_at
    
    assignments = assignments_query.all()
    
    if not assignments:
        raise HTTPException(status_code=404, detail="No leads assigned to user")
    
    # Try to find first is_call=false lead
    current_assignment = None
    for assignment in assignments:
        if not assignment.is_call:
            current_assignment = assignment
            break
    
    # If no is_call=false found, get first assignment
    if not current_assignment:
        current_assignment = assignments[0]
    
    # Get lead details
    lead = db.query(Lead).filter(Lead.id == current_assignment.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Calculate position and navigation info
    position = next((i + 1 for i, a in enumerate(assignments) if a.id == current_assignment.id), 1)
    total_count = len(assignments)
    
    return LeadNavigationResponse(
        id=lead.id,
        full_name=lead.full_name,
        email=lead.email,
        mobile=lead.mobile,
        city=lead.city,
        occupation=lead.occupation,
        investment=lead.investment,
        created_at=lead.created_at,
        lead_source_id=lead.lead_source_id,
        lead_response_id=lead.lead_response_id,
        is_call=current_assignment.is_call,
        assignment_id=current_assignment.id,
        position=position,
        total_count=total_count,
        has_next=position < total_count,
        has_previous=position > 1
    )

@router.get("/navigation/next", response_model=LeadNavigationResponse)
async def get_next_lead(
    current_assignment_id: int = Query(..., description="Current assignment ID"),
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """
    Get next lead in sequence
    """
    # Get user's active assignments - use timezone-aware datetime
    now = datetime.now(timezone.utc)  # Fixed timezone issue
    expiry_cutoff = now - timedelta(hours=24)
    
    assignments = db.query(LeadAssignment).filter(
        and_(
            LeadAssignment.user_id == current_user.employee_code,
            LeadAssignment.fetched_at >= expiry_cutoff
        )
    ).order_by(LeadAssignment.fetched_at).all()  # Changed from created_at to fetched_at
    
    if not assignments:
        raise HTTPException(status_code=404, detail="No leads assigned")
    
    # Find current position
    current_index = next((i for i, a in enumerate(assignments) if a.id == current_assignment_id), -1)
    
    if current_index == -1:
        raise HTTPException(status_code=404, detail="Current assignment not found")
    
    # Check if next exists
    if current_index >= len(assignments) - 1:
        raise HTTPException(status_code=404, detail="No next lead available")
    
    # Get next assignment
    next_assignment = assignments[current_index + 1]
    
    # Get lead details
    lead = db.query(Lead).filter(Lead.id == next_assignment.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    position = current_index + 2  # +2 because index is 0-based and we want next
    total_count = len(assignments)
    
    return LeadNavigationResponse(
        id=lead.id,
        full_name=lead.full_name,
        email=lead.email,
        mobile=lead.mobile,
        city=lead.city,
        occupation=lead.occupation,
        investment=lead.investment,
        created_at=lead.created_at,
        lead_source_id=lead.lead_source_id,
        lead_response_id=lead.lead_response_id,
        is_call=next_assignment.is_call,
        assignment_id=next_assignment.id,
        position=position,
        total_count=total_count,
        has_next=position < total_count,
        has_previous=position > 1
    )

@router.get("/navigation/previous", response_model=LeadNavigationResponse)
async def get_previous_lead(
    current_assignment_id: int = Query(..., description="Current assignment ID"),
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """
    Get previous lead in sequence (including is_call=true leads)
    """
    # Get user's active assignments - use timezone-aware datetime
    now = datetime.now(timezone.utc)  # Fixed timezone issue
    expiry_cutoff = now - timedelta(hours=24)
    
    assignments = db.query(LeadAssignment).filter(
        and_(
            LeadAssignment.user_id == current_user.employee_code,
            LeadAssignment.fetched_at >= expiry_cutoff
        )
    ).order_by(LeadAssignment.fetched_at).all()  # Changed from created_at to fetched_at
    
    if not assignments:
        raise HTTPException(status_code=404, detail="No leads assigned")
    
    # Find current position
    current_index = next((i for i, a in enumerate(assignments) if a.id == current_assignment_id), -1)
    
    if current_index == -1:
        raise HTTPException(status_code=404, detail="Current assignment not found")
    
    # Check if previous exists
    if current_index <= 0:
        raise HTTPException(status_code=404, detail="No previous lead available")
    
    # Get previous assignment
    prev_assignment = assignments[current_index - 1]
    
    # Get lead details
    lead = db.query(Lead).filter(Lead.id == prev_assignment.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    position = current_index  # current_index is already 0-based, so this gives us the position
    total_count = len(assignments)
    
    return LeadNavigationResponse(
        id=lead.id,
        full_name=lead.full_name,
        email=lead.email,
        mobile=lead.mobile,
        city=lead.city,
        occupation=lead.occupation,
        investment=lead.investment,
        created_at=lead.created_at,
        lead_source_id=lead.lead_source_id,
        lead_response_id=lead.lead_response_id,
        is_call=prev_assignment.is_call,
        assignment_id=prev_assignment.id,
        position=position,
        total_count=total_count,
        has_next=position < total_count,
        has_previous=position > 1
    )

@router.put("/navigation/mark-called/{assignment_id}")
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
    
    return {"message": "Lead marked as called", "assignment_id": assignment_id}

@router.get("/navigation/position")
async def get_navigation_position(
    current_assignment_id: int = Query(..., description="Current assignment ID"),
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """
    Get navigation position info only
    """
    # Get user's active assignments - use timezone-aware datetime
    now = datetime.now(timezone.utc)  # Fixed timezone issue
    expiry_cutoff = now - timedelta(hours=24)
    
    assignments = db.query(LeadAssignment).filter(
        and_(
            LeadAssignment.user_id == current_user.employee_code,
            LeadAssignment.fetched_at >= expiry_cutoff
        )
    ).order_by(LeadAssignment.fetched_at).all()  # Changed from created_at to fetched_at
    
    if not assignments:
        raise HTTPException(status_code=404, detail="No leads assigned")
    
    # Find current position
    current_index = next((i for i, a in enumerate(assignments) if a.id == current_assignment_id), -1)
    
    if current_index == -1:
        raise HTTPException(status_code=404, detail="Assignment not found")
    
    position = current_index + 1
    total_count = len(assignments)
    
    return LeadPositionResponse(
        position=position,
        total_count=total_count,
        has_next=position < total_count,
        has_previous=position > 1
    )

@router.get("/navigation/uncalled-count")
async def get_uncalled_leads_count(
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user)
):
    """
    Get count of uncalled leads (is_call = false)
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

