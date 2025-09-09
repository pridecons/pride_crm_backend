from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.connection import get_db
from db.models import Lead, UserDetails
from routes.auth.auth_dependency import get_current_user
from utils.AddLeadStory import AddLeadStory
from routes.notification.notification_service import notification_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/leads",
    tags=["leads transfer"],
)

# --------- helpers ----------
def _role(current_user) -> str:
    return (getattr(current_user, "role_name", "") or "").upper()

class TransferPayload(BaseModel):
    lead_id: int = Field(..., description="Lead ID to transfer")
    employee_id: str = Field(..., description="Target employee_code")

# --------- endpoint ----------
@router.post("/transfer/", status_code=status.HTTP_200_OK)
async def transfer_leads(
    payload: TransferPayload,
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user),
):
    role = _role(current_user)

    # --- fetch lead ---
    lead = (
        db.query(Lead)
        .filter(Lead.id == payload.lead_id, Lead.is_delete.is_(False))
        .first()
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # --- fetch employee (target assignee) ---
    employee = (
        db.query(UserDetails)
        .filter(UserDetails.employee_code == payload.employee_id, UserDetails.is_active.is_(True))
        .first()
    )
    if not employee:
        raise HTTPException(status_code=404, detail="Target employee not found or inactive")

    # --- permissions and scope checks ---
    if role == "SUPERADMIN":
        # can move across branches freely
        pass
    elif role == "BRANCH_MANAGER":
        # manager can only move leads inside their own branch
        if current_user.branch_id is None:
            raise HTTPException(status_code=403, detail="Branch manager has no branch assigned")

        if lead.branch_id != current_user.branch_id:
            raise HTTPException(status_code=403, detail="You can only transfer leads from your branch")

        if employee.branch_id != current_user.branch_id:
            raise HTTPException(status_code=403, detail="You can only transfer leads to employees in your branch")
    else:
        raise HTTPException(status_code=403, detail="You don't have permission to transfer leads")

    # --- no-op check ---
    if lead.assigned_to_user == employee.employee_code and lead.branch_id == employee.branch_id:
        return {
            "message": "No changes; lead already assigned to this user in the same branch.",
            "lead_id": lead.id,
            "assigned_to_user": lead.assigned_to_user,
            "branch_id": lead.branch_id,
        }

    # --- perform transfer ---
    previous_user = lead.assigned_to_user
    previous_branch = lead.branch_id

    lead.assigned_to_user = employee.employee_code
    # Usually a transfer means lead follows the assignee’s branch.
    lead.branch_id = employee.branch_id

    try:
        db.commit()
        db.refresh(lead)

        # Optional: add a story entry for audit
        try:
            AddLeadStory(
                lead.id,
                current_user.employee_code,
                f"Lead transferred from {previous_user or 'UNASSIGNED'} (branch {previous_branch}) "
                f"to {employee.employee_code} (branch {employee.branch_id}) by {current_user.employee_code}"
            )
        except Exception:
            pass

        try:
            title = "Lead Transferred"
            message = (
                f"Lead {lead.id} has been transferred to you "
                f"by {current_user.name or current_user.employee_code}."
            )

            await notification_service.notify(
                user_id=employee.employee_code,
                title=title,
                message=message,
                lead_id=lead.id
            )
        except Exception as e:
            logger.error("Background notification failed: %s", e)


        return {
            "message": "Lead transferred successfully",
            "lead_id": lead.id,
            "from_user": previous_user,
            "to_user": employee.employee_code,
            "from_branch": previous_branch,
            "to_branch": employee.branch_id,
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to transfer lead: {e}")
