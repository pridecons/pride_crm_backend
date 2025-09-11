from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query, Form
from typing import Optional, List, Dict, Any
import csv, io, re, secrets, string
from sqlalchemy import func, cast, Integer
from sqlalchemy.orm import Session
import hashlib
import bcrypt

from db.connection import get_db
from db.models import UserDetails, ProfileRole

router = APIRouter(
    prefix="/users",
    tags=["users"],
)

# ---------------- Employee code ----------------
def _next_emp_code(db: Session) -> str:
    """
    Robustly compute next EMP code by extracting numeric suffix and taking max+1.
    Works even if some rows were deleted.
    """
    # Postgres: regexp_replace(text, pattern, replacement, flags)
    max_num = db.query(
        func.max(
            cast(
                func.nullif(
                    func.regexp_replace(UserDetails.employee_code, r'[^0-9]', '', 'g'),
                    ''
                ),
                Integer,
            )
        )
    ).scalar()
    nxt = (max_num or 0) + 1
    return f"EMP{nxt:03d}"

def _gen_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    pwd = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
    ]
    pwd += [secrets.choice(alphabet) for _ in range(max(0, length - len(pwd)))]
    secrets.SystemRandom().shuffle(pwd)
    return ''.join(pwd)

def _norm(s: Any) -> str:
    return (str(s).strip() if s is not None else "")

# ---------------- Header mapping ----------------
_HEADER_ALIASES = {
    "employee_code": {"empcode", "employee code", "emp_code"},
    "name": {"name", "full_name", "employee_name"},
    "email": {"email,mail", "mail", "email_id", "email"},
    "phone_number": {"phone", "mobile", "mobile_no", "phone_number", "contact"},
    "role_id": {"role_id", "roleid"},
    "role_name": {"role", "role_name", "rolename"},
    "branch_id": {"branch", "branch_id"},
    "password": {"password", "pass", "pwd"},
    "father_name": {"father_name"},
    "experience": {"experience", "exp"},
    "date_of_joining": {"date_of_joining", "doj", "joining_date"},
    "date_of_birth": {"date_of_birth", "dob", "birth_date"},
    "pan": {"pan"},
    "aadhaar": {"aadhaar", "aadhar"},
    "address": {"address"},
    "city": {"city"},
    "state": {"state"},
    "pincode": {"pincode", "pin", "zip"},
    "comment": {"comment", "remarks", "note"},
    "senior_profile_id": {"senior_profile_id", "senior_empcode", "reporting_to"},
    "vbc_extension_id": {"vbc_extension_id", "vbc_ext"},
    "vbc_user_username": {"vbc_user_username", "vbc_username"},
    "vbc_user_password": {"vbc_user_password", "vbc_password"},
    "target": {"target", "monthly_target"},
}

def _canonicalize_headers(headers: List[str]) -> Dict[int, str]:
    can: Dict[int, str] = {}
    for idx, raw in enumerate(headers):
        h = _norm(raw).lower()
        matched = None
        for canonical, aliases in _HEADER_ALIASES.items():
            if h == canonical or h in aliases:
                matched = canonical
                break
        can[idx] = matched or h
    return can

def _read_rows(file: UploadFile) -> List[Dict[str, Any]]:
    name = (file.filename or "").lower()
    content = file.file.read()
    if not content:
        return []

    # Try XLSX if extension suggests Excel
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        try:
            import openpyxl  # optional dependency
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                return []
            headers = [(_norm(c)) for c in rows[0]]
            canon = _canonicalize_headers([str(h) for h in headers])
            out = []
            for r in rows[1:]:
                row = {}
                for idx, v in enumerate(r):
                    key = canon.get(idx)
                    if key:
                        row[key] = v if v is not None else ""
                out.append(row)
            return out
        except Exception:
            # fall through to CSV
            pass

    # CSV/TSV
    try:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")

        sample = text[:4096]
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        reader = csv.reader(io.StringIO(text), dialect)
        rows = list(reader)
        if not rows:
            return []
        headers = [(_norm(c)) for c in rows[0]]
        canon = _canonicalize_headers(headers)
        out = []
        for r in rows[1:]:
            row = {}
            for idx, v in enumerate(r):
                key = canon.get(idx)
                if key:
                    row[key] = v
            out.append(row)
        return out
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {e}")

def _resolve_role_id(db: Session, row: Dict[str, Any]) -> int:
    rid = _norm(row.get("role_id"))
    if rid:
        try:
            return int(rid)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid role_id '{rid}'")
    rname = _norm(row.get("role_name"))
    if not rname:
        raise HTTPException(status_code=400, detail="Either role_id or role_name must be provided")
    role = db.query(ProfileRole).filter(func.lower(ProfileRole.name) == rname.lower()).first()
    if not role:
        raise HTTPException(status_code=404, detail=f"Role '{rname}' not found")
    return int(role.id)

def _as_int_or_none(v: Any) -> Optional[int]:
    s = _norm(v)
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None

# ---------------- Role → Department ----------------
def _department_id_for_role(db: Session, role_id: int) -> Optional[int]:
    role = db.query(ProfileRole).filter(ProfileRole.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail=f"ProfileRole {role_id} not found")
    return getattr(role, "department_id", None)

# ---------------- Password utils ----------------
def hash_password(password: str) -> str:
    """Hash password with bcrypt; fallback to sha256 if bcrypt unavailable."""
    try:
        # some environments may not have gensalts (typo); keep safe fallback
        salt = getattr(bcrypt, "gensalts", None) and bcrypt.gensalts() or bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
        return hashed.decode("utf-8")
    except Exception:
        return hashlib.sha256(password.encode()).hexdigest()

# ---------------- Bulk create ----------------
@router.post("/bulk", status_code=status.HTTP_201_CREATED)
def bulk_create_users(
    file: UploadFile = File(..., description="CSV or XLSX with user rows"),
    dry_run: bool = Query(False, description="Validate only; do not insert"),
    # NEW: force role/branch for all rows (coming from multipart form)
    force_role_id: Optional[int] = Form(None),
    force_branch_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    """
    Bulk create users from CSV/XLSX.

    Required per row when NOT forced:
      - name, email, phone_number, role_id/role_name, branch_id
    If `force_role_id` and/or `force_branch_id` are provided,
    they override every row for role/branch respectively.

    Behavior:
      - Maps role -> department automatically (via _department_id_for_role)
      - Generates unique employee_code per created row
      - Skips duplicates on email/phone_number with an error record
      - Returns a detailed per-row report
      - `dry_run=true` validates without writing
    """
    rows = _read_rows(file)
    if not rows:
        raise HTTPException(status_code=400, detail="No rows found in uploaded file")

    # Apply overrides before validation
    if force_role_id is not None:
        # simple validation that role exists
        _ = _department_id_for_role(db, int(force_role_id))  # raises if missing
        for r in rows:
            r["role_id"] = str(force_role_id)
            r.pop("role_name", None)

    if force_branch_id is not None:
        for r in rows:
            r["branch_id"] = str(force_branch_id)

    # Preload uniqueness
    existing_emails = {
        e for (e,) in db.query(UserDetails.email).filter(UserDetails.email.isnot(None)).all()
    }
    existing_phones = {
        p for (p,) in db.query(UserDetails.phone_number).filter(UserDetails.phone_number.isnot(None)).all()
    }

    results: List[Dict[str, Any]] = []
    to_create: List[UserDetails] = []
    generated_passwords: Dict[str, str] = {}
    seen_emails: set = set()
    seen_phones: set = set()

    for idx, row in enumerate(rows, start=2):  # header is row 1
        rec: Dict[str, Any] = {"row": idx, "status": "pending"}
        try:
            name = _norm(row.get("name"))
            email = _norm(row.get("email")).lower()
            phone = re.sub(r"\D", "", _norm(row.get("phone_number")))

            if not name:
                raise ValueError("name is required")
            if not email:
                raise ValueError("email is required")
            if not phone:
                raise ValueError("phone_number is required")

            # Branch (after possible override)
            branch_id = _as_int_or_none(row.get("branch_id"))
            if branch_id is None:
                raise ValueError("branch_id is required (integer)")

            # Role (after possible override)
            role_id_val = _resolve_role_id(db, row)
            dept_id_val = _department_id_for_role(db, role_id_val)

            # Uniqueness
            if email in existing_emails or email in seen_emails:
                raise ValueError(f"Email already registered: {email}")
            if phone in existing_phones or phone in seen_phones:
                raise ValueError(f"Phone number already registered: {phone}")

            seen_emails.add(email)
            seen_phones.add(phone)

            # Password
            raw_password = _norm(row.get("password")) or _gen_password()
            if len(raw_password) < 6:
                raise ValueError("password must be at least 6 characters")
            hashed_pw = hash_password(raw_password)

            emp_code = _next_emp_code(db)

            user = UserDetails(
                employee_code=emp_code,
                phone_number=phone,
                email=email,
                name=name,
                password=hashed_pw,
                role_id=role_id_val,
                father_name=_norm(row.get("father_name")) or None,
                is_active=True,
                experience=_norm(row.get("experience")) or None,
                date_of_joining=row.get("date_of_joining") or None,
                date_of_birth=row.get("date_of_birth") or None,
                pan=_norm(row.get("pan")) or None,
                aadhaar=_norm(row.get("aadhaar")) or None,
                address=_norm(row.get("address")) or None,
                city=_norm(row.get("city")) or None,
                state=_norm(row.get("state")) or None,
                pincode=_norm(row.get("pincode")) or None,
                comment=_norm(row.get("comment")) or None,
                branch_id=branch_id,
                senior_profile_id=_norm(row.get("senior_profile_id")) or None,
                permissions=None,  # leave default on bulk
                vbc_extension_id=_norm(row.get("vbc_extension_id")) or None,
                vbc_user_username=_norm(row.get("vbc_user_username")) or None,
                vbc_user_password=_norm(row.get("vbc_user_password")) or None,
                target=_norm(row.get("target")) or None,
                department_id=dept_id_val,
            )

            to_create.append(user)
            generated_passwords[emp_code] = raw_password
            rec.update({
                "status": "ok",
                "employee_code": emp_code,
                "email": email,
                "phone_number": phone,
                "role_id": role_id_val,
                "department_id": dept_id_val,
            })
        except Exception as e:
            rec.update({"status": "error", "error": str(e)})
        results.append(rec)

    created = [r for r in results if r["status"] == "ok"]
    failed = [r for r in results if r["status"] == "error"]

    if dry_run:
        return {
            "dry_run": True,
            "summary": {"rows": len(rows), "will_create": len(created), "errors": len(failed)},
            "results": results,
        }

    # Persist
    try:
        for u in to_create:
            db.add(u)
        db.commit()

        for u in to_create:
            db.refresh(u)

        created_detail = []
        for u in to_create:
            plain = generated_passwords.get(u.employee_code, "")
            created_detail.append({
                "employee_code": u.employee_code,
                "name": u.name,
                "email": u.email,
                "phone_number": u.phone_number,
                "branch_id": u.branch_id,
                "role_id": int(u.role_id),
                "department_id": u.department_id,
                "password": plain,
                "password_masked": f"{plain[:2]}{'*'*(max(0,len(plain)-4))}{plain[-2:]}" if plain else None,
                "created_at": u.created_at,
            })

        return {
            "dry_run": False,
            "summary": {"rows": len(rows), "created": len(created_detail), "errors": len(failed)},
            "created": created_detail,
            "errors": failed,
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Bulk insert failed: {e}")
