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
            html_content = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <!-- Hint to clients that both themes are supported -->
  <meta name="color-scheme" content="light dark">
  <meta name="supported-color-schemes" content="light dark">
  <title>{subject}</title>
  <style>
    /* ===== Base (light) ===== */
    body {{
      margin:0; padding:0;
      background:#ffffff; color:#333333;
      font-family: Arial, sans-serif; line-height:1.6;
    }}
    .wrap {{ max-width:600px; margin:0 auto; }}
    .content {{
      background:#f9f9f9; padding:30px;
      border-radius:0 0 10px 10px;
    }}
    .footer {{
      background:#ffffff; color:#333333;
      padding:20px; text-align:center; font-size:12px; margin-top:20px; border-radius:5px;
    }}
    /* Buttons & links in light */
    a {{ color:#1d4ed8; }}
    .btn {{
      display:inline-block; background:#3498db; color:#ffffff !important;
      padding:15px 30px; text-decoration:none; border-radius:5px; font-weight:bold;
    }}
    .btn:hover {{ background:#2980b9; }}
    .warning {{
      background:#f8f9fa; border-left:4px solid #17a2b8;
      padding:15px; margin:20px 0; color:#555555;
    }}

    /* ===== Dark mode overrides ===== */
    @media (prefers-color-scheme: dark) {{
      body {{ background:#0b0e14 !important; color:#e5e7eb !important; }}
      .content {{ background:#121723 !important; color:#e5e7eb !important; }}
      .footer {{ background:#0b0e14 !important; color:#cbd5e1 !important; }}
      a {{ color:#93c5fd !important; }}
      .btn {{ background:#60a5fa !important; color:#0b0e14 !important; }}
      .btn:hover {{ background:#93c5fd !important; }}
      .warning {{
        background:#0f172a !important; border-left-color:#38bdf8 !important; color:#cbd5e1 !important;
      }}
    }}

    /* Outlook.com / Office 365 dark mode hint */
    [data-ogsc] body,
    [data-ogsc] .content {{ background:#0b0e14 !important; color:#e5e7eb !important; }}
    [data-ogsc] .footer {{ background:#0b0e14 !important; color:#cbd5e1 !important; }}
    [data-ogsc] a {{ color:#93c5fd !important; }}
    [data-ogsc] .btn {{ background:#60a5fa !important; color:#0b0e14 !important; }}
  </style>
</head>
<body>
  <div class="wrap">
    <!-- Your same content goes here, unchanged -->
    <div class="content">
      {content}
    </div>

    <div class="footer">
      <strong>Pride Trading Consultancy Pvt. Ltd.</strong><br>
      <strong>Sebi Registered Research Analyst</strong><br>
      <strong>Sebi Registration No.: INH000010362</strong><br>
      📧 Email: compliance@pridecons.com<br>
      📞 Phone: +91-9981919424<br>
      🌐 Website: www.pridecons.com<br><br>
      <small>This is an automated email. Please do not reply directly to this email.</small>
    </div>
  </div>
</body>
</html>"""

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
    

    