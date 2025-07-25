from fastapi.responses import JSONResponse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib
import ssl
import time
import logging
from typing import Dict, Any
from config import COM_SMTP_SERVER, COM_SMTP_PORT, COM_SMTP_USER, COM_SMTP_PASSWORD

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def send_mail_by_client(to_email: str, subject: str, html_content: str, max_retries: int = 3) -> Dict[str, Any]:
    """
    Send a payment link email with enhanced HTML design and disclaimer.
    Includes retry mechanism and better error handling.
    
    Args:
        to_email: Recipient email address
        subject: Email subject
        html_content: HTML content for email body
        max_retries: Maximum number of retry attempts (default: 3)
    
    Returns:
        Dict containing status and message
    """
    smtp_server = COM_SMTP_SERVER
    smtp_port = COM_SMTP_PORT
    smtp_user = COM_SMTP_USER
    smtp_pass = COM_SMTP_PASSWORD
    
    # Validate inputs
    if not all([to_email, subject, html_content]):
        return {
            "status": "error",
            "message": "Missing required parameters: to_email, subject, or html_content"
        }
    
    if not all([smtp_server, smtp_port, smtp_user, smtp_pass]):
        return {
            "status": "error",
            "message": "Missing SMTP configuration parameters"
        }
    
    # Build the email
    msg = MIMEMultipart("alternative")
    msg["From"] = "Pride Trading Consultancy <compliance@pridecons.com>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = "compliance@pridecons.com"
    msg["X-Priority"] = "1"  # High priority
    msg["X-MSMail-Priority"] = "High"
    
    html_content_text = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{subject}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: 'Inter', Arial, sans-serif;">
    <div>
        {html_content}
    </div>
</body>
</html>
    """
    
    msg.attach(MIMEText(html_content_text, "html"))
    
    # Retry mechanism
    for attempt in range(max_retries):
        try:
            logger.info(f"Attempt {attempt + 1} to send email to {to_email}")
            
            # Create SSL context with more permissive settings
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            
            # Use SMTP_SSL for secure connection
            with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context, timeout=30) as server:
                # Enable debug output
                server.set_debuglevel(1)
                
                # Login
                logger.info("Logging into SMTP server...")
                server.login(smtp_user, smtp_pass)
                logger.info("Login successful")
                
                # Send email
                logger.info(f"Sending email to {to_email}...")
                rejected = server.send_message(msg)
                
                if rejected:
                    logger.warning(f"Some recipients were rejected: {rejected}")
                    return {
                        "status": "partial_success",
                        "message": f"Email sent but some recipients rejected: {rejected}",
                        "subject": subject,
                        "attempt": attempt + 1
                    }
                else:
                    logger.info("Email sent successfully!")
                    return {
                        "status": "success",
                        "message": "Email sent successfully!",
                        "subject": subject,
                        "email_type": "Enhanced HTML with responsive design",
                        "attempt": attempt + 1
                    }
                
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP Authentication failed: {e}")
            return {
                "status": "error",
                "message": "SMTP Authentication failed. Check username/password.",
                "error": str(e),
                "attempt": attempt + 1
            }
            
        except smtplib.SMTPRecipientsRefused as e:
            logger.error(f"Recipients refused: {e}")
            return {
                "status": "error",
                "message": f"Recipient email address refused: {to_email}",
                "error": str(e),
                "attempt": attempt + 1
            }
            
        except smtplib.SMTPSenderRefused as e:
            logger.error(f"Sender refused: {e}")
            return {
                "status": "error",
                "message": "Sender email address refused",
                "error": str(e),
                "attempt": attempt + 1
            }
            
        except smtplib.SMTPConnectError as e:
            logger.error(f"SMTP connection failed on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2  # Exponential backoff
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                continue
            else:
                return {
                    "status": "error",
                    "message": f"Failed to connect to SMTP server after {max_retries} attempts",
                    "error": str(e),
                    "attempt": attempt + 1
                }
                
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                continue
            else:
                return {
                    "status": "error",
                    "message": f"SMTP error after {max_retries} attempts",
                    "error": str(e),
                    "attempt": attempt + 1
                }
                
        except Exception as e:
            logger.error(f"Unexpected error on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                continue
            else:
                return JSONResponse(
                    content={
                        "status": "error",
                        "message": f"Failed to send email after {max_retries} attempts",
                        "error": str(e),
                        "attempt": attempt + 1,
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                    },
                    status_code=500
                )
    
    # This should never be reached, but just in case
    return JSONResponse(
        content={
            "status": "error",
            "message": "Unexpected error in email sending process",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        },
        status_code=500
    )


# Alternative function using STARTTLS (if SMTP_SSL doesn't work reliably)
def send_mail_by_client_starttls(to_email: str, subject: str, html_content: str, max_retries: int = 3) -> Dict[str, Any]:
    """
    Alternative email sending function using STARTTLS instead of SMTP_SSL
    """
    smtp_server = COM_SMTP_SERVER
    smtp_port = 587  # Use port 587 for STARTTLS
    smtp_user = COM_SMTP_USER
    smtp_pass = COM_SMTP_PASSWORD
    
    # Validate inputs
    if not all([to_email, subject, html_content]):
        return {
            "status": "error",
            "message": "Missing required parameters"
        }
    
    # Build the email
    msg = MIMEMultipart("alternative")
    msg["From"] = "Pride Trading Consultancy <compliance@pridecons.com>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = "compliance@pridecons.com"
    
    html_content_text = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{subject}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: 'Inter', Arial, sans-serif;">
    <div>
        {html_content}
    </div>
</body>
</html>
    """
    
    msg.attach(MIMEText(html_content_text, "html"))
    
    for attempt in range(max_retries):
        try:
            logger.info(f"STARTTLS attempt {attempt + 1} to send email to {to_email}")
            
            # Use regular SMTP with STARTTLS
            with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
                server.set_debuglevel(1)
                server.starttls()  # Enable TLS
                server.login(smtp_user, smtp_pass)
                rejected = server.send_message(msg)
                
                if rejected:
                    logger.warning(f"Some recipients were rejected: {rejected}")
                    return {
                        "status": "partial_success",
                        "message": f"Email sent but some recipients rejected: {rejected}",
                        "subject": subject,
                        "attempt": attempt + 1
                    }
                else:
                    logger.info("Email sent successfully via STARTTLS!")
                    return {
                        "status": "success",
                        "message": "Email sent successfully via STARTTLS!",
                        "subject": subject,
                        "attempt": attempt + 1
                    }
                    
        except Exception as e:
            logger.error(f"STARTTLS error on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2
                time.sleep(wait_time)
                continue
            else:
                return {
                    "status": "error",
                    "message": f"STARTTLS failed after {max_retries} attempts",
                    "error": str(e)
                }
            

            