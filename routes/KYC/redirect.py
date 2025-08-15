from fastapi.responses import RedirectResponse
from fastapi import APIRouter, Request, HTTPException, Depends, Response, BackgroundTasks
import json
from sqlalchemy.orm import Session
from db.connection import get_db
import httpx
from db.models import Lead, Payment
from routes.mail_service.kyc_agreement_mail import send_agreement
import base64
from routes.notification.notification_service import notification_service
from datetime import datetime, timezone, timedelta
from utils.AddLeadStory import AddLeadStory
from sqlalchemy import and_, or_
from routes.payments.Invoice import generate_invoices_from_payments
import logging
import asyncio
from typing import Any, Dict, List, Optional
import anyio  # pip install anyio

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Agreement KYC Redirect"])



# Middleware-like functionality for each endpoint
def set_cors_allow_all(response: Response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"

@router.post("/redirect/{platform}/{mobile}")
async def redirect_route(response: Response,platform: str, mobile: str):
    set_cors_allow_all(response)
    if platform == "pridecons":
        redirect_url = f"https://pridecons.com/web/download_agreement/{mobile}"
    elif platform == "service":
        redirect_url = f"https://service.pridecons.sbs/kyc/agreement/{mobile}"
    else:
        redirect_url = f"https://pridebuzz.in/kyc/agreement/{mobile}"

    return RedirectResponse(
        url=redirect_url,
        status_code=302
    )

# ---------- SAFE WRAPPER ----------

async def _safe_generate_invoices(payloads: List[Dict[str, Any]]):
    """
    Runs generate_invoices_from_payments whether it's sync or async.
    Adds resilient logging so you can see if it actually ran.
    """
    try:
        logger.info("[invoice] starting background generation for %d payload(s)", len(payloads))
        # Import here if needed to avoid circulars
        # from your_module import generate_invoices_from_payments

        if asyncio.iscoroutinefunction(generate_invoices_from_payments):
            await generate_invoices_from_payments(payloads)
        else:
            # run sync fn in a worker thread
            await anyio.to_thread.run_sync(generate_invoices_from_payments, payloads)

        logger.info("[invoice] done background generation")
    except HTTPException as he:
        logger.error("[invoice] HTTPException during generation: %s", he.detail)
    except Exception as e:
        logger.exception("[invoice] Background invoice gen failed: %s", e)


# ---------- ENDPOINT ----------

@router.post("/response_url/{mobile}/{employee_code}")
async def response_url_endpoint(
    request: Request,
    response: Response,
    mobile: str,
    employee_code: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    set_cors_allow_all(response)

    payload = await request.json()
    result = payload.get("result") or {}
    document = result.get("document") or {}
    signed_url = document.get("signed_url")

    if not signed_url:
        raise HTTPException(status_code=400, detail="signed_url missing in callback payload")

    # Fetch the PDF
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            pdf_response = await client.get(signed_url)
        pdf_response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=500, detail=f"HTTP error fetching PDF: {exc}")

    # Lookup lead
    kyc_user: Optional[Lead] = db.query(Lead).filter(Lead.mobile == mobile).first()
    if not kyc_user:
        raise HTTPException(status_code=404, detail="Lead not found for given mobile")

    # Email agreement (already working)
    await send_agreement(kyc_user.email, getattr(kyc_user, "full_name", kyc_user.name), pdf_response.content)

    # Mark KYC true
    kyc_user.kyc = True
    db.commit()

    # Notify employee
    ist = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30)))
    msg_html = (
        "<div style='font-family:Arial,sans-serif; line-height:1.4;'>"
        "  <h3>📝 Agreement Completed</h3>"
        f"  <p><strong>Lead</strong>: {getattr(kyc_user,'full_name',kyc_user.name)} ({mobile})</p>"
        f"  <p><strong>Time</strong>: {ist.strftime('%Y-%m-%d %H:%M:%S')} IST</p>"
        f"  <p><strong>Employee</strong>: {employee_code}</p>"
        "</div>"
    )
    await notification_service.notify(
        user_id=employee_code,
        title="Agreement Done",
        message=msg_html,
    )

    # Find a payment that needs an invoice
    # - handle NULL/False for is_send_invoice
    # - normalize status to common paid values
    paid_statuses = {"PAID", "SUCCESS", "SUCCESSFUL", "COMPLETED"}
    payment = (
        db.query(Payment)
        .filter(
            and_(
                Payment.lead_id == kyc_user.id,
                or_(Payment.is_send_invoice.is_(False), Payment.is_send_invoice == False, Payment.is_send_invoice.is_(None)),
                Payment.status.in_(paid_statuses),
            )
        )
        .order_by(Payment.created_at.desc())
        .first()
    )

    if payment:
        logger.info("[invoice] scheduling background invoice for order_id=%s", payment.order_id)
        invoice_payload = {
            "order_id": payment.order_id,
            "paid_amount": float(payment.paid_amount or 0.0),
            "plan": payment.plan,
            "call": payment.call or 0,
            "created_at": payment.created_at.isoformat() if isinstance(payment.created_at, datetime) else None,
            "phone_number": payment.phone_number,
            "email": payment.email,
            "name": getattr(kyc_user, "full_name", kyc_user.name),
            "mode": payment.mode,
            "employee_code": payment.user_id,
        }
        # ✅ Schedule robust background task
        background_tasks.add_task(_safe_generate_invoices, [invoice_payload])
    else:
        logger.info("[invoice] no eligible payment found for lead_id=%s (status or is_send_invoice filter failed)", kyc_user.id)

    # Story log
    msg = (
        f"📝 Agreement completed for lead “{getattr(kyc_user,'full_name',kyc_user.name)}” "
        f"(mobile: {kyc_user.mobile}) by employee {employee_code} "
        f"at {ist.strftime('%Y-%m-%d %H:%M:%S')} IST"
    )
    AddLeadStory(kyc_user.id, employee_code, msg)

    print("✅ Zoop callback received:")
    print(payload)
    return {"status": "received"}



