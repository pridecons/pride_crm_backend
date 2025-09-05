from sqlalchemy import (
    Column, Integer, String, Text, Date, DateTime, Float, Boolean,
    JSON, ARRAY, ForeignKey, func, Enum, Enum as SAEnum, text, select, BigInteger
)
from sqlalchemy.orm import relationship, column_property
from db.connection import Base
import uuid
import enum
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime   

# class RecommendationType(str, enum.Enum):
#     equity_cash= "Equity Cash"
#     stock_future= "Stock Future"
#     index_future= "Index Future"
#     index_option= "Index Option"
#     stock_option= "Stock Option"
#     mcx_bullion= "MCX Bullion"
#     mcx_base_metal= "MCX Base Metal"
#     mcx_energy= "MCX Energy"

class RecommendationType(str, enum.Enum):
    equity_cash_buy= "Equity Cash Buy"
    equity_cash_sell= "Equity Cash Sell"
    stock_future_buy= "Stock Future Buy"
    stock_future_sell= "Stock Future Sell"
    index_future_buy= "Index Future Buy"
    index_future_sell= "Index Future Sell"
    index_option_call_buy= "Index Option Call Buy"
    index_option_put_buy= "Index Option Put Buy"
    stock_option_call_buy= "Stock Option Call Buy"
    stock_option_put_buy= "Stock Option Put Buy"
    mcx_bullion_buy= "MCX Bullion Buy"
    mcx_bullion_sell= "MCX Bullion Sell"
    mcx_base_metal_buy= "MCX Base Metal Buy"
    mcx_base_metal_sell= "MCX Base Metal Sell"
    mcx_energy_buy= "MCX Energy Buy"
    mcx_energy_sell= "MCX Energy Sell"

class PermissionDetails(str, enum.Enum):
    # LEAD/[id]
    lead_recording_view = "lead_recording_view"
    lead_recording_upload   = "lead_recording_upload"
    lead_story_view = "lead_story_view"
    lead_transfer = "lead_transfer"
    lead_branch_view = "lead_branch_view"

    # LEAD SOURCE
    create_lead = "create_lead"
    edit_lead = "edit_lead"
    delete_lead  = 'delete_lead'

    # LEAD RESPONSE
    create_new_lead_response  = "create_new_lead_response"
    edit_response = "edit_response"
    delete_response = "delete_response"

    # USER 
    user_add_user = "user_add_user"
    user_all_roles = 'user_all_roles'
    user_all_branches = "user_all_branches"
    user_view_user_details = "user_view_user_details"
    user_edit_user = "user_edit_user"
    user_delete_user = "user_delete_user"

    # FETCH LIMIT
    fetch_limit_create_new = 'fetch_limit_create_new'
    fetch_limit_edit = "fetch_limit_edit"
    fetch_limit_delete = "fetch_limit_delete"

    # PLANS
    plans_create = "plans_create"
    edit_plan = "edit_plan"
    delete_plane = "delete_plane"

    # CLIENT
    client_select_branch = "client_select_branch"
    client_invoice = "client_invoice"
    client_story = "client_story"
    client_comments = "client_comments"

    # SIDEBAR
    lead_manage_page = "lead_manage_page"
    plane_page = "plane_page"
    attandance_page = "attandance_page"
    client_page = "client_page"
    lead_source_page = "lead_source_page"
    lead_response_page = "lead_response_page"
    user_page = "user_page"
    permission_page = "permission_page"
    lead_upload_page = "lead_upload_page"
    fetch_limit_page = "fetch_limit_page"


    add_lead_page = "add_lead_page"
    payment_page = "payment_page"
    messanger_page = "messanger_page"
    template = "template"
    sms_page = "sms_page"
    email_page = "email_page"
    branch_page = "branch_page"
    old_lead_page = "old_lead_page"
    new_lead_page = "new_lead_page"
    department_page = "department_page"

    # MESSANGER
    rational_download = "rational_download"
    rational_pdf_model_download = "rational_pdf_model_download"
    rational_pdf_model_view = "rational_pdf_model_view"
    rational_graf_model_view = "rational_graf_model_view"
    rational_status = "rational_status"
    rational_edit = "rational_edit"
    rational_add_recommadation = "rational_add_recommadation"

    # EMAIL
    email_add_temp = "email_add_temp"
    email_view_temp = "email_view_temp"
    email_edit_temp = "email_edit_temp"
    email_delete_temp = "email_delete_temp"

    # SMS
    sms_add = "sms_add"
    sms_edit = "sms_edit"
    sms_delete = 'sms_delete'

    # BRANCH
    branch_add = "branch_add"
    branch_edit = "branch_edit"
    branch_details = "branch_details"
    branch_agreement_view = "branch_agreement_view"

    # header 
    header_global_search = "header_global_search"

    
class OTP(Base):
    __tablename__ = "crm_otps"

    id        = Column(Integer, primary_key=True, index=True)
    mobile    = Column(String(20), nullable=False, index=True)
    otp       = Column(Integer, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class Department(Base):
    __tablename__ = "crm_departments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    available_permissions = Column(ARRAY(String), nullable=True, default=[])

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    profiles = relationship("ProfileRole", back_populates="department", cascade="all, delete-orphan")
    users = relationship("UserDetails", back_populates="department")


class ProfileRole(Base):
    __tablename__ = "crm_profile_roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, index=True)

    department_id = Column(Integer, ForeignKey("crm_departments.id"), nullable=False, index=True)
    hierarchy_level = Column(Integer, nullable=False)
    default_permissions = Column(ARRAY(String), nullable=True, default=[])
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Existing relationship
    department = relationship("Department", back_populates="profiles")
    
    # ADD THIS MISSING RELATIONSHIP:
    users = relationship(
        "UserDetails",
        back_populates="profile_role", 
        foreign_keys="[UserDetails.role_id]"
    )



class UserDetails(Base):
    __tablename__ = "crm_user_details"

    employee_code     = Column(String(100), primary_key=True, unique=True, index=True)
    phone_number      = Column(String(10), nullable=False, unique=True, index=True)
    email             = Column(String(100), nullable=False, unique=True, index=True)
    name              = Column(String(100), nullable=False)
    password          = Column(String(255), nullable=False)
    role_id = Column(Integer, ForeignKey("crm_profile_roles.id"), nullable=False, index=True)

    # DO NOT store role_name as a second FK column; derive it read-only instead:
    role_name = column_property(
        select(ProfileRole.name).where(ProfileRole.id == role_id).scalar_subquery()
    )


    father_name       = Column(String(100), nullable=False)
    is_active         = Column(Boolean, nullable=False, default=True)
    experience        = Column(Float, nullable=False)

    date_of_joining   = Column(Date, nullable=False)
    date_of_birth     = Column(Date, nullable=False)

    pan               = Column(String(10), nullable=True)
    aadhaar           = Column(String(12), nullable=True)

    address           = Column(Text, nullable=True)
    city              = Column(String(100), nullable=True)
    state             = Column(String(100), nullable=True)
    pincode           = Column(String(6), nullable=True)

    comment           = Column(Text, nullable=True)

    # Foreign Keys - Removed manager_id, kept
    branch_id         = Column(Integer, ForeignKey("crm_branch_details.id"), nullable=True)
    senior_profile_id  = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=True)
    permissions = Column(ARRAY(String), nullable=True, default=[])

    vbc_extension_id = Column(String(10), nullable=True)
    vbc_user_username = Column(String(100), nullable=True)
    vbc_user_password = Column(String(100), nullable=True)

    # Timestamps
    created_at        = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at        = Column(
                         DateTime(timezone=True),
                         server_default=func.now(),
                         onupdate=func.now(),
                         nullable=False
                       )
    department_id = Column(Integer, ForeignKey("crm_departments.id"), nullable=True, index=True)
    reference_id = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=True, index=True)
    target   = Column(Float, nullable=True)
    profile_role = relationship(
        "ProfileRole", 
        back_populates="users",
        foreign_keys=[role_id]
    )
    department = relationship(
        "Department",
        back_populates="users",
        foreign_keys=[department_id],
    )

    # Relationships with explicit foreign_keys
    branch            = relationship(
                         "BranchDetails", 
                         back_populates="users",
                         foreign_keys=[branch_id]
                       )
    


    # Branch management relationship (only for BRANCH MANAGER)
    manages_branch    = relationship(
                         "BranchDetails",
                         back_populates="manager",
                         uselist=False,
                         foreign_keys="[BranchDetails.manager_id]"
                       )


    audit_logs        = relationship(
                         "AuditLog",
                         back_populates="user",
                         cascade="all, delete-orphan"
                       )

    attendance_records= relationship(
                         "Attendance",
                         back_populates="employee",
                         cascade="all, delete-orphan"
                       )
    salary_slips      = relationship(
                         "SalarySlip",
                         back_populates="employee",
                         cascade="all, delete-orphan"
                       )
    tokens            = relationship(
                    "TokenDetails",
                    back_populates="user",
                    cascade="all, delete-orphan"
                )



class TokenDetails(Base):
    __tablename__ = "crm_token_details"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        unique=True,
        nullable=False
    )

    user_id = Column(
        String(100),
        ForeignKey("crm_user_details.employee_code", ondelete="CASCADE"),
        nullable=False
    )

    refresh_token = Column(String(255), unique=True, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    user = relationship("UserDetails", back_populates="tokens")


class BranchDetails(Base):
    __tablename__ = "crm_branch_details"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    name              = Column(String(100), nullable=False, unique=True, index=True)
    address           = Column(Text, nullable=False)
    authorized_person = Column(String(100), nullable=False)
    agreement_url     = Column(String(255), nullable=True)
    active            = Column(Boolean, nullable=False, default=True)

    created_at        = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at        = Column(
                         DateTime(timezone=True),
                         server_default=func.now(),
                         onupdate=func.now(),
                         nullable=False
                       )

    # Branch Manager (one-to-one relationship)
    manager_id        = Column(String(100), ForeignKey("crm_user_details.employee_code"), unique=True, nullable=True)
    
    # Relationships
    manager           = relationship(
                         "UserDetails",
                         back_populates="manages_branch",
                         foreign_keys=[manager_id],
                         uselist=False
                       )

    users             = relationship(
                         "UserDetails",
                         back_populates="branch",
                         foreign_keys="[UserDetails.branch_id]",
                         cascade="all, delete-orphan"
                       )
    leads             = relationship(
                         "Lead",
                         back_populates="branch",
                         cascade="all, delete-orphan"
                       )


class LeadAssignment(Base):
    __tablename__ = "crm_lead_assignments"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    lead_id      = Column(Integer, ForeignKey("crm_lead.id"), nullable=False, unique=True)
    user_id      = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=False)
    is_call      = Column(Boolean, default=False)
    fetched_at   = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    lead         = relationship("Lead", back_populates="assignment")
    user         = relationship("UserDetails")


class LeadFetchConfig(Base):
    __tablename__ = "crm_lead_fetch_config"
    id                = Column(Integer, primary_key=True, autoincrement=True)
    role_id              = Column(String(50), nullable=True)
    branch_id         = Column(Integer, ForeignKey("crm_branch_details.id"), nullable=True)
    per_request_limit = Column(Integer, nullable=False)
    daily_call_limit  = Column(Integer, nullable=False)
    last_fetch_limit  = Column(Integer, nullable=False)
    assignment_ttl_hours = Column(Integer, nullable=False, default=24*7)
    old_lead_remove_days = Column(Integer, nullable=True, default=30)

    # Add relationship
    branch = relationship("BranchDetails", foreign_keys=[branch_id])


class LeadFetchHistory(Base):
    __tablename__ = "crm_lead_fetch_history"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    user_id     = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=False)
    date        = Column(Date, nullable=False, index=True)
    call_count  = Column(Integer, default=0, nullable=False)


class LeadSource(Base):
    __tablename__ = "crm_lead_source"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(100), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    created_by  = Column(String(100), nullable=True)
    branch_id   = Column(Integer, ForeignKey("crm_branch_details.id"), nullable=True)

    leads       = relationship("Lead", back_populates="lead_source")


class LeadResponse(Base):
    __tablename__ = "crm_lead_response"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    name       = Column(String(100), nullable=False, unique=True, index=True)

    leads      = relationship("Lead", back_populates="lead_response")

class LeadStory(Base):
    __tablename__ = "crm_lead_story"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    lead_id          = Column(Integer, ForeignKey("crm_lead.id"), nullable=False)
    user_id          = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=False)
    msg              = Column(Text, nullable=False)
    timestamp        = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    lead             = relationship("Lead", back_populates="stories")
    user             = relationship("UserDetails")

class LeadComment(Base):
    __tablename__ = "crm_comment"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    lead_id          = Column(Integer, ForeignKey("crm_lead.id"), nullable=False)
    user_id          = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=False)
    timestamp        = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    comment          = Column(Text, nullable=False)

    lead             = relationship("Lead", back_populates="comments")
    user             = relationship("UserDetails")


class Lead(Base):
    __tablename__ = "crm_lead"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    full_name         = Column(String(100), nullable=True)
    director_name     = Column(String(100), nullable=True)
    father_name       = Column(String(100), nullable=True)
    gender            = Column(String(10), nullable=True)
    marital_status    = Column(String(20), nullable=True)
    email             = Column(String(100), nullable=True, index=True)
    mobile            = Column(String(20), nullable=True, index=True)
    alternate_mobile  = Column(String(20), nullable=True)
    aadhaar           = Column(String(12), nullable=True)
    pan               = Column(String(10), nullable=True)
    gstin             = Column(String(15), nullable=True, default="URP")

    state             = Column(String(100), nullable=True)
    city              = Column(String(100), nullable=True)
    district          = Column(String(100), nullable=True)
    address           = Column(Text, nullable=True)
    pincode           = Column(String(6), nullable=True)
    country           = Column(String(50), nullable=True)

    dob               = Column(Date, nullable=True)
    occupation        = Column(String(100), nullable=True)
    segment           = Column(Text, nullable=True)  # Store as JSON string
    ft_service_type   = Column(String(50), nullable=True) #call or sms
    experience        = Column(String(50), nullable=True)
    investment        = Column(String(50), nullable=True)

    lead_response_id  = Column(Integer, ForeignKey("crm_lead_response.id"), nullable=True)
    lead_source_id    = Column(Integer, ForeignKey("crm_lead_source.id"), nullable=True)

    created_by        = Column(String(100), nullable=True)
    created_by_name   = Column(String(100), nullable=True)
    comment           = Column(Text, nullable=True)  # Store as JSON string

    aadhar_front_pic  = Column(String(255), nullable=True)
    aadhar_back_pic   = Column(String(255), nullable=True)
    pan_pic           = Column(String(255), nullable=True)
    kyc               = Column(Boolean, default=False, nullable=True)
    kyc_id            = Column(String(100), nullable=True)

    is_old_lead       = Column(Boolean, default=False, nullable=True)
    call_back_date    = Column(DateTime, nullable=True)
    lead_status       = Column(String(50), nullable=True)
    is_delete         = Column(Boolean, default=False, nullable=True)
    ft_to_date        = Column(String(50), nullable=True)
    ft_from_date      = Column(String(50), nullable=True)
    is_client         = Column(Boolean, default=False, nullable=True)
    assigned_to_user = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=True)
    response_changed_at = Column(DateTime(timezone=True), nullable=True)
    assigned_for_conversion = Column(Boolean, default=False, nullable=True) 
    conversion_deadline = Column(DateTime(timezone=True), nullable=True)

    created_at        = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at        = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    branch_id         = Column(Integer, ForeignKey("crm_branch_details.id"), nullable=True)
    reference_id = Column(String(100), ForeignKey("crm_lead.id"), nullable=True, index=True)

    comments          = relationship("LeadComment", back_populates="lead", cascade="all, delete-orphan")
    branch            = relationship("BranchDetails", back_populates="leads")
    payments          = relationship("Payment", back_populates="lead")
    stories           = relationship("LeadStory", back_populates="lead", cascade="all, delete-orphan")
    lead_source       = relationship("LeadSource", back_populates="leads")
    lead_response     = relationship("LeadResponse", back_populates="leads")
    assignment        = relationship("LeadAssignment", back_populates="lead", uselist=False)
    recordings = relationship("LeadRecording", back_populates="lead", cascade="all, delete-orphan")
    assigned_user = relationship("UserDetails", foreign_keys=[assigned_to_user])

class Payment(Base):
    __tablename__ = "crm_payment"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    name             = Column(String(100), nullable=True)
    email            = Column(String(100), nullable=True)
    phone_number     = Column(Text, nullable=False)
    order_id         = Column(String(100), nullable=True, index=True)

    Service          = Column(ARRAY(String), nullable=True)
    paid_amount      = Column(Float, nullable=False)
    call             = Column(Integer, nullable=True)
    duration_day     = Column(Integer, nullable=True)
    plan             = Column(
                            JSONB, 
                            nullable=True, 
                            server_default="[]",       # default to empty list in DB
                        )
    status           = Column(String(50), nullable=True)
    mode             = Column(String(50), nullable=False)
    is_send_invoice  = Column(Boolean, nullable=False, default=False)
    invoice          = Column(String(255), nullable=True)
    invoice_no       = Column(String(300), nullable=True)
    description      = Column(Text, nullable=True)
    transaction_id   = Column(String(100), nullable=True)
    user_id          = Column(String(50), nullable=True)
    branch_id        = Column(String(50), nullable=True)

    created_at       = Column(
                         DateTime(timezone=True),
                         server_default=func.now(),
                         nullable=False
                      )
    updated_at       = Column(
                         DateTime(timezone=True),
                         server_default=func.now(),
                         onupdate=func.now(),
                         nullable=False
                       )

    # foreign key to Lead, many payments per lead
    lead_id          = Column(Integer, ForeignKey("crm_lead.id"), nullable=True)
    lead             = relationship("Lead", back_populates="payments")


class ServiceDispatchHistory(Base):
    __tablename__ = "crm_service_dispatch_history"

    id = Column(Integer, primary_key=True, autoincrement=True)

    lead_id = Column(Integer, ForeignKey("crm_lead.id"), nullable=False, index=True)
    recommendation_id = Column(Integer, ForeignKey("crm_narration.id"), nullable=True, index=True)
    payment_id = Column(Integer, ForeignKey("crm_payment.id"), nullable=True, index=True)

    service_name = Column(String(150), nullable=False, index=True)
    scheduled_for = Column(DateTime(timezone=True), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    lead = relationship("Lead", backref="dispatch_histories")
    recommendation = relationship("NARRATION", backref="dispatch_histories")
    payment = relationship("Payment", backref="dispatch_histories")
    platform_statuses = relationship("ServiceDispatchPlatformStatus", back_populates="dispatch_history", cascade="all, delete-orphan")


class ServiceDispatchPlatformStatus(Base):
    __tablename__ = "crm_service_dispatch_platform_status"

    id = Column(Integer, primary_key=True, autoincrement=True)
    history_id = Column(Integer, ForeignKey("crm_service_dispatch_history.id"), nullable=False)

    platform = Column(String(30), nullable=False)  # SMS, WHATSAPP, CALL, EMAIL, APPLICATION
    platform_identifier = Column(String(100), nullable=True)  # Twilio ID, WhatsApp Msg ID, etc.
    status = Column(String(30), nullable=False, default="PENDING")  # SENT / FAILED / etc.
    delivered_at = Column(String(100), nullable=True)

    dispatch_history = relationship("ServiceDispatchHistory", back_populates="platform_statuses")

class LeadRecording(Base):
    __tablename__ = "crm_lead_recordings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # link back to Lead
    lead_id = Column(Integer, ForeignKey("crm_lead.id"), nullable=False)

    # optional link to an employee (must match crm_user_details.employee_code)
    employee_code = Column(
        String(100),                           # ← use String, not Integer
        ForeignKey("crm_user_details.employee_code"),
        nullable=True
    )

    recording_url = Column(String(255), nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    lead = relationship("Lead", back_populates="recordings")
    employee = relationship("UserDetails", backref="recordings")

class BillingCycleEnum(str, enum.Enum):
    MONTHLY = "MONTHLY"
    YEARLY  = "YEARLY"
    CALL = "CALL"

class Service(Base):
    __tablename__ = "crm_services"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    name             = Column(String(100), nullable=False, unique=True, index=True)
    description      = Column(Text, nullable=True)
    service_type      = Column(ARRAY(String), nullable=True)

    # Base price before discount
    price            = Column(Float, nullable=False)

    CALL            = Column(Integer, nullable=True)

    # Discount percentage (0–100)
    discount_percent = Column(Float, nullable=True, default=0.0)

    billing_cycle    = Column(
                          SAEnum(BillingCycleEnum),
                          nullable=False,
                          default=BillingCycleEnum.MONTHLY
                       )

    @property
    def discounted_price(self) -> float:
        """Compute price after discount"""
        return round(self.price * (1 - self.discount_percent / 100), 2)
    
class AuditLog(Base):
    __tablename__ = "crm_audit_logs"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    user_id   = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=False)
    action    = Column(String(20), nullable=False)
    entity    = Column(String(50), nullable=False)
    entity_id = Column(String(100), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    details   = Column(JSON, nullable=True)

    user      = relationship("UserDetails", back_populates="audit_logs")

class Attendance(Base):
    __tablename__ = "crm_attendance"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    employee_code = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=False)
    date          = Column(Date, nullable=False)
    check_in      = Column(DateTime(timezone=True), nullable=True)
    check_out     = Column(DateTime(timezone=True), nullable=True)
    status        = Column(String(20), nullable=False)

    created_at    = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    employee      = relationship("UserDetails", back_populates="attendance_records")


class SalarySlip(Base):
    __tablename__ = "crm_salary_slips"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    employee_code    = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=False)
    month_year       = Column(Date, nullable=False)
    base_salary      = Column(Float, nullable=False)
    commission_total = Column(Float, default=0.0, nullable=False)
    bonus            = Column(Float, default=0.0, nullable=False)
    deductions       = Column(Float, default=0.0, nullable=False)
    net_pay          = Column(Float, nullable=False)
    generated_at     = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    slip_url         = Column(String(255), nullable=True)

    employee         = relationship("UserDetails", back_populates="salary_slips")


class PanVerification(Base):
    __tablename__ = "crm_pan_verifications"

    PANnumber = Column(String(10), primary_key=True, index=True)
    response  = Column(Text, nullable=True)
    APICount = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
                    DateTime(timezone=True),
                    server_default=func.now(),
                    onupdate=func.now(),
                    nullable=False
                )
    

class NARRATION(Base):
    __tablename__ = "crm_narration"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    entry_price = Column(Float, nullable=True)
    stop_loss   = Column(Float, nullable=True)
    targets    = Column(Float, default=0, nullable=True)
    targets2    = Column(Float, nullable=True)
    targets3    = Column(Float, nullable=True)
    status = Column(String(50), default="OPEN", nullable=False)
    # OPEN, TARGET1_HIT, TARGET2_HIT, TARGET3_HIT, STOP_LOSS_HIT, CLOSED
    graph    = Column(String, nullable=True)
    rational   = Column(String(100),nullable=True )
    stock_name       = Column(String(100),nullable=True )
    recommendation_type = Column(ARRAY(String),nullable=True )
    pdf  = Column(String, nullable=True)
    user_id   = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
                    DateTime(timezone=True),
                    server_default=func.now(),
                    onupdate=func.now(),
                    nullable=False
                )
    

class TemplateTypeEnum(str, enum.Enum):
    ADMIN = "admin"
    EMPLOYEE = "employee"

class EmailTemplate(Base):
    __tablename__ = "crm_email_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    template_type = Column(ARRAY(String), nullable=False)
    subject = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)

class SMSTemplate(Base):
    __tablename__ = "crm_sms_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    dlt_template_id = Column(String(200), nullable=False, index=True)
    message_type = Column(String(200), nullable=False)
    source_address = Column(ARRAY(String), nullable=False)  # array of strings
    allowed_roles = Column(
        ARRAY(String),
        nullable=False,
        server_default=text("ARRAY['HR','TL','SBA','BA','RESEARCHER']::text[]"),
        comment="Which user roles are permitted to use this template",
    )

    template = Column(Text, nullable=False)

    logs = relationship("SMSLog", back_populates="template")

class SMSLog(Base):
    __tablename__ = "crm_sms_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    template_id = Column(Integer, ForeignKey("crm_sms_templates.id"), nullable=False)
    lead_id = Column(Integer, ForeignKey("crm_lead.id"), nullable=False)
    recipient_phone_number = Column(String(320), nullable=False, index=True)
    body = Column(Text, nullable=False)
    sms_type = Column(String(50), nullable=True)
    status = Column(String(50), nullable=True)
    sent_id = Column(String(100), nullable=True)
    sent_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    user_id = Column(String(50), nullable=False, index=True)

    template = relationship("SMSTemplate", back_populates="logs")


class WhatsappLog(Base):
    __tablename__ = "crm_whatsapp_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    template_id = Column(Integer, ForeignKey("crm_sms_templates.id"), nullable=True)
    lead_id = Column(Integer, ForeignKey("crm_lead.id"), nullable=False)
    recipient_phone_number = Column(String(320), nullable=False, index=True)
    sent_id = Column(String(100), nullable=True)
    template = Column(Text, nullable=False)
    sms_type = Column(String(50), nullable=True)
    status = Column(String(50), nullable=True)
    sent_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    user_id = Column(String(50), nullable=False, index=True)

class EmailLog(Base):
    __tablename__ = "crm_email_logs"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    template_id     = Column(Integer, ForeignKey("crm_email_templates.id"), nullable=True)
    recipient_email = Column(String(320), nullable=False, index=True)
    sender_email = Column(String(320), nullable=True)
    mail_type = Column(String(50), nullable=True)
    subject         = Column(String(200), nullable=False)
    body            = Column(Text, nullable=False)
    user_id         = Column(String(50), nullable=False, index=True)
    sent_id = Column(String(100), nullable=True)
    sent_at         = Column(DateTime, nullable=False, default=datetime.utcnow)

    template = relationship("EmailTemplate", back_populates="logs")

# also add back‑ref on EmailTemplate:
EmailTemplate.logs = relationship(
    "EmailLog", order_by=EmailLog.sent_at.desc(), back_populates="template"
)

class ClientConsent(Base):
    __tablename__ = "crm_client_consent"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("crm_lead.id"), nullable=False)
    email = Column(String(255), nullable=True)
    consent_text = Column(String, nullable=False)
    channel = Column(String(20), nullable=False, default="WEB")
    purpose = Column(String(50), nullable=False, default="PAYMENT")
    ip_address = Column(String(64), nullable=False)
    user_agent = Column(String, nullable=False)
    device_info = Column(JSON, nullable=True)
    tz_offset_minutes = Column(Integer, nullable=False)

    consented_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    consented_at_ist = Column(DateTime(timezone=True), nullable=False)

    ref_id = Column(String(40), unique=True, nullable=False)
    mail_sent = Column(Boolean, nullable=True, default=False)

