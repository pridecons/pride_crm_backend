from datetime import datetime, date, timedelta
from typing import Optional, Tuple, List

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

# ──────────────────────────────────────────────────────────────────────────────
# Response DTO
# ──────────────────────────────────────────────────────────────────────────────
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


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _role_key(role_id) -> Optional[str]:
    """Always return a string key for role_id, whether enum/int/str/None."""
    if role_id is None:
        return None
    return getattr(role_id, "value", str(role_id))


def _active_assignments_count(db: Session, user_id: str, assignment_ttl_hours: int) -> int:
    """
    Count how many leads are *currently assigned and not expired* for this user.
    These are the 'unfinished' leads used by last_fetch_limit.
    """
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


def _can_user_fetch(db: Session, user_id: str, cfg: LeadFetchConfig) -> Tuple[bool, int]:
    """
    True if user has fewer active (unexpired) assignments than last_fetch_limit.
    """
    active = _active_assignments_count(db, user_id, cfg.assignment_ttl_hours)
    return (active < cfg.last_fetch_limit, active)


def _load_fetch_config(db: Session, user: UserDetails) -> Tuple[LeadFetchConfig, str]:
    """
    Resolve config priority:
      1) role_id + branch
      2) role_id global
      3) branch global
      4) default in-memory values
    """
    cfg = None
    source = "default"
    role_key = _role_key(user.role_id)

    # 1) role+branch
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
            return cfg, "role_branch"

    # 2) role global
    if role_key and not cfg:
        cfg = (
            db.query(LeadFetchConfig)
            .filter(
                LeadFetchConfig.role_id == role_key,
                LeadFetchConfig.branch_id.is_(None),
            )
            .first()
        )
        if cfg:
            return cfg, "role_global"

    # 3) branch global
    if user.branch_id is not None and not cfg:
        cfg = (
            db.query(LeadFetchConfig)
            .filter(
                LeadFetchConfig.role_id.is_(None),
                LeadFetchConfig.branch_id == user.branch_id,
            )
            .first()
        )
        if cfg:
            return cfg, "branch_global"

    # 4) defaults (no DB row)
    class _Temp: ...
    cfg = _Temp()
    cfg.per_request_limit = 100     # how many leads per fetch call
    cfg.daily_call_limit = 3       # how many fetch calls per day
    cfg.last_fetch_limit = 10       # max unfinished leads allowed before blocking
    cfg.assignment_ttl_hours = 24   # how long an assignment stays 'active'
    cfg.old_lead_remove_days = 30
    return cfg, source


# ──────────────────────────────────────────────────────────────────────────────
# Endpoint
# ──────────────────────────────────────────────────────────────────────────────
@router.post("/fetch", response_model=dict)
def fetch_leads(
    db: Session = Depends(get_db),
    # NOTE: ensure your Permission enum actually has this key, e.g. "lead_manage_page"
    # or add "fetch_lead" to PermissionDetails. Adjust the string if needed.
    current_user: UserDetails = Depends(require_permission("fetch_lead")),
):
    """
    Fetch leads with 3 guardrails:

    - per_request_limit: how many leads are returned in one call.
    - daily_call_limit: how many times per day the user can call this endpoint.
    - last_fetch_limit: max unfinished (active, unexpired) assignments a user may hold.
                        If active >= last_fetch_limit ⇒ block new fetch.

    A lead becomes "unfinished" for TTL hours (assignment_ttl_hours) from when it was fetched.
    After TTL it is considered expired and becomes fetchable by others again.
    """
    try:
        # 1) Resolve config
        cfg, cfg_source = _load_fetch_config(db, current_user)

        # 2) Enforce outstanding limit (last_fetch_limit)
        ok, active_count = _can_user_fetch(db, current_user.employee_code, cfg)
        if not ok:
            return {
                "leads": [],
                "message": (
                    f"You currently have {active_count} unfinished leads. "
                    f"Reduce them below {cfg.last_fetch_limit} to fetch new leads."
                ),
                "fetched_count": 0,
                "current_assignments": active_count,
                "limits": {
                    "per_request_limit": cfg.per_request_limit,
                    "daily_call_limit": cfg.daily_call_limit,
                    "last_fetch_limit": cfg.last_fetch_limit,
                    "assignment_ttl_hours": cfg.assignment_ttl_hours,
                },
                "config_source": cfg_source,
            }

        # 3) Enforce daily call limit
        today = date.today()
        hist = (
            db.query(LeadFetchHistory)
            .filter_by(user_id=current_user.employee_code, date=today)
            .first()
        )
        calls_used = hist.call_count if hist else 0
        if calls_used >= cfg.daily_call_limit:
            return {
                "leads": [],
                "message": f"Daily fetch limit ({cfg.daily_call_limit}) reached for today.",
                "fetched_count": 0,
                "current_assignments": active_count,
                "limits": {
                    "per_request_limit": cfg.per_request_limit,
                    "daily_call_limit": cfg.daily_call_limit,
                    "last_fetch_limit": cfg.last_fetch_limit,
                    "assignment_ttl_hours": cfg.assignment_ttl_hours,
                },
                "daily_calls_used": calls_used,
                "daily_calls_remaining": 0,
                "config_source": cfg_source,
            }

        # 4) Compute how many we can fetch right now
        #    We must not exceed last_fetch_limit outstanding after this call.
        remaining_slots = max(0, cfg.last_fetch_limit - active_count)
        if remaining_slots == 0:
            return {
                "leads": [],
                "message": f"No remaining assignment capacity (limit: {cfg.last_fetch_limit}).",
                "fetched_count": 0,
                "current_assignments": active_count,
                "limits": {
                    "per_request_limit": cfg.per_request_limit,
                    "daily_call_limit": cfg.daily_call_limit,
                    "last_fetch_limit": cfg.last_fetch_limit,
                    "assignment_ttl_hours": cfg.assignment_ttl_hours,
                },
                "daily_calls_used": calls_used,
                "daily_calls_remaining": max(0, cfg.daily_call_limit - calls_used),
                "config_source": cfg_source,
            }

        fetch_limit = min(cfg.per_request_limit, remaining_slots)

        # 5) Find unassigned or expired leads (scope by branch if user has one)
        expiry_cutoff = datetime.utcnow() - timedelta(hours=cfg.assignment_ttl_hours)
        base_q = db.query(Lead).outerjoin(LeadAssignment).filter(Lead.is_delete.is_(False))
        if current_user.branch_id:
            base_q = base_q.filter(Lead.branch_id == current_user.branch_id)

        candidate_leads: List[Lead] = (
            base_q.filter(
                or_(
                    LeadAssignment.id.is_(None),                      # never assigned
                    LeadAssignment.fetched_at < expiry_cutoff,        # assignment expired
                )
            )
            .order_by(Lead.created_at.asc())  # FIFO-ish
            .limit(fetch_limit)
            .with_for_update(skip_locked=True)  # reduce race conditions
            .all()
        )

        if not candidate_leads:
            return {
                "leads": [],
                "message": "No leads available right now.",
                "fetched_count": 0,
                "current_assignments": active_count,
                "limits": {
                    "per_request_limit": cfg.per_request_limit,
                    "daily_call_limit": cfg.daily_call_limit,
                    "last_fetch_limit": cfg.last_fetch_limit,
                    "assignment_ttl_hours": cfg.assignment_ttl_hours,
                },
                "daily_calls_used": calls_used,
                "daily_calls_remaining": max(0, cfg.daily_call_limit - calls_used),
                "config_source": cfg_source,
            }

        # 6) Assign them to the user; remove any expired assignment first
        now = datetime.utcnow()
        for lead in candidate_leads:
            # purge expired assignment (if any)
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

            # still free? (avoid race)
            already = db.query(LeadAssignment).filter_by(lead_id=lead.id).first()
            if not already:
                db.add(
                    LeadAssignment(
                        lead_id=lead.id,
                        user_id=current_user.employee_code,
                        fetched_at=now,
                    )
                )
                # reflect on the Lead row (useful for quick filters/UX)
                lead.assigned_to_user = current_user.employee_code
                lead.conversion_deadline = now + timedelta(hours=cfg.assignment_ttl_hours)

        # 7) Increment daily call counter and commit
        if not hist:
            db.add(LeadFetchHistory(
                user_id=current_user.employee_code,
                date=today,
                call_count=1
            ))
            calls_used = 1
        else:
            hist.call_count += 1
            calls_used = hist.call_count

        db.commit()

        # 8) Audit message for each fetched lead
        for lead in candidate_leads:
            AddLeadStory(
                lead.id,
                current_user.employee_code,
                f"{current_user.name} ({current_user.employee_code}) fetched this lead",
            )

        # 9) Shape response
        payload_leads = [
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
            for ld in candidate_leads
        ]

        return {
            "leads": payload_leads,
            "message": f"Fetched {len(payload_leads)} lead(s).",
            "fetched_count": len(payload_leads),
            "current_assignments": active_count + len(payload_leads),
            "limits": {
                "per_request_limit": cfg.per_request_limit,
                "daily_call_limit": cfg.daily_call_limit,
                "last_fetch_limit": cfg.last_fetch_limit,
                "assignment_ttl_hours": cfg.assignment_ttl_hours,
            },
            "daily_calls_used": calls_used,
            "daily_calls_remaining": max(0, cfg.daily_call_limit - calls_used),
            "config_source": cfg_source,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching leads: {e}",
        )
