# routes/leads/assignments.py

from datetime import datetime, timedelta, timezone, date
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, validator
from sqlalchemy import and_
from sqlalchemy.orm import Session

from db.connection import get_db
from db.models import Lead, LeadAssignment, UserDetails
from routes.auth.auth_dependency import require_permission
from routes.leads.leads_fetch import load_fetch_config
from utils.AddLeadStory import AddLeadStory
import json

router = APIRouter(
    prefix="/leads/assignments",
    tags=["lead assignments"],
)

class LeadOut(BaseModel):
    id: int
    full_name: Optional[str] = None
    director_name: Optional[str] = None
    father_name: Optional[str] = None
    gender: Optional[str] = None
    marital_status: Optional[str] = None
    email: Optional[str] = None
    mobile: Optional[str] = None
    alternate_mobile: Optional[str] = None
    aadhaar: Optional[str] = None
    pan: Optional[str] = None
    gstin: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = None
    dob: Optional[date] = None
    occupation: Optional[str] = None
    segment: Optional[List[str]] = None
    experience: Optional[str] = None
    investment: Optional[str] = None
    profile: Optional[str] = None
    lead_response_id: Optional[int] = None
    lead_source_id: Optional[int] = None
    branch_id: Optional[int] = None
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None
    aadhar_front_pic: Optional[str] = None
    aadhar_back_pic: Optional[str] = None
    pan_pic: Optional[str] = None
    kyc: Optional[bool] = False
    kyc_id: Optional[str] = None
    is_old_lead: Optional[bool] = False
    call_back_date: Optional[datetime] = None
    lead_status: Optional[str] = None
    created_at: datetime
    ft_to_date: Optional[str] = None
    ft_from_date: Optional[str] = None

    @validator('segment', pre=True, always=True)
    def parse_segment(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return parsed if isinstance(parsed, list) else [parsed]
            except json.JSONDecodeError:
                return [v] if v.strip() else None
        if isinstance(v, list):
            return v
        return [str(v)] if v is not None else None

    class Config:
        from_attributes = True  # allow reading attrs directly from SQLAlchemy model

class AssignmentResponse(BaseModel):
    assignment_id: int
    lead_id: int
    lead: LeadOut
    fetched_at: datetime
    expires_at: datetime
    hours_remaining: float

class MyAssignmentsResponse(BaseModel):
    assignments: List[AssignmentResponse]
    total_count: int
    assignment_ttl_hours: int
    can_fetch_new: bool
    last_fetch_limit: int

@router.get("/my", response_model=MyAssignmentsResponse)
def get_my_assignments(
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(require_permission("fetch_lead")),
):
    try:
        config, _ = load_fetch_config(db, current_user)

        now = datetime.now(timezone.utc)
        expiry_cutoff = now - timedelta(hours=config.assignment_ttl_hours)

        assignments = (
            db.query(LeadAssignment)
              .join(Lead)
              .filter(
                  and_(
                      LeadAssignment.user_id == current_user.employee_code,
                      LeadAssignment.fetched_at >= expiry_cutoff
                  )
              )
              .all()
        )

        resp_list: List[AssignmentResponse] = []
        for a in assignments:
            expires_at = a.fetched_at + timedelta(hours=config.assignment_ttl_hours)
            hours_left = (expires_at - now).total_seconds() / 3600

            # Audit trail
            AddLeadStory(
                a.lead_id,
                current_user.employee_code,
                f"{current_user.name} fetched assignment {a.id}"
            )

            # Build nested LeadOut
            lead_out = LeadOut.from_orm(a.lead)

            resp_list.append(AssignmentResponse(
                assignment_id = a.id,
                lead_id       = a.lead_id,
                lead          = lead_out,
                fetched_at    = a.fetched_at,
                expires_at    = expires_at,
                hours_remaining = max(0, hours_left),
            ))

        can_fetch_new = len(resp_list) <= config.last_fetch_limit

        return MyAssignmentsResponse(
            assignments         = resp_list,
            total_count         = len(resp_list),
            assignment_ttl_hours= config.assignment_ttl_hours,
            can_fetch_new       = can_fetch_new,
            last_fetch_limit    = config.last_fetch_limit
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching assignments: {e}"
        )

@router.delete("/{assignment_id}")
def complete_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(require_permission("fetch_lead")),
):
    try:
        assignment = (
            db.query(LeadAssignment)
              .filter(
                  and_(
                      LeadAssignment.id == assignment_id,
                      LeadAssignment.user_id == current_user.employee_code
                  )
              )
              .first()
        )
        if not assignment:
            raise HTTPException(404, "Assignment not found or not owned by you")

        lead_id = assignment.lead_id
        db.delete(assignment)
        db.commit()

        AddLeadStory(
            lead_id,
            current_user.employee_code,
            f"{current_user.name} completed assignment {assignment_id}"
        )

        return {
            "message": "Assignment completed successfully",
            "assignment_id": assignment_id,
            "lead_id": lead_id
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error completing assignment: {e}")

@router.post("/complete-multiple")
def complete_multiple_assignments(
    assignment_ids: List[int],
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(require_permission("fetch_lead")),
):
    try:
        if not assignment_ids:
            raise HTTPException(400, "Assignment IDs list cannot be empty")

        assignments = (
            db.query(LeadAssignment)
              .filter(
                  and_(
                      LeadAssignment.id.in_(assignment_ids),
                      LeadAssignment.user_id == current_user.employee_code
                  )
              )
              .all()
        )
        if len(assignments) != len(assignment_ids):
            raise HTTPException(404, "Some assignments not found or not owned by you")

        completed = []
        for a in assignments:
            completed.append(a.id)
            # audit
            AddLeadStory(
                a.lead_id,
                current_user.employee_code,
                f"{current_user.name} completed assignment {a.id}"
            )
            db.delete(a)

        db.commit()
        return {
            "message": f"Successfully completed {len(completed)} assignments",
            "completed_assignment_ids": completed
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error completing assignments: {e}")
