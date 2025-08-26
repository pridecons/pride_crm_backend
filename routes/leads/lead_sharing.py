# routes/leads/lead_sharing.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from datetime import datetime, timedelta
import logging

from db.connection import get_db
from db.models import (
    Lead, UserDetails, LeadAssignment, BranchDetails, LeadStory, AuditLog
)
from routes.auth.auth_dependency import get_current_user
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/lead-sharing", tags=["Lead Sharing"])

# Pydantic Models
class LeadShareRequest(BaseModel):
    lead_id: int = Field(..., description="ID of the lead to share")
    target_user_id: str = Field(..., description="Employee code of user to share with")
    message: Optional[str] = Field(None, description="Optional message for sharing")
    transfer_ownership: bool = Field(False, description="Whether to transfer ownership or just share")

class LeadShareResponse(BaseModel):
    id: int
    lead_id: int
    shared_by: str
    shared_with: str
    shared_at: datetime
    message: Optional[str]
    transfer_ownership: bool
    status: str

class BulkLeadShareRequest(BaseModel):
    lead_ids: List[int] = Field(..., description="List of lead IDs to share")
    target_user_id: str = Field(..., description="Employee code of user to share with")
    message: Optional[str] = Field(None, description="Optional message for sharing")
    transfer_ownership: bool = Field(False, description="Whether to transfer ownership or just share")

# Helper Functions
def can_share_lead(current_user: UserDetails, lead: Lead, db: Session) -> bool:
    """Check if current user can share this lead"""
    
    # SUPERADMIN can share any lead
    if current_user.role == "SUPERADMIN":
        return True
    
    # BRANCH_MANAGER can share leads in their branch
    if current_user.role == "BRANCH_MANAGER":
        if current_user.manages_branch and current_user.manages_branch.id == lead.branch_id:
            return True
    
    # Check if user is assigned to this lead
    assignment = db.query(LeadAssignment).filter(
        and_(
            LeadAssignment.lead_id == lead.id,
            LeadAssignment.user_id == current_user.employee_code
        )
    ).first()
    
    if assignment:
        return True
    
    
    return False

def can_receive_lead(target_user: UserDetails, current_user: UserDetails) -> bool:
    """Check if target user can receive leads"""
    
    # Can't share with yourself
    if target_user.employee_code == current_user.employee_code:
        return False
    
    # Target user must be active
    if not target_user.is_active:
        return False
    
    # Check role hierarchy - can only share to same or lower level
    if current_user.get_hierarchy_level() > target_user.get_hierarchy_level():
        return False
    
    return True

# API Endpoints

@router.post("/share", response_model=dict)
async def share_lead(
    request: LeadShareRequest,
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Share a lead with another user"""
    
    try:
        # Validate lead exists
        lead = db.query(Lead).filter(
            and_(Lead.id == request.lead_id, Lead.is_delete == False)
        ).first()
        
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
        
        # Check if current user can share this lead
        if not can_share_lead(current_user, lead, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to share this lead"
            )
        
        # Validate target user
        target_user = db.query(UserDetails).filter(
            UserDetails.employee_code == request.target_user_id
        ).first()
        
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Target user not found"
            )
        
        # Check if target user can receive leads
        if not can_receive_lead(target_user, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot share lead with this user"
            )
        
        # Check if lead is already assigned to target user
        existing_assignment = db.query(LeadAssignment).filter(
            and_(
                LeadAssignment.lead_id == request.lead_id,
                LeadAssignment.user_id == request.target_user_id
            )
        ).first()
        
        if existing_assignment:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Lead is already assigned to this user"
            )
        
        # Handle ownership transfer
        if request.transfer_ownership:
            # Remove existing assignment
            existing_assignment = db.query(LeadAssignment).filter(
                LeadAssignment.lead_id == request.lead_id
            ).first()
            
            if existing_assignment:
                db.delete(existing_assignment)
        
        # Create new assignment
        new_assignment = LeadAssignment(
            lead_id=request.lead_id,
            user_id=request.target_user_id,
            is_call=False,
            fetched_at=datetime.now()
        )
        
        db.add(new_assignment)
        
        # Add story entry
        share_message = f"Lead {'transferred to' if request.transfer_ownership else 'shared with'} {target_user.name}"
        if request.message:
            share_message += f" - Message: {request.message}"
        
        story = LeadStory(
            lead_id=request.lead_id,
            user_id=current_user.employee_code,
            msg=share_message
        )
        db.add(story)
        
        # Add audit log
        audit_log = AuditLog(
            user_id=current_user.employee_code,
            action="SHARE" if not request.transfer_ownership else "TRANSFER",
            entity="Lead",
            entity_id=str(request.lead_id),
            details={
                "target_user": request.target_user_id,
                "target_name": target_user.name,
                "message": request.message,
                "transfer_ownership": request.transfer_ownership
            }
        )
        db.add(audit_log)
        
        db.commit()
        
        logger.info(f"Lead {request.lead_id} {'transferred' if request.transfer_ownership else 'shared'} "
                   f"from {current_user.employee_code} to {request.target_user_id}")
        
        return {
            "success": True,
            "message": f"Lead successfully {'transferred to' if request.transfer_ownership else 'shared with'} {target_user.name}",
            "lead_id": request.lead_id,
            "shared_with": {
                "employee_code": target_user.employee_code,
                "name": target_user.name,
                "role": target_user.role
            },
            "transfer_ownership": request.transfer_ownership
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error sharing lead: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while sharing lead"
        )

@router.post("/bulk-share", response_model=dict)
async def bulk_share_leads(
    request: BulkLeadShareRequest,
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Share multiple leads with a user"""
    
    try:
        # Validate target user first
        target_user = db.query(UserDetails).filter(
            UserDetails.employee_code == request.target_user_id
        ).first()
        
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Target user not found"
            )
        
        if not can_receive_lead(target_user, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot share leads with this user"
            )
        
        shared_leads = []
        failed_leads = []
        
        for lead_id in request.lead_ids:
            try:
                # Validate lead exists
                lead = db.query(Lead).filter(
                    and_(Lead.id == lead_id, Lead.is_delete == False)
                ).first()
                
                if not lead:
                    failed_leads.append({"lead_id": lead_id, "reason": "Lead not found"})
                    continue
                
                # Check if current user can share this lead
                if not can_share_lead(current_user, lead, db):
                    failed_leads.append({"lead_id": lead_id, "reason": "No permission to share"})
                    continue
                
                # Check if already assigned
                existing_assignment = db.query(LeadAssignment).filter(
                    and_(
                        LeadAssignment.lead_id == lead_id,
                        LeadAssignment.user_id == request.target_user_id
                    )
                ).first()
                
                if existing_assignment:
                    failed_leads.append({"lead_id": lead_id, "reason": "Already assigned to user"})
                    continue
                
                # Handle ownership transfer
                if request.transfer_ownership:
                    existing_assignment = db.query(LeadAssignment).filter(
                        LeadAssignment.lead_id == lead_id
                    ).first()
                    
                    if existing_assignment:
                        db.delete(existing_assignment)
                
                # Create new assignment
                new_assignment = LeadAssignment(
                    lead_id=lead_id,
                    user_id=request.target_user_id,
                    is_call=False,
                    fetched_at=datetime.now()
                )
                
                db.add(new_assignment)
                
                # Add story entry
                share_message = f"Lead {'transferred to' if request.transfer_ownership else 'shared with'} {target_user.name} (Bulk Operation)"
                if request.message:
                    share_message += f" - Message: {request.message}"
                
                story = LeadStory(
                    lead_id=lead_id,
                    user_id=current_user.employee_code,
                    msg=share_message
                )
                db.add(story)
                
                shared_leads.append(lead_id)
                
            except Exception as e:
                failed_leads.append({"lead_id": lead_id, "reason": str(e)})
                continue
        
        # Add bulk audit log
        if shared_leads:
            audit_log = AuditLog(
                user_id=current_user.employee_code,
                action="BULK_SHARE" if not request.transfer_ownership else "BULK_TRANSFER",
                entity="Lead",
                entity_id="bulk",
                details={
                    "target_user": request.target_user_id,
                    "target_name": target_user.name,
                    "message": request.message,
                    "transfer_ownership": request.transfer_ownership,
                    "shared_leads": shared_leads,
                    "failed_leads": failed_leads,
                    "total_requested": len(request.lead_ids),
                    "successful": len(shared_leads),
                    "failed": len(failed_leads)
                }
            )
            db.add(audit_log)
        
        db.commit()
        
        logger.info(f"Bulk share operation: {len(shared_leads)} leads shared, {len(failed_leads)} failed")
        
        return {
            "success": True,
            "message": f"Bulk share completed: {len(shared_leads)} successful, {len(failed_leads)} failed",
            "shared_leads": shared_leads,
            "failed_leads": failed_leads,
            "target_user": {
                "employee_code": target_user.employee_code,
                "name": target_user.name,
                "role": target_user.role
            },
            "transfer_ownership": request.transfer_ownership,
            "summary": {
                "total_requested": len(request.lead_ids),
                "successful": len(shared_leads),
                "failed": len(failed_leads)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error in bulk share: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while bulk sharing leads"
        )

@router.get("/available-users", response_model=List[dict])
async def get_available_users_for_sharing(
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get list of users who can receive shared leads"""
    
    try:
        # Base query for active users
        query = db.query(UserDetails).filter(
            and_(
                UserDetails.is_active == True,
                UserDetails.employee_code != current_user.employee_code
            )
        )
        
        # Filter based on current user's role and hierarchy
        if current_user.role == "SUPERADMIN":
            # SUPERADMIN can share with anyone
            pass
        elif current_user.role == "BRANCH_MANAGER":
            # BRANCH_MANAGER can share within their branch
            if current_user.manages_branch:
                query = query.filter(UserDetails.branch_id == current_user.manages_branch.id)

        
        # Filter by hierarchy level (can only share to same or lower level)
        current_level = current_user.get_hierarchy_level()
        
        users = query.all()
        available_users = []
        
        for user in users:
            if user.get_hierarchy_level() >= current_level:
                available_users.append({
                    "employee_code": user.employee_code,
                    "name": user.name,
                    "role": user.role,
                    "branch_name": user.branch.name if user.branch else None,
                    "hierarchy_level": user.get_hierarchy_level()
                })
        
        return available_users
        
    except Exception as e:
        logger.error(f"Error getting available users: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while fetching available users"
        )

@router.get("/my-shared-leads", response_model=List[dict])
async def get_my_shared_leads(
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get leads that current user has shared with others"""
    
    try:
        # Get audit logs for share/transfer actions by current user
        share_logs = db.query(AuditLog).filter(
            and_(
                AuditLog.user_id == current_user.employee_code,
                AuditLog.action.in_(["SHARE", "TRANSFER", "BULK_SHARE", "BULK_TRANSFER"]),
                AuditLog.entity == "Lead"
            )
        ).order_by(AuditLog.timestamp.desc()).all()
        
        shared_leads = []
        
        for log in share_logs:
            if log.action in ["BULK_SHARE", "BULK_TRANSFER"]:
                # Handle bulk operations
                details = log.details or {}
                shared_leads.append({
                    "type": "bulk",
                    "action": log.action,
                    "timestamp": log.timestamp,
                    "target_user": details.get("target_name"),
                    "target_employee_code": details.get("target_user"),
                    "message": details.get("message"),
                    "transfer_ownership": details.get("transfer_ownership", False),
                    "lead_count": details.get("successful", 0),
                    "details": details
                })
            else:
                # Handle single lead operations
                details = log.details or {}
                lead_id = log.entity_id
                
                # Get lead info
                lead = db.query(Lead).filter(Lead.id == lead_id).first()
                
                shared_leads.append({
                    "type": "single",
                    "action": log.action,
                    "timestamp": log.timestamp,
                    "lead_id": int(lead_id) if lead_id != "bulk" else None,
                    "lead_name": lead.full_name if lead else "Unknown",
                    "target_user": details.get("target_name"),
                    "target_employee_code": details.get("target_user"),
                    "message": details.get("message"),
                    "transfer_ownership": details.get("transfer_ownership", False)
                })
        
        return shared_leads
        
    except Exception as e:
        logger.error(f"Error getting shared leads: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while fetching shared leads"
        )

@router.get("/received-leads", response_model=List[dict])
async def get_received_leads(
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get leads that have been shared with current user"""
    
    try:
        # Get all lead assignments for current user
        assignments = db.query(LeadAssignment).filter(
            LeadAssignment.user_id == current_user.employee_code
        ).order_by(LeadAssignment.fetched_at.desc()).all()
        
        received_leads = []
        
        for assignment in assignments:
            lead = assignment.lead
            if lead and not lead.is_delete:
                # Find who shared this lead (look for recent share stories)
                share_story = db.query(LeadStory).filter(
                    and_(
                        LeadStory.lead_id == lead.id,
                        LeadStory.msg.like(f"%shared with {current_user.name}%")
                    )
                ).order_by(LeadStory.timestamp.desc()).first()
                
                shared_by = None
                shared_at = assignment.fetched_at
                
                if share_story:
                    shared_by_user = db.query(UserDetails).filter(
                        UserDetails.employee_code == share_story.user_id
                    ).first()
                    shared_by = shared_by_user.name if shared_by_user else "Unknown"
                    shared_at = share_story.timestamp
                
                received_leads.append({
                    "lead_id": lead.id,
                    "lead_name": lead.full_name,
                    "lead_mobile": lead.mobile,
                    "lead_email": lead.email,
                    "shared_by": shared_by,
                    "shared_at": shared_at,
                    "is_call": assignment.is_call,
                    "lead_status": lead.lead_status,
                    "branch_name": lead.branch.name if lead.branch else None
                })
        
        return received_leads
        
    except Exception as e:
        logger.error(f"Error getting received leads: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while fetching received leads"
        )
    
    