# db/Schema/attendance.py

from pydantic import BaseModel, Field, ConfigDict
import datetime
from typing import Optional

class AttendanceBase(BaseModel):
    employee_code: str = Field(..., description="Employee code")
    # fully qualify the date type so it cannot be confused
    date: datetime.date = Field(..., description="Date of attendance")
    check_in: Optional[datetime.datetime] = Field(
        None, description="Check‑in timestamp"
    )
    check_out: Optional[datetime.datetime] = Field(
        None, description="Check‑out timestamp"
    )
    status: str = Field(..., description="Attendance status (e.g. present, absent)")

class AttendanceCreate(AttendanceBase):
    pass

class AttendanceUpdate(BaseModel):
    date: Optional[datetime.date] = Field(None, description="Date of attendance")
    check_in: Optional[datetime.datetime] = Field(
        None, description="Check‑in timestamp"
    )
    check_out: Optional[datetime.datetime] = Field(
        None, description="Check‑out timestamp"
    )
    status: Optional[str] = Field(None, description="Attendance status")

class AttendanceOut(AttendanceBase):
    id: int
    created_at: datetime.datetime

    # tell Pydantic to pull values off ORM objects
    model_config = ConfigDict(from_attributes=True)
