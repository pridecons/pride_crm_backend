from __future__ import annotations

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.utils import parseaddr

import smtplib
import ssl
import time
import logging
import socket
from typing import Dict, Any, Optional
from pathlib import Path

# ---- Your config (ensure these are set) ----
from config import COM_SMTP_SERVER, COM_SMTP_PORT, COM_SMTP_USER, COM_SMTP_PASSWORD

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Try to import dnspython for MX lookups (optional)
try:
    import dns.resolver  # type: ignore
    _HAS_DNSPYTHON = True
except Exception:
    dns = None
    _HAS_DNSPYTHON = False


# =============================================================================
# Paths (resolved relative to THIS file, not CWD)
# =============================================================================
MODULE_DIR = Path(__file__).resolve().parent
CHARTER_PATH = MODULE_DIR / "Files" / "Investor Charter for Research Analyst.pdf"
CHARTER_NAME = "Investor Charter for Research Analyst.pdf"  # filename shown to recipient


# =============================================================================
# SMTP recipient probe (best-effort pre-validation)
# =============================================================================
def validate_recipient_smtp(
    recipient: str,
    probe_from: str = "bounce-noreply@pridecons.com",
    timeout: int = 10,
) -> Dict[str, Any]:
    """
    Best-effort SMTP probe:
      1) Resolve MX for recipient domain.
      2) Connect and issue MAIL FROM + RCPT TO (no DATA).
    Returns: { 'ok': bool|None, 'code': int|None, 'message': str }
      ok=True   -> server explicitly accepted RCPT during probe
      ok=False  -> server explicitly rejected RCPT (e.g., 550)
      ok=None   -> inconclusive (accept-all domain, no MX, DNS missing, temp error, etc.)
    """
    name, addr = parseaddr(recipient)
    if not addr or "@" not in addr:
        return {"ok": False, "code": None, "message": "Invalid email format"}

    local, domain = addr.rsplit("@", 1)
    domain = domain.strip().lower()

    if not _HAS_DNSPYTHON:
        return {"ok": None, "code": None, "message": "dnspython not installed; skipping MX probe"}

    # Resolve MX
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=timeout)  # type: ignore
        mx_hosts = sorted([(r.preference, str(r.exchange).rstrip(".")) for r in answers], key=lambda x: x[0])
        if not mx_hosts:
            return {"ok": None, "code": None, "message": "No MX records found"}
    except Exception as e:
        return {"ok": None, "code": None, "message": f"MX lookup failed: {e}"}

    last_err: Optional[Exception] = None
    for _, mx_host in mx_hosts:
        try:
            with smtplib.SMTP(mx_host, 25, timeout=timeout) as smtp:
                smtp.ehlo_or_helo_if_needed()

                # STARTTLS if supported
                if smtp.has_extn("starttls"):
                    context = ssl.create_default_context()
                    smtp.starttls(context=context)
                    smtp.ehlo()

                code, resp = smtp.mail(probe_from)
                if code >= 400:
                    return {"ok": None, "code": code, "message": f"MAIL FROM refused: {resp!r}"}

                code, resp = smtp.rcpt(addr)
                # 250/251 ~ accepted, 550/551/553 ~ invalid, 450/451/452 ~ temp/greylist
                if 200 <= code < 300:
                    return {"ok": True, "code": code, "message": f"RCPT accepted: {resp!r}"}
                elif code in (550, 551, 553):
                    return {"ok": False, "code": code, "message": f"RCPT rejected: {resp!r}"}
                else:
                    return {"ok": None, "code": code, "message": f"Inconclusive RCPT status: {code} {resp!r}"}
        except (socket.timeout, smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, smtplib.SMTPHeloError) as e:
            last_err = e
            continue
        except Exception as e:
            last_err = e
            continue

    return {"ok": None, "code": None, "message": f"Could not complete probe via MX hosts. Last error: {last_err}"}


# =============================================================================
# Main send function
# =============================================================================
def send_mail_by_client_with_file(
    to_email: str,
    subject: str,
    html_content: str,
    pdf_file_path: Optional[str] = None,
    max_retries: int = 3,
    validate_recipient: bool = False,          # enable pre-flight probe
    require_positive_validation: bool = False, # if True, fail on not-ok
    show_pdf: bool = True,
) -> Dict[str, Any]:
    """
    Sends an HTML email with optional PDF attachment and always attaches the Investor Charter.
    Optionally pre-validates the recipient via SMTP RCPT probe.

    Returns dict with keys:
      status: "success" | "partial_success" | "error"
      message: str
      (and additional diagnostics)
    """
    smtp_server = COM_SMTP_SERVER
    smtp_port   = COM_SMTP_PORT
    smtp_user   = COM_SMTP_USER
    smtp_pass   = COM_SMTP_PASSWORD

    # Basic checks
    if not all([to_email, subject, html_content]):
        return {"status": "error", "message": "Missing required parameters", "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}
    if not all([smtp_server, smtp_port, smtp_user, smtp_pass]):
        return {"status": "error", "message": "Missing SMTP configuration parameters", "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}

    # Optional best-effort recipient validation
    if validate_recipient:
        probe = validate_recipient_smtp(to_email)
        logger.info(f"SMTP probe for {to_email}: {probe}")
        if require_positive_validation:
            if probe.get("ok") is not True:
                return {
                    "status": "error",
                    "message": f"Recipient validation failed/inconclusive: {probe.get('message')}",
                    "recipient": to_email,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
        else:
            if probe.get("ok") is False:
                return {
                    "status": "error",
                    "message": f"Recipient rejected during SMTP probe: {probe.get('message')}",
                    "recipient": to_email,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                }

    # Build message
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
            return {"status": "error", "message": f"Could not attach PDF: {e}", "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}

    # Always attach Investor Charter
    if show_pdf:
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
            # uncomment to enforce:
            # return {"status": "error", "message": f"Could not attach Investor Charter: {e}", "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}

    # Send (requesting DSN if server supports)
    last_error: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(COM_SMTP_SERVER, COM_SMTP_PORT, context=context, timeout=30) as server:
                server.login(COM_SMTP_USER, COM_SMTP_PASSWORD)

                # Use sendmail to specify rcpt_options (DSN request). Server may ignore DSN.
                from_addr = parseaddr(msg.get("From"))[1] or COM_SMTP_USER
                to_addrs = [to_email]
                raw_msg = msg.as_string()

                mail_opts = []  # e.g., ["SMTPUTF8"] if needed
                rcpt_opts = ["NOTIFY=SUCCESS,FAILURE,DELAY"]

                rejected = server.sendmail(from_addr, to_addrs, raw_msg,
                                           mail_options=mail_opts, rcpt_options=rcpt_opts)

            if rejected:
                return {
                    "status": "partial_success",
                    "message": "Some recipients rejected during SMTP transaction",
                    "rejected_recipients": rejected,
                    "recipient": to_email,
                    "subject": subject,
                    "attempt": attempt,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                }

            return {
                "status": "success",
                "message": "SMTP accepted the message (delivery may still bounce later).",
                "recipient": to_email,
                "subject": subject,
                "email_type": "Enhanced HTML with PDF attachment",
                "attempt": attempt,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        except Exception as e:
            last_error = e
            logger.exception(f"SMTP send attempt {attempt} failed: {e}")
            if attempt < max_retries:
                time.sleep(attempt * 2)

    return {
        "status": "error",
        "message": f"Failed to send email after {max_retries} attempts",
        "error": str(last_error) if last_error else "Unknown",
        "recipient": to_email,
        "subject": subject,
        "attempts": max_retries,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


# =============================================================================
# Static test block
# =============================================================================
# if __name__ == "__main__":
#     # ---- Static test data ----
#     test_to_email = "rajmalviya545@gmail.com"   # try invalid; switch to your email for a real send
#     test_subject  = "Test Email from Pride Trading Consultancy"
#     test_html     = """
#     <h2 style="color:#2b6cb0;">Hello, Investor!</h2>
#     <p>This is a <b>test email</b> generated for validation purposes.</p>
#     <p>Please find the mandatory Investor Charter attached.</p>
#     """

#     # Optional extra attachment; the charter is attached anyway.
#     # Put a small dummy file at MODULE_DIR/Files/dummy.pdf if you want.
#     test_pdf_path = (MODULE_DIR / "Files" / "dummy.pdf")
#     test_pdf_path_str = str(test_pdf_path) if test_pdf_path.exists() else None

#     result = send_mail_by_client_with_file(
#         to_email=test_to_email,
#         subject=test_subject,
#         html_content=test_html,
#         pdf_file_path=test_pdf_path_str,   # can be None
#         max_retries=1,                     # quick test
#         validate_recipient=True,           # enable pre-flight probe
#         require_positive_validation=False  # set True to hard-fail on inconclusive
#     )

#     print("=== Mail Send Result ===")
#     for k, v in result.items():
#         print(f"{k}: {v}")
