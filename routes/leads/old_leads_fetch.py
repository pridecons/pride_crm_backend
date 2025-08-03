# routes/leads/old_leads_fetch.py - Complete Implementation

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from datetime import datetime, timedelta
import logging

from db.connection import get_db
from db.models import Lead, LeadAssignment, UserDetails, LeadFetchConfig, LeadFetchHistory
from routes.auth.auth_dependency import require_permission
from utils.AddLeadStory import AddLeadStory
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/old-leads", tags=["Old Lead Management"])

class OldLeadResponse(BaseModel):
    id: int
    full_name: Optional[str]
    email: Optional[str]
    mobile: Optional[str]
    city: Optional[str]
    occupation: Optional[str]
    investment: Optional[str]
    created_at: datetime
    response_changed_at: Optional[datetime]
    conversion_deadline: Optional[datetime]
    days_remaining: Optional[int]
    lead_source_id: Optional[int]
    lead_response_id: Optional[int]
    assigned_to_user: Optional[str]

# Helper functions
def load_fetch_config(db: Session, user: UserDetails):
    """Load fetch config for user from LeadFetchConfig"""
    cfg = None
    source = "default"

    try:
        # 1️⃣ Try role+branch first
        if user.role and user.branch_id:
            cfg = db.query(LeadFetchConfig).filter_by(
                role=user.role, 
                branch_id=user.branch_id
            ).first()
            if cfg:
                source = "role_branch"

        # 2️⃣ Try role global
        if not cfg and user.role:
            cfg = db.query(LeadFetchConfig).filter_by(
                role=user.role, 
                branch_id=None
            ).first()
            if cfg:
                source = "role_global"

        # 3️⃣ Try branch global
        if not cfg and user.branch_id:
            cfg = db.query(LeadFetchConfig).filter_by(
                role=None, 
                branch_id=user.branch_id
            ).first()
            if cfg:
                source = "branch_global"

        # 4️⃣ Default fallback based on role
        if not cfg:
            defaults = {
                "SUPERADMIN": dict(
                    per_request_limit=50, 
                    daily_call_limit=30, 
                    last_fetch_limit=15, 
                    assignment_ttl_hours=24,
                    old_lead_remove_days=15
                ),
                "BRANCH_MANAGER": dict(
                    per_request_limit=30, 
                    daily_call_limit=20, 
                    last_fetch_limit=10, 
                    assignment_ttl_hours=48,
                    old_lead_remove_days=20
                ),
                "SALES_MANAGER": dict(
                    per_request_limit=25, 
                    daily_call_limit=15, 
                    last_fetch_limit=8, 
                    assignment_ttl_hours=72,
                    old_lead_remove_days=25
                ),
                "TL": dict(
                    per_request_limit=20, 
                    daily_call_limit=12, 
                    last_fetch_limit=6, 
                    assignment_ttl_hours=72,
                    old_lead_remove_days=30
                ),
                "BA": dict(
                    per_request_limit=10, 
                    daily_call_limit=8, 
                    last_fetch_limit=4, 
                    assignment_ttl_hours=168,
                    old_lead_remove_days=30
                ),
                "SBA": dict(
                    per_request_limit=15, 
                    daily_call_limit=10, 
                    last_fetch_limit=5, 
                    assignment_ttl_hours=120,
                    old_lead_remove_days=25
                ),
                "HR": dict(
                    per_request_limit=5, 
                    daily_call_limit=3, 
                    last_fetch_limit=2, 
                    assignment_ttl_hours=168,
                    old_lead_remove_days=30
                )
            }
            
            role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
            cfg_values = defaults.get(role_str, defaults["BA"])

            class TempConfig:
                def __init__(self, **kw):
                    for k, v in kw.items():
                        setattr(self, k, v)

            cfg = TempConfig(**cfg_values)
            source = "default"

    except Exception as e:
        logger.error(f"Error loading fetch config: {e}")
        # Emergency fallback
        class TempConfig:
            def __init__(self, **kw):
                for k, v in kw.items():
                    setattr(self, k, v)
        cfg = TempConfig(
            per_request_limit=10,
            daily_call_limit=5,
            last_fetch_limit=3,
            assignment_ttl_hours=168,
            old_lead_remove_days=30
        )
        source = "emergency_fallback"

    return cfg, source

def get_user_active_assignments_count(db: Session, user_id: str, assignment_ttl_hours: int):
    """Get count of user's active assignments"""
    try:
        expiry_cutoff = datetime.utcnow() - timedelta(hours=assignment_ttl_hours)
        
        active_count = db.query(LeadAssignment).filter(
            and_(
                LeadAssignment.user_id == user_id,
                LeadAssignment.fetched_at >= expiry_cutoff
            )
        ).count()
        
        return active_count
    except Exception as e:
        logger.error(f"Error getting active assignments count: {e}")
        return 0

def can_user_fetch_leads(db: Session, user_id: str, config):
    """Check if user can fetch more leads based on last_fetch_limit"""
    try:
        current_assignments = get_user_active_assignments_count(
            db, user_id, config.assignment_ttl_hours
        )
        
        can_fetch = current_assignments < config.last_fetch_limit
        return can_fetch, current_assignments
    except Exception as e:
        logger.error(f"Error checking fetch eligibility: {e}")
        return False, 0

def check_daily_call_limit(db: Session, user_id: str, daily_limit: int):
    """Check if user has exceeded daily call limit"""
    try:
        today = datetime.utcnow().date()
        
        # Get or create today's history record
        hist = db.query(LeadFetchHistory).filter_by(
            user_id=user_id,
            date=today
        ).first()
        
        if not hist:
            return True, 0  # No calls made today, can fetch
        
        return hist.call_count < daily_limit, hist.call_count
    except Exception as e:
        logger.error(f"Error checking daily limit: {e}")
        return False, 0

@router.post("/fetch", response_model=dict)
def fetch_old_leads(
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(require_permission("fetch_lead"))
):
    """
    Fetch old leads for the current user (Point 10)
    Only returns leads marked as is_old_lead = True
    Limits are taken from LeadFetchConfig based on user role/branch
    """
    try:
        logger.info(f"User {current_user.employee_code} requesting old leads fetch")
        
        # Load user's fetch configuration from database
        config, cfg_source = load_fetch_config(db, current_user)
        logger.info(f"Using config from: {cfg_source}")
        
        # Check daily call limit
        can_call_today, today_calls = check_daily_call_limit(
            db, current_user.employee_code, config.daily_call_limit
        )
        
        if not can_call_today:
            return {
                "leads": [],
                "message": f"Daily fetch limit reached ({today_calls}/{config.daily_call_limit}). Try again tomorrow.",
                "fetched_count": 0,
                "config_used": {
                    "per_request_limit": config.per_request_limit,
                    "daily_call_limit": config.daily_call_limit,
                    "last_fetch_limit": config.last_fetch_limit,
                    "source": cfg_source
                }
            }
        
        # Check if user can fetch more leads (last_fetch_limit)
        can_fetch, active_count = can_user_fetch_leads(
            db, current_user.employee_code, config
        )
        
        if not can_fetch:
            return {
                "leads": [],
                "message": f"You have {active_count} active assignments (limit: {config.last_fetch_limit})",
                "fetched_count": 0,
                "current_assignments": active_count,
                "config_used": {
                    "per_request_limit": config.per_request_limit,
                    "daily_call_limit": config.daily_call_limit,
                    "last_fetch_limit": config.last_fetch_limit,
                    "source": cfg_source
                }
            }
        
        # Determine how many leads to fetch

        to_fetch = config.per_request_limit
        logger.info(f"Using config per_request_limit: {to_fetch}")
        
        # Calculate expiry cutoff for assignments
        now = datetime.utcnow()
        expiry_cutoff = now - timedelta(hours=config.assignment_ttl_hours)
        
        # Query for old leads
        query = db.query(Lead).outerjoin(LeadAssignment)
        
        # Filter for old leads only
        query = query.filter(
            and_(
                Lead.is_old_lead == True,
                Lead.is_delete == False,
                Lead.is_client == False,  # Not converted to client
                or_(
                    LeadAssignment.id == None,  # Unassigned
                    LeadAssignment.fetched_at < expiry_cutoff,  # Expired assignment
                    and_(  # Or user's own expired conversion assignments
                        Lead.assigned_for_conversion == True,
                        Lead.conversion_deadline < now,
                        Lead.assigned_to_user == current_user.employee_code
                    )
                )
            )
        )
        
        # Branch filtering if user has branch
        if current_user.branch_id:
            query = query.filter(Lead.branch_id == current_user.branch_id)
            logger.info(f"Filtering by branch: {current_user.branch_id}")
        
        # Get leads with limit
        old_leads = query.limit(to_fetch).all()
        logger.info(f"Found {len(old_leads)} old leads to assign")
        
        if not old_leads:
            return {
                "leads": [],
                "message": "No old leads available at this time",
                "fetched_count": 0,
                "current_assignments": active_count,
                "config_used": {
                    "per_request_limit": config.per_request_limit,
                    "daily_call_limit": config.daily_call_limit,
                    "last_fetch_limit": config.last_fetch_limit,
                    "source": cfg_source
                }
            }
        
        # Process each lead
        assigned_leads = []
        for lead in old_leads:
            try:
                # Remove expired assignments
                expired_assignment = db.query(LeadAssignment).filter(
                    and_(
                        LeadAssignment.lead_id == lead.id,
                        or_(
                            LeadAssignment.fetched_at < expiry_cutoff,
                            and_(
                                Lead.assigned_for_conversion == True,
                                Lead.conversion_deadline < now
                            )
                        )
                    )
                ).first()
                
                if expired_assignment:
                    logger.info(f"Removing expired assignment for lead {lead.id}")
                    db.delete(expired_assignment)
                
                # Create new assignment if not already assigned
                existing_assignment = db.query(LeadAssignment).filter_by(
                    lead_id=lead.id
                ).first()
                
                if not existing_assignment:
                    new_assignment = LeadAssignment(
                        lead_id=lead.id,
                        user_id=current_user.employee_code,
                        fetched_at=now
                    )
                    db.add(new_assignment)
                    assigned_leads.append(lead)
                    
                    # Reset conversion fields if expired
                    if (lead.assigned_for_conversion and 
                        lead.conversion_deadline and 
                        lead.conversion_deadline < now):
                        
                        logger.info(f"Resetting expired conversion fields for lead {lead.id}")
                        lead.assigned_for_conversion = False
                        lead.assigned_to_user = None
                        lead.conversion_deadline = None
                        
            except Exception as e:
                logger.error(f"Error processing lead {lead.id}: {e}")
                continue
        
        # Update daily fetch history
        today = datetime.utcnow().date()
        hist = db.query(LeadFetchHistory).filter_by(
            user_id=current_user.employee_code,
            date=today
        ).first()
        
        if not hist:
            hist = LeadFetchHistory(
                user_id=current_user.employee_code,
                date=today,
                call_count=1
            )
            db.add(hist)
        else:
            hist.call_count += 1
        
        # Commit all changes
        db.commit()
        logger.info(f"Successfully assigned {len(assigned_leads)} old leads to user {current_user.employee_code}")
        
        # Add stories for fetched leads
        for lead in assigned_leads:
            try:
                AddLeadStory(
                    lead.id,
                    current_user.employee_code,
                    f"{current_user.name} ({current_user.employee_code}) fetched this OLD lead"
                )
            except Exception as e:
                logger.error(f"Error adding story for lead {lead.id}: {e}")
        
        # Prepare response
        response_leads = []
        for lead in assigned_leads:
            days_remaining = None
            if lead.conversion_deadline:
                delta = lead.conversion_deadline - now
                days_remaining = max(0, delta.days)
            
            response_leads.append(OldLeadResponse(
                id=lead.id,
                full_name=lead.full_name,
                email=lead.email,
                mobile=lead.mobile,
                city=lead.city,
                occupation=lead.occupation,
                investment=lead.investment,
                created_at=lead.created_at,
                response_changed_at=lead.response_changed_at,
                conversion_deadline=lead.conversion_deadline,
                days_remaining=days_remaining,
                lead_source_id=lead.lead_source_id,
                lead_response_id=lead.lead_response_id,
                assigned_to_user=lead.assigned_to_user
            ))
        
        return {
            "leads": response_leads,
            "message": f"Successfully fetched {len(response_leads)} old leads",
            "fetched_count": len(response_leads),
            "current_assignments": active_count + len(response_leads),
            "today_calls": hist.call_count,
            "config_used": {
                "per_request_limit": config.per_request_limit,
                "daily_call_limit": config.daily_call_limit,
                "last_fetch_limit": config.last_fetch_limit,
                "assignment_ttl_hours": config.assignment_ttl_hours,
                "source": cfg_source
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in fetch_old_leads: {e}")
        db.rollback()
        raise HTTPException(500, f"Error fetching old leads: {str(e)}")


@router.get("/my-assigned")
def get_my_assigned_old_leads(
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(require_permission("fetch_lead"))
):
    """Get old leads currently assigned to user"""
    
    try:       
        assigned_leads = db.query(Lead).filter(
            and_(
                Lead.is_old_lead == True,
                Lead.is_delete == False,
                Lead.is_client == False,
                Lead.assigned_to_user == current_user.employee_code
            )
        ).all()
        
        return {
            "assigned_old_leads": assigned_leads,
            "count": len(assigned_leads)
        }
        
    except Exception as e:
        logger.error(f"Error getting assigned old leads: {e}")
        raise HTTPException(500, f"Error getting assigned leads: {str(e)}")


