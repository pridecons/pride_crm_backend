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
    
    ALWAYS returns a dictionary (never JSONResponse)
    
    Args:
        to_email: Recipient email address
        subject: Email subject
        html_content: HTML content for email body
        max_retries: Maximum number of retry attempts (default: 3)
    
    Returns:
        Dict containing status, message, and other details
    """
    smtp_server = COM_SMTP_SERVER
    smtp_port = COM_SMTP_PORT
    smtp_user = COM_SMTP_USER
    smtp_pass = COM_SMTP_PASSWORD
    
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
    
    logger.info(f"Attempting to send email to {to_email} with subject: {subject}")
    
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
    
    # Debug: Log SMTP configuration (without password)
    logger.info(f"SMTP Config - Server: {smtp_server}, Port: {smtp_port}, User: {smtp_user}")
    
    # Retry mechanism
    last_error = None
    for attempt in range(max_retries):
        try:
            logger.info(f"Attempt {attempt + 1}/{max_retries} to send email to {to_email}")
            
            # Create SSL context
            context = ssl.create_default_context()
            
            # Use SMTP_SSL for secure connection
            with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context, timeout=30) as server:
                # Enable debug output for troubleshooting
                server.set_debuglevel(1 if attempt == 0 else 0)  # Only debug first attempt
                
                # Login
                logger.info("Attempting SMTP login...")
                server.login(smtp_user, smtp_pass)
                logger.info("SMTP login successful")
                
                # Send email
                logger.info(f"Sending email...")
                rejected = server.send_message(msg)
                
                if rejected:
                    logger.warning(f"Some recipients were rejected: {rejected}")
                    return {
                        "status": "partial_success",
                        "message": f"Email sent but some recipients rejected: {rejected}",
                        "subject": subject,
                        "recipient": to_email,
                        "attempt": attempt + 1,
                        "rejected_recipients": rejected,
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                    }
                else:
                    logger.info("Email sent successfully!")
                    return {
                        "status": "success",
                        "message": "Email sent successfully!",
                        "subject": subject,
                        "recipient": to_email,
                        "email_type": "Enhanced HTML with responsive design",
                        "attempt": attempt + 1,
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                    }
                
        except smtplib.SMTPAuthenticationError as e:
            error_msg = f"SMTP Authentication failed: {e}"
            logger.error(error_msg)
            return {
                "status": "error",
                "message": "SMTP Authentication failed. Check username/password.",
                "error": str(e),
                "attempt": attempt + 1,
                "recipient": to_email,
                "smtp_server": smtp_server,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            
        except smtplib.SMTPRecipientsRefused as e:
            error_msg = f"Recipients refused: {e}"
            logger.error(error_msg)
            return {
                "status": "error",
                "message": f"Recipient email address refused: {to_email}",
                "error": str(e),
                "attempt": attempt + 1,
                "recipient": to_email,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            
        except smtplib.SMTPSenderRefused as e:
            error_msg = f"Sender refused: {e}"
            logger.error(error_msg)
            return {
                "status": "error",
                "message": "Sender email address refused",
                "error": str(e),
                "attempt": attempt + 1,
                "sender": "compliance@pridecons.com",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            
        except smtplib.SMTPConnectError as e:
            error_msg = f"SMTP connection failed on attempt {attempt + 1}: {e}"
            logger.error(error_msg)
            last_error = e
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2  # Exponential backoff
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                continue
                
        except smtplib.SMTPException as e:
            error_msg = f"SMTP error on attempt {attempt + 1}: {e}"
            logger.error(error_msg)
            last_error = e
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                continue
                
        except Exception as e:
            error_msg = f"Unexpected error on attempt {attempt + 1}: {e}"
            logger.error(error_msg)
            last_error = e
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                continue
    
    # If we reach here, all attempts failed
    return {
        "status": "error",
        "message": f"Failed to send email after {max_retries} attempts",
        "error": str(last_error) if last_error else "Unknown error",
        "attempts": max_retries,
        "recipient": to_email,
        "subject": subject,
        "smtp_server": smtp_server,
        "smtp_port": smtp_port,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
