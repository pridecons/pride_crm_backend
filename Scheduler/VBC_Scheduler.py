from __future__ import annotations

from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import text
import httpx
import os
import logging

from db.connection import get_db, SessionLocal  # ensure SessionLocal is exported
from db.models import UserDetails
from db.Models.models_VBC import VBCReport
from routes.VBC_Calling.vbc_client import VBCEnv, VBCClient
from config import VBC_ACCOUNT_ID, API_CLIENT_ID, API_CLIENT_SECRET
from apscheduler.schedulers.background import BackgroundScheduler

router = APIRouter(prefix="/vbc-reports", tags=["vbc-call-reports"])
log = logging.getLogger("uvicorn.error")

def _last_hours_ist_window_strings(hours: int) -> Tuple[str, str]:
    tz = ZoneInfo("Asia/Kolkata")
    end_dt = datetime.now(tz).replace(microsecond=0)
    start_dt = (end_dt - timedelta(hours=hours)).replace(microsecond=0)
    return _fmt_dt(start_dt), _fmt_dt(end_dt)

# ----------------- helpers -----------------
def _token_cache_file_for(user: UserDetails) -> str:
    cache_dir = os.path.join(os.getcwd(), "vbc_token_cache")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"{user.employee_code}.json")

def _build_vbc_client_for_user(user: UserDetails) -> VBCClient:
    if not user or not user.vbc_user_username or not user.vbc_user_password:
        raise RuntimeError("User is missing VBC username/password.")
    env = VBCEnv(
        account_id=VBC_ACCOUNT_ID,
        vbc_user_username=user.vbc_user_username,
        vbc_user_password=user.vbc_user_password,
        client_id=API_CLIENT_ID,
        client_secret=API_CLIENT_SECRET,
    )
    return VBCClient(env, token_cache_path=_token_cache_file_for(user))

def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def _today_ist_window_strings() -> Tuple[str, str]:
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime.now(tz)
    start_dt = datetime.combine(now.date(), time(0, 0, 0), tzinfo=tz)
    end_dt = datetime.combine(now.date(), time(23, 59, 59), tzinfo=tz)
    return _fmt_dt(start_dt), _fmt_dt(end_dt)

def _extract_records(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        emb = payload.get("_embedded")
        if isinstance(emb, dict):
            cl = emb.get("call_logs")
            if isinstance(cl, list):
                return [x for x in cl if isinstance(x, dict)]
        for key in ("records", "data", "items", "result"):
            v = payload.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return [payload] if isinstance(payload, dict) else []

def _rows_from_payload(payload: Dict[str, Any]) -> list[dict]:
    recs = _extract_records(payload)
    rows: list[dict] = []
    for r in recs:
        rid = r.get("id")
        if not rid:
            continue
        rows.append({
            "id": str(rid),
            "in_network": None if r.get("in_network") is None else str(r.get("in_network")),
            "international": None if r.get("international") is None else str(r.get("international")),
            "extension_id": r.get("to") if r.get("direction")=="Inbound" else str(r.get("from")),
            "to": r.get("from") if r.get("direction")=="Inbound" else str(r.get("to")),
            "direction": None if r.get("direction") is None else str(r.get("direction")),
            "length": None if r.get("length") is None else str(r.get("length")),
            "start": None if r.get("start") is None else str(r.get("start")),
            "end": None if r.get("end") is None else str(r.get("end")),
            "charge": None if r.get("charge") is None else str(r.get("charge")),
            "rate": None if r.get("rate") is None else str(r.get("rate")),
            "destination_device_name": None if r.get("destination_device_name") is None else str(r.get("destination_device_name")),
            "source_device_name": None if r.get("source_device_name") is None else str(r.get("source_device_name")),
            "destination_user_full_name": None if r.get("destination_user_full_name") is None else str(r.get("destination_user_full_name")),
            "destination_user": None if r.get("destination_user") is None else str(r.get("destination_user")),
            "destination_sip_id": None if r.get("destination_sip_id") is None else str(r.get("destination_sip_id")),
            "destination_extension": None if r.get("destination_extension") is None else str(r.get("destination_extension")),
            "source_user_full_name": None if r.get("source_user_full_name") is None else str(r.get("source_user_full_name")),
            "source_user": None if r.get("source_user") is None else str(r.get("source_user")),
            "custom_tag": None if r.get("custom_tag") is None else str(r.get("custom_tag")),
            "source_sip_id": None if r.get("source_sip_id") is None else str(r.get("source_sip_id")),
            "source_extension": None if r.get("source_extension") is None else str(r.get("source_extension")),
            "result": None if r.get("result") is None else str(r.get("result")),
            "recorded": None if r.get("recorded") is None else str(r.get("recorded")),
        })
    return rows

def _bulk_insert_skip_dupes(db: Session, rows: list[dict]) -> Tuple[int, int]:
    """
    Insert into crm_vbc_reports using ON CONFLICT DO NOTHING on (id).
    Returns (inserted_count, skipped_count).
    """
    if not rows:
        return (0, 0)

    # De-dupe within batch by id
    seen = set()
    deduped = []
    for row in rows:
        rid = row["id"]
        if rid in seen:
            continue
        seen.add(rid)
        deduped.append(row)

    stmt = pg_insert(VBCReport.__table__).values(deduped)
    stmt = stmt.on_conflict_do_nothing(index_elements=["id"])

    res = db.execute(stmt)
    inserted = res.rowcount or 0
    skipped = len(deduped) - inserted
    db.commit()
    return (inserted, skipped)

# ----------------- core ingest (re-usable by API + scheduler) -----------------
def ingest_call_logs_window(
    db: Session,
    *,
    start_gte: str,
    start_lte: str,
    page_size: int = 5000,
    auth_employee_code: str = "ADMIN001",
) -> Dict[str, Any]:
    """
    Pull ALL pages for the given window and save to crm_vbc_reports.
    Idempotent via ON CONFLICT DO NOTHING.
    """
    # Optional: advisory lock to avoid concurrent ingests stepping on each other
    db.execute(text("SELECT pg_advisory_lock(:k)"), {"k": 424283})
    try:
        user: Optional[UserDetails] = (
            db.query(UserDetails)
            .filter(UserDetails.employee_code == auth_employee_code)
            .first()
        )
        if not user:
            raise RuntimeError(f"{auth_employee_code} user not found.")
        client = _build_vbc_client_for_user(user)

        # First page
        try:
            first = client.reports_call_logs(
                start_gte=start_gte,
                start_lte=start_lte,
                page_size=page_size,
                page=1,
            )
        except httpx.HTTPStatusError as e:
            try:
                detail = e.response.json()
            except Exception:
                detail = e.response.text
            raise RuntimeError(f"Vonage error: {detail}")

        total_items = int(first.get("total_items", 0)) if isinstance(first, dict) else 0
        total_page = int(first.get("total_page", 1)) if isinstance(first, dict) else 1

        received_total = 0
        inserted_total = 0
        skipped_total = 0

        def _save_payload(db_sess: Session, payload: Dict[str, Any]) -> tuple[int, int, int]:
            rows = _rows_from_payload(payload)
            received = len(rows)
            inserted, skipped = _bulk_insert_skip_dupes(db_sess, rows)
            return (received, inserted, skipped)

        # Save first page
        rcv, ins, skp = _save_payload(db, first)
        received_total += rcv
        inserted_total += ins
        skipped_total += skp

        # Save remaining pages
        for page in range(2, max(2, total_page + 1)):
            try:
                payload = client.reports_call_logs(
                    start_gte=start_gte,
                    start_lte=start_lte,
                    page_size=page_size,
                    page=page,
                )
            except httpx.HTTPStatusError as e:
                try:
                    detail = e.response.json()
                except Exception:
                    detail = e.response.text
                raise RuntimeError(f"Vonage error on page {page}: {detail}")

            rcv, ins, skp = _save_payload(db, payload)  # ✅ pass db
            received_total += rcv
            inserted_total += ins
            skipped_total += skp

        summary = {
            "window_used": {"start_gte": start_gte, "start_lte": start_lte},
            "page_size": page_size,
            "vonage_total_items": total_items,
            "vonage_total_pages": total_page,
            "received_records": received_total,
            "inserted_new": inserted_total,
            "skipped_existing": skipped_total,
        }
        log.info("VBC ingest summary: %s", summary)
        return summary
    finally:
        db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": 424283})

# ----------------- Background entrypoint -----------------
def _run_ingest_job(start_gte: str, start_lte: str, page_size: int, auth_employee_code: str) -> None:
    """Background task entrypoint; creates its own DB session."""
    db = SessionLocal()
    try:
        ingest_call_logs_window(
            db,
            start_gte=start_gte,
            start_lte=start_lte,
            page_size=page_size,
            auth_employee_code=auth_employee_code,
        )
    except Exception as e:
        log.exception("VBC ingest job failed: %s", e)
    finally:
        db.close()

# ----------------- API: trigger as background task -----------------
@router.post("/ingest")
def trigger_ingest(
    background_tasks: BackgroundTasks,
    *,
    start_gte: Optional[str] = Query(None, description="YYYY-MM-DD HH:mm:ss (inclusive)"),
    start_lte: Optional[str] = Query(None, description="YYYY-MM-DD HH:mm:ss (inclusive)"),
    page_size: int = Query(5000, ge=1, le=5000),
    auth_employee_code: str = Query("ADMIN001"),
) -> Dict[str, Any]:
    """
    Queues an ingest job in the background.
    Defaults to today's full day (IST) if dates are omitted.
    """
    if not start_gte or not start_lte:
        start_gte, start_lte = _today_ist_window_strings()

    background_tasks.add_task(_run_ingest_job, start_gte, start_lte, page_size, auth_employee_code)
    return {
        "queued": True,
        "window_used": {"start_gte": start_gte, "start_lte": start_lte},
        "page_size": page_size,
        "auth_employee_code": auth_employee_code,
        "note": "Ingest is running in the background.",
    }

# ----------------- API: run NOW (synchronously) -----------------
@router.post("/ingest/run-now")
def run_ingest_now(
    *,
    db: Session = Depends(get_db),
    start_gte: Optional[str] = Query(None),
    start_lte: Optional[str] = Query(None),
    page_size: int = Query(5000, ge=1, le=5000),
    auth_employee_code: str = Query("ADMIN001"),
) -> Dict[str, Any]:
    """Runs ingest and returns the summary when done (blocking)."""
    if not start_gte or not start_lte:
        start_gte, start_lte = _today_ist_window_strings()
    try:
        return ingest_call_logs_window(
            db,
            start_gte=start_gte,
            start_lte=start_lte,
            page_size=page_size,
            auth_employee_code=auth_employee_code,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
_scheduler: Optional[BackgroundScheduler] = None

def _ingest_last_2_hours_job():
    """
    APScheduler job: runs ingest for the last 2 hours (IST).
    Uses same background entrypoint that creates its own DB session.
    """
    try:
        start_gte, start_lte = _last_hours_ist_window_strings(2)
        # page_size और auth_employee_code चाहें तो config से लें
        _run_ingest_job(start_gte, start_lte, page_size=5000, auth_employee_code="ADMIN001")
        log.info("VBC 2h job OK: %s -> %s", start_gte, start_lte)
    except Exception as e:
        log.exception("VBC 2h job failed: %s", e)

def start_vbc_ingest_scheduler(interval_hours: int = 2):
    """
    Call this from FastAPI startup. Starts a background scheduler that
    runs `_ingest_last_2_hours_job` every `interval_hours`.
    """
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    _scheduler.add_job(
        _ingest_last_2_hours_job,
        trigger="interval",
        hours=interval_hours,
        id="vbc_ingest_2h",
        replace_existing=True,
        coalesce=True,        # missed runs को merge कर देगा
        max_instances=1       # overlap नहीं होगा
    )
    _scheduler.start()
    log.info("VBC ingest scheduler started (every %sh)", interval_hours)

def stop_vbc_ingest_scheduler():
    """Call this from FastAPI shutdown to stop scheduler cleanly."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("VBC ingest scheduler stopped")
