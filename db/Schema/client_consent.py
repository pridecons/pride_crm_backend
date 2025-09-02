from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Dict
from datetime import datetime

class ClientConsentCreate(BaseModel):
    lead_id: int = Field(..., gt=0)
    consent_text: str = Field(..., min_length=5)
    channel: str = "WEB"        # you can override if needed
    purpose: str = "PAYMENT"    # you can override if needed
    tz_offset_minutes: int      # from client: -new Date().getTimezoneOffset()
    device_info: Optional[Dict] = None

class ClientConsentOut(BaseModel):
    id: int
    lead_id: int
    email: Optional[str]
    consent_text: str
    channel: str
    purpose: str
    ip_address: str
    user_agent: str
    device_info: Optional[Dict]
    tz_offset_minutes: int
    consented_at_utc: datetime
    consented_at_ist: datetime
    ref_id: str

    class Config:
        orm_mode = True
