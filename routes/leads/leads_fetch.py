from datetime import datetime, date, timedelta
from typing import Optional, Tuple

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
    lead_source_name: Optional[str] = None   # 👈 NEW
    lead_response_id: Optional[int] = None


from sqlalchemy import and_
from db.models import Lead, LeadAssignment

def get_user_open_assignments_count(
    db: Session, user_id: str, assignment_ttl_hours: int
) -> int:
    """
    Count only those assignments that are still 'open':
    - within TTL
    - assigned to this user
    - and the lead hasn't been worked (lead_response_id IS NULL)
      (Adjust the 'open' definition as needed for your flow.)
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=assignment_ttl_hours)
    return (
        db.query(LeadAssignment)
          .join(Lead, Lead.id == LeadAssignment.lead_id)
          .filter(
              LeadAssignment.user_id == user_id,
              LeadAssignment.fetched_at >= cutoff,
              Lead.assigned_to_user == user_id,
              Lead.lead_response_id.is_(None)   # <-- treat as "not worked yet"
          )
          .count()
    )

# ---------- helpers ----------
def _role_key(role_id) -> Optional[str]:
    """Return a string key for role_id regardless of whether role_id is Enum/int/str/None."""
    if role_id is None:
        return None
    # If Enum-like, use .value; else coerce to str
    return getattr(role_id, "value", str(role_id))


def get_user_active_assignments_count(
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


def can_user_fetch_leads(db: Session, user_id: str, config: LeadFetchConfig) -> Tuple[bool, int]:
    """
    Eligible if OPEN (unworked) assignment count <= last_fetch_limit.
    """
    current_open = get_user_open_assignments_count(db, user_id, config.assignment_ttl_hours)
    return (current_open <= config.last_fetch_limit, current_open)


def load_fetch_config(db: Session, user: UserDetails) -> Tuple[LeadFetchConfig, str]:
    cfg = None
    source = "default"

    role_key = _role_key(user.role_id)

    # 1️⃣ role_id+branch
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

    # 2️⃣ role_id global
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

    # 3️⃣ branch global
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

    # 4️⃣ defaults
    if not cfg:
        cfg_values = {
            "per_request_limit": 100,
            "daily_call_limit": 50,
            "last_fetch_limit": 10,
            "assignment_ttl_hours": 24,
            "old_lead_remove_days": 30,
        }

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
    try:
        # Load config and check per‐user active assignments
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
                    "daily_call_limit": getattr(config, "daily_call_limit", None),  # NEW
                    "last_fetch_limit": config.last_fetch_limit,
                    "source": cfg_source,
                },
            }

        # Remaining capacity based on last_fetch_limit
        remaining_slots = max(0, config.last_fetch_limit - active_count)
        if remaining_slots == 0:
            return {
                "leads": [],
                "message": f"No remaining assignment capacity (limit: {config.last_fetch_limit}).",
                "fetched_count": 0,
                "current_assignments": active_count,
                "config_used": {
                    "per_request_limit": config.per_request_limit,
                    "last_fetch_limit": config.last_fetch_limit,
                    "source": cfg_source,
                },
            }

        # Enforce daily limit (call-count based)
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

        # Determine how many to fetch this call
        fetch_limit = config.per_request_limit

        # Query unassigned or expired leads
        expiry_cutoff = datetime.utcnow() - timedelta(hours=config.assignment_ttl_hours)
        query = db.query(Lead).outerjoin(LeadAssignment).filter(Lead.is_delete == False)
        if current_user.branch_id:
            query = query.filter(Lead.branch_id == current_user.branch_id)

        leads = (
            query.filter(
                or_(
                    LeadAssignment.id == None,
                    LeadAssignment.fetched_at < expiry_cutoff,
                )
            )
            .limit(fetch_limit)
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

        # Assign leads and update Lead fields
        now = datetime.utcnow()
        for lead in leads:
            # Remove expired assignment (if any)
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

            # If still unassigned, assign to current user and stamp fetched_at
            if not db.query(LeadAssignment).filter_by(lead_id=lead.id).first():
                db.add(
                    LeadAssignment(
                        lead_id=lead.id,
                        user_id=current_user.employee_code,
                        fetched_at=now,  # <-- important for TTL logic
                    )
                )
                # also stamp the Lead record
                lead.assigned_to_user = current_user.employee_code
                lead.conversion_deadline = now + timedelta(hours=config.assignment_ttl_hours)

        # Update daily history and commit all changes
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

        # Audit story entries
        for lead in leads:
            AddLeadStory(
                lead.id,
                current_user.employee_code,
                f"{current_user.name} ({current_user.employee_code}) fetched this lead",
            )

        # Build response payload
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
                lead_source_name=getattr(ld.lead_source, "name", None),  # 👈 NEW
                lead_response_id=getattr(ld, "lead_response_id", None),
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


# class LeadFetchConfig(Base):
#     __tablename__ = "crm_lead_fetch_config"
#     id                = Column(Integer, primary_key=True, autoincrement=True)
#     role_id              = Column(String(50), nullable=True)
#     branch_id         = Column(Integer, ForeignKey("crm_branch_details.id"), nullable=True)
#     per_request_limit = Column(Integer, nullable=False)
#     daily_call_limit  = Column(Integer, nullable=False)
#     last_fetch_limit  = Column(Integer, nullable=False)
#     assignment_ttl_hours = Column(Integer, nullable=False, default=24*7)
#     old_lead_remove_days = Column(Integer, nullable=True, default=30)

#     # Add relationship
#     branch = relationship("BranchDetails", foreign_keys=[branch_id])

# per_request_limit ka matlab he ek bar me kitni lead fetch kar skat he je per_request_limit=100 he to ek bar me 100 lead fetch kr skta he
# daily_call_limit ka matlab he 1 din me kitni bar fetch kr skat he jese daily_call_limit = 2 he to 1 din me 2 bar hi fetch kr skta he matlab total 200 lead fetch kr skta he 1 din me 
# last_fetch_limit ka mtlab he ki mene lead fetch kari or sab par kam kar liye or kuch lead bachi uske bad fetch kr skta hu jese last_fetch_limit=5 he to mene 100 lead fetch kari or usme se 95 par kam kr chuka hu or last 5 bachi he to new lead fetch kr skta hu 5 se jyada hui to lead nahi fetch kr paye ga

