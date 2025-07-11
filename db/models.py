from sqlalchemy import (
    Column, Integer, String, Text, Date, DateTime, Float, Boolean,
    JSON, ARRAY, ForeignKey, func
)
from sqlalchemy.orm import relationship
from db.connection import Base
import uuid


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
    role              = Column(String(30), nullable=False, default="user")

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

    branch_id         = Column(Integer, ForeignKey("crm_branch_details.id"), nullable=False)
    manager_id        = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=True)

    created_at        = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at        = Column(
                         DateTime(timezone=True),
                         server_default=func.now(),
                         onupdate=func.now(),
                         nullable=False
                       )

    # relationships
    branch            = relationship("BranchDetails", back_populates="users")
    manages_branch    = relationship(
                         "BranchDetails",
                         back_populates="manager",
                         uselist=False,
                         foreign_keys="[BranchDetails.manager_id]"
                       )

    manager           = relationship(
                         "UserDetails",
                         remote_side=[employee_code],
                         back_populates="subordinates"
                       )
    subordinates      = relationship(
                         "UserDetails",
                         back_populates="manager",
                         cascade="all, delete-orphan"
                       )

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


class TokenDetails(Base):
    __tablename__ = "crm_token_details"

    # Use a UUID4 string ID (36 chars including hyphens)
    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        unique=True,
        nullable=False
    )

    # Link to the UserDetails.employee_code
    user_id = Column(
        String(100),
        ForeignKey("crm_user_details.employee_code", ondelete="CASCADE"),
        nullable=False
    )

    refresh_token = Column(String(255), unique=True, nullable=False)

    # Use server-side timestamp for consistency
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    # relationship back to UserDetails
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

    manager_id        = Column(String(100), ForeignKey("crm_user_details.employee_code"), unique=True, nullable=True)
    manager           = relationship(
                         "UserDetails",
                         back_populates="manages_branch",
                         foreign_keys=[manager_id],
                         uselist=False
                       )

    users             = relationship(
                         "UserDetails",
                         back_populates="branch",
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

    add_user        = Column(Boolean, default=False)
    edit_user       = Column(Boolean, default=False)
    delete_user     = Column(Boolean, default=False)

    add_lead        = Column(Boolean, default=False)
    edit_lead       = Column(Boolean, default=False)
    delete_lead     = Column(Boolean, default=False)

    view_users      = Column(Boolean, default=False)
    view_lead       = Column(Boolean, default=False)
    view_branch     = Column(Boolean, default=False)
    view_accounts   = Column(Boolean, default=False)
    view_research   = Column(Boolean, default=False)
    view_client     = Column(Boolean, default=False)
    view_payment    = Column(Boolean, default=False)
    view_invoice    = Column(Boolean, default=False)
    view_kyc        = Column(Boolean, default=False)

    approval        = Column(Boolean, default=False)
    internal_mailing= Column(Boolean, default=False)
    chatting        = Column(Boolean, default=False)
    targets         = Column(Boolean, default=False)
    reports         = Column(Boolean, default=False)
    fetch_lead      = Column(Boolean, default=False)

    user            = relationship("UserDetails", back_populates="permission")


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


class Payment(Base):
    __tablename__ = "crm_payment"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    lead_id        = Column(Integer, ForeignKey("crm_lead.id"), nullable=False)
    user_id        = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=False)
    timestamp      = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    raised_by      = Column(String(100), nullable=False)
    payment_amount = Column(Float, nullable=False)
    mode           = Column(String(50), nullable=False)
    status         = Column(String(50), nullable=False)
    invoice        = Column(String(255), nullable=True)
    description    = Column(Text, nullable=True)
    transaction_id = Column(String(100), nullable=True)
    utr            = Column(String(100), nullable=True)

    lead           = relationship("Lead", back_populates="payments")
    user           = relationship("UserDetails")


class Lead(Base):
    __tablename__ = "crm_lead"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    full_name         = Column(String(100), nullable=False)
    father_name       = Column(String(100), nullable=True)
    email             = Column(String(100), nullable=False, index=True)
    mobile            = Column(String(20), nullable=False, index=True)
    alternate_mobile  = Column(String(20), nullable=True)
    aadhaar           = Column(String(12), nullable=True)
    pan               = Column(String(10), nullable=True)
    gstin             = Column(String(15), nullable=True)

    state             = Column(String(100), nullable=False)
    city              = Column(String(100), nullable=False)
    district          = Column(String(100), nullable=True)
    address           = Column(Text, nullable=True)

    dob               = Column(Date, nullable=True)
    occupation        = Column(String(100), nullable=True)
    segment           = Column(ARRAY(String), nullable=True)
    experience        = Column(String(50), nullable=True)
    investment        = Column(String(50), nullable=True)

    lead_response_id  = Column(Integer, ForeignKey("crm_lead_response.id"), nullable=False)
    lead_source_id    = Column(Integer, ForeignKey("crm_lead_source.id"), nullable=False)

    created_by        = Column(String(100), nullable=True)
    created_by_name   = Column(String(100), nullable=True)
    comment           = Column(JSON, nullable=True)

    aadhar_front_pic  = Column(String(255), nullable=True)
    aadhar_back_pic   = Column(String(255), nullable=True)
    pan_pic           = Column(String(255), nullable=True)
    kyc               = Column(Boolean, default=False)
    kyc_id            = Column(Integer, nullable=True)

    is_old_lead       = Column(Boolean, default=False)
    call_back_date    = Column(DateTime, nullable=True)
    lead_status       = Column(String(50), nullable=True)

    created_at        = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    branch_id         = Column(Integer, ForeignKey("crm_branch_details.id"), nullable=True)

    branch            = relationship("BranchDetails", back_populates="leads")
    payments          = relationship("Payment", back_populates="lead", cascade="all, delete-orphan")
    stories           = relationship("LeadStory", back_populates="lead", cascade="all, delete-orphan")
    lead_source       = relationship("LeadSource", back_populates="leads")
    lead_response     = relationship("LeadResponse", back_populates="leads")


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

