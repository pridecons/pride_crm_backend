import logging
from typing import Any, Optional, List

from fastapi import (
    APIRouter,
    HTTPException,
    status,
    Body,
    Depends,
    Query,
)
from httpx import AsyncClient
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict

from config import CASHFREE_APP_ID, CASHFREE_SECRET_KEY
from db.connection import get_db
from db.models import Payment, Lead, Service, UserDetails
from db.Schema.payment import CreateOrderRequest, FrontUserCreate, PaymentOut  # keep using your existing request types
from routes.mail_service.payment_link_mail import payment_link_mail
from routes.whatsapp.cashfree_payment_link import cashfree_payment_link
from routes.auth.auth_dependency import get_current_user
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

# ── Endpoints ───────────────────────────────────────────────

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
            "notify_url": "https://crm.24x7techelp.com/api/v1/payment/webhook",
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
    service_field = data.service
    if isinstance(service_field, str):
        service_field = [service_field]

    payment = Payment(
        phone_number=data.phone,
        Service=service_field,
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
    if getattr(data, "email", None):
        payment.email = data.email          # ✅ attribute-style
    if getattr(data, "name", None):
        payment.name = data.name
    db.add(payment)
    db.commit()
    db.refresh(payment)

    user_lead = db.query(Lead).filter(Lead.id == data.lead_id).first()

    # 4) Send notifications
    newLink = urlparse(link).path.lstrip("/")
    kyc_pay_link = newLink if user_lead.kyc else link.replace("https://",f"{data.lead_id}/")
    name = data.name or "Client"
    await cashfree_payment_link(data.phone, name, data.amount, kyc_pay_link, user_lead.kyc)

    new_link = link if user_lead.kyc else link.replace("https://", "https://service.pridecons.com/payment/consent/")
    if data.email:
       await payment_link_mail(data.email, data.name, new_link)

    return {
        "orderId": cf_order_id,
        "paymentId": payment.id,
        "plan": payment.plan,
        "cashfreeResponse": cf_resp,
    }
