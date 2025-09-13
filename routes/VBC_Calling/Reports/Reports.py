# routes/VBC_Calling/call_reports.py
from __future__ import annotations

from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, Integer, cast

from db.connection import get_db
from db.models import UserDetails
from routes.auth.auth_dependency import get_current_user
from utils.user_tree import get_subordinate_users
from db.Models.models_VBC import VBCReport

router = APIRouter(prefix="/vbc-reports", tags=["vbc-call-reports"])

# ----------------- helpers -----------------
def _role(u: UserDetails) -> str:
    return (getattr(u, "role_name", "") or "").upper().replace(" ", "").replace("_", "")

def _today_ist_date_str() -> str:
    tz = ZoneInfo("Asia/Kolkata")
    return datetime.now(tz).strftime("%Y-%m-%d")  # matches "YYYY-MM-DD HH:mm:ss" prefix

def _normalize(s: Optional[str]) -> str:
    return (s or "").strip().upper()

def _hms(total_seconds: int) -> str:
    s = int(total_seconds or 0)
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}"

def _empty_stats() -> Dict[str, int]:
    # accepted is an alias of answered (kept for backward-compat with existing UI)
    return {
        "total": 0,
        "inbound": 0,
        "outbound": 0,
        "answered": 0,
        "missed": 0,
        "attempted": 0,
        "blocked": 0,
        "voicemail": 0,
        "accepted": 0,  # alias of answered
        # NEW:
        "duration_seconds": 0,
        "duration_hms": "00:00:00",
    }

def _empty_totals() -> Dict[str, int]:
    return _empty_stats().copy()

# ----------------- API -----------------
@router.get("/call-logs")
def get_call_logs(
    *,
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user),
    view: Literal["self", "team"] = Query("self"),
) -> Dict[str, Any]:
    """
    Aggregated *today (IST)* counts from VBCReport for users in scope.
    Scope:
      - SUPERADMIN: all users
      - BRANCHMANAGER: users in same branch
      - OTHER: view=self (self) | view=team (subordinates)
    Match: VBCReport.extension_id == UserDetails.vbc_extension_id
    Buckets returned: total, inbound, outbound, answered, missed, attempted, blocked, voicemail, accepted(=answered),
    and duration_seconds / duration_hms.
    """

    # 1) Resolve users in scope
    role = _role(current_user)
    if role in {"SUPERADMIN", "ADMIN", "SUPERADMINISTRATOR"}:
        users: List[UserDetails] = db.query(UserDetails).all()
        scope = "company"
    elif role in {"BRANCHMANAGER", "BRANCHHEAD"}:
        if current_user.branch_id is None:
            raise HTTPException(status_code=400, detail="Branch manager has no branch_id assigned.")
        users = (
            db.query(UserDetails)
            .filter(UserDetails.branch_id == current_user.branch_id)
            .all()
        )
        scope = "branch"
    else:
        if view == "team":
            users = get_subordinate_users(db, current_user.employee_code, include_inactive=False) or []
            scope = "team"
        else:
            users = (
                db.query(UserDetails)
                .filter(UserDetails.employee_code == current_user.employee_code)
                .all()
            )
            scope = "self"

    if not users:
        return {
            "scope": scope,
            "date_ist": _today_ist_date_str(),
            "employee_count": 0,
            "employees": [],
            "totals": _empty_totals(),
            "note": "No users in scope.",
        }

    # 2) Map extensions for these users
    ext_to_user: Dict[str, UserDetails] = {}
    for u in users:
        ext = (u.vbc_extension_id or "").strip()
        if ext:
            ext_to_user[ext] = u

    if not ext_to_user:
        return {
            "scope": scope,
            "date_ist": _today_ist_date_str(),
            "employee_count": 0,
            "employees": [],
            "totals": _empty_totals(),
            "note": "No VBC extensions found for users in scope.",
        }

    extensions = list(ext_to_user.keys())

    # 3) Filter for today's records (IST) on string column VBCReport.start
    today_str = _today_ist_date_str()
    date_filter = VBCReport.start.like(f"{today_str}%")

    # 4a) Aggregate once by (extension_id, direction, result) for counts
    rows = (
        db.query(
            VBCReport.extension_id.label("ext"),
            VBCReport.direction.label("direction"),
            VBCReport.result.label("result"),
            func.count().label("cnt"),
        )
        .filter(VBCReport.extension_id.in_(extensions))
        .filter(date_filter)
        .group_by(VBCReport.extension_id, VBCReport.direction, VBCReport.result)
        .all()
    )

    # 4b) Aggregate duration per extension (safe-cast length; non-numeric -> 0)
    numeric_len = cast(
        case(
            (VBCReport.length.op("~")("^[0-9]+$"), VBCReport.length),
            else_="0",
        ),
        Integer,
    )
    dur_rows = (
        db.query(
            VBCReport.extension_id.label("ext"),
            func.sum(numeric_len).label("dur"),
        )
        .filter(VBCReport.extension_id.in_(extensions))
        .filter(date_filter)
        .group_by(VBCReport.extension_id)
        .all()
    )
    dur_map = {r.ext: int(r.dur or 0) for r in dur_rows}

    # 5) Build stats
    per_ext_stats: Dict[str, Dict[str, int]] = {ext: _empty_stats() for ext in extensions}

    for r in rows:
        ext = r.ext
        direction = _normalize(r.direction)
        result = _normalize(r.result)
        cnt = int(r.cnt or 0)

        s = per_ext_stats.get(ext)
        if not s:
            s = _empty_stats()
            per_ext_stats[ext] = s

        # direction buckets
        if direction == "INBOUND":
            s["inbound"] += cnt
        elif direction == "OUTBOUND":
            s["outbound"] += cnt

        # per-result buckets
        if result == "ANSWERED":
            s["answered"] += cnt
            s["accepted"] += cnt  # alias
        elif result == "MISSED":
            s["missed"] += cnt
        elif result == "ATTEMPTED":
            s["attempted"] += cnt
        elif result == "BLOCKED":
            s["blocked"] += cnt
        elif result == "VOICEMAIL":
            s["voicemail"] += cnt

        s["total"] += cnt

    # attach duration per extension
    for ext, seconds in dur_map.items():
        s = per_ext_stats.get(ext, _empty_stats())
        s["duration_seconds"] = seconds
        s["duration_hms"] = _hms(seconds)
        per_ext_stats[ext] = s

    # 6) Per-employee array + rollup
    employees_out: List[Dict[str, Any]] = []
    totals = _empty_totals()
    totals_seconds = 0

    for ext, user in ext_to_user.items():
        s = per_ext_stats.get(ext, _empty_stats())
        employees_out.append(
            {
                "employee_code": user.employee_code,
                "name": user.name,
                "branch_id": user.branch_id,
                "vbc_extension_id": ext,
                "stats": s,
            }
        )
        # sum counts
        for k in ("total", "inbound", "outbound", "answered", "missed", "attempted", "blocked", "voicemail", "accepted"):
            totals[k] += s[k]
        # sum duration seconds
        totals_seconds += int(s.get("duration_seconds", 0))

    totals["duration_seconds"] = totals_seconds
    totals["duration_hms"] = _hms(totals_seconds)

    employees_out.sort(key=lambda e: (e["name"] or "").lower())

    return {
        "scope": scope,
        "date_ist": today_str,
        "employee_count": len(employees_out),
        "employees": employees_out,
        "totals": totals,
    }

# ---------- NEW: employee-specific endpoint with logs ----------
@router.get("/call-logs/employee")
def get_call_logs_employee(
    *,
    employee_code: str = Query(..., description="Employee code to fetch stats and logs for"),
    page: int = Query(1, ge=1),
    page_size: int = Query(1000, ge=1, le=1000),
    order: Literal["asc", "desc"] = Query("desc", description="Sort by start time"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Returns today's (IST) aggregated buckets + a paginated list of logs
    for the given employee_code, matched via VBCReport.extension_id == UserDetails.vbc_extension_id.
    Includes duration_seconds and duration_hms.
    """

    # 1) Find the user and their extension
    user: Optional[UserDetails] = (
        db.query(UserDetails)
        .filter(UserDetails.employee_code == employee_code)
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail=f"Employee {employee_code!r} not found.")
    ext = (user.vbc_extension_id or "").strip()
    if not ext:
        return {
            "date_ist": _today_ist_date_str(),
            "user": {
                "employee_code": user.employee_code,
                "name": user.name,
                "branch_id": user.branch_id,
                "vbc_extension_id": None,
            },
            "stats": _empty_stats(),
            "logs": {
                "page": page,
                "page_size": page_size,
                "total": 0,
                "records": [],
                "order": order,
            },
            "note": "User has no VBC extension configured.",
        }

    # 2) Today filter (string prefix match)
    today_str = _today_ist_date_str()
    date_filter = VBCReport.start.like(f"{today_str}%")

    # 3a) Aggregation for this extension (counts)
    rows = (
        db.query(
            VBCReport.direction.label("direction"),
            VBCReport.result.label("result"),
            func.count().label("cnt"),
        )
        .filter(VBCReport.extension_id == ext)
        .filter(date_filter)
        .group_by(VBCReport.direction, VBCReport.result)
        .all()
    )

    stats = _empty_stats()
    for r in rows:
        direction = _normalize(r.direction)
        result = _normalize(r.result)
        cnt = int(r.cnt or 0)

        if direction == "INBOUND":
            stats["inbound"] += cnt
        elif direction == "OUTBOUND":
            stats["outbound"] += cnt

        if result == "ANSWERED":
            stats["answered"] += cnt
            stats["accepted"] += cnt
        elif result == "MISSED":
            stats["missed"] += cnt
        elif result == "ATTEMPTED":
            stats["attempted"] += cnt
        elif result == "BLOCKED":
            stats["blocked"] += cnt
        elif result == "VOICEMAIL":
            stats["voicemail"] += cnt

        stats["total"] += cnt

    # 3b) Duration sum for this extension
    numeric_len = cast(
        case(
            (VBCReport.length.op("~")("^[0-9]+$"), VBCReport.length),
            else_="0",
        ),
        Integer,
    )
    dur_seconds = (
        db.query(func.coalesce(func.sum(numeric_len), 0))
        .filter(VBCReport.extension_id == ext)
        .filter(date_filter)
        .scalar()
        or 0
    )
    stats["duration_seconds"] = int(dur_seconds)
    stats["duration_hms"] = _hms(int(dur_seconds))

    # 4) Logs list (paginated)
    base_q = (
        db.query(VBCReport)
        .filter(VBCReport.extension_id == ext)
        .filter(date_filter)
    )
    total_logs = base_q.count()

    order_col = VBCReport.start.asc() if order == "asc" else VBCReport.start.desc()
    records = (
        base_q.order_by(order_col)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    def _serialize(r: VBCReport) -> Dict[str, Any]:
        # per-row duration from "length" (string) -> seconds + hms
        try:
            sec = int(r.length) if r.length is not None and str(r.length).isdigit() else None
        except Exception:
            sec = None
        return {
            "id": r.id,
            "in_network": r.in_network,
            "international": r.international,
            "from": r.extension_id,              # you saved "from" into extension_id
            "to": r.to,
            "direction": r.direction,
            "length": r.length,
            "duration_seconds": sec,
            "duration_hms": _hms(sec or 0) if sec is not None else None,
            "start": r.start,
            "end": r.end,
            "charge": r.charge,
            "rate": r.rate,
            "destination_device_name": r.destination_device_name,
            "source_device_name": r.source_device_name,
            "destination_user_full_name": r.destination_user_full_name,
            "destination_user": r.destination_user,
            "destination_sip_id": r.destination_sip_id,
            "destination_extension": r.destination_extension,
            "source_user_full_name": r.source_user_full_name,
            "source_user": r.source_user,
            "custom_tag": r.custom_tag,
            "source_sip_id": r.source_sip_id,
            "source_extension": r.source_extension,
            "result": r.result,
            "recorded": r.recorded,
        }

    return {
        "date_ist": today_str,
        "user": {
            "employee_code": user.employee_code,
            "name": user.name,
            "branch_id": user.branch_id,
            "vbc_extension_id": ext,
        },
        "stats": stats,
        "logs": {
            "page": page,
            "page_size": page_size,
            "total": total_logs,
            "records": [_serialize(r) for r in records],
            "order": order,
        },
    }
