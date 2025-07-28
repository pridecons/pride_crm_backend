from fastapi import APIRouter, Depends, HTTPException, status, Path, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
import requests
from db.connection import get_db
from db.models import SMSTemplate, SMSLog
from config import SMS_API_URL, SMS_AUTHKEY, DLT_TE_ID, SENDER_ID, ROUTE, COUNTRY
from routes.auth.auth_dependency import get_current_user
from datetime import datetime
from sqlalchemy import and_, or_


router = APIRouter(prefix="/sms-templates", tags=["SMS Templates"])


# ──────── SCHEMAS ─────────────

class SMSTemplateCreate(BaseModel):
    title: str
    template: str

class SMSTemplateUpdate(BaseModel):
    title: Optional[str]
    template: Optional[str]

class SMSLogOut(BaseModel):
    id: int
    template_id: int
    template_title: Optional[str]
    recipient_phone_number: str
    body: str
    sent_at: datetime
    user_id: str

    class Config:
        from_attributes = True


# ──────── CREATE ─────────────

@router.post("/", status_code=status.HTTP_201_CREATED)
def create_sms_template(payload: SMSTemplateCreate, db: Session = Depends(get_db)):
    template = SMSTemplate(title=payload.title, template=payload.template)
    db.add(template)
    db.commit()
    db.refresh(template)
    return {"message": "template created", "id": template.id}


# ──────── UPDATE ─────────────

@router.put("/{template_id}")
def update_sms_template(
    template_id: int,
    payload: SMSTemplateUpdate,
    db: Session = Depends(get_db)
):
    template = db.query(SMSTemplate).filter(SMSTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="template not found")

    if payload.title is not None:
        template.title = payload.title
    if payload.template is not None:
        template.template = payload.template

    db.commit()
    db.refresh(template)
    return {"message": "template updated", "id": template.id}


# ──────── DELETE ─────────────

@router.delete("/{template_id}")
def delete_sms_template(
    template_id: int,
    db: Session = Depends(get_db)
):
    template = db.query(SMSTemplate).filter(SMSTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="template not found")

    db.delete(template)
    db.commit()
    return {"message": "template deleted"}


@router.post("/send-sms")
def send_sms_template(
    msg: str,
    phone_number: str,
    template_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user_id = current_user.employee_code

    # 1. Validate template
    template = db.query(SMSTemplate).filter(SMSTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="SMS template not found")

    # 2. Prepare SMS API params
    params = {
        "authkey": SMS_AUTHKEY,
        "mobiles": phone_number,
        "message": msg,
        "sender": SENDER_ID,
        "route": ROUTE,
        "country": COUNTRY,
        "DLT_TE_ID": DLT_TE_ID,
    }

    # 3. Send SMS
    try:
        resp = requests.get(SMS_API_URL, params=params, timeout=5)
        resp.raise_for_status()
        api_response = resp.json()
        print("api_response : ",api_response)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"SMS API error: {str(e)}")

    # 4. Log the SMS
    sms_log = SMSLog(
        template_id=template.id,
        recipient_phone_number=phone_number,
        body=msg,
        user_id=user_id,
        sent_at=datetime.utcnow()
    )
    db.add(sms_log)
    db.commit()

    return {
        "message": "SMS sent successfully",
        "phone_number": phone_number,
        "template_title": template.title,
        "api_response": api_response,
        "log_id": sms_log.id,
    }

@router.get("/logs", response_model=List[SMSLogOut])
def get_sms_logs(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    template_id: Optional[int] = Query(None, description="Filter by template ID"),
    phone: Optional[str] = Query(None, description="Filter by recipient phone number"),
    start_date: Optional[str] = Query(None, description="Filter from date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Filter to date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
):
    query = db.query(SMSLog).join(SMSTemplate, SMSLog.template_id == SMSTemplate.id)

    # Apply filters
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

    # Apply all filters
    if filters:
        query = query.filter(and_(*filters))

    logs = query.order_by(SMSLog.sent_at.desc()).all()

    return [
        SMSLogOut(
            id=log.id,
            template_id=log.template_id,
            template_title=log.template.title if log.template else None,
            recipient_phone_number=log.recipient_phone_number,
            body=log.body,
            sent_at=log.sent_at,
            user_id=log.user_id,
        )
        for log in logs
    ]
