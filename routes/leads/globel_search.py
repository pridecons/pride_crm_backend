# import json
# from typing import Optional, List, Any, Dict, Union, Literal, Tuple
# from datetime import datetime, date, timedelta, timezone

# from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form, Query
# from pydantic import BaseModel, validator
# from sqlalchemy.orm import Session
# from sqlalchemy import or_, and_, select, literal

# from db.connection import get_db
# from db.models import (
#     Lead, LeadAssignment,
# )
# from routes.auth.auth_dependency import get_current_user
# from utils.user_tree import get_subordinate_ids

# router = APIRouter(
#     prefix="/leads",
#     tags=["leads"],
# )

# # ----------------- helpers -----------------
# def _role(current_user) -> str:
#     """Uppercased role name from the denormalized column."""
#     return (getattr(current_user, "role_name", "") or "").upper()

# def _branch_id_for_manager(u) -> Optional[int]:
#     """Prefer managed branch; otherwise fall back to own branch_id."""
#     if getattr(u, "manages_branch", None):
#         return u.manages_branch.id
#     return getattr(u, "branch_id", None)

# def _exists_assignment_for_allowed(allowed_codes: List[str]):
#     """
#     SQL EXISTS(SELECT 1 FROM crm_lead_assignments ...)
#     correlated to Lead; TRUE if any assignment for this lead is in allowed_codes.
#     """
#     if not allowed_codes:
#         return literal(False)
#     return (
#         select(literal(1))
#         .select_from(LeadAssignment)
#         .where(
#             and_(
#                 LeadAssignment.lead_id == Lead.id,
#                 LeadAssignment.user_id.in_(allowed_codes),
#             )
#         )
#         .correlate(Lead)
#         .exists()
#     )

# # ----------------- output model & converters -----------------
# class LeadOut(BaseModel):
#     id: int
#     full_name: Optional[str] = None
#     director_name: Optional[str] = None
#     father_name: Optional[str] = None
#     gender: Optional[str] = None
#     marital_status: Optional[str] = None
#     email: Optional[str] = None
#     mobile: Optional[str] = None
#     alternate_mobile: Optional[str] = None
#     aadhaar: Optional[str] = None
#     pan: Optional[str] = None
#     gstin: Optional[str] = None
#     state: Optional[str] = None
#     city: Optional[str] = None
#     district: Optional[str] = None
#     address: Optional[str] = None
#     pincode: Optional[str] = None
#     country: Optional[str] = None
#     dob: Optional[date] = None
#     occupation: Optional[str] = None
#     segment: Optional[List[str]] = None
#     experience: Optional[str] = None
#     investment: Optional[str] = None
#     ft_service_type: Optional[str] = None
#     lead_response_id: Optional[int] = None
#     lead_source_id: Optional[int] = None
#     branch_id: Optional[int] = None
#     created_by: Optional[str] = None
#     created_by_name: Optional[str] = None
#     aadhar_front_pic: Optional[str] = None
#     aadhar_back_pic: Optional[str] = None
#     pan_pic: Optional[str] = None
#     kyc: Optional[bool] = False
#     kyc_id: Optional[str] = None
#     is_old_lead: Optional[bool] = False
#     call_back_date: Optional[datetime] = None
#     lead_status: Optional[str] = None
#     ft_to_date: Optional[str] = None
#     ft_from_date: Optional[str] = None
#     is_client: Optional[bool] = None
#     assigned_to_user: Optional[str] = None
#     response_changed_at: Optional[datetime] = None
#     assigned_for_conversion: Optional[bool] = False
#     conversion_deadline: Optional[datetime] = None
#     created_at: datetime

#     @validator("segment", pre=True, always=True)
#     def parse_segment(cls, v):
#         if v is None:
#             return None
#         if isinstance(v, str):
#             try:
#                 parsed = json.loads(v)
#                 return parsed if isinstance(parsed, list) else [parsed]
#             except json.JSONDecodeError:
#                 return [v] if v.strip() else None
#         if isinstance(v, list):
#             return v
#         return [str(v)] if v is not None else None

#     class Config:
#         from_attributes = True

# def safe_convert_lead_to_dict(lead) -> dict:
#     try:
#         lead_dict = {}
#         for column in lead.__table__.columns:
#             value = getattr(lead, column.name, None)
#             if column.name == "segment":
#                 if value is not None:
#                     try:
#                         parsed = json.loads(value)
#                         lead_dict[column.name] = parsed if isinstance(parsed, list) else [parsed]
#                     except (json.JSONDecodeError, TypeError):
#                         lead_dict[column.name] = [value] if value else []
#                 else:
#                     lead_dict[column.name] = None
#             else:
#                 lead_dict[column.name] = value
#         return lead_dict
#     except Exception:
#         return {
#             "id": getattr(lead, "id", None),
#             "full_name": getattr(lead, "full_name", None),
#             "director_name": getattr(lead, "director_name", None),
#             "father_name": getattr(lead, "father_name", None),
#             "gender": getattr(lead, "gender", None),
#             "marital_status": getattr(lead, "marital_status", None),
#             "email": getattr(lead, "email", None),
#             "mobile": getattr(lead, "mobile", None),
#             "alternate_mobile": getattr(lead, "alternate_mobile", None),
#             "aadhaar": getattr(lead, "aadhaar", None),
#             "pan": getattr(lead, "pan", None),
#             "gstin": getattr(lead, "gstin", None),
#             "state": getattr(lead, "state", None),
#             "city": getattr(lead, "city", None),
#             "district": getattr(lead, "district", None),
#             "address": getattr(lead, "address", None),
#             "pincode": getattr(lead, "pincode", None),
#             "country": getattr(lead, "country", None),
#             "dob": getattr(lead, "dob", None),
#             "occupation": getattr(lead, "occupation", None),
#             "experience": getattr(lead, "experience", None),
#             "investment": getattr(lead, "investment", None),
#             "ft_service_type": getattr(lead, "ft_service_type", None),
#             "created_at": getattr(lead, "created_at", datetime.now()),
#             "lead_status": getattr(lead, "lead_status", None),
#             "kyc": getattr(lead, "kyc", False),
#             "segment": None,
#             "lead_response_id": getattr(lead, "lead_response_id", None),
#             "lead_source_id": getattr(lead, "lead_source_id", None),
#             "branch_id": getattr(lead, "branch_id", None),
#             "created_by": getattr(lead, "created_by", None),
#             "created_by_name": getattr(lead, "created_by_name", None),
#             "aadhar_front_pic": getattr(lead, "aadhar_front_pic", None),
#             "aadhar_back_pic": getattr(lead, "aadhar_back_pic", None),
#             "pan_pic": getattr(lead, "pan_pic", None),
#             "kyc_id": getattr(lead, "kyc_id", None),
#             "is_old_lead": getattr(lead, "is_old_lead", False),
#             "call_back_date": getattr(lead, "call_back_date", None),
#         }

# # ----------------- SEARCH with visibility -----------------
# @router.get("/search/")
# def search_leads(
#     q: str,
#     search_type: str = "all",  # all, name, mobile, email, pan, aadhaar
#     db: Session = Depends(get_db),
#     current_user = Depends(get_current_user),
# ):
#     """
#     Visibility rules:
#       - SUPERADMIN: no restriction
#       - BRANCH_MANAGER: restricted to their branch
#       - Others: restricted to (self + all subordinates) assignments
#         (matches either Lead.assigned_to_user OR crm_lead_assignments.user_id)
#     """
#     try:
#         if not q or len(q.strip()) < 2:
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Search query must be at least 2 characters long",
#             )

#         # ---------- Base query ----------
#         query = db.query(Lead).filter(Lead.is_delete.is_(False))

#         # ---------- Role-based visibility ----------
#         role = _role(current_user)

#         if role == "SUPERADMIN":
#             pass  # no extra filters

#         elif role == "BRANCH_MANAGER":
#             b_id = _branch_id_for_manager(current_user)
#             if b_id is None:
#                 # Manager without a branch -> nothing visible
#                 query = query.filter(literal(False))
#             else:
#                 query = query.filter(Lead.branch_id == b_id)

#         else:
#             # Self + all subordinates
#             subs = get_subordinate_ids(db, current_user.employee_code)
#             allowed = [current_user.employee_code] + subs if subs else [current_user.employee_code]

#             query = query.filter(
#                 or_(
#                     Lead.assigned_to_user.in_(allowed),
#                     _exists_assignment_for_allowed(allowed),
#                 )
#             )

#         # ---------- Text search ----------
#         term = f"%{q.strip()}%"

#         if search_type == "name":
#             query = query.filter(
#                 or_(
#                     Lead.full_name.ilike(term),
#                     Lead.father_name.ilike(term),
#                     Lead.director_name.ilike(term),
#                 )
#             )
#         elif search_type == "mobile":
#             query = query.filter(or_(Lead.mobile.ilike(term), Lead.alternate_mobile.ilike(term)))
#         elif search_type == "email":
#             query = query.filter(Lead.email.ilike(term))
#         elif search_type == "pan":
#             query = query.filter(Lead.pan.ilike(term))
#         elif search_type == "aadhaar":
#             query = query.filter(Lead.aadhaar.ilike(term))
#         else:  # "all"
#             query = query.filter(
#                 or_(
#                     Lead.full_name.ilike(term),
#                     Lead.father_name.ilike(term),
#                     Lead.director_name.ilike(term),
#                     Lead.mobile.ilike(term),
#                     Lead.alternate_mobile.ilike(term),
#                     Lead.email.ilike(term),
#                     Lead.pan.ilike(term),
#                     Lead.aadhaar.ilike(term),
#                     Lead.city.ilike(term),
#                     Lead.state.ilike(term),
#                 )
#             )

#         # ---------- Execute ----------
#         leads = query.order_by(Lead.created_at.desc()).limit(50).all()

#         result: List[LeadOut] = []
#         for lead in leads:
#             try:
#                 lead_dict = safe_convert_lead_to_dict(lead)
#                 result.append(LeadOut(**lead_dict))
#             except Exception:
#                 # if any row is malformed, skip it but keep others
#                 continue

#         return {
#             "search_query": q,
#             "search_type": search_type,
#             "total_results": len(result),
#             "leads": result,
#         }

#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Error searching leads: {str(e)}",
#         )

import json
from typing import Optional, List, Any, Dict, Union, Literal, Tuple
from datetime import datetime, date, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form, Query
from pydantic import BaseModel, validator
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, select, literal, not_

from db.connection import get_db
from db.models import (
    Lead, LeadAssignment,
)
from routes.auth.auth_dependency import get_current_user
from utils.user_tree import get_subordinate_ids

router = APIRouter(
    prefix="/leads",
    tags=["leads"],
)

# ----------------- helpers -----------------
def _role(current_user) -> str:
    """Uppercased role name from the denormalized column."""
    return (getattr(current_user, "role_name", "") or "").upper()

def _branch_id_for_manager(u) -> Optional[int]:
    """Prefer managed branch; otherwise fall back to own branch_id."""
    if getattr(u, "manages_branch", None):
        return u.manages_branch.id
    return getattr(u, "branch_id", None)

def _exists_assignment_for_allowed(allowed_codes: List[str]):
    """
    SQL EXISTS(SELECT 1 FROM crm_lead_assignments ...)
    correlated to Lead; TRUE if any assignment for this lead is in allowed_codes.
    """
    if not allowed_codes:
        return literal(False)
    return (
        select(literal(1))
        .select_from(LeadAssignment)
        .where(
            and_(
                LeadAssignment.lead_id == Lead.id,
                LeadAssignment.user_id.in_(allowed_codes),
            )
        )
        .correlate(Lead)
        .exists()
    )

# ---------- masking helpers ----------
def mask_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    p = "".join(ch for ch in phone if ch.isdigit())
    if len(p) < 3:
        return "*" * len(p)
    # show first 3 digits, mask the rest (up to 10)
    shown = p[:3]
    stars = "*" * max(0, len(p) - 3)
    return f"{shown}{stars}"

def mask_email(email: Optional[str]) -> Optional[str]:
    if not email or "@" not in email:
        return None
    local, domain = email.split("@", 1)
    if len(local) <= 3:
        return f"{local[0] if local else ''}{'*' * max(0, len(local)-1)}@{domain}"
    return f"{local[:3]}{'*' * (len(local)-3)}@{domain}"

def mask_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    n = name.strip()
    if not n:
        return None
    if len(n) <= 2:
        return n[0] + "*"
    return n[0] + ("*" * (len(n)-2)) + n[-1]

# ----------------- output model & converters -----------------
class LeadOut(BaseModel):
    id: int
    full_name: Optional[str] = None
    director_name: Optional[str] = None
    father_name: Optional[str] = None
    gender: Optional[str] = None
    marital_status: Optional[str] = None
    email: Optional[str] = None
    mobile: Optional[str] = None
    alternate_mobile: Optional[str] = None
    aadhaar: Optional[str] = None
    pan: Optional[str] = None
    gstin: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = None
    dob: Optional[date] = None
    occupation: Optional[str] = None
    segment: Optional[List[str]] = None
    experience: Optional[str] = None
    investment: Optional[str] = None
    ft_service_type: Optional[str] = None
    lead_response_id: Optional[int] = None
    lead_source_id: Optional[int] = None
    branch_id: Optional[int] = None
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None
    aadhar_front_pic: Optional[str] = None
    aadhar_back_pic: Optional[str] = None
    pan_pic: Optional[str] = None
    kyc: Optional[bool] = False
    kyc_id: Optional[str] = None
    is_old_lead: Optional[bool] = False
    call_back_date: Optional[datetime] = None
    lead_status: Optional[str] = None
    ft_to_date: Optional[str] = None
    ft_from_date: Optional[str] = None
    is_client: Optional[bool] = None
    assigned_to_user: Optional[str] = None
    response_changed_at: Optional[datetime] = None
    assigned_for_conversion: Optional[bool] = False
    conversion_deadline: Optional[datetime] = None
    created_at: datetime

    @validator("segment", pre=True, always=True)
    def parse_segment(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return parsed if isinstance(parsed, list) else [parsed]
            except json.JSONDecodeError:
                return [v] if v.strip() else None
        if isinstance(v, list):
            return v
        return [str(v)] if v is not None else None

    class Config:
        from_attributes = True

def safe_convert_lead_to_dict(lead) -> dict:
    try:
        lead_dict = {}
        for column in lead.__table__.columns:
            value = getattr(lead, column.name, None)
            if column.name == "segment":
                if value is not None:
                    try:
                        parsed = json.loads(value)
                        lead_dict[column.name] = parsed if isinstance(parsed, list) else [parsed]
                    except (json.JSONDecodeError, TypeError):
                        lead_dict[column.name] = [value] if value else []
                else:
                    lead_dict[column.name] = None
            else:
                lead_dict[column.name] = value
        return lead_dict
    except Exception:
        return {
            "id": getattr(lead, "id", None),
            "full_name": getattr(lead, "full_name", None),
            "director_name": getattr(lead, "director_name", None),
            "father_name": getattr(lead, "father_name", None),
            "gender": getattr(lead, "gender", None),
            "marital_status": getattr(lead, "marital_status", None),
            "email": getattr(lead, "email", None),
            "mobile": getattr(lead, "mobile", None),
            "alternate_mobile": getattr(lead, "alternate_mobile", None),
            "aadhaar": getattr(lead, "aadhaar", None),
            "pan": getattr(lead, "pan", None),
            "gstin": getattr(lead, "gstin", None),
            "state": getattr(lead, "state", None),
            "city": getattr(lead, "city", None),
            "district": getattr(lead, "district", None),
            "address": getattr(lead, "address", None),
            "pincode": getattr(lead, "pincode", None),
            "country": getattr(lead, "country", None),
            "dob": getattr(lead, "dob", None),
            "occupation": getattr(lead, "occupation", None),
            "experience": getattr(lead, "experience", None),
            "investment": getattr(lead, "investment", None),
            "ft_service_type": getattr(lead, "ft_service_type", None),
            "created_at": getattr(lead, "created_at", datetime.now()),
            "lead_status": getattr(lead, "lead_status", None),
            "kyc": getattr(lead, "kyc", False),
            "segment": None,
            "lead_response_id": getattr(lead, "lead_response_id", None),
            "lead_source_id": getattr(lead, "lead_source_id", None),
            "branch_id": getattr(lead, "branch_id", None),
            "created_by": getattr(lead, "created_by", None),
            "created_by_name": getattr(lead, "created_by_name", None),
            "aadhar_front_pic": getattr(lead, "aadhar_front_pic", None),
            "aadhar_back_pic": getattr(lead, "aadhar_back_pic", None),
            "pan_pic": getattr(lead, "pan_pic", None),
            "kyc_id": getattr(lead, "kyc_id", None),
            "is_old_lead": getattr(lead, "is_old_lead", False),
            "call_back_date": getattr(lead, "call_back_date", None),
        }

# ----------------- SEARCH with visibility + masked “activate” -----------------
@router.get("/search/")
def search_leads(
    q: str,
    search_type: str = "all",  # all, name, mobile, email, pan, aadhaar
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """
    Visibility rules:
      - SUPERADMIN: no restriction
      - BRANCH_MANAGER: restricted to their branch
      - Others: restricted to (self + all subordinates) assignments
        (matches either Lead.assigned_to_user OR crm_lead_assignments.user_id)

    Also returns a masked list `activate_leads` for records that match the search
    but are NOT visible to the caller (e.g., phone as 736*******, email as raj********@gmail.com).
    """
    try:
        if not q or len(q.strip()) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Search query must be at least 2 characters long",
            )

        # ---------- Build the text filter once ----------
        term = f"%{q.strip()}%"
        def _text_filter():
            if search_type == "name":
                return or_(
                    Lead.full_name.ilike(term),
                    Lead.father_name.ilike(term),
                    Lead.director_name.ilike(term),
                )
            elif search_type == "mobile":
                return or_(Lead.mobile.ilike(term), Lead.alternate_mobile.ilike(term))
            elif search_type == "email":
                return Lead.email.ilike(term)
            elif search_type == "pan":
                return Lead.pan.ilike(term)
            elif search_type == "aadhaar":
                return Lead.aadhaar.ilike(term)
            else:  # "all"
                return or_(
                    Lead.full_name.ilike(term),
                    Lead.father_name.ilike(term),
                    Lead.director_name.ilike(term),
                    Lead.mobile.ilike(term),
                    Lead.alternate_mobile.ilike(term),
                    Lead.email.ilike(term),
                    Lead.pan.ilike(term),
                    Lead.aadhaar.ilike(term),
                    Lead.city.ilike(term),
                    Lead.state.ilike(term),
                )

        # ---------- VISIBLE QUERY (with role visibility) ----------
        query = db.query(Lead).filter(
            Lead.is_delete.is_(False),
            _text_filter(),
        )

        role = _role(current_user)

        if role == "SUPERADMIN":
            pass  # no extra filters
        elif role == "BRANCH_MANAGER":
            b_id = _branch_id_for_manager(current_user)
            if b_id is None:
                query = query.filter(literal(False))
            else:
                query = query.filter(Lead.branch_id == b_id)
        else:
            subs = get_subordinate_ids(db, current_user.employee_code)
            allowed = [current_user.employee_code] + (subs or [])
            query = query.filter(
                or_(
                    Lead.assigned_to_user.in_(allowed),
                    _exists_assignment_for_allowed(allowed),
                )
            )

        visible_rows = query.order_by(Lead.created_at.desc()).limit(50).all()

        visible_ids = {ld.id for ld in visible_rows}

        # ---------- MASKED (ACTIVATE) QUERY (no visibility restriction) ----------
        # Find additional matches the user is NOT allowed to see.
        masked_query = (
            db.query(Lead)
            .filter(
                Lead.is_delete.is_(False),
                _text_filter(),
                not_(Lead.id.in_(visible_ids)) if visible_ids else literal(True),
            )
            .order_by(Lead.created_at.desc())
            .limit(50)
        )
        masked_rows = masked_query.all()

        # ---------- Build responses ----------
        # Visible (full) details using your existing transformer
        result: List[LeadOut] = []
        for lead in visible_rows:
            try:
                lead_dict = safe_convert_lead_to_dict(lead)
                result.append(LeadOut(**lead_dict))
            except Exception:
                continue

        # Masked list (minimal, non-sensitive — intended for “Activate” tab)
        activate_leads = []
        for ld in masked_rows:
            try:
                activate_leads.append({
                    # Do NOT include id or other sensitive fields
                    "full_name": mask_name(ld.full_name),
                    "mobile": mask_phone(ld.mobile) or mask_phone(ld.alternate_mobile),
                    "email": mask_email(ld.email),
                    # Small non-sensitive hints (optional):
                    "city": (ld.city or None),
                    "state": (ld.state or None),
                    "created_at": ld.created_at,
                    "is_masked": True,
                })
            except Exception:
                continue

        return {
            "search_query": q,
            "search_type": search_type,
            "total_results": len(result),
            "leads": result,                 # visible
            "total_activate": len(activate_leads),
            "activate_leads": activate_leads # masked, for “Activate” tab
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error searching leads: {str(e)}",
        )

