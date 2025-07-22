from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date

from db.connection import get_db
from db.models import Attendance as AttendanceModel
from db.Schema.attendance import (
    AttendanceCreate,
    AttendanceOut,
    AttendanceUpdate,
)

router = APIRouter(
    prefix="/attendance",
    tags=["Attendance"],
)


@router.post(
    "/",
    response_model=AttendanceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a new attendance entry",
)
def create_attendance(
    payload: AttendanceCreate,
    db: Session = Depends(get_db),
):
    att = AttendanceModel(**payload.dict())
    db.add(att)
    db.commit()
    db.refresh(att)
    return att


@router.get(
    "/",
    response_model=List[AttendanceOut],
    summary="List attendance records (with optional filters)",
)
def list_attendances(
    employee_code: Optional[str] = Query(None, description="Filter by employee code"),
    date_from: Optional[date]     = Query(None, description="Start date (inclusive)"),
    date_to:   Optional[date]     = Query(None, description="End date (inclusive)"),
    skip:      int                = Query(0, description="Number of records to skip"),
    limit:     int                = Query(100, description="Max records to return"),
    db: Session = Depends(get_db),
):
    q = db.query(AttendanceModel)
    if employee_code:
        q = q.filter(AttendanceModel.employee_code == employee_code)
    if date_from:
        q = q.filter(AttendanceModel.date >= date_from)
    if date_to:
        q = q.filter(AttendanceModel.date <= date_to)
    return q.offset(skip).limit(limit).all()


@router.get(
    "/{attendance_id}",
    response_model=AttendanceOut,
    summary="Get a single attendance record by ID",
)
def get_attendance(
    attendance_id: int,
    db: Session = Depends(get_db),
):
    att = db.get(AttendanceModel, attendance_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    return att


@router.patch(
    "/{attendance_id}",
    response_model=AttendanceOut,
    summary="Update an existing attendance record",
)
def update_attendance(
    attendance_id: int,
    payload: AttendanceUpdate,
    db: Session = Depends(get_db),
):
    att = db.get(AttendanceModel, attendance_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attendance record not found")

    for field, value in payload.dict(exclude_unset=True).items():
        setattr(att, field, value)

    db.commit()
    db.refresh(att)
    return att


@router.delete(
    "/{attendance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an attendance record",
)
def delete_attendance(
    attendance_id: int,
    db: Session = Depends(get_db),
):
    att = db.get(AttendanceModel, attendance_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    db.delete(att)
    db.commit()
