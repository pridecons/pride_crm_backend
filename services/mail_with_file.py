from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import smtplib, ssl, time, logging, os
from typing import Dict, Any, Optional
from pathlib import Path
from config import COM_SMTP_SERVER, COM_SMTP_PORT, COM_SMTP_USER, COM_SMTP_PASSWORD

logger = logging.getLogger(__name__)

# ---- Resolve the PDF path RELIABLY (relative to this file) ----
MODULE_DIR = Path(__file__).resolve().parent
CHARTER_PATH = MODULE_DIR / "Files" / "Investor Charter for Research Analyst.pdf"
CHARTER_NAME = "Investor Charter for Research Analyst.pdf"  # filename shown to recipient

def send_mail_by_client_with_file(
    to_email: str,
    subject: str,
    html_content: str,
    pdf_file_path: Optional[str] = None,
    max_retries: int = 3
) -> Dict[str, Any]:
    smtp_server = COM_SMTP_SERVER
    smtp_port   = COM_SMTP_PORT
    smtp_user   = COM_SMTP_USER
    smtp_pass   = COM_SMTP_PASSWORD

    if not all([to_email, subject, html_content]):
        return {"status":"error","message":"Missing required parameters","timestamp":time.strftime("%Y-%m-%d %H:%M:%S")}
    if not all([smtp_server, smtp_port, smtp_user, smtp_pass]):
        return {"status":"error","message":"Missing SMTP configuration parameters","timestamp":time.strftime("%Y-%m-%d %H:%M:%S")}

    msg = MIMEMultipart("mixed")
    msg["From"] = "Pride Trading Consultancy <compliance@pridecons.com>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = "compliance@pridecons.com"
    msg["X-Priority"] = "1"
    msg["X-MSMail-Priority"] = "High"

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText("Please view this email in an HTML-capable email client.", "plain"))

    html_wrapper = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{subject}</title></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:Arial,sans-serif;">
  <div>{html_content}</div>
</body></html>"""
    alt.attach(MIMEText(html_wrapper, "html"))
    msg.attach(alt)

    # Optional user-provided PDF
    if pdf_file_path:
        try:
            user_pdf = Path(pdf_file_path)
            if not user_pdf.is_file():
                raise FileNotFoundError(f"Attachment not found: {user_pdf}")
            with user_pdf.open("rb") as f:
                part = MIMEApplication(f.read(), _subtype="pdf")
            part.add_header("Content-Disposition", "attachment", filename=user_pdf.name)
            msg.attach(part)
            logger.info(f"Attached PDF '{user_pdf.name}' from '{user_pdf.resolve()}'")
        except Exception as e:
            logger.error(f"Failed to attach provided PDF: {e}")
            return {"status":"error","message":f"Could not attach PDF: {e}","timestamp":time.strftime("%Y-%m-%d %H:%M:%S")}

    # Always attach Investor Charter
    try:
        if not CHARTER_PATH.is_file():
            raise FileNotFoundError(f"Attachment not found: {CHARTER_PATH}")
        with CHARTER_PATH.open("rb") as f:
            charter = MIMEApplication(f.read(), _subtype="pdf")
        charter.add_header("Content-Disposition", "attachment", filename=CHARTER_NAME)
        msg.attach(charter)
        logger.info(f"Attached Investor Charter '{CHARTER_NAME}' from '{CHARTER_PATH}'")
    except Exception as e:
        logger.error(f"Failed to attach Investor Charter: {e}")
        # If mandatory, return an error; otherwise continue:
        # return {"status":"error","message":f"Could not attach Investor Charter: {e}","timestamp":time.strftime("%Y-%m-%d %H:%M:%S")}

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context, timeout=30) as server:
                server.login(smtp_user, smtp_pass)
                rejected = server.send_message(msg)
            if rejected:
                return {"status":"partial_success","message":"Some recipients rejected","rejected_recipients":rejected,
                        "recipient":to_email,"subject":subject,"attempt":attempt,"timestamp":time.strftime("%Y-%m-%d %H:%M:%S")}
            return {"status":"success","message":"Email sent successfully!","recipient":to_email,"subject":subject,
                    "email_type":"Enhanced HTML with PDF attachment","attempt":attempt,"timestamp":time.strftime("%Y-%m-%d %H:%M:%S")}
        except Exception as e:
            last_error = e
            logger.exception(f"SMTP send attempt {attempt} failed: {e}")
            if attempt < max_retries:
                time.sleep(attempt * 2)

    return {"status":"error","message":f"Failed to send email after {max_retries} attempts",
            "error":str(last_error) if last_error else "Unknown","recipient":to_email,"subject":subject,
            "attempts":max_retries,"timestamp":time.strftime("%Y-%m-%d %H:%M:%S")}
