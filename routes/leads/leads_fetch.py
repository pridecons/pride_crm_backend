# routes/leads/leads_fetch.py - FIXED VERSION with Automatic Config Loading

from datetime import datetime, date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from db.connection import get_db
from db.models import Lead, LeadAssignment, LeadFetchConfig, LeadFetchHistory, UserDetails
from routes.auth.auth_dependency import get_current_user, require_permission

router = APIRouter(
    prefix="/leads",
    tags=["leads fetch"],
)

# Remove the FetchRequest model since count is now automatic
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

class FetchConfigInfo(BaseModel):
    """Response model for fetch configuration info"""
    per_request_limit: int
    daily_call_limit: int
    assignment_ttl_hours: int
    remaining_calls_today: int
    config_source: str  # "role_branch", "role_global", "branch_global", or "default"

def load_fetch_config(db: Session, user: UserDetails) -> tuple[LeadFetchConfig, str]:
    """Load fetch configuration for user - Returns config and source"""
    
    # Priority order:
    # 1. Role + Branch specific config
    # 2. Global role config  
    # 3. Global branch config
    # 4. Fallback defaults
    
    cfg = None
    source = "default"
    
    # 1. Try role + branch specific config
    if user.role and user.branch_id:
        cfg = db.query(LeadFetchConfig).filter_by(
            role=user.role, 
            branch_id=user.branch_id
        ).first()
        if cfg:
            source = "role_branch"
    
    # 2. Fallback to global role config
    if not cfg and user.role:
        cfg = db.query(LeadFetchConfig).filter_by(
            role=user.role, 
            branch_id=None
        ).first()
        if cfg:
            source = "role_global"
    
    # 3. Fallback to global branch config
    if not cfg and user.branch_id:
        cfg = db.query(LeadFetchConfig).filter_by(
            role=None, 
            branch_id=user.branch_id
        ).first()
        if cfg:
            source = "branch_global"
    
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
        source = "default"
    
    return cfg, source


@router.get("/fetch-config", response_model=FetchConfigInfo)
def get_fetch_config_info(
    current_user: UserDetails = Depends(require_permission("fetch_lead")),
    db: Session = Depends(get_db),
):
    """Get current user's fetch configuration and remaining calls"""
    try:
        config, source = load_fetch_config(db, current_user)
        
        # Calculate remaining calls for today
        today = date.today()
        hist = (
            db.query(LeadFetchHistory)
            .filter_by(user_id=current_user.employee_code, date=today)
            .first()
        )
        
        calls_used_today = hist.call_count if hist else 0
        remaining_calls = max(0, config.daily_call_limit - calls_used_today)
        
        return FetchConfigInfo(
            per_request_limit=config.per_request_limit,
            daily_call_limit=config.daily_call_limit,
            assignment_ttl_hours=config.assignment_ttl_hours,
            remaining_calls_today=remaining_calls,
            config_source=source
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching configuration: {str(e)}"
        )


@router.post("/fetch", response_model=list[LeadFetchResponse])
def fetch_leads(
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(require_permission("fetch_lead")),
):
    """
    Fetch leads for the current user based on their role and branch configuration.
    Count is automatically determined from LeadFetchConfig.
    """
    try:
        # Load limits (per-request, daily-call, TTL) - Updated for branch-wise config
        config, config_source = load_fetch_config(db, current_user)

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
                detail=f"Daily fetch limit of {config.daily_call_limit} reached. Try again tomorrow.",
            )

        # 2. Compute expiry cutoff for "in-flight" assignments
        now = datetime.utcnow()
        expiry_cutoff = now - timedelta(hours=config.assignment_ttl_hours)

        # 3. Use per_request_limit from config as count
        to_fetch = config.per_request_limit
        
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
            return {
                "leads": [],
                "message": "No leads available at this time",
                "fetched_count": 0,
                "config_used": {
                    "per_request_limit": config.per_request_limit,
                    "source": config_source
                }
            }

        # 4. Delete any expired assignments that we're reclaiming
        expired_assignment_ids = []
        for lead in leads:
            expired_assignment = db.query(LeadAssignment).filter(
                LeadAssignment.lead_id == lead.id,
                LeadAssignment.fetched_at < expiry_cutoff
            ).first()
            if expired_assignment:
                expired_assignment_ids.append(expired_assignment.id)
                db.delete(expired_assignment)

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


@router.post("/fetch-with-count", response_model=list[LeadFetchResponse])
def fetch_leads_with_custom_count(
    count: int,
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(require_permission("fetch_lead")),
):
    """
    Fetch leads with a custom count (for special cases).
    Count will be limited by per_request_limit from config.
    """
    try:
        # Load config to check limits
        config, config_source = load_fetch_config(db, current_user)
        
        # Limit count by per_request_limit
        if count > config.per_request_limit:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Requested count ({count}) exceeds your limit of {config.per_request_limit}. Use /fetch endpoint for automatic count."
            )
        
        if count <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Count must be greater than 0"
            )

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
        ).limit(count).all()

        if not leads:
            return []

        # 4. Delete any expired assignments that we're reclaiming
        for lead in leads:
            expired_assignment = db.query(LeadAssignment).filter(
                LeadAssignment.lead_id == lead.id,
                LeadAssignment.fetched_at < expiry_cutoff
            ).first()
            if expired_assignment:
                db.delete(expired_assignment)

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
        config, _ = load_fetch_config(db, current_user)
        
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


@router.get("/my-assignments")
def get_my_assigned_leads(
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get leads currently assigned to the current user"""
    try:
        assignments = db.query(LeadAssignment).filter_by(
            user_id=current_user.employee_code
        ).all()
        
        config, _ = load_fetch_config(db, current_user)
        now = datetime.utcnow()
        expiry_cutoff = now - timedelta(hours=config.assignment_ttl_hours)
        
        assigned_leads = []
        for assignment in assignments:
            is_expired = assignment.fetched_at < expiry_cutoff
            
            assigned_leads.append({
                "lead_id": assignment.lead_id,
                "fetched_at": assignment.fetched_at,
                "is_expired": is_expired,
                "expires_at": assignment.fetched_at + timedelta(hours=config.assignment_ttl_hours),
                "lead_details": {
                    "full_name": assignment.lead.full_name if assignment.lead else None,
                    "mobile": assignment.lead.mobile if assignment.lead else None,
                    "email": assignment.lead.email if assignment.lead else None,
                }
            })
        
        return {
            "total_assigned": len(assigned_leads),
            "active_assignments": len([l for l in assigned_leads if not l["is_expired"]]),
            "expired_assignments": len([l for l in assigned_leads if l["is_expired"]]),
            "assignments": assigned_leads
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching assignments: {str(e)}"
        )
    

    