# routes/leads/assignments.py - Fixed version with proper route ordering

from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_
from sqlalchemy.orm import Session

from db.connection import get_db
from db.models import Lead, LeadAssignment, UserDetails
from routes.auth.auth_dependency import require_permission
from routes.leads.leads_fetch import load_fetch_config

# Create a separate router with a specific prefix to avoid conflicts
router = APIRouter(
    prefix="/leads/assignments",  # Changed to more specific prefix
    tags=["lead assignments"],
)

class AssignmentResponse(BaseModel):
    assignment_id: int
    lead_id: int
    lead_name: Optional[str]
    lead_mobile: Optional[str]
    lead_email: Optional[str]
    lead_city: Optional[str]
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
        
        db.delete(assignment)
        db.commit()
        
        return {
            "message": "Assignment completed successfully",
            "assignment_id": assignment_id,
            "lead_id": assignment.lead_id
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