# routes/leads/leads_fetch.py
from datetime import datetime, date, timedelta
from typing import Optional, Tuple, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, or_, exists
from sqlalchemy.orm import Session

from db.connection import get_db
from db.models import (
    Lead,
    LeadAssignment,
    LeadFetchConfig,      # use ORM model from db.models
    LeadFetchHistory,
    UserDetails,
)
from routes.auth.auth_dependency import require_permission
from utils.AddLeadStory import AddLeadStory

router = APIRouter(
    prefix="/leads",
    tags=["leads fetch"],
)

# ----------------- Schemas -----------------
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


# ----------------- Helpers -----------------
def _role_key(role_id) -> Optional[str]:
    """Return a string key for role_id regardless of whether role_id is Enum/int/str/None."""
    if role_id is None:
        return None
    return getattr(role_id, "value", str(role_id))


def _get_user_active_assignments_count(
    db: Session, user_id: str, assignment_ttl_hours: int
) -> int:
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


def _can_user_fetch_leads(
    db: Session, user_id: str, config: LeadFetchConfig
) -> Tuple[bool, int]:
    current = _get_user_active_assignments_count(
        db, user_id, config.assignment_ttl_hours
    )
    # strictly less than limit to allow fetching until exactly at the cap
    return (current < config.last_fetch_limit, current)


def load_fetch_config(db: Session, user: UserDetails) -> Tuple[LeadFetchConfig, str]:
    """
    Determine which LeadFetchConfig to use for the given user.
    Precedence:
      1) (role_id + branch_id) match
      2) (role_id) global
      3) (branch_id) global
      4) in-memory defaults (not persisted)
    Returns (config_object, source_tag)
    """
    cfg = None
    source = "default"

    role_key = _role_key(user.role_id)

    # 1) role_id + branch
    if role_key and user.branch_id is not None:
        cfg = (
            db.query(LeadFetchConfig)
            .filter(
                LeadFetchConfig.role_id == role_key,
                LeadFetchConfig.branch_id == user.branch_id,
            )
            .first()
        )
        if cfg:
            source = "role_branch"

    # 2) role_id global
    if not cfg and role_key:
        cfg = (
            db.query(LeadFetchConfig)
            .filter(
                LeadFetchConfig.role_id == role_key,
                LeadFetchConfig.branch_id.is_(None),
            )
            .first()
        )
        if cfg:
            source = "role_global"

    # 3) branch global
    if not cfg and user.branch_id is not None:
        cfg = (
            db.query(LeadFetchConfig)
            .filter(
                LeadFetchConfig.role_id.is_(None),
                LeadFetchConfig.branch_id == user.branch_id,
            )
            .first()
        )
        if cfg:
            source = "branch_global"

    # 4) fallback defaults (in-memory object)
    if not cfg:
        class _TempCfg:
            per_request_limit = 100
            daily_call_limit = 50
            last_fetch_limit = 10
            assignment_ttl_hours = 24
            old_lead_remove_days = 30

        cfg = _TempCfg()
        source = "memory_default"

    return cfg, source


# Backwards-compatibility alias for older imports:
_load_fetch_config = load_fetch_config


# ----------------- Endpoint -----------------
@router.post("/fetch", response_model=dict)
def fetch_leads(
    db: Session = Depends(get_db),
    # Use an existing permission from PermissionDetails.
    current_user: UserDetails = Depends(require_permission("lead_manage_page")),
):
    """
    Concurrency-safe fetch:
      - Find leads with NO *fresh* assignment (NOT EXISTS subquery),
      - Lock only crm_lead rows (FOR UPDATE OF crm_lead SKIP LOCKED),
      - Create LeadAssignment rows and stamp TTL fields.
    This avoids OUTER JOIN + FOR UPDATE (which Postgres rejects).
    """
    try:
        # 1) Load config + capacity checks
        config, cfg_source = load_fetch_config(db, current_user)
        can_fetch, active_count = _can_user_fetch_leads(
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
                    "daily_call_limit": getattr(config, "daily_call_limit", None),
                    "last_fetch_limit": config.last_fetch_limit,
                    "assignment_ttl_hours": config.assignment_ttl_hours,
                    "source": cfg_source,
                },
            }

        # 2) Remaining capacity based on last_fetch_limit
        remaining_slots = max(0, config.last_fetch_limit - active_count)
        if remaining_slots == 0:
            return {
                "leads": [],
                "message": f"No remaining assignment capacity (limit: {config.last_fetch_limit}).",
                "fetched_count": 0,
                "current_assignments": active_count,
                "config_used": {
                    "per_request_limit": config.per_request_limit,
                    "daily_call_limit": getattr(config, "daily_call_limit", None),
                    "last_fetch_limit": config.last_fetch_limit,
                    "assignment_ttl_hours": config.assignment_ttl_hours,
                    "source": cfg_source,
                },
            }

        # 3) Enforce daily (call) limit
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
                    "daily_call_limit": getattr(config, "daily_call_limit", None),
                    "last_fetch_limit": config.last_fetch_limit,
                    "assignment_ttl_hours": config.assignment_ttl_hours,
                    "source": cfg_source,
                },
            }

        # 4) Determine how many to fetch this call
        fetch_limit = min(config.per_request_limit, remaining_slots)

        # 5) Build NOT EXISTS subquery defining "fresh assignment"
        now = datetime.utcnow()
        expiry_cutoff = now - timedelta(hours=config.assignment_ttl_hours)

        fresh_assignment_exists = (
            db.query(LeadAssignment.id)
            .filter(
                LeadAssignment.lead_id == Lead.id,
                LeadAssignment.fetched_at >= expiry_cutoff,
            )
            .exists()
        )

        # 6) Find candidates WITHOUT any fresh assignment; lock ONLY crm_lead rows
        q = (
            db.query(Lead)
            .filter(Lead.is_delete.is_(False))
            .filter(~fresh_assignment_exists)  # NOT EXISTS fresh assignment
        )

        # Scope to user's branch (if any)
        if current_user.branch_id:
            q = q.filter(Lead.branch_id == current_user.branch_id)

        # Lock rows only from crm_lead, avoid joining anything nullable
        candidates: List[Lead] = (
            q.order_by(Lead.created_at.asc())
            .with_for_update(of=Lead, skip_locked=True)
            .limit(fetch_limit)
            .all()
        )

        if not candidates:
            return {
                "leads": [],
                "message": "No leads available at this time",
                "fetched_count": 0,
                "current_assignments": active_count,
                "config_used": {
                    "per_request_limit": config.per_request_limit,
                    "daily_call_limit": getattr(config, "daily_call_limit", None),
                    "last_fetch_limit": config.last_fetch_limit,
                    "assignment_ttl_hours": config.assignment_ttl_hours,
                    "source": cfg_source,
                },
            }

        # 7) Assign the leads and stamp TTL-related fields
        for lead in candidates:
            # Safety: if a fresh assignment appeared just before our insert (rare), skip
            already_fresh = (
                db.query(LeadAssignment.id)
                .filter(
                    LeadAssignment.lead_id == lead.id,
                    LeadAssignment.fetched_at >= expiry_cutoff,
                )
                .first()
            )
            if already_fresh:
                continue

            # Create/replace assignment for the current user
            existing = db.query(LeadAssignment).filter(LeadAssignment.lead_id == lead.id).first()
            if existing:
                existing.user_id = current_user.employee_code
                existing.fetched_at = now
            else:
                db.add(
                    LeadAssignment(
                        lead_id=lead.id,
                        user_id=current_user.employee_code,
                        fetched_at=now,
                    )
                )

            # Stamp the Lead row with assignee + conversion TTL
            lead.assigned_to_user = current_user.employee_code
            lead.conversion_deadline = now + timedelta(hours=config.assignment_ttl_hours)

        # 8) Update daily call history and commit
        if not hist:
            db.add(
                LeadFetchHistory(
                    user_id=current_user.employee_code,
                    date=today,
                    call_count=1,
                )
            )
        else:
            hist.call_count += 1

        db.commit()

        # 9) Audit trail / story
        for ld in candidates:
            AddLeadStory(
                ld.id,
                current_user.employee_code,
                f"{current_user.name} ({current_user.employee_code}) fetched this lead",
            )

        # 10) Build response
        response_leads = [
            LeadFetchResponse(
                id=ld.id,
                full_name=getattr(ld, "full_name", None),
                email=getattr(ld, "email", None),
                mobile=getattr(ld, "mobile", None),
                city=getattr(ld, "city", None),
                occupation=getattr(ld, "occupation", None),
                investment=getattr(ld, "investment", None),
                created_at=ld.created_at,
                lead_source_id=getattr(ld, "lead_source_id", None),
                lead_response_id=getattr(ld, "lead_response_id", None),
            )
            for ld in candidates
        ]

        return {
            "leads": [l.model_dump() for l in response_leads],
            "message": f"Successfully fetched {len(response_leads)} leads",
            "fetched_count": len(response_leads),
            "current_assignments": active_count + len(response_leads),
            "config_used": {
                "per_request_limit": config.per_request_limit,
                "daily_call_limit": getattr(config, "daily_call_limit", None),
                "last_fetch_limit": config.last_fetch_limit,
                "assignment_ttl_hours": config.assignment_ttl_hours,
                "source": cfg_source,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching leads: {e}",
        )


__all__ = ["router", "load_fetch_config", "_load_fetch_config"]
