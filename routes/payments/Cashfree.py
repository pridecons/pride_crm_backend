import json
import os
import logging
from datetime import datetime, date
from typing import Any, Optional, List

from fastapi import (
    APIRouter,
    HTTPException,
    status,
    Body,
    Depends,
    Request,
    Query,
    BackgroundTasks,
)
from httpx import AsyncClient
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from pydantic import BaseModel
from config import CASHFREE_APP_ID, CASHFREE_SECRET_KEY
from db.connection import get_db
from db.models import Payment, Lead, Service, LeadAssignment, UserDetails
from db.Schema.payment import CreateOrderRequest, FrontUserCreate, PaymentOut
from routes.mail_service.payment_link_mail import payment_link_mail
from routes.whatsapp.cashfree_payment_link import cashfree_payment_link
from routes.auth.auth_dependency import get_current_user
from routes.notification.notification_service import notification_service
from utils.AddLeadStory import AddLeadStory
from routes.payments.Invoice import generate_invoices_from_payments
from sqlalchemy.exc import SQLAlchemyError
from urllib.parse import urlparse

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

def _headers_new() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "x-client-id": CASHFREE_APP_ID,
        "x-client-secret": CASHFREE_SECRET_KEY,
        "x-api-version": "2025-01-01",
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

async def _call_cashfree_new(method: str, path: str, json_data: Optional[dict] = None) -> dict:
    url = _base_url() + path
    headers = _headers_new()
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


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get(
    "/orders/{order_id}",
    response_model=dict,
    summary="Get order status",
)
async def get_order(order_id: str):
    """Fetch order status from Cashfree."""
    try:
        return await _call_cashfree("GET", f"/orders/{order_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching order %s: %s", order_id, e)
        raise HTTPException(500, f"Error fetching order: {e}")


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

        # Build serializable dict
        data = {k: v for k, v in r.__dict__.items() if not k.startswith("_sa_instance_state")}
        data["status"] = current_status

        # Normalize datetimes to isoformat for consistent JSON
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


class PaginatedPayments(BaseModel):
    limit: int
    offset: int
    total: int
    payments: List[PaymentOut]


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
            # Search inside the array of services: flatten to string and ilike
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
        employee_map: dict[str, UserDetails] = {}
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
            data["raised_by_role"] = getattr(employee, "role", None)
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


@router.post(
    "/generate-qr-code/{order_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Generate QR code for existing Cashfree order",
)
async def front_create_qr_code(order_id: str):
    try:
        cf_resp = await _call_cashfree_new("GET", f"/orders/{order_id}")
    except HTTPException:
        raise
    payment_session_id = cf_resp.get("payment_session_id")
    if not payment_session_id:
        raise HTTPException(500, "Missing payment_session_id in Cashfree response")

    qrBody = {
        "payment_session_id": payment_session_id,
        "payment_method": {"upi": {"channel": "qrcode"}},
    }

    qr_resp = await _call_cashfree_new("POST", f"/orders/sessions", json_data=qrBody)
    qrcode = qr_resp.get("data", {}).get("payload", {}).get("qrcode")
    payment_amount = qr_resp.get("payment_amount")

    if not qrcode:
        logger.warning("QR code missing in response for order %s: %s", order_id, qr_resp)

    return {
        "payment_session_id": payment_session_id,
        "order_id": order_id,
        "qrcode": qrcode,
        "payment_amount": payment_amount,
    }


@router.post(
    "/generate-upi-request/{order_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Generate UPI collect request for existing order",
)
async def front_create_upi_req(
    order_id: str,
    upi_id: str = Query(..., description="The UPI ID to collect payment from"),
):
    try:
        cf_resp = await _call_cashfree_new("GET", f"/orders/{order_id}")
    except Exception as exc:
        logger.exception("Cashfree GET /orders/%s failed: %s", order_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to retrieve order details from payment gateway",
        )

    payment_session_id = cf_resp.get("payment_session_id")
    if not payment_session_id:
        logger.error("Missing payment_session_id in Cashfree response: %s", cf_resp)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Malformed response from payment gateway",
        )

    qr_body = {
        "payment_session_id": payment_session_id,
        "payment_method": {"upi": {"channel": "collect", "upi_id": upi_id}},
    }

    try:
        qr_resp = await _call_cashfree_new("POST", "/orders/sessions", json_data=qr_body)
    except Exception as exc:
        logger.exception("Cashfree POST /orders/sessions failed for order %s: %s", order_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate UPI payment request",
        )

    return {
        "status": "success",
        "message": "UPI collect request generated successfully",
        "data": qr_resp,
    }


@router.post(
    "/create-order",
    status_code=status.HTTP_201_CREATED,
    summary="Create Cashfree order and seed Payment record",
)
async def front_create(
    data: FrontUserCreate = Body(...),
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user),
):
    # 1) build & call Cashfree
    cf_payload = CreateOrderRequest(
        order_amount=data.amount,
        order_currency="INR",
        customer_details={
            "customer_id": data.phone,
            "customer_name": data.name,
            "customer_phone": data.phone,
        },
        order_meta={
            "notify_url": "https://2edf77cfd7e2.ngrok-free.app/api/v1/payment/webhook",
            "payment_methods": data.payment_methods,
        },
    )
    cf_body = cf_payload.model_dump(by_alias=False, exclude_none=True)
    cf_resp = await _call_cashfree("POST", "/orders", json_data=cf_body)
    cf_order_id = cf_resp.get("order_id")
    link = cf_resp.get("payment_link")

    if not cf_order_id or not link:
        logger.error("Invalid Cashfree create order response: %s", cf_resp)
        raise HTTPException(502, "Failed to create order on Cashfree")

    # 2) Fetch & serialize your Service
    plan_obj = db.get(Service, data.service_id)
    if not plan_obj:
        raise HTTPException(status_code=404, detail="Service not found")

    plan_json = {
        "id": plan_obj.id,
        "name": plan_obj.name,
        "description": plan_obj.description,
        "service_type": plan_obj.service_type,
        "price": plan_obj.price,
        "discount_percent": plan_obj.discount_percent,
        "billing_cycle": plan_obj.billing_cycle.value,
        "discounted_price": plan_obj.discounted_price,
    }

    # 3) Seed the Payment record
    payment = Payment(
        name=data.name,
        email=data.email,
        phone_number=data.phone,
        Service=data.service,  # legacy field if still required
        order_id=cf_order_id,
        paid_amount=data.amount,
        status="ACTIVE",
        mode="CASHFREE",
        plan=[plan_json],
        call=data.call,
        description=data.description,
        user_id=current_user.employee_code,
        branch_id=current_user.branch_id,
        lead_id=data.lead_id,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    # 4) Send notifications
    newLink = urlparse(link).path.lstrip("/")
    await cashfree_payment_link(data.phone, data.name, data.amount, newLink)
    await payment_link_mail(data.email, data.name, link)

    return {
        "orderId": cf_order_id,
        "paymentId": payment.id,
        "plan": payment.plan,
        "cashfreeResponse": cf_resp,
    }


LOG_FILE = os.getenv("WEBHOOK_LOG_PATH", "payment_webhook.log")


async def _safe_notify(user_id: str, title: str, message: str):
    try:
        await notification_service.notify(user_id=user_id, title=title, message=message)
    except Exception as e:
        logger.error("Background notification failed: %s", e)


async def _safe_add_lead_story(lead_id: int, user_id: str, msg: str):
    if not lead_id:
        logger.warning("Skipping AddLeadStory: lead_id is None")
        return
    try:
        AddLeadStory(lead_id, user_id, msg)
    except Exception as e:
        logger.error("Background AddLeadStory failed: %s", e)


async def _safe_generate_invoices(payloads: list[dict]):
    try:
        await generate_invoices_from_payments(payloads)
    except HTTPException as he:
        logger.error("Invoice gen HTTPException: %s", he.detail)
    except Exception as e:
        logger.error("Background invoice gen failed: %s", e)


@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
    summary="Cashfree S2S notification",
)
async def payment_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    # 1) Read & log raw body
    raw = (await request.body()).decode("utf-8", errors="ignore")
    with open(LOG_FILE, "a") as f:
        f.write(f"{datetime.utcnow().isoformat()} RAW: {raw}\n")

    # 2) Parse JSON
    try:
        payload = json.loads(raw)
        logger.debug("Webhook payload: %s", payload)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")

    data = payload.get("data", {})
    order = data.get("order", {})
    payment_d = data.get("payment", {})

    order_id = order.get("order_id")
    status_cf = payment_d.get("payment_status")
    if not order_id or not status_cf:
        raise HTTPException(400, "Missing order_id or payment_status")

    new_status = "PAID" if status_cf.upper() == "SUCCESS" else status_cf.upper()

    # 3) Fetch payment record
    payment = db.query(Payment).filter(Payment.order_id == order_id).first()
    if not payment:
        raise HTTPException(404, "Payment record not found")

    # Determine lead: prefer explicit lead_id, else fallback by phone
    lead = None
    if payment.lead_id:
        lead = db.query(Lead).filter_by(id=payment.lead_id).first()
    else:
        lead = db.query(Lead).filter(Lead.mobile == payment.phone_number).first()

    # 4) If conversion condition met
    if lead and payment.lead_id and status_cf.upper() == "SUCCESS":
        lead.is_client = True

        assignment = db.query(LeadAssignment).filter_by(lead_id=lead.id).first()
        if assignment:
            AddLeadStory(
                lead.id,
                assignment.user_id,
                f"Lead converted to client via payment {order_id}. Amount: ₹{payment.paid_amount}",
            )
            db.delete(assignment)

    old_status = payment.status or ""
    if old_status.upper() == new_status:
        return {"message": "processed", "new_status": new_status}

    payment.status = new_status

    try:
        db.commit()
        db.refresh(payment)
    except Exception as e:
        db.rollback()
        logger.exception("DB update error for payment %s: %s", payment.id, e)
        raise HTTPException(500, "DB update error")

    # 5) Build auxiliary payloads
    notify_msg = f"Order {order_id} status updated to {new_status}"
    story_msg = f"Payment for order {order_id} updated to {new_status}"
    invoice_payload = {
        "order_id": payment.order_id,
        "paid_amount": float(payment.paid_amount),
        "plan": payment.plan,
        "call": payment.call or 0,
        "created_at": payment.created_at.isoformat() if isinstance(payment.created_at, datetime) else None,
        "phone_number": payment.phone_number,
        "email": payment.email,
        "name": payment.name,
        "mode": payment.mode,
        "employee_code": payment.user_id,
    }

    # 6) Schedule background tasks
    background_tasks.add_task(_safe_notify, payment.user_id, "Payment Update", notify_msg)
    background_tasks.add_task(_safe_add_lead_story, payment.lead_id, payment.user_id, story_msg)
    background_tasks.add_task(_safe_generate_invoices, [invoice_payload])

    return {"message": "processed", "new_status": new_status}
