from datetime import datetime, date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, conint
from sqlalchemy import or_
from sqlalchemy.orm import Session

from db.connection import get_db
from db.models import Lead, LeadAssignment, LeadFetchConfig, LeadFetchHistory, UserDetails

router = APIRouter(
    prefix="/leads",
    tags=["leads fetch"],
)

class FetchRequest(BaseModel):
    count: conint(gt=0)  # must be a positive integer


def load_fetch_config(
    db: Session, user: UserDetails
) -> LeadFetchConfig:
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


@router.post("/fetch", response_model=list[dict])
def fetch_leads(
    request: Request,
    body: FetchRequest,
    db: Session = Depends(get_db),
    user: UserDetails = Depends(get_db),
):
    # Load limits (per-request, daily-call, TTL)
    config = load_fetch_config(db, user)

    # 1. Enforce daily-call limit
    today = date.today()
    hist = (
        db.query(LeadFetchHistory)
        .filter_by(user_id=user.employee_code, date=today)
        .first()
    )
    if hist and hist.call_count >= config.daily_call_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily fetch limit reached",
        )

    # 2. Compute expiry cutoff for “in-flight” assignments
    now = datetime.utcnow()
    expiry_cutoff = now - timedelta(hours=config.assignment_ttl_hours)

    # 3. Query for unassigned OR expired-assigned leads in the user’s branch
    to_fetch = min(body.count, config.per_request_limit)
    leads = (
        db.query(Lead)
        .outerjoin(LeadAssignment)
        .filter(
            Lead.branch_id == user.branch_id,
            or_(
                LeadAssignment.id == None,
                LeadAssignment.fetched_at < expiry_cutoff,
            ),
        )
        .limit(to_fetch)
        .all()
    )

    if not leads:
        return []

    # 4. Delete any expired assignments that we’re reclaiming
    db.query(LeadAssignment) \
      .filter(LeadAssignment.fetched_at < expiry_cutoff) \
      .delete(synchronize_session=False)

    # 5. Assign the leads to this user
    for lead in leads:
        db.add(LeadAssignment(lead_id=lead.id, user_id=user.employee_code))

    # 6. Update or create today’s history record
    if not hist:
        hist = LeadFetchHistory(
            user_id=user.employee_code,
            date=today,
            call_count=1
        )
        db.add(hist)
    else:
        hist.call_count += 1

    # 7. Commit all changes
    db.commit()

    # 8. Return the leads (you may want a proper serializer here)
    return [lead.to_dict() for lead in leads]


