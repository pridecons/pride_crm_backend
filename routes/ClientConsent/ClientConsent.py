from fastapi import APIRouter, Depends, Request, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import Optional

# adjust these imports to match your project structure
from db import get_db
from db.models import ClientConsent, Lead
from db.Schema.client_consent import ClientConsentCreate, ClientConsentOut
from utils.time_and_ids import gen_ref, now_utc_ist

router = APIRouter(prefix="client-consent", tags=["client-consent"])

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
    email= kyc_user.email
    # Check existing (unique on lead_id)
    existing: Optional[ClientConsent] = (
        db.query(ClientConsent).filter(ClientConsent.lead_id == payload.lead_id).one_or_none()
    )
    if existing:
        # Return existing with 200 OK
        # Manually set status_code since decorator has 201
        request.scope["state"] = getattr(request, "scope", {})
        return existing  # FastAPI will still respond 201 by default
        # If you want 200 explicitly, do:
        # from fastapi.responses import JSONResponse
        # return JSONResponse(status_code=200, content=ClientConsentOut.from_orm(existing).dict())

    ip = _get_client_ip(request)
    ua = request.headers.get("user-agent", "-")[:1024]  # avoid overly long UA strings
    now_utc, now_ist = now_utc_ist()

    consent = ClientConsent(
        lead_id=payload.lead_id,
        email=email,
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


