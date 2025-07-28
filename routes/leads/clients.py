# routes/clients/clients.py

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, desc, func
from typing import List, Optional
from datetime import datetime, date

from db.connection import get_db
from db.models import (
    Lead, Payment, UserDetails, UserRoleEnum, LeadAssignment, BranchDetails
)
from routes.auth.auth_dependency import get_current_user
from pydantic import BaseModel

router = APIRouter(prefix="/clients", tags=["Clients"])

# Pydantic Models for Response
class ClientPaymentInfo(BaseModel):
    payment_id: int
    order_id: Optional[str]
    service: Optional[str]
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
    role: str
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

class ClientListResponse(BaseModel):
    clients: List[ClientResponse]
    total_count: int
    page: int
    limit: int
    total_pages: int

# Helper Functions
def get_client_query_base(db: Session):
    """Base query to get leads that have made payments (clients)"""
    return db.query(Lead).join(Payment, Lead.id == Payment.lead_id).filter(
        and_(
            Lead.is_delete == False,
            Payment.paid_amount > 0,
            Payment.status == "PAID"
        )
    ).distinct()

def can_view_client(current_user: UserDetails, client_lead: Lead, db: Session) -> bool:
    """Check if current user can view this client"""
    
    # SUPERADMIN and BRANCH_MANAGER can see all clients
    if current_user.role in [UserRoleEnum.SUPERADMIN, UserRoleEnum.BRANCH_MANAGER]:
        return True
    
    # Check if client is assigned to current user
    assignment = db.query(LeadAssignment).filter(
        and_(
            LeadAssignment.lead_id == client_lead.id,
            LeadAssignment.user_id == current_user.employee_code
        )
    ).first()
    
    if assignment:
        return True
    
    # SALES_MANAGER can see clients of their team members
    if current_user.role == UserRoleEnum.SALES_MANAGER:
        team_assignments = db.query(LeadAssignment).join(
            UserDetails, LeadAssignment.user_id == UserDetails.employee_code
        ).filter(
            and_(
                LeadAssignment.lead_id == client_lead.id,
                UserDetails.sales_manager_id == current_user.employee_code
            )
        ).first()
        
        if team_assignments:
            return True
    
    # TL can see clients of their team members
    if current_user.role == UserRoleEnum.TL:
        team_assignments = db.query(LeadAssignment).join(
            UserDetails, LeadAssignment.user_id == UserDetails.employee_code
        ).filter(
            and_(
                LeadAssignment.lead_id == client_lead.id,
                UserDetails.tl_id == current_user.employee_code
            )
        ).first()
        
        if team_assignments:
            return True
    
    return False

def format_client_response(lead: Lead, db: Session) -> ClientResponse:
    """Format lead data into client response"""
    
    # Get all payments for this client
    payments = db.query(Payment).filter(
        Payment.lead_id == lead.id
    ).order_by(desc(Payment.created_at)).all()
    
    # Format payment information
    payment_info = []
    for payment in payments:
        payment_info.append(ClientPaymentInfo(
            payment_id=payment.id,
            order_id=payment.order_id,
            service=payment.Service,
            paid_amount=payment.paid_amount,
            status=payment.status,
            mode=payment.mode,
            plan=payment.plan if payment.plan else [],
            created_at=payment.created_at,
            duration_day=payment.duration_day,
            call=payment.call
        ))
    
    # Get assigned employee information
    assignment = db.query(LeadAssignment).filter(
        LeadAssignment.lead_id == lead.id
    ).first()
    
    assigned_employee = None
    if assignment:
        employee = db.query(UserDetails).filter(
            UserDetails.employee_code == assignment.user_id
        ).first()
        
        if employee:
            assigned_employee = AssignedEmployeeInfo(
                employee_code=employee.employee_code,
                name=employee.name,
                role=employee.role.value,
                phone_number=employee.phone_number,
                email=employee.email
            )
    
    # Get branch information
    branch_name = None
    if lead.branch:
        branch_name = lead.branch.name
    
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
        is_active_client=any(p.status == "success" for p in payments),
        kyc_status=lead.kyc if lead.kyc else False
    )

# API Endpoints

@router.get("/", response_model=ClientListResponse)
async def get_clients(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by name, email, or mobile"),
    employee_code: Optional[str] = Query(None, description="Filter by assigned employee"),
    branch_id: Optional[int] = Query(None, description="Filter by branch"),
    status: Optional[str] = Query(None, description="Filter by payment status"),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get list of clients (leads who have made payments)
    
    - **Employees**: Can see only their assigned clients
    - **TL/Sales Manager**: Can see their team's clients
    - **Branch Manager**: Can see all clients in their branch
    - **Admin**: Can see all clients
    """
    
    # Check permission
    if not current_user.permission or not current_user.permission.view_client:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to view clients"
        )
    
    # Base query
    query = get_client_query_base(db)
    
    # Apply role-based filtering
    if current_user.role == UserRoleEnum.SUPERADMIN:
        # Admin can see all clients
        pass
    elif current_user.role == UserRoleEnum.BRANCH_MANAGER:
        # Branch manager sees clients in their branch
        if current_user.manages_branch:
            query = query.filter(Lead.branch_id == current_user.manages_branch.id)
        else:
            # If no branch assigned, see no clients
            query = query.filter(Lead.id == -1)
    elif current_user.role == UserRoleEnum.SALES_MANAGER:
        # Sales manager sees clients of their team
        team_user_codes = db.query(UserDetails.employee_code).filter(
            UserDetails.sales_manager_id == current_user.employee_code
        ).subquery()
        
        query = query.join(LeadAssignment, Lead.id == LeadAssignment.lead_id).filter(
            LeadAssignment.user_id.in_(team_user_codes)
        )
    elif current_user.role == UserRoleEnum.TL:
        # TL sees clients of their team
        team_user_codes = db.query(UserDetails.employee_code).filter(
            UserDetails.tl_id == current_user.employee_code
        ).subquery()
        
        query = query.join(LeadAssignment, Lead.id == LeadAssignment.lead_id).filter(
            LeadAssignment.user_id.in_(team_user_codes)
        )
    else:
        # Regular employees see only their assigned clients
        query = query.join(LeadAssignment, Lead.id == LeadAssignment.lead_id).filter(
            LeadAssignment.user_id == current_user.employee_code
        )
    
    # Apply filters
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Lead.full_name.ilike(search_term),
                Lead.email.ilike(search_term),
                Lead.mobile.ilike(search_term)
            )
        )
    
    if employee_code:
        query = query.join(LeadAssignment, Lead.id == LeadAssignment.lead_id).filter(
            LeadAssignment.user_id == employee_code
        )
    
    if branch_id:
        query = query.filter(Lead.branch_id == branch_id)
    
    if status:
        query = query.join(Payment, Lead.id == Payment.lead_id).filter(
            Payment.status == status
        )
    
    # Get total count
    total_count = query.count()
    
    # Apply pagination
    offset = (page - 1) * limit
    clients = query.options(
        joinedload(Lead.branch),
        joinedload(Lead.payments),
        joinedload(Lead.assignment)
    ).offset(offset).limit(limit).all()
    
    # Format response
    client_responses = []
    for client in clients:
        if can_view_client(current_user, client, db):
            client_responses.append(format_client_response(client, db))
    
    return ClientListResponse(
        clients=client_responses,
        total_count=total_count,
        page=page,
        limit=limit,
        total_pages=(total_count + limit - 1) // limit
    )

@router.get("/{client_id}", response_model=ClientResponse)
async def get_client_details(
    client_id: int,
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific client
    """
    
    # Check permission
    if not current_user.permission or not current_user.permission.view_client:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to view clients"
        )
    
    # Get client (lead with payments)
    client = db.query(Lead).filter(
        and_(
            Lead.id == client_id,
            Lead.is_delete == False
        )
    ).options(
        joinedload(Lead.branch),
        joinedload(Lead.payments),
        joinedload(Lead.assignment)
    ).first()
    
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )
    
    # Check if this lead has made payments (is a client)
    has_payments = db.query(Payment).filter(
        and_(
            Payment.lead_id == client_id,
            Payment.paid_amount > 0
        )
    ).first()
    
    if not has_payments:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This lead is not a client (no payments found)"
        )
    
    # Check if user can view this client
    if not can_view_client(current_user, client, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to view this client"
        )
    
    return format_client_response(client, db)

@router.get("/my/clients", response_model=ClientListResponse)
async def get_my_clients(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get clients assigned to current user only
    """
    
    # Check permission
    if not current_user.permission or not current_user.permission.view_client:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to view clients"
        )
    
    # Get clients assigned to current user
    query = get_client_query_base(db).join(
        LeadAssignment, Lead.id == LeadAssignment.lead_id
    ).filter(
        LeadAssignment.user_id == current_user.employee_code
    )
    
    total_count = query.count()
    
    # Apply pagination
    offset = (page - 1) * limit
    clients = query.options(
        joinedload(Lead.branch),
        joinedload(Lead.payments),
        joinedload(Lead.assignment)
    ).offset(offset).limit(limit).all()
    
    # Format response
    client_responses = [format_client_response(client, db) for client in clients]
    
    return ClientListResponse(
        clients=client_responses,
        total_count=total_count,
        page=page,
        limit=limit,
        total_pages=(total_count + limit - 1) // limit
    )

@router.get("/stats/summary")
async def get_client_stats(
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get client statistics based on user role
    """
    
    # Check permission
    if not current_user.permission or not current_user.permission.view_client:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to view client statistics"
        )
    
    # Base query for clients
    base_query = get_client_query_base(db)
    
    # Apply role-based filtering
    if current_user.role == UserRoleEnum.SUPERADMIN:
        # Admin sees all
        pass
    elif current_user.role == UserRoleEnum.BRANCH_MANAGER:
        if current_user.manages_branch:
            base_query = base_query.filter(Lead.branch_id == current_user.manages_branch.id)
    elif current_user.role == UserRoleEnum.SALES_MANAGER:
        team_user_codes = db.query(UserDetails.employee_code).filter(
            UserDetails.sales_manager_id == current_user.employee_code
        ).subquery()
        base_query = base_query.join(LeadAssignment, Lead.id == LeadAssignment.lead_id).filter(
            LeadAssignment.user_id.in_(team_user_codes)
        )
    elif current_user.role == UserRoleEnum.TL:
        team_user_codes = db.query(UserDetails.employee_code).filter(
            UserDetails.tl_id == current_user.employee_code
        ).subquery()
        base_query = base_query.join(LeadAssignment, Lead.id == LeadAssignment.lead_id).filter(
            LeadAssignment.user_id.in_(team_user_codes)
        )
    else:
        base_query = base_query.join(LeadAssignment, Lead.id == LeadAssignment.lead_id).filter(
            LeadAssignment.user_id == current_user.employee_code
        )
    
    # Get statistics
    total_clients = base_query.count()
    
    # Get total revenue from these clients
    client_ids = base_query.with_entities(Lead.id).subquery()
    total_revenue = db.query(func.sum(Payment.paid_amount)).filter(
        Payment.lead_id.in_(client_ids)
    ).scalar() or 0
    
    # Get active clients (with successful payments)
    active_clients = base_query.join(Payment, Lead.id == Payment.lead_id).filter(
        Payment.status == "PAID"
    ).distinct().count()
    
    # Get KYC completed clients
    kyc_completed = base_query.filter(Lead.kyc == True).count()
    
    return {
        "total_clients": total_clients,
        "active_clients": active_clients,
        "total_revenue": float(total_revenue),
        "kyc_completed": kyc_completed,
        "kyc_pending": total_clients - kyc_completed
    }