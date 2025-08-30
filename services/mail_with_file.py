from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import smtplib, ssl, time, logging, os
from typing import Dict, Any, Optional
from config import COM_SMTP_SERVER, COM_SMTP_PORT, COM_SMTP_USER, COM_SMTP_PASSWORD

logger = logging.getLogger(__name__)

INVESTOR_CHARTER_PATH = "Investor Charter for Research Analyst.pdf"
INVESTOR_CHARTER_NAME = "Investor Charter for Research Analyst.pdf"  # keep extension

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

    # Root container for attachments
    msg = MIMEMultipart("mixed")
    msg["From"] = "Pride Trading Consultancy <compliance@pridecons.com>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = "compliance@pridecons.com"
    msg["X-Priority"] = "1"
    msg["X-MSMail-Priority"] = "High"

    # Create the alternative part (plain + HTML)
    alt = MIMEMultipart("alternative")
    text_fallback = "Please view this email in an HTML-capable email client."
    alt.attach(MIMEText(text_fallback, "plain"))

    html_wrapper = f"""\
<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{subject}</title></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:Arial,sans-serif;">
  <div>{html_content}</div>
</body></html>"""
    alt.attach(MIMEText(html_wrapper, "html"))
    msg.attach(alt)

    # Optional: attach the user-provided PDF
    if pdf_file_path:
        try:
            if not os.path.isfile(pdf_file_path):
                raise FileNotFoundError(f"Attachment not found: {pdf_file_path}")
            with open(pdf_file_path, "rb") as f:
                part = MIMEApplication(f.read(), _subtype="pdf")
            part.add_header("Content-Disposition", 'attachment', filename=os.path.basename(pdf_file_path))
            msg.attach(part)
            logger.info(f"Attached PDF '{os.path.basename(pdf_file_path)}'")
        except Exception as e:
            logger.error(f"Failed to attach provided PDF: {e}")
            return {"status":"error","message":f"Could not attach PDF: {e}","timestamp":time.strftime("%Y-%m-%d %H:%M:%S")}

    # Always attach Investor Charter (with extension)
    try:
        if not os.path.isfile(INVESTOR_CHARTER_PATH):
            raise FileNotFoundError(f"Attachment not found: {INVESTOR_CHARTER_PATH}")
        with open(INVESTOR_CHARTER_PATH, "rb") as f:
            charter = MIMEApplication(f.read(), _subtype="pdf")
        charter.add_header("Content-Disposition", "attachment", filename=INVESTOR_CHARTER_NAME)
        msg.attach(charter)
        logger.info(f"Attached PDF '{INVESTOR_CHARTER_NAME}'")
    except Exception as e:
        logger.error(f"Failed to attach Investor Charter: {e}")
        # If this must be mandatory, return error; else just log and continue.
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
            if attempt < max_retries:
                time.sleep(attempt * 2)

    return {"status":"error","message":f"Failed to send email after {max_retries} attempts",
            "error":str(last_error) if last_error else "Unknown","recipient":to_email,"subject":subject,
            "attempts":max_retries,"timestamp":time.strftime("%Y-%m-%d %H:%M:%S")}
