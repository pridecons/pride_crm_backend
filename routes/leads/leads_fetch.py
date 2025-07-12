# routes/leads/leads_fetch.py - Updated for Branch-wise Config

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
    """Load fetch configuration for user - Updated for branch-wise config"""
    
    # Priority order:
    # 1. Role + Branch specific config
    # 2. Global role config  
    # 3. Global branch config
    # 4. Fallback defaults
    
    cfg = None
    
    # 1. Try role + branch specific config
    if user.role and user.branch_id:
        cfg = db.query(LeadFetchConfig).filter_by(
            role=user.role, 
            branch_id=user.branch_id
        ).first()
    
    # 2. Fallback to global role config
    if not cfg and user.role:
        cfg = db.query(LeadFetchConfig).filter_by(
            role=user.role, 
            branch_id=None
        ).first()
    
    # 3. Fallback to global branch config
    if not cfg and user.branch_id:
        cfg = db.query(LeadFetchConfig).filter_by(
            role=None, 
            branch_id=user.branch_id
        ).first()
    
    # 4. If no config found, use defaults based on role
    if not cfg:
        default_configs = {
            "SUPERADMIN": {"per_request_limit": 100, "daily_call_limit": 50, "assignment_ttl_hours": 24},
            "BRANCH_MANAGER": {"per_request_limit": 50, "daily_call_limit": 30, "assignment_ttl_hours": 48},
            "SALES_MANAGER": {"per_request_limit": 30, "daily_call_limit": 20, "assignment_ttl_hours": 72},
            "TL": {"per_request_limit": 20, "daily_call_limit": 15, "assignment_ttl_hours": 72},
            "BA": {"per_request_limit": 10, "daily_call_limit": 10, "assignment_ttl_hours": 168},
            "SBA": {"per_request_limit": 15, "daily_call_limit": 12, "assignment_ttl_hours": 120}
        }
        
        role_str = user.role.value if hasattr(user.role, 'value') else str(user.role)
        default_config = default_configs.get(role_str, {
            "per_request_limit": 10, 
            "daily_call_limit": 5, 
            "assignment_ttl_hours": 168
        })
        
        # Create a temporary config object
        class TempConfig:
            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    setattr(self, key, value)
        
        cfg = TempConfig(**default_config)
    
    return cfg


@router.post("/fetch", response_model=list[LeadFetchResponse])
def fetch_leads(
    body: FetchRequest,
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(require_permission("fetch_lead")),
):
    """
    Fetch leads for the current user based on their role and branch configuration
    """
    try:
        # Load limits (per-request, daily-call, TTL) - Updated for branch-wise config
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
        
        # Filter by branch if user has one (branch-wise lead distribution)
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


@router.post("/release-expired")
def release_expired_assignments(
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually release expired lead assignments"""
    try:
        config = load_fetch_config(db, current_user)
        
        # Calculate expiry cutoff
        now = datetime.utcnow()
        expiry_cutoff = now - timedelta(hours=config.assignment_ttl_hours)
        
        # Find expired assignments
        expired_assignments = db.query(LeadAssignment).filter(
            LeadAssignment.fetched_at < expiry_cutoff
        ).all()
        
        expired_count = len(expired_assignments)
        
        # Delete expired assignments
        for assignment in expired_assignments:
            db.delete(assignment)
        
        db.commit()
        
        return {
            "message": f"Released {expired_count} expired lead assignments",
            "expired_count": expired_count,
            "expiry_cutoff": expiry_cutoff.isoformat(),
            "assignment_ttl_hours": config.assignment_ttl_hours
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error releasing expired assignments: {str(e)}"
        )
    
