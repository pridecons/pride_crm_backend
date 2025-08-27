from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError
from pydantic import BaseModel, Field, ConfigDict, root_validator
from typing import Optional, List, Union
from datetime import datetime

import httpx
import os
import logging

from db.connection import get_db
from db.models import SMSTemplate, SMSLog
from routes.auth.auth_dependency import get_current_user
from config import AIRTEL_IQ_SMS_URL, BASIC_AUTH_PASS, BASIC_AUTH_USER, BASIC_IQ_CUSTOMER_ID, BASIC_IQ_ENTITY_ID

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sms-templates", tags=["SMS Templates"])


# ------------------ Schemas -------------------

class SMSTemplateCreate(BaseModel):
    title: str = Field(..., min_length=1)
    template: str = Field(..., min_length=1)
    dltTemplateId: str
    messageType: str
    sourceAddress: List[str] = Field(..., min_items=1)
    allowedRoles: Optional[List[str]] = None  # if omitted, DB default applies


class SMSTemplateUpdate(BaseModel):
    title: Optional[str]
    template: Optional[str]
    dltTemplateId: Optional[str]
    messageType: Optional[str]
    sourceAddress: Optional[List[str]]
    allowedRoles: Optional[List[str]]


class SMSTemplateOut(BaseModel):
    id: int
    title: str
    template: str
    dltTemplateId: str = Field(..., alias="dlt_template_id")
    messageType: str = Field(..., alias="message_type")
    sourceAddress: List[str] = Field(..., alias="source_address")
    allowedRoles: List[str] = Field(..., alias="allowed_roles")

    class Config:
        from_attributes = True


class SendSMSRequest(BaseModel):
    template_id: int
    phone_number: Union[str, List[str]]
    message_override: Optional[str] = None

    @root_validator(pre=True)
    def normalize_phone(cls, values):
        phones = values.get("phone_number")
        if isinstance(phones, str):
            values["phone_number"] = [phones]
        return values


class SMSLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    template_id: int
    template_title: Optional[str]
    recipient_phone_number: str
    body: str
    sent_at: datetime
    user_id: str


class PaginatedSMSLogs(BaseModel):
    limit: int
    offset: int
    total: int
    logs: List[SMSLogOut]


# ------------------ Helpers -------------------

def normalize_indian_number(num: str) -> str:
    cleaned = num.strip()
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    if len(cleaned) == 10:
        return "91" + cleaned
    return cleaned  # assume already includes country code


# ------------------ Template CRUD -------------------

@router.post("/", status_code=status.HTTP_201_CREATED, response_model=SMSTemplateOut)
def create_sms_template(payload: SMSTemplateCreate, db: Session = Depends(get_db)):
    try:
        kwargs = {
            "title": payload.title,
            "template": payload.template,
            "dlt_template_id": payload.dltTemplateId,
            "message_type": payload.messageType,
            "source_address": payload.sourceAddress,
        }
        if payload.allowedRoles is not None:
            kwargs["allowed_roles"] = payload.allowedRoles

        template = SMSTemplate(**kwargs)
        db.add(template)
        db.commit()
        db.refresh(template)
        return SMSTemplateOut.model_validate(template)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error("Failed to create SMS template: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create SMS template")


@router.get("/", response_model=List[SMSTemplateOut])
def list_sms_templates(
    search: Optional[str] = Query(None, description="Search in title or template"),
    allowed_role: Optional[str] = Query(None, description="Filter templates allowed for this role"),
    db: Session = Depends(get_db),
):
    try:
        q = db.query(SMSTemplate)
        if search:
            pattern = f"%{search}%"
            q = q.filter(
                or_(SMSTemplate.title.ilike(pattern), SMSTemplate.template.ilike(pattern))
            )
        if allowed_role:
            # PostgreSQL ARRAY contains check: template.allowed_roles contains the single role
            q = q.filter(SMSTemplate.allowed_roles.contains([allowed_role]))
        templates = q.order_by(SMSTemplate.id.desc()).all()
        return [SMSTemplateOut.model_validate(t) for t in templates]
    except SQLAlchemyError as e:
        logger.error("Failed to list SMS templates: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list SMS templates")


@router.put("/{template_id}", response_model=SMSTemplateOut)
def update_sms_template(
    template_id: int,
    payload: SMSTemplateUpdate,
    db: Session = Depends(get_db),
):
    template = db.query(SMSTemplate).filter(SMSTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="template not found")

    try:
        if payload.title is not None:
            template.title = payload.title
        if payload.template is not None:
            template.template = payload.template
        if payload.dltTemplateId is not None:
            template.dlt_template_id = payload.dltTemplateId
        if payload.messageType is not None:
            template.message_type = payload.messageType
        if payload.sourceAddress is not None:
            template.source_address = payload.sourceAddress
        if payload.allowedRoles is not None:
            template.allowed_roles = payload.allowedRoles

        db.commit()
        db.refresh(template)
        return SMSTemplateOut.model_validate(template)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error("Failed to update SMS template %s: %s", template_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update SMS template")


@router.delete("/{template_id}", status_code=status.HTTP_200_OK)
def delete_sms_template(
    template_id: int,
    db: Session = Depends(get_db),
):
    template = db.query(SMSTemplate).filter(SMSTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="template not found")
    try:
        db.delete(template)
        db.commit()
        return {"message": "template deleted", "id": template_id}
    except SQLAlchemyError as e:
        db.rollback()
        logger.error("Failed to delete SMS template %s: %s", template_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete template")


# ------------------ Send SMS -------------------

@router.post("/send-sms", status_code=status.HTTP_200_OK)
async def send_sms_template(
    payload: SendSMSRequest = Body(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not AIRTEL_IQ_SMS_URL or not BASIC_AUTH_USER or not BASIC_AUTH_PASS:
        raise HTTPException(status_code=500, detail="SMS gateway credentials or URL not configured")

    user_id = getattr(current_user, "employee_code", None) or getattr(current_user, "sub", None)
    user_role = getattr(current_user, "role", None)
    if not user_role:
        raise HTTPException(status_code=500, detail="Current user has no role information")

    template = db.query(SMSTemplate).filter(SMSTemplate.id == payload.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="SMS template not found")

    # enforce role permission
    allowed = template.allowed_roles or []
    if user_role not in allowed:
        raise HTTPException(status_code=403, detail=f"User role '{user_role}' not permitted to use this template")

    # Extract source address from template (use first if multiple)
    source_addresses = template.source_address
    if not source_addresses:
        raise HTTPException(status_code=500, detail="SMS template has no source_address configured")
    if isinstance(source_addresses, list):
        if len(source_addresses) > 1:
            logger.warning(
                "Template %s has multiple source addresses, using first: %s",
                template.id,
                source_addresses,
            )
        source_address = source_addresses[0]
    else:
        source_address = source_addresses  # fallback in case it's stored as a single string

    message_text = payload.message_override or template.template

    dests = []
    for p in payload.phone_number:
        norm = normalize_indian_number(p)
        if not norm.isdigit():
            raise HTTPException(status_code=400, detail=f"Invalid phone number: {p}")
        dests.append(norm)

    sms_body = {
        "customerId": BASIC_IQ_CUSTOMER_ID,
        "destinationAddress": dests,
        "dltTemplateId": template.dlt_template_id,
        "entityId": BASIC_IQ_ENTITY_ID,
        "message": message_text,
        "messageType": template.message_type,
        "sourceAddress": source_address,
    }

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                AIRTEL_IQ_SMS_URL,
                json=sms_body,
                headers=headers,
                auth=(BASIC_AUTH_USER, BASIC_AUTH_PASS),
            )
            resp.raise_for_status()
            api_response = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error("Airtel IQ API error %s: %s; request body: %s", e.response.status_code, e.response.text, sms_body)
        raise HTTPException(
            status_code=502,
            detail=f"SMS gateway error: {e.response.status_code} {e.response.text}"
        )
    except Exception as e:
        logger.exception("Failed to call SMS gateway")
        raise HTTPException(status_code=502, detail="Failed to send SMS due to gateway error")

    log_ids = []
    try:
        for dest in dests:
            sms_log = SMSLog(
                template_id=template.id,
                recipient_phone_number=dest,
                body=message_text,
                user_id=user_id or "unknown",
                sent_at=datetime.utcnow(),
            )
            db.add(sms_log)
            db.flush()
            log_ids.append(sms_log.id)
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        logger.error("Failed to persist SMS logs: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="SMS sent but failed to log")

    return {
        "message": "SMS sent successfully",
        "template_title": template.title,
        "recipients": dests,
        "gateway_response": api_response,
        "log_ids": log_ids,
    }


# ------------------ Logs -------------------

@router.get("/logs", response_model=PaginatedSMSLogs)
def get_sms_logs(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    template_id: Optional[int] = Query(None, description="Filter by template ID"),
    phone: Optional[str] = Query(None, description="Filter by recipient phone number"),
    start_date: Optional[str] = Query(None, description="Filter from date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Filter to date (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        query = db.query(SMSLog).join(SMSTemplate, SMSLog.template_id == SMSTemplate.id)

        filters = []
        if user_id:
            filters.append(SMSLog.user_id == user_id)
        if template_id:
            filters.append(SMSLog.template_id == template_id)
        if phone:
            filters.append(SMSLog.recipient_phone_number.ilike(f"%{phone}%"))

        if start_date:
            try:
                start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                filters.append(SMSLog.sent_at >= start_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD")

        if end_date:
            try:
                end_dt = datetime.strptime(end_date, "%Y-%m-%d")
                filters.append(SMSLog.sent_at <= end_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD")

        if filters:
            query = query.filter(and_(*filters))

        total = query.count()
        logs = query.order_by(SMSLog.sent_at.desc()).limit(limit).offset(offset).all()

        results = [
            SMSLogOut.model_validate(
                {
                    "id": log.id,
                    "template_id": log.template_id,
                    "template_title": log.template.title if log.template else None,
                    "recipient_phone_number": log.recipient_phone_number,
                    "body": log.body,
                    "sent_at": log.sent_at,
                    "user_id": log.user_id,
                }
            )
            for log in logs
        ]

        return PaginatedSMSLogs(
            limit=limit,
            offset=offset,
            total=total,
            logs=results,
        )
    except SQLAlchemyError as e:
        logger.error("Failed to fetch SMS logs: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch SMS logs")

@router.get("/{template_id}", response_model=SMSTemplateOut)
def get_sms_template(template_id: int, db: Session = Depends(get_db)):
    template = db.query(SMSTemplate).filter(SMSTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="SMS template not found")
    return SMSTemplateOut.model_validate(template)
