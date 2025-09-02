# routes/analytics/dashboard.py
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, select, literal, case
from typing import Optional, List, Dict, Any, Tuple, Literal
from datetime import datetime, date, timedelta, time

from db.connection import get_db
from db.models import (
    Lead, Payment, UserDetails, LeadAssignment,
    BranchDetails, LeadSource, LeadResponse
)
from routes.auth.auth_dependency import get_current_user
from utils.user_tree import get_subordinate_ids, get_subordinate_users

router = APIRouter(prefix="/analytics/leads", tags=["Lead Analytics"])

# ----------------- role helpers + blanks -----------------
def _role(current_user: UserDetails) -> str:
    return (getattr(current_user, "role_name", "") or "").upper()

def _is_employee(current_user: UserDetails) -> bool:
    return _role(current_user) not in ("SUPERADMIN", "BRANCH_MANAGER")

def _blank_dict() -> Dict[str, Any]:
    return {}

def _blank_list() -> List[Any]:
    return []

# ----------------- time/window helpers -----------------
def _week_start_today() -> datetime:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    return datetime.combine(week_start, time.min)

def _month_start_today() -> datetime:
    today = date.today()
    month_start = today.replace(day=1)
    return datetime.combine(month_start, time.min)

def _year_start_today() -> datetime:
    today = date.today()
    year_start = date(today.year, 1, 1)
    return datetime.combine(year_start, time.min)

def _bounds_from_to(
    from_date: Optional[date],
    to_date: Optional[date],
    fallback_days: int = 30
) -> Tuple[datetime, datetime]:
    if from_date or to_date:
        start = datetime.combine(from_date or (date.today() - timedelta(days=fallback_days)), time.min)
        end = datetime.combine(to_date or date.today(), time.max)
    else:
        end_date = date.today()
        start_date = end_date - timedelta(days=fallback_days)
        start = datetime.combine(start_date, time.min)
        end = datetime.combine(end_date, time.max)
    return start, end

# ----------------- visibility helpers -----------------
def _branch_id_for_manager(u: UserDetails) -> Optional[int]:
    if getattr(u, "manages_branch", None):
        return u.manages_branch.id
    return u.branch_id

def _allowed_codes_for_employee_scope(
    db: Session,
    current_user: UserDetails,
    view: Literal["self", "team", "all", "other"] = "all",
) -> Optional[List[str]]:
    """
    SUPERADMIN / BRANCH_MANAGER -> None (no per-user restriction)
    EMPLOYEE:
      - self  -> [me]
      - team/other -> [all my juniors]
      - all   -> [me + all my juniors]
    """
    role = _role(current_user)
    if role in ("SUPERADMIN", "BRANCH_MANAGER"):
        return None

    subs: List[str] = get_subordinate_ids(db, current_user.employee_code)
    if view == "self":
        return [current_user.employee_code]
    elif view in ("team", "other"):
        return subs
    else:  # "all"
        return [current_user.employee_code] + subs

def _exists_assignment_for_allowed(allowed_codes: List[str]):
    if not allowed_codes:
        return literal(False)
    return (
        select(literal(1))
        .select_from(LeadAssignment)
        .where(
            and_(
                LeadAssignment.lead_id == Lead.id,
                LeadAssignment.user_id.in_(allowed_codes),
            )
        )
        .correlate(Lead)
        .exists()
    )

def _scope_leads(
    db: Session,
    current_user: UserDetails,
    *,
    view: Literal["self", "team", "all", "other"] = "all",
    branch_id: Optional[int] = None,
):
    """
    Returns a base leads query scoped by role + view (+ optional branch filter).
    """
    role = _role(current_user)
    q = db.query(Lead).filter(Lead.is_delete.is_(False))

    if role == "SUPERADMIN":
        pass
    elif role == "BRANCH_MANAGER":
        b_id = _branch_id_for_manager(current_user)
        q = q.filter(Lead.branch_id == b_id)
    else:
        allowed = _allowed_codes_for_employee_scope(db, current_user, view) or []
        q = q.filter(
            or_(
                Lead.assigned_to_user.in_(allowed),
                _exists_assignment_for_allowed(allowed),
            )
        )

    if branch_id is not None:
        q = q.filter(Lead.branch_id == branch_id)

    return q

def _scope_payments(
    db: Session,
    current_user: UserDetails,
    *,
    view: Literal["self", "team", "all", "other"] = "all",
    branch_id: Optional[int] = None,
):
    """
    Payments are scoped independently:
      - SUPERADMIN: all
      - BRANCH_MANAGER: via Lead.branch_id
      - EMPLOYEE: Payment.user_id in allowed
    """
    role = _role(current_user)
    q = db.query(Payment).join(Lead, Payment.lead_id == Lead.id)

    if role == "SUPERADMIN":
        pass
    elif role == "BRANCH_MANAGER":
        b_id = _branch_id_for_manager(current_user)
        q = q.filter(Lead.branch_id == b_id)
    else:
        allowed = _allowed_codes_for_employee_scope(db, current_user, view) or []
        if not allowed:
            q = q.filter(literal(False))
        else:
            q = q.filter(Payment.user_id.in_(allowed))

    if branch_id is not None:
        q = q.filter(Lead.branch_id == branch_id)

    return q

def _apply_common_lead_filters(
    q,
    *,
    from_dt: datetime,
    to_dt: datetime,
    source_id: Optional[int],
    response_id: Optional[int],
    profile_id: Optional[int],
    department_id: Optional[int],
    employee_id: Optional[str],
):
    q = q.filter(Lead.created_at >= from_dt, Lead.created_at <= to_dt)

    if source_id:
        q = q.filter(Lead.lead_source_id == source_id)
    if response_id:
        q = q.filter(Lead.lead_response_id == response_id)

    if employee_id:
        # match by LeadAssignment or assigned_to_user
        q = q.filter(
            or_(
                Lead.assigned_to_user == employee_id,
                _exists_assignment_for_allowed([employee_id]),
            )
        )

    if profile_id or department_id:
        # join to assignee's profile if needed
        q = q.outerjoin(UserDetails, Lead.assigned_to_user == UserDetails.employee_code)
        if profile_id:
            q = q.filter(UserDetails.role_id == profile_id)
        if department_id and hasattr(UserDetails, "department_id"):
            q = q.filter(UserDetails.department_id == department_id)

    return q

def _apply_common_payment_filters(
    q,
    *,
    from_dt: datetime,
    to_dt: datetime,
    source_id: Optional[int],
    response_id: Optional[int],
    profile_id: Optional[int],
    department_id: Optional[int],
    employee_id: Optional[str],
):
    q = q.filter(Payment.created_at >= from_dt, Payment.created_at <= to_dt)
    # these require the Lead join already present
    if source_id:
        q = q.filter(Lead.lead_source_id == source_id)
    if response_id:
        q = q.filter(Lead.lead_response_id == response_id)

    if employee_id:
        q = q.filter(Payment.user_id == employee_id)

    if profile_id or department_id:
        q = q.outerjoin(UserDetails, Payment.user_id == UserDetails.employee_code)
        if profile_id:
            q = q.filter(UserDetails.role_id == profile_id)
        if department_id and hasattr(UserDetails, "department_id"):
            q = q.filter(UserDetails.department_id == department_id)

    return q

# ------------------------------
# 1) Payment analytics
# ------------------------------
def payment_analytics(
    db: Session,
    current_user: UserDetails,
    *,
    view: Literal["self", "team", "all", "other"],
    from_dt: datetime,
    to_dt: datetime,
    branch_id: Optional[int],
    source_id: Optional[int],
    response_id: Optional[int],
    profile_id: Optional[int],
    department_id: Optional[int],
    employee_id: Optional[str],
) -> Dict[str, Any]:
    base = _scope_payments(db, current_user, view=view, branch_id=branch_id)
    q = _apply_common_payment_filters(
        base,
        from_dt=from_dt, to_dt=to_dt,
        source_id=source_id, response_id=response_id,
        profile_id=profile_id, department_id=department_id,
        employee_id=employee_id,
    )

    # totals (raised = sum of paid_amount for all rows in window, regardless of status)
    total_raised = q.with_entities(func.coalesce(func.sum(Payment.paid_amount), 0.0)).scalar() or 0.0
    total_paid = (
        q.filter(Payment.status == "PAID")
         .with_entities(func.coalesce(func.sum(Payment.paid_amount), 0.0))
         .scalar() or 0.0
    )

    week_start = _week_start_today()
    month_start = _month_start_today()
    year_start = _year_start_today()

    weekly_paid = (
        q.filter(Payment.status == "PAID", Payment.created_at >= week_start)
         .with_entities(func.coalesce(func.sum(Payment.paid_amount), 0.0))
         .scalar() or 0.0
    )
    monthly_paid = (
        q.filter(Payment.status == "PAID", Payment.created_at >= month_start)
         .with_entities(func.coalesce(func.sum(Payment.paid_amount), 0.0))
         .scalar() or 0.0
    )
    yearly_paid = (
        q.filter(Payment.status == "PAID", Payment.created_at >= year_start)
         .with_entities(func.coalesce(func.sum(Payment.paid_amount), 0.0))
         .scalar() or 0.0
    )

    return {
        "total_paid": float(total_paid),
        "total_raised": float(total_raised),
        "weekly_paid": float(weekly_paid),
        "monthly_paid": float(monthly_paid),
        "yearly_paid": float(yearly_paid),
    }

# ------------------------------
# 2) Lead analytics
# ------------------------------
def lead_analytics(
    db: Session,
    current_user: UserDetails,
    *,
    view: Literal["self", "team", "all", "other"],
    from_dt: datetime,
    to_dt: datetime,
    branch_id: Optional[int],
    source_id: Optional[int],
    response_id: Optional[int],
    profile_id: Optional[int],
    department_id: Optional[int],
    employee_id: Optional[str],
) -> Dict[str, Any]:
    base = _scope_leads(db, current_user, view=view, branch_id=branch_id)
    q = _apply_common_lead_filters(
        base,
        from_dt=from_dt, to_dt=to_dt,
        source_id=source_id, response_id=response_id,
        profile_id=profile_id, department_id=department_id,
        employee_id=employee_id,
    )

    total_uploaded = q.count()

    week_start = _week_start_today().date()
    month_start = _month_start_today().date()

    this_week = q.filter(func.date(Lead.created_at) >= week_start).count()
    this_month = q.filter(func.date(Lead.created_at) >= month_start).count()

    old_leads = q.filter(Lead.is_old_lead.is_(True), Lead.is_client.is_(False)).count()
    fresh_leads = q.filter(Lead.is_old_lead.is_(False), Lead.is_client.is_(False)).count()
    total_clients = q.filter(Lead.is_client.is_(True)).count()

    total_ft = q.filter(
        or_(
            Lead.ft_service_type.isnot(None),
            Lead.ft_from_date.isnot(None),
            Lead.ft_to_date.isnot(None),
        )
    ).count()

    return {
        "total_uploaded": total_uploaded,
        "this_week": this_week,
        "this_month": this_month,
        "old_leads": old_leads,
        "fresh_leads": fresh_leads,
        "total_clients": total_clients,
        "total_ft": total_ft,
    }

# ------------------------------
# 3) Source & Response-wise lead analytics
# ------------------------------
def source_and_response_wise_lead_analytics(
    db: Session,
    current_user: UserDetails,
    *,
    view: Literal["self", "team", "all", "other"],
    from_dt: datetime,
    to_dt: datetime,
    branch_id: Optional[int],
    profile_id: Optional[int],
    department_id: Optional[int],
    employee_id: Optional[str],
) -> Dict[str, Any]:
    # Base leads
    base = _scope_leads(db, current_user, view=view, branch_id=branch_id)
    leads_q = base.filter(Lead.created_at >= from_dt, Lead.created_at <= to_dt)

    if employee_id or profile_id or department_id:
        leads_q = leads_q.outerjoin(UserDetails, Lead.assigned_to_user == UserDetails.employee_code)
        if employee_id:
            leads_q = leads_q.filter(
                or_(
                    Lead.assigned_to_user == employee_id,
                    _exists_assignment_for_allowed([employee_id]),
                )
            )
        if profile_id:
            leads_q = leads_q.filter(UserDetails.role_id == profile_id)
        if department_id and hasattr(UserDetails, "department_id"):
            leads_q = leads_q.filter(UserDetails.department_id == department_id)

    # Source-wise
    src_rows = (
        leads_q
        .outerjoin(LeadSource, Lead.lead_source_id == LeadSource.id)
        .outerjoin(Payment, Lead.id == Payment.lead_id)
        .with_entities(
            LeadSource.name.label("source_name"),
            func.count(Lead.id).label("total_leads"),
            func.count(case((Payment.status == "PAID", 1))).label("paid_rows"),
            func.coalesce(func.sum(case((Payment.status == "PAID", Payment.paid_amount), else_=0.0)), 0.0).label("paid_revenue"),
        )
        .group_by(LeadSource.name)
        .all()
    )

    source_wise = [
        {
            "source_name": r.source_name or "Unknown",
            "total_leads": int(r.total_leads or 0),
            "paid_revenue": float(r.paid_revenue or 0.0),
        }
        for r in src_rows
    ]

    # Response-wise
    resp_rows = (
        leads_q
        .outerjoin(LeadResponse, Lead.lead_response_id == LeadResponse.id)
        .with_entities(
            LeadResponse.name.label("response_name"),
            func.count(Lead.id).label("total_leads"),
        )
        .group_by(LeadResponse.name)
        .all()
    )

    response_wise = [
        {
            "response_name": r.response_name or "No Response",
            "total_leads": int(r.total_leads or 0),
        }
        for r in resp_rows
    ]

    return {
        "source_wise": source_wise,
        "response_wise": response_wise,
    }

# ------------------------------
# 4) Top performance branches
# ------------------------------
def top_performance_branches(
    db: Session,
    current_user: UserDetails,
    *,
    view: Literal["self", "team", "all", "other"],
    from_dt: datetime,
    to_dt: datetime,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    # Only Superadmin list across branches; BM is already scoped to their branch by _scope_payments/_scope_leads
    pay_q = _scope_payments(db, current_user, view=view, branch_id=None)
    pay_q = pay_q.filter(Payment.created_at >= from_dt, Payment.created_at <= to_dt)

    rows = (
        pay_q.join(BranchDetails, Lead.branch_id == BranchDetails.id)
             .filter(Payment.status == "PAID")
             .with_entities(
                 BranchDetails.id.label("branch_id"),
                 BranchDetails.name.label("branch_name"),
                 func.coalesce(func.sum(Payment.paid_amount), 0.0).label("revenue"),
                 func.count(Payment.id).label("paid_count"),
             )
             .group_by(BranchDetails.id, BranchDetails.name)
             .order_by(func.coalesce(func.sum(Payment.paid_amount), 0.0).desc())
             .limit(limit)
             .all()
    )

    # Add conversion rate (leads with at least one PAID payment / total leads) per branch in range
    results = []
    for r in rows:
        total_leads = (
            _scope_leads(db, current_user, view=view, branch_id=r.branch_id)
            .filter(Lead.created_at >= from_dt, Lead.created_at <= to_dt)
            .count()
        )
        converted_leads = (
            _scope_leads(db, current_user, view=view, branch_id=r.branch_id)
            .filter(Lead.created_at >= from_dt, Lead.created_at <= to_dt)
            .join(Payment, Lead.id == Payment.lead_id)
            .filter(Payment.status == "PAID")
            .distinct()
            .count()
        )
        conv_rate = round((converted_leads / total_leads) * 100, 2) if total_leads else 0.0
        results.append({
            "branch_id": r.branch_id,
            "branch_name": r.branch_name,
            "revenue": float(r.revenue or 0.0),
            "paid_count": int(r.paid_count or 0),
            "conversion_rate": conv_rate,
        })
    return results

# ------------------------------
# 5) Top performance employees
# ------------------------------
def top_performance_employee(
    db: Session,
    current_user: UserDetails,
    *,
    view: Literal["self", "team", "all", "other"],
    from_dt: datetime,
    to_dt: datetime,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    # Candidate employees list is already restricted by role
    role = _role(current_user)
    users_q = db.query(UserDetails).filter(UserDetails.is_active.is_(True))
    if role == "BRANCH_MANAGER":
        b_id = _branch_id_for_manager(current_user)
        if b_id:
            users_q = users_q.filter(UserDetails.branch_id == b_id)
    elif role not in ("SUPERADMIN",):
        allowed = _allowed_codes_for_employee_scope(db, current_user, view) or []
        users_q = users_q.filter(UserDetails.employee_code.in_(allowed))

    users = users_q.all()
    out: List[Dict[str, Any]] = []

    for u in users:
        # leads assigned to this user in window
        leads_q = (
            db.query(Lead)
              .join(LeadAssignment, Lead.id == LeadAssignment.lead_id)
              .filter(
                  LeadAssignment.user_id == u.employee_code,
                  Lead.is_delete.is_(False),
                  Lead.created_at >= from_dt,
                  Lead.created_at <= to_dt,
              )
        )
        total_leads = leads_q.count()

        # converted (has paid payment)
        converted = (
            leads_q.join(Payment, Lead.id == Payment.lead_id)
                   .filter(Payment.status == "PAID")
                   .distinct()
                   .count()
        )

        revenue = (
            db.query(func.coalesce(func.sum(Payment.paid_amount), 0.0))
              .filter(
                  Payment.user_id == u.employee_code,
                  Payment.status == "PAID",
                  Payment.created_at >= from_dt,
                  Payment.created_at <= to_dt,
              ).scalar() or 0.0
        )

        conv_rate = round((converted / total_leads) * 100, 2) if total_leads else 0.0

        out.append({
            "employee_code": u.employee_code,
            "employee_name": u.name,
            "role_id": int(u.role_id),
            "role_name": getattr(u, "role_name", None),
            "total_leads": total_leads,
            "converted_leads": converted,
            "total_revenue": float(revenue),
            "conversion_rate": conv_rate,
        })

    # Sort: conversion rate desc, then revenue desc
    out.sort(key=lambda x: (x["conversion_rate"], x["total_revenue"]), reverse=True)
    return out[:limit]

# ------------------------------
# 6) User analytics (compact per-user table)
# ------------------------------
def user_analytics(
    db: Session,
    current_user: UserDetails,
    *,
    view: Literal["self", "team", "all", "other"],
    from_dt: datetime,
    to_dt: datetime,
) -> List[Dict[str, Any]]:
    role = _role(current_user)
    users_q = db.query(UserDetails).filter(UserDetails.is_active.is_(True))
    if role == "BRANCH_MANAGER":
        b_id = _branch_id_for_manager(current_user)
        if b_id:
            users_q = users_q.filter(UserDetails.branch_id == b_id)
    elif role not in ("SUPERADMIN",):
        allowed = _allowed_codes_for_employee_scope(db, current_user, view) or []
        if not allowed:
            return []
        users_q = users_q.filter(UserDetails.employee_code.in_(allowed))

    users = users_q.all()
    rows: List[Dict[str, Any]] = []

    for u in users:
        # leads handled by user
        lq = (
            db.query(Lead)
              .join(LeadAssignment, Lead.id == LeadAssignment.lead_id)
              .filter(
                  LeadAssignment.user_id == u.employee_code,
                  Lead.is_delete.is_(False),
                  Lead.created_at >= from_dt,
                  Lead.created_at <= to_dt,
              )
        )
        total_leads = lq.count()
        converted = (
            lq.join(Payment, Lead.id == Payment.lead_id)
              .filter(Payment.status == "PAID")
              .distinct()
              .count()
        )
        revenue = (
            db.query(func.coalesce(func.sum(Payment.paid_amount), 0.0))
              .filter(
                  Payment.user_id == u.employee_code,
                  Payment.status == "PAID",
                  Payment.created_at >= from_dt,
                  Payment.created_at <= to_dt,
              ).scalar() or 0.0
        )

        rows.append({
            "employee_code": u.employee_code,
            "employee_name": u.name,
            "role_id": int(u.role_id),
            "role_name": getattr(u, "role_name", None),
            "total_leads": total_leads,
            "converted_leads": converted,
            "total_revenue": float(revenue),
        })

    return rows

# ------------------------------
# 7) Profile-wise analytics
# ------------------------------
def profile_wise_analytics(
    db: Session,
    current_user: UserDetails,
    *,
    view: Literal["self", "team", "all", "other"],
    from_dt: datetime,
    to_dt: datetime,
) -> List[Dict[str, Any]]:
    # For employees, limit to their allowed set before grouping
    role = _role(current_user)
    allowed = None
    if role not in ("SUPERADMIN", "BRANCH_MANAGER"):
        allowed = _allowed_codes_for_employee_scope(db, current_user, view) or []

    # join Lead -> UserDetails (assignee) for profile grouping
    q = (
        db.query(
            UserDetails.role_id.label("profile_id"),
            func.count(Lead.id).label("total_leads"),
            func.count(case((Payment.status == "PAID", 1))).label("paid_rows"),
            func.coalesce(func.sum(case((Payment.status == "PAID", Payment.paid_amount), else_=0.0)), 0.0).label("paid_revenue"),
        )
        .select_from(Lead)
        .outerjoin(LeadAssignment, Lead.id == LeadAssignment.lead_id)
        .outerjoin(UserDetails, LeadAssignment.user_id == UserDetails.employee_code)
        .outerjoin(Payment, Lead.id == Payment.lead_id)
        .filter(
            Lead.is_delete.is_(False),
            Lead.created_at >= from_dt,
            Lead.created_at <= to_dt,
        )
    )

    if allowed is not None:
        q = q.filter(LeadAssignment.user_id.in_(allowed))

    rows = q.group_by(UserDetails.role_id).all()

    return [
        {
            "profile_id": int(r.profile_id) if r.profile_id is not None else None,
            "total_leads": int(r.total_leads or 0),
            "paid_revenue": float(r.paid_revenue or 0.0),
        }
        for r in rows
    ]

# ------------------------------
# 8) Department-wise analytics
# ------------------------------
def department_wise_analytics(
    db: Session,
    current_user: UserDetails,
    *,
    view: Literal["self", "team", "all", "other"],
    from_dt: datetime,
    to_dt: datetime,
) -> List[Dict[str, Any]]:
    if not hasattr(UserDetails, "department_id"):
        return []

    role = _role(current_user)
    allowed = None
    if role not in ("SUPERADMIN", "BRANCH_MANAGER"):
        allowed = _allowed_codes_for_employee_scope(db, current_user, view) or []

    q = (
        db.query(
            UserDetails.department_id.label("department_id"),
            func.count(Lead.id).label("total_leads"),
            func.coalesce(func.sum(case((Payment.status == "PAID", Payment.paid_amount), else_=0.0)), 0.0).label("paid_revenue"),
        )
        .select_from(Lead)
        .outerjoin(LeadAssignment, Lead.id == LeadAssignment.lead_id)
        .outerjoin(UserDetails, LeadAssignment.user_id == UserDetails.employee_code)
        .outerjoin(Payment, Lead.id == Payment.lead_id)
        .filter(
            Lead.is_delete.is_(False),
            Lead.created_at >= from_dt,
            Lead.created_at <= to_dt,
        )
    )

    if allowed is not None:
        q = q.filter(LeadAssignment.user_id.in_(allowed))

    rows = q.group_by(UserDetails.department_id).all()

    return [
        {
            "department_id": int(r.department_id) if r.department_id is not None else None,
            "total_leads": int(r.total_leads or 0),
            "paid_revenue": float(r.paid_revenue or 0.0),
        }
        for r in rows
    ]

# ------------------------------
# Public endpoints
# ------------------------------
def _resolved_view(v: str) -> Literal["self","team","all","other"]:
    v = (v or "all").lower()
    return "team" if v == "other" else v  # allow old naming

@router.get("/dashboard")
def dashboard(
    # time window
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    days: int = Query(30, ge=1, le=365),

    # filters
    branch_id: Optional[int] = Query(None),
    source_id: Optional[int] = Query(None),
    response_id: Optional[int] = Query(None),
    profile_id: Optional[int] = Query(None),
    department_id: Optional[int] = Query(None),
    employee_id: Optional[str] = Query(None),

    # visibility
    view: Literal["self","team","all","other"] = Query("all"),

    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from_dt, to_dt = _bounds_from_to(from_date, to_date, days)
    v_req = _resolved_view(view)
    role = _role(current_user)

    # Employees: force "team" for users table
    v_for_users = "team" if _is_employee(current_user) else v_req

    payments = payment_analytics(
        db, current_user,
        view=v_req, from_dt=from_dt, to_dt=to_dt,
        branch_id=branch_id,
        source_id=source_id, response_id=response_id,
        profile_id=profile_id, department_id=department_id,
        employee_id=employee_id,
    )

    leads = lead_analytics(
        db, current_user,
        view=v_req, from_dt=from_dt, to_dt=to_dt,
        branch_id=branch_id,
        source_id=source_id, response_id=response_id,
        profile_id=profile_id, department_id=department_id,
        employee_id=employee_id,
    )

    src_resp = source_and_response_wise_lead_analytics(
        db, current_user,
        view=v_req, from_dt=from_dt, to_dt=to_dt,
        branch_id=branch_id,
        profile_id=profile_id, department_id=department_id,
        employee_id=employee_id,
    )

    # top branches: admin only
    branches = top_performance_branches(
        db, current_user,
        view=v_req, from_dt=from_dt, to_dt=to_dt, limit=10,
    ) if role == "SUPERADMIN" else _blank_list()

    # top employees: employees limited to 5
    emp_limit = 5 if _is_employee(current_user) else 10
    employees = top_performance_employee(
        db, current_user,
        view=v_req, from_dt=from_dt, to_dt=to_dt, limit=emp_limit,
    )

    # users table: employees forced to team view
    users = user_analytics(
        db, current_user,
        view=v_for_users, from_dt=from_dt, to_dt=to_dt,
    )

    # profile/department: admin & BM only
    profiles = profile_wise_analytics(
        db, current_user,
        view=v_req, from_dt=from_dt, to_dt=to_dt,
    ) if role in ("SUPERADMIN","BRANCH_MANAGER") else _blank_list()

    departments = department_wise_analytics(
        db, current_user,
        view=v_req, from_dt=from_dt, to_dt=to_dt,
    ) if role in ("SUPERADMIN","BRANCH_MANAGER") else _blank_list()

    return {
        "window": {"from": from_dt.isoformat(), "to": to_dt.isoformat()},
        "filters": {
            "branch_id": branch_id,
            "source_id": source_id,
            "response_id": response_id,
            "profile_id": profile_id,
            "department_id": department_id,
            "employee_id": employee_id,
            "view": v_req,
        },
        "cards": {
            "payments": payments,
            "leads": leads,
        },
        "breakdowns": {
            "source_and_response": src_resp,
            "profile_wise": profiles,
            "department_wise": departments,
        },
        "top": {
            "branches": branches,
            "employees": employees,
        },
        "users": users,
    }

# ——— Individual endpoints (each function separately exposed) ———

# show admin, branch manager, employee
@router.get("/payments")
def payment_card(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    days: int = Query(30, ge=1, le=365),
    branch_id: Optional[int] = Query(None),
    source_id: Optional[int] = Query(None),
    response_id: Optional[int] = Query(None),
    profile_id: Optional[int] = Query(None),
    department_id: Optional[int] = Query(None),
    employee_id: Optional[str] = Query(None),
    view: Literal["self","team","all","other"] = Query("all"),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from_dt, to_dt = _bounds_from_to(from_date, to_date, days)
    return payment_analytics(
        db, current_user,
        view=_resolved_view(view), from_dt=from_dt, to_dt=to_dt,
        branch_id=branch_id,
        source_id=source_id, response_id=response_id,
        profile_id=profile_id, department_id=department_id,
        employee_id=employee_id,
    )

# show admin, branch manager, employee
@router.get("/leads-card")
def leads_card(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    days: int = Query(30, ge=1, le=365),
    branch_id: Optional[int] = Query(None),
    source_id: Optional[int] = Query(None),
    response_id: Optional[int] = Query(None),
    profile_id: Optional[int] = Query(None),
    department_id: Optional[int] = Query(None),
    employee_id: Optional[str] = Query(None),
    view: Literal["self","team","all","other"] = Query("all"),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from_dt, to_dt = _bounds_from_to(from_date, to_date, days)
    return lead_analytics(
        db, current_user,
        view=_resolved_view(view), from_dt=from_dt, to_dt=to_dt,
        branch_id=branch_id,
        source_id=source_id, response_id=response_id,
        profile_id=profile_id, department_id=department_id,
        employee_id=employee_id,
    )

# show admin, branch manager, employee
@router.get("/source-response")
def source_response_breakdown(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    days: int = Query(30, ge=1, le=365),
    branch_id: Optional[int] = Query(None),
    profile_id: Optional[int] = Query(None),
    department_id: Optional[int] = Query(None),
    employee_id: Optional[str] = Query(None),
    view: Literal["self","team","all","other"] = Query("all"),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from_dt, to_dt = _bounds_from_to(from_date, to_date, days)
    return source_and_response_wise_lead_analytics(
        db, current_user,
        view=_resolved_view(view), from_dt=from_dt, to_dt=to_dt,
        branch_id=branch_id,
        profile_id=profile_id, department_id=department_id,
        employee_id=employee_id,
    )

# show only admin
@router.get("/top-branches")
def top_branches(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    days: int = Query(30, ge=1, le=365),
    view: Literal["self","team","all","other"] = Query("all"),
    limit: int = Query(10, ge=1, le=50),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if _role(current_user) != "SUPERADMIN":
        return _blank_list()
    from_dt, to_dt = _bounds_from_to(from_date, to_date, days)
    return top_performance_branches(
        db, current_user,
        view=_resolved_view(view), from_dt=from_dt, to_dt=to_dt, limit=limit,
    )

# show admin, branch manager, employee (employee ko top 5 dikhenge)
@router.get("/top-employees")
def top_employees(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    days: int = Query(30, ge=1, le=365),
    view: Literal["self","team","all","other"] = Query("all"),
    limit: int = Query(10, ge=1, le=100),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if _is_employee(current_user):
        limit = min(limit, 5)
    from_dt, to_dt = _bounds_from_to(from_date, to_date, days)
    return top_performance_employee(
        db, current_user,
        view=_resolved_view(view), from_dt=from_dt, to_dt=to_dt, limit=limit,
    )

# show admin, branch manager, employee (employee ko uski team ke hi dikhe)
@router.get("/users")
def users_table(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    days: int = Query(30, ge=1, le=365),
    view: Literal["self","team","all","other"] = Query("all"),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    forced_view = "team" if _is_employee(current_user) else _resolved_view(view)
    from_dt, to_dt = _bounds_from_to(from_date, to_date, days)
    return user_analytics(
        db, current_user,
        view=forced_view, from_dt=from_dt, to_dt=to_dt,
    )

# show admin, branch manager
@router.get("/profiles")
def profiles_table(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    days: int = Query(30, ge=1, le=365),
    view: Literal["self","team","all","other"] = Query("all"),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if _is_employee(current_user):
        return _blank_list()
    from_dt, to_dt = _bounds_from_to(from_date, to_date, days)
    return profile_wise_analytics(
        db, current_user,
        view=_resolved_view(view), from_dt=from_dt, to_dt=to_dt,
    )

# show admin, branch manager
@router.get("/departments")
def departments_table(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    days: int = Query(30, ge=1, le=365),
    view: Literal["self","team","all","other"] = Query("all"),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if _is_employee(current_user):
        return _blank_list()
    from_dt, to_dt = _bounds_from_to(from_date, to_date, days)
    return department_wise_analytics(
        db, current_user,
        view=_resolved_view(view), from_dt=from_dt, to_dt=to_dt,
    )
