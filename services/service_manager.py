import logging
from datetime import datetime, timedelta, timezone
import json
from typing import Iterable, List, Union
from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from sqlalchemy import func
from sqlalchemy.orm import Session

from db.models import ( Payment, ServiceDispatchPlatformStatus, ServiceDispatchHistory, BillingCycleEnum, NARRATION, SMSLog, Lead, SMSTemplate )
from db.connection import get_db, SessionLocal
from pydantic import BaseModel, Field, ConfigDict, root_validator
from typing import Optional, List, Union
from config import AIRTEL_IQ_SMS_URL, BASIC_AUTH_PASS, BASIC_AUTH_USER, BASIC_IQ_CUSTOMER_ID, BASIC_IQ_ENTITY_ID
import httpx

logger = logging.getLogger(__name__)

class SendSMSRequest(BaseModel):
    template_id: int
    phone_number: Union[str, List[str]]
    message_override: Optional[str] = None

    @root_validator(pre=True)
    def normalize_phone(cls, values):
        phones = values.get("phone_number")
        if isinstance(phones, str):
            values["phone_number"] = [phones]
        return values

def _normalize_key(s: str) -> str:
    """
    Lowercase, strip & remove non‐alphanumeric so “Equity Cash” → “equitycash”.
    """
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _get_used_history_counts(payment_ids: List[int], db: Session) -> dict[int, int]:
    """
    Bulk‐fetch how many distinct dispatch_history IDs with status="SENT" each payment has used.
    Returns { payment_id: used_count }.
    """
    subq = (
        db.query(
            ServiceDispatchHistory.payment_id.label("payment_id"),
            ServiceDispatchPlatformStatus.history_id.label("history_id"),
        )
        .join(
            ServiceDispatchPlatformStatus,
            ServiceDispatchPlatformStatus.history_id == ServiceDispatchHistory.id,
        )
        .filter(
            ServiceDispatchPlatformStatus.status == "SENT",
            ServiceDispatchHistory.payment_id.in_(payment_ids),
        )
        .distinct()
        .subquery()
    )

    rows = (
        db.query(subq.c.payment_id, func.count().label("used"))
        .group_by(subq.c.payment_id)
        .all()
    )
    return {r.payment_id: r.used for r in rows}


def _remaining_calls_for_payment_cached(payment: Payment, used_counts: dict[int, int]) -> int:
    total = payment.call or 0
    used = used_counts.get(payment.id, 0)
    remaining = max(0, total - used)
    logger.debug(
        "[calls] payment=%s total=%s used=%s remaining=%s",
        payment.id, total, used, remaining
    )
    return remaining


def get_eligible_lead_ids_for_recommendation_type(
    recommendation_type: Union[str, Iterable[str]],
    db: Session,
) -> List[int]:
    """
    Return list of lead IDs with active payments matching the given recommendation_type(s).
    Active means:
      - MONTHLY/YEARLY: now <= created_at + duration_day
      - CALL: remaining calls > 0
    """
    now = datetime.now(timezone.utc)
    logger.debug("Now (UTC): %s", now)

    # 1) Normalize input to list of strings
    if isinstance(recommendation_type, str):
        recommendation_type = [
            s.strip() for s in recommendation_type.split(",") if s.strip()
        ]

    # 2) Build set of normalized keys
    normalized_types = {_normalize_key(rt) for rt in recommendation_type}
    logger.debug(
        "Looking for recommendation types %s → normalized %s",
        recommendation_type, normalized_types
    )

    # 3) Fetch all PAID payments
    payments = db.query(Payment).filter(Payment.status == "PAID").all()
    logger.debug("Fetched %d PAID payments", len(payments))

    # 4) Precompute used call‐counts to avoid N+1
    payment_ids = [p.id for p in payments if p.lead_id]
    used_counts = _get_used_history_counts(payment_ids, db) if payment_ids else {}

    lead_ids = set()

    # 5) Evaluate each payment
    for p in payments:
        if not p.lead_id:
            continue

        logger.debug(
            "Payment %s → lead %s | call=%s | duration_day=%s | plan=%r | Service=%r",
            p.id, p.lead_id, p.call, p.duration_day, p.plan, p.Service
        )

        matched = False
        remaining = None

        # ————— Try plan JSON first —————
        plan_obj = None
        if p.plan is not None:
            try:
                plan_obj = json.loads(p.plan) if isinstance(p.plan, str) else p.plan
            except Exception:
                logger.debug("Cannot parse plan for payment %s", p.id)

        if isinstance(plan_obj, list):
            for svc in plan_obj:
                if not isinstance(svc, dict):
                    continue

                # **NEW**: check each entry in the plan’s service_type list
                types_list = svc.get("service_type") or []
                if not isinstance(types_list, list):
                    continue

                for raw_type in types_list:
                    key = _normalize_key(raw_type)
                    logger.debug("  plan service_type %r → key=%r", raw_type, key)
                    if key not in normalized_types:
                        continue

                    billing_raw = svc.get("billing_cycle") or ""
                    billing = billing_raw.upper() if isinstance(billing_raw, str) else None
                    logger.debug("    billing=%r", billing)

                    # Monthly/Yearly window
                    if billing in (
                        BillingCycleEnum.MONTHLY.value,
                        BillingCycleEnum.YEARLY.value
                    ):
                        if p.duration_day:
                            end = p.created_at + timedelta(days=p.duration_day)
                            logger.debug("    duration check: now=%s end=%s", now, end)
                            if now <= end:
                                matched = True
                                break

                    # Call‐based window
                    elif billing == BillingCycleEnum.CALL.value:
                        if remaining is None:
                            remaining = _remaining_calls_for_payment_cached(p, used_counts)
                        if remaining > 0:
                            matched = True
                            break

                    # Unspecified cycle = active
                    else:
                        matched = True
                        break

                if matched:
                    break

        # ————— Fallback to legacy Payment.Service array —————
        if not matched and p.Service:
            for raw in p.Service:
                if not isinstance(raw, str):
                    continue
                key = _normalize_key(raw)
                logger.debug("  Service item %r → key=%r", raw, key)
                if key not in normalized_types:
                    continue

                # CALL inference
                if p.call and p.call > 0:
                    if remaining is None:
                        remaining = _remaining_calls_for_payment_cached(p, used_counts)
                    if remaining > 0:
                        matched = True
                        break

                # duration inference
                elif p.duration_day:
                    end = p.created_at + timedelta(days=p.duration_day)
                    logger.debug("    duration check: now=%s end=%s", now, end)
                    if now <= end:
                        matched = True
                        break

                # else active
                else:
                    matched = True
                    break

        if matched:
            logger.debug("  → Payment %s MATCHES; adding lead %s", p.id, p.lead_id)
            lead_ids.add(p.lead_id)
        else:
            logger.debug("  → Payment %s did NOT match", p.id)

    result = list(lead_ids)
    logger.info("Eligible lead IDs: %s", result)
    return result

def normalize_indian_number(num: str) -> str:
    cleaned = num.strip()
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    if len(cleaned) == 10:
        return "91" + cleaned
    return cleaned

async def send_sms_template(
    payload: SendSMSRequest,
    db: Session = Depends(get_db),
):

    template = db.query(SMSTemplate).filter(SMSTemplate.id == payload.template_id).first()

    # Extract source address from template (use first if multiple)
    source_addresses = template.source_address
    if not source_addresses:
        raise HTTPException(status_code=500, detail="SMS template has no source_address configured")
    if isinstance(source_addresses, list):
        if len(source_addresses) > 1:
            logger.warning(
                "Template %s has multiple source addresses, using first: %s",
                template.id,
                source_addresses,
            )
        source_address = source_addresses[0]
    else:
        source_address = source_addresses  # fallback in case it's stored as a single string

    message_text = payload.message_override or template.template

    dests = []
    for p in payload.phone_number:
        norm = normalize_indian_number(p)
        if not norm.isdigit():
            raise HTTPException(status_code=400, detail=f"Invalid phone number: {p}")
        dests.append(norm)

    sms_body = {
        "customerId": BASIC_IQ_CUSTOMER_ID,
        "destinationAddress": dests,
        "dltTemplateId": template.dlt_template_id,
        "entityId": BASIC_IQ_ENTITY_ID,
        "message": message_text,
        "messageType": template.message_type,
        "sourceAddress": source_address,
    }

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                AIRTEL_IQ_SMS_URL,
                json=sms_body,
                headers=headers,
                auth=(BASIC_AUTH_USER, BASIC_AUTH_PASS),
            )
            resp.raise_for_status()
            api_response = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error("Airtel IQ API error %s: %s; request body: %s", e.response.status_code, e.response.text, sms_body)
        raise HTTPException(
            status_code=502,
            detail=f"SMS gateway error: {e.response.status_code} {e.response.text}"
        )
    except Exception as e:
        logger.exception("Failed to call SMS gateway")
        raise HTTPException(status_code=502, detail="Failed to send SMS due to gateway error")

async def distribution_rational(
    recommendation_id: int,
    template_id: int,
    message: str,
):
    """
    Background task that:
     1. Loads the recommendation by ID
     2. Finds all eligible lead IDs
     3. Sends each lead an SMS with the given message (or rec.rational)
     4. Logs the dispatch to ServiceDispatchHistory, ServiceDispatchPlatformStatus and SMSLog
    """
    db = SessionLocal()
    try:
        # 1) Load recommendation
        rec = db.query(NARRATION).get(recommendation_id)
        if not rec:
            logger.error("distribution_rational: rec %s not found", recommendation_id)
            return

        # 2) Load SMS template
        template = db.query(SMSTemplate).get(template_id)
        if not template:
            logger.error("distribution_rational: template %s not found", template_id)
            return

        # pick sourceAddress
        srcs = template.source_address or []
        source_address = (
            srcs[0] if isinstance(srcs, list) and srcs else
            srcs if isinstance(srcs, str) else None
        )
        if not source_address:
            logger.error("distribution_rational: template %s has no source_address", template_id)
            return

        # 3) Compute eligible leads
        lead_ids = get_eligible_lead_ids_for_recommendation_type(rec.recommendation_type, db)
        logger.info("distribution_rational: sending to leads %s", lead_ids)

        # 4) Loop over each lead
        for lead_id in lead_ids:
            lead = db.query(Lead).get(lead_id)
            if not lead or not lead.mobile:
                logger.warning("Lead %s has no mobile, skipping", lead_id)
                continue

            to_number = normalize_indian_number(lead.mobile)
            if not to_number.isdigit():
                logger.warning("Lead %s mobile %r invalid after normalize", lead_id, lead.mobile)
                continue

            # build payload
            sms_body = {
                "customerId": BASIC_IQ_CUSTOMER_ID,
                "destinationAddress": [to_number],
                "dltTemplateId": template.dlt_template_id,
                "entityId": BASIC_IQ_ENTITY_ID,
                "message": message or rec.rational or "",
                "messageType": template.message_type,
                "sourceAddress": source_address,
            }

            headers = {
                "accept": "application/json",
                "content-type": "application/json",
            }

            # send SMS
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(
                        AIRTEL_IQ_SMS_URL,
                        json=sms_body,
                        headers=headers,
                        auth=(BASIC_AUTH_USER, BASIC_AUTH_PASS),
                    )
                resp.raise_for_status()
                api = resp.json()
                status_str = "SENT"
                identifier = api.get("messageRequestId")
                logger.info("SMS sent to %s (lead %s): %s", to_number, lead_id, identifier)
            except Exception as e:
                # HTTP errors or network failures land here
                status_str = "FAILED"
                identifier = None
                logger.error("Failed to send SMS to %s (lead %s): %s", to_number, lead_id, e)

            # ---- now record DB logs ----

            # a) history
            hist = ServiceDispatchHistory(
                lead_id=lead_id,
                recommendation_id=recommendation_id,
                payment_id=None,
                service_name="RATIONAL_SMS",
                scheduled_for=datetime.now(timezone.utc)
            )
            db.add(hist)
            db.flush()  # assign hist.id

            # b) platform status
            plat = ServiceDispatchPlatformStatus(
                history_id=hist.id,
                platform="SMS",
                platform_identifier=identifier,
                status=status_str,
                delivered_at=datetime.now(timezone.utc).isoformat()
            )
            db.add(plat)

            # c) SMSLog
            sms_log = SMSLog(
                template_id=template_id,
                recipient_phone_number=to_number,
                body=sms_body["message"],
                status=status_str,
                sent_at=datetime.now(timezone.utc),
                user_id=rec.user_id
            )
            db.add(sms_log)

            # commit per-lead so you can see partial progress
            db.commit()

    finally:
        db.close()

