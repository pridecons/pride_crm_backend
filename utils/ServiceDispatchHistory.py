# routes/services/dispatch_analytics.py

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from db.connection import get_db
from db.models import (
    Lead,
    Payment,
    Service,
    ServiceDispatchHistory,
    BillingCycleEnum,
)

# ----------------------- helpers -----------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _extract_purchase_lines_from_payment(pay: Payment) -> List[Dict[str, Any]]:
    """
    Normalize purchased service lines from a Payment row.

    We support TWO sources:
      1) Payment.Service -> List[str] of service names
      2) Payment.plan    -> JSON array like:
            [{ "name": "...", "CALL": 10, "duration_day": 30, "billing_cycle": "MONTHLY" }, ...]
    Returns a list of dicts:
      { "name": str, "calls": int, "duration_day": int, "billing_cycle": Optional[str] }
    """
    lines: Dict[str, Dict[str, Any]] = {}

    # 1) From array of names
    if getattr(pay, "Service", None):
        for name in (pay.Service or []):
            if not name:
                continue
            key = name.strip()
            lines.setdefault(key, {"name": key, "calls": 0, "duration_day": 0, "billing_cycle": None})

    # 2) From plan JSON
    try:
        for item in (pay.plan or []):
            nm = (item or {}).get("name") or (item or {}).get("service") or ""
            if not nm:
                continue
            key = str(nm).strip()
            row = lines.setdefault(key, {"name": key, "calls": 0, "duration_day": 0, "billing_cycle": None})
            row["calls"] += _safe_int(item.get("CALL", 0))
            row["duration_day"] += _safe_int(item.get("duration_day", 0))
            bc = item.get("billing_cycle") or item.get("billingCycle")
            if bc:
                row["billing_cycle"] = str(bc)
    except Exception:
        # if plan is a dict or malformed, ignore gracefully
        pass

    # 3) The top-level Payment columns (CALL, duration_day) may represent a single service purchase;
    # if there's exactly one service line, merge them in.
    if len(lines) == 1:
        only = next(iter(lines.values()))
        only["calls"] += _safe_int(getattr(pay, "CALL", 0))
        only["duration_day"] += _safe_int(getattr(pay, "duration_day", 0))

    return list(lines.values())


def _merge_purchases(purchase_lists: List[List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    """
    Merge multiple payments' purchases per service name.
    """
    agg: Dict[str, Dict[str, Any]] = {}
    for rows in purchase_lists:
        for r in rows:
            key = r["name"]
            dst = agg.setdefault(key, {"name": key, "calls": 0, "duration_day": 0, "billing_cycle": None})
            dst["calls"] += _safe_int(r.get("calls", 0))
            dst["duration_day"] += _safe_int(r.get("duration_day", 0))
            # Prefer an explicit billing_cycle if provided anywhere
            if r.get("billing_cycle"):
                dst["billing_cycle"] = r["billing_cycle"]
    return agg


def _fetch_billing_cycle_from_master(db: Session, service_names: List[str]) -> Dict[str, str]:
    """
    If Service master has the billing_cycle, use it to fill gaps.
    """
    if not service_names:
        return {}
    rows = (
        db.query(Service.name, Service.billing_cycle)
        .filter(Service.name.in_(service_names))
        .all()
    )
    out: Dict[str, str] = {}
    for nm, bc in rows:
        try:
            out[nm] = (bc.value if isinstance(bc, BillingCycleEnum) else str(bc)) if bc else None
        except Exception:
            out[nm] = str(bc) if bc else None
    return out


def _dispatch_counts_by_service(db: Session, lead_id: int) -> Dict[str, int]:
    """
    How many dispatches already done per service_name for a given lead.
    """
    rows = (
        db.query(ServiceDispatchHistory.service_name, func.count(ServiceDispatchHistory.id))
        .filter(ServiceDispatchHistory.lead_id == lead_id)
        .group_by(ServiceDispatchHistory.service_name)
        .all()
    )
    return {r[0]: int(r[1]) for r in rows}


def _first_dispatch_at(db: Session, lead_id: int, service_name: str) -> Optional[datetime]:
    row = (
        db.query(func.min(ServiceDispatchHistory.scheduled_for))
        .filter(
            ServiceDispatchHistory.lead_id == lead_id,
            ServiceDispatchHistory.service_name == service_name,
        )
        .scalar()
    )
    return row


# ----------------------- 1) summary for one client -----------------------
def client_service_summary(
    lead_id: int,
    db: Session = Depends(get_db),
):
    """
    For a given client (lead), return purchased services, how many delivered,
    and whether they are CALL-based or time-based (weekly/monthly/etc.).
    """
    # Ensure lead exists
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    # All successful payments for this lead (treat every payment as entitlement)
    pays = db.query(Payment).filter(Payment.lead_id == lead_id).all()

    purchases_per_payment = [_extract_purchase_lines_from_payment(p) for p in pays]
    purchases = _merge_purchases(purchases_per_payment)  # by service_name

    # Backfill billing_cycle from Service master where missing
    name_list = list(purchases.keys())
    master_cycles = _fetch_billing_cycle_from_master(db, name_list)
    for nm, info in purchases.items():
        if not info.get("billing_cycle") and master_cycles.get(nm):
            info["billing_cycle"] = master_cycles[nm]

    # Delivered counts
    delivered = _dispatch_counts_by_service(db, lead_id)

    # Build per-service rows
    details = []
    total_services = len(purchases)
    total_delivered = 0

    now = _now_utc()

    for nm, info in purchases.items():
        calls_purchased = _safe_int(info.get("calls", 0))
        days_purchased = _safe_int(info.get("duration_day", 0))
        cycle = info.get("billing_cycle")

        delivered_count = _safe_int(delivered.get(nm, 0))
        total_delivered += delivered_count

        first_at = _first_dispatch_at(db, lead_id, nm)
        days_consumed = 0
        if first_at and days_purchased > 0:
            try:
                days_consumed = max(0, (now - first_at).days)
            except Exception:
                days_consumed = 0

        details.append({
            "service_name": nm,
            "billing_cycle": cycle,       # e.g., CALL/WEEKLY/MONTHLY...
            "calls_purchased": calls_purchased,
            "calls_delivered": delivered_count if (cycle == "CALL" or calls_purchased) else 0,
            "calls_remaining": max(0, calls_purchased - delivered_count) if (cycle == "CALL" or calls_purchased) else 0,
            "duration_days_purchased": days_purchased if days_purchased else None,
            "first_dispatch_at": first_at,
            "days_consumed": days_consumed if days_purchased else None,
            "days_remaining": max(0, days_purchased - days_consumed) if days_purchased else None,
        })

    return {
        "lead_id": lead_id,
        "client_name": getattr(lead, "full_name", None),
        "total_service_types": total_services,
        "total_dispatches": total_delivered,
        "services": details,
    }


# ----------------------- 2) list all clients with pending -----------------------
def clients_with_pending_services(
    branch_id: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Return clients (leads) who still have calls or days remaining for any service.

    Logic:
      - Calls remaining: purchased CALLs > number of dispatch rows.
      - Days remaining: for duration-based purchase, compare duration_day with days since first dispatch.
    """
    # Get candidate leads that have at least one payment (faster than full scan)
    lead_q = db.query(Lead.id, Lead.full_name)
    if branch_id is not None:
        lead_q = lead_q.filter(Lead.branch_id == branch_id)
    lead_ids = [lid for (lid, _) in lead_q.all()]

    rows: List[Dict[str, Any]] = []

    for lid in lead_ids:
        pays = db.query(Payment).filter(Payment.lead_id == lid).all()
        if not pays:
            continue

        purchases = _merge_purchases([_extract_purchase_lines_from_payment(p) for p in pays])
        if not purchases:
            continue

        delivered = _dispatch_counts_by_service(db, lid)
        master_cycles = _fetch_billing_cycle_from_master(db, list(purchases.keys()))
        lead_obj = db.query(Lead).filter(Lead.id == lid).first()

        pending_services = []

        now = _now_utc()

        for nm, info in purchases.items():
            cycle = info.get("billing_cycle") or master_cycles.get(nm)
            calls_purchased = _safe_int(info.get("calls", 0))
            days_purchased = _safe_int(info.get("duration_day", 0))

            disp = _safe_int(delivered.get(nm, 0))
            first_at = _first_dispatch_at(db, lid, nm)

            has_pending = False
            pending_info: Dict[str, Any] = {"service_name": nm, "billing_cycle": cycle}

            if (cycle == "CALL") or calls_purchased:
                remaining_calls = max(0, calls_purchased - disp)
                if remaining_calls > 0:
                    has_pending = True
                    pending_info.update({
                        "calls_purchased": calls_purchased,
                        "calls_delivered": disp,
                        "calls_remaining": remaining_calls,
                    })

            if days_purchased and first_at:
                days_consumed = max(0, (now - first_at).days)
                remaining_days = max(0, days_purchased - days_consumed)
                if remaining_days > 0:
                    has_pending = True
                    pending_info.update({
                        "duration_days_purchased": days_purchased,
                        "first_dispatch_at": first_at,
                        "days_consumed": days_consumed,
                        "days_remaining": remaining_days,
                    })

            # If no first dispatch yet and there is a days_purchased entitlement, entire duration is pending
            if days_purchased and not first_at:
                has_pending = True
                pending_info.update({
                    "duration_days_purchased": days_purchased,
                    "first_dispatch_at": None,
                    "days_consumed": 0,
                    "days_remaining": days_purchased,
                })

            if has_pending:
                pending_services.append(pending_info)

        if pending_services:
            rows.append({
                "lead_id": lid,
                "client_name": getattr(lead_obj, "full_name", None),
                "pending_services": pending_services,
            })

    total = len(rows)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "data": rows[offset: offset + limit],
    }
