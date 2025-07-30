from typing import Any, Dict, Optional
from pydantic import BaseModel, EmailStr
from db.models import TemplateTypeEnum
from datetime import datetime

class TemplateBase(BaseModel):
    name: str
    template_type: TemplateTypeEnum
    subject: str
    body: str     # can contain Jinja2 placeholders, e.g. "Hello {{ user_name }}!"

class TemplateCreate(TemplateBase):
    pass

class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    template_type: Optional[TemplateTypeEnum] = None
    subject: Optional[str] = None
    body: Optional[str] = None

class TemplateOut(TemplateBase):
    id: int

    class Config:
        from_attributes = True

class SendEmailRequest(BaseModel):
    template_id: int
    recipient_email: EmailStr
    context: Dict[str, Any]     # e.g. {"user_name": "Dheeraj", "reset_link": "…"}

class EmailLogOut(BaseModel):
    id: int
    template_id: int
    recipient_email: EmailStr
    subject: str
    body: str
    sent_at: datetime
    user_id:Optional[str]

    class Config:
        from_attributes = True

