from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from jinja2 import Template as JinjaTemplate

from db.connection import get_db
from db.models import EmailTemplate, EmailLog
from db.Schema.email import (
    TemplateCreate, TemplateUpdate, TemplateOut,
    SendEmailRequest, EmailLogOut
)
from services.mail import render_template, send_mail
from typing import Optional
from pydantic import EmailStr


router = APIRouter(prefix="/email", tags=["email"])

@router.post("/templates/", response_model=TemplateOut)
def create_template(
    payload: TemplateCreate,
    db: Session = Depends(get_db)
):
    tmpl = EmailTemplate(**payload.dict())
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)
    return tmpl

@router.get("/templates/", response_model=list[TemplateOut])
def list_templates(db: Session = Depends(get_db)):
    return db.query(EmailTemplate).all()

@router.get("/templates/{template_id}", response_model=TemplateOut)
def get_template(template_id: int, db: Session = Depends(get_db)):
    tmpl = db.query(EmailTemplate).get(template_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return tmpl

@router.put("/templates/{template_id}", response_model=TemplateOut)
def update_template(
    template_id: int,
    payload: TemplateUpdate,
    db: Session = Depends(get_db)
):
    tmpl = db.query(EmailTemplate).get(template_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    for field, value in payload.dict(exclude_unset=True).items():
        setattr(tmpl, field, value)
    db.commit()
    db.refresh(tmpl)
    return tmpl

@router.delete(
    "/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an email template by ID",
)
def delete_template(
    template_id: int,
    db: Session = Depends(get_db)
):
    # 1) fetch via Session.get (SQLAlchemy 2.x compatible)
    tmpl = db.get(EmailTemplate, template_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    # 2) delete + commit
    db.delete(tmpl)
    db.commit()

    # 3) return bare 204
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.post("/send/")
def send_email(
    req: SendEmailRequest,
    db: Session = Depends(get_db)
):
    tmpl = db.query(EmailTemplate).get(req.template_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    # Render
    subject  = render_template(tmpl.subject, req.context)
    body_html = render_template(tmpl.body,    req.context)

    # Send
    try:
        send_mail(req.recipient_email, subject, body_html)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SMTP error: {e}")

    # Log it
    log = EmailLog(
        template_id     = tmpl.id,
        recipient_email = req.recipient_email,
        subject         = subject,
        body            = body_html,
        # sent_at defaults to now()
    )
    db.add(log)
    db.commit()

    return {"message": "Email sent and logged successfully"}

@router.get("/logs/", response_model=list[EmailLogOut])
def list_email_logs(
    template_id: Optional[int] = Query(None, description="Filter by template"),
    recipient_email: Optional[EmailStr] = Query(None, description="Filter by recipient"),
    db: Session = Depends(get_db)
):
    q = db.query(EmailLog)
    if template_id:
        q = q.filter(EmailLog.template_id == template_id)
    if recipient_email:
        q = q.filter(EmailLog.recipient_email == recipient_email)
    return q.order_by(EmailLog.sent_at.desc()).all()

@router.get("/logs/{log_id}", response_model=EmailLogOut)
def get_email_log(log_id: int, db: Session = Depends(get_db)):
    log = db.query(EmailLog).get(log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Log entry not found")
    return log

