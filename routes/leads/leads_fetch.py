# routes/leads/leads_fetch.py - FIXED VERSION

from datetime import datetime, date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, conint
from sqlalchemy import or_
from sqlalchemy.orm import Session

from db.connection import get_db
from db.models import Lead, LeadAssignment, LeadFetchConfig, LeadFetchHistory, UserDetails
from routes.auth.auth_dependency import get_current_user, require_permission

router = APIRouter(
    prefix="/leads",
    tags=["leads fetch"],
)

class FetchRequest(BaseModel):
    count: conint(gt=0)  # must be a positive integer

class LeadFetchResponse(BaseModel):
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

def load_fetch_config(db: Session, user: UserDetails) -> LeadFetchConfig:
    """Load fetch configuration for user"""
    # Try per-user override first
    cfg = (
        db.query(LeadFetchConfig)
        .filter(LeadFetchConfig.user_id == user.employee_code)
        .first()
    )
    if not cfg:
        # Fallback to role-based config
        cfg = (
            db.query(LeadFetchConfig)
            .filter(LeadFetchConfig.role == user.role)
            .first()
        )
    if not cfg:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No fetch configuration found for your account/role",
        )
    return cfg

@router.post("/fetch", response_model=list[LeadFetchResponse])
def fetch_leads(
    body: FetchRequest,
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(require_permission("fetch_lead")),
):
    """
    Fetch leads for the current user based on their role and configuration
    """
    try:
        # Load limits (per-request, daily-call, TTL)
        config = load_fetch_config(db, current_user)

        # 1. Enforce daily-call limit
        today = date.today()
        hist = (
            db.query(LeadFetchHistory)
            .filter_by(user_id=current_user.employee_code, date=today)
            .first()
        )
        
        if hist and hist.call_count >= config.daily_call_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Daily fetch limit of {config.daily_call_limit} reached",
            )

        # 2. Compute expiry cutoff for "in-flight" assignments
        now = datetime.utcnow()
        expiry_cutoff = now - timedelta(hours=config.assignment_ttl_hours)

        # 3. Query for unassigned OR expired-assigned leads in the user's branch
        to_fetch = min(body.count, config.per_request_limit)
        
        # Build query based on user's branch
        query = db.query(Lead).outerjoin(LeadAssignment)
        
        # Filter by branch if user has one
        if current_user.branch_id:
            query = query.filter(Lead.branch_id == current_user.branch_id)
        
        # Filter for unassigned or expired assignments
        leads = query.filter(
            or_(
                LeadAssignment.id == None,  # Unassigned leads
                LeadAssignment.fetched_at < expiry_cutoff,  # Expired assignments
            ),
        ).limit(to_fetch).all()

        if not leads:
            return []

        # 4. Delete any expired assignments that we're reclaiming
        expired_assignments = db.query(LeadAssignment).filter(
            LeadAssignment.fetched_at < expiry_cutoff
        )
        
        for assignment in expired_assignments:
            db.delete(assignment)

        # 5. Assign the leads to this user
        for lead in leads:
            # Check if already assigned (shouldn't happen but just in case)
            existing_assignment = db.query(LeadAssignment).filter_by(lead_id=lead.id).first()
            if not existing_assignment:
                assignment = LeadAssignment(
                    lead_id=lead.id, 
                    user_id=current_user.employee_code
                )
                db.add(assignment)

        # 6. Update or create today's history record
        if not hist:
            hist = LeadFetchHistory(
                user_id=current_user.employee_code,
                date=today,
                call_count=1
            )
            db.add(hist)
        else:
            hist.call_count += 1

        # 7. Commit all changes
        db.commit()

        # 8. Convert leads to response format
        response_leads = []
        for lead in leads:
            try:
                lead_response = LeadFetchResponse(
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
                )
                response_leads.append(lead_response)
            except Exception as e:
                # Log error but continue with other leads
                print(f"Error converting lead {lead.id}: {e}")
                continue

        return response_leads

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching leads: {str(e)}"
        )

@router.get("/fetch-config")
def get_fetch_config(
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get current user's fetch configuration"""
    try:
        config = load_fetch_config(db, current_user)
        
        # Get today's usage
        today = date.today()
        hist = (
            db.query(LeadFetchHistory)
            .filter_by(user_id=current_user.employee_code, date=today)
            .first()
        )
        
        calls_today = hist.call_count if hist else 0
        
        return {
            "per_request_limit": config.per_request_limit,
            "daily_call_limit": config.daily_call_limit,
            "assignment_ttl_hours": config.assignment_ttl_hours,
            "calls_today": calls_today,
            "remaining_calls": max(0, config.daily_call_limit - calls_today),
            "can_fetch": calls_today < config.daily_call_limit
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting fetch config: {str(e)}"
        )

@router.get("/my-assigned-leads")
def get_my_assigned_leads(
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get leads assigned to current user"""
    try:
        # Get all lead assignments for current user
        assignments = (
            db.query(LeadAssignment)
            .filter_by(user_id=current_user.employee_code)
            .all()
        )
        
        # Get the actual leads
        lead_ids = [assignment.lead_id for assignment in assignments]
        leads = db.query(Lead).filter(Lead.id.in_(lead_ids)).all()
        
        # Convert to response format
        response_leads = []
        for lead in leads:
            try:
                lead_response = LeadFetchResponse(
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
                )
                response_leads.append(lead_response)
            except Exception as e:
                print(f"Error converting lead {lead.id}: {e}")
                continue
        
        return {
            "total_assigned": len(leads),
            "leads": response_leads
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching assigned leads: {str(e)}"
        )