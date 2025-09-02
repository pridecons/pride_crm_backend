# routes/VBC_Calling/Create_call.py
from __future__ import annotations

import os
from typing import Optional, Literal, Dict, Any
import re
import httpx
from fastapi import APIRouter, HTTPException, status, Depends, Query, Path
from pydantic import BaseModel, constr, Field, validator
from db.models import UserDetails
from routes.auth.auth_dependency import get_current_user

from routes.VBC_Calling.vbc_client import VBCClient, VBCEnv
from config import VBC_ACCOUNT_ID, API_CLIENT_ID, API_CLIENT_SECRET

from datetime import datetime, timedelta, timezone
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/vbc", tags=["vbc-calls"])

# =========================
# Common helpers
# =========================
E164_LIKE = re.compile(r"^\+?\d{5,}$")

def _normalize_dst(num: str) -> str:
    """Keep + and digits only; basic E.164-ish guard."""
    num = re.sub(r"[^\d+]", "", num or "")
    if not E164_LIKE.match(num):
        raise HTTPException(
            status_code=400,
            detail="Phone number must contain only digits (optionally starting with +).",
        )
    return num

def _token_cache_file_for(user: UserDetails) -> str:
    """
    Per-user token cache file (persists access/refresh tokens & expiry).
    """
    cache_dir = os.path.join(os.getcwd(), "vbc_token_cache")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"{user.employee_code}.json")

def _build_vbc_client_for_user(user: UserDetails) -> VBCClient:
    """
    Build a fresh VBC client using the current user's Vonage username/password.
    Account/client id/secret come from env (config).
    Uses on-disk token cache so tokens survive process restarts.
    """
    if not user.vbc_user_username or not user.vbc_user_password:
        raise HTTPException(
            status_code=400,
            detail="VBC credentials are not configured for this user (username/password missing).",
        )
    env = VBCEnv(
        account_id=VBC_ACCOUNT_ID,
        vbc_user_username=user.vbc_user_username,
        vbc_user_password=user.vbc_user_password,
        client_id=API_CLIENT_ID,
        client_secret=API_CLIENT_SECRET,
    )
    return VBCClient(env, token_cache_path=_token_cache_file_for(user))

def _raise_for_httpx(e: httpx.HTTPStatusError, msg: str):
    try:
        detail = e.response.json()
    except Exception:
        detail = e.response.text
    raise HTTPException(status_code=502, detail={"error": msg, "detail": detail})


# =========================
# Schemas
# =========================
class Click2DialRequest(BaseModel):
    # allow numbers like "17735551234" or "+17735551234"
    to_number: constr(strip_whitespace=True, min_length=5)

    @validator("to_number")
    def _v_num(cls, v: str) -> str:
        _ = _normalize_dst(v)
        return v

class Party(BaseModel):
    destination: constr(strip_whitespace=True, min_length=1)
    type: Literal["pstn", "extension"]

    @validator("destination")
    def _clean_dest(cls, v, values):
        if values.get("type") == "pstn":
            return _normalize_dst(v)
        return v.strip()

class CallUpdatePayload(BaseModel):
    # keyword 'from' is reserved in python -> alias
    from_: Optional[Party] = Field(default=None, alias="from")
    to: Optional[Party] = None

    class Config:
        populate_by_name = True

class LegDtmfPayload(BaseModel):
    dtmf: constr(min_length=1, max_length=32)

class LegStatePayload(BaseModel):
    # passthrough; many backends accept {"state":"held"} or similar
    state: constr(strip_whitespace=True, min_length=2)


# =========================
# Create Call
# =========================
@router.post(
    "/call",
    status_code=status.HTTP_201_CREATED,
    summary="Place a VBC click2dial call (from the current user's extension)",
)
def create_call_api(
    payload: Click2DialRequest,
    current_user: UserDetails = Depends(get_current_user),
):
    """
    POST /vbc/call
    Body: { "to_number": "+17735551234" }

    Uses the logged-in user's:
      - vbc_extension_id as the 'from' extension
      - vbc_user_username / vbc_user_password to authenticate against VBC

    Tokens are fetched/refreshed automatically and cached on disk per user.
    """
    if not current_user.vbc_extension_id:
        raise HTTPException(status_code=400, detail="VBC extension is not configured for this user.")

    dst = _normalize_dst(payload.to_number)
    client = _build_vbc_client_for_user(current_user)

    try:
        resp = client.telephony_click2dial(
            from_type="extension",
            from_destination=str(current_user.vbc_extension_id),
            to_type="pstn",
            to_destination=dst,
        )
        return {
            "message": "Call created",
            "from_extension": str(current_user.vbc_extension_id),
            "to_number": dst,
            "vbc_response": resp,
        }
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "VBC call failed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error placing call: {e}")


# =========================
# Calls: list / get / update / delete
# =========================
@router.get(
    "/calls",
    summary="List active/recent calls (scoped to your account)",
)
def list_calls_api(
    page_size: Optional[int] = Query(None, ge=1, le=200),
    page: Optional[int] = Query(None, ge=1),
    extension: Optional[str] = Query(None, description="Filter by extension"),
    order: Optional[Literal["asc", "desc"]] = Query(None),
    start_time: Optional[int] = Query(None, description="Epoch seconds >= start"),
    end_time: Optional[int] = Query(None, description="Epoch seconds <= end"),
    current_user: UserDetails = Depends(get_current_user),
):
    client = _build_vbc_client_for_user(current_user)
    try:
        filters: Dict[str, Any] = {}
        if page_size is not None:
            filters["page_size"] = page_size
        if page is not None:
            filters["page"] = page
        if extension:
            filters["extension"] = extension
        if order:
            filters["order"] = order
        if start_time is not None:
            filters["start_time"] = start_time
        if end_time is not None:
            filters["end_time"] = end_time

        resp = client.telephony_calls(**filters)
        return {"filters": filters, "vbc_response": resp}
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to list calls")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error listing calls: {e}")


@router.get(
    "/calls/{call_id}",
    summary="Get a specific call by ID",
)
def get_call_api(
    call_id: str = Path(..., min_length=1),
    current_user: UserDetails = Depends(get_current_user),
):
    client = _build_vbc_client_for_user(current_user)
    try:
        resp = client.telephony_call(call_id)
        return {"call_id": call_id, "vbc_response": resp}
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to fetch call")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


@router.put(
    "/calls/{call_id}",
    summary="Update a call (e.g., transfer legs)",
)
def update_call_api(
    payload: CallUpdatePayload,
    call_id: str = Path(..., min_length=1),
    current_user: UserDetails = Depends(get_current_user),
):
    client = _build_vbc_client_for_user(current_user)
    try:
        # build payload exactly as VBC expects ("from" key, not "from_")
        body: Dict[str, Any] = {}
        if payload.from_ is not None:
            body["from"] = payload.from_.model_dump()
        if payload.to is not None:
            body["to"] = payload.to.model_dump()

        if not body:
            raise HTTPException(status_code=400, detail="Nothing to update; provide at least 'from' or 'to'.")

        resp = client.telephony_call_update(call_id, body)
        return {"call_id": call_id, "request": body, "vbc_response": resp}
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to update call")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


@router.delete(
    "/calls/{call_id}",
    status_code=status.HTTP_200_OK,
    summary="End a call",
)
def delete_call_api(
    call_id: str = Path(..., min_length=1),
    current_user: UserDetails = Depends(get_current_user),
):
    """
    Ends the call. Backend typically does not require a body for delete.
    """
    client = _build_vbc_client_for_user(current_user)
    try:
        resp = client.telephony_call_delete(call_id, payload={})
        return {"message": "Call ended", "call_id": call_id, "vbc_response": resp}
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to end call")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


# =========================
# Call Legs
# =========================
@router.get(
    "/calls/{call_id}/legs",
    summary="List legs for a call",
)
def list_call_legs_api(
    call_id: str = Path(..., min_length=1),
    current_user: UserDetails = Depends(get_current_user),
):
    client = _build_vbc_client_for_user(current_user)
    try:
        resp = client.telephony_call_legs(call_id)
        return {"call_id": call_id, "vbc_response": resp}
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to list call legs")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


@router.get(
    "/calls/{call_id}/legs/{leg_id}",
    summary="Get leg details",
)
def get_call_leg_api(
    call_id: str = Path(..., min_length=1),
    leg_id: str = Path(..., min_length=1),
    current_user: UserDetails = Depends(get_current_user),
):
    client = _build_vbc_client_for_user(current_user)
    try:
        resp = client.telephony_call_leg(call_id, leg_id)
        return {"call_id": call_id, "leg_id": leg_id, "vbc_response": resp}
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to fetch leg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


@router.put(
    "/calls/{call_id}/legs/{leg_id}",
    summary="Send DTMF to a leg",
)
def put_call_leg_api(
    payload: LegDtmfPayload,
    call_id: str = Path(..., min_length=1),
    leg_id: str = Path(..., min_length=1),
    current_user: UserDetails = Depends(get_current_user),
):
    client = _build_vbc_client_for_user(current_user)
    try:
        body = payload.model_dump()
        resp = client.telephony_call_leg_put(call_id, leg_id, payload=body)
        return {"call_id": call_id, "leg_id": leg_id, "request": body, "vbc_response": resp}
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to update leg (DTMF)")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


@router.delete(
    "/calls/{call_id}/legs/{leg_id}",
    summary="Modify/terminate a leg (provider-dependent)",
)
def delete_call_leg_api(
    call_id: str = Path(..., min_length=1),
    leg_id: str = Path(..., min_length=1),
    payload: Optional[LegStatePayload] = None,
    current_user: UserDetails = Depends(get_current_user),
):
    """
    Some backends accept a body like {"state":"held"} when deleting a leg.
    If your backend does not require a body, this will still send an empty JSON.
    """
    client = _build_vbc_client_for_user(current_user)
    try:
        body = payload.model_dump() if payload else {}
        resp = client.telephony_call_leg_delete(call_id, leg_id, payload=body)
        return {
            "message": "Leg modified/terminated",
            "call_id": call_id,
            "leg_id": leg_id,
            "request": body,
            "vbc_response": resp,
        }
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to delete/modify leg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


# =========================
# Devices (registrations)
# =========================
@router.get(
    "/devices",
    summary="List registered devices (SIP/softphone) for the account",
)
def list_devices_api(
    page_size: Optional[int] = Query(None, ge=1, le=200),
    page: Optional[int] = Query(None, ge=1),
    order: Optional[Literal["asc", "desc"]] = Query(None),
    start_time: Optional[int] = Query(None, description="Epoch seconds >= start"),
    end_time: Optional[int] = Query(None, description="Epoch seconds <= end"),
    current_user: UserDetails = Depends(get_current_user),
):
    client = _build_vbc_client_for_user(current_user)
    try:
        filters: Dict[str, Any] = {}
        if page_size is not None:
            filters["page_size"] = page_size
        if page is not None:
            filters["page"] = page
        if order:
            filters["order"] = order
        if start_time is not None:
            filters["start_time"] = start_time
        if end_time is not None:
            filters["end_time"] = end_time

        resp = client.telephony_devices(**filters)
        return {"filters": filters, "vbc_response": resp}
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to list devices")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


@router.get(
    "/devices/{device_id}",
    summary="Get a device by ID",
)
def get_device_api(
    device_id: str = Path(..., min_length=1),
    current_user: UserDetails = Depends(get_current_user),
):
    client = _build_vbc_client_for_user(current_user)
    try:
        resp = client.telephony_device(device_id)
        return {"device_id": device_id, "vbc_response": resp}
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to fetch device")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


# ========= Call Recording helpers =========
def _to_iso_z(dt: datetime) -> str:
    return dt.replace(microsecond=0, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _cr_bounds_or_default(start_gte: str | None, start_lte: str | None, days: int = 1) -> tuple[str, str]:
    if start_gte and start_lte:
        return start_gte, start_lte
    # default last N days (UTC)
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days)
    return _to_iso_z(start_dt), _to_iso_z(end_dt)

# ========== COMPANY CALL RECORDINGS ==========
@router.get("/cr/company", summary="List company call recordings")
def cr_company_list_api(
    start_gte: str | None = None,
    start_lte: str | None = None,
    page_size: int = Query(20, ge=1, le=200),
    page: int = Query(1, ge=1),
    call_direction: str | None = Query(None, description="INBOUND | OUTBOUND | INTRA_PBX"),
    call_id: str | None = None,
    caller_id: str | None = None,
    cnam: str | None = None,
    dnis: str | None = Query(None, description="cc+number"),
    duration_gte: int | None = None,
    duration_lte: int | None = None,
    extension: str | None = None,
    order: str | None = Query(None, description="start:DESC"),
    current_user: UserDetails = Depends(get_current_user),
):
    client = _build_vbc_client_for_user(current_user)
    s_gte, s_lte = _cr_bounds_or_default(start_gte, start_lte)

    filters = {
        "call_direction": call_direction,
        "call_id": call_id,
        "caller_id": caller_id,
        "cnam": cnam,
        "dnis": dnis,
        "duration:gte": duration_gte,
        "duration:lte": duration_lte,
        "extension": extension,
        "order": order,
    }
    filters = {k: v for k, v in filters.items() if v is not None}

    try:
        data = client.cr_company_list(
            start_gte=s_gte, start_lte=s_lte, page_size=page_size, page=page, **filters
        )
        return {"window": {"start_gte": s_gte, "start_lte": s_lte}, "filters": filters, "vbc_response": data}
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to list company recordings")

@router.get("/cr/company/{recording_id}", summary="Get company recording by id")
def cr_company_get_api(
    recording_id: str,
    current_user: UserDetails = Depends(get_current_user),
):
    client = _build_vbc_client_for_user(current_user)
    try:
        data = client.cr_company_get(recording_id)
        return {"recording_id": recording_id, "vbc_response": data}
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to fetch company recording")

@router.delete("/cr/company/{recording_id}", summary="Delete company recording")
def cr_company_delete_api(
    recording_id: str,
    current_user: UserDetails = Depends(get_current_user),
):
    client = _build_vbc_client_for_user(current_user)
    try:
        data = client.cr_company_delete(recording_id)
        return {"message": "Recording deleted", "recording_id": recording_id, "vbc_response": data}
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to delete company recording")

@router.post("/cr/company/export", summary="Export company recordings (creates job)")
def cr_company_export_api(
    start_gte: str | None = None,
    start_lte: str | None = None,
    current_user: UserDetails = Depends(get_current_user),
):
    client = _build_vbc_client_for_user(current_user)
    s_gte, s_lte = _cr_bounds_or_default(start_gte, start_lte)
    try:
        data = client.cr_company_export(start_gte=s_gte, start_lte=s_lte)
        return {"window": {"start_gte": s_gte, "start_lte": s_lte}, "vbc_response": data}
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to request export for company recordings")

@router.get("/cr/audio/{recording_id}", summary="Download company recording audio")
def cr_company_audio_api(
    recording_id: str,
    filename: str | None = Query(None, description="Optional download filename (e.g., rec.mp3)"),
    current_user: UserDetails = Depends(get_current_user),
):
    client = _build_vbc_client_for_user(current_user)
    try:
        audio_bytes = client.cr_company_audio(recording_id)
        fname = filename or f"recording_{recording_id}.bin"
        headers = {"Content-Disposition": f'attachment; filename="{fname}"'}
        return StreamingResponse(iter([audio_bytes]), media_type="application/octet-stream", headers=headers)
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to download recording audio")

# ========== ON-DEMAND (USER) RECORDINGS ==========
@router.get("/cr/user", summary="List on-demand recordings for a user (defaults to self)")
def cr_user_list_api(
    start_gte: str | None = None,
    start_lte: str | None = None,
    page_size: int = Query(20, ge=1, le=200),
    page: int = Query(1, ge=1),
    user_id: str = Query("self", description="Use 'self' (default) or a specific user_id if allowed"),
    call_direction: str | None = Query(None, description="INBOUND | OUTBOUND | INTRA_PBX"),
    call_id: str | None = None,
    caller_id: str | None = None,
    cnam: str | None = None,
    dnis: str | None = None,
    duration_gte: int | None = None,
    duration_lte: int | None = None,
    extension: str | None = None,
    order: str | None = None,
    current_user: UserDetails = Depends(get_current_user),
):
    client = _build_vbc_client_for_user(current_user)
    s_gte, s_lte = _cr_bounds_or_default(start_gte, start_lte)

    filters = {
        "call_direction": call_direction,
        "call_id": call_id,
        "caller_id": caller_id,
        "cnam": cnam,
        "dnis": dnis,
        "duration:gte": duration_gte,
        "duration:lte": duration_lte,
        "extension": extension,
        "order": order,
    }
    filters = {k: v for k, v in filters.items() if v is not None}

    try:
        data = client.cr_user_list(user_id=user_id, start_gte=s_gte, start_lte=s_lte, page_size=page_size, page=page, **filters)
        return {"window": {"start_gte": s_gte, "start_lte": s_lte}, "user_id": user_id, "filters": filters, "vbc_response": data}
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to list user recordings")

@router.get("/cr/user/{recording_id}", summary="Get one on-demand recording (self by default)")
def cr_user_get_api(
    recording_id: str,
    user_id: str = Query("self"),
    current_user: UserDetails = Depends(get_current_user),
):
    client = _build_vbc_client_for_user(current_user)
    try:
        data = client.cr_user_get(user_id=user_id, recording_id=recording_id)
        return {"user_id": user_id, "recording_id": recording_id, "vbc_response": data}
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to fetch user recording")

@router.delete("/cr/user/{recording_id}", summary="Delete on-demand recording (self by default)")
def cr_user_delete_api(
    recording_id: str,
    user_id: str = Query("self"),
    current_user: UserDetails = Depends(get_current_user),
):
    client = _build_vbc_client_for_user(current_user)
    try:
        data = client.cr_user_delete(user_id=user_id, recording_id=recording_id)
        return {"message": "Recording deleted", "user_id": user_id, "recording_id": recording_id, "vbc_response": data}
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to delete user recording")

@router.post("/cr/user/export", summary="Export on-demand recordings (self by default)")
def cr_user_export_api(
    user_id: str = Query("self"),
    start_gte: str | None = None,
    start_lte: str | None = None,
    current_user: UserDetails = Depends(get_current_user),
):
    client = _build_vbc_client_for_user(current_user)
    s_gte, s_lte = _cr_bounds_or_default(start_gte, start_lte)
    try:
        data = client.cr_user_export(user_id=user_id, start_gte=s_gte, start_lte=s_lte)
        return {"user_id": user_id, "window": {"start_gte": s_gte, "start_lte": s_lte}, "vbc_response": data}
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to request export for user recordings")

@router.get("/cr/user/jobs", summary="List export jobs (self by default)")
def cr_user_jobs_api(
    user_id: str = Query("self"),
    status_filter: str | None = Query(None, alias="status"),
    current_user: UserDetails = Depends(get_current_user),
):
    client = _build_vbc_client_for_user(current_user)
    try:
        filters = {"status": status_filter} if status_filter else {}
        data = client.cr_user_jobs(user_id=user_id, **filters)
        return {"user_id": user_id, "filters": filters, "vbc_response": data}
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to list export jobs")

@router.get("/cr/user/jobs/{job_id}", summary="Get a specific export job (self by default)")
def cr_user_job_api(
    job_id: str,
    user_id: str = Query("self"),
    current_user: UserDetails = Depends(get_current_user),
):
    client = _build_vbc_client_for_user(current_user)
    try:
        data = client.cr_user_job(job_id=job_id, user_id=user_id)
        return {"user_id": user_id, "job_id": job_id, "vbc_response": data}
    except httpx.HTTPStatusError as e:
        _raise_for_httpx(e, "Failed to fetch export job")

