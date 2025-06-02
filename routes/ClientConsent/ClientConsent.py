from fastapi import APIRouter, Depends, Request, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import Optional
from db.connection import get_db
from db.models import ClientConsent, Lead
from db.Schema.client_consent import ClientConsentCreate, ClientConsentOut
from utils.time_and_ids import gen_ref, now_utc_ist
from services.mail_with_file import send_mail_by_client_with_file
from datetime import datetime, timezone, timedelta

from zoneinfo import ZoneInfo

router = APIRouter(prefix="/client-consent", tags=["client consent"])

def _get_client_ip(request: Request) -> str:
    # Prefer X-Forwarded-For (if behind proxy/load balancer)
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # could be "client, proxy1, proxy2"; take first non-empty
        parts = [p.strip() for p in xff.split(",")]
        for p in parts:
            if p:
                return p
    return request.client.host if request.client else "0.0.0.0"

@router.post("", response_model=ClientConsentOut, status_code=status.HTTP_201_CREATED)
def create_client_consent(
    payload: ClientConsentCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Create consent for a lead. Idempotent by lead_id:
    - If consent already exists for the lead, return it with 200.
    - Otherwise create and return 201.
    """
    kyc_user = db.query(Lead).filter(Lead.id == payload.lead_id).first()

    ip = _get_client_ip(request)
    ua = request.headers.get("user-agent", "-")[:1024]  # avoid overly long UA strings
    now_utc, now_ist = now_utc_ist()

    consent = ClientConsent(
        lead_id=payload.lead_id,
        consent_text=payload.consent_text,
        channel=payload.channel,
        purpose=payload.purpose,
        ip_address=ip,
        user_agent=ua,
        device_info=payload.device_info or {},
        tz_offset_minutes=payload.tz_offset_minutes,
        consented_at_utc=now_utc,
        consented_at_ist=now_ist,
        ref_id=gen_ref(),
    )

    if kyc_user.email:
        # Parse string → datetime (UTC)
        dt_utc = datetime.fromisoformat(now_ist.replace("Z", "+00:00"))

                # Define IST offset (+5:30)
        IST = timezone(timedelta(hours=5, minutes=30))

                # Convert to IST
        dt_ist = dt_utc.astimezone(IST)

                # Format into Indian-style 12-hour time with AM/PM
        formatted = dt_ist.strftime("%d-%m-%Y %I:%M:%S %p")
        consent["email"] = kyc_user.email
        consent["mail_sent"] = True
        send_mail_by_client_with_file(to_email=kyc_user.email,subject= "Pre Paymnet Consent", html_content=f"""
        <h2>Pre Payment Consent Confirmation</h2>
        <p>{payload.consent_text}</p>

        <h3>Consent Details</h3>
        <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">
        <tr><td><b>Channel</b></td><td>{payload.channel}</td></tr>
        <tr><td><b>Purpose</b></td><td>{payload.purpose}</td></tr>
        <tr><td><b>IP Address</b></td><td>{ip}</td></tr>
        <tr><td><b>User Agent</b></td><td>{ua}</td></tr>
        <tr><td><b>Device Info</b></td><td><pre>{payload.device_info or {} }</pre></td></tr>
        <tr><td><b>Timezone Offset (minutes)</b></td><td>{payload.tz_offset_minutes}</td></tr>
        <tr><td><b>Consented At (UTC)</b></td><td>{now_utc}</td></tr>
        <tr><td><b>Consented At (IST)</b></td><td>{formatted}</td></tr>
        <tr><td><b>Reference ID</b></td><td>{consent.ref_id}</td></tr>
        </table>
        """
        , show_pdf=False)

    try:
        db.add(consent)
        db.commit()
        db.refresh(consent)
        return consent
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create consent: {str(e)}",
        )

@router.get("/{lead_id}", response_model=ClientConsentOut)
def get_client_consent(
    lead_id: int,
    db: Session = Depends(get_db),
):
    rec: Optional[ClientConsent] = (
        db.query(ClientConsent).filter(ClientConsent.lead_id == lead_id).one_or_none()
    )
    if not rec:
        raise HTTPException(status_code=404, detail="Consent not found for this lead_id")
    return rec


