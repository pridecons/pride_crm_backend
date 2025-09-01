# services/service_manager.py
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional, Union, Dict, Set, Tuple

import httpx
from fastapi import HTTPException
from sqlalchemy import func, cast, String, or_, case
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from db.connection import SessionLocal
from db.models import (
    Payment,
    ServiceDispatchPlatformStatus,
    ServiceDispatchHistory,
    BillingCycleEnum,
    NARRATION,
    SMSLog,
    Lead,
    SMSTemplate,
    EmailLog,  # <-- added
)
from services.mail import send_mail_by_client
from config import (
    AIRTEL_IQ_SMS_URL,
    BASIC_AUTH_PASS,
    BASIC_AUTH_USER,
    BASIC_IQ_CUSTOMER_ID,
    BASIC_IQ_ENTITY_ID,
)

logger = logging.getLogger(__name__)


# =========================
# Normalization helpers
# =========================
def _norm(s: Optional[str]) -> str:
    """Lowercase + keep alnum only, e.g. 'MCX Energy' -> 'mcxenergy'."""
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _tokenize(s: Optional[str]) -> Set[str]:
    """Split on non-alnum, lowercase tokens."""
    import re
    return {t for t in re.split(r"[^a-zA-Z0-9]+", (s or "").lower()) if t}


def _type_matches(normalized_targets: Set[str], raw_service_type: str) -> bool:
    """
    Flexible match:
      1) exact normalized match (e.g., 'stockoption')
      2) token-subset match: 'stock option premium' ⊇ {'stock','option'}
    """
    key = _norm(raw_service_type)
    if key in normalized_targets:
        return True
    svc_tokens = _tokenize(raw_service_type)
    for tgt in normalized_targets:
        tgt_tokens = _tokenize(tgt)
        if tgt_tokens and tgt_tokens.issubset(svc_tokens):
            return True
    return False


def _aware(dt: datetime) -> datetime:
    """Ensure UTC-aware datetime."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_indian_number(num: str) -> str:
    """
    Normalize to Airtel IQ expected format:
      - '9876543210' -> '919876543210'
      - '+919876543210' -> '919876543210'
    """
    cleaned = (num or "").strip()
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    if len(cleaned) == 10 and cleaned.isdigit():
        return "91" + cleaned
    return cleaned


# =========================
# Used-call counting helpers
# =========================
def _get_used_history_counts(payment_ids: List[int], db: Session) -> Dict[int, int]:
    """
    For each payment_id, count distinct dispatch_history rows with status='SENT'.
    Returns: { payment_id: used_count }
    """
    if not payment_ids:
        return {}

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
            func.lower(ServiceDispatchPlatformStatus.status) == "sent",
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


def _remaining_calls_for_payment_cached(payment: Payment, used_counts: Dict[int, int]) -> int:
    total = int(payment.call or 0)
    used = int(used_counts.get(payment.id, 0))
    return max(0, total - used)


# =========================
# Eligibility (returns the payment too)
# =========================
def get_eligible_payment_targets(
    recommendation_type: Union[str, Iterable[str], None],
    db: Session,
) -> List[Tuple[int, int]]:
    """
    Return [(lead_id, payment_id)] that have an explicit entitlement:
      - CALL: (svc_calls > 0) or (payment.call > 0)
      - DURATION: (svc_duration_day > 0) or (payment.duration_day > 0)
    If neither is present → NOT eligible.
    """
    now = datetime.now(timezone.utc)

    # normalize wanted types
    if recommendation_type is None:
        logger.info("No recommendation_type provided; returning no targets")
        return []
    if isinstance(recommendation_type, str):
        wanted_list = [s.strip() for s in recommendation_type.split(",") if s.strip()]
    else:
        wanted_list = [str(s).strip() for s in recommendation_type if str(s).strip()]
    if not wanted_list:
        logger.info("Empty recommendation_type after normalization; returning no targets")
        return []
    normalized_targets = {_norm(s) for s in wanted_list}

    # PAID only
    payments: List[Payment] = (
        db.query(Payment)
        .filter(func.lower(Payment.status) == "paid")
        .all()
    )
    if not payments:
        return []

    # For call quota checks
    payment_ids = [p.id for p in payments if p.lead_id]
    used_counts = _get_used_history_counts(payment_ids, db) if payment_ids else {}

    def is_active_duration(payment: Payment, days: int) -> bool:
        end = _aware(payment.created_at) + timedelta(days=days)
        return datetime.now(timezone.utc) <= end

    def remaining_calls(payment: Payment, svc_calls: Optional[int]) -> int:
        used = int(used_counts.get(payment.id, 0))
        if svc_calls is not None:
            return max(0, int(svc_calls) - used)
        return max(0, int(payment.call or 0) - used)

    def has_explicit_entitlement(payment: Payment, svc_calls: Optional[int], svc_duration: Optional[int]) -> str:
        """
        Returns 'CALL' if there is a call-based entitlement,
                'DURATION' if there is a duration-based entitlement,
                '' if none.
        """
        if svc_calls is not None and int(svc_calls) > 0:
            return "CALL"
        if svc_duration is not None and int(svc_duration) > 0:
            return "DURATION"
        if payment.call and int(payment.call) > 0:
            return "CALL"
        if payment.duration_day and int(payment.duration_day) > 0:
            return "DURATION"
        return ""

    # Prefer best payment per lead (more remaining calls / more time left)
    best_for_lead: Dict[int, Tuple[int, int]] = {}  # lead_id -> (payment_id, score)

    for p in payments:
        if not p.lead_id:
            continue

        matched_any = False

        # parse plan JSON if present
        plan_obj = None
        if p.plan is not None:
            try:
                plan_obj = json.loads(p.plan) if isinstance(p.plan, str) else p.plan
            except Exception:
                plan_obj = None

        # Plan path (preferred)
        if isinstance(plan_obj, list) and plan_obj:
            for svc in plan_obj:
                if not isinstance(svc, dict):
                    continue

                svc_types = svc.get("service_type")
                if isinstance(svc_types, str):
                    svc_types = [svc_types]
                if not isinstance(svc_types, list):
                    continue

                # pull plan fields
                billing_cycle = (svc.get("billing_cycle") or svc.get("billingCycle") or "").upper().strip()
                raw_duration = svc.get("duration_day") or svc.get("durationDay")
                raw_calls = svc.get("calls") or svc.get("call_count") or svc.get("callCount")
                try:
                    svc_duration = int(raw_duration) if raw_duration is not None else None
                except Exception:
                    svc_duration = None
                try:
                    svc_calls = int(raw_calls) if raw_calls is not None else None
                except Exception:
                    svc_calls = None

                # service-type match?
                if not any(_type_matches(normalized_targets, t) for t in svc_types):
                    continue

                # must have explicit entitlement
                ent = has_explicit_entitlement(p, svc_calls, svc_duration)
                if not ent:
                    continue

                # is active?
                active = False
                score = -1

                if ent == "CALL":
                    rem = remaining_calls(p, svc_calls)
                    active = rem > 0
                    score = rem  # higher remaining calls is better

                elif ent == "DURATION":
                    days = svc_duration if (svc_duration and svc_duration > 0) else int(p.duration_day or 0)
                    if days > 0:
                        active = is_active_duration(p, days)
                        if active:
                            end = _aware(p.created_at) + timedelta(days=days)
                            score = int((end - now).total_seconds())

                if active:
                    matched_any = True
                    prev = best_for_lead.get(p.lead_id)
                    if (prev is None) or (score > prev[1]):
                        best_for_lead[p.lead_id] = (p.id, score)
                    break  # one matching svc is enough

        # Legacy Payment.Service fallback (comma-split)
        if not matched_any and p.Service:
            legacy_types: List[str] = []
            for raw in p.Service:
                if isinstance(raw, str):
                    legacy_types.extend([s.strip() for s in raw.split(",") if s.strip()])

            if any(_type_matches(normalized_targets, raw) for raw in legacy_types):
                # entitlement purely from Payment fields
                ent = has_explicit_entitlement(p, None, None)
                if not ent:
                    continue  # no calls, no duration -> skip

                active = False
                score = -1

                if ent == "CALL":
                    rem = remaining_calls(p, None)
                    active = rem > 0
                    score = rem
                else:
                    # duration
                    days = int(p.duration_day or 0)
                    if days > 0:
                        active = is_active_duration(p, days)
                        if active:
                            end = _aware(p.created_at) + timedelta(days=days)
                            score = int((end - now).total_seconds())

                if active:
                    prev = best_for_lead.get(p.lead_id)
                    if (prev is None) or (score > prev[1]):
                        best_for_lead[p.lead_id] = (p.id, score)

    return [(lid, pid) for lid, (pid, _score) in best_for_lead.items()]


# Backward-compatible wrapper (returns only lead IDs)
def get_eligible_lead_ids_for_recommendation_type(
    recommendation_type: Union[str, Iterable[str], None],
    db: Session,
) -> List[int]:
    return [lead_id for (lead_id, _payment_id) in get_eligible_payment_targets(recommendation_type, db)]


# =========================
# Template resolver
# =========================
def resolve_sms_template(db: Session, template_identifier: Union[int, str]) -> Optional[SMSTemplate]:
    """
    Resolve an SMSTemplate by internal id OR by DLT template id.
    Handles string/numeric storage and stray whitespace.
    """
    norm = str(template_identifier).strip()

    # try internal PK id
    try:
        as_int = int(norm)
        tmpl = db.query(SMSTemplate).filter(SMSTemplate.id == as_int).first()
        if tmpl:
            return tmpl
    except ValueError:
        pass

    # try DLT id (cast to text, trim, also remove spaces)
    dlt_text = cast(SMSTemplate.dlt_template_id, String)
    tmpl = (
        db.query(SMSTemplate)
        .filter(
            or_(
                func.trim(dlt_text) == norm,
                func.replace(func.trim(dlt_text), " ", "") == norm,
            )
        )
        .first()
    )
    return tmpl


# =========================
# Single-shot sender
# =========================
async def send_sms_template(payload, db: Session) -> Dict[str, Union[str, int]]:
    """
    Send SMS through Airtel IQ using an SMSTemplate.
    payload.template_id can be internal SMSTemplate.id or a DLT template id.
    """
    template = db.query(SMSTemplate).filter(SMSTemplate.id == payload.template_id).first()
    if not template:
        norm_id = str(payload.template_id).strip()
        template = (
            db.query(SMSTemplate)
            .filter(cast(SMSTemplate.dlt_template_id, String) == norm_id)
            .first()
        )
    if not template:
        raise HTTPException(status_code=404, detail=f"Template {payload.template_id} not found")

    srcs = template.source_address or []
    source_address = (
        srcs[0] if isinstance(srcs, list) and srcs else
        srcs if isinstance(srcs, str) else None
    )
    if not source_address:
        raise HTTPException(status_code=500, detail="Template has no source_address configured")

    message_text = (getattr(payload, "message_override", None) or template.template or "").strip()

    dests: List[str] = []
    phones = getattr(payload, "phone_number", [])
    if isinstance(phones, str):
        phones = [phones]
    for p in phones:
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

    headers = {"accept": "application/json", "content-type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                AIRTEL_IQ_SMS_URL,
                json=sms_body,
                headers=headers,
                auth=(BASIC_AUTH_USER, BASIC_AUTH_PASS),
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        logger.error("Airtel IQ API error %s: %s; body: %s", e.response.status_code, e.response.text, sms_body)
        raise HTTPException(status_code=502, detail=f"SMS gateway error: {e.response.status_code} {e.response.text}")
    except Exception:
        logger.exception("Failed to call SMS gateway")
        raise HTTPException(status_code=502, detail="Failed to send SMS due to gateway error")


# =========================
# SMS usage report (prints who got SMS, quota, used, pending)
# =========================
def _sql_norm_phone(expr):
    """
    Normalize a phone column in SQL:
      - strip non-digits
      - if exactly 10 digits, prefix '91'
    Returns a SQL expression usable in filters / selects.
    """
    digits = func.regexp_replace(func.coalesce(expr, ""), r"\D", "", "g")
    return case(
        (func.length(digits) == 10, func.concat("91", digits)),
        else_=digits,
    )


def debug_print_sms_usage(db: Session, only_with_activity: bool = True) -> List[dict]:
    """
    Print & return a consolidated SMS usage view per lead:
      [
        {
          "lead_id": 26005,
          "lead_name": "Rahul Sharma",
          "phone": "917772883338",
          "quota_calls": 8,
          "used": 9,
          "pending": 0,
          "duration_until": "...",
          "first_sent_at": "...",
          "last_sent_at": "...",
          "total_sms_logs": 11
        },
        ...
      ]
    """
    # Aggregate PAID payments in Python (sum call / compute duration end)
    paid_payments = (
        db.query(Payment)
          .filter(func.lower(func.coalesce(Payment.status, "")) == "paid")
          .all()
    )

    quota_calls_map: Dict[int, int] = {}  # lead_id -> sum(call)
    duration_until_map: Dict[int, Optional[datetime]] = {}

    for p in paid_payments:
        if not p.lead_id:
            continue

        if p.call:
            quota_calls_map[p.lead_id] = quota_calls_map.get(p.lead_id, 0) + int(p.call or 0)
        else:
            quota_calls_map.setdefault(p.lead_id, quota_calls_map.get(p.lead_id, 0))

        if p.duration_day:
            try:
                end = _aware(p.created_at) + timedelta(days=int(p.duration_day))
            except Exception:
                end = None
            if end is not None:
                prev = duration_until_map.get(p.lead_id)
                if prev is None or end > prev:
                    duration_until_map[p.lead_id] = end
        else:
            duration_until_map.setdefault(p.lead_id, duration_until_map.get(p.lead_id))

    # Used via dispatch history (distinct SENT)
    sent_hist_subq = (
        db.query(
            ServiceDispatchHistory.id.label("hid"),
            ServiceDispatchHistory.lead_id.label("lead_id"),
        )
        .join(
            ServiceDispatchPlatformStatus,
            ServiceDispatchPlatformStatus.history_id == ServiceDispatchHistory.id,
        )
        .filter(
            func.lower(ServiceDispatchPlatformStatus.status) == "sent",
            ServiceDispatchHistory.service_name == "RATIONAL_SMS",
        )
        .distinct()
        .subquery()
    )
    used_rows = (
        db.query(sent_hist_subq.c.lead_id, func.count().label("used"))
          .group_by(sent_hist_subq.c.lead_id)
          .all()
    )
    used_map: Dict[int, int] = {r.lead_id: int(r.used or 0) for r in used_rows}

    # First/last SMS timestamps grouped by normalized phone from SMSLog
    sms_norm = _sql_norm_phone(SMSLog.recipient_phone_number)
    sms_rows = (
        db.query(
            sms_norm.label("nphone"),
            func.min(SMSLog.sent_at).label("first_at"),
            func.max(SMSLog.sent_at).label("last_at"),
            func.count().label("cnt"),
        )
        .group_by("nphone")
        .all()
    )
    sms_map: Dict[str, Tuple[Optional[datetime], Optional[datetime], int]] = {
        (r.nphone or ""): (r.first_at, r.last_at, int(r.cnt or 0)) for r in sms_rows
    }

    leads = db.query(Lead.id, Lead.full_name, Lead.mobile).all()
    out: List[dict] = []

    logger.info("===== SMS USAGE REPORT (start) =====")
    for lid, name, mobile in leads:
        phone_norm = normalize_indian_number(mobile or "")
        quota = int(quota_calls_map.get(lid, 0) or 0)
        used = int(used_map.get(lid, 0) or 0)
        pending = (max(quota - used, 0) if quota > 0 else None)
        duration_until = duration_until_map.get(lid)

        first_at, last_at, sms_cnt = sms_map.get(phone_norm, (None, None, 0))

        has_activity = (used > 0) or (sms_cnt and sms_cnt > 0)
        if only_with_activity and not has_activity:
            continue

        row = {
            "lead_id": lid,
            "lead_name": (name or "").strip(),
            "phone": phone_norm,
            "quota_calls": quota,
            "used": used,
            "pending": pending,
            "duration_until": duration_until,
            "first_sent_at": first_at,
            "last_sent_at": last_at,
            "total_sms_logs": sms_cnt,
        }
        out.append(row)

        logger.info(
            "Lead %-6s | %-25s | %s | quota=%s used=%s pending=%s | duration_until=%s | first=%s last=%s | logs=%s",
            lid, row["lead_name"][:25], phone_norm, quota, used, pending,
            duration_until, first_at, last_at, sms_cnt
        )
    logger.info("===== SMS USAGE REPORT (end) =====")
    return out


def run_sms_usage_report(only_with_activity: bool = True) -> List[dict]:
    """Open/close a session and print the report now."""
    db = SessionLocal()
    try:
        return debug_print_sms_usage(db, only_with_activity=only_with_activity)
    finally:
        db.close()


# =========================
# Hybrid quota helpers (lead-level + payment-level)
# =========================
def _build_lead_quota_map(db: Session) -> Dict[int, int]:
    """Total call quota per lead = SUM(Payment.call) across PAID payments."""
    rows = (
        db.query(Payment.lead_id, func.coalesce(Payment.call, 0))
          .filter(func.lower(func.coalesce(Payment.status, "")) == "paid")
          .all()
    )
    out: Dict[int, int] = {}
    for lid, call in rows:
        if not lid:
            continue
        out[lid] = out.get(lid, 0) + int(call or 0)
    return out


def _build_used_by_lead_map(db: Session) -> Dict[int, int]:
    """
    Count USED per lead = DISTINCT count of RATIONAL_SMS histories
    with status SENT (regardless of payment_id). This catches old rows
    where payment_id was NULL so we still block correctly.
    """
    sent_hist_subq = (
        db.query(
            ServiceDispatchHistory.id.label("hid"),
            ServiceDispatchHistory.lead_id.label("lead_id"),
        )
        .join(
            ServiceDispatchPlatformStatus,
            ServiceDispatchPlatformStatus.history_id == ServiceDispatchHistory.id,
        )
        .filter(
            func.lower(ServiceDispatchPlatformStatus.status) == "sent",
            ServiceDispatchHistory.service_name == "RATIONAL_SMS",
        )
        .distinct()
        .subquery()
    )
    rows = (
        db.query(sent_hist_subq.c.lead_id, func.count().label("used"))
          .group_by(sent_hist_subq.c.lead_id)
          .all()
    )
    return {r.lead_id: int(r.used or 0) for r in rows}


def _sd_get(sd, key, default=None):
    """Read from dict or object."""
    if sd is None:
        return default
    if isinstance(sd, dict):
        return sd.get(key, default)
    return getattr(sd, key, default)

def _fmt_num(v):
    """Format numbers nicely, preserve 0, but show '-' for None/''."""
    if v is None or v == "":
        return "-"
    try:
        # remove trailing .0 while keeping integers readable
        s = ("%.6f" % float(v)).rstrip("0").rstrip(".")
        return s if s else "0"
    except Exception:
        return str(v)

def _fmt_rec_type(v):
    """Join list to comma string; pass through string; '-' if empty."""
    if v is None or v == "":
        return "-"
    if isinstance(v, (list, tuple, set)):
        return ", ".join(str(x) for x in v if str(x).strip()) or "-"
    return str(v)


# =========================
# Bulk distribution (background-safe) — HYBRID ENFORCEMENT
# =========================
async def distribution_rational(
    recommendation_id: int,
    template_id: Union[int, str],
    message: Optional[str],
    stock_details={}
):
    """
    Hybrid quota enforcement:
      - Per-payment: use ServiceDispatchHistory.payment_id for remaining calls
      - Lead-level: if older rows missed payment_id, block when
        used_by_lead >= SUM(Payment.call) for that lead
    Also sends an email (if lead.email exists) and logs it to crm_email_logs.
    """
    logger.info("distribution_rational: recommendation_id=%s template_id=%s", recommendation_id, template_id)

    mail_sub = "Recomensation"
        # ------ Email subject + HTML & text bodies ------
    stock_name        = _sd_get(stock_details, "stock_name")
    rec_type_display  = _fmt_rec_type(_sd_get(stock_details, "recommendation_type"))
    entry_price_disp  = _fmt_num(_sd_get(stock_details, "entry_price"))
    stop_loss_disp    = _fmt_num(_sd_get(stock_details, "stop_loss"))
    t1_disp           = _fmt_num(_sd_get(stock_details, "targets"))
    t2_disp           = _fmt_num(_sd_get(stock_details, "targets2"))
    t3_disp           = _fmt_num(_sd_get(stock_details, "targets3"))

    mail_sub = f"Recommendation{f' – {stock_name}' if stock_name else ''}"

    # Clean, inline-styled HTML (safe for most email clients)
    mail_temp_html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{mail_sub}</title>
  </head>
  <body style="margin:0; padding:0; background:#f5f7fb; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif; color:#111827;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f7fb;">
      <tr>
        <td align="center" style="padding:20px;">
          <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:600px; max-width:100%; background:#ffffff; border:1px solid #e5e7eb; border-radius:14px; overflow:hidden;">
            <tr>
              <td style="padding:18px 20px; border-bottom:1px solid #e5e7eb;">
                <div style="font-size:16px; font-weight:700;">
                  {stock_name or "Recommendation"}
                </div>
                <div style="font-size:12px; color:#6b7280; margin-top:2px;">
                  {rec_type_display}
                </div>
              </td>
            </tr>

            <tr>
              <td style="padding:0;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate; border-spacing:0;">
                  <tr>
                    <td style="width:50%; padding:14px 18px; border-bottom:1px solid #f1f5f9; font-size:12px; color:#6b7280; text-transform:uppercase; letter-spacing:.4px;">
                      Entry Price
                    </td>
                    <td style="width:50%; padding:14px 18px; border-bottom:1px solid #f1f5f9; font-size:18px; font-weight:700; text-align:right; color:#111827;">
                      {entry_price_disp}
                    </td>
                  </tr>
                  <tr>
                    <td style="width:50%; padding:14px 18px; border-bottom:1px solid #f1f5f9; background:#fcfcfd; font-size:12px; color:#6b7280; text-transform:uppercase; letter-spacing:.4px;">
                      Stop Loss
                    </td>
                    <td style="width:50%; padding:14px 18px; border-bottom:1px solid #f1f5f9; background:#fcfcfd; font-size:18px; font-weight:700; text-align:right; color:#111827;">
                      {stop_loss_disp}
                    </td>
                  </tr>
                  <tr>
                    <td style="width:50%; padding:14px 18px; border-bottom:1px solid #f1f5f9; font-size:12px; color:#6b7280; text-transform:uppercase; letter-spacing:.4px;">
                      Target 1
                    </td>
                    <td style="width:50%; padding:14px 18px; border-bottom:1px solid #f1f5f9; font-size:18px; font-weight:700; text-align:right; color:#065f46;">
                      {t1_disp}
                    </td>
                  </tr>
                  <tr>
                    <td style="width:50%; padding:14px 18px; border-bottom:1px solid #f1f5f9; background:#fcfcfd; font-size:12px; color:#6b7280; text-transform:uppercase; letter-spacing:.4px;">
                      Target 2
                    </td>
                    <td style="width:50%; padding:14px 18px; border-bottom:1px solid #f1f5f9; background:#fcfcfd; font-size:18px; font-weight:700; text-align:right; color:#065f46;">
                      {t2_disp}
                    </td>
                  </tr>
                  <tr>
                    <td style="width:50%; padding:14px 18px; font-size:12px; color:#6b7280; text-transform:uppercase; letter-spacing:.4px;">
                      Target 3
                    </td>
                    <td style="width:50%; padding:14px 18px; font-size:18px; font-weight:700; text-align:right; color:#065f46;">
                      {t3_disp}
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <tr>
              <td style="background:#f9fafb; padding:16px 20px; border-top:1px solid #e5e7eb;">
                <div style="font-size:11px; color:#6b7280; line-height:16px;">
                  This message is for informational purposes and is not investment advice. Trading involves risk.
                </div>
              </td>
            </tr>

          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""

    # Plain-text fallback (if your mailer ever forces text)
    mail_temp_text = (
        f"Stock Name: {stock_name or '-'}\n"
        f"Recommendation: {rec_type_display}\n"
        f"Entry Price: {entry_price_disp}\n"
        f"Stop Loss: {stop_loss_disp}\n"
        f"Target 1: {t1_disp}\n"
        f"Target 2: {t2_disp}\n"
        f"Target 3: {t3_disp}\n\n"
        "This message is for informational purposes and is not investment advice. Trading involves risk."
    )


    db = SessionLocal()
    try:
        # Optional: print usage BEFORE sending
        try:
            run_sms_usage_report(True)
        except Exception:
            logger.exception("Failed to run SMS usage report (pre)")

        rec = db.query(NARRATION).get(recommendation_id)
        if not rec:
            logger.error("distribution_rational: recommendation %s not found", recommendation_id)
            return

        template = resolve_sms_template(db, template_id)
        if not template:
            logger.error("distribution_rational: template %s not found", template_id)
            return

        # Sender ID
        srcs = template.source_address or []
        source_address = (
            srcs[0] if isinstance(srcs, list) and srcs else
            srcs if isinstance(srcs, str) else None
        )
        if not source_address:
            logger.error("distribution_rational: template %s has no source_address", template_id)
            return

        # Targets (lead_id, payment_id) that are currently eligible by plan rules
        targets = get_eligible_payment_targets(rec.recommendation_type, db)
        logger.info("distribution_rational: eligible targets (lead,payment) = %s", targets)
        if not targets:
            return

        final_message = (message or rec.rational or "").strip()
        if not final_message:
            logger.warning("distribution_rational: empty message text; nothing to send")
            return

        # Build counters
        payment_ids = [pid for (_lid, pid) in targets]
        used_counts_by_payment = _get_used_history_counts(payment_ids, db)

        lead_quota_map = _build_lead_quota_map(db)       # SUM(call) across PAID payments
        used_by_lead_map = _build_used_by_lead_map(db)   # DISTINCT sent histories per lead

        headers = {"accept": "application/json", "content-type": "application/json"}
        successes = failures = 0
        batch_size = 100
        ops_since_commit = 0

        async with httpx.AsyncClient(timeout=15) as client:
            for lead_id, payment_id in targets:
                lead = db.query(Lead).get(lead_id)
                payment = db.query(Payment).get(payment_id)
                if not lead or not lead.mobile or not payment:
                    continue

                # 1) LEAD-LEVEL HARD CAP
                total_quota_for_lead = int(lead_quota_map.get(lead_id, 0) or 0)
                total_used_for_lead = int(used_by_lead_map.get(lead_id, 0) or 0)
                if total_quota_for_lead > 0 and total_used_for_lead >= total_quota_for_lead:
                    logger.info(
                        "Skip lead %s (global cap): used=%s >= quota=%s",
                        lead_id, total_used_for_lead, total_quota_for_lead
                    )
                    continue

                # 2) PAYMENT-LEVEL CHECK (CALL plans)
                billing = None
                if payment.call and payment.call > 0:
                    billing = BillingCycleEnum.CALL.value
                elif payment.duration_day and payment.duration_day > 0:
                    billing = BillingCycleEnum.MONTHLY.value

                if billing == BillingCycleEnum.CALL.value:
                    remaining_for_payment = _remaining_calls_for_payment_cached(payment, used_counts_by_payment)
                    if remaining_for_payment <= 0:
                        logger.info("Skip lead %s (payment %s): no remaining calls for this payment", lead_id, payment_id)
                        continue

                # Reserve locally to avoid overshoot inside this run
                if total_quota_for_lead > 0:
                    used_by_lead_map[lead_id] = total_used_for_lead + 1
                if billing == BillingCycleEnum.CALL.value:
                    used_counts_by_payment[payment_id] = used_counts_by_payment.get(payment_id, 0) + 1

                # SEND SMS
                to_number = normalize_indian_number(lead.mobile)
                if not to_number.isdigit():
                    logger.warning("distribution_rational: invalid mobile for lead %s: %r", lead_id, lead.mobile)
                    # undo local reservations
                    if total_quota_for_lead > 0:
                        used_by_lead_map[lead_id] = max(0, used_by_lead_map.get(lead_id, 1) - 1)
                    if billing == BillingCycleEnum.CALL.value:
                        used_counts_by_payment[payment_id] = max(0, used_counts_by_payment.get(payment_id, 1) - 1)
                    continue

                sms_body = {
                    "customerId": BASIC_IQ_CUSTOMER_ID,
                    "destinationAddress": [to_number],
                    "dltTemplateId": template.dlt_template_id,
                    "entityId": BASIC_IQ_ENTITY_ID,
                    "message": final_message,
                    "messageType": template.message_type,
                    "sourceAddress": source_address,
                }

                status_str = "SENT"
                identifier = None
                try:
                    resp = await client.post(
                        AIRTEL_IQ_SMS_URL,
                        json=sms_body,
                        headers=headers,
                        auth=(BASIC_AUTH_USER, BASIC_AUTH_PASS),
                    )
                    resp.raise_for_status()
                    api = resp.json()
                    identifier = api.get("messageRequestId")
                    successes += 1
                    logger.info("SMS sent to %s (lead %s): %s", to_number, lead_id, identifier)

                    # SEND EMAIL + LOG (only if email present)
                    if lead.email:
                        try:
                            send_mail_by_client(lead.email, mail_sub, mail_temp_html)
                            # Save email log
                            email_log = EmailLog(
                                template_id=None,                 # unknown template, using free-form body
                                recipient_email=lead.email,
                                sender_email=None,                # set if you have a sender/account email
                                mail_type="RATIONAL",
                                subject=mail_sub,
                                body=mail_temp_html,
                                user_id=rec.user_id,
                                sent_at=datetime.now(timezone.utc),
                            )
                            db.add(email_log)
                        except Exception as e:
                            logger.error("Failed to send email to %s (lead %s): %s", lead.email, lead_id, e)

                except Exception as e:
                    status_str = "FAILED"
                    identifier = None
                    failures += 1
                    logger.error("Failed SMS to %s (lead %s): %s", to_number, lead_id, e)
                    # undo local reservations on failure
                    if total_quota_for_lead > 0:
                        used_by_lead_map[lead_id] = max(0, used_by_lead_map.get(lead_id, 1) - 1)
                    if billing == BillingCycleEnum.CALL.value:
                        used_counts_by_payment[payment_id] = max(0, used_counts_by_payment.get(payment_id, 1) - 1)

                # Persist logs (with payment_id)
                hist = ServiceDispatchHistory(
                    lead_id=lead_id,
                    recommendation_id=recommendation_id,
                    payment_id=payment_id,  # REQUIRED so future runs count usage by payment
                    service_name="RATIONAL_SMS",
                    scheduled_for=datetime.now(timezone.utc),
                )
                db.add(hist)
                db.flush()  # hist.id

                plat = ServiceDispatchPlatformStatus(
                    history_id=hist.id,
                    platform="SMS",
                    platform_identifier=identifier,
                    status=status_str,
                    delivered_at=datetime.now(timezone.utc).isoformat(),
                )
                db.add(plat)

                sms_log = SMSLog(
                    template_id=template.id,  # internal PK (not the DLT id)
                    recipient_phone_number=to_number,
                    body=final_message,
                    status=status_str,
                    sent_at=datetime.now(timezone.utc),
                    user_id=rec.user_id,
                    sms_type="RATIONAL",
                    lead_id=lead_id
                )
                db.add(sms_log)

                ops_since_commit += 1
                if ops_since_commit >= batch_size:
                    try:
                        db.commit()
                        ops_since_commit = 0
                    except SQLAlchemyError as e:
                        logger.exception("DB commit failed mid-batch: %s", e)
                        db.rollback()

            # final commit
            try:
                db.commit()
            except SQLAlchemyError as e:
                logger.exception("DB commit failed at end: %s", e)
                db.rollback()

        logger.info("distribution_rational: DONE | success=%s failed=%s", successes, failures)

        # Optional: print usage AFTER sending
        try:
            run_sms_usage_report(True)
        except Exception:
            logger.exception("Failed to run SMS usage report (post)")

    except Exception:
        logger.exception("distribution_rational: fatal error")
    finally:
        db.close()
