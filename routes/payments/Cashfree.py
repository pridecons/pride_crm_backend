import json
from datetime import datetime,date, timezone, timedelta
from fastapi import APIRouter, HTTPException, status, Body, Depends, Request, Query
from httpx import AsyncClient
from sqlalchemy.orm import Session

from config import CASHFREE_APP_ID, CASHFREE_SECRET_KEY
from db.connection import get_db
from db.models import Payment, Lead, Service
from db.Schema.payment import CreateOrderRequest, FrontUserCreate
from routes.mail_service.payment_link_mail import payment_link_mail
from sqlalchemy import func
from routes.whatsapp.cashfree_payment_link import cashfree_payment_link
import os
import logging
from routes.auth.auth_dependency import get_current_user
from routes.notification.notification_service import notification_service
from utils.AddLeadStory import AddLeadStory

logger = logging.getLogger(__name__)


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
    - Any PENDING records will be refreshed via a one-off GET /orders/{order_id}.
    """
    # 1) Build base query
    query = db.query(Payment).filter(Payment.phone_number == phone)

    # 2) Apply date filter only if provided
    if on_date is not None:
        query = query.filter(func.date(Payment.created_at) == on_date)

    # 3) Fetch ordered
    records = query.order_by(Payment.created_at.desc()).all()

    # 4) Refresh any PENDING statuses
    results = []
    for r in records:
        current_status = r.status
        if current_status.upper() == "PENDING":
            try:
                cf = await _call_cashfree("GET", f"/orders/{r.order_id}")
                cf_status = cf.get("order_status")
                if cf_status:
                    current_status = cf_status
            except HTTPException:
                pass

        results.append({
            "order_id":       r.order_id,
            "paid_amount":    r.paid_amount,
            "status":         current_status,
            "transaction_id": r.transaction_id,
            "service":        r.Service,
            "created_at":     r.created_at,
        })

    return results

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
            "notify_url": "https://crm.24x7techelp.com/api/v1/payment/webhook",
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
        status         = "PENDING",
        mode           = "CASHFREE",
        plan           = [plan_json],          # <<< store your JSON here
        call           = data.call,
        description    = data.description,
        user_id        = current_user.employee_code,
        branch_id      = current_user.branch_id,
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

@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
    summary="Cashfree S2S notification"
)
async def payment_webhook(request: Request, db: Session = Depends(get_db)):
    # 1) Read & log raw body
    body = await request.body()
    raw  = body.decode("utf-8", errors="ignore")
    logger.info("💸 Webhook raw payload: %s", raw)
    with open(LOG_FILE, "a") as f:
        f.write(f"{datetime.utcnow().isoformat()} RAW: {raw}\n")

    # 2) Parse JSON
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("❌ Webhook invalid JSON")
        raise HTTPException(400, "Invalid JSON")

    # 3) Extract order_id & status
    data      = payload.get("data", {})
    order     = data.get("order", {})
    payment_d = data.get("payment", {})

    order_id  = order.get("order_id")
    status_cf = payment_d.get("payment_status")

    if not order_id or not status_cf:
        raise HTTPException(400, "Missing order_id or payment_status")

    # 4) Fetch existing payment
    payment = db.query(Payment).filter_by(order_id=order_id).first()
    if not payment:
        # you can choose to ignore or 404 here
        logger.warning("⚠️ Webhook for unknown order_id: %s", order_id)
        return {"message": "ignored"}

    # 5) Map CASHFREE status to your field
    payment.status = "PAID" if status_cf == "SUCCESS" else status_cf

    # 6) Commit
    try:
        db.commit()
    except Exception as e:
        logger.error("❌ Webhook DB error: %s", e)
        db.rollback()

    is_success = (status_cf == "SUCCESS")
    notify_title = "Payment Successful" if is_success else "Payment Failed"
    ist = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30)))
    notify_message = (
        f"<div style='font-family:Arial,sans-serif; line-height:1.4;'>"
        f"  <h2 style='color:{ 'green' if is_success else 'red' };'>{notify_title}</h2>"
        f"  <p>Your payment for order <strong>{order_id}</strong> "
        f"of <strong>₹{payment.paid_amount:.2f}</strong> has "
        f"<strong>{'succeeded' if is_success else 'failed'}</strong>.</p>"
        f"  <p>Status: <em>{status_cf}</em></p>"
        f"  <p>Time: {ist.strftime('%Y-%m-%d %H:%M:%S')} IST</p>"
        f"</div>"
    )

    await notification_service.notify(
        user_id=payment.user_id,
        title= notify_title,
        message= notify_message,
    )

    msg = (
        f"💸 Payment for order {order_id} "
        f"{'succeeded' if is_success else 'failed'} "
        f"for ₹{payment.paid_amount:.2f} "
        f"at {ist.strftime('%Y-%m-%d %H:%M:%S')} IST"
    )
    AddLeadStory(payment.lead_id, payment.user_id, msg)

    # 7) Respond
    resp = {"message": "ok"}
    logger.info("↩️ Webhook updated status: %s → %s", order_id, payment.status)
    with open(LOG_FILE, "a") as f:
        f.write(f"{datetime.utcnow().isoformat()} RESP: {resp}\n\n")

    return resp

