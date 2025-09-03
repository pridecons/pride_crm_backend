# logs.py
from typing import Optional, Literal, Union
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from db.models import EmailLog, SMSLog, WhatsappLog

Channel = Literal["sms", "whatsapp", "email"]
LogModel = Union[SMSLog, WhatsappLog, EmailLog]


def create_comm_log(
    db: Session,
    channel: Channel,
    *,
    user_id: str,
    # common-ish
    template_id: Optional[int] = None,
    lead_id: Optional[int] = None,          # ignored for EmailLog (no column)
    sent_id: Optional[str] = None,
    status: Optional[str] = None,           # not stored for EmailLog (no column)
    sent_at: Optional[datetime] = None,
    # sms / whatsapp
    recipient_phone_number: Optional[str] = None,
    sms_type: Optional[str] = None,         # used by SMSLog & WhatsappLog (column name is sms_type in both)
    body: Optional[str] = None,             # SMS body; WhatsApp uses 'template' column (see below)
    # whatsapp
    whatsapp_template_text: Optional[str] = None,  # maps to WhatsappLog.template
    # email
    recipient_email: Optional[str] = None,
    sender_email: Optional[str] = None,
    mail_type: Optional[str] = None,
    subject: Optional[str] = None,
    email_body: Optional[str] = None,
) -> LogModel:
    """
    Create & persist a communication log row for the given channel.

    Returns the ORM instance (SMSLog | WhatsappLog | EmailLog).

    Notes:
    - EmailLog schema (as provided) has no lead_id or status columns; those args are ignored for email.
    - WhatsappLog stores message content in `template` column; pass `whatsapp_template_text`.
    - SMSLog stores content in `body`.
    - `sent_at` defaults to utcnow() if not provided.
    """
    sent_at = sent_at or datetime.utcnow()

    try:
        if channel == "sms":
            # Required fields sanity (based on your model)
            if template_id is None or lead_id is None:
                raise ValueError("SMS requires template_id and lead_id")
            if not recipient_phone_number:
                raise ValueError("SMS requires recipient_phone_number")
            if not body:
                raise ValueError("SMS requires body")

            row = SMSLog(
                template_id=template_id,
                lead_id=lead_id,
                recipient_phone_number=recipient_phone_number,
                body=body,
                sms_type=sms_type,
                status=status,
                sms_sent_id=sent_id,
                sent_at=sent_at,
                user_id=user_id,
            )

        elif channel == "whatsapp":
            if lead_id is None:
                raise ValueError("WhatsApp requires lead_id")
            if not recipient_phone_number:
                raise ValueError("WhatsApp requires recipient_phone_number")
            # text to store in WhatsappLog.template
            tpl_text = whatsapp_template_text or body
            if not tpl_text:
                raise ValueError("WhatsApp requires whatsapp_template_text or body")

            row = WhatsappLog(
                template_id=template_id,
                lead_id=lead_id,
                recipient_phone_number=recipient_phone_number,
                whatsapp_sent_id=sent_id,
                template=tpl_text,
                sms_type=sms_type,
                status=status,
                sent_at=sent_at,
                user_id=user_id,
            )

        elif channel == "email":
            if not recipient_email:
                raise ValueError("Email requires recipient_email")
            if not subject:
                raise ValueError("Email requires subject")
            if not (email_body or body):
                raise ValueError("Email requires email_body or body")

            row = EmailLog(
                template_id=template_id,
                recipient_email=recipient_email,
                sender_email=sender_email,
                mail_type=mail_type,
                subject=subject,
                body=email_body or body,
                user_id=user_id,
                email_sent_id=sent_id,
                sent_at=sent_at,
            )

        else:
            raise ValueError(f"Unsupported channel: {channel}")

        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    except (ValueError, SQLAlchemyError) as e:
        db.rollback()
        # Re-raise so caller can handle / translate to HTTPException if needed
        raise


# -----------------------
# Convenience wrappers
# -----------------------

def log_sms(
    db: Session,
    *,
    user_id: str,
    template_id: int,
    lead_id: int,
    recipient_phone_number: str,
    body: str,
    sms_type: Optional[str] = None,
    status: Optional[str] = None,
    sent_id: Optional[str] = None,
    sent_at: Optional[datetime] = None,
) -> SMSLog:
    return create_comm_log(
        db,
        "sms",
        user_id=user_id,
        template_id=template_id,
        lead_id=lead_id,
        recipient_phone_number=recipient_phone_number,
        body=body,
        sms_type=sms_type,
        status=status,
        sent_id=sent_id,
        sent_at=sent_at,
    )  # type: ignore[return-value]


def log_whatsapp(
    db: Session,
    *,
    user_id: str,
    lead_id: int,
    recipient_phone_number: str,
    whatsapp_template_text: str,
    template_id: Optional[int] = None,
    sms_type: Optional[str] = None,
    status: Optional[str] = None,
    sent_id: Optional[str] = None,
    sent_at: Optional[datetime] = None,
) -> WhatsappLog:
    return create_comm_log(
        db,
        "whatsapp",
        user_id=user_id,
        template_id=template_id,
        lead_id=lead_id,
        recipient_phone_number=recipient_phone_number,
        whatsapp_template_text=whatsapp_template_text,
        sms_type=sms_type,
        status=status,
        sent_id=sent_id,
        sent_at=sent_at,
    )  # type: ignore[return-value]


def log_email(
    db: Session,
    *,
    user_id: str,
    recipient_email: str,
    subject: str,
    body: str,
    template_id: Optional[int] = None,
    sender_email: Optional[str] = None,
    mail_type: Optional[str] = None,
    sent_id: Optional[str] = None,
    sent_at: Optional[datetime] = None,
) -> EmailLog:
    return create_comm_log(
        db,
        "email",
        user_id=user_id,
        template_id=template_id,
        recipient_email=recipient_email,
        sender_email=sender_email,
        mail_type=mail_type,
        subject=subject,
        email_body=body,
        sent_id=sent_id,
        sent_at=sent_at,
    )  # type: ignore[return-value]
