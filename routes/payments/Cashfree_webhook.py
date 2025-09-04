# routes/payments/Cashfree_webhook.py

import json
import os
import logging
from datetime import datetime
from typing import Optional, List

from fastapi import (
    APIRouter,
    HTTPException,
    status,
    Depends,
    Request,
    BackgroundTasks,
)
from sqlalchemy.orm import Session
from sqlalchemy import and_

from db.connection import get_db
from db.models import Payment, Lead, LeadAssignment
from routes.notification.notification_service import notification_service
from utils.AddLeadStory import AddLeadStory
from routes.payments.Invoice import generate_invoices_from_payments

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payment", tags=["payment"])

LOG_FILE = os.getenv("WEBHOOK_LOG_PATH", "payment_webhook.log")


# ---------------------------
# Helpers (safe + reusable)
# ---------------------------

def _fmt_inr(val: Optional[float]) -> str:
    try:
        return f"₹{float(val or 0):,.2f}"
    except Exception:
        return "₹0.00"

def _lead_name(lead: Optional[Lead], payment: Payment) -> str:
    """
    Lead model generally has 'full_name' (not 'name').
    Fall back to payment.name if needed.
    """
    if lead:
        return getattr(lead, "full_name", None) or getattr(lead, "name", None) or (payment.name or "")
    return payment.name or ""

def _lead_email(lead: Optional[Lead], payment: Payment) -> str:
    if lead:
        return getattr(lead, "email", None) or (getattr(payment, "email", None) or "")
    return getattr(payment, "email", None) or ""


# ---------------------------
# Background-safe wrappers
# ---------------------------

async def _safe_notify(user_id: str, title: str, message: str, lead_id: str):
    try:
        await notification_service.notify(user_id=user_id, title=title, message=message, lead_id=lead_id)
    except Exception as e:
        logger.error("Background notification failed: %s", e)

async def _safe_add_lead_story(lead_id: Optional[int], user_id: str, msg: str):
    if not lead_id:
        logger.warning("Skipping AddLeadStory: lead_id is None")
        return
    try:
        AddLeadStory(lead_id, user_id, msg)
    except Exception as e:
        logger.error("Background AddLeadStory failed: %s", e)

async def _safe_generate_invoices(payloads: List[dict]):
    try:
        await generate_invoices_from_payments(payloads)
    except HTTPException as he:
        logger.error("Invoice gen HTTPException: %s", he.detail)
    except Exception as e:
        logger.error("Background invoice gen failed: %s", e)


# ---------------------------
# Webhook Endpoint
# ---------------------------

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
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{datetime.utcnow().isoformat()} RAW: {raw}\n")
    except Exception as e:
        logger.warning("Could not write webhook log: %s", e)

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

    # Normalize status: SUCCESS -> PAID
    new_status = "PAID" if (status_cf or "").upper() == "SUCCESS" else (status_cf or "").upper()

    # 3) Fetch payment record
    payment = db.query(Payment).filter(Payment.order_id == order_id).first()
    if not payment:
        raise HTTPException(404, "Payment record not found")

    # Determine lead: prefer explicit lead_id, else fallback by phone
    lead: Optional[Lead] = None
    if payment.lead_id:
        lead = db.query(Lead).filter_by(id=payment.lead_id).first()
    if not lead and payment.phone_number:
        lead = db.query(Lead).filter(Lead.mobile == payment.phone_number).first()

    # 4) Conversion logic
    conversion_happened = False
    actor_user_id = payment.user_id or "SYSTEM"

    if lead and (status_cf or "").upper() == "SUCCESS":
        if not lead.is_client:
            lead.is_client = True
            conversion_happened = True

        assignment = db.query(LeadAssignment).filter_by(lead_id=lead.id).first()
        if assignment:
            actor_user_id = assignment.user_id or actor_user_id
            # conversion story (bg)
            background_tasks.add_task(
                _safe_add_lead_story,
                lead.id,
                actor_user_id,
                f"Lead converted to client via payment {order_id}. Amount: {_fmt_inr(payment.paid_amount)}",
            )
            db.delete(assignment)
        else:
            # conversion story even without assignment
            background_tasks.add_task(
                _safe_add_lead_story,
                lead.id,
                actor_user_id,
                f"Lead converted to client via payment {order_id}. Amount: {_fmt_inr(payment.paid_amount)}",
            )

    old_status = (payment.status or "").upper()
    status_changed = old_status != new_status

    # If nothing changed, shortcut
    if not status_changed and not conversion_happened:
        return {"message": "processed", "new_status": new_status}

    # 5) Apply updates
    if status_changed:
        payment.status = new_status

    # 6) Persist
    try:
        db.commit()
        db.refresh(payment)
        if lead:
            db.refresh(lead)
    except Exception as e:
        db.rollback()
        logger.exception("DB update error for payment %s: %s", getattr(payment, "id", "?"), e)
        raise HTTPException(500, "DB update error")

    # 7) Build auxiliary payloads (SAFE)
    lead_name = _lead_name(lead, payment)
    lead_email = _lead_email(lead, payment)

    notify_msg = (
        "<div style='font-family:Arial,sans-serif; line-height:1.5;'>"
        f"<p><strong>Lead:</strong> {lead_name} ({payment.phone_number or ''})</p>"
        f"<p><strong>Status:</strong> {new_status}" + (f" <em>(prev: {old_status})</em>" if old_status else "") + "</p>"
        f"<p><strong>Amount:</strong> {_fmt_inr(payment.paid_amount)}</p>"
        f"<p><strong>Mode:</strong> {payment.mode or 'N/A'}</p>"
        "</div>"
    )

    story_msg = (
        f"Payment status updated for order {order_id}: "
        f"{old_status or 'N/A'} → {new_status}. "
        f"Amount: {_fmt_inr(payment.paid_amount)}, Mode: {payment.mode or 'N/A'}"
    )

    invoice_payload = {
        "order_id": payment.order_id,
        "paid_amount": float(payment.paid_amount) if payment.paid_amount is not None else 0.0,
        "plan": payment.plan,
        "call": payment.call or 0,
        "created_at": payment.created_at.isoformat() if isinstance(payment.created_at, datetime) else None,
        "phone_number": payment.phone_number,
        "email": lead_email,
        "name": lead_name,
        "mode": payment.mode,
        "employee_code": payment.user_id
    }

    # 8) Background tasks
    background_tasks.add_task(_safe_notify, actor_user_id, "Payment Update", notify_msg, lead.id)
    if lead:
        background_tasks.add_task(_safe_add_lead_story, lead.id, actor_user_id, story_msg)

    if lead and getattr(lead, "kyc", False):
        background_tasks.add_task(_safe_generate_invoices, [invoice_payload])

    return {"message": "processed", "new_status": new_status}
