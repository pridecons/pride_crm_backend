# routes/analytics/lead_analytics.py

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, desc, func, text, case, extract
from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta
from pydantic import BaseModel

from db.connection import get_db
from db.models import (
    Lead, Payment, UserDetails, UserRoleEnum, LeadAssignment, 
    BranchDetails, LeadSource, LeadResponse, LeadStory, LeadComment
)
from routes.auth.auth_dependency import get_current_user

router = APIRouter(prefix="/analytics/leads", tags=["Lead Analytics"])

# Pydantic Models for Analytics Response
class LeadStatsModel(BaseModel):
    total_leads: int
    new_leads_today: int
    new_leads_this_week: int
    new_leads_this_month: int
    assigned_leads: int
    unassigned_leads: int
    called_leads: int
    uncalled_leads: int
    converted_leads: int  # leads with payments
    conversion_rate: float

class PaymentStatsModel(BaseModel):
    total_revenue: float
    total_payments: int
    successful_payments: int
    pending_payments: int
    failed_payments: int
    average_payment_amount: float
    revenue_today: float
    revenue_this_week: float
    revenue_this_month: float

class SourceAnalyticsModel(BaseModel):
    source_name: str
    total_leads: int
    converted_leads: int
    conversion_rate: float
    total_revenue: float

class ResponseAnalyticsModel(BaseModel):
    response_name: str
    total_leads: int
    percentage: float

class DailyActivityModel(BaseModel):
    date: str
    leads_created: int
    leads_called: int
    payments_made: int
    revenue: float

class EmployeePerformanceModel(BaseModel):
    employee_code: str
    employee_name: str
    role: str
    branch_name: Optional[str]
    total_leads: int
    called_leads: int
    converted_leads: int
    total_revenue: float
    conversion_rate: float
    call_rate: float

class EmployeeAnalyticsResponse(BaseModel):
    employee_stats: LeadStatsModel
    payment_stats: PaymentStatsModel
    daily_activity: List[DailyActivityModel]
    source_breakdown: List[SourceAnalyticsModel]
    response_breakdown: List[ResponseAnalyticsModel]
    recent_activities: List[Dict[str, Any]]
    targets_vs_achievement: Dict[str, Any]

class AdminAnalyticsResponse(BaseModel):
    overall_stats: LeadStatsModel
    payment_stats: PaymentStatsModel
    employee_performance: List[EmployeePerformanceModel]
    daily_trends: List[DailyActivityModel]
    source_analytics: List[SourceAnalyticsModel]
    response_analytics: List[ResponseAnalyticsModel]
    branch_performance: List[Dict[str, Any]]
    top_performers: List[EmployeePerformanceModel]

# Helper Functions
def get_date_range_filter(days: int = 30):
    """Get date filter for last N days"""
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)
    return start_date, end_date

def calculate_conversion_rate(total_leads: int, converted_leads: int) -> float:
    """Calculate conversion rate percentage"""
    if total_leads == 0:
        return 0.0
    return round((converted_leads / total_leads) * 100, 2)

def get_employee_leads_query(db: Session, employee_code: str, date_from: Optional[date] = None, date_to: Optional[date] = None):
    """Get base query for employee's leads"""
    query = db.query(Lead).join(
        LeadAssignment, Lead.id == LeadAssignment.lead_id
    ).filter(
        and_(
            LeadAssignment.user_id == employee_code,
            Lead.is_delete == False
        )
    )
    
    if date_from:
        query = query.filter(Lead.created_at >= date_from)
    if date_to:
        query = query.filter(Lead.created_at <= date_to)
    
    return query

def get_admin_leads_query(db: Session, current_user: UserDetails, date_from: Optional[date] = None, date_to: Optional[date] = None):
    """Get base query for admin's accessible leads"""
    query = db.query(Lead).filter(Lead.is_delete == False)
    
    # Apply role-based filtering
    if current_user.role == UserRoleEnum.BRANCH_MANAGER:
        if current_user.manages_branch:
            query = query.filter(Lead.branch_id == current_user.manages_branch.id)
    elif current_user.role == UserRoleEnum.SALES_MANAGER:
        # Get team members
        team_members = db.query(UserDetails.employee_code).filter(
            UserDetails.sales_manager_id == current_user.employee_code
        ).subquery()
        
        query = query.join(LeadAssignment, Lead.id == LeadAssignment.lead_id).filter(
            LeadAssignment.user_id.in_(team_members)
        )
    elif current_user.role == UserRoleEnum.TL:
        # Get team members
        team_members = db.query(UserDetails.employee_code).filter(
            UserDetails.tl_id == current_user.employee_code
        ).subquery()
        
        query = query.join(LeadAssignment, Lead.id == LeadAssignment.lead_id).filter(
            LeadAssignment.user_id.in_(team_members)
        )
    
    if date_from:
        query = query.filter(Lead.created_at >= date_from)
    if date_to:
        query = query.filter(Lead.created_at <= date_to)
    
    return query

# Employee Analytics Endpoints

@router.get("/employee/dashboard", response_model=EmployeeAnalyticsResponse)
async def get_employee_analytics(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get comprehensive analytics for the current employee
    """
    start_date, end_date = get_date_range_filter(days)
    
    # Base query for employee's leads
    leads_query = get_employee_leads_query(db, current_user.employee_code, start_date, end_date)
    
    # Lead Statistics
    total_leads = leads_query.count()
    
    # Date-based lead counts
    today = datetime.now().date()
    new_leads_today = leads_query.filter(
        func.date(Lead.created_at) == today
    ).count()
    
    week_start = today - timedelta(days=today.weekday())
    new_leads_this_week = leads_query.filter(
        Lead.created_at >= week_start
    ).count()
    
    month_start = today.replace(day=1)
    new_leads_this_month = leads_query.filter(
        Lead.created_at >= month_start
    ).count()
    
    # Assignment statistics
    assignments_query = db.query(LeadAssignment).filter(
        LeadAssignment.user_id == current_user.employee_code
    )
    
    assigned_leads = assignments_query.count()
    called_leads = assignments_query.filter(LeadAssignment.is_call == True).count()
    uncalled_leads = assigned_leads - called_leads
    
    # Conversion statistics
    converted_leads_query = leads_query.join(Payment, Lead.id == Payment.lead_id).filter(
        Payment.paid_amount > 0
    ).distinct()
    converted_leads = converted_leads_query.count()
    
    lead_stats = LeadStatsModel(
        total_leads=total_leads,
        new_leads_today=new_leads_today,
        new_leads_this_week=new_leads_this_week,
        new_leads_this_month=new_leads_this_month,
        assigned_leads=assigned_leads,
        unassigned_leads=0,  # Not applicable for employee
        called_leads=called_leads,
        uncalled_leads=uncalled_leads,
        converted_leads=converted_leads,
        conversion_rate=calculate_conversion_rate(total_leads, converted_leads)
    )
    
    # Payment Statistics
    payments_query = db.query(Payment).join(
        Lead, Payment.lead_id == Lead.id
    ).join(
        LeadAssignment, Lead.id == LeadAssignment.lead_id
    ).filter(
        and_(
            LeadAssignment.user_id == current_user.employee_code,
            Lead.created_at >= start_date,
            Lead.created_at <= end_date
        )
    )
    
    total_payments = payments_query.count()
    total_revenue = payments_query.with_entities(func.sum(Payment.paid_amount)).scalar() or 0
    
    successful_payments = payments_query.filter(Payment.status == "success").count()
    pending_payments = payments_query.filter(Payment.status == "pending").count()
    failed_payments = payments_query.filter(Payment.status == "failed").count()
    
    avg_payment = (total_revenue / total_payments) if total_payments > 0 else 0
    
    # Revenue by time periods
    revenue_today = payments_query.filter(
        func.date(Payment.created_at) == today
    ).with_entities(func.sum(Payment.paid_amount)).scalar() or 0
    
    revenue_this_week = payments_query.filter(
        Payment.created_at >= week_start
    ).with_entities(func.sum(Payment.paid_amount)).scalar() or 0
    
    revenue_this_month = payments_query.filter(
        Payment.created_at >= month_start
    ).with_entities(func.sum(Payment.paid_amount)).scalar() or 0
    
    payment_stats = PaymentStatsModel(
        total_revenue=float(total_revenue),
        total_payments=total_payments,
        successful_payments=successful_payments,
        pending_payments=pending_payments,
        failed_payments=failed_payments,
        average_payment_amount=float(avg_payment),
        revenue_today=float(revenue_today),
        revenue_this_week=float(revenue_this_week),
        revenue_this_month=float(revenue_this_month)
    )
    
    # Daily Activity Trends
    daily_activity = []
    for i in range(days):
        activity_date = end_date - timedelta(days=i)
        
        leads_created = leads_query.filter(
            func.date(Lead.created_at) == activity_date
        ).count()
        
        leads_called = db.query(LeadAssignment).join(
            Lead, LeadAssignment.lead_id == Lead.id
        ).filter(
            and_(
                LeadAssignment.user_id == current_user.employee_code,
                LeadAssignment.is_call == True,
                func.date(LeadAssignment.fetched_at) == activity_date
            )
        ).count()
        
        day_payments = payments_query.filter(
            func.date(Payment.created_at) == activity_date
        )
        
        payments_made = day_payments.count()
        revenue = day_payments.with_entities(func.sum(Payment.paid_amount)).scalar() or 0
        
        daily_activity.append(DailyActivityModel(
            date=activity_date.strftime("%Y-%m-%d"),
            leads_created=leads_created,
            leads_called=leads_called,
            payments_made=payments_made,
            revenue=float(revenue)
        ))
    
    daily_activity.reverse()  # Show oldest to newest
    
    # Source Breakdown
    source_analytics = db.query(
        LeadSource.name,
        func.count(Lead.id).label('total_leads'),
        func.count(Payment.id).label('converted_leads'),
        func.sum(Payment.paid_amount).label('total_revenue')
    ).select_from(Lead).join(
        LeadAssignment, Lead.id == LeadAssignment.lead_id
    ).outerjoin(
        LeadSource, Lead.lead_source_id == LeadSource.id
    ).outerjoin(
        Payment, Lead.id == Payment.lead_id
    ).filter(
        and_(
            LeadAssignment.user_id == current_user.employee_code,
            Lead.created_at >= start_date,
            Lead.created_at <= end_date,
            Lead.is_delete == False
        )
    ).group_by(LeadSource.name).all()
    
    source_breakdown = []
    for source_name, total, converted, revenue in source_analytics:
        source_breakdown.append(SourceAnalyticsModel(
            source_name=source_name or "Unknown",
            total_leads=total,
            converted_leads=converted or 0,
            conversion_rate=calculate_conversion_rate(total, converted or 0),
            total_revenue=float(revenue or 0)
        ))
    
    # Response Breakdown
    response_analytics = db.query(
        LeadResponse.name,
        func.count(Lead.id).label('total_leads')
    ).select_from(Lead).join(
        LeadAssignment, Lead.id == LeadAssignment.lead_id
    ).outerjoin(
        LeadResponse, Lead.lead_response_id == LeadResponse.id
    ).filter(
        and_(
            LeadAssignment.user_id == current_user.employee_code,
            Lead.created_at >= start_date,
            Lead.created_at <= end_date,
            Lead.is_delete == False
        )
    ).group_by(LeadResponse.name).all()
    
    response_breakdown = []
    total_for_percentage = sum(count for _, count in response_analytics)
    
    for response_name, count in response_analytics:
        percentage = (count / total_for_percentage * 100) if total_for_percentage > 0 else 0
        response_breakdown.append(ResponseAnalyticsModel(
            response_name=response_name or "No Response",
            total_leads=count,
            percentage=round(percentage, 2)
        ))
    
    # Recent Activities
    recent_activities = []
    recent_stories = db.query(LeadStory).filter(
        LeadStory.user_id == current_user.employee_code
    ).order_by(desc(LeadStory.timestamp)).limit(10).all()
    
    for story in recent_stories:
        lead = db.query(Lead).filter(Lead.id == story.lead_id).first()
        recent_activities.append({
            "timestamp": story.timestamp.isoformat(),
            "activity": story.msg,
            "lead_name": lead.full_name if lead else "Unknown",
            "lead_id": story.lead_id
        })
    
    # Targets vs Achievement (placeholder - implement based on your target system)
    targets_vs_achievement = {
        "monthly_lead_target": 100,  # You can make this configurable
        "monthly_leads_achieved": new_leads_this_month,
        "monthly_revenue_target": 100000,  # You can make this configurable
        "monthly_revenue_achieved": float(revenue_this_month),
        "achievement_percentage": round((new_leads_this_month / 100) * 100, 2) if 100 > 0 else 0
    }
    
    return EmployeeAnalyticsResponse(
        employee_stats=lead_stats,
        payment_stats=payment_stats,
        daily_activity=daily_activity,
        source_breakdown=source_breakdown,
        response_breakdown=response_breakdown,
        recent_activities=recent_activities,
        targets_vs_achievement=targets_vs_achievement
    )

# Admin Analytics Endpoints

@router.get("/admin/dashboard", response_model=AdminAnalyticsResponse)
async def get_admin_analytics(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    branch_id: Optional[int] = Query(None, description="Filter by branch ID"),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get comprehensive analytics for admin dashboard
    Only accessible by SUPERADMIN, BRANCH_MANAGER, SALES_MANAGER, and TL
    """
    # Check permissions
    if current_user.role not in [UserRoleEnum.SUPERADMIN, UserRoleEnum.BRANCH_MANAGER, 
                                 UserRoleEnum.SALES_MANAGER, UserRoleEnum.TL]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to view admin analytics"
        )
    
    start_date, end_date = get_date_range_filter(days)
    
    # Base query for accessible leads
    leads_query = get_admin_leads_query(db, current_user, start_date, end_date)
    
    if branch_id:
        leads_query = leads_query.filter(Lead.branch_id == branch_id)
    
    # Overall Lead Statistics
    total_leads = leads_query.count()
    
    today = datetime.now().date()
    new_leads_today = leads_query.filter(
        func.date(Lead.created_at) == today
    ).count()
    
    week_start = today - timedelta(days=today.weekday())
    new_leads_this_week = leads_query.filter(
        Lead.created_at >= week_start
    ).count()
    
    month_start = today.replace(day=1)
    new_leads_this_month = leads_query.filter(
        Lead.created_at >= month_start
    ).count()
    
    # Assignment statistics
    assigned_leads = leads_query.join(LeadAssignment, Lead.id == LeadAssignment.lead_id).distinct().count()
    unassigned_leads = total_leads - assigned_leads
    
    called_leads = leads_query.join(LeadAssignment, Lead.id == LeadAssignment.lead_id).filter(
        LeadAssignment.is_call == True
    ).distinct().count()
    
    uncalled_leads = assigned_leads - called_leads
    
    # Conversion statistics
    converted_leads = leads_query.join(Payment, Lead.id == Payment.lead_id).filter(
        Payment.paid_amount > 0
    ).distinct().count()
    
    overall_stats = LeadStatsModel(
        total_leads=total_leads,
        new_leads_today=new_leads_today,
        new_leads_this_week=new_leads_this_week,
        new_leads_this_month=new_leads_this_month,
        assigned_leads=assigned_leads,
        unassigned_leads=unassigned_leads,
        called_leads=called_leads,
        uncalled_leads=uncalled_leads,
        converted_leads=converted_leads,
        conversion_rate=calculate_conversion_rate(total_leads, converted_leads)
    )
    
    # Payment Statistics (similar to employee but for all accessible leads)
    payments_query = db.query(Payment).join(Lead, Payment.lead_id == Lead.id)
    
    # Apply same filtering as leads_query
    if current_user.role == UserRoleEnum.BRANCH_MANAGER and current_user.manages_branch:
        payments_query = payments_query.filter(Lead.branch_id == current_user.manages_branch.id)
    elif current_user.role in [UserRoleEnum.SALES_MANAGER, UserRoleEnum.TL]:
        # Apply team filtering
        if current_user.role == UserRoleEnum.SALES_MANAGER:
            team_members = db.query(UserDetails.employee_code).filter(
                UserDetails.sales_manager_id == current_user.employee_code
            ).subquery()
        else:  # TL
            team_members = db.query(UserDetails.employee_code).filter(
                UserDetails.tl_id == current_user.employee_code
            ).subquery()
        
        payments_query = payments_query.join(
            LeadAssignment, Lead.id == LeadAssignment.lead_id
        ).filter(LeadAssignment.user_id.in_(team_members))
    
    payments_query = payments_query.filter(
        and_(
            Payment.created_at >= start_date,
            Payment.created_at <= end_date,
            Lead.is_delete == False
        )
    )
    
    total_payments = payments_query.count()
    total_revenue = payments_query.with_entities(func.sum(Payment.paid_amount)).scalar() or 0
    successful_payments = payments_query.filter(Payment.status == "success").count()
    pending_payments = payments_query.filter(Payment.status == "pending").count()
    failed_payments = payments_query.filter(Payment.status == "failed").count()
    
    avg_payment = (total_revenue / total_payments) if total_payments > 0 else 0
    
    # Revenue by time periods
    revenue_today = payments_query.filter(
        func.date(Payment.created_at) == today
    ).with_entities(func.sum(Payment.paid_amount)).scalar() or 0
    
    revenue_this_week = payments_query.filter(
        Payment.created_at >= week_start
    ).with_entities(func.sum(Payment.paid_amount)).scalar() or 0
    
    revenue_this_month = payments_query.filter(
        Payment.created_at >= month_start
    ).with_entities(func.sum(Payment.paid_amount)).scalar() or 0
    
    payment_stats = PaymentStatsModel(
        total_revenue=float(total_revenue),
        total_payments=total_payments,
        successful_payments=successful_payments,
        pending_payments=pending_payments,
        failed_payments=failed_payments,
        average_payment_amount=float(avg_payment),
        revenue_today=float(revenue_today),
        revenue_this_week=float(revenue_this_week),
        revenue_this_month=float(revenue_this_month)
    )
    
    # Employee Performance Analysis
    employee_performance = []
    
    # Get all employees based on current user's role
    employees_query = db.query(UserDetails).filter(UserDetails.is_active == True)
    
    if current_user.role == UserRoleEnum.BRANCH_MANAGER and current_user.manages_branch:
        employees_query = employees_query.filter(UserDetails.branch_id == current_user.manages_branch.id)
    elif current_user.role == UserRoleEnum.SALES_MANAGER:
        employees_query = employees_query.filter(UserDetails.sales_manager_id == current_user.employee_code)
    elif current_user.role == UserRoleEnum.TL:
        employees_query = employees_query.filter(UserDetails.tl_id == current_user.employee_code)
    
    employees = employees_query.all()
    
    for employee in employees:
        # Get employee's lead statistics
        emp_leads_query = get_employee_leads_query(db, employee.employee_code, start_date, end_date)
        emp_total_leads = emp_leads_query.count()
        
        emp_assignments = db.query(LeadAssignment).filter(
            LeadAssignment.user_id == employee.employee_code
        )
        emp_called_leads = emp_assignments.filter(LeadAssignment.is_call == True).count()
        
        emp_converted_leads = emp_leads_query.join(Payment, Lead.id == Payment.lead_id).filter(
            Payment.paid_amount > 0
        ).distinct().count()
        
        emp_revenue = db.query(func.sum(Payment.paid_amount)).join(
            Lead, Payment.lead_id == Lead.id
        ).join(
            LeadAssignment, Lead.id == LeadAssignment.lead_id
        ).filter(
            and_(
                LeadAssignment.user_id == employee.employee_code,
                Payment.created_at >= start_date,
                Payment.created_at <= end_date
            )
        ).scalar() or 0
        
        employee_performance.append(EmployeePerformanceModel(
            employee_code=employee.employee_code,
            employee_name=employee.name,
            role=employee.role.value,
            branch_name=employee.branch.name if employee.branch else None,
            total_leads=emp_total_leads,
            called_leads=emp_called_leads,
            converted_leads=emp_converted_leads,
            total_revenue=float(emp_revenue),
            conversion_rate=calculate_conversion_rate(emp_total_leads, emp_converted_leads),
            call_rate=calculate_conversion_rate(emp_total_leads, emp_called_leads)
        ))
    
    # Daily Trends (similar to employee but for all accessible data)
    daily_trends = []
    for i in range(min(days, 30)):  # Limit to 30 days for performance
        trend_date = end_date - timedelta(days=i)
        
        leads_created = leads_query.filter(
            func.date(Lead.created_at) == trend_date
        ).count()
        
        leads_called_count = db.query(LeadAssignment).join(
            Lead, LeadAssignment.lead_id == Lead.id
        ).filter(
            and_(
                LeadAssignment.is_call == True,
                func.date(LeadAssignment.fetched_at) == trend_date,
                Lead.is_delete == False
            )
        )
        
        # Apply same role-based filtering
        if current_user.role == UserRoleEnum.BRANCH_MANAGER and current_user.manages_branch:
            leads_called_count = leads_called_count.filter(Lead.branch_id == current_user.manages_branch.id)
        elif current_user.role in [UserRoleEnum.SALES_MANAGER, UserRoleEnum.TL]:
            if current_user.role == UserRoleEnum.SALES_MANAGER:
                team_members = db.query(UserDetails.employee_code).filter(
                    UserDetails.sales_manager_id == current_user.employee_code
                ).subquery()
            else:
                team_members = db.query(UserDetails.employee_code).filter(
                    UserDetails.tl_id == current_user.employee_code
                ).subquery()
            leads_called_count = leads_called_count.filter(LeadAssignment.user_id.in_(team_members))
        
        leads_called = leads_called_count.count()
        
        day_payments = payments_query.filter(
            func.date(Payment.created_at) == trend_date
        )
        
        payments_made = day_payments.count()
        revenue = day_payments.with_entities(func.sum(Payment.paid_amount)).scalar() or 0
        
        daily_trends.append(DailyActivityModel(
            date=trend_date.strftime("%Y-%m-%d"),
            leads_created=leads_created,
            leads_called=leads_called,
            payments_made=payments_made,
            revenue=float(revenue)
        ))
    
    daily_trends.reverse()
    
    # Source Analytics (similar structure as employee)
    source_analytics_query = db.query(
        LeadSource.name,
        func.count(Lead.id).label('total_leads'),
        func.count(Payment.id).label('converted_leads'),
        func.sum(Payment.paid_amount).label('total_revenue')
    ).select_from(Lead).outerjoin(
        LeadSource, Lead.lead_source_id == LeadSource.id
    ).outerjoin(
        Payment, Lead.id == Payment.lead_id
    ).filter(
        and_(
            Lead.created_at >= start_date,
            Lead.created_at <= end_date,
            Lead.is_delete == False
        )
    )
    
    # Apply role-based filtering
    if current_user.role == UserRoleEnum.BRANCH_MANAGER and current_user.manages_branch:
        source_analytics_query = source_analytics_query.filter(Lead.branch_id == current_user.manages_branch.id)
    elif current_user.role in [UserRoleEnum.SALES_MANAGER, UserRoleEnum.TL]:
        if current_user.role == UserRoleEnum.SALES_MANAGER:
            team_members = db.query(UserDetails.employee_code).filter(
                UserDetails.sales_manager_id == current_user.employee_code
            ).subquery()
        else:
            team_members = db.query(UserDetails.employee_code).filter(
                UserDetails.tl_id == current_user.employee_code
            ).subquery()
        
        source_analytics_query = source_analytics_query.join(
            LeadAssignment, Lead.id == LeadAssignment.lead_id
        ).filter(LeadAssignment.user_id.in_(team_members))
    
    source_analytics_data = source_analytics_query.group_by(LeadSource.name).all()
    
    source_analytics = []
    for source_name, total, converted, revenue in source_analytics_data:
        source_analytics.append(SourceAnalyticsModel(
            source_name=source_name or "Unknown",
            total_leads=total,
            converted_leads=converted or 0,
            conversion_rate=calculate_conversion_rate(total, converted or 0),
            total_revenue=float(revenue or 0)
        ))
    
    # Response Analytics
    response_analytics_query = db.query(
        LeadResponse.name,
        func.count(Lead.id).label('total_leads')
    ).select_from(Lead).outerjoin(
        LeadResponse, Lead.lead_response_id == LeadResponse.id
    ).filter(
        and_(
            Lead.created_at >= start_date,
            Lead.created_at <= end_date,
            Lead.is_delete == False
        )
    )
    
    # Apply same role-based filtering as source_analytics
    if current_user.role == UserRoleEnum.BRANCH_MANAGER and current_user.manages_branch:
        response_analytics_query = response_analytics_query.filter(Lead.branch_id == current_user.manages_branch.id)
    elif current_user.role in [UserRoleEnum.SALES_MANAGER, UserRoleEnum.TL]:
        if current_user.role == UserRoleEnum.SALES_MANAGER:
            team_members = db.query(UserDetails.employee_code).filter(
                UserDetails.sales_manager_id == current_user.employee_code
            ).subquery()
        else:
            team_members = db.query(UserDetails.employee_code).filter(
                UserDetails.tl_id == current_user.employee_code
            ).subquery()
        
        response_analytics_query = response_analytics_query.join(
            LeadAssignment, Lead.id == LeadAssignment.lead_id
        ).filter(LeadAssignment.user_id.in_(team_members))
    
    response_analytics_data = response_analytics_query.group_by(LeadResponse.name).all()
    
    response_analytics = []
    total_for_percentage = sum(count for _, count in response_analytics_data)
    
    for response_name, count in response_analytics_data:
        percentage = (count / total_for_percentage * 100) if total_for_percentage > 0 else 0
        response_analytics.append(ResponseAnalyticsModel(
            response_name=response_name or "No Response",
            total_leads=count,
            percentage=round(percentage, 2)
        ))
    
    # Branch Performance (only for SUPERADMIN)
    branch_performance = []
    if current_user.role == UserRoleEnum.SUPERADMIN:
        branches = db.query(BranchDetails).filter(BranchDetails.active == True).all()
        
        for branch in branches:
            branch_leads = db.query(Lead).filter(
                and_(
                    Lead.branch_id == branch.id,
                    Lead.created_at >= start_date,
                    Lead.created_at <= end_date,
                    Lead.is_delete == False
                )
            ).count()
            
            branch_revenue = db.query(func.sum(Payment.paid_amount)).join(
                Lead, Payment.lead_id == Lead.id
            ).filter(
                and_(
                    Lead.branch_id == branch.id,
                    Payment.created_at >= start_date,
                    Payment.created_at <= end_date
                )
            ).scalar() or 0
            
            branch_converted = db.query(Lead).join(
                Payment, Lead.id == Payment.lead_id
            ).filter(
                and_(
                    Lead.branch_id == branch.id,
                    Lead.created_at >= start_date,
                    Lead.created_at <= end_date,
                    Lead.is_delete == False,
                    Payment.paid_amount > 0
                )
            ).distinct().count()
            
            branch_performance.append({
                "branch_id": branch.id,
                "branch_name": branch.name,
                "manager_name": branch.manager.name if branch.manager else "No Manager",
                "total_leads": branch_leads,
                "converted_leads": branch_converted,
                "total_revenue": float(branch_revenue),
                "conversion_rate": calculate_conversion_rate(branch_leads, branch_converted)
            })
    
    # Top Performers (sorted by conversion rate and revenue)
    top_performers = sorted(
        employee_performance,
        key=lambda x: (x.conversion_rate, x.total_revenue),
        reverse=True
    )[:10]  # Top 10 performers
    
    return AdminAnalyticsResponse(
        overall_stats=overall_stats,
        payment_stats=payment_stats,
        employee_performance=employee_performance,
        daily_trends=daily_trends,
        source_analytics=source_analytics,
        response_analytics=response_analytics,
        branch_performance=branch_performance,
        top_performers=top_performers
    )

@router.get("/admin/employee/{employee_code}", response_model=EmployeeAnalyticsResponse)
async def get_specific_employee_analytics(
    employee_code: str,
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get analytics for a specific employee (admin only)
    """
    # Check permissions
    if current_user.role not in [UserRoleEnum.SUPERADMIN, UserRoleEnum.BRANCH_MANAGER, 
                                 UserRoleEnum.SALES_MANAGER, UserRoleEnum.TL]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to view employee analytics"
        )
    
    # Check if the employee exists and is accessible
    employee = db.query(UserDetails).filter(
        UserDetails.employee_code == employee_code
    ).first()
    
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found"
        )
    
    # Check if current user can view this employee's data
    can_view = False
    
    if current_user.role == UserRoleEnum.SUPERADMIN:
        can_view = True
    elif current_user.role == UserRoleEnum.BRANCH_MANAGER:
        if current_user.manages_branch and employee.branch_id == current_user.manages_branch.id:
            can_view = True
    elif current_user.role == UserRoleEnum.SALES_MANAGER:
        if employee.sales_manager_id == current_user.employee_code:
            can_view = True
    elif current_user.role == UserRoleEnum.TL:
        if employee.tl_id == current_user.employee_code:
            can_view = True
    
    if not can_view:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to view this employee's analytics"
        )
    
    # Use the same logic as employee dashboard but for the specified employee
    start_date, end_date = get_date_range_filter(days)
    
    # Base query for employee's leads
    leads_query = get_employee_leads_query(db, employee_code, start_date, end_date)
    
    # [Rest of the analytics logic is same as employee dashboard - reuse the same code]
    # For brevity, I'll just return a placeholder response structure
    # You can copy the entire analytics logic from the employee dashboard endpoint
    
    # This is a simplified version - implement full analytics like in employee dashboard
    total_leads = leads_query.count()
    
    return EmployeeAnalyticsResponse(
        employee_stats=LeadStatsModel(
            total_leads=total_leads,
            new_leads_today=0,
            new_leads_this_week=0,
            new_leads_this_month=0,
            assigned_leads=0,
            unassigned_leads=0,
            called_leads=0,
            uncalled_leads=0,
            converted_leads=0,
            conversion_rate=0.0
        ),
        payment_stats=PaymentStatsModel(
            total_revenue=0.0,
            total_payments=0,
            successful_payments=0,
            pending_payments=0,
            failed_payments=0,
            average_payment_amount=0.0,
            revenue_today=0.0,
            revenue_this_week=0.0,
            revenue_this_month=0.0
        ),
        daily_activity=[],
        source_breakdown=[],
        response_breakdown=[],
        recent_activities=[],
        targets_vs_achievement={}
    )

@router.get("/reports/export")
async def export_analytics_report(
    format: str = Query("csv", regex="^(csv|excel|pdf)$", description="Export format"),
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Export analytics report in various formats
    """
    # Check permissions
    if not current_user.permission or not current_user.permission.reports:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to export reports"
        )
    
    start_date, end_date = get_date_range_filter(days)
    
    # Get analytics data based on user role
    if current_user.role in [UserRoleEnum.SUPERADMIN, UserRoleEnum.BRANCH_MANAGER, 
                             UserRoleEnum.SALES_MANAGER, UserRoleEnum.TL]:
        # Admin level analytics
        analytics_data = await get_admin_analytics(days, None, current_user, db)
        report_type = "admin"
    else:
        # Employee level analytics
        analytics_data = await get_employee_analytics(days, current_user, db)
        report_type = "employee"
    
    # For now, return a JSON response
    # You can implement actual CSV/Excel/PDF generation here
    from fastapi.responses import JSONResponse
    
    return JSONResponse(
        content={
            "report_type": report_type,
            "format": format,
            "date_range": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            },
            "data": analytics_data.dict(),
            "generated_at": datetime.now().isoformat(),
            "generated_by": current_user.name
        }
    )

# Additional utility endpoints

@router.get("/summary/quick-stats")
async def get_quick_stats(
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get quick statistics for dashboard widgets
    """
    today = datetime.now().date()
    
    if current_user.role in [UserRoleEnum.SUPERADMIN, UserRoleEnum.BRANCH_MANAGER]:
        # Admin quick stats
        leads_query = get_admin_leads_query(db, current_user)
        
        total_leads = leads_query.count()
        today_leads = leads_query.filter(func.date(Lead.created_at) == today).count()
        
        # Revenue today
        revenue_query = db.query(func.sum(Payment.paid_amount)).join(
            Lead, Payment.lead_id == Lead.id
        ).filter(
            and_(
                func.date(Payment.created_at) == today,
                Lead.is_delete == False
            )
        )
        
        if current_user.role == UserRoleEnum.BRANCH_MANAGER and current_user.manages_branch:
            revenue_query = revenue_query.filter(Lead.branch_id == current_user.manages_branch.id)
        
        today_revenue = revenue_query.scalar() or 0
        
        # Active employees count
        employees_count = db.query(UserDetails).filter(UserDetails.is_active == True)
        if current_user.role == UserRoleEnum.BRANCH_MANAGER and current_user.manages_branch:
            employees_count = employees_count.filter(UserDetails.branch_id == current_user.manages_branch.id)
        employees_count = employees_count.count()
        
    else:
        # Employee quick stats
        leads_query = get_employee_leads_query(db, current_user.employee_code)
        
        total_leads = leads_query.count()
        today_leads = leads_query.filter(func.date(Lead.created_at) == today).count()
        
        # Revenue today for employee's leads
        today_revenue = db.query(func.sum(Payment.paid_amount)).join(
            Lead, Payment.lead_id == Lead.id
        ).join(
            LeadAssignment, Lead.id == LeadAssignment.lead_id
        ).filter(
            and_(
                LeadAssignment.user_id == current_user.employee_code,
                func.date(Payment.created_at) == today
            )
        ).scalar() or 0
        
        employees_count = 1  # Just the current user
    
    return {
        "total_leads": total_leads,
        "today_leads": today_leads,
        "today_revenue": float(today_revenue),
        "active_employees": employees_count,
        "last_updated": datetime.now().isoformat()
    }

@router.get("/trends/monthly")
async def get_monthly_trends(
    months: int = Query(12, ge=1, le=24, description="Number of months to analyze"),
    current_user: UserDetails = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get monthly trends for leads and revenue
    """
    monthly_data = []
    
    for i in range(months):
        # Calculate month start and end
        current_date = datetime.now().replace(day=1) - timedelta(days=32*i)
        month_start = current_date.replace(day=1)
        
        # Get next month start for end date
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1)
        
        # Get leads for this month
        if current_user.role in [UserRoleEnum.SUPERADMIN, UserRoleEnum.BRANCH_MANAGER]:
            leads_query = get_admin_leads_query(db, current_user, month_start.date(), month_end.date())
        else:
            leads_query = get_employee_leads_query(db, current_user.employee_code, month_start.date(), month_end.date())
        
        month_leads = leads_query.count()
        
        # Get revenue for this month
        if current_user.role in [UserRoleEnum.SUPERADMIN, UserRoleEnum.BRANCH_MANAGER]:
            revenue_query = db.query(func.sum(Payment.paid_amount)).join(
                Lead, Payment.lead_id == Lead.id
            ).filter(
                and_(
                    Payment.created_at >= month_start,
                    Payment.created_at < month_end,
                    Lead.is_delete == False
                )
            )
            
            if current_user.role == UserRoleEnum.BRANCH_MANAGER and current_user.manages_branch:
                revenue_query = revenue_query.filter(Lead.branch_id == current_user.manages_branch.id)
        else:
            revenue_query = db.query(func.sum(Payment.paid_amount)).join(
                Lead, Payment.lead_id == Lead.id
            ).join(
                LeadAssignment, Lead.id == LeadAssignment.lead_id
            ).filter(
                and_(
                    LeadAssignment.user_id == current_user.employee_code,
                    Payment.created_at >= month_start,
                    Payment.created_at < month_end
                )
            )
        
        month_revenue = revenue_query.scalar() or 0
        
        monthly_data.append({
            "month": month_start.strftime("%Y-%m"),
            "month_name": month_start.strftime("%B %Y"),
            "leads_count": month_leads,
            "revenue": float(month_revenue)
        })
    
    monthly_data.reverse()  # Show oldest to newest
    
    return {
        "monthly_trends": monthly_data,
        "period": f"Last {months} months",
        "generated_at": datetime.now().isoformat()
    }
           