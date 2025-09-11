# routes/Research_Report/ResearchReport.py
from typing import Optional, List, Dict
from datetime import date, datetime
import os, uuid
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status, Body, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.inspection import inspect

from db.connection import get_db
from db.models import UserDetails
from db.Models.models_research import ResearchReport
from routes.auth.auth_dependency import get_current_user
from routes.Research_Report.generateResearchPdf import generate_outlook_pdf

# (Optionally fetch from settings/env)
STATIC_UPLOAD_DIR = os.getenv("STATIC_UPLOAD_DIR", "static/uploads")
STATIC_BASE_URL   = os.getenv("STATIC_BASE_URL", "/static/uploads")

router = APIRouter(prefix="/research", tags=["Research Report"])

# --------- Schemas ---------
class IPOItem(BaseModel):
    company: Optional[str] = None
    lot_size: Optional[int] = None
    price_range: Optional[str] = None
    open_date: Optional[date] = None
    close_date: Optional[date] = None
    category: Optional[str] = None

class BoardMeetingItem(BaseModel):
    company: Optional[str] = None
    date: Optional[dt.date] = None
    agenda: Optional[str] = None

class CorporateActionItem(BaseModel):
    company: Optional[str] = None
    action: Optional[str] = None
    ex_date: Optional[date] = None
    details: Optional[str] = None

class ResultCalendarItem(BaseModel):
    company: Optional[str] = None
    date: Optional[dt.date] = None
    type: Optional[str] = None
    ltp: Optional[float] = None
    change: Optional[float] = None

class GainLoseItem(BaseModel):
    symbol: Optional[str] = None
    cmp: Optional[float] = None
    price_change: Optional[float] = None
    change_pct: Optional[float] = None

class FiiDiiBlock(BaseModel):
    date: Optional[dt.date] = None
    fii_fpi: Optional[Dict[str, Optional[float]]] = None
    dii: Optional[Dict[str, Optional[float]]] = None

class CallItem(BaseModel):
    symbol: Optional[str] = None
    view: Optional[str] = None     # BULLISH / BEARISH / NEUTRAL
    entry_at: Optional[float] = None
    buy_above: Optional[float] = None
    t1: Optional[float] = None
    t2: Optional[float] = None
    sl: Optional[float] = None
    # ✅ chart_url filled by /research/upload-chart
    chart_url: Optional[str] = None

class ResearchReportIn(BaseModel):
    report_date: Optional[date] = None
    title: Optional[str] = None          # may not exist on DB model; OK to keep in API
    notes: Optional[str] = None
    tags: Optional[List[str]] = None

    ipo: Optional[List[IPOItem]] = None
    board_meeting: Optional[List[BoardMeetingItem]] = None
    corporate_action: Optional[List[CorporateActionItem]] = None
    result_calendar: Optional[List[ResultCalendarItem]] = None
    top_gainers: Optional[List[GainLoseItem]] = None
    top_losers: Optional[List[GainLoseItem]] = None
    fii_dii: Optional[FiiDiiBlock] = None

    # ✅ separate picks
    calls_index: Optional[List[CallItem]] = None
    calls_stock: Optional[List[CallItem]] = None

class ResearchReportOut(ResearchReportIn):
    id: int
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None

    class Config:
        from_attributes = True

# --------- Internal helpers ----------
def _list_or_none(items):
    return [i.model_dump(exclude_none=True) for i in items] if items else None

def _dict_or_none(obj):
    return obj.model_dump(exclude_none=True) if obj else None

# --------- Presenter ----------
def _to_out(rr: ResearchReport) -> ResearchReportOut:
    # Use getattr to avoid AttributeError when columns are dropped on the ORM
    return ResearchReportOut(
        id=rr.id,
        report_date=getattr(rr, "report_date", None),
        title=getattr(rr, "title", None),  # will be None if column removed in ORM
        notes=getattr(rr, "notes", None),
        tags=getattr(rr, "tags", None),
        ipo=getattr(rr, "ipo", None),
        board_meeting=getattr(rr, "board_meeting", None),
        corporate_action=getattr(rr, "corporate_action", None),
        result_calendar=getattr(rr, "result_calendar", None),
        top_gainers=getattr(rr, "top_gainers", None),
        top_losers=getattr(rr, "top_losers", None),
        fii_dii=getattr(rr, "fii_dii", None),
        calls_index=getattr(rr, "calls_index", None),
        calls_stock=getattr(rr, "calls_stock", None),
        created_by=getattr(rr, "created_by", None),
        created_at=getattr(rr, "created_at", None),
        updated_at=getattr(rr, "updated_at", None),
    )

# --------- Create ---------
@router.post("/", response_model=ResearchReportOut, status_code=status.HTTP_201_CREATED)
async def create_report(
    payload: ResearchReportIn = Body(...),
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user),
):
    # Build incoming dict from Pydantic payload (lists/dicts cleaned)
    incoming = {
        "report_date": payload.report_date,
        # "title": payload.title,   # <- DO NOT pass into ORM if column is removed
        "notes": payload.notes,
        "tags": payload.tags,

        "ipo": _list_or_none(payload.ipo),
        "board_meeting": _list_or_none(payload.board_meeting),
        "corporate_action": _list_or_none(payload.corporate_action),
        "result_calendar": _list_or_none(payload.result_calendar),

        "top_gainers": _list_or_none(payload.top_gainers),
        "top_losers": _list_or_none(payload.top_losers),
        "fii_dii": _dict_or_none(payload.fii_dii),

        "calls_index": _list_or_none(payload.calls_index),
        "calls_stock": _list_or_none(payload.calls_stock),

        "created_by": getattr(current_user, "employee_code", None),
    }

    # Keep only keys that are actual ORM columns to avoid "invalid keyword argument"
    model_cols = {attr.key for attr in inspect(ResearchReport).mapper.column_attrs}
    clean_kwargs = {k: v for k, v in incoming.items() if k in model_cols}

    rr = ResearchReport(**clean_kwargs)

    # ✅ The PDF generator is now resilient to missing attributes (see file below)
    await generate_outlook_pdf(rr)

    db.add(rr)
    db.commit()
    db.refresh(rr)
    return _to_out(rr)

# --------- Chart Upload (returns URL) ---------
@router.post("/upload-chart", status_code=201)
def upload_chart_image(
    file: UploadFile = File(...),
    current_user: UserDetails = Depends(get_current_user),
):
    # Validate mime
    if file.content_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(400, "Only PNG/JPEG/WEBP allowed")

    # Build path: static/uploads/research_charts/YYYY/MM/
    today = datetime.utcnow()
    subdir = os.path.join("research_charts", today.strftime("%Y"), today.strftime("%m"))
    out_dir = os.path.join(STATIC_UPLOAD_DIR, subdir)
    os.makedirs(out_dir, exist_ok=True)

    ext = ".png"
    if file.content_type == "image/jpeg":
        ext = ".jpg"
    elif file.content_type == "image/webp":
        ext = ".webp"

    fname = f"{uuid.uuid4().hex}{ext}"
    fpath = os.path.join(out_dir, fname)

    with open(fpath, "wb") as out:
        out.write(file.file.read())

    # Public URL
    url = "/".join([STATIC_BASE_URL.rstrip("/"), subdir.replace("\\", "/"), fname])
    return {"url": url}


