# routes/payment/payments.py

import json
from datetime import datetime
from fastapi import APIRouter, HTTPException, status, Body, Depends, Request, Query
from httpx import AsyncClient
from sqlalchemy.orm import Session

from config import CASHFREE_APP_ID, CASHFREE_SECRET_KEY, CASHFREE_PRODUCTION
from db.connection import get_db
from db.models import Payment, Lead
from db.Schema.payment import CreateOrderRequest, FrontCreate

router = APIRouter(prefix="/payment", tags=["payment"])

def _base_url() -> str:
    return (
        "https://api.cashfree.com/pg"
        if CASHFREE_PRODUCTION
        else "https://sandbox.cashfree.com/pg"
    )

def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "x-client-id": CASHFREE_APP_ID,
        "x-client-secret": CASHFREE_SECRET_KEY,
        "x-api-version": "2022-01-01",
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

@router.post(
    "/orders",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new order",
)
async def create_order(
    payload: CreateOrderRequest = Body(...),
    db: Session = Depends(get_db),
):
    """Create a new payment order with Cashfree."""
    # dump with aliases (camelCase) and skip None
    order_data = payload.model_dump(by_alias=False, exclude_none=True)
    try:
        response = await _call_cashfree("POST", "/orders", json_data=order_data)
        # TODO: persist to DB if desired
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error creating order: {e}")

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
            "return_url": "https://yourdomain.com/payment/return",
            "notify_url": "https://yourdomain.com/payment/webhook",
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

    # 5) return your IDs *and* the raw Cashfree response
    return {
        "orderId":            cf_order_id,
        "paymentId":          payment.id,
        "cashfreeResponse":   cf_resp,
    }


from datetime import date
from sqlalchemy import func
from fastapi import Query


from datetime import date
from sqlalchemy import func
from fastapi import Query, HTTPException

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


