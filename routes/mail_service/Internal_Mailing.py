# routes/internal_mailing.py

from typing import List, Optional, Set, Tuple, Dict, Union
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

import smtplib, ssl, mimetypes, io
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from config import COM_SMTP_SERVER, COM_SMTP_PORT, COM_SMTP_USER, COM_SMTP_PASSWORD
from db.connection import get_db
from db.models import UserDetails, ProfileRole
from routes.auth.auth_dependency import get_current_user

router = APIRouter(
    prefix="/internal-mailing",
    tags=["Internal Mailing"],
)

# ---------------- helpers ----------------
def _role(current_user: UserDetails) -> str:
    return (getattr(current_user, "role_name", "") or "").upper()

def _ensure_smtp() -> Tuple[smtplib.SMTP_SSL, str]:
    context = ssl.create_default_context()
    server = smtplib.SMTP_SSL(COM_SMTP_SERVER, COM_SMTP_PORT, context=context)
    server.login(COM_SMTP_USER, COM_SMTP_PASSWORD)
    sender = COM_SMTP_USER
    return server, sender

def _attach_files(msg: MIMEMultipart, files: List[UploadFile]) -> None:
    for f in files or []:
        if not f.filename:
            continue
        content = f.file.read()
        f.file.seek(0)
        ctype, _ = mimetypes.guess_type(f.filename)
        if not ctype:
            ctype = "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        part = MIMEBase(maintype, subtype)
        part.set_payload(content)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{f.filename}"')
        msg.attach(part)


def _build_message(sender: str, to_email: str, subject: str, body: str, attachments: List[UploadFile]) -> MIMEMultipart:
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = to_email
    msg["Subject"] = subject
    # Prefer HTML, but also include plain text fallback if desired
    msg.attach(MIMEText(body, "html"))
    _attach_files(msg, attachments)
    return msg

def _collect_by_profiles(db: Session, profile_ids: List[int]) -> List[UserDetails]:
    if not profile_ids:
        return []
    return (
        db.query(UserDetails)
        .filter(
            UserDetails.is_active.is_(True),
            UserDetails.role_id.in_(profile_ids),
            UserDetails.email.isnot(None),
        )
        .all()
    )

def _collect_by_employees(db: Session, employee_codes: List[str]) -> List[UserDetails]:
    if not employee_codes:
        return []
    return (
        db.query(UserDetails)
        .filter(
            UserDetails.is_active.is_(True),
            UserDetails.employee_code.in_(employee_codes),
            UserDetails.email.isnot(None),
        )
        .all()
    )

def _collect_by_branches(db: Session, branch_ids: List[int]) -> List[UserDetails]:
    if not branch_ids:
        return []
    return (
        db.query(UserDetails)
        .filter(
            UserDetails.is_active.is_(True),
            UserDetails.branch_id.in_(branch_ids),
            UserDetails.email.isnot(None),
        )
        .all()
    )

def _collect_all(db: Session) -> List[UserDetails]:
    return (
        db.query(UserDetails)
        .filter(UserDetails.is_active.is_(True), UserDetails.email.isnot(None))
        .all()
    )

def _dedupe_emails(users: List[UserDetails]) -> Dict[str, UserDetails]:
    out = {}
    for u in users or []:
        em = (u.email or "").strip().lower()
        if em and em not in out:
            out[em] = u
    return out


@router.post(
    "/send",
    status_code=status.HTTP_200_OK,
    summary="Send internal emails by profile / employees / branches / all",
)
async def send_internal_mail(
    subject: str = Form(..., description="Email subject"),
    body: str = Form(..., description="Email HTML body"),
    mode: str = Form(..., description="One of: profiles | employees | branches | all"),
    # lists (optional, depending on mode)
    profile_ids: Optional[str] = Form(None, description="Comma-separated role ids"),
    employee_ids: Optional[str] = Form(None, description="Comma-separated employee_codes"),
    branch_ids: Optional[str] = Form(None, description="Comma-separated branch ids"),
    # accept single OR multiple files
    files: Union[List[UploadFile], UploadFile, None] = File(default=None),
    db: Session = Depends(get_db),
    current_user: UserDetails = Depends(get_current_user),
):
    """
    Rules:
    - SUPERADMIN: may use all modes, including 'all' and any branches
    - BRANCH_MANAGER: may use 'profiles', 'employees', and 'branches' *but only within their branch*; cannot use 'all'
    - Other users: may use 'profiles' or 'employees' targeting only recipients within their visibility (same branch)
    """

    role = _role(current_user)

    # Parse CSV params into lists
    def _parse_csv(s: Optional[str]) -> List[str]:
        return [x.strip() for x in (s or "").split(",") if x.strip()]

    profile_id_list = [int(x) for x in _parse_csv(profile_ids)]
    employee_id_list = _parse_csv(employee_ids)
    branch_id_list = [int(x) for x in _parse_csv(branch_ids)]

    # Permission checks per mode
    mode = mode.lower().strip()
    if mode not in {"profiles", "employees", "branches", "all"}:
        raise HTTPException(status_code=400, detail="Invalid mode. Use: profiles | employees | branches | all")

    if mode == "all" and role != "SUPERADMIN":
        raise HTTPException(status_code=403, detail="Only SUPERADMIN can mail all employees")

    if mode == "branches":
        if role not in {"SUPERADMIN", "BRANCH_MANAGER"}:
            raise HTTPException(status_code=403, detail="Only SUPERADMIN or BRANCH_MANAGER can mail by branch")
        if role == "BRANCH_MANAGER":
            if current_user.branch_id is None:
                raise HTTPException(status_code=403, detail="Branch manager has no branch assigned")
            if not branch_id_list:
                branch_id_list = [int(current_user.branch_id)]
            if any(bid != int(current_user.branch_id) for bid in branch_id_list):
                raise HTTPException(status_code=403, detail="Branch manager can only target their own branch")

    # Collect recipients
    recipients: List[UserDetails] = []
    if mode == "profiles":
        if not profile_id_list:
            raise HTTPException(status_code=400, detail="profile_ids is required for mode=profiles")
        recipients = _collect_by_profiles(db, profile_id_list)
    elif mode == "employees":
        if not employee_id_list:
            raise HTTPException(status_code=400, detail="employee_ids is required for mode=employees")
        recipients = _collect_by_employees(db, employee_id_list)
    elif mode == "branches":
        if not branch_id_list:
            raise HTTPException(status_code=400, detail="branch_ids is required for mode=branches")
        recipients = _collect_by_branches(db, branch_id_list)
    elif mode == "all":
        recipients = _collect_all(db)

    # Scope for non-admins
    if role not in {"SUPERADMIN"}:
        user_branch = current_user.branch_id
        recipients = [u for u in recipients if u.branch_id == user_branch]

    deduped = _dedupe_emails(recipients)
    if not deduped:
        return JSONResponse(
            status_code=200,
            content={
                "sent": 0,
                "failed": 0,
                "message": "No recipients found for the selected filters",
                "recipients": [],
            },
        )

    # --- Normalize files to a list ---
    if files is None:
        file_list: List[UploadFile] = []
    elif isinstance(files, list):
        file_list = files
    else:
        file_list = [files]
    # ---------------------------------

    server, sender = _ensure_smtp()
    sent = 0
    failed = 0
    details = []

    try:
        for email_addr, user in deduped.items():
            try:
                msg = _build_message(sender, email_addr, subject, body, file_list)
                server.sendmail(sender, [email_addr], msg.as_string())
                sent += 1
                details.append({"email": email_addr, "status": "SENT"})
            except Exception as e:
                failed += 1
                details.append({"email": email_addr, "status": "FAILED", "error": str(e)})
        return {
            "mode": mode,
            "subject": subject,
            "sent": sent,
            "failed": failed,
            "total_recipients": len(deduped),
            "details": details,
        }
    finally:
        try:
            server.quit()
        except Exception:
            pass


