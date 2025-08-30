# routes/mail_service/send_mail.py - FIXED VERSION with HTML Support

from fastapi.responses import JSONResponse
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib
import ssl
from config import COM_SMTP_SERVER, COM_SMTP_PORT, COM_SMTP_USER, COM_SMTP_PASSWORD

async def send_mail(email, name, subject, content, is_html=False):
    smtp_server = COM_SMTP_SERVER
    smtp_port = COM_SMTP_PORT
    smtp_user = COM_SMTP_USER
    smtp_pass = COM_SMTP_PASSWORD

    try:
        if is_html:
            # Create multipart message for HTML email
            msg = MIMEMultipart('alternative')
            msg["From"] = "Pride Trading Consultancy Pvt. Ltd. <compliance@pridecons.com>"
            msg["To"] = email
            msg["Subject"] = subject
            
            # Create plain text version (fallback)
            text_content = f"""
Dear {name},

{content if not is_html else 'Please view this email in an HTML-capable email client.'}

Thanks & Regards  
Pride Trading Consultancy Pvt. Ltd.
Email: compliance@pridecons.com
Phone: +91-9981919424
Website: www.pridecons.com
            """
            
            # Create HTML version
            html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{subject}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            text-align: center;
            border-radius: 10px 10px 0 0;
        }}
        .content {{
            background: #f9f9f9;
            padding: 30px;
            border-radius: 0 0 10px 10px;
        }}
        .footer {{
            background: #2c3e50;
            color: white;
            padding: 20px;
            text-align: center;
            font-size: 12px;
            margin-top: 20px;
            border-radius: 5px;
        }}
        .btn {{
            display: inline-block;
            background-color: #3498db;
            color: white;
            padding: 15px 30px;
            text-decoration: none;
            border-radius: 5px;
            font-weight: bold;
            margin: 20px 0;
        }}
        .btn:hover {{
            background-color: #2980b9;
        }}
        .warning {{
            background-color: #f8f9fa;
            border-left: 4px solid #17a2b8;
            padding: 15px;
            margin: 20px 0;
        }}
    </style>
</head>
<body>   
    <div class="content">
        {content}
    </div>
    
    <div class="footer">
        <strong>Pride Trading Consultancy Pvt. Ltd.</strong><br>
        <strong>Sebi Registered Research Analyst</strong><br>
        <strong>Sebi Registration No.: INH000010362</strong><br>
        📧 Email: compliance@pridecons.com<br>
        📞 Phone: +91-9981919424<br>
        🌐 Website: www.pridecons.com<br>
        <br>
        <small>This is an automated email. Please do not reply directly to this email.</small>
    </div>
</body>
</html>
            """
            
            # Attach parts
            part1 = MIMEText(text_content, 'plain')
            part2 = MIMEText(html_content, 'html')
            
            msg.attach(part1)
            msg.attach(part2)
            
        else:
            # Create simple text email
            msg = EmailMessage()
            msg["From"] = "Pride Trading Consultancy Pvt. Ltd. <compliance@pridecons.com>"
            msg["To"] = email
            msg["Subject"] = subject
            
            text_content = f"""
Dear {name},

{content}

Thanks & Regards  
Pride Trading Consultancy Pvt. Ltd.
Email: compliance@pridecons.com
Phone: +91-9981919424
Website: www.pridecons.com

---
This is an automated email. Please do not reply directly to this email.
            """
            
            msg.set_content(text_content)

        # Send email
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context) as server:
            server.login(smtp_user, smtp_pass)
            
            if is_html:
                server.send_message(msg)
            else:
                server.send_message(msg)

        return {
            "message": "Email sent successfully!",
            "email": email,
            "name": name,
            "subject": subject,
            "type": "HTML" if is_html else "Plain Text"
        }

    except Exception as e:
        print(f"Email sending error: {str(e)}")
        return JSONResponse(
            content={
                "message": "Failed to send email",
                "error": str(e),
                "email": email,
                "name": name
            }, 
            status_code=500
        )
    

    