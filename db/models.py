# db/models.py - Complete Fixed Version without manager_id

from sqlalchemy import (
    Column, Integer, String, Text, Date, DateTime, Float, Boolean,
    JSON, ARRAY, ForeignKey, func, Enum, Enum as SAEnum, text
)
from sqlalchemy.orm import relationship
from db.connection import Base
import uuid
import enum
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime


class UserRoleEnum(str, enum.Enum):
    SUPERADMIN = "SUPERADMIN"
    COMPLIANCE = "COMPLIANCE"
    BRANCH_MANAGER = "BRANCH MANAGER"
    HR = "HR"
    SALES_MANAGER = "SALES MANAGER"
    TL = "TL"  # Team Leader
    SBA = "SBA"  # Senior Business Associate
    BA = "BA"  # Business Associate
    RESEARCHER = "RESEARCHER"
     

class RecommendationType(str, enum.Enum):
    equity_cash= "Equity Cash"
    stock_future= "Stock Future"
    index_future= "Index Future"
    index_option= "Index Option"
    stock_option= "Stock Option"
    mcx_bullion= "MCX Bullion"
    mcx_base_metal= "MCX Base Metal"
    mcx_energy= "MCX Energy"
    
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

    # LEAD/[id]
    lead_recording_view = Column(Boolean, default=False)
    lead_recording_upload   = Column(Boolean, default=False)
    lead_story_view = Column(Boolean, default=False)
    lead_transfer = Column(Boolean, default=False)

    # LEAD SOURCE
    create_lead = Column(Boolean, default=False)
    edit_lead = Column(Boolean, default=False)
    delete_lead  = Column(Boolean, default=False)

    # LEAD RESPONSE
    create_new_lead_response  = Column(Boolean, default=False)
    edit_response = Column(Boolean, default=False)
    delete_response = Column(Boolean, default=False)

    # USER 
    user_add_user = Column(Boolean, default=False)
    user_all_roles = Column(Boolean, default=False)
    user_all_branches = Column(Boolean, default=False)
    user_view_user_details = Column(Boolean, default=False)
    user_edit_user = Column(Boolean, default=False)
    user_delete_user = Column(Boolean, default=False)

    # FETCH LIMIT
    fetch_limit_create_new = Column(Boolean, default=False)
    fetch_limit_edit = Column(Boolean, default=False)
    fetch_limit_delete = Column(Boolean, default=False)

    # PLANS
    plans_create = Column(Boolean, default=False)
    edit_plan = Column(Boolean, default=False)
    delete_plane = Column(Boolean, default=False)

    # CLIENT
    client_select_branch = Column(Boolean, default=False)
    client_invoice = Column(Boolean, default=False)
    client_story = Column(Boolean, default=False)
    client_comments = Column(Boolean, default=False)

    # SIDEBAR
    lead_manage_page = Column(Boolean, default=False)
    plane_page = Column(Boolean, default=False)
    attandance_page = Column(Boolean, default=False)
    client_page = Column(Boolean, default=False)
    lead_source_page = Column(Boolean, default=False)
    lead_response_page = Column(Boolean, default=False)
    user_page = Column(Boolean, default=False)
    permission_page = Column(Boolean, default=False)
    lead_upload_page = Column(Boolean, default=False)
    fetch_limit_page = Column(Boolean, default=False)

    # MESSANGER
    rational_download = Column(Boolean, default=False)
    rational_pdf_model_download = Column(Boolean, default=False)
    rational_pdf_model_view = Column(Boolean, default=False)
    rational_graf_model_view = Column(Boolean, default=False)
    rational_status = Column(Boolean, default=False)
    rational_edit = Column(Boolean, default=False)
    rational_add_recommadation = Column(Boolean, default=False)

    # EMAIL
    email_add = Column(Boolean, default=False)
    email_edit = Column(Boolean, default=False)
    email_delete = Column(Boolean, default=False)
    email_preview_template = Column(Boolean, default=False)

    # SMS
    sms_add = Column(Boolean, default=False)
    sms_edit = Column(Boolean, default=False)
    sms_delete = Column(Boolean, default=False)

    # BRANCH
    branch_add = Column(Boolean, default=False)
    branch_edit = Column(Boolean, default=False)
    branch_details = Column(Boolean, default=False)
    branch_agreement_view = Column(Boolean, default=False)

    user            = relationship("UserDetails", back_populates="permission")

    @classmethod
    def get_default_permissions(cls, role: UserRoleEnum):
        """Get default permissions based on user role"""
        permissions = {
            UserRoleEnum.SUPERADMIN: {
                'lead_recording_view' : True,
                'lead_recording_upload': True,
                'lead_story_view' : True,
                'lead_transfer' : True,

                # LEAD SOURCE
                'create_lead' : True,
                'edit_lead' : True,
                'delete_lead'  : True,

                # LEAD RESPONSE
                'create_new_lead_response'  : True,
                'edit_response' : True,
                'delete_response' : True,

                # USER 
                'user_add_user' : True,
                'user_all_roles' : True,
                'user_all_branches' : True,
                'user_view_user_details' : True,
                'user_edit_user' : True,
                'user_delete_user' : True,

                # FETCH LIMIT
                'fetch_limit_create_new' : True,
                'fetch_limit_edit' : True,
                'fetch_limit_delete' : True,

                # PLANS
                'plans_create' : True,
                'edit_plan' : True,
                'delete_plane' : True,

                # CLIENT
                'client_select_branch' : True,
                'client_invoice' : True,
                'client_story' : True,
                'client_comments' : True,

                # SIDEBAR
                'lead_manage_page' : True,
                'plane_page' : True,
                'attandance_page' : True,
                'client_page' : True,
                'lead_source_page' : True,
                'lead_response_page' : True,
                'user_page' : True,
                'permission_page' : True,
                'lead_upload_page' : True,
                'fetch_limit_page' : True,

                # MESSANGER
                'rational_download' : True,
                'rational_pdf_model_download' : True,
                'rational_pdf_model_view' : True,
                'rational_graf_model_view' : True,
                'rational_status' : True,
                'rational_edit' : True,
                'rational_add_recommadation' : True,

                # EMAIL
                'email_add' : True,
                'email_edit' : True,
                'email_delete' : True,
                'email_preview_template' : True,

                # SMS
                'sms_add' : True,
                'sms_edit' : True,
                'sms_delete' : True,

                # BRANCH
                'branch_add' : True,
                'branch_edit' : True,
                'branch_details' : True,
                'branch_agreement_view' : True

            },
            UserRoleEnum.BRANCH_MANAGER: {
                # LEAD/[id]
                'lead_recording_view' : True, 'lead_recording_upload': False,
                'lead_story_view' : True, 'lead_transfer' : False,

                # LEAD SOURCE
                'create_lead' : True, 'edit_lead' : True, 'delete_lead'  : False,

                # LEAD RESPONSE
                'create_new_lead_response' : False, 'edit_response' : False, 'delete_response' : False,

                # USER 
                'user_add_user' : True, 'user_all_roles' : False, 'user_all_branches' : False,
                'user_view_user_details' : True, 'user_edit_user' : True, 'user_delete_user' : False,

                # FETCH LIMIT
                'fetch_limit_create_new' : True, 'fetch_limit_edit' : True, 'fetch_limit_delete' : True,

                # PLANS
                'plans_create' : False, 'edit_plan' : False, 'delete_plane' : False,

                # CLIENT
                'client_select_branch' : False, 'client_invoice' : True, 'client_story' : True, 'client_comments' : True,

                # SIDEBAR
                'lead_manage_page' : True, 'plane_page' : True, 'attandance_page' : True,
                'client_page' : True, 'lead_source_page' : True, 'lead_response_page' : True,
                'user_page' : True, 'permission_page' : False, 'lead_upload_page' : True, 'fetch_limit_page' : False,

                # MESSANGER
                'rational_download' : False, 'rational_pdf_model_download' : False, 'rational_pdf_model_view' : False,
                'rational_graf_model_view' : False, 'rational_status' : False, 'rational_edit' : False, 'rational_add_recommadation' : False,

                # EMAIL
                'email_add' : False, 'email_edit' : False, 'email_delete' : False, 'email_preview_template' : False,

                # SMS
                'sms_add' : False, 'sms_edit' : False, 'sms_delete' : False,

                # BRANCH
                'branch_add' : False, 'branch_edit' : False, 'branch_details' : False, 'branch_agreement_view' : False
            },
            UserRoleEnum.SALES_MANAGER: {
                # LEAD/[id]
                'lead_recording_view' : True, 'lead_recording_upload': False,
                'lead_story_view' : True, 'lead_transfer' : False,

                # LEAD SOURCE
                'create_lead' : True, 'edit_lead' : True, 'delete_lead'  : False,

                # LEAD RESPONSE
                'create_new_lead_response' : False, 'edit_response' : False, 'delete_response' : False,

                # USER 
                'user_add_user' : False, 'user_all_roles' : False, 'user_all_branches' : False,
                'user_view_user_details' : False, 'user_edit_user' : False, 'user_delete_user' : False,

                # FETCH LIMIT
                'fetch_limit_create_new' : False, 'fetch_limit_edit' : False, 'fetch_limit_delete' : False,

                # PLANS
                'plans_create' : False, 'edit_plan' : False, 'delete_plane' : False,

                # CLIENT
                'client_select_branch' : False, 'client_invoice' : True, 'client_story' : True, 'client_comments' : True,

                # SIDEBAR
                'lead_manage_page' : False, 'plane_page' : True, 'attandance_page' : False,
                'client_page' : True, 'lead_source_page' : False, 'lead_response_page' : False,
                'user_page' : False, 'permission_page' : False, 'lead_upload_page' : False, 'fetch_limit_page' : False,

                # MESSANGER
                'rational_download' : False, 'rational_pdf_model_download' : False, 'rational_pdf_model_view' : False,
                'rational_graf_model_view' : False, 'rational_status' : False, 'rational_edit' : False, 'rational_add_recommadation' : False,

                # EMAIL
                'email_add' : False, 'email_edit' : False, 'email_delete' : False, 'email_preview_template' : False,

                # SMS
                'sms_add' : False, 'sms_edit' : False, 'sms_delete' : False,

                # BRANCH
                'branch_add' : False, 'branch_edit' : False, 'branch_details' : False, 'branch_agreement_view' : False
            },
            UserRoleEnum.HR: {
                # LEAD/[id]
                'lead_recording_view' : False, 'lead_recording_upload': False,
                'lead_story_view' : False, 'lead_transfer' : False,

                # LEAD SOURCE
                'create_lead' : False, 'edit_lead' : False, 'delete_lead'  : False,

                # LEAD RESPONSE
                'create_new_lead_response' : False, 'edit_response' : False, 'delete_response' : False,

                # USER 
                'user_add_user' : True, 'user_all_roles' : False, 'user_all_branches' : False,
                'user_view_user_details' : True, 'user_edit_user' : True, 'user_delete_user' : False,

                # FETCH LIMIT
                'fetch_limit_create_new' : False, 'fetch_limit_edit' : False, 'fetch_limit_delete' : False,

                # PLANS
                'plans_create' : False, 'edit_plan' : False, 'delete_plane' : False,

                # CLIENT
                'client_select_branch' : False, 'client_invoice' : False, 'client_story' : False, 'client_comments' : False,

                # SIDEBAR
                'lead_manage_page' : False, 'plane_page' : False, 'attandance_page' : True,
                'client_page' : False, 'lead_source_page' : False, 'lead_response_page' : False,
                'user_page' : True, 'permission_page' : False, 'lead_upload_page' : False, 'fetch_limit_page' : False,

                # MESSANGER
                'rational_download' : False, 'rational_pdf_model_download' : False, 'rational_pdf_model_view' : False,
                'rational_graf_model_view' : False, 'rational_status' : False, 'rational_edit' : False, 'rational_add_recommadation' : False,

                # EMAIL
                'email_add' : False, 'email_edit' : False, 'email_delete' : False, 'email_preview_template' : False,

                # SMS
                'sms_add' : False, 'sms_edit' : False, 'sms_delete' : False,

                # BRANCH
                'branch_add' : False, 'branch_edit' : False, 'branch_details' : False, 'branch_agreement_view' : False
            },
            UserRoleEnum.TL: {
                 # LEAD/[id]
                'lead_recording_view' : True, 'lead_recording_upload': False,
                'lead_story_view' : True, 'lead_transfer' : False,

                # LEAD SOURCE
                'create_lead' : True, 'edit_lead' : True, 'delete_lead'  : False,

                # LEAD RESPONSE
                'create_new_lead_response' : False, 'edit_response' : False, 'delete_response' : False,

                # USER 
                'user_add_user' : False, 'user_all_roles' : False, 'user_all_branches' : False,
                'user_view_user_details' : False, 'user_edit_user' : False, 'user_delete_user' : False,

                # FETCH LIMIT
                'fetch_limit_create_new' : False, 'fetch_limit_edit' : False, 'fetch_limit_delete' : False,

                # PLANS
                'plans_create' : False, 'edit_plan' : False, 'delete_plane' : False,

                # CLIENT
                'client_select_branch' : False, 'client_invoice' : True, 'client_story' : True, 'client_comments' : True,

                # SIDEBAR
                'lead_manage_page' : False, 'plane_page' : True, 'attandance_page' : False,
                'client_page' : True, 'lead_source_page' : False, 'lead_response_page' : False,
                'user_page' : False, 'permission_page' : False, 'lead_upload_page' : False, 'fetch_limit_page' : False,

                # MESSANGER
                'rational_download' : False, 'rational_pdf_model_download' : False, 'rational_pdf_model_view' : False,
                'rational_graf_model_view' : False, 'rational_status' : False, 'rational_edit' : False, 'rational_add_recommadation' : False,

                # EMAIL
                'email_add' : False, 'email_edit' : False, 'email_delete' : False, 'email_preview_template' : False,

                # SMS
                'sms_add' : False, 'sms_edit' : False, 'sms_delete' : False,

                # BRANCH
                'branch_add' : False, 'branch_edit' : False, 'branch_details' : False, 'branch_agreement_view' : False
            },
            UserRoleEnum.SBA: {
                 # LEAD/[id]
                'lead_recording_view' : True, 'lead_recording_upload': False,
                'lead_story_view' : True, 'lead_transfer' : False,

                # LEAD SOURCE
                'create_lead' : True, 'edit_lead' : True, 'delete_lead'  : False,

                # LEAD RESPONSE
                'create_new_lead_response' : False, 'edit_response' : False, 'delete_response' : False,

                # USER 
                'user_add_user' : False, 'user_all_roles' : False, 'user_all_branches' : False,
                'user_view_user_details' : False, 'user_edit_user' : False, 'user_delete_user' : False,

                # FETCH LIMIT
                'fetch_limit_create_new' : False, 'fetch_limit_edit' : False, 'fetch_limit_delete' : False,

                # PLANS
                'plans_create' : False, 'edit_plan' : False, 'delete_plane' : False,

                # CLIENT
                'client_select_branch' : False, 'client_invoice' : True, 'client_story' : True, 'client_comments' : True,

                # SIDEBAR
                'lead_manage_page' : False, 'plane_page' : True, 'attandance_page' : False,
                'client_page' : True, 'lead_source_page' : False, 'lead_response_page' : False,
                'user_page' : False, 'permission_page' : False, 'lead_upload_page' : False, 'fetch_limit_page' : False,

                # MESSANGER
                'rational_download' : False, 'rational_pdf_model_download' : False, 'rational_pdf_model_view' : False,
                'rational_graf_model_view' : False, 'rational_status' : False, 'rational_edit' : False, 'rational_add_recommadation' : False,

                # EMAIL
                'email_add' : False, 'email_edit' : False, 'email_delete' : False, 'email_preview_template' : False,

                # SMS
                'sms_add' : False, 'sms_edit' : False, 'sms_delete' : False,

                # BRANCH
                'branch_add' : False, 'branch_edit' : False, 'branch_details' : False, 'branch_agreement_view' : False
                },
            UserRoleEnum.BA: {
                 # LEAD/[id]
                'lead_recording_view' : True, 'lead_recording_upload': False,
                'lead_story_view' : True, 'lead_transfer' : False,

                # LEAD SOURCE
                'create_lead' : True, 'edit_lead' : True, 'delete_lead'  : False,

                # LEAD RESPONSE
                'create_new_lead_response' : False, 'edit_response' : False, 'delete_response' : False,

                # USER 
                'user_add_user' : False, 'user_all_roles' : False, 'user_all_branches' : False,
                'user_view_user_details' : False, 'user_edit_user' : False, 'user_delete_user' : False,

                # FETCH LIMIT
                'fetch_limit_create_new' : False, 'fetch_limit_edit' : False, 'fetch_limit_delete' : False,

                # PLANS
                'plans_create' : False, 'edit_plan' : False, 'delete_plane' : False,

                # CLIENT
                'client_select_branch' : False, 'client_invoice' : True, 'client_story' : True, 'client_comments' : True,

                # SIDEBAR
                'lead_manage_page' : False, 'plane_page' : True, 'attandance_page' : False,
                'client_page' : True, 'lead_source_page' : False, 'lead_response_page' : False,
                'user_page' : False, 'permission_page' : False, 'lead_upload_page' : False, 'fetch_limit_page' : False,

                # MESSANGER
                'rational_download' : False, 'rational_pdf_model_download' : False, 'rational_pdf_model_view' : False,
                'rational_graf_model_view' : False, 'rational_status' : False, 'rational_edit' : False, 'rational_add_recommadation' : False,

                # EMAIL
                'email_add' : False, 'email_edit' : False, 'email_delete' : False, 'email_preview_template' : False,

                # SMS
                'sms_add' : False, 'sms_edit' : False, 'sms_delete' : False,

                # BRANCH
                'branch_add' : False, 'branch_edit' : False, 'branch_details' : False, 'branch_agreement_view' : False
            },
            UserRoleEnum.RESEARCHER: {
                # LEAD/[id]
                'lead_recording_view' : False, 'lead_recording_upload': False,
                'lead_story_view' : False, 'lead_transfer' : False,

                # LEAD SOURCE
                'create_lead' : False, 'edit_lead' : False, 'delete_lead'  : False,

                # LEAD RESPONSE
                'create_new_lead_response' : False, 'edit_response' : False, 'delete_response' : False,

                # USER 
                'user_add_user' : False, 'user_all_roles' : False, 'user_all_branches' : False,
                'user_view_user_details' : False, 'user_edit_user' : False, 'user_delete_user' : False,

                # FETCH LIMIT
                'fetch_limit_create_new' : False, 'fetch_limit_edit' : False, 'fetch_limit_delete' : False,

                # PLANS
                'plans_create' : False, 'edit_plan' : False, 'delete_plane' : False,

                # CLIENT
                'client_select_branch' : False, 'client_invoice' : False, 'client_story' : False, 'client_comments' : False,

                # SIDEBAR
                'lead_manage_page' : False, 'plane_page' : False, 'attandance_page' : False,
                'client_page' : False, 'lead_source_page' : False, 'lead_response_page' : False,
                'user_page' : False, 'permission_page' : False, 'lead_upload_page' : False, 'fetch_limit_page' : False,

                # MESSANGER
                'rational_download' : False, 'rational_pdf_model_download' : False, 'rational_pdf_model_view' : False,
                'rational_graf_model_view' : True, 'rational_status' : True, 'rational_edit' : True, 'rational_add_recommadation' : True,

                # EMAIL
                'email_add' : False, 'email_edit' : False, 'email_delete' : False, 'email_preview_template' : False,

                # SMS
                'sms_add' : False, 'sms_edit' : False, 'sms_delete' : False,

                # BRANCH
                'branch_add' : False, 'branch_edit' : False, 'branch_details' : False, 'branch_agreement_view' : False
            },
            UserRoleEnum.COMPLIANCE: {
                # LEAD/[id]
                'lead_recording_view' : True, 'lead_recording_upload': True,
                'lead_story_view' : False, 'lead_transfer' : False,

                # LEAD SOURCE
                'create_lead' : False, 'edit_lead' : False, 'delete_lead'  : False,

                # LEAD RESPONSE
                'create_new_lead_response' : False, 'edit_response' : False, 'delete_response' : False,

                # USER 
                'user_add_user' : False, 'user_all_roles' : False, 'user_all_branches' : False,
                'user_view_user_details' : False, 'user_edit_user' : False, 'user_delete_user' : False,

                # FETCH LIMIT
                'fetch_limit_create_new' : False, 'fetch_limit_edit' : False, 'fetch_limit_delete' : False,

                # PLANS
                'plans_create' : False, 'edit_plan' : False, 'delete_plane' : False,

                # CLIENT
                'client_select_branch' : False, 'client_invoice' : False, 'client_story' : False, 'client_comments' : False,

                # SIDEBAR
                'lead_manage_page' : False, 'plane_page' : False, 'attandance_page' : False,
                'client_page' : False, 'lead_source_page' : False, 'lead_response_page' : False,
                'user_page' : False, 'permission_page' : False, 'lead_upload_page' : False, 'fetch_limit_page' : False,

                # MESSANGER
                'rational_download' : False, 'rational_pdf_model_download' : False, 'rational_pdf_model_view' : False,
                'rational_graf_model_view' : False, 'rational_status' : False, 'rational_edit' : False, 'rational_add_recommadation' : False,

                # EMAIL
                'email_add' : False, 'email_edit' : False, 'email_delete' : False, 'email_preview_template' : False,

                # SMS
                'sms_add' : False, 'sms_edit' : False, 'sms_delete' : False,

                # BRANCH
                'branch_add' : False, 'branch_edit' : False, 'branch_details' : False, 'branch_agreement_view' : False
            }
        }
        return permissions.get(role, {})


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
    role              = Column(Enum(UserRoleEnum), nullable=True)
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
    name             = Column(String(100), nullable=False)
    email            = Column(String(100), nullable=False)
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
    recipient_phone_number = Column(String(320), nullable=False, index=True)
    body = Column(Text, nullable=False)
    status = Column(String(50), nullable=True)
    sent_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    user_id = Column(String(50), nullable=False, index=True)

    template = relationship("SMSTemplate", back_populates="logs")

class EmailLog(Base):
    __tablename__ = "crm_email_logs"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    template_id     = Column(Integer, ForeignKey("crm_email_templates.id"), nullable=False)
    recipient_email = Column(String(320), nullable=False, index=True)
    subject         = Column(String(200), nullable=False)
    body            = Column(Text, nullable=False)
    user_id         = Column(String(50), nullable=False, index=True)
    sent_at         = Column(DateTime, nullable=False, default=datetime.utcnow)

    template = relationship("EmailTemplate", back_populates="logs")

# also add back‑ref on EmailTemplate:
EmailTemplate.logs = relationship(
    "EmailLog", order_by=EmailLog.sent_at.desc(), back_populates="template"
)

