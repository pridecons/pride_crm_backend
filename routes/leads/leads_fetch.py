from datetime import datetime, date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from db.connection import get_db
from db.models import (
    Lead,
    LeadAssignment,
    LeadFetchConfig,
    LeadFetchHistory,
    UserDetails,
)
from routes.auth.auth_dependency import require_permission
from utils.AddLeadStory import AddLeadStory

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


def get_user_active_assignments_count(
    db: Session, user_id: str, assignment_ttl_hours: int
) -> int:
    """Count active (non‐expired) assignments for a user."""
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=assignment_ttl_hours)
    return (
        db.query(LeadAssignment)
        .filter(
            and_(
                LeadAssignment.user_id == user_id,
                LeadAssignment.fetched_at >= cutoff,
            )
        )
        .count()
    )


def can_user_fetch_leads(
    db: Session, user_id: str, config: LeadFetchConfig
) -> tuple[bool, int]:
    """
    Check last_fetch_limit. Returns (can_fetch, current_active_assignments).
    """
    current = get_user_active_assignments_count(
        db, user_id, config.assignment_ttl_hours
    )
    return (current <= config.last_fetch_limit, current)


def load_fetch_config(db: Session, user: UserDetails) -> tuple[LeadFetchConfig, str]:
    """
    Load LeadFetchConfig in order:
    1) role+branch, 2) role global, 3) branch global, 4) defaults.
    Returns (config, source_string).
    """
    cfg = None
    source = "default"

    # 1️⃣ role+branch
    if user.role and user.branch_id:
        cfg = (
            db.query(LeadFetchConfig)
            .filter_by(role=user.role, branch_id=user.branch_id)
            .first()
        )
        if cfg:
            source = "role_branch"

    # 2️⃣ role global
    if not cfg and user.role:
        cfg = (
            db.query(LeadFetchConfig)
            .filter_by(role=user.role, branch_id=None)
            .first()
        )
        if cfg:
            source = "role_global"

    # 3️⃣ branch global
    if not cfg and user.branch_id:
        cfg = (
            db.query(LeadFetchConfig)
            .filter_by(role=None, branch_id=user.branch_id)
            .first()
        )
        if cfg:
            source = "branch_global"

    # 4️⃣ default mapping
    if not cfg:
        # fallback defaults per role
        defaults = {
            "SUPERADMIN": dict(per_request_limit=100, daily_call_limit=50, last_fetch_limit=10, assignment_ttl_hours=24),
            "BRANCH_MANAGER": dict(per_request_limit=50, daily_call_limit=30, last_fetch_limit=8, assignment_ttl_hours=48),
            "SALES_MANAGER": dict(per_request_limit=30, daily_call_limit=20, last_fetch_limit=6, assignment_ttl_hours=72),
            "TL": dict(per_request_limit=20, daily_call_limit=15, last_fetch_limit=5, assignment_ttl_hours=72),
            "BA": dict(per_request_limit=10, daily_call_limit=10, last_fetch_limit=3, assignment_ttl_hours=168),
            "SBA": dict(per_request_limit=15, daily_call_limit=12, last_fetch_limit=4, assignment_ttl_hours=120),
        }
        role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
        cfg_values = defaults.get(role_str, defaults["BA"])

        class TempConfig:
            def __init__(self, **kw):
                for k, v in kw.items():
                    setattr(self, k, v)

        cfg = TempConfig(**cfg_values)

    return cfg, source


@router.post("/fetch", response_model=dict)
def fetch_leads(
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(require_permission("fetch_lead")),
):
    """
    Fetch leads for the current user based on their role/branch.
    Respects limits, assigns unassigned leads, logs each assignment via AddLeadStory.
    """
    try:
        # ─── Load config & check last_fetch_limit ─────────────────────────────────
        config, cfg_source = load_fetch_config(db, current_user)
        can_fetch, active_count = can_user_fetch_leads(
            db, current_user.employee_code, config
        )
        if not can_fetch:
            return {
                "leads": [],
                "message": f"You have {active_count} active assignments (limit: {config.last_fetch_limit}).",
                "fetched_count": 0,
                "current_assignments": active_count,
                "config_used": {
                    "per_request_limit": config.per_request_limit,
                    "last_fetch_limit": config.last_fetch_limit,
                    "source": cfg_source,
                },
            }

        # ─── Enforce daily_call_limit ───────────────────────────────────────────
        today = date.today()
        hist = (
            db.query(LeadFetchHistory)
            .filter_by(user_id=current_user.employee_code, date=today)
            .first()
        )
        if hist and hist.call_count >= config.daily_call_limit:
            return {
                "leads": [],
                "message": f"Daily fetch limit of {config.daily_call_limit} reached.",
                "fetched_count": 0,
                "current_assignments": active_count,
                "config_used": {
                    "per_request_limit": config.per_request_limit,
                    "last_fetch_limit": config.last_fetch_limit,
                    "source": cfg_source,
                },
            }

        # ─── Find unassigned or expired leads ────────────────────────────────────
        expiry_cutoff = datetime.utcnow() - timedelta(hours=config.assignment_ttl_hours)
        query = db.query(Lead).outerjoin(LeadAssignment)
        query = query.filter(Lead.is_delete == False)
        
        if current_user.branch_id:
            query = query.filter(Lead.branch_id == current_user.branch_id)

        to_fetch = config.per_request_limit
        leads = (
            query.filter(
                or_(
                    LeadAssignment.id == None,
                    LeadAssignment.fetched_at < expiry_cutoff,
                )
            )
            .limit(to_fetch)
            .all()
        )
        if not leads:
            return {
                "leads": [],
                "message": "No leads available at this time",
                "fetched_count": 0,
                "current_assignments": active_count,
                "config_used": {
                    "per_request_limit": config.per_request_limit,
                    "last_fetch_limit": config.last_fetch_limit,
                    "source": cfg_source,
                },
            }

        # ─── Remove expired & assign new ─────────────────────────────────────────
        for lead in leads:
            expired = (
                db.query(LeadAssignment)
                .filter(
                    LeadAssignment.lead_id == lead.id,
                    LeadAssignment.fetched_at < expiry_cutoff,
                )
                .first()
            )
            if expired:
                db.delete(expired)

            # assign if still unassigned
            if not db.query(LeadAssignment).filter_by(lead_id=lead.id).first():
                db.add(LeadAssignment(lead_id=lead.id, user_id=current_user.employee_code))

        # ─── Update daily history ────────────────────────────────────────────────
        if not hist:
            db.add(LeadFetchHistory(user_id=current_user.employee_code, date=today, call_count=1))
        else:
            hist.call_count += 1

        db.commit()

        # ─── Audit each assignment in crm_lead_story ──────────────────────────────
        for lead in leads:
            AddLeadStory(
                lead.id,
                current_user.employee_code,
                f"{current_user.name} ({current_user.employee_code}) fetched this lead"
            )

        # ─── Build response ──────────────────────────────────────────────────────
        response_leads = [
            LeadFetchResponse(
                id=ld.id,
                full_name=ld.full_name,
                email=ld.email,
                mobile=ld.mobile,
                city=ld.city,
                occupation=ld.occupation,
                investment=ld.investment,
                created_at=ld.created_at,
                lead_source_id=ld.lead_source_id,
                lead_response_id=ld.lead_response_id,
            )
            for ld in leads
        ]

        return {
            "leads": response_leads,
            "message": f"Successfully fetched {len(response_leads)} leads",
            "fetched_count": len(response_leads),
            "current_assignments": active_count + len(response_leads),
            "config_used": {
                "per_request_limit": config.per_request_limit,
                "last_fetch_limit": config.last_fetch_limit,
                "source": cfg_source,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching leads: {e}",
        )
