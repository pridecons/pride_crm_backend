# ResearchReport.py
from typing import Optional, List, Dict
from datetime import date, datetime
import os, uuid
from fastapi import APIRouter, Depends, HTTPException, status, Query, Body, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.connection import get_db
from db.models import UserDetails
from db.Models.models_research import ResearchReport
from routes.auth.auth_dependency import get_current_user
import datetime as dt
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
    title: Optional[str] = None
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

# --------- Helpers ----------
def _to_out(rr: ResearchReport) -> ResearchReportOut:
    return ResearchReportOut(
        id=rr.id,
        report_date=rr.report_date,
        title=rr.title,
        notes=rr.notes,
        tags=rr.tags,
        ipo=rr.ipo,
        board_meeting=rr.board_meeting,
        corporate_action=rr.corporate_action,
        result_calendar=rr.result_calendar,
        top_gainers=rr.top_gainers,
        top_losers=rr.top_losers,
        fii_dii=rr.fii_dii,
        calls_index=rr.calls_index,
        calls_stock=rr.calls_stock,
        created_by=rr.created_by,
        created_at=rr.created_at,
        updated_at=rr.updated_at,
    )

# --------- Create ---------
@router.post("/", response_model=ResearchReportOut, status_code=status.HTTP_201_CREATED)
async def create_report(
    payload: ResearchReportIn = Body(...),
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user),
):
    rr = ResearchReport(
        report_date=payload.report_date,
        title=payload.title,
        notes=payload.notes,
        tags=payload.tags,
        ipo=(payload.ipo and [i.model_dump(exclude_none=True) for i in payload.ipo]) or None,
        board_meeting=(payload.board_meeting and [i.model_dump(exclude_none=True) for i in payload.board_meeting]) or None,
        corporate_action=(payload.corporate_action and [i.model_dump(exclude_none=True) for i in payload.corporate_action]) or None,
        result_calendar=(payload.result_calendar and [i.model_dump(exclude_none=True) for i in payload.result_calendar]) or None,
        top_gainers=(payload.top_gainers and [i.model_dump(exclude_none=True) for i in payload.top_gainers]) or None,
        top_losers=(payload.top_losers and [i.model_dump(exclude_none=True) for i in payload.top_losers]) or None,
        fii_dii=(payload.fii_dii and payload.fii_dii.model_dump(exclude_none=True)) or None,
        # ✅ split calls
        calls_index=(payload.calls_index and [i.model_dump(exclude_none=True) for i in payload.calls_index]) or None,
        calls_stock=(payload.calls_stock and [i.model_dump(exclude_none=True) for i in payload.calls_stock]) or None,
        created_by=getattr(current_user, "employee_code", None),
    )
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

