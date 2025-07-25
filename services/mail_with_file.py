from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import smtplib
import ssl
import time
import logging
import os
from typing import Dict, Any, Optional
from config import COM_SMTP_SERVER, COM_SMTP_PORT, COM_SMTP_USER, COM_SMTP_PASSWORD

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def send_mail_by_client_with_file(
    to_email: str,
    subject: str,
    html_content: str,
    pdf_file_path: Optional[str] = None,
    max_retries: int = 3
) -> Dict[str, Any]:
    """
    Send a payment link email with enhanced HTML design, optional PDF attachment,
    retry mechanism, and robust error handling.

    Args:
        to_email: Recipient email address
        subject: Email subject
        html_content: HTML content for email body
        pdf_file_path: Path to a PDF file to attach (optional)
        max_retries: Maximum number of retry attempts (default: 3)

    Returns:
        Dict containing status, message, and other details
    """
    smtp_server = COM_SMTP_SERVER
    smtp_port   = COM_SMTP_PORT
    smtp_user   = COM_SMTP_USER
    smtp_pass   = COM_SMTP_PASSWORD

    # Validate inputs
    if not all([to_email, subject, html_content]):
        return {
            "status": "error",
            "message": "Missing required parameters: to_email, subject, or html_content",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
    if not all([smtp_server, smtp_port, smtp_user, smtp_pass]):
        return {
            "status": "error",
            "message": "Missing SMTP configuration parameters",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    logger.info(f"Preparing email to {to_email} with subject: {subject}")
    msg = MIMEMultipart("alternative")
    msg["From"] = "Pride Trading Consultancy <compliance@pridecons.com>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = "compliance@pridecons.com"
    msg["X-Priority"] = "1"
    msg["X-MSMail-Priority"] = "High"

    # HTML body wrapper
    html_wrapper = f"""\
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
</head>
<body style="margin:0; padding:0; background-color:#f8fafc; font-family:'Inter',Arial,sans-serif;">
  <div>
    {html_content}
  </div>
</body>
</html>
"""
    msg.attach(MIMEText(html_wrapper, "html"))

    # Attach PDF if provided
    if pdf_file_path:
        try:
            with open(pdf_file_path, "rb") as f:
                pdf_part = MIMEApplication(f.read(), _subtype="pdf")
            filename = os.path.basename(pdf_file_path)
            pdf_part.add_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"'
            )
            msg.attach(pdf_part)
            logger.info(f"Attached PDF '{filename}'")
        except Exception as e:
            logger.error(f"Failed to attach PDF: {e}")
            return {
                "status": "error",
                "message": f"Could not attach PDF: {e}",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }

    logger.info(f"SMTP Config ─ Server: {smtp_server}, Port: {smtp_port}, User: {smtp_user}")

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Attempt {attempt}/{max_retries} to send email")
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context, timeout=30) as server:
                server.set_debuglevel(1 if attempt == 1 else 0)
                logger.info("Logging in to SMTP server")
                server.login(smtp_user, smtp_pass)
                rejected = server.send_message(msg)

                if rejected:
                    logger.warning(f"Recipients rejected: {rejected}")
                    return {
                        "status": "partial_success",
                        "message": f"Email sent but some recipients rejected: {rejected}",
                        "subject": subject,
                        "recipient": to_email,
                        "attempt": attempt,
                        "rejected_recipients": rejected,
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                    }
                logger.info("Email sent successfully")
                return {
                    "status": "success",
                    "message": "Email sent successfully!",
                    "subject": subject,
                    "recipient": to_email,
                    "email_type": "Enhanced HTML with PDF attachment" if pdf_file_path else "Enhanced HTML",
                    "attempt": attempt,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP auth failed: {e}")
            return {
                "status": "error",
                "message": "SMTP Authentication failed. Check credentials.",
                "error": str(e),
                "attempt": attempt,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
        except smtplib.SMTPRecipientsRefused as e:
            logger.error(f"Recipients refused: {e}")
            return {
                "status": "error",
                "message": f"Recipient refused: {to_email}",
                "error": str(e),
                "attempt": attempt,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
        except smtplib.SMTPConnectError as e:
            logger.error(f"Connection error on attempt {attempt}: {e}")
            last_error = e
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error on attempt {attempt}: {e}")
            last_error = e
        except Exception as e:
            logger.error(f"Unexpected error on attempt {attempt}: {e}")
            last_error = e

        if attempt < max_retries:
            backoff = attempt * 2
            logger.info(f"Retrying in {backoff}s...")
            time.sleep(backoff)

    return {
        "status": "error",
        "message": f"Failed to send email after {max_retries} attempts",
        "error": str(last_error) if last_error else "Unknown",
        "attempts": max_retries,
        "recipient": to_email,
        "subject": subject,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
