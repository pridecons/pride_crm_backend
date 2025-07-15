# routes/leads/leads_fetch.py - Updated with last_fetch_limit logic

from datetime import datetime, date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_, and_, func
from sqlalchemy.orm import Session

from db.connection import get_db
from db.models import Lead, LeadAssignment, LeadFetchConfig, LeadFetchHistory, UserDetails
from routes.auth.auth_dependency import get_current_user, require_permission

router = APIRouter(
    prefix="/leads",
    tags=["leads fetch"],
)

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
    last_fetch_limit: int
    assignment_ttl_hours: int
    remaining_calls_today: int
    current_assignments: int
    can_fetch: bool
    config_source: str

def get_user_active_assignments_count(db: Session, user_id: str, assignment_ttl_hours: int) -> int:
    """Get count of active (non-expired) assignments for user"""
    now = datetime.utcnow()
    expiry_cutoff = now - timedelta(hours=assignment_ttl_hours)
    
    active_assignments = db.query(LeadAssignment).filter(
        and_(
            LeadAssignment.user_id == user_id,
            LeadAssignment.fetched_at >= expiry_cutoff
        )
    ).count()
    
    return active_assignments

def can_user_fetch_leads(db: Session, user_id: str, config: LeadFetchConfig) -> tuple[bool, int]:
    """
    Check if user can fetch leads based on last_fetch_limit
    Returns: (can_fetch, current_assignments_count)
    """
    current_assignments = get_user_active_assignments_count(db, user_id, config.assignment_ttl_hours)
    
    # User can fetch if current assignments <= last_fetch_limit
    can_fetch = current_assignments <= config.last_fetch_limit
    
    return can_fetch, current_assignments

def load_fetch_config(db: Session, user: UserDetails) -> tuple[LeadFetchConfig, str]:
    """Load fetch configuration for user - Returns config and source"""
    
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
            "SUPERADMIN": {
                "per_request_limit": 100, 
                "daily_call_limit": 50, 
                "last_fetch_limit": 10,
                "assignment_ttl_hours": 24
            },
            "BRANCH_MANAGER": {
                "per_request_limit": 50, 
                "daily_call_limit": 30, 
                "last_fetch_limit": 8,
                "assignment_ttl_hours": 48
            },
            "SALES_MANAGER": {
                "per_request_limit": 30, 
                "daily_call_limit": 20, 
                "last_fetch_limit": 6,
                "assignment_ttl_hours": 72
            },
            "TL": {
                "per_request_limit": 20, 
                "daily_call_limit": 15, 
                "last_fetch_limit": 5,
                "assignment_ttl_hours": 72
            },
            "BA": {
                "per_request_limit": 10, 
                "daily_call_limit": 10, 
                "last_fetch_limit": 3,
                "assignment_ttl_hours": 168
            },
            "SBA": {
                "per_request_limit": 15, 
                "daily_call_limit": 12, 
                "last_fetch_limit": 4,
                "assignment_ttl_hours": 120
            }
        }
        
        role_str = user.role.value if hasattr(user.role, 'value') else str(user.role)
        default_config = default_configs.get(role_str, {
            "per_request_limit": 10, 
            "daily_call_limit": 5, 
            "last_fetch_limit": 3,
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
    """Get current user's fetch configuration and status"""
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
        
        # Check current assignments and fetch eligibility
        can_fetch, current_assignments = can_user_fetch_leads(db, current_user.employee_code, config)
        
        return FetchConfigInfo(
            per_request_limit=config.per_request_limit,
            daily_call_limit=config.daily_call_limit,
            last_fetch_limit=config.last_fetch_limit,
            assignment_ttl_hours=config.assignment_ttl_hours,
            remaining_calls_today=remaining_calls,
            current_assignments=current_assignments,
            can_fetch=can_fetch and remaining_calls > 0,
            config_source=source
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching configuration: {str(e)}"
        )


@router.post("/fetch", response_model=dict)
def fetch_leads(
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(require_permission("fetch_lead")),
):
    """
    Fetch leads for the current user based on their role and branch configuration.
    Count is automatically determined from LeadFetchConfig.
    Respects last_fetch_limit to control when user can fetch new leads.
    """
    try:
        # Load limits (per-request, daily-call, last-fetch, TTL)
        config, config_source = load_fetch_config(db, current_user)

        # 1. Check last_fetch_limit constraint
        can_fetch, current_assignments = can_user_fetch_leads(db, current_user.employee_code, config)
        
        if not can_fetch:
            return {
                "leads": [],
                "message": f"You have {current_assignments} active assignments. Complete them to fetch new leads (limit: {config.last_fetch_limit})",
                "fetched_count": 0,
                "current_assignments": current_assignments,
                "config_used": {
                    "per_request_limit": config.per_request_limit,
                    "last_fetch_limit": config.last_fetch_limit,
                    "source": config_source
                }
            }

        # 2. Enforce daily-call limit
        today = date.today()
        hist = (
            db.query(LeadFetchHistory)
            .filter_by(user_id=current_user.employee_code, date=today)
            .first()
        )
        
        if hist and hist.call_count >= config.daily_call_limit:
            return {
                "leads": [],
                "message": f"Daily fetch limit of {config.daily_call_limit} reached. Try again tomorrow.",
                "fetched_count": 0,
                "current_assignments": current_assignments,
                "config_used": {
                    "per_request_limit": config.per_request_limit,
                    "last_fetch_limit": config.last_fetch_limit,
                    "source": config_source
                }
            }

        # 3. Compute expiry cutoff for "in-flight" assignments
        now = datetime.utcnow()
        expiry_cutoff = now - timedelta(hours=config.assignment_ttl_hours)

        # 4. Use per_request_limit from config as count
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
                "current_assignments": current_assignments,
                "config_used": {
                    "per_request_limit": config.per_request_limit,
                    "last_fetch_limit": config.last_fetch_limit,
                    "source": config_source
                }
            }

        # 5. Delete any expired assignments that we're reclaiming
        expired_assignment_ids = []
        for lead in leads:
            expired_assignment = db.query(LeadAssignment).filter(
                LeadAssignment.lead_id == lead.id,
                LeadAssignment.fetched_at < expiry_cutoff
            ).first()
            if expired_assignment:
                expired_assignment_ids.append(expired_assignment.id)
                db.delete(expired_assignment)

        # 6. Assign the leads to this user
        for lead in leads:
            # Check if already assigned (shouldn't happen but just in case)
            existing_assignment = db.query(LeadAssignment).filter_by(lead_id=lead.id).first()
            if not existing_assignment:
                assignment = LeadAssignment(
                    lead_id=lead.id, 
                    user_id=current_user.employee_code
                )
                db.add(assignment)

        # 7. Update or create today's history record
        if not hist:
            hist = LeadFetchHistory(
                user_id=current_user.employee_code,
                date=today,
                call_count=1
            )
            db.add(hist)
        else:
            hist.call_count += 1

        # 8. Commit all changes
        db.commit()

        # 9. Convert leads to response format
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

        return {
            "leads": response_leads,
            "message": f"Successfully fetched {len(response_leads)} leads",
            "fetched_count": len(response_leads),
            "current_assignments": current_assignments + len(response_leads),
            "config_used": {
                "per_request_limit": config.per_request_limit,
                "last_fetch_limit": config.last_fetch_limit,
                "source": config_source
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching leads: {str(e)}"
        )


@router.get("/my-assignments")
def get_my_assignments(
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(require_permission("fetch_lead")),
):
    """Get current user's active lead assignments"""
    try:
        config, _ = load_fetch_config(db, current_user)
        
        # Get non-expired assignments
        now = datetime.utcnow()
        expiry_cutoff = now - timedelta(hours=config.assignment_ttl_hours)
        
        assignments = db.query(LeadAssignment).join(Lead).filter(
            and_(
                LeadAssignment.user_id == current_user.employee_code,
                LeadAssignment.fetched_at >= expiry_cutoff
            )
        ).all()
        
        assignment_data = []
        for assignment in assignments:
            assignment_data.append({
                "assignment_id": assignment.id,
                "lead_id": assignment.lead_id,
                "lead_name": assignment.lead.full_name,
                "lead_mobile": assignment.lead.mobile,
                "lead_email": assignment.lead.email,
                "fetched_at": assignment.fetched_at,
                "expires_at": assignment.fetched_at + timedelta(hours=config.assignment_ttl_hours)
            })
        
        return {
            "assignments": assignment_data,
            "total_count": len(assignment_data),
            "assignment_ttl_hours": config.assignment_ttl_hours
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching assignments: {str(e)}"
        )


@router.delete("/assignment/{assignment_id}")
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
            "assignment_id": assignment_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error completing assignment: {str(e)}"
        )
    
    