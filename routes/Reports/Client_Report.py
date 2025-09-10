# routes/reports/Client_Report.py
# Details of all fee-paying clients with rich filters + CSV/XLSX export

from __future__ import annotations

import io
import csv
from typing import Optional, List, Dict, Any, Tuple, Literal
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, select, literal

from db.connection import get_db
from db.models import Lead, Payment, UserDetails, LeadAssignment, LeadSource, LeadResponse, BranchDetails
from routes.auth.auth_dependency import get_current_user
from pydantic import BaseModel

from utils.user_tree import get_subordinate_ids

router = APIRouter(prefix="/reports", tags=["Client Reports"])


# ---------- helpers: role/view scoping ----------
def _role(u: UserDetails) -> str:
    return (getattr(u, "role_name", "") or "").upper()

def _branch_id_for_manager(u: UserDetails) -> Optional[int]:
    if getattr(u, "manages_branch", None):
        return u.manages_branch.id
    return u.branch_id

def _allowed_codes_for_employee_scope(
    db: Session,
    current_user: UserDetails,
    view: Literal["self", "team", "all"] = "all",
) -> Optional[List[str]]:
    role = _role(current_user)
    if role in ("SUPERADMIN", "BRANCH_MANAGER"):
        return None
    subs = get_subordinate_ids(db, current_user.employee_code)
    if view == "self":
        return [current_user.employee_code]
    elif view == "team":
        return subs
    else:  # all
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

def _bounds(from_date: Optional[date], to_date: Optional[date], fallback_days: int = 30) -> Tuple[datetime, datetime]:
    if from_date or to_date:
        start = datetime.combine(from_date or (date.today() - timedelta(days=fallback_days)), time.min)
        end = datetime.combine(to_date or date.today(), time.max)
    else:
        end_d = date.today()
        start_d = end_d - timedelta(days=fallback_days)
        start = datetime.combine(start_d, time.min)
        end = datetime.combine(end_d, time.max)
    return start, end


# ---------- column dictionary (internal keys -> label + builder) ----------
# We’ll build rows as dicts using these keys, then allow selecting subset.
COLUMN_MAP = {
    "client_name":          ("Client Name",        lambda r: r.client_name),
    "pan":                  ("PAN",                lambda r: r.pan),
    "registration_date":    ("Registration Date",  lambda r: (r.registration_date.date().isoformat() if r.registration_date else None)),
    "email":                ("Email",              lambda r: r.email),
    "mobile":               ("Mobile",             lambda r: r.mobile),
    "address":              ("Address",            lambda r: r.address),
    "city":                 ("City",               lambda r: r.city),
    "state":                ("State",              lambda r: r.state),
    "pincode":              ("Pincode",            lambda r: r.pincode),
    "fees_collected":       ("Fees Collected",     lambda r: float(r.fees_collected or 0.0)),
    "payments_count":       ("Payments Count",     lambda r: int(r.payments_count or 0)),
    "first_payment_date":   ("First Payment",      lambda r: (r.first_payment_date.date().isoformat() if r.first_payment_date else None)),
    "last_payment_date":    ("Last Payment",       lambda r: (r.last_payment_date.date().isoformat() if r.last_payment_date else None)),
    "product":              ("Product/Service",    lambda r: r.product),
    "service_start":        ("Service Start",      lambda r: r.service_start),
    "service_end":          ("Service End",        lambda r: r.service_end),
    "renewal_date":         ("Renewal Date",       lambda r: r.renewal_date),
    "lead_source":          ("Lead Source",        lambda r: r.lead_source),
    "lead_response":        ("Lead Response",      lambda r: r.lead_response),
    "employee_code":        ("Employee Code",      lambda r: r.employee_code),
    "employee_name":        ("Employee Name",      lambda r: r.employee_name),
    "branch_name":          ("Branch",             lambda r: r.branch_name),
}

DEFAULT_COLUMNS = [
    "client_name", "pan", "registration_date", "email", "mobile",
    "fees_collected", "payments_count", "first_payment_date", "last_payment_date",
    "product", "service_start", "service_end", "renewal_date",
    "lead_source", "lead_response", "employee_code", "employee_name", "branch_name",
]


# ---------- base query builder ----------
def _clients_base_query(
    db: Session,
    current_user: UserDetails,
    *,
    view: Literal["self", "team", "all"],
    from_dt: datetime,
    to_dt: datetime,
    filter_by: Literal["payment_date", "registration_date"] = "payment_date",
    branch_id: Optional[int] = None,
    source_id: Optional[int] = None,
    response_id: Optional[int] = None,
    employee_id: Optional[str] = None,
    profile_id: Optional[int] = None,
    department_id: Optional[int] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    search: Optional[str] = None,
):
    """
    Build an aggregated query of fee-paying clients (leads with PAID payments).
    Group by Lead.id and return labeled columns.
    """

    role = _role(current_user)

    # Start with Lead + joins we need for projection
    q = (
        db.query(
            Lead.id.label("lead_id"),
            Lead.full_name.label("client_name"),
            Lead.pan.label("pan"),
            Lead.created_at.label("registration_date"),
            Lead.email.label("email"),
            Lead.mobile.label("mobile"),
            func.concat_ws(
                ", ",
                func.nullif(Lead.address, ""),
                func.nullif(Lead.city, ""),
                func.nullif(Lead.state, ""),
                func.nullif(Lead.pincode, ""),
            ).label("address"),
            Lead.city.label("city"),
            Lead.state.label("state"),
            Lead.pincode.label("pincode"),
            func.coalesce(func.sum(func.case((Payment.status == "PAID", Payment.paid_amount), else_=0.0)), 0.0).label("fees_collected"),
            func.sum(func.case((Payment.status == "PAID", 1), else_=0)).label("payments_count"),
            func.min(func.case((Payment.status == "PAID", Payment.created_at), else_=None)).label("first_payment_date"),
            func.max(func.case((Payment.status == "PAID", Payment.created_at), else_=None)).label("last_payment_date"),
            func.coalesce(Lead.ft_service_type, "").label("product"),
            Lead.ft_from_date.label("service_start"),
            Lead.ft_to_date.label("service_end"),
            # simplistic renewal: last paid payment date (same as last_payment_date)
            func.max(func.case((Payment.status == "PAID", Payment.created_at), else_=None)).label("renewal_date"),
            LeadSource.name.label("lead_source"),
            LeadResponse.name.label("lead_response"),
            LeadAssignment.user_id.label("employee_code"),
            UserDetails.name.label("employee_name"),
            BranchDetails.name.label("branch_name"),
        )
        .select_from(Lead)
        .join(LeadAssignment, Lead.id == LeadAssignment.lead_id, isouter=True)
        .join(UserDetails, LeadAssignment.user_id == UserDetails.employee_code, isouter=True)
        .join(BranchDetails, Lead.branch_id == BranchDetails.id, isouter=True)
        .join(LeadSource, Lead.lead_source_id == LeadSource.id, isouter=True)
        .join(LeadResponse, Lead.lead_response_id == LeadResponse.id, isouter=True)
        .join(Payment, Lead.id == Payment.lead_id, isouter=True)
        .filter(Lead.is_delete.is_(False))
    )

    # ---- Visibility rules ----
    if role == "SUPERADMIN":
        pass
    elif role == "BRANCH_MANAGER":
        b_id = _branch_id_for_manager(current_user)
        if b_id:
            q = q.filter(Lead.branch_id == b_id)
        else:
            q = q.filter(literal(False))
    else:
        allowed = _allowed_codes_for_employee_scope(db, current_user, view) or []
        if not allowed:
            q = q.filter(literal(False))
        else:
            q = q.filter(
                or_(
                    Lead.assigned_to_user.in_(allowed),
                    _exists_assignment_for_allowed(allowed),
                )
            )

    # ---- Client (fee-paying) filter: at least one PAID payment in window ----
    # Decide date dimension for window
    if filter_by == "registration_date":
        q = q.filter(Lead.created_at >= from_dt, Lead.created_at <= to_dt)
        # ensure paid exists (not necessarily in same window)
        q = q.filter(
            db.query(Payment)
            .filter(Payment.lead_id == Lead.id, Payment.status == "PAID")
            .exists()
        )
    else:  # payment_date
        q = q.filter(Payment.status == "PAID", Payment.created_at >= from_dt, Payment.created_at <= to_dt)

    # ---- Additional filters ----
    if branch_id:
        q = q.filter(Lead.branch_id == branch_id)
    if source_id:
        q = q.filter(Lead.lead_source_id == source_id)
    if response_id:
        q = q.filter(Lead.lead_response_id == response_id)
    if employee_id:
        q = q.filter(
            or_(
                Lead.assigned_to_user == employee_id,
                LeadAssignment.user_id == employee_id,
            )
        )
    if profile_id:
        q = q.filter(UserDetails.role_id == profile_id)
    if department_id and hasattr(UserDetails, "department_id"):
        q = q.filter(UserDetails.department_id == department_id)
    if min_amount is not None:
        q = q.having(func.coalesce(func.sum(func.case((Payment.status == "PAID", Payment.paid_amount), else_=0.0)), 0.0) >= float(min_amount))
    if max_amount is not None:
        q = q.having(func.coalesce(func.sum(func.case((Payment.status == "PAID", Payment.paid_amount), else_=0.0)), 0.0) <= float(max_amount))
    if search:
        t = f"%{search.strip()}%"
        q = q.filter(
            or_(
                Lead.full_name.ilike(t),
                Lead.email.ilike(t),
                Lead.mobile.ilike(t),
                Lead.pan.ilike(t),
                Lead.city.ilike(t),
                Lead.state.ilike(t),
                func.coalesce(Lead.ft_service_type, "").ilike(t),
            )
        )

    # ---- Group by lead to aggregate payments ----
    q = q.group_by(
        Lead.id, Lead.full_name, Lead.pan, Lead.created_at,
        Lead.email, Lead.mobile, Lead.address, Lead.city, Lead.state, Lead.pincode,
        Lead.ft_service_type, Lead.ft_from_date, Lead.ft_to_date,
        LeadSource.name, LeadResponse.name,
        LeadAssignment.user_id, UserDetails.name, BranchDetails.name,
    )

    return q


# ---------- response models ----------
class ClientRow(BaseModel):
    client_name: Optional[str]
    pan: Optional[str]
    registration_date: Optional[str]
    email: Optional[str]
    mobile: Optional[str]
    address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    pincode: Optional[str]
    fees_collected: float
    payments_count: int
    first_payment_date: Optional[str]
    last_payment_date: Optional[str]
    product: Optional[str]
    service_start: Optional[str]
    service_end: Optional[str]
    renewal_date: Optional[str]
    lead_source: Optional[str]
    lead_response: Optional[str]
    employee_code: Optional[str]
    employee_name: Optional[str]
    branch_name: Optional[str]

class ClientReportResponse(BaseModel):
    window: Dict[str, str]
    total: int
    columns: List[str]
    rows: List[ClientRow]


# ---------- utility: rows -> selected columns ----------
def _shape_rows(sql_rows, columns: List[str]) -> List[Dict[str, Any]]:
    shaped = []
    getters = [(col, COLUMN_MAP[col][1]) for col in columns]
    for r in sql_rows:
        item = {}
        for key, fn in getters:
            try:
                item[key] = fn(r)
            except Exception:
                item[key] = None
        shaped.append(item)
    return shaped


# ---------- API: JSON (with pagination) ----------
@router.get("/clients", response_model=ClientReportResponse)
def clients_report(
    # window + dimension
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    days: int = Query(30, ge=1, le=365),
    filter_by: Literal["payment_date", "registration_date"] = Query("payment_date"),
    # filters
    branch_id: Optional[int] = Query(None),
    source_id: Optional[int] = Query(None),
    response_id: Optional[int] = Query(None),
    employee_id: Optional[str] = Query(None),
    profile_id: Optional[int] = Query(None),
    department_id: Optional[int] = Query(None),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None),
    search: Optional[str] = Query(None),
    # visibility
    view: Literal["self","team","all"] = Query("all"),
    # columns
    columns: Optional[List[str]] = Query(None, description=f"Subset of: {', '.join(COLUMN_MAP.keys())}"),
    # paging
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=5000),

    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user),
):
    cols = columns or DEFAULT_COLUMNS
    unknown = [c for c in cols if c not in COLUMN_MAP]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown columns: {unknown}")

    from_dt, to_dt = _bounds(from_date, to_date, days)
    q = _clients_base_query(
        db, current_user,
        view=view, from_dt=from_dt, to_dt=to_dt, filter_by=filter_by,
        branch_id=branch_id, source_id=source_id, response_id=response_id,
        employee_id=employee_id, profile_id=profile_id, department_id=department_id,
        min_amount=min_amount, max_amount=max_amount, search=search,
    )

    total = q.count()
    rows_sql = (
        q.order_by(func.max(func.case((Payment.status == "PAID", Payment.created_at), else_=None)).desc())
         .offset(skip).limit(limit).all()
    )
    shaped = _shape_rows(rows_sql, cols)

    # serialize dates as iso strings if they are datetime objects already handled above
    for row in shaped:
        for k in ("service_start", "service_end", "renewal_date"):
            v = row.get(k)
            if hasattr(v, "isoformat"):
                row[k] = v if isinstance(v, str) else v.isoformat()

    return ClientReportResponse(
        window={"from": from_dt.isoformat(), "to": to_dt.isoformat(), "dimension": filter_by},
        total=total,
        columns=cols,
        rows=[ClientRow(**row) for row in shaped],
    )


# ---------- API: Export CSV / XLSX ----------
@router.get("/clients/export")
def clients_report_export(
    # window + dimension
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    days: int = Query(30, ge=1, le=365),
    filter_by: Literal["payment_date", "registration_date"] = Query("payment_date"),
    # filters
    branch_id: Optional[int] = Query(None),
    source_id: Optional[int] = Query(None),
    response_id: Optional[int] = Query(None),
    employee_id: Optional[str] = Query(None),
    profile_id: Optional[int] = Query(None),
    department_id: Optional[int] = Query(None),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None),
    search: Optional[str] = Query(None),
    # visibility
    view: Literal["self","team","all"] = Query("all"),
    # columns + format
    columns: Optional[List[str]] = Query(None),
    fmt: Literal["csv", "xlsx"] = Query("csv"),

    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user),
):
    cols = columns or DEFAULT_COLUMNS
    unknown = [c for c in cols if c not in COLUMN_MAP]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown columns: {unknown}")

    from_dt, to_dt = _bounds(from_date, to_date, days)
    q = _clients_base_query(
        db, current_user,
        view=view, from_dt=from_dt, to_dt=to_dt, filter_by=filter_by,
        branch_id=branch_id, source_id=source_id, response_id=response_id,
        employee_id=employee_id, profile_id=profile_id, department_id=department_id,
        min_amount=min_amount, max_amount=max_amount, search=search,
    )

    rows_sql = q.order_by(func.max(func.case((Payment.status == "PAID", Payment.created_at), else_=None)).desc()).all()
    shaped = _shape_rows(rows_sql, cols)

    # Friendly headers
    headers = [COLUMN_MAP[c][0] for c in cols]

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(headers)
        for row in shaped:
            writer.writerow([row.get(c, "") for c in cols])
        data = buf.getvalue().encode("utf-8-sig")
        buf.close()
        filename = f"client_report_{date.today().isoformat()}.csv"
        return StreamingResponse(
            io.BytesIO(data),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # xlsx
    try:
        from openpyxl import Workbook
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="XLSX export requires openpyxl. Please install it or use fmt=csv."
        )

    wb = Workbook()
    ws = wb.active
    ws.title = "Clients"
    ws.append(headers)
    for row in shaped:
        ws.append([row.get(c, "") for c in cols])

    for col in ws.columns:
        max_len = 10
        for cell in col:
            try:
                max_len = max(max_len, len(str(cell.value or "")))
            except Exception:
                pass
        idx = col[0].column_letter
        ws.column_dimensions[idx].width = min(max_len + 2, 60)

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    filename = f"client_report_{date.today().isoformat()}.xlsx"
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
