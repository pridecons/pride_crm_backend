import json
import os
import logging
from datetime import datetime

from fastapi import (
    APIRouter,
    HTTPException,
    status,
    Depends,
    Request,
    BackgroundTasks,
)
from sqlalchemy.orm import Session
from db.connection import get_db
from db.models import Payment, Lead, LeadAssignment
from routes.notification.notification_service import notification_service
from utils.AddLeadStory import AddLeadStory
from routes.payments.Invoice import generate_invoices_from_payments

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payment", tags=["payment"])

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
        db.commit(lead)
        db.refresh(payment)
        if lead:
            db.refresh(lead)
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
