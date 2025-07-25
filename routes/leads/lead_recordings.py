import os
import uuid
import shutil
from datetime import datetime
from typing import List, Optional

from fastapi import (
    APIRouter, Depends, HTTPException, status,
    UploadFile, File, Form, Response, Query
)
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import date
from db.connection import get_db
from db.models import LeadRecording
from sqlalchemy import func

# where to store uploaded recordings
UPLOAD_DIR = "static/recordings"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ─── Pydantic schemas ───────────────────────────────────────────────────────────

class LeadRecordingOut(BaseModel):
    id: int
    lead_id: int
    employee_code: Optional[str]
    recording_url: str
    created_at: datetime

    class Config:
        from_attributes = True

# ─── Router ─────────────────────────────────────────────────────────────────────

router = APIRouter(
    prefix="/recordings",
    tags=["lead_recordings"],
)

@router.get("/", response_model=List[LeadRecordingOut])
def list_recordings(
    lead_id: Optional[int]          = Query(None, description="Filter by lead ID"),
    employee_code: Optional[str]    = Query(None, description="Filter by employee code"),
    created_date: Optional[date]    = Query(None, description="Filter by creation date (YYYY‑MM‑DD)"),
    db: Session                     = Depends(get_db)
):
    q = db.query(LeadRecording)

    if lead_id is not None:
        q = q.filter(LeadRecording.lead_id == lead_id)

    if employee_code is not None:
        q = q.filter(LeadRecording.employee_code == employee_code)

    if created_date is not None:
        # Compare only the date part of created_at
        q = q.filter(func.date(LeadRecording.created_at) == created_date)

    recordings = q.order_by(LeadRecording.created_at.desc()).all()

    if not recordings:
        raise HTTPException(status_code=404, detail="No recordings found with given filters")

    return recordings


@router.get(
    "/lead/{lead_id}",
    response_model=List[LeadRecordingOut],
    summary="Get all recordings for a specific lead"
)
def get_recordings_for_lead(
    lead_id: int,
    db: Session = Depends(get_db)
):
    recordings = (
        db.query(LeadRecording)
          .filter(LeadRecording.lead_id == lead_id)
          .order_by(LeadRecording.created_at.desc())
          .all()
    )
    if not recordings:
        raise HTTPException(status_code=404, detail="No recordings found for this lead")
    return recordings

@router.post(
    "/",
    response_model=LeadRecordingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a new lead recording"
)
def upload_recording(
    lead_id: int        = Form(..., description="ID of the lead"),
    employee_code: Optional[str] = Form(
        None, description="(optional) employee_code of the recorder"
    ),
    file: UploadFile     = File(..., description="Audio/video file"),
    db: Session          = Depends(get_db)
):
    # 1) Save file to disk
    ext = os.path.splitext(file.filename)[1]
    fn  = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, fn)
    with open(path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    # 2) Create DB record
    rec = LeadRecording(
        lead_id=lead_id,
        employee_code=employee_code,
        recording_url=path
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec

@router.delete(
    "/{recording_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a recording and its file"
)
def delete_recording(
    recording_id: int,
    db: Session = Depends(get_db)
):
    rec = db.get(LeadRecording, recording_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")

    # 1) Remove file from disk (ignore errors)
    try:
        os.remove(rec.recording_url)
    except OSError:
        pass

    # 2) Delete DB record
    db.delete(rec)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
