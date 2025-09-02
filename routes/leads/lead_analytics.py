# routes/analytics/lead_analytics.py

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import (
    and_, or_, desc, func, text, case, extract, exists, select, literal
)
from typing import List, Optional, Dict, Any, Tuple, Literal
from datetime import datetime, date, timedelta
from pydantic import BaseModel
from db.connection import get_db
from db.models import (
    Lead, Payment, UserDetails, LeadAssignment,
    BranchDetails, LeadSource, LeadResponse, LeadStory, LeadComment
)
from routes.auth.auth_dependency import get_current_user
from utils.user_tree import get_subordinate_users, get_subordinate_ids

router = APIRouter(prefix="/analytics/leads", tags=["Lead Analytics"])

# ===========================
# Pydantic Models for Responses
# ===========================
class LeadStatsModel(BaseModel):
    total_leads: int
    new_leads_today: int
    new_leads_this_week: int
    new_leads_this_month: int
    assigned_leads: int
    unassigned_leads: int
    called_leads: int
    uncalled_leads: int
    converted_leads: int
    conversion_rate: float

class PaymentStatsModel(BaseModel):
    total_revenue: float
    total_payments: int
    successful_payments: int
    pending_payments: int
    failed_payments: int
    average_payment_amount: float
    revenue_today: float
    revenue_this_week: float
    revenue_this_month: float

class SourceAnalyticsModel(BaseModel):
    source_name: str
    total_leads: int
    converted_leads: int
    conversion_rate: float
    total_revenue: float

class ResponseAnalyticsModel(BaseModel):
    response_name: str
    total_leads: int
    percentage: float

class DailyActivityModel(BaseModel):
    date: str
    leads_created: int
    leads_called: int
    payments_made: int
    revenue: float

class EmployeePerformanceModel(BaseModel):
    employee_code: str
    employee_name: str
    role_id: int
    role_name: Optional[str] = None
    branch_name: Optional[str]
    total_leads: int
    called_leads: int
    converted_leads: int
    total_revenue: float
    conversion_rate: float
    call_rate: float

class EmployeeAnalyticsResponse(BaseModel):
    employee_stats: LeadStatsModel
    payment_stats: PaymentStatsModel
    daily_activity: List[DailyActivityModel]
    source_breakdown: List[SourceAnalyticsModel]
    response_breakdown: List[ResponseAnalyticsModel]
    recent_activities: List[Dict[str, Any]]
    targets_vs_achievement: Dict[str, Any]

class FiltersMeta(BaseModel):
    view: Literal["self", "other", "all"]
    available_views: List[str]
    available_team_members: List[Dict[str, str]] = []
    selected_team_member: Optional[str] = None

class AdminAnalyticsResponse(BaseModel):
    overall_stats: LeadStatsModel
    payment_stats: PaymentStatsModel
    employee_performance: List[EmployeePerformanceModel]
    daily_trends: List[DailyActivityModel]
    source_analytics: List[SourceAnalyticsModel]
    branch_performance: List[Dict[str, Any]]
    top_performers: List[EmployeePerformanceModel]
    filters: Optional[FiltersMeta] = None

class ResponseAnalyticsSummary(BaseModel):
    total_leads: int
    breakdown: List[ResponseAnalyticsModel]

# ===========================
# Helpers
# ===========================
def get_date_range_filter(days: int = 30):
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)
    return start_date, end_date

def calculate_conversion_rate(total_leads: int, converted_leads: int) -> float:
    if total_leads == 0:
        return 0.0
    return round((converted_leads / total_leads) * 100, 2)

def get_employee_leads_query(
    db: Session,
    employee_code: str,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
):
    query = (
        db.query(Lead)
        .join(LeadAssignment, Lead.id == LeadAssignment.lead_id)
        .filter(
            and_(
                LeadAssignment.user_id == employee_code,
                Lead.is_delete.is_(False),
            )
        )
    )
    if date_from:
        query = query.filter(Lead.created_at >= date_from)
    if date_to:
        query = query.filter(Lead.created_at <= date_to)
    return query

def _branch_id_for_manager(u: UserDetails) -> Optional[int]:
    if getattr(u, "manages_branch", None):
        return u.manages_branch.id
    return u.branch_id

def apply_visibility_to_leads(
    db: Session,
    current_user: UserDetails,
    base_leads_q,
    *,
    view: Literal["self", "other", "all"] = "all",
    team_member: Optional[str] = None,
):
    role = (getattr(current_user, "role_name", "") or "").upper()

    if role == "SUPERADMIN":
        return base_leads_q, None

    if role == "BRANCH_MANAGER":
        b_id = _branch_id_for_manager(current_user)
        if b_id is None:
            return base_leads_q.filter(Lead.id == -1), None
        return base_leads_q.filter(Lead.branch_id == b_id), None

    subs: List[str] = get_subordinate_ids(db, current_user.employee_code)
    if view == "self":
        allowed = [current_user.employee_code]
    elif view == "other":
        allowed = [team_member] if (team_member and team_member in subs) else subs
    else:
        allowed = [current_user.employee_code] + subs

    scoped = (
        base_leads_q.join(LeadAssignment, Lead.id == LeadAssignment.lead_id)
        .filter(LeadAssignment.user_id.in_(allowed))
        .distinct()
    )

    subs_users = get_subordinate_users(db, current_user.employee_code)
    filters_meta = FiltersMeta(
        view=view,
        available_views=["self", "other", "all"],
        available_team_members=[
            {
                "employee_code": u.employee_code,
                "name": u.name,
                "role_id": str(u.role_id),
            }
            for u in subs_users
        ],
        selected_team_member=team_member if view == "other" else None,
    )
    return scoped, filters_meta

def apply_visibility_to_payments_from_leads_scope(
    db: Session,
    current_user: UserDetails,
    base_payments_q,
    *,
    view: Literal["self", "other", "all"] = "all",
    team_member: Optional[str] = None,
):
    role = (getattr(current_user, "role_name", "") or "").upper()

    if role == "SUPERADMIN":
        return base_payments_q

    if role == "BRANCH_MANAGER":
        b_id = _branch_id_for_manager(current_user)
        if b_id is None:
            return base_payments_q.filter(Payment.id == -1)
        return base_payments_q.filter(
            or_(
                Payment.branch_id == str(b_id),
                and_(Payment.branch_id == None, Lead.branch_id == b_id),
            )
        )

    subs: List[str] = get_subordinate_ids(db, current_user.employee_code)
    if view == "self":
        allowed = [current_user.employee_code]
    elif view == "other":
        allowed = [team_member] if (team_member and team_member in subs) else subs
    else:
        allowed = [current_user.employee_code] + subs

    if not allowed:
        return base_payments_q.filter(Payment.id == -1)

    return base_payments_q.filter(Payment.user_id.in_(allowed))

def get_admin_leads_query(
    db: Session,
    current_user: UserDetails,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    *,
    view: Literal["self","other","all"] = "all",
    team_member: Optional[str] = None,
) -> Tuple[Any, Optional[FiltersMeta]]:
    q = db.query(Lead).filter(Lead.is_delete.is_(False))
    if date_from:
        q = q.filter(Lead.created_at >= date_from)
    if date_to:
        q = q.filter(Lead.created_at <= date_to)
    q, filters_meta = apply_visibility_to_leads(
        db=db,
        current_user=current_user,
        base_leads_q=q,
        view=view,
        team_member=team_member,
    )
    return q, filters_meta

def _compute_response_analytics_from_leads_query(
    db: Session, leads_base_q
) -> Tuple[int, List[ResponseAnalyticsModel]]:
    leads_subq = (
        leads_base_q.with_entities(
            Lead.id.label("id"),
            Lead.lead_response_id.label("lead_response_id"),
        )
    ).subquery()

    rows = (
        db.query(
            LeadResponse.name.label("response_name"),
            func.count(leads_subq.c.id).label("total_leads"),
        )
        .outerjoin(LeadResponse, leads_subq.c.lead_response_id == LeadResponse.id)
        .group_by(LeadResponse.name)
        .all()
    )

    overall_total = sum(int(r.total_leads or 0) for r in rows) or 0

    breakdown: List[ResponseAnalyticsModel] = []
    for rname, total in rows:
        pct = (float(total) / overall_total * 100.0) if overall_total > 0 else 0.0
        breakdown.append(
            ResponseAnalyticsModel(
                response_name=rname or "No Response",
                total_leads=int(total or 0),
                percentage=round(pct, 2),
            )
        )
    return overall_total, breakdown

# ---------- EXISTS helpers (explicit correlation keeps SQLA happy) ----------
def _exists_any_assignment_for_lead():
    return (
        select(literal(1))
        .select_from(LeadAssignment)
        .where(LeadAssignment.lead_id == Lead.id)
        .correlate(Lead)
        .exists()
    )

def _exists_called_assignment_for_lead():
    return (
        select(literal(1))
        .select_from(LeadAssignment)
        .where(and_(LeadAssignment.lead_id == Lead.id, LeadAssignment.is_call.is_(True)))
        .correlate(Lead)
        .exists()
    )

def _exists_assignment_for_users(user_codes_selectable):
    """
    user_codes_selectable: a selectable that yields one column (employee_code)
    """
    # ensure we have a selectable that can be used in IN (...)
    if hasattr(user_codes_selectable, "c") and "employee_code" in user_codes_selectable.c:
        col_sel = select(user_codes_selectable.c.employee_code)
    else:
        # assume it's already a Select of a single column
        col_sel = user_codes_selectable

    return (
        select(literal(1))
        .select_from(LeadAssignment)
        .where(
            and_(
                LeadAssignment.lead_id == Lead.id,
                LeadAssignment.user_id.in_(col_sel),
            )
        )
        .correlate(Lead)
        .exists()
    )

# ===========================
# Employee Analytics
# ===========================
@router.get("/employee/dashboard", response_model=EmployeeAnalyticsResponse)
async def get_employee_analytics(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start_date, end_date = get_date_range_filter(days)

    leads_query = get_employee_leads_query(
        db, current_user.employee_code, start_date, end_date
    )

    total_leads = leads_query.count()

    today = datetime.now().date()
    new_leads_today = leads_query.filter(func.date(Lead.created_at) == today).count()

    week_start = today - timedelta(days=today.weekday())
    new_leads_this_week = leads_query.filter(Lead.created_at >= week_start).count()

    month_start = today.replace(day=1)
    new_leads_this_month = leads_query.filter(Lead.created_at >= month_start).count()

    assignments_query = db.query(LeadAssignment).filter(
        LeadAssignment.user_id == current_user.employee_code
    )

    assigned_leads = assignments_query.count()
    called_leads = assignments_query.filter(LeadAssignment.is_call.is_(True)).count()
    uncalled_leads = assigned_leads - called_leads

    converted_leads_query = (
        leads_query.join(Payment, Lead.id == Payment.lead_id)
        .filter(Payment.paid_amount > 0)
        .distinct()
    )
    converted_leads = converted_leads_query.count()

    lead_stats = LeadStatsModel(
        total_leads=total_leads,
        new_leads_today=new_leads_today,
        new_leads_this_week=new_leads_this_week,
        new_leads_this_month=new_leads_this_month,
        assigned_leads=assigned_leads,
        unassigned_leads=0,
        called_leads=called_leads,
        uncalled_leads=uncalled_leads,
        converted_leads=converted_leads,
        conversion_rate=calculate_conversion_rate(total_leads, converted_leads),
    )

    payments_query = (
        db.query(Payment)
        .join(Lead, Payment.lead_id == Lead.id)
        .join(LeadAssignment, Lead.id == LeadAssignment.lead_id)
        .filter(
            and_(
                LeadAssignment.user_id == current_user.employee_code,
                Lead.created_at >= start_date,
                Lead.created_at <= end_date,
            )
        )
    )

    total_payments = payments_query.count()
    total_revenue = (
        payments_query.with_entities(func.sum(Payment.paid_amount)).scalar() or 0
    )

    successful_payments = payments_query.filter(Payment.status == "PAID").count()
    pending_payments = payments_query.filter(Payment.status == "ACTIVE").count()
    failed_payments = payments_query.filter(Payment.status == "EXPIRED").count()

    avg_payment = (total_revenue / total_payments) if total_payments > 0 else 0

    revenue_today = (
        payments_query.filter(func.date(Payment.created_at) == today)
        .with_entities(func.sum(Payment.paid_amount))
        .scalar()
        or 0
    )

    revenue_this_week = (
        payments_query.filter(Payment.created_at >= week_start)
        .with_entities(func.sum(Payment.paid_amount))
        .scalar()
        or 0
    )

    revenue_this_month = (
        payments_query.filter(Payment.created_at >= month_start)
        .with_entities(func.sum(Payment.paid_amount))
        .scalar()
        or 0
    )

    payment_stats = PaymentStatsModel(
        total_revenue=float(total_revenue),
        total_payments=total_payments,
        successful_payments=successful_payments,
        pending_payments=pending_payments,
        failed_payments=failed_payments,
        average_payment_amount=float(avg_payment),
        revenue_today=float(revenue_today),
        revenue_this_week=float(revenue_this_week),
        revenue_this_month=float(revenue_this_month),
    )

    daily_activity: List[DailyActivityModel] = []
    for i in range(days):
        activity_date = end_date - timedelta(days=i)

        leads_created = (
            leads_query.filter(func.date(Lead.created_at) == activity_date).count()
        )

        leads_called = (
            db.query(LeadAssignment)
            .join(Lead, LeadAssignment.lead_id == Lead.id)
            .filter(
                and_(
                    LeadAssignment.user_id == current_user.employee_code,
                    LeadAssignment.is_call.is_(True),
                    func.date(LeadAssignment.fetched_at) == activity_date,
                )
            )
            .count()
        )

        day_payments = payments_query.filter(
            func.date(Payment.created_at) == activity_date
        )

        payments_made = day_payments.count()
        revenue = day_payments.with_entities(func.sum(Payment.paid_amount)).scalar() or 0

        daily_activity.append(
            DailyActivityModel(
                date=activity_date.strftime("%Y-%m-%d"),
                leads_created=leads_created,
                leads_called=leads_called,
                payments_made=payments_made,
                revenue=float(revenue),
            )
        )

    daily_activity.reverse()

    source_analytics = (
        db.query(
            LeadSource.name,
            func.count(Lead.id).label("total_leads"),
            func.count(Payment.id).label("converted_leads"),
            func.sum(Payment.paid_amount).label("total_revenue"),
        )
        .select_from(Lead)
        .join(LeadAssignment, Lead.id == LeadAssignment.lead_id)
        .outerjoin(LeadSource, Lead.lead_source_id == LeadSource.id)
        .outerjoin(Payment, Lead.id == Payment.lead_id)
        .filter(
            and_(
                LeadAssignment.user_id == current_user.employee_code,
                Lead.created_at >= start_date,
                Lead.created_at <= end_date,
                Lead.is_delete.is_(False),
            )
        )
        .group_by(LeadSource.name)
        .all()
    )

    source_breakdown: List[SourceAnalyticsModel] = []
    for source_name, total, converted, revenue in source_analytics:
        source_breakdown.append(
            SourceAnalyticsModel(
                source_name=source_name or "Unknown",
                total_leads=int(total or 0),
                converted_leads=int(converted or 0),
                conversion_rate=calculate_conversion_rate(int(total or 0), int(converted or 0)),
                total_revenue=float(revenue or 0),
            )
        )

    response_analytics = (
        db.query(LeadResponse.name, func.count(Lead.id).label("total_leads"))
        .select_from(Lead)
        .join(LeadAssignment, Lead.id == LeadAssignment.lead_id)
        .outerjoin(LeadResponse, Lead.lead_response_id == LeadResponse.id)
        .filter(
            and_(
                LeadAssignment.user_id == current_user.employee_code,
                Lead.created_at >= start_date,
                Lead.created_at <= end_date,
                Lead.is_delete.is_(False),
            )
        )
        .group_by(LeadResponse.name)
        .all()
    )

    response_breakdown: List[ResponseAnalyticsModel] = []
    total_for_percentage = sum(int(count or 0) for _, count in response_analytics) or 0

    for response_name, count in response_analytics:
        pct = (float(count or 0) / total_for_percentage * 100.0) if total_for_percentage > 0 else 0.0
        response_breakdown.append(
            ResponseAnalyticsModel(
                response_name=response_name or "No Response",
                total_leads=int(count or 0),
                percentage=round(pct, 2),
            )
        )

    recent_activities: List[Dict[str, Any]] = []
    recent_stories = (
        db.query(LeadStory)
        .filter(LeadStory.user_id == current_user.employee_code)
        .order_by(desc(LeadStory.timestamp))
        .limit(10)
        .all()
    )

    for story in recent_stories:
        lead = db.query(Lead).filter(Lead.id == story.lead_id).first()
        recent_activities.append(
            {
                "timestamp": story.timestamp.isoformat(),
                "activity": story.msg,
                "lead_name": lead.full_name if lead else "Unknown",
                "lead_id": story.lead_id,
            }
        )

    targets_vs_achievement = {
        "monthly_lead_target": 100,
        "monthly_leads_achieved": new_leads_this_month,
        "monthly_revenue_target": 100000,
        "monthly_revenue_achieved": float(revenue_this_month),
        "achievement_percentage": round((new_leads_this_month / 100) * 100, 2) if 100 > 0 else 0,
    }

    return EmployeeAnalyticsResponse(
        employee_stats=lead_stats,
        payment_stats=payment_stats,
        daily_activity=daily_activity,
        source_breakdown=source_breakdown,
        response_breakdown=response_breakdown,
        recent_activities=recent_activities,
        targets_vs_achievement=targets_vs_achievement,
    )

# ===========================
# Admin Analytics
# ===========================
@router.get("/admin/dashboard", response_model=AdminAnalyticsResponse)
async def get_admin_analytics(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    branch_id: Optional[int] = Query(None, description="Filter by branch ID"),
    view: Literal["self","other","all"] = Query("all", description="Scope for non-managers"),
    team_member: Optional[str] = Query(None, description="When view='other', restrict to this subordinate"),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start_date, end_date = get_date_range_filter(days)

    leads_query, filters_meta = get_admin_leads_query(
        db, current_user, start_date, end_date, view=view, team_member=team_member
    )

    if branch_id:
        leads_query = leads_query.filter(Lead.branch_id == branch_id)

    total_leads = leads_query.count()

    today = datetime.now().date()
    new_leads_today = leads_query.filter(func.date(Lead.created_at) == today).count()

    week_start = today - timedelta(days=today.weekday())
    new_leads_this_week = leads_query.filter(Lead.created_at >= week_start).count()

    month_start = today.replace(day=1)
    new_leads_this_month = leads_query.filter(Lead.created_at >= month_start).count()

    # ---- FIX: use correlated EXISTS (no extra JOIN) ----
    assigned_leads = leads_query.filter(_exists_any_assignment_for_lead()).count()
    called_leads = leads_query.filter(_exists_called_assignment_for_lead()).count()
    unassigned_leads = total_leads - assigned_leads
    uncalled_leads = assigned_leads - called_leads

    converted_leads = (
        leads_query.join(Payment, Lead.id == Payment.lead_id)
        .filter(Payment.paid_amount > 0)
        .distinct()
        .count()
    )

    overall_stats = LeadStatsModel(
        total_leads=total_leads,
        new_leads_today=new_leads_today,
        new_leads_this_week=new_leads_this_week,
        new_leads_this_month=new_leads_this_month,
        assigned_leads=assigned_leads,
        unassigned_leads=unassigned_leads,
        called_leads=called_leads,
        uncalled_leads=uncalled_leads,
        converted_leads=converted_leads,
        conversion_rate=calculate_conversion_rate(total_leads, converted_leads),
    )

    payments_query = db.query(Payment).join(Lead, Payment.lead_id == Lead.id)
    payments_query = apply_visibility_to_payments_from_leads_scope(
        db, current_user, payments_query, view=view, team_member=team_member
    )
    payments_query = payments_query.filter(
        and_(
            Payment.created_at >= start_date,
            Payment.created_at <= end_date,
            Lead.is_delete.is_(False),
        )
    )
    if branch_id:
        payments_query = payments_query.filter(Lead.branch_id == branch_id)

    total_payments = payments_query.count()
    total_revenue = (
        payments_query.with_entities(func.sum(Payment.paid_amount)).scalar() or 0
    )
    successful_payments = payments_query.filter(Payment.status == "PAID").count()
    pending_payments = payments_query.filter(Payment.status == "ACTIVE").count()
    failed_payments = payments_query.filter(Payment.status == "EXPIRED").count()

    avg_payment = (total_revenue / total_payments) if total_payments > 0 else 0

    revenue_today = (
        payments_query.filter(func.date(Payment.created_at) == today)
        .with_entities(func.sum(Payment.paid_amount))
        .scalar()
        or 0
    )

    revenue_this_week = (
        payments_query.filter(Payment.created_at >= week_start)
        .with_entities(func.sum(Payment.paid_amount))
        .scalar()
        or 0
    )
    revenue_this_month = (
        payments_query.filter(Payment.created_at >= month_start)
        .with_entities(func.sum(Payment.paid_amount))
        .scalar()
        or 0
    )

    payment_stats = PaymentStatsModel(
        total_revenue=float(total_revenue),
        total_payments=total_payments,
        successful_payments=successful_payments,
        pending_payments=pending_payments,
        failed_payments=failed_payments,
        average_payment_amount=float(avg_payment),
        revenue_today=float(revenue_today),
        revenue_this_week=float(revenue_this_week),
        revenue_this_month=float(revenue_this_month),
    )

    employees_query = (
        db.query(UserDetails)
        .options(joinedload(UserDetails.branch))
        .filter(UserDetails.is_active.is_(True))
    )
    role = (getattr(current_user, "role_name", "") or "").upper()
    if role == "BRANCH_MANAGER":
        b_id = _branch_id_for_manager(current_user)
        if b_id:
            employees_query = employees_query.filter(UserDetails.branch_id == b_id)
    elif role not in ("SUPERADMIN", "BRANCH_MANAGER"):
        team_codes = [current_user.employee_code] + get_subordinate_ids(db, current_user.employee_code)
        if not team_codes:
            employees_query = employees_query.filter(UserDetails.employee_code == current_user.employee_code)
        else:
            employees_query = employees_query.filter(UserDetails.employee_code.in_(team_codes))

    employees = employees_query.all()

    employee_performance: List[EmployeePerformanceModel] = []
    for employee in employees:
        emp_leads_query = get_employee_leads_query(
            db, employee.employee_code, start_date, end_date
        )
        emp_total_leads = emp_leads_query.count()

        emp_assignments = db.query(LeadAssignment).filter(
            LeadAssignment.user_id == employee.employee_code
        )
        emp_called_leads = emp_assignments.filter(
            LeadAssignment.is_call.is_(True)
        ).count()

        emp_converted_leads = (
            emp_leads_query.join(Payment, Lead.id == Payment.lead_id)
            .filter(Payment.paid_amount > 0)
            .distinct()
            .count()
        )

        emp_revenue = (
            db.query(func.sum(Payment.paid_amount))
            .filter(
                Payment.user_id == employee.employee_code,
                Payment.created_at >= start_date,
                Payment.created_at <= end_date,
                Payment.status == "PAID",
            )
            .scalar()
            or 0
        )

        employee_performance.append(
            EmployeePerformanceModel(
                employee_code=employee.employee_code,
                employee_name=employee.name,
                role_id=int(employee.role_id),
                role_name=getattr(employee, "role_name", None),
                branch_name=employee.branch.name if employee.branch else None,
                total_leads=emp_total_leads,
                called_leads=emp_called_leads,
                converted_leads=emp_converted_leads,
                total_revenue=float(emp_revenue),
                conversion_rate=calculate_conversion_rate(
                    emp_total_leads, emp_converted_leads
                ),
                call_rate=calculate_conversion_rate(emp_total_leads, emp_called_leads),
            )
        )

    daily_trends: List[DailyActivityModel] = []
    for i in range(min(days, 30)):
        trend_date = end_date - timedelta(days=i)

        leads_created = (
            leads_query.filter(func.date(Lead.created_at) == trend_date).count()
        )

        leads_called_count = (
            db.query(LeadAssignment)
            .join(Lead, LeadAssignment.lead_id == Lead.id)
            .filter(
                and_(
                    LeadAssignment.is_call.is_(True),
                    func.date(LeadAssignment.fetched_at) == trend_date,
                    Lead.is_delete.is_(False),
                )
            )
        )
        if branch_id:
            leads_called_count = leads_called_count.filter(Lead.branch_id == branch_id)

        leads_called = leads_called_count.count()

        day_payments = payments_query.filter(func.date(Payment.created_at) == trend_date)

        payments_made = day_payments.count()
        revenue = day_payments.with_entities(func.sum(Payment.paid_amount)).scalar() or 0

        daily_trends.append(
            DailyActivityModel(
                date=trend_date.strftime("%Y-%m-%d"),
                leads_created=leads_created,
                leads_called=leads_called,
                payments_made=payments_made,
                revenue=float(revenue),
            )
        )

    daily_trends.reverse()

    source_analytics_query = (
        db.query(
            LeadSource.name,
            func.count(Lead.id).label("total_leads"),
            func.count(Payment.id).label("converted_leads"),
            func.sum(Payment.paid_amount).label("total_revenue"),
        )
        .select_from(Lead)
        .outerjoin(LeadSource, Lead.lead_source_id == LeadSource.id)
        .outerjoin(Payment, Lead.id == Payment.lead_id)
        .filter(
            and_(
                Lead.created_at >= start_date,
                Lead.created_at <= end_date,
                Lead.is_delete.is_(False),
            )
        )
    )
    if role == "SUPERADMIN":
        pass
    elif role == "BRANCH_MANAGER":
        b_id = _branch_id_for_manager(current_user)
        if b_id:
            source_analytics_query = source_analytics_query.filter(Lead.branch_id == b_id)
    else:
        team_codes = [current_user.employee_code] + get_subordinate_ids(db, current_user.employee_code)
        # Use EXISTS to avoid accidental duplicate joins
        source_analytics_query = source_analytics_query.filter(
            (
                select(literal(1))
                .select_from(LeadAssignment)
                .where(
                    and_(
                        LeadAssignment.lead_id == Lead.id,
                        LeadAssignment.user_id.in_(team_codes if team_codes else [current_user.employee_code]),
                    )
                )
                .correlate(Lead)
                .exists()
            )
        )

    if branch_id:
        source_analytics_query = source_analytics_query.filter(Lead.branch_id == branch_id)

    source_analytics_data = source_analytics_query.group_by(LeadSource.name).all()

    source_analytics: List[SourceAnalyticsModel] = []
    for source_name, total, converted, revenue in source_analytics_data:
        source_analytics.append(
            SourceAnalyticsModel(
                source_name=source_name or "Unknown",
                total_leads=int(total or 0),
                converted_leads=int(converted or 0),
                conversion_rate=calculate_conversion_rate(
                    int(total or 0), int(converted or 0)
                ),
                total_revenue=float(revenue or 0),
            )
        )

    branch_performance: List[Dict[str, Any]] = []
    if role == "SUPERADMIN":
        branches = db.query(BranchDetails).filter(BranchDetails.active.is_(True)).all()

        for branch in branches:
            branch_leads = (
                db.query(Lead)
                .filter(
                    and_(
                        Lead.branch_id == branch.id,
                        Lead.created_at >= start_date,
                        Lead.created_at <= end_date,
                        Lead.is_delete.is_(False),
                    )
                )
                .count()
            )

            branch_revenue = (
                db.query(func.sum(Payment.paid_amount))
                .join(Lead, Payment.lead_id == Lead.id)
                .filter(
                    and_(
                        Lead.branch_id == branch.id,
                        Payment.created_at >= start_date,
                        Payment.created_at <= end_date,
                    )
                )
                .scalar()
                or 0
            )

            branch_converted = (
                db.query(Lead)
                .join(Payment, Lead.id == Payment.lead_id)
                .filter(
                    and_(
                        Lead.branch_id == branch.id,
                        Lead.created_at >= start_date,
                        Lead.created_at <= end_date,
                        Lead.is_delete.is_(False),
                        Payment.paid_amount > 0,
                    )
                )
                .distinct()
                .count()
            )

            branch_performance.append(
                {
                    "branch_id": branch.id,
                    "branch_name": branch.name,
                    "manager_name": branch.manager.name if branch.manager else "No Manager",
                    "total_leads": branch_leads,
                    "converted_leads": branch_converted,
                    "total_revenue": float(branch_revenue),
                    "conversion_rate": calculate_conversion_rate(
                        branch_leads, branch_converted
                    ),
                }
            )

    top_performers = sorted(
        employee_performance,
        key=lambda x: (x.conversion_rate, x.total_revenue),
        reverse=True,
    )[:10]

    return AdminAnalyticsResponse(
        overall_stats=overall_stats,
        payment_stats=payment_stats,
        employee_performance=employee_performance,
        daily_trends=daily_trends,
        source_analytics=source_analytics,
        branch_performance=branch_performance,
        top_performers=top_performers,
        filters=filters_meta,
    )

# ===============================
# Lightweight admin dashboard card
# ===============================
@router.get("/admin/dashboard-card")
async def get_admin_dashboard_card(
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
    branch_id: Optional[int] = Query(None, description="Filter by branch ID"),
    view: Literal["self","other","all"] = Query("all"),
    team_member: Optional[str] = Query(None),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start_date, end_date = get_date_range_filter(days)

    base_q, filters_meta = get_admin_leads_query(
        db, current_user, start_date, end_date, view=view, team_member=team_member
    )
    if branch_id:
        base_q = base_q.filter(Lead.branch_id == branch_id)

    total_leads = base_q.count()
    total_clients = base_q.filter(Lead.is_client.is_(True)).count()
    old_leads = base_q.filter(Lead.is_old_lead.is_(True)).count()
    new_leads = base_q.filter(Lead.is_old_lead.is_(False)).count()

    leads_subq = (
        base_q.with_entities(
            Lead.id.label("id"),
            Lead.lead_source_id.label("lead_source_id"),
            Lead.is_client.label("is_client"),
            Lead.is_old_lead.label("is_old_lead"),
        )
    ).subquery()

    src_stats = (
        db.query(
            LeadSource.id.label("source_id"),
            LeadSource.name.label("source_name"),
            func.count(leads_subq.c.id).label("total_leads"),
            func.sum(case((leads_subq.c.is_client.is_(True), 1), else_=0)).label(
                "total_clients"
            ),
            func.sum(case((leads_subq.c.is_old_lead.is_(True), 1), else_=0)).label(
                "old_leads"
            ),
            func.sum(case((leads_subq.c.is_old_lead.is_(False), 1), else_=0)).label(
                "new_leads"
            ),
        )
        .outerjoin(LeadSource, leads_subq.c.lead_source_id == LeadSource.id)
        .group_by(LeadSource.id, LeadSource.name)
        .all()
    )

    source_wise = [
        {
            "source_id": (src_id if src_id is not None else 0),
            "source_name": (src_name if src_name is not None else "Unknown"),
            "total_leads": int(tl or 0),
            "total_clients": int(tc or 0),
            "old_leads": int(ol or 0),
            "new_leads": int(nl or 0),
        }
        for src_id, src_name, tl, tc, ol, nl in src_stats
    ]

    return {
        "overall": {
            "total_leads": total_leads,
            "total_clients": total_clients,
            "old_leads": old_leads,
            "new_leads": new_leads,
        },
        "source_wise": source_wise,
        "filters": filters_meta,
    }

# ===============================
# Response Analytics APIs
# ===============================
@router.get("/employee/response-analytics", response_model=ResponseAnalyticsSummary)
async def get_employee_response_analytics(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start_date, end_date = get_date_range_filter(days)

    leads_q = get_employee_leads_query(
        db=db,
        employee_code=current_user.employee_code,
        date_from=start_date,
        date_to=end_date,
    ).filter(Lead.is_delete.is_(False))

    total, breakdown = _compute_response_analytics_from_leads_query(db, leads_q)
    return ResponseAnalyticsSummary(total_leads=total, breakdown=breakdown)

@router.get("/admin/response-analytics", response_model=ResponseAnalyticsSummary)
async def get_admin_response_analytics(
    days: int = Query(30, ge=1, le=365, description="Default window if from/to not given"),
    branch_id: Optional[int] = Query(None, description="Filter by branch ID"),
    employee_role: Optional[str] = Query(
        None, description="Filter user-wise by role (numeric id or role name, e.g., 3 or 'TL')"
    ),
    from_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    to_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    source_id: Optional[int] = Query(None, description="Filter by Lead Source ID"),
    user_id: Optional[str] = Query(None, description="Filter by specific employee_code"),
    view: Literal["self","other","all"] = Query("all"),
    team_member: Optional[str] = Query(None),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date

    if from_date or to_date:
        start_date = from_date or (datetime.now().date() - timedelta(days=days))
        end_date = to_date or datetime.now().date()
    else:
        start_date, end_date = get_date_range_filter(days)

    leads_q, _ = get_admin_leads_query(
        db=db,
        current_user=current_user,
        date_from=start_date,
        date_to=end_date,
        view=view,
        team_member=team_member,
    )
    leads_q = leads_q.filter(Lead.is_delete.is_(False))

    if branch_id:
        leads_q = leads_q.filter(Lead.branch_id == branch_id)

    if source_id:
        leads_q = leads_q.filter(Lead.lead_source_id == source_id)

    # Intersect with extra user/role filter WITHOUT re-joining
    if user_id or employee_role:
        emp_q = db.query(UserDetails.employee_code)
        role = (getattr(current_user, "role_name", "") or "").upper()
        if role == "BRANCH_MANAGER" and getattr(current_user, "manages_branch", None):
            emp_q = emp_q.filter(UserDetails.branch_id == current_user.manages_branch.id)
        emp_q = emp_q.filter(UserDetails.is_active.is_(True))

        if employee_role:
            if str(employee_role).isdigit():
                emp_q = emp_q.filter(UserDetails.role_id == int(employee_role))
            else:
                emp_q = emp_q.filter(UserDetails.role_name == employee_role)

        if user_id:
            emp_q = emp_q.filter(UserDetails.employee_code == user_id)

        accessible_users_subq = emp_q.subquery()

        leads_q = leads_q.filter(
            _exists_assignment_for_users(accessible_users_subq)
        )

    total, breakdown = _compute_response_analytics_from_leads_query(db, leads_q)
    return ResponseAnalyticsSummary(total_leads=total, breakdown=breakdown)
