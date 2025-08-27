import logging
from datetime import datetime, date
from typing import Any, Optional, List, Union, Dict
from fastapi import (
    APIRouter,
    HTTPException,
    status,
    Depends,
    Query,
)
from httpx import AsyncClient
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from pydantic import BaseModel, ConfigDict

from config import CASHFREE_APP_ID, CASHFREE_SECRET_KEY
from db.connection import get_db
from db.models import Payment, Lead, UserDetails
from db.Schema.payment import  PaymentOut  # keep using your existing request types
from routes.auth.auth_dependency import get_current_user
from sqlalchemy.exc import SQLAlchemyError
from config import PAYMENT_LIMIT


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payment", tags=["payment"])

# Cashfree helpers
def _base_url() -> str:
    return "https://api.cashfree.com/pg"

def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "x-client-id": CASHFREE_APP_ID,
        "x-client-secret": CASHFREE_SECRET_KEY,
        "x-api-version": "2022-01-01",
    }

async def _call_cashfree(method: str, path: str, json_data: Optional[dict] = None) -> dict:
    url = _base_url() + path
    headers = _headers()
    async with AsyncClient(timeout=30.0) as client:
        resp = await client.request(method, url, headers=headers, json=json_data)
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Resource not found: {path}")
    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid Cashfree credentials")
    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    try:
        return resp.json()
    except Exception:
        raise HTTPException(status_code=500, detail="Invalid JSON from Cashfree")

# Common status refresh logic for ACTIVE orders
async def refresh_active_status(payment: Payment) -> str:
    current_status = (payment.status or "").upper()
    if current_status == "ACTIVE" and payment.order_id:
        try:
            cf = await _call_cashfree("GET", f"/orders/{payment.order_id}")
            cf_status = cf.get("order_status")
            if cf_status:
                return cf_status.upper()
        except Exception:
            logger.debug("Failed to refresh Cashfree status for order %s", payment.order_id)
    return current_status


# ---------------------- Schemas ----------------------

class PaginatedPayments(BaseModel):
    limit: int
    offset: int
    total: int
    payments: List[PaymentOut]

    model_config = ConfigDict(from_attributes=True)

@router.get(
    "/history/{phone}",
    status_code=status.HTTP_200_OK,
    summary="Get payment history for a phone number (optional date filter)",
)
async def get_payment_history_by_phone(
    phone: str,
    on_date: Optional[date] = Query(
        None,
        alias="date",
        description="(Optional) YYYY-MM-DD to fetch only that day's payments",
    ),
    db: Session = Depends(get_db),
):
    """
    Fetch all payments for the given phone.
    - If `?date=` is provided, filters to that date.
    - ACTIVE statuses are refreshed from Cashfree.
    """
    # 1) Base query
    query = db.query(Payment).filter(Payment.phone_number == phone)

    # 2) Date filter
    if on_date is not None:
        query = query.filter(func.date(Payment.created_at) == on_date)

    # 3) Fetch records
    try:
        records = query.order_by(Payment.created_at.desc()).all()
    except SQLAlchemyError as e:
        logger.error("DB error fetching history for phone %s: %s", phone, e)
        raise HTTPException(500, "Database error")

    # 4) Process and refresh statuses
    results = []
    for r in records:
        current_status = await refresh_active_status(r)
        logger.debug("Payment record: %s, status after refresh: %s", r.id, current_status)

        data = {k: v for k, v in r.__dict__.items() if not k.startswith("_sa_instance_state")}
        data["status"] = current_status

        for dt_field in ("created_at", "updated_at"):
            val = getattr(r, dt_field, None)
            if isinstance(val, datetime):
                data[dt_field] = val.isoformat()

        results.append(data)

    return results

@router.get(
    "/employee/history",
    status_code=status.HTTP_200_OK,
    summary="Get current user's payment history (optional date filter)",
)
async def get_employee_payment_history(
    on_date: Optional[date] = Query(
        None,
        alias="date",
        description="(Optional) YYYY-MM-DD to fetch only that day's payments",
    ),
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user),
):
    """
    Fetch all payments made/raised by current user.
    - If `?date=` is provided, filters to that date.
    - ACTIVE statuses are refreshed from Cashfree.
    """
    query = db.query(Payment).filter(Payment.user_id == current_user.employee_code)

    if on_date is not None:
        query = query.filter(func.date(Payment.created_at) == on_date)

    try:
        records = query.order_by(Payment.created_at.desc()).all()
    except SQLAlchemyError as e:
        logger.error("DB error fetching user history for %s: %s", current_user.employee_code, e)
        raise HTTPException(500, "Database error")

    results = []
    for r in records:
        current_status = await refresh_active_status(r)
        logger.debug("Employee payment record: %s, status after refresh: %s", r.id, current_status)

        data = {k: v for k, v in r.__dict__.items() if not k.startswith("_sa_instance_state")}
        data["status"] = current_status

        for dt_field in ("created_at", "updated_at"):
            val = getattr(r, dt_field, None)
            if isinstance(val, datetime):
                data[dt_field] = val.isoformat()

        results.append(data)

    return results

@router.get(
    "/all/employee/history",
    status_code=status.HTTP_200_OK,
    summary="Get payment history with rich filters",
    response_model=PaginatedPayments,
)
async def get_payment_history_rich(
    service: Optional[str] = Query(None, description="Service name (partial, case-insensitive)"),
    plan_id: Optional[str] = Query(None, description="Plan filter: matches plan.id in stored JSON"),
    name: Optional[str] = Query(None, description="Payer name (partial, case-insensitive)"),
    email: Optional[str] = Query(None, description="Email (partial, case-insensitive)"),
    phone_number: Optional[str] = Query(None, description="Phone number to filter (exact)"),
    status: Optional[str] = Query(None, description="Payment status filter (case-insensitive)"),
    mode: Optional[str] = Query(None, description="Mode filter"),
    user_id: Optional[str] = Query(None, description="User ID filter"),
    branch_id: Optional[str] = Query(None, description="Branch ID filter"),
    lead_id: Optional[int] = Query(None, description="Lead ID filter"),
    order_id: Optional[str] = Query(None, description="Order ID to filter"),
    date_from: Optional[date] = Query(None, description="YYYY-MM-DD start date (inclusive)"),
    date_to: Optional[date] = Query(None, description="YYYY-MM-DD end date (inclusive)"),
    limit: int = Query(100, ge=1, le=500, description="Max records to return (capped at 500)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from cannot be after date_to")

    try:
        q = db.query(Payment)

        if service:
            q = q.filter(func.array_to_string(Payment.Service, " ").ilike(f"%{service}%"))

        if plan_id is not None:
            try:
                plan_id_val = int(plan_id)
                q = q.filter(Payment.plan.contains([{"id": plan_id_val}]))
            except ValueError:
                q = q.filter(Payment.plan.contains([{"id": plan_id}]))  # fallback if not int

        if name:
            q = q.filter(Payment.name.ilike(f"%{name}%"))
        if email:
            q = q.filter(Payment.email.ilike(f"%{email}%"))
        if phone_number:
            q = q.filter(Payment.phone_number == phone_number)
        if status:
            q = q.filter(func.upper(Payment.status) == status.upper())
        if mode:
            q = q.filter(Payment.mode == mode)
        if user_id:
            q = q.filter(Payment.user_id == user_id)
        if branch_id:
            q = q.filter(Payment.branch_id == branch_id)
        if lead_id is not None:
            q = q.filter(Payment.lead_id == lead_id)
        if order_id:
            q = q.filter(Payment.order_id == order_id)

        if date_from and date_to:
            q = q.filter(
                func.date(Payment.created_at) >= date_from,
                func.date(Payment.created_at) <= date_to,
            )
        elif date_from:
            q = q.filter(func.date(Payment.created_at) >= date_from)
        elif date_to:
            q = q.filter(func.date(Payment.created_at) <= date_to)

        total = q.count()

        records = (
            q.order_by(Payment.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

        # Prefetch employee/user details to avoid N+1
        user_ids = {r.user_id for r in records if r.user_id}
        employee_map: Dict[str, UserDetails] = {}
        if user_ids:
            users = db.query(UserDetails).filter(UserDetails.employee_code.in_(list(user_ids))).all()
            employee_map = {u.employee_code: u for u in users}

    except SQLAlchemyError as e:
        logger.error("Database query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch payment history from database")

    payments_out: list[PaymentOut] = []
    for r in records:
        current_status = await refresh_active_status(r)

        data: dict[str, Any] = {k: v for k, v in r.__dict__.items() if not k.startswith("_sa_instance_state")}
        data["status"] = current_status

        # Normalize datetime fields
        for dt_field in ("created_at", "updated_at"):
            val = getattr(r, dt_field, None)
            if isinstance(val, datetime):
                data[dt_field] = val.isoformat()

        # Attach employee info
        employee = employee_map.get(r.user_id) if r.user_id else None
        if employee:
            data["raised_by"] = getattr(employee, "name", None) or getattr(employee, "full_name", None)
            data["raised_by_role"] = getattr(employee, "role_id", None)
            data["raised_by_phone"] = getattr(employee, "phone_number", None)
            data["raised_by_email"] = getattr(employee, "email", None)
        else:
            data.setdefault("raised_by", None)
            data.setdefault("raised_by_role", None)
            data.setdefault("raised_by_phone", None)
            data.setdefault("raised_by_email", None)

        try:
            payment_obj = PaymentOut(**data)
        except Exception as e:
            logger.error(
                "Serialization of payment record failed (id=%s): %s",
                getattr(r, "id", "<unknown>"),
                e,
            )
            continue

        payments_out.append(payment_obj)

    return PaginatedPayments(
        limit=limit,
        offset=offset,
        total=total,
        payments=payments_out,
    )


@router.get(
    "/payment-limit/{lead_id}",
    status_code=status.HTTP_200_OK,
    summary="Total paid amount for a lead (status=PAID only)",
)
async def get_total_payment_limit(
    lead_id: int,                     # ← Lead.id int hota hai
    db: Session = Depends(get_db),
):
    # Check lead exists
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Sum only PAID payments for this lead
    total_paid = (
        db.query(func.coalesce(func.sum(Payment.paid_amount), 0.0))
        .filter(
            Payment.lead_id == lead_id,
            Payment.status == "PAID"
        )
        .scalar()
    )

    # Optionally: count of paid payments
    paid_count = (
        db.query(func.count(Payment.id))
        .filter(
            Payment.lead_id == lead_id,
            Payment.status == "PAID"
        )
        .scalar()
    )

    return {
        "lead_id": lead_id,
        "total_paid": float(total_paid),  # ensure JSON serializable
        "paid_payments_count": int(paid_count),
        "total_paid_limit": PAYMENT_LIMIT,
        "remaining_limit": PAYMENT_LIMIT-float(total_paid)
    }





