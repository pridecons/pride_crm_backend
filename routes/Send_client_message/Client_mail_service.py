# routes/email.py

import os
from typing import List, Optional, Dict, Any

from fastapi import (
    APIRouter, Depends, HTTPException,
    status, Query
)
from fastapi.responses import JSONResponse
from pydantic import EmailStr
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from jinja2 import Template, TemplateError
from smtplib import SMTPException

from db.connection import get_db
from db.models import EmailTemplate, EmailLog
from db.Schema.email import (
    TemplateCreate, TemplateUpdate, TemplateOut,
    SendEmailRequest, EmailLogOut
)
from services.mail import send_mail_by_client
import logging

router = APIRouter(prefix="/email", tags=["email"])


logger = logging.getLogger(__name__)


def render_template(template_str: str, context: Dict[str, Any]) -> str:
    try:
        return Template(template_str).render(**context)
    except TemplateError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Template rendering error: {e}"
        )


@router.post(
    "/templates/",
    response_model=TemplateOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new email template"
)
def create_template(
    payload: TemplateCreate,
    db: Session = Depends(get_db)
):
    tmpl = EmailTemplate(**payload.dict())
    db.add(tmpl)
    try:
        db.commit()
        db.refresh(tmpl)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A template with that name already exists."
        )
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {e}"
        )
    return tmpl


@router.get(
    "/templates/",
    response_model=List[TemplateOut],
    summary="List all email templates"
)
def list_templates(db: Session = Depends(get_db)):
    return db.query(EmailTemplate).all()


@router.get(
    "/templates/{template_id}",
    response_model=TemplateOut,
    summary="Get a single email template"
)
def get_template(template_id: int, db: Session = Depends(get_db)):
    tmpl = db.get(EmailTemplate, template_id)
    if not tmpl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )
    return tmpl


@router.put(
    "/templates/{template_id}",
    response_model=TemplateOut,
    summary="Update an email template"
)
def update_template(
    template_id: int,
    payload: TemplateUpdate,
    db: Session = Depends(get_db)
):
    tmpl = db.get(EmailTemplate, template_id)
    if not tmpl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )

    for field, value in payload.dict(exclude_unset=True).items():
        setattr(tmpl, field, value)

    try:
        db.commit()
        db.refresh(tmpl)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Template name conflict."
        )
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {e}"
        )

    return tmpl


@router.delete(
    "/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an email template by ID"
)
def delete_template(
    template_id: int,
    db: Session = Depends(get_db)
):
    tmpl = db.get(EmailTemplate, template_id)
    if not tmpl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )

    try:
        db.delete(tmpl)
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {e}"
        )

    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)


@router.post(
    "/send/",
    response_model=Dict[str, str],
    summary="Render and send an email based on a template"
)
def send_email(
    req: SendEmailRequest,
    db: Session = Depends(get_db)
):
    # Get template
    tmpl = db.get(EmailTemplate, req.template_id)
    if not tmpl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )

    # 1) Render subject & body
    try:
        subject = render_template(tmpl.subject, req.context)
        body_html = render_template(tmpl.body, req.context)
    except Exception as e:
        logger.error(f"Template rendering error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Template rendering error: {e}"
        )

    # 2) Send via SMTP - Handle the response properly
    try:
        email_result = send_mail_by_client(req.recipient_email, subject, body_html)
        
        # Check if email was actually sent successfully
        if isinstance(email_result, JSONResponse):
            # If it's a JSONResponse, it means there was an error
            logger.error(f"Email sending failed: {email_result.body}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="SMTP send error - check server logs for details"
            )
        elif isinstance(email_result, dict):
            if email_result.get("status") != "success":
                logger.error(f"Email sending failed: {email_result}")
                error_msg = email_result.get("message", "Unknown error")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"SMTP send error: {error_msg}"
                )
            else:
                logger.info(f"Email sent successfully: {email_result}")
        else:
            # Unexpected response type
            logger.error(f"Unexpected email function response: {email_result}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unexpected response from email function"
            )
            
    except HTTPException:
        # Re-raise HTTPExceptions
        raise
    except Exception as e:
        logger.error(f"Unexpected error in email sending: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected send error: {e}"
        )

    # 3) Log it only if email was sent successfully
    log = EmailLog(
        template_id=tmpl.id,
        recipient_email=req.recipient_email,
        subject=subject,
        body=body_html,
        status="sent"  # Add status field if you have it
    )
    db.add(log)
    
    try:
        db.commit()
        logger.info(f"Email logged successfully for {req.recipient_email}")
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Failed to log email: {e}")
        # Email was sent successfully, but logging failed
        return {
            "message": "Email sent successfully, but failed to log.",
            "logging_error": str(e),
            "email_status": email_result.get("message", "Email sent")
        }

    return {
        "message": "Email sent and logged successfully",
        "email_details": {
            "recipient": req.recipient_email,
            "subject": subject,
            "attempts": email_result.get("attempt", 1),
            "status": email_result.get("status", "success")
        }
    }

@router.get(
    "/logs/",
    response_model=List[EmailLogOut],
    summary="List email send logs"
)
def list_email_logs(
    template_id: Optional[int] = Query(None, description="Filter by template"),
    recipient_email: Optional[EmailStr] = Query(None, description="Filter by recipient"),
    db: Session = Depends(get_db)
):
    q = db.query(EmailLog)
    if template_id is not None:
        q = q.filter(EmailLog.template_id == template_id)
    if recipient_email is not None:
        q = q.filter(EmailLog.recipient_email == recipient_email)
    return q.order_by(EmailLog.sent_at.desc()).all()


@router.get(
    "/logs/{log_id}",
    response_model=EmailLogOut,
    summary="Get a specific email log entry"
)
def get_email_log(log_id: int, db: Session = Depends(get_db)):
    log = db.get(EmailLog, log_id)
    if not log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Log entry not found"
        )
    return log
