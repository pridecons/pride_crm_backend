import ssl
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config import COM_SMTP_SERVER, COM_SMTP_PORT, COM_SMTP_USER, COM_SMTP_PASSWORD
from jinja2 import Template

def render_template(template_str: str, context: dict) -> str:
    """Render a Jinja2 template string with the given context."""
    return Template(template_str).render(**context)

def send_mail(
    to_email: str,
    subject: str,
    body_html: str
) -> None:
    """Send an HTML email via SMTP."""
    msg = MIMEMultipart("alternative")
    msg["From"] = "Pride Trading Consultancy Pvt. Ltd. <compliance@pridecons.com>"
    msg["To"] = to_email
    msg["Subject"] = subject

    # attach HTML body
    msg.attach(MIMEText(body_html, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(COM_SMTP_SERVER, COM_SMTP_PORT, context=context) as server:
        server.login(COM_SMTP_USER, COM_SMTP_PASSWORD)
        server.send_message(msg)
