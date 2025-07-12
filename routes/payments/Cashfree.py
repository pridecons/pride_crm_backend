# routes/payment/payments.py

from fastapi import APIRouter, HTTPException, status, Body
from httpx import AsyncClient

from config import CASHFREE_APP_ID, CASHFREE_SECRET_KEY, CASHFREE_PRODUCTION
from db.Schema.payment import (
    CreateOrderRequest,
    CreatePaymentRequest,
    CreatePaymentLinkRequest,
    CreateRefundRequest,
    CreateCustomerRequest,
    CreateSubscriptionRequest,
    CreateMandateRequest,
    SettlementReconRequest,
)

router = APIRouter(prefix="/payment", tags=["payment"])


def _base_url() -> str:
    return (
        "https://api.cashfree.com/pg"
        if CASHFREE_PRODUCTION
        else "https://sandbox.cashfree.com/pg"
    )


def _headers() -> dict[str, str]:
    return {
        "Content-Type":    "application/json",
        "x-client-id":     CASHFREE_APP_ID,
        "x-client-secret": CASHFREE_SECRET_KEY,
        "x-api-version":   "2022-01-01",
    }


async def _call_cashfree(method: str, path: str, json: dict | None = None):
    url = _base_url() + path
    async with AsyncClient() as client:
        resp = await client.request(method, url, headers=_headers(), json=json)
    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


# ─── Orders ────────────────────────────────────────────────────────────────

@router.post(
    "/orders",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new order",
)
async def create_order(payload: CreateOrderRequest = Body(...)):
    return await _call_cashfree("POST", "/orders", json=payload.model_dump())


@router.get("/orders/{order_id}", response_model=dict, summary="Get order status")
async def get_order(order_id: str):
    return await _call_cashfree("GET", f"/orders/{order_id}")


# ─── Payments ──────────────────────────────────────────────────────────────

@router.post(
    "/payments",
    response_model=dict,
    summary="Initiate a payment",
)
async def create_payment(payload: CreatePaymentRequest = Body(...)):
    return await _call_cashfree("POST", "/payments", json=payload.model_dump())


@router.get(
    "/payments/{payment_id}",
    response_model=dict,
    summary="Get payment status",
)
async def get_payment_status(payment_id: str):
    return await _call_cashfree("GET", f"/payments/{payment_id}")


# ─── Payment Links ─────────────────────────────────────────────────────────

@router.post(
    "/payment-links",
    response_model=dict,
    summary="Create a payment link",
)
async def create_payment_link(payload: CreatePaymentLinkRequest = Body(...)):
    return await _call_cashfree("POST", "/payment-links", json=payload.model_dump())


@router.get(
    "/payment-links/{link_id}",
    response_model=dict,
    summary="Get payment link details",
)
async def get_payment_link(link_id: str):
    return await _call_cashfree("GET", f"/payment-links/{link_id}")


# ─── Refunds ───────────────────────────────────────────────────────────────

@router.post(
    "/refunds",
    response_model=dict,
    summary="Initiate a refund",
)
async def create_refund(payload: CreateRefundRequest = Body(...)):
    return await _call_cashfree("POST", "/refunds", json=payload.model_dump())


@router.get(
    "/refunds/{refund_id}",
    response_model=dict,
    summary="Get refund status",
)
async def get_refund_status(refund_id: str):
    return await _call_cashfree("GET", f"/refunds/{refund_id}")


# ─── Customers ────────────────────────────────────────────────────────────

@router.post(
    "/customers",
    response_model=dict,
    summary="Register a customer",
)
async def create_customer(payload: CreateCustomerRequest = Body(...)):
    return await _call_cashfree("POST", "/customers", json=payload.model_dump())


@router.get(
    "/customers/{customer_id}",
    response_model=dict,
    summary="Get customer details",
)
async def get_customer(customer_id: str):
    return await _call_cashfree("GET", f"/customers/{customer_id}")


# ─── Subscriptions & Mandates ─────────────────────────────────────────────

@router.post(
    "/subscription",
    response_model=dict,
    summary="Create a subscription plan",
)
async def create_subscription(payload: CreateSubscriptionRequest = Body(...)):
    return await _call_cashfree("POST", "/subscription", json=payload.model_dump())


@router.get(
    "/subscription/{subscription_id}",
    response_model=dict,
    summary="Get subscription details",
)
async def get_subscription(subscription_id: str):
    return await _call_cashfree("GET", f"/subscription/{subscription_id}")


@router.post(
    "/subscription/{subscription_id}/mandate",
    response_model=dict,
    summary="Create a mandate for a subscription",
)
async def create_mandate(
    subscription_id: str,
    payload: CreateMandateRequest = Body(...),
):
    data = payload.model_dump()
    data["subscription_id"] = subscription_id
    return await _call_cashfree(
        "POST",
        f"/subscription/{subscription_id}/mandate",
        json=data,
    )


# ─── Virtual Bank Account (VBA) Lookups ────────────────────────────────────

@router.get(
    "/vba/payments/{utr}",
    response_model=dict,
    summary="Get VBA payment by UTR",
)
async def get_vba_payment(utr: str):
    return await _call_cashfree("GET", f"/vba/payments/{utr}")


# ─── Settlement Reconciliation ─────────────────────────────────────────────

@router.post(
    "/settlement/recon",
    response_model=dict,
    summary="Reconcile settlements by UTR",
)
async def settlement_recon(payload: SettlementReconRequest = Body(...)):
    return await _call_cashfree(
        "POST", "/settlement/recon", json=payload.model_dump()
    )
