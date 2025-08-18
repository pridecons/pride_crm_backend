# routes/leads/old_leads_fetch.py

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from sqlalchemy.types import Date
from typing import Optional
from datetime import datetime, timedelta, date
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


# ----------------------------- Helpers -----------------------------

def load_fetch_config(db: Session, user: UserDetails):
    """Load fetch config for user from LeadFetchConfig (role/branch), else defaults."""
    cfg = None
    source = "default"

    try:
        # 1) role + branch
        if user.role and user.branch_id:
            cfg = db.query(LeadFetchConfig).filter_by(role=user.role, branch_id=user.branch_id).first()
            if cfg:
                source = "role_branch"

        # 2) role global
        if not cfg and user.role:
            cfg = db.query(LeadFetchConfig).filter_by(role=user.role, branch_id=None).first()
            if cfg:
                source = "role_global"

        # 3) branch global
        if not cfg and user.branch_id:
            cfg = db.query(LeadFetchConfig).filter_by(role=None, branch_id=user.branch_id).first()
            if cfg:
                source = "branch_global"

        # 4) defaults
        if not cfg:
            defaults = {
                "SUPERADMIN": dict(per_request_limit=50, daily_call_limit=30, last_fetch_limit=15,
                                   assignment_ttl_hours=24, old_lead_remove_days=15),
                "BRANCH_MANAGER": dict(per_request_limit=30, daily_call_limit=20, last_fetch_limit=10,
                                       assignment_ttl_hours=48, old_lead_remove_days=20),
                "SALES_MANAGER": dict(per_request_limit=25, daily_call_limit=15, last_fetch_limit=8,
                                      assignment_ttl_hours=72, old_lead_remove_days=25),
                "TL": dict(per_request_limit=20, daily_call_limit=12, last_fetch_limit=6,
                           assignment_ttl_hours=72, old_lead_remove_days=30),
                "BA": dict(per_request_limit=10, daily_call_limit=8, last_fetch_limit=4,
                           assignment_ttl_hours=168, old_lead_remove_days=30),
                "SBA": dict(per_request_limit=15, daily_call_limit=10, last_fetch_limit=5,
                            assignment_ttl_hours=120, old_lead_remove_days=25),
                "HR": dict(per_request_limit=5, daily_call_limit=3, last_fetch_limit=2,
                           assignment_ttl_hours=168, old_lead_remove_days=30),
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


def get_user_active_assignments_count(db: Session, user_id: str, assignment_ttl_hours: int) -> int:
    """Count user's active assignments within TTL."""
    try:
        expiry_cutoff = datetime.utcnow() - timedelta(hours=assignment_ttl_hours)
        return db.query(LeadAssignment).filter(
            and_(
                LeadAssignment.user_id == user_id,
                LeadAssignment.fetched_at >= expiry_cutoff
            )
        ).count()
    except Exception as e:
        logger.error(f"Error getting active assignments count: {e}")
        return 0


def can_user_fetch_leads(db: Session, user_id: str, config):
    """Whether user can fetch more leads per 'last_fetch_limit'."""
    try:
        current_assignments = get_user_active_assignments_count(db, user_id, config.assignment_ttl_hours)
        return current_assignments < config.last_fetch_limit, current_assignments
    except Exception as e:
        logger.error(f"Error checking fetch eligibility: {e}")
        return False, 0


def check_daily_call_limit(db: Session, user_id: str, daily_limit: int):
    """Checks/initializes today's fetch call counter."""
    try:
        today = datetime.utcnow().date()
        hist = db.query(LeadFetchHistory).filter_by(user_id=user_id, date=today).first()
        if not hist:
            return True, 0
        return hist.call_count < daily_limit, hist.call_count
    except Exception as e:
        logger.error(f"Error checking daily limit: {e}")
        return False, 0


# ----------------------------- Routes -----------------------------

@router.post("/fetch", response_model=dict)
def fetch_old_leads(
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(require_permission("fetch_lead"))
):
    """
    Fetch old leads for the current user.
    Only returns leads marked as is_old_lead = True, not deleted, not client.
    Respects per-request, daily, and active-assignment limits.
    """
    try:
        logger.info(f"User {current_user.employee_code} requesting old leads fetch")

        # Load config
        config, cfg_source = load_fetch_config(db, current_user)
        logger.info(f"Using config from: {cfg_source}")

        # Daily call limit
        can_call_today, today_calls = check_daily_call_limit(db, current_user.employee_code, config.daily_call_limit)
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

        # Active assignment cap (last_fetch_limit)
        can_fetch, active_count = can_user_fetch_leads(db, current_user.employee_code, config)
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

        to_fetch = config.per_request_limit
        now = datetime.utcnow()
        expiry_cutoff = now - timedelta(hours=config.assignment_ttl_hours)

        # Select eligible old leads (unassigned or expired assignment, or user's expired conversion)
        query = (
            db.query(Lead)
            .outerjoin(LeadAssignment, LeadAssignment.lead_id == Lead.id)
            .filter(
                and_(
                    Lead.is_old_lead.is_(True),
                    Lead.is_delete.is_(False),
                    Lead.is_client.is_(False),
                    or_(
                        LeadAssignment.id.is_(None),                       # never assigned
                        LeadAssignment.fetched_at < expiry_cutoff,         # expired assignment
                        and_(                                              # or user's own expired conversion assignment
                            Lead.assigned_for_conversion.is_(True),
                            Lead.conversion_deadline.isnot(None),
                            Lead.conversion_deadline < now,
                            Lead.assigned_to_user == current_user.employee_code
                        )
                    )
                )
            )
            .order_by(Lead.response_changed_at.desc().nullslast(), Lead.id.desc())
        )

        # Branch scoping
        if current_user.branch_id:
            query = query.filter(Lead.branch_id == current_user.branch_id)
            logger.info(f"Filtering by branch: {current_user.branch_id}")

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

        assigned_leads = []
        for lead in old_leads:
            try:
                # Remove expired assignment (check against TTL, or expired conversion on the Lead object)
                assignment = db.query(LeadAssignment).filter(LeadAssignment.lead_id == lead.id).first()
                expired_by_ttl = assignment and assignment.fetched_at < expiry_cutoff
                expired_conversion = bool(
                    lead.assigned_for_conversion and lead.conversion_deadline and lead.conversion_deadline < now
                )

                if assignment and (expired_by_ttl or expired_conversion):
                    logger.info(f"Removing expired assignment for lead {lead.id}")
                    db.delete(assignment)
                    assignment = None  # allow re-assignment below

                # Create new assignment if none present
                if not assignment:
                    new_assignment = LeadAssignment(
                        lead_id=lead.id,
                        user_id=current_user.employee_code,
                        fetched_at=now
                    )
                    db.add(new_assignment)
                    assigned_leads.append(lead)

                    # Reset conversion fields if conversion has expired
                    if expired_conversion:
                        logger.info(f"Resetting expired conversion fields for lead {lead.id}")
                        lead.assigned_for_conversion = False
                        lead.assigned_to_user = None
                        lead.conversion_deadline = None

            except Exception as e:
                logger.error(f"Error processing lead {lead.id}: {e}")
                continue

        # Update daily fetch history counter
        today = datetime.utcnow().date()
        hist = db.query(LeadFetchHistory).filter_by(
            user_id=current_user.employee_code,
            date=today
        ).first()
        if not hist:
            hist = LeadFetchHistory(user_id=current_user.employee_code, date=today, call_count=1)
            db.add(hist)
        else:
            hist.call_count += 1

        db.commit()
        logger.info(f"Successfully assigned {len(assigned_leads)} old leads to user {current_user.employee_code}")

        # Add lead stories (ignore failures)
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
    # Filters
    from_date: Optional[date] = Query(None, alias="fromdate", description="Start date YYYY-MM-DD"),
    to_date:   Optional[date] = Query(None, alias="todate",   description="End   date YYYY-MM-DD"),
    search:    Optional[str]  = Query(None, description="Global search on name/email/mobile"),
    response_id: Optional[int] = Query(None, description="Filter by lead_response_id"),
    source_id:   Optional[int] = Query(None, description="Filter by lead_source_id"),

    # Pagination
    skip:  int = Query(0, ge=0,   description="Number of records to skip"),
    limit: int = Query(100, gt=0, description="Max number of records to return"),

    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(require_permission("fetch_lead"))
):
    """
    Get old leads assigned to the current user, with optional filters and pagination.
    NOTE: Uses func.date(...) for date-only filtering to avoid Python date constructor issues.
    """
    try:
        base_q = db.query(Lead).filter(
            Lead.is_old_lead.is_(True),
            Lead.is_delete.is_(False),
            Lead.is_client.is_(False),
            Lead.assigned_to_user == current_user.employee_code
        )

        # ---- Date filters (compare just the date portion) ----
        if from_date and to_date:
            base_q = base_q.filter(func.date(Lead.created_at).between(from_date, to_date))
        elif from_date:
            base_q = base_q.filter(func.date(Lead.created_at) >= from_date)
        elif to_date:
            base_q = base_q.filter(func.date(Lead.created_at) <= to_date)

        # ---- Search filter ----
        if search:
            term = f"%{search.strip()}%"
            base_q = base_q.filter(
                or_(
                    Lead.full_name.ilike(term),
                    Lead.email.ilike(term),
                    Lead.mobile.ilike(term)
                )
            )

        # ---- Response / Source filters ----
        if response_id is not None:
            base_q = base_q.filter(Lead.lead_response_id == response_id)
        if source_id is not None:
            base_q = base_q.filter(Lead.lead_source_id == source_id)

        total_count = base_q.count()

        # Deterministic ordering (most recent first)
        items = (
            base_q
            .order_by(Lead.created_at.desc(), Lead.id.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

        return {
            "assigned_old_leads": items,
            "count": total_count
        }

    except Exception as e:
        logger.error(f"Error getting assigned old leads: {e}")
        raise HTTPException(500, f"Error getting assigned leads: {str(e)}")
