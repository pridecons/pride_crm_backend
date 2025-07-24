from fastapi.responses import JSONResponse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib
import ssl
from config import COM_SMTP_SERVER, COM_SMTP_PORT, COM_SMTP_USER, COM_SMTP_PASSWORD

def send_mail_by_client(to_email: str, subject: str, html_content: str):
    """
    Send a payment link email with enhanced HTML design and disclaimer.
    """
    smtp_server = COM_SMTP_SERVER
    smtp_port   = COM_SMTP_PORT
    smtp_user   = COM_SMTP_USER
    smtp_pass   = COM_SMTP_PASSWORD
    
    # Build the email
    msg = MIMEMultipart("alternative")
    msg["From"]    = "Pride Trading Consultancy <compliance@pridecons.com>"
    msg["To"]      = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = "compliance@pridecons.com"
    print("html_content : ",html_content)
    print("subject : ",subject)
    print("to_email : ",to_email)
    # Attach both parts
    # msg.attach(MIMEText(html_content, "plain"))
    # msg.attach(MIMEText(html_content, "html"))
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

    print("html_content_text : ",html_content_text)

    msg.attach(MIMEText(html_content_text, "html"))

    # Send via SMTP SSL
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_server, 465, context=context) as server:
            server.login(smtp_user, smtp_pass)
            print("msg : ",msg)
            server.send_message(msg)
            print("Done mail!.")

        return {
            "status": "success",
            "message": "Payment link email sent successfully!",
            "subject": subject,
            "email_type": "Enhanced HTML with responsive design"
        }

    except Exception as e:
        print(f"Email sending error: {e}")
        return JSONResponse(
            content={
                "status": "error",
                "message": "Failed to send payment link email",
                "error": str(e),
                "timestamp": "2025-07-16"
            },
            status_code=500
        )