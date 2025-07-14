# db/models.py - Complete Fixed Version without manager_id

from sqlalchemy import (
    Column, Integer, String, Text, Date, DateTime, Float, Boolean,
    JSON, ARRAY, ForeignKey, func, Enum, Enum as SAEnum
)
from sqlalchemy.orm import relationship
from db.connection import Base
import uuid
import enum


class UserRoleEnum(str, enum.Enum):
    SUPERADMIN = "SUPERADMIN"
    BRANCH_MANAGER = "BRANCH MANAGER"
    HR = "HR"
    SALES_MANAGER = "SALES MANAGER"
    TL = "TL"  # Team Leader
    SBA = "SBA"  # Senior Business Associate
    BA = "BA"  # Business Associate


class OTP(Base):
    __tablename__ = "crm_otps"

    id        = Column(Integer, primary_key=True, index=True)
    mobile    = Column(String(20), nullable=False, index=True)
    otp       = Column(Integer, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UserDetails(Base):
    __tablename__ = "crm_user_details"

    employee_code     = Column(String(100), primary_key=True, unique=True, index=True)
    phone_number      = Column(String(10), nullable=False, unique=True, index=True)
    email             = Column(String(100), nullable=False, unique=True, index=True)
    name              = Column(String(100), nullable=False)
    password          = Column(String(255), nullable=False)
    role              = Column(Enum(UserRoleEnum), nullable=False, default=UserRoleEnum.BA)

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

    # Foreign Keys - Removed manager_id, kept sales_manager_id and tl_id
    branch_id         = Column(Integer, ForeignKey("crm_branch_details.id"), nullable=True)
    sales_manager_id  = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=True)
    tl_id            = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=True)

    # Timestamps
    created_at        = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at        = Column(
                         DateTime(timezone=True),
                         server_default=func.now(),
                         onupdate=func.now(),
                         nullable=False
                       )

    # Relationships with explicit foreign_keys
    branch            = relationship(
                         "BranchDetails", 
                         back_populates="users",
                         foreign_keys=[branch_id]
                       )

    # Self-referential relationships for hierarchy
    sales_manager     = relationship(
                         "UserDetails",
                         remote_side=[employee_code],
                         foreign_keys=[sales_manager_id],
                         post_update=True
                       )
    
    tl                = relationship(
                         "UserDetails",
                         remote_side=[employee_code],
                         foreign_keys=[tl_id],
                         post_update=True
                       )

    # Branch management relationship (only for BRANCH MANAGER)
    manages_branch    = relationship(
                         "BranchDetails",
                         back_populates="manager",
                         uselist=False,
                         foreign_keys="[BranchDetails.manager_id]"
                       )

    # Other relationships
    permission        = relationship(
                         "PermissionDetails",
                         back_populates="user",
                         uselist=False,
                         cascade="all, delete-orphan"
                       )

    audit_logs        = relationship(
                         "AuditLog",
                         back_populates="user",
                         cascade="all, delete-orphan"
                       )
    notifications     = relationship(
                         "Notification",
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
    campaigns         = relationship(
                         "Campaign",
                         back_populates="owner",
                         cascade="all, delete-orphan"
                       )
    tokens            = relationship(
                    "TokenDetails",
                    back_populates="user",
                    cascade="all, delete-orphan"
                )

    def get_hierarchy_level(self):
        """Get hierarchy level based on role"""
        hierarchy = {
            UserRoleEnum.SUPERADMIN: 1,
            UserRoleEnum.BRANCH_MANAGER: 2,
            UserRoleEnum.SALES_MANAGER: 3,
            UserRoleEnum.HR: 3,
            UserRoleEnum.TL: 4,
            UserRoleEnum.SBA: 5,
            UserRoleEnum.BA: 6
        }
        return hierarchy.get(self.role, 7)

    def can_manage(self, other_user):
        """Check if this user can manage another user"""
        return self.get_hierarchy_level() < other_user.get_hierarchy_level()

    def get_required_manager_role(self):
        """Get the role that should be this user's manager"""
        manager_mapping = {
            UserRoleEnum.BRANCH_MANAGER: UserRoleEnum.SUPERADMIN,
            UserRoleEnum.SALES_MANAGER: UserRoleEnum.BRANCH_MANAGER,
            UserRoleEnum.HR: UserRoleEnum.BRANCH_MANAGER,
            UserRoleEnum.TL: UserRoleEnum.SALES_MANAGER,
            UserRoleEnum.BA: UserRoleEnum.TL,
            UserRoleEnum.SBA: UserRoleEnum.TL
        }
        return manager_mapping.get(self.role)


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
    pan               = Column(String(10), nullable=False)
    aadhaar           = Column(String(12), nullable=False)
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


class PermissionDetails(Base):
    __tablename__ = "crm_permission_details"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    user_id         = Column(String(100), ForeignKey("crm_user_details.employee_code"), unique=True, nullable=False)

    # User Management Permissions
    add_user        = Column(Boolean, default=False)
    edit_user       = Column(Boolean, default=False)
    delete_user     = Column(Boolean, default=False)

    # Lead Management Permissions
    add_lead        = Column(Boolean, default=False)
    edit_lead       = Column(Boolean, default=False)
    delete_lead     = Column(Boolean, default=False)

    # View Permissions
    view_users      = Column(Boolean, default=False)
    view_lead       = Column(Boolean, default=False)
    view_branch     = Column(Boolean, default=False)
    view_accounts   = Column(Boolean, default=False)
    view_research   = Column(Boolean, default=False)
    view_client     = Column(Boolean, default=False)
    view_payment    = Column(Boolean, default=False)
    view_invoice    = Column(Boolean, default=False)
    view_kyc        = Column(Boolean, default=False)

    # Special Permissions
    approval        = Column(Boolean, default=False)
    internal_mailing= Column(Boolean, default=False)
    chatting        = Column(Boolean, default=False)
    targets         = Column(Boolean, default=False)
    reports         = Column(Boolean, default=False)
    fetch_lead      = Column(Boolean, default=False)

    user            = relationship("UserDetails", back_populates="permission")

    @classmethod
    def get_default_permissions(cls, role: UserRoleEnum):
        """Get default permissions based on user role"""
        permissions = {
            UserRoleEnum.SUPERADMIN: {
                'add_user': True, 'edit_user': True, 'delete_user': True,
                'add_lead': True, 'edit_lead': True, 'delete_lead': True,
                'view_users': True, 'view_lead': True, 'view_branch': True,
                'view_accounts': True, 'view_research': True, 'view_client': True,
                'view_payment': True, 'view_invoice': True, 'view_kyc': True,
                'approval': True, 'internal_mailing': True, 'chatting': True,
                'targets': True, 'reports': True, 'fetch_lead': True
            },
            UserRoleEnum.BRANCH_MANAGER: {
                'add_user': True, 'edit_user': True, 'delete_user': False,
                'add_lead': True, 'edit_lead': True, 'delete_lead': True,
                'view_users': True, 'view_lead': True, 'view_branch': True,
                'view_accounts': True, 'view_research': True, 'view_client': True,
                'view_payment': True, 'view_invoice': True, 'view_kyc': True,
                'approval': True, 'internal_mailing': True, 'chatting': True,
                'targets': True, 'reports': True, 'fetch_lead': True
            },
            UserRoleEnum.SALES_MANAGER: {
                'add_user': False, 'edit_user': False, 'delete_user': False,
                'add_lead': True, 'edit_lead': True, 'delete_lead': False,
                'view_users': True, 'view_lead': True, 'view_branch': False,
                'view_accounts': True, 'view_research': True, 'view_client': True,
                'view_payment': True, 'view_invoice': True, 'view_kyc': True,
                'approval': False, 'internal_mailing': True, 'chatting': True,
                'targets': True, 'reports': True, 'fetch_lead': True
            },
            UserRoleEnum.HR: {
                'add_user': True, 'edit_user': True, 'delete_user': False,
                'add_lead': False, 'edit_lead': False, 'delete_lead': False,
                'view_users': True, 'view_lead': False, 'view_branch': True,
                'view_accounts': False, 'view_research': False, 'view_client': False,
                'view_payment': False, 'view_invoice': False, 'view_kyc': False,
                'approval': False, 'internal_mailing': True, 'chatting': True,
                'targets': False, 'reports': True, 'fetch_lead': False
            },
            UserRoleEnum.TL: {
                'add_user': False, 'edit_user': False, 'delete_user': False,
                'add_lead': True, 'edit_lead': True, 'delete_lead': False,
                'view_users': True, 'view_lead': True, 'view_branch': False,
                'view_accounts': True, 'view_research': True, 'view_client': True,
                'view_payment': True, 'view_invoice': True, 'view_kyc': True,
                'approval': False, 'internal_mailing': True, 'chatting': True,
                'targets': True, 'reports': True, 'fetch_lead': True
            },
            UserRoleEnum.SBA: {
                'add_user': False, 'edit_user': False, 'delete_user': False,
                'add_lead': True, 'edit_lead': True, 'delete_lead': False,
                'view_users': False, 'view_lead': True, 'view_branch': False,
                'view_accounts': True, 'view_research': True, 'view_client': True,
                'view_payment': True, 'view_invoice': True, 'view_kyc': True,
                'approval': False, 'internal_mailing': False, 'chatting': True,
                'targets': False, 'reports': False, 'fetch_lead': True
            },
            UserRoleEnum.BA: {
                'add_user': False, 'edit_user': False, 'delete_user': False,
                'add_lead': True, 'edit_lead': True, 'delete_lead': False,
                'view_users': False, 'view_lead': True, 'view_branch': False,
                'view_accounts': True, 'view_research': True, 'view_client': True,
                'view_payment': True, 'view_invoice': True, 'view_kyc': True,
                'approval': False, 'internal_mailing': False, 'chatting': True,
                'targets': False, 'reports': False, 'fetch_lead': True
            }
        }
        return permissions.get(role, {})


class LeadAssignment(Base):
    __tablename__ = "crm_lead_assignments"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    lead_id      = Column(Integer, ForeignKey("crm_lead.id"), nullable=False, unique=True)
    user_id      = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=False)
    fetched_at   = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    lead         = relationship("Lead", back_populates="assignment")
    user         = relationship("UserDetails")


class LeadFetchConfig(Base):
    __tablename__ = "crm_lead_fetch_config"
    id                = Column(Integer, primary_key=True, autoincrement=True)
    role              = Column(Enum(UserRoleEnum), nullable=True)
    branch_id         = Column(Integer, ForeignKey("crm_branch_details.id"), nullable=True)
    per_request_limit = Column(Integer, nullable=False)
    daily_call_limit  = Column(Integer, nullable=False)
    assignment_ttl_hours = Column(Integer, nullable=False, default=24*7)

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

    leads       = relationship("Lead", back_populates="lead_source")


class LeadResponse(Base):
    __tablename__ = "crm_lead_response"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    name       = Column(String(100), nullable=False, unique=True, index=True)
    lead_limit = Column(Integer, default=0)

    leads      = relationship("Lead", back_populates="lead_response")


class LeadStory(Base):
    __tablename__ = "crm_lead_story"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    lead_id          = Column(Integer, ForeignKey("crm_lead.id"), nullable=False)
    user_id          = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=False)
    timestamp        = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    title            = Column(String(200), nullable=True)
    msg              = Column(Text, nullable=False)
    lead_response_id = Column(Integer, ForeignKey("crm_lead_response.id"), nullable=True)

    lead             = relationship("Lead", back_populates="stories")
    user             = relationship("UserDetails")
    response         = relationship("LeadResponse")


class Lead(Base):
    __tablename__ = "crm_lead"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    full_name         = Column(String(100), nullable=True)
    father_name       = Column(String(100), nullable=True)
    email             = Column(String(100), nullable=True, index=True)
    mobile            = Column(String(20), nullable=True, index=True)
    alternate_mobile  = Column(String(20), nullable=True)
    aadhaar           = Column(String(12), nullable=True)
    pan               = Column(String(10), nullable=True)
    gstin             = Column(String(15), nullable=True)

    state             = Column(String(100), nullable=True)
    city              = Column(String(100), nullable=True)
    district          = Column(String(100), nullable=True)
    address           = Column(Text, nullable=True)

    dob               = Column(Date, nullable=True)
    occupation        = Column(String(100), nullable=True)
    segment           = Column(Text, nullable=True)  # Store as JSON string
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
    kyc_id            = Column(Integer, nullable=True)

    is_old_lead       = Column(Boolean, default=False, nullable=True)
    call_back_date    = Column(DateTime, nullable=True)
    lead_status       = Column(String(50), nullable=True)
    profile           = Column(String(50), nullable=True)

    created_at        = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    branch_id         = Column(Integer, ForeignKey("crm_branch_details.id"), nullable=True)

    branch            = relationship("BranchDetails", back_populates="leads")
    payments          = relationship("Payment", back_populates="lead")
    stories           = relationship("LeadStory", back_populates="lead", cascade="all, delete-orphan")
    lead_source       = relationship("LeadSource", back_populates="leads")
    lead_response     = relationship("LeadResponse", back_populates="leads")
    assignment        = relationship("LeadAssignment", back_populates="lead", uselist=False)


class Payment(Base):
    __tablename__ = "crm_payment"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    name             = Column(String(100), nullable=False)
    email            = Column(String(100), nullable=False)
    phone_number     = Column(Text, nullable=False)
    order_id         = Column(String(100), nullable=True, index=True)

    Service          = Column(String(50), nullable=True)
    paid_amount      = Column(Float, nullable=False)
    status           = Column(String(50), nullable=True)
    mode             = Column(String(50), nullable=False)
    is_send_invoice  = Column(Boolean, nullable=False, default=False)
    description      = Column(Text, nullable=True)
    transaction_id   = Column(String(100), nullable=True)
    user_id          = Column(Integer, nullable=True)
    branch_id        = Column(Integer, nullable=True)

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


class Notification(Base):
    __tablename__ = "crm_notifications"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    user_id    = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=False)
    type       = Column(String(30), nullable=False)
    message    = Column(Text, nullable=False)
    is_read    = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user       = relationship("UserDetails", back_populates="notifications")


class Attendance(Base):
    __tablename__ = "crm_attendance"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    employee_code = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=False)
    date          = Column(Date, nullable=False)
    check_in      = Column(DateTime(timezone=True), nullable=True)
    check_out     = Column(DateTime(timezone=True), nullable=True)
    status        = Column(String(20), nullable=False)

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


class Campaign(Base):
    __tablename__ = "crm_campaigns"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(150), nullable=False, unique=True)
    start_date  = Column(Date, nullable=False)
    end_date    = Column(Date, nullable=True)
    budget      = Column(Float, nullable=True)
    status      = Column(String(20), nullable=False, default="planned")
    results     = Column(JSON, nullable=True)
    created_by  = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    owner       = relationship("UserDetails", back_populates="campaigns")


class BillingCycleEnum(str, enum.Enum):
    MONTHLY = "MONTHLY"
    YEARLY  = "YEARLY"
    CALL = "CALL"


class Service(Base):
    __tablename__ = "crm_services"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    name             = Column(String(100), nullable=False, unique=True, index=True)
    description      = Column(Text, nullable=True)

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
    




    