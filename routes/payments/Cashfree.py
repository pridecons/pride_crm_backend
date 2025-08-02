import json
from datetime import datetime,date, timezone, timedelta
from fastapi import APIRouter, HTTPException, status, Body, Depends, Request, Query, BackgroundTasks
from httpx import AsyncClient
from sqlalchemy.orm import Session

from config import CASHFREE_APP_ID, CASHFREE_SECRET_KEY
from db.connection import get_db
from db.models import Payment, Lead, Service, LeadAssignment
from db.Schema.payment import CreateOrderRequest, FrontUserCreate, PaymentOut
from routes.mail_service.payment_link_mail import payment_link_mail
from sqlalchemy import func
from routes.whatsapp.cashfree_payment_link import cashfree_payment_link
import os
import logging
from routes.auth.auth_dependency import get_current_user
from routes.notification.notification_service import notification_service
from utils.AddLeadStory import AddLeadStory
from routes.payments.Invoice import generate_invoices_from_payments

logger = logging.getLogger(__name__)

# ACTIVE: Order does not have a sucessful transaction yet
# PAID: Order is PAID with one successful transaction
# EXPIRED: Order was not PAID and not it has expired. No transaction can be initiated for an EXPIRED order. TERMINATED: Order terminated TERMINATION_REQUESTED: Order termination requested

router = APIRouter(prefix="/payment", tags=["payment"])

def _base_url() -> str:
    return (
        "https://api.cashfree.com/pg"
    )

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

async def _call_cashfree(method: str, path: str, json_data: dict | None = None):
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
    return resp.json()

async def _call_cashfree_new(method: str, path: str, json_data: dict | None = None):
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
    return resp.json()

@router.get(
    "/orders/{order_id}",
    response_model=dict,
    summary="Get order status"
)
async def get_order(order_id: str):
    """Fetch order status from Cashfree."""
    try:
        return await _call_cashfree("GET", f"/orders/{order_id}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error fetching order: {e}")


@router.get(
    "/history/{phone}",
    status_code=status.HTTP_200_OK,
    summary="Get payment history by phone number (optional date filter)",
)
async def get_payment_history(
    phone: str,
    on_date: date | None = Query(
        None,
        alias="date",
        description="(Optional) YYYY-MM-DD to fetch only that day's payments"
    ),
    db: Session = Depends(get_db)
):
    """
    Fetch all payments for the given phone.
    - If `?date=` is provided, only payments on that date are returned.
    - Any ACTIVE records will be refreshed via a one-off GET /orders/{order_id}.
    """
    # 1) Build base query
    query = db.query(Payment).filter(Payment.phone_number == phone)

    # 2) Apply date filter only if provided
    if on_date is not None:
        query = query.filter(func.date(Payment.created_at) == on_date)

    # 3) Fetch ordered
    records = query.order_by(Payment.created_at.desc()).all()

    # 4) Refresh any ACTIVE statuses
    results = []
    for r in records:
        current_status = r.status
        if current_status.upper() == "ACTIVE":
            try:
                cf = await _call_cashfree("GET", f"/orders/{r.order_id}")
                cf_status = cf.get("order_status")
                if cf_status:
                    current_status = cf_status
            except HTTPException:
                pass
        print("r:", r.__dict__)

        data = {k: v for k, v in r.__dict__.items() if not k.startswith("_sa_instance_state")}

        # If created_at/updated_at are datetime, ensure they serialize properly:
        for dt_field in ("created_at", "updated_at"):
            if isinstance(data.get(dt_field), datetime):
                data[dt_field] = data[dt_field]

        results.append(data)

    return results

@router.get(
    "/employee/history",
    status_code=status.HTTP_200_OK,
    summary="Get payment history by phone number (optional date filter)",
)
async def get_payment_history_lead(
    on_date: date | None = Query(
        None,
        alias="date",
        description="(Optional) YYYY-MM-DD to fetch only that day's payments"
    ),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Fetch all payments for the given phone.
    - If `?date=` is provided, only payments on that date are returned.
    - Any ACTIVE records will be refreshed via a one-off GET /orders/{order_id}.
    """
    # 1) Build base query
    query = db.query(Payment).filter(Payment.user_id == current_user.employee_code)

    # 2) Apply date filter only if provided
    if on_date is not None:
        query = query.filter(func.date(Payment.created_at) == on_date)

    # 3) Fetch ordered
    records = query.order_by(Payment.created_at.desc()).all()

    # 4) Refresh any ACTIVE statuses
    results = []
    for r in records:
        current_status = r.status
        if current_status.upper() == "ACTIVE":
            try:
                cf = await _call_cashfree("GET", f"/orders/{r.order_id}")
                cf_status = cf.get("order_status")
                if cf_status:
                    current_status = cf_status
            except HTTPException:
                pass
        print("r:", r.__dict__)

        data = {k: v for k, v in r.__dict__.items() if not k.startswith("_sa_instance_state")}

        # If created_at/updated_at are datetime, ensure they serialize properly:
        for dt_field in ("created_at", "updated_at"):
            if isinstance(data.get(dt_field), datetime):
                data[dt_field] = data[dt_field]

        results.append(data)

    return results


from fastapi import APIRouter, Query, Depends, status, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, date
from typing import Any, Optional, List
import json
import logging

from pydantic import BaseModel

# assume these are available / imported appropriately in your module:
# get_db, _call_cashfree, Payment

router = APIRouter()
logger = logging.getLogger(__name__)  # fallback logger; replace/use your existing logger if available

# Response model

class PaginatedPayments(BaseModel):
    limit: int
    offset: int
    total: int
    payments: List[PaymentOut]


@router.get(
    "/all/employee/history",
    status_code=status.HTTP_200_OK,
    summary="Get payment history with rich filters (service, plan, name, email, phone, status, mode, user, branch, lead, order)",
    response_model=PaginatedPayments,
)
async def get_payment_history_lead(
    service: str | None = Query(None, description="Service name (partial, case-insensitive)"),
    plan: str | None = Query(None, description="Plan filter: JSON for containment or plain string for substring match"),
    name: str | None = Query(None, description="Payer name (partial, case-insensitive)"),
    email: str | None = Query(None, description="Email (partial, case-insensitive)"),
    phone_number: str | None = Query(None, description="Phone number to filter (exact match)"),
    status: str | None = Query(None, description="Payment status filter (case-insensitive)"),
    mode: str | None = Query(None, description="Mode filter"),
    user_id: str | None = Query(None, description="User ID filter"),
    branch_id: str | None = Query(None, description="Branch ID filter"),
    lead_id: int | None = Query(None, description="Lead ID filter"),
    order_id: str | None = Query(None, description="Order ID to filter"),
    date_from: date | None = Query(None, description="YYYY-MM-DD start date (inclusive)"),
    date_to: date | None = Query(None, description="YYYY-MM-DD end date (inclusive)"),
    limit: int = Query(100, ge=1, le=500, description="Max records to return (capped at 500)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
):
    """
    Fetch payment history with optional rich filters.
    ACTIVE statuses are refreshed via one-off call to Cashfree `/orders/{order_id}`.
    """
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from cannot be after date_to")

    try:
        q = db.query(Payment)

        if service:
            q = q.filter(Payment.Service.ilike(f"%{service}%"))
        if plan:
            try:
                parsed = json.loads(plan)
                q = q.filter(Payment.plan.contains(parsed))
            except (json.JSONDecodeError, TypeError):
                logger.warning("Invalid JSON for plan filter, falling back to substring match: %s", plan)
                q = q.filter(func.cast(Payment.plan, func.text).ilike(f"%{plan}%"))
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
    except SQLAlchemyError as e:
        logger.error("Database query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch payment history from database")

    payments_out = []
    for r in records:
        # Default to original status
        current_status = (r.status or "").upper()

        # Refresh if ACTIVE and order_id exists
        if current_status == "ACTIVE" and r.order_id:
            try:
                cf = await _call_cashfree("GET", f"/orders/{r.order_id}")
                cf_status = cf.get("order_status")
                if cf_status:
                    current_status = cf_status
            except Exception as e:
                logger.warning("Cashfree refresh failed for order %s: %s", r.order_id, e)

        # Build serializable dict (Pydantic will handle most via orm_mode)
        data = {k: v for k, v in r.__dict__.items() if not k.startswith("_sa_instance_state")}
        data["status"] = current_status

        # Ensure datetime fields are ISO strings (Pydantic can also handle but keeping explicit)
        for dt_field in ("created_at", "updated_at"):
            val = getattr(r, dt_field, None)
            if isinstance(val, datetime):
                data[dt_field] = val.isoformat()

        try:
            payment_obj = PaymentOut(**data)
        except Exception as e:
            logger.error("Serialization of payment record failed (id=%s): %s", getattr(r, "id", "<unknown>"), e)
            # skip malformed record
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
    summary="Create Cashfree order + seed Payment record",
)
async def front_create_qr_code(
    order_id: str
):

    # 3) call Cashfree
    cf_resp = await _call_cashfree_new("GET", f"/orders/{order_id}")
    payment_session_id = cf_resp["payment_session_id"]

    qrBody = {
        "payment_session_id": payment_session_id,
        "payment_method": {
            "upi": {
            "channel": "qrcode"
            }
        }
    }

    qr_resp = await _call_cashfree_new("POST", f"/orders/sessions", json_data=qrBody)
    qrcode=qr_resp["data"]["payload"]["qrcode"]
    payment_amount=qr_resp["payment_amount"]
    print("qr_resp : ",qr_resp)
    print("qrcode : ",qrcode)

    return{
        "payment_session_id": payment_session_id,
        "order_id": order_id,
        "qrcode": qrcode,
        "payment_amount":payment_amount
    }


@router.post(
    "/generate-upi-request/{order_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Create Cashfree order + seed Payment record",
)
async def front_create_upi_req(
    order_id: str,
    upi_id: str = Query(..., description="The UPI ID to collect payment from"),
):
    # 1) Fetch order details from Cashfree
    try:
        cf_resp = await _call_cashfree_new("GET", f"/orders/{order_id}")
    except Exception as exc:
        logger.exception("💥 Cashfree GET /orders/%s failed", order_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to retrieve order details from payment gateway"
        )

    payment_session_id = cf_resp.get("payment_session_id")
    if not payment_session_id:
        logger.error("❌ Missing payment_session_id in Cashfree response: %s", cf_resp)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Malformed response from payment gateway"
        )

    # 2) Build the QR payload
    qr_body = {
        "payment_session_id": payment_session_id,
        "payment_method": {
            "upi": {
                "channel": "collect",
                "upi_id": upi_id
            }
        }
    }

    # 3) Create the UPI collect session
    try:
        qr_resp = await _call_cashfree_new("POST", "/orders/sessions", json_data=qr_body)
    except Exception as exc:
        logger.exception("💥 Cashfree POST /orders/sessions failed for order %s", order_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate UPI payment request"
        )

    # 4) Return a clear, consistent payload
    return {
        "status": "success",
        "message": "UPI collect request generated successfully",
        "data": qr_resp
    }



@router.post(
    "/create-order",
    status_code=status.HTTP_201_CREATED,
    summary="Create Cashfree order + seed Payment record",
)
async def front_create(
    data: FrontUserCreate = Body(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 1) build & call Cashfree
    cf_payload = CreateOrderRequest(
        order_amount   = data.amount,
        order_currency = "INR",
        customer_details={
            "customer_id":    data.phone,
            "customer_name":  data.name,
            "customer_phone": data.phone,
        },
        order_meta={
            "notify_url": "https://2edf77cfd7e2.ngrok-free.app/api/v1/payment/webhook",
            "payment_methods":  data.payment_methods
        },
    )
    cf_body = cf_payload.model_dump(by_alias=False, exclude_none=True)
    cf_resp = await _call_cashfree("POST", "/orders", json_data=cf_body)
    cf_order_id = cf_resp["order_id"]
    link        = cf_resp["payment_link"]

    # 2) Fetch & serialize your Service
    plan_obj = db.get(Service, data.service_id)
    if not plan_obj:
        raise HTTPException(404, "Service not found")

    plan_json = {
        "id":               plan_obj.id,
        "name":             plan_obj.name,
        "description":      plan_obj.description,
        "service_type":     plan_obj.service_type,
        "price":            plan_obj.price,
        "discount_percent": plan_obj.discount_percent,
        "billing_cycle":    plan_obj.billing_cycle.value,
        "discounted_price": plan_obj.discounted_price,
    }

    # 3) Seed the Payment record, embedding that JSON in a list
    payment = Payment(
        name           = data.name,
        email          = data.email,
        phone_number   = data.phone,
        Service        = data.service,         # if you still need this field
        order_id       = cf_order_id,
        paid_amount    = data.amount,
        status         = "ACTIVE",
        mode           = "CASHFREE",
        plan           = [plan_json],          # <<< store your JSON here
        call           = data.call,
        description    = data.description,
        user_id        = current_user.employee_code,
        branch_id      = current_user.branch_id,
        lead_id        = data.lead_id
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    # 4) Send out your link & return
    await cashfree_payment_link(data.phone, data.name, data.amount, link)
    await payment_link_mail(data.email, data.name, link)

    return {
        "orderId":          cf_order_id,
        "paymentId":        payment.id,
        "plan":             payment.plan,      # you’ll now see the JSON array
        "cashfreeResponse": cf_resp,
    }


LOG_FILE = os.getenv("WEBHOOK_LOG_PATH", "payment_webhook.log")



async def _safe_notify(user_id: str, title: str, message: str):
    try:
        await notification_service.notify(user_id=user_id, title=title, message=message)
    except Exception as e:
        logger.error("🔔 background notification failed: %s", e)


async def _safe_add_lead_story(lead_id: int, user_id: str, msg: str):
    if not lead_id:
        logger.warning("Skipping AddLeadStory: lead_id is None")
        return
    try:
        AddLeadStory(lead_id, user_id, msg)
    except Exception as e:
        logger.error("📖 background AddLeadStory failed: %s", e)


async def _safe_generate_invoices(payloads: list[dict]):
    try:
        # Try async
        await generate_invoices_from_payments(payloads)
    except HTTPException as he:
        # invoice builder might raise HTTPException if Lead not found, etc.
        logger.error("📄 invoice gen HTTPException: %s", he.detail)
    except Exception as e:
        # catch-all
        logger.error("📄 background invoice gen failed: %s", e)


# ── Webhook endpoint ─────────────────────────────────────────────────────────

@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
    summary="Cashfree S2S notification"
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
        print("payload : ",payload)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")

    data      = payload.get("data", {})
    order     = data.get("order", {})
    payment_d = data.get("payment", {})

    order_id  = order.get("order_id")
    print("order_id : ",order_id)
    status_cf = payment_d.get("payment_status")
    print("status_cf : ",status_cf)
    if not order_id or not status_cf:
        raise HTTPException(400, "Missing order_id or payment_status")

    # 3) Normalize to your status
    new_status = "PAID" if status_cf.upper() == "SUCCESS" else status_cf.upper()

    print("new_status : ",new_status)

    # 4) Fetch & update your Payment record
    payment = db.query(Payment).filter(Payment.order_id == order_id).first()
    lead = db.query(Lead).filter(Lead.mobile == payment.phone_number).first()

    if payment.lead_id and status_cf.upper() == "SUCCESS":
                lead = db.query(Lead).filter_by(id=payment.lead_id).first()
                if lead:
                    lead.is_client = True
                    
                    # Remove from assignment pool
                    assignment = db.query(LeadAssignment).filter_by(
                        lead_id=lead.id
                    ).first()
                    if assignment:
                        # Add story before deletion
                        AddLeadStory(
                            lead.id,
                            assignment.user_id,
                            f"Lead converted to client via payment {order_id}. Amount: ₹{payment.paid_amount}"
                        )
                        db.delete(assignment)

    if not payment:
        raise HTTPException(404, "Payment record not found")
    


    old_status = payment.status

    if old_status == new_status:
        return {"message": "processed", "new_status": new_status}

    payment.status = new_status

    try:
        db.commit()
        db.refresh(payment)
    except Exception:
        db.rollback()
        raise HTTPException(500, "DB update error")

    # 5) Build messages & invoice payload
    notify_msg = f"Order {order_id} status updated to {new_status}"
    story_msg  = f"Payment for order {order_id} updated to {new_status}"
    invoice_payload = {
        "order_id":     payment.order_id,
        "paid_amount":  float(payment.paid_amount),
        "plan":         payment.plan,
        "call":         payment.call or 0,
        "created_at":   payment.created_at.isoformat(),
        "phone_number": payment.phone_number,
        "email":        payment.email,
        "name":         payment.name,
        "mode":         payment.mode,
    }

    # 6) Schedule background tasks (won’t block the response)
    background_tasks.add_task(
        _safe_notify,
        payment.user_id,
        "Payment Update",
        notify_msg,
    )
    background_tasks.add_task(
        _safe_add_lead_story,
        payment.lead_id,
        payment.user_id,
        story_msg,
    )
    background_tasks.add_task(
        _safe_generate_invoices,
        [invoice_payload],
    )

    # 7) Return immediately
    return {"message": "processed", "new_status": new_status}
