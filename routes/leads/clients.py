# routes/clients/clients.py

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, desc, func, exists
from typing import List, Optional, Literal
from datetime import datetime

from db.connection import get_db
from db.models import Lead, Payment, UserDetails
from routes.auth.auth_dependency import get_current_user
from pydantic import BaseModel
# ⬇️ use the recursive CTE helpers (put them in services/user_tree.py as in my previous message)
from utils.user_tree import get_subordinate_ids, get_subordinate_users

router = APIRouter(prefix="/clients", tags=["Clients"])

# ---------------------------
# Pydantic Models for Response
# ---------------------------

class ClientPaymentInfo(BaseModel):
    payment_id: int
    order_id: Optional[str]
    service: Optional[List[str]]
    paid_amount: float
    status: Optional[str]
    mode: str
    plan: Optional[list]
    created_at: datetime
    duration_day: Optional[int]
    call: Optional[int]

class AssignedEmployeeInfo(BaseModel):
    employee_code: str
    name: str
    role_id: str
    phone_number: Optional[str]
    email: Optional[str]

class ClientResponse(BaseModel):
    # Lead Information
    lead_id: int
    full_name: Optional[str]
    email: Optional[str]
    mobile: Optional[str]
    city: Optional[str]
    state: Optional[str]
    occupation: Optional[str]
    segment: Optional[str]
    lead_status: Optional[str]
    created_at: datetime

    # Payment Information
    total_payments: int
    total_amount_paid: float
    latest_payment: Optional[ClientPaymentInfo]
    all_payments: List[ClientPaymentInfo]

    # Employee Assignment Information
    assigned_employee: Optional[AssignedEmployeeInfo]
    branch_name: Optional[str]

    # Client Status
    is_active_client: bool
    kyc_status: bool

class TeamMember(BaseModel):
    employee_code: str
    name: str
    role_id: str

class FiltersMeta(BaseModel):
    view: Literal["self", "other", "all"]
    available_views: List[str]
    available_team_members: List[TeamMember] = []
    selected_team_member: Optional[str] = None

class ClientListResponse(BaseModel):
    clients: List[ClientResponse]
    total_count: int
    page: int
    limit: int
    total_pages: int
    filters: Optional[FiltersMeta] = None

# ---------------------------
# Helper Functions
# ---------------------------

def get_client_query_base(db: Session):
    """
    Base query: active clients only, no deletions.
    """
    return (
        db.query(Lead)
        .filter(
            and_(
                Lead.is_delete == False,
                Lead.is_client == True
            )
        )
        .distinct()
    )

def _paid_statuses():
    return {"PAID", "SUCCESS", "SUCCESSFUL", "COMPLETED"}

def _is_paid_status(status: Optional[str]) -> bool:
    return (status or "").upper() in _paid_statuses()

def format_client_response(lead: Lead, db: Session) -> ClientResponse:
    payments = (
        db.query(Payment)
        .filter(
            Payment.lead_id == lead.id,
            func.upper(Payment.status).in_(list(_paid_statuses()))
        )
        .order_by(desc(Payment.created_at))
        .all()
    )

    payment_info = [
        ClientPaymentInfo(
            payment_id=p.id,
            order_id=p.order_id,
            service=p.Service if p.Service else [],
            paid_amount=p.paid_amount,
            status=p.status,
            mode=p.mode,
            plan=p.plan if p.plan else [],
            created_at=p.created_at,
            duration_day=p.duration_day,
            call=p.call,
        )
        for p in payments
    ]

    assigned_employee = None
    if lead.assigned_user:
        u = lead.assigned_user
        assigned_employee = AssignedEmployeeInfo(
            employee_code=u.employee_code,
            name=u.name,
            role_id=str(u.role_id),
            phone_number=u.phone_number,
            email=u.email,
        )

    branch_name = lead.branch.name if lead.branch else None

    return ClientResponse(
        lead_id=lead.id,
        full_name=lead.full_name,
        email=lead.email,
        mobile=lead.mobile,
        city=lead.city,
        state=lead.state,
        occupation=lead.occupation,
        segment=lead.segment,
        lead_status=lead.lead_status,
        created_at=lead.created_at,
        total_payments=len(payments),
        total_amount_paid=sum(p.paid_amount for p in payments),
        latest_payment=payment_info[0] if payment_info else None,
        all_payments=payment_info,
        assigned_employee=assigned_employee,
        branch_name=branch_name,
        is_active_client=any(_is_paid_status(p.status) for p in payments) or bool(lead.is_client),
        kyc_status=bool(lead.kyc),
    )

# ---------------------------
# API Endpoints
# ---------------------------

@router.get("/", response_model=ClientListResponse)
async def get_clients(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by name, email, or mobile"),
    employee_code: Optional[str] = Query(None, description="Filter by assigned employee (exact employee_code)"),
    branch_id: Optional[int] = Query(None, description="Filter by branch id"),
    status: Optional[str] = Query(None, description="Filter by payment status"),
    # New filters for 'other employees'
    view: Literal["self", "other", "all"] = Query("all", description="Scope for non-managers: self | other | all"),
    team_member: Optional[str] = Query(None, description="When view='other', restrict to this subordinate employee_code"),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Role visibility:
      - SUPERADMIN: all clients.
      - BRANCH_MANAGER: only their branch (managed branch if any, else own branch_id).
      - Others: self + subordinates (controlled by `view` and `team_member`).
    """

    query = get_client_query_base(db)

    # -------- Role-scoped visibility --------
    role = (current_user.role_name or "").upper()

    filters_meta: Optional[FiltersMeta] = None
    team_codes: List[str] = []
    team_users: List[UserDetails] = []

    if role == "SUPERADMIN":
        # full access
        pass

    elif role == "BRANCH_MANAGER":
        branch_id_for_filter = None
        if current_user.manages_branch:
            branch_id_for_filter = current_user.manages_branch.id
        elif current_user.branch_id:
            branch_id_for_filter = current_user.branch_id

        if branch_id_for_filter:
            query = query.filter(Lead.branch_id == branch_id_for_filter)
        else:
            # no branch → empty set
            query = query.filter(Lead.id == -1)

    else:
        # Other employees → build team (recursive)
        team_codes = get_subordinate_ids(db, current_user.employee_code, include_inactive=False)
        team_users = get_subordinate_users(db, current_user.employee_code, include_inactive=False)

        # Apply view filter
        if view == "self":
            query = query.filter(Lead.assigned_to_user == current_user.employee_code)
        elif view == "other":
            if not team_codes:
                query = query.filter(Lead.id == -1)  # no subordinates
            else:
                if team_member:
                    # restrict to a selected subordinate (if it's actually under me)
                    if team_member in team_codes:
                        query = query.filter(Lead.assigned_to_user == team_member)
                    else:
                        query = query.filter(Lead.id == -1)
                else:
                    query = query.filter(Lead.assigned_to_user.in_(team_codes))
        else:  # "all"
            if team_codes:
                query = query.filter(
                    or_(
                        Lead.assigned_to_user == current_user.employee_code,
                        Lead.assigned_to_user.in_(team_codes),
                    )
                )
            else:
                query = query.filter(Lead.assigned_to_user == current_user.employee_code)

        # Prepare filters metadata for UI (list of subordinate users)
        filters_meta = FiltersMeta(
            view=view,
            available_views=["self", "other", "all"],
            available_team_members=[
                TeamMember(
                    employee_code=u.employee_code,
                    name=u.name,
                    role_id=str(u.role_id),
                )
                for u in team_users
            ],
            selected_team_member=team_member if view == "other" else None,
        )

    # -------- Additional filters --------
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Lead.full_name.ilike(search_term),
                Lead.email.ilike(search_term),
                Lead.mobile.ilike(search_term),
            )
        )

    if employee_code:
        query = query.filter(Lead.assigned_to_user == employee_code)

    if branch_id:
        query = query.filter(Lead.branch_id == branch_id)

    if status:
        query = query.filter(
            exists().where(
                and_(
                    Payment.lead_id == Lead.id,
                    func.upper(Payment.status) == "PAID",
                )
            )
        )

    # Count BEFORE pagination
    total_count = query.count()

    # Pagination + eager loads
    offset = (page - 1) * limit
    clients = (
        query.options(
            joinedload(Lead.branch),
            joinedload(Lead.payments),
            joinedload(Lead.assigned_user),
        )
        .order_by(desc(Lead.created_at))
        .offset(offset)
        .limit(limit)
        .all()
    )

    client_responses = [format_client_response(client, db) for client in clients]

    return ClientListResponse(
        clients=client_responses,
        total_count=total_count,
        page=page,
        limit=limit,
        total_pages=(total_count + limit - 1) // limit,
        filters=filters_meta,
    )

@router.get("/my/clients", response_model=ClientListResponse)
async def get_my_clients(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Clients directly assigned to the current user (via Lead.assigned_to_user).
    """
    query = (
        db.query(Lead)
        .filter(
            and_(
                Lead.is_delete == False,
                Lead.is_client == True,
                Lead.assigned_to_user == current_user.employee_code,
            )
        )
    )

    total_count = query.count()
    offset = (page - 1) * limit
    clients = (
        query.options(
            joinedload(Lead.branch),
            joinedload(Lead.payments),
            joinedload(Lead.assigned_user),
        )
        .order_by(desc(Lead.created_at))
        .offset(offset)
        .limit(limit)
        .all()
    )

    client_responses = [format_client_response(client, db) for client in clients]

    return ClientListResponse(
        clients=client_responses,
        total_count=total_count,
        page=page,
        limit=limit,
        total_pages=(total_count + limit - 1) // limit,
        filters=FiltersMeta(
            view="self",
            available_views=["self"],
            available_team_members=[],
            selected_team_member=None,
        ),
    )

