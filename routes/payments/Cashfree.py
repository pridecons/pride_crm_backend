# routes/payment/payments.py
import json
from datetime import datetime,date
from fastapi import APIRouter, HTTPException, status, Body, Depends, Request, Query
from httpx import AsyncClient
from sqlalchemy.orm import Session

from config import CASHFREE_APP_ID, CASHFREE_SECRET_KEY, CASHFREE_PRODUCTION
from db.connection import get_db
from db.models import Payment, Lead
from db.Schema.payment import CreateOrderRequest, FrontCreate
from routes.mail_service.payment_link_mail import payment_link_mail
from sqlalchemy import func
from routes.whatsapp.cashfree_payment_link import cashfree_payment_link

import logging

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


@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
    summary="Cashfree server‐to‐server notification"
)
async def payment_webhook(request: Request, db: Session = Depends(get_db)):
    data = await request.json()

    order_id       = data["orderId"]
    tx_status      = data["txStatus"]      # SUCCESS / FAILED
    tx_ref         = data.get("referenceId")
    paid_amount    = float(data.get("orderAmount", 0))
    customer       = data.get("customerDetails", {})
    tags           = data.get("orderTags", {})

    # 1) find your seeded Payment
    payment = (
        db.query(Payment)
          .filter(Payment.order_id == order_id)
          .first()
    )
    if not payment:
        # if you didn't seed it, create a fresh one
        payment = Payment(
            order_id=order_id,
            name=customer.get("customerName"),
            email=customer.get("customerEmail"),
            phone_number=customer.get("customerPhone"),
            Service=tags.get("service"),
            paid_amount=paid_amount,
        )
        db.add(payment)

    # 2) update status + txn id + actual amount
    payment.status         = tx_status
    payment.transaction_id = tx_ref
    payment.paid_amount    = paid_amount
    payment.updated_at     = datetime.utcnow()

    # 3) automatically link to any existing Lead by phone
    lead = (
        db.query(Lead)
          .filter(Lead.mobile == payment.phone_number)
          .first()
    )
    if lead:
        payment.lead_id = lead.id

    db.commit()
    return {"message": "ok"}



@router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    summary="Create Cashfree order + seed Payment record",
)
async def front_create(
    data: FrontCreate = Body(...),
    db: Session = Depends(get_db),
):
    # 1) build the Cashfree payload
    cf_payload = CreateOrderRequest(
        order_amount   = data.amount,
        order_currency = "INR",
        customer_details={
            "customer_id":    data.phone,
            "customer_name":  data.name,
            "customer_phone": data.phone,
        },
        order_meta={
            # "return_url": "https://yourdomain.com/payment/return",
            # "notify_url": "https://yourdomain.com/payment/webhook",
            "payment_methods": data.payment_methods
        },
    )

    # 2) dump in snake_case so Cashfree accepts it
    cf_body = cf_payload.model_dump(by_alias=False, exclude_none=True)

    # 3) call Cashfree
    cf_resp = await _call_cashfree("POST", "/orders", json_data=cf_body)
    cf_order_id = cf_resp["order_id"]

    # 4) seed a PENDING Payment record
    payment = Payment(
        name         = data.name,
        email        = data.email,
        phone_number = data.phone,
        Service      = data.service,
        order_id     = cf_order_id,
        paid_amount  = data.amount,
        status       = "PENDING",
        mode         = "CASHFREE",
    )
    db.add(payment)
    db.commit()

    link = cf_resp["payment_link"]

    cash_link = link.replace("https://api.cashfree.com/", "")

    await cashfree_payment_link(data.phone, data.name, data.amount, cash_link)
    await payment_link_mail(data.email, data.name, link)

    # 5) return your IDs *and* the raw Cashfree response
    return {
        "orderId":            cf_order_id,
        "paymentId":          payment.id,
        "cashfreeResponse":   cf_resp,
    }


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


