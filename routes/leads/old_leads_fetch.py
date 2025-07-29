# routes/leads/old_leads_fetch.py

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from datetime import datetime, timedelta

from db.connection import get_db
from db.models import Lead, LeadAssignment, UserDetails, LeadFetchConfig
from routes.auth.auth_dependency import require_permission
from utils.AddLeadStory import AddLeadStory
from pydantic import BaseModel

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

@router.post("/fetch", response_model=dict)
def fetch_old_leads(
    limit: Optional[int] = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(require_permission("fetch_lead"))
):
    """
    Fetch old leads for the current user (Point 10)
    Only returns leads marked as is_old_lead = True
    """
    try:
        # Load user's fetch configuration
        config, cfg_source = load_fetch_config(db, current_user)
        
        # Check if user can fetch more leads
        can_fetch, active_count = can_user_fetch_leads(
            db, current_user.employee_code, config
        )
        
        if not can_fetch:
            return {
                "leads": [],
                "message": f"You have {active_count} active assignments (limit: {config.last_fetch_limit})",
                "fetched_count": 0,
                "config_used": {
                    "per_request_limit": config.per_request_limit,
                    "last_fetch_limit": config.last_fetch_limit,
                    "source": cfg_source
                }
            }
        
        # Calculate expiry cutoff for assignments
        now = datetime.utcnow()
        expiry_cutoff = now - timedelta(hours=config.assignment_ttl_hours)
        
        # Use limit or config per_request_limit
        to_fetch = min(limit, config.per_request_limit)
        
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
        
        # Get leads
        old_leads = query.limit(to_fetch).all()
        
        if not old_leads:
            return {
                "leads": [],
                "message": "No old leads available at this time",
                "fetched_count": 0,
                "current_assignments": active_count,
                "config_used": {
                    "per_request_limit": config.per_request_limit,
                    "last_fetch_limit": config.last_fetch_limit,
                    "source": cfg_source
                }
            }
        
        # Process each lead
        for lead in old_leads:
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
                
                # Reset conversion fields if expired
                if lead.assigned_for_conversion and lead.conversion_deadline and lead.conversion_deadline < now:
                    lead.assigned_for_conversion = False
                    lead.assigned_to_user = None
                    lead.conversion_deadline = None
        
        db.commit()
        
        # Add stories for fetched leads
        for lead in old_leads:
            AddLeadStory(
                lead.id,
                current_user.employee_code,
                f"{current_user.name} ({current_user.employee_code}) fetched this OLD lead"
            )
        
        # Prepare response
        response_leads = []
        for lead in old_leads:
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
            "config_used": {
                "per_request_limit": config.per_request_limit,
                "last_fetch_limit": config.last_fetch_limit,
                "source": cfg_source
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error fetching old leads: {e}")


@router.get("/my-assigned")
def get_my_assigned_old_leads(
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(require_permission("fetch_lead"))
):
    """Get old leads currently assigned to user"""
    
    # Get active assignments for old leads
    now = datetime.utcnow()
    expiry_cutoff = now - timedelta(hours=24 * 7)  # 7 days default TTL
    
    assigned_leads = db.query(Lead).join(LeadAssignment).filter(
        and_(
            Lead.is_old_lead == True,
            Lead.is_delete == False,
            Lead.is_client == False,
            LeadAssignment.user_id == current_user.employee_code,
            LeadAssignment.fetched_at >= expiry_cutoff
        )
    ).all()
    
    response_leads = []
    for lead in assigned_leads:
        days_remaining = None
        if lead.conversion_deadline:
            delta = lead.conversion_deadline - now
            days_remaining = max(0, delta.days)
        
        response_leads.append({
            "id": lead.id,
            "full_name": lead.full_name,
            "mobile": lead.mobile,
            "email": lead.email,
            "response_changed_at": lead.response_changed_at,
            "conversion_deadline": lead.conversion_deadline,
            "days_remaining": days_remaining,
            "assigned_for_conversion": lead.assigned_for_conversion
        })
    
    return {
        "assigned_old_leads": response_leads,
        "count": len(response_leads)
    }


@router.get("/stats")
def get_old_leads_stats(
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(require_permission("fetch_lead"))
):
    """Get statistics about old leads"""
    
    now = datetime.utcnow()
    
    # Total old leads available
    available_old_leads = db.query(Lead).outerjoin(LeadAssignment).filter(
        and_(
            Lead.is_old_lead == True,
            Lead.is_delete == False,
            Lead.is_client == False,
            or_(
                LeadAssignment.id == None,
                LeadAssignment.fetched_at < now - timedelta(hours=168)  # 7 days
            )
        )
    )
    
    if current_user.branch_id:
        available_old_leads = available_old_leads.filter(Lead.branch_id == current_user.branch_id)
    
    total_available = available_old_leads.count()
    
    # User's assigned old leads
    user_assigned = db.query(Lead).join(LeadAssignment).filter(
        and_(
            Lead.is_old_lead == True,
            Lead.is_delete == False,
            Lead.is_client == False,
            LeadAssignment.user_id == current_user.employee_code,
            LeadAssignment.fetched_at >= now - timedelta(hours=168)
        )
    ).count()
    
    # Conversion deadline approaching (next 3 days)
    deadline_approaching = db.query(Lead).filter(
        and_(
            Lead.is_old_lead == True,
            Lead.assigned_to_user == current_user.employee_code,
            Lead.conversion_deadline.between(now, now + timedelta(days=3)),
            Lead.is_client == False
        )
    ).count()
    
    return {
        "total_available_old_leads": total_available,
        "my_assigned_old_leads": user_assigned,
        "deadline_approaching": deadline_approaching,
        "can_fetch_more": user_assigned < 10  # Assuming limit of 10
    }


# Helper functions
def load_fetch_config(db: Session, user: UserDetails):
    """Same as in leads_fetch.py"""
    # Implementation same as leads_fetch.py
    pass

def can_user_fetch_leads(db: Session, user_id: str, config):
    """Same as in leads_fetch.py"""
    # Implementation same as leads_fetch.py
    pass

