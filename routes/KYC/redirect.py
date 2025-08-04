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
from sqlalchemy import and_
from routes.payments.Invoice import generate_invoices_from_payments
import logging

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

async def _safe_generate_invoices(payloads: list[dict]):
    try:
        await generate_invoices_from_payments(payloads)
    except HTTPException as he:
        logger.error("Invoice gen HTTPException: %s", he.detail)
    except Exception as e:
        logger.error("Background invoice gen failed: %s", e)


@router.post("/response_url/{mobile}/{employee_code}")
async def response_url_endpoint(request: Request,response: Response,mobile: str,employee_code:str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    set_cors_allow_all(response)
    payload = await request.json()
    result = payload.get("result")
    document = result.get("document")
    signed_url = document.get("signed_url")
    try:
        async with httpx.AsyncClient() as client:
            pdf_response = await client.get(signed_url)
        pdf_response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"HTTP error fetching PDF: {exc}"
        )
    

    kyc_user = db.query(Lead).filter(Lead.mobile == mobile).first()

    await send_agreement(kyc_user.email,kyc_user.full_name,pdf_response.content)

    kyc_user.kyc = True

    db.commit()
    
    ist = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30)))
    
    # 2) Build your HTML message
    msg_html = (
        "<div style='font-family:Arial,sans-serif; line-height:1.4;'>"
        "  <h3>📝 Agreement Completed</h3>"
        f"  <p><strong>Lead</strong>: {kyc_user.full_name} ({mobile})</p>"
        f"  <p><strong>Time</strong>: {ist.strftime('%Y-%m-%d %H:%M:%S')} IST</p>"
        f"  <p><strong>Employee</strong>: {employee_code}</p>"
        "</div>"
    )

    await notification_service.notify(
        user_id=employee_code,
        title= "Agreement Done",
        message= msg_html,
    )

    payment = (
        db.query(Payment)
        .filter(
            and_(
                Payment.lead_id == kyc_user.id,
                Payment.is_send_invoice.is_(False),  # या == False
                Payment.status == "PAID",
            )
        )
        .first()
    )

    if payment:
        invoice_payload = {
            "order_id": payment.order_id,
            "paid_amount": float(payment.paid_amount) if payment.paid_amount is not None else 0.0,
            "plan": payment.plan,
            "call": payment.call or 0,
            "created_at": payment.created_at.isoformat() if isinstance(payment.created_at, datetime) else None,
            "phone_number": payment.phone_number,
            "email": payment.email,
            "name": kyc_user.name,
            "mode": payment.mode,
            "employee_code": payment.user_id
        }

        background_tasks.add_task(_safe_generate_invoices, [invoice_payload])

    msg = (
        f"📝 Agreement completed for lead “{kyc_user.full_name}” "
        f"(mobile: {kyc_user.mobile}) by employee {employee_code} "
        f"at {ist.strftime('%Y-%m-%d %H:%M:%S')} IST"
    )

    AddLeadStory(kyc_user.id, employee_code, msg)

    print("✅ Zoop callback received:")
    print(payload)
    return {"status": "received"}



