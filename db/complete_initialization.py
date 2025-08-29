# db/complete_initialization.py
"""
Single function to initialize everything - Departments, ProfileRoles, and Admin user
"""

import logging
from datetime import date
from typing import List, Dict

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

from db.connection import engine
from db.models import (
    Base,
    Department,
    ProfileRole,
    UserDetails,
    PermissionDetails,
)

from passlib.context import CryptContext

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ----------------------------- Helpers -----------------------------

def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    return pwd_context.hash(password)


def enum_permissions() -> List[str]:
    """All canonical permission strings from the PermissionDetails Enum."""
    return [p.value for p in PermissionDetails]


def validate_permissions(values: List[str]) -> List[str]:
    """Keep only valid permissions; drop anything not in the Enum."""
    valid = set(enum_permissions())
    out = [v for v in (values or []) if v in valid]
    if len(out) != len(values or []):
        dropped = list(set(values or []) - valid)
        logger.warning(f"Dropping invalid permissions (not in Enum): {dropped}")
    # de-dupe while preserving order
    seen = set()
    deduped = []
    for p in out:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    return deduped


def get_role_permissions(role_name: str) -> List[str]:
    """
    Your curated TRUE permissions per role.
    These are validated against the Enum to avoid typos/drift.
    """
    role_permissions: Dict[str, List[str]] = {
        "SUPERADMIN": [
            # FULL access list (kept for readability), but will be validated anyway
            'lead_recording_view', 'lead_recording_upload', 'lead_story_view', 'lead_transfer', 'lead_branch_view',
            'header_global_search', 'create_lead', 'edit_lead', 'delete_lead', 'create_new_lead_response',
            'edit_response', 'delete_response', 'user_add_user', 'user_all_roles', 'user_all_branches',
            'user_view_user_details', 'user_edit_user', 'user_delete_user', 'fetch_limit_create_new',
            'fetch_limit_edit', 'fetch_limit_delete', 'plans_create', 'edit_plan', 'delete_plane',
            'client_select_branch', 'client_invoice', 'client_story', 'client_comments', 'lead_manage_page',
            'plane_page', 'attandance_page', 'client_page', 'lead_source_page', 'lead_response_page',
            'user_page', 'permission_page', 'lead_upload_page', 'fetch_limit_page', 'add_lead_page',
            'payment_page', 'messanger_page', 'template', 'sms_page', 'email_page', 'branch_page',
            'old_lead_page', 'new_lead_page', 'rational_download', 'rational_pdf_model_download',
            'rational_pdf_model_view', 'rational_graf_model_view', 'rational_status', 'rational_edit',
            'rational_add_recommadation', 'email_add_temp', 'email_edit_temp', 'email_delete_temp',
            'email_view_temp', 'sms_add', 'sms_edit', 'sms_delete', 'branch_add', 'branch_edit',
            'branch_details', 'branch_agreement_view'
        ],

        "BRANCH_MANAGER": [
            'lead_recording_view', 'lead_story_view', 'header_global_search', 'create_lead', 'edit_lead',
            'user_add_user', 'user_view_user_details', 'user_edit_user', 'fetch_limit_create_new',
            'fetch_limit_edit', 'fetch_limit_delete', 'client_invoice', 'client_story', 'client_comments',
            'lead_manage_page', 'plane_page', 'attandance_page', 'client_page', 'lead_source_page',
            'lead_response_page', 'user_page', 'lead_upload_page', 'add_lead_page', 'payment_page',
            'old_lead_page', 'new_lead_page'
        ],

        "SALES_MANAGER": [
            'lead_recording_view', 'lead_story_view', 'header_global_search', 'create_lead', 'edit_lead',
            'client_invoice', 'client_story', 'client_comments', 'plane_page', 'client_page',
            'add_lead_page', 'old_lead_page', 'new_lead_page'
        ],

        "HR": [
            'header_global_search', 'user_add_user', 'user_view_user_details', 'user_edit_user',
            'attandance_page', 'user_page'
        ],

        "TL": [
            'lead_recording_view', 'lead_story_view', 'header_global_search', 'create_lead', 'edit_lead',
            'client_invoice', 'client_story', 'client_comments', 'plane_page', 'client_page',
            'add_lead_page', 'old_lead_page', 'new_lead_page'
        ],

        "SBA": [
            'lead_recording_view', 'lead_story_view', 'header_global_search', 'create_lead', 'edit_lead',
            'client_invoice', 'client_story', 'client_comments', 'plane_page', 'client_page',
            'add_lead_page', 'old_lead_page', 'new_lead_page'
        ],

        "BA": [
            'lead_recording_view', 'lead_story_view', 'header_global_search', 'create_lead', 'edit_lead',
            'client_invoice', 'client_story', 'client_comments', 'plane_page', 'client_page',
            'add_lead_page', 'old_lead_page', 'new_lead_page'
        ],

        "RESEARCHER": [
            'messanger_page', 'rational_graf_model_view', 'rational_status', 'rational_edit',
            'rational_add_recommadation'
        ],

        "COMPLIANCE_OFFICER": [
            'lead_recording_view', 'lead_recording_upload'
        ],

        "ACCOUNTANT": [
            'client_invoice', 'payment_page', 'client_page'
        ],
    }

    # SUPERADMIN → better to grant ALL enum permissions, not just the list
    if role_name == "SUPERADMIN":
        return enum_permissions()

    return validate_permissions(role_permissions.get(role_name, []))


def upsert_department(db: Session, name: str, description: str, available_permissions: List[str]) -> Department:
    """Create/update a Department and return it."""
    perms = validate_permissions(available_permissions)
    dept = db.query(Department).filter_by(name=name).first()
    if dept:
        # update available permissions if changed
        if sorted(dept.available_permissions or []) != sorted(perms):
            dept.available_permissions = perms
            db.flush()
        return dept

    dept = Department(
        name=name,
        description=description,
        available_permissions=perms
    )
    db.add(dept)
    db.flush()
    return dept


def upsert_profile_role(
    db: Session,
    name: str,
    department_id: int,
    hierarchy_level: int,
    default_permissions: List[str],
    description: str,
) -> ProfileRole:
    """Create/update a ProfileRole and return it."""
    perms = validate_permissions(default_permissions)
    pr = db.query(ProfileRole).filter_by(name=name).first()
    if pr:
        updated = False
        if pr.department_id != department_id:
            pr.department_id = department_id
            updated = True
        if pr.hierarchy_level != hierarchy_level:
            pr.hierarchy_level = hierarchy_level
            updated = True
        if sorted(pr.default_permissions or []) != sorted(perms):
            pr.default_permissions = perms
            updated = True
        if (pr.description or "") != (description or ""):
            pr.description = description
            updated = True
        if updated:
            db.flush()
        return pr

    pr = ProfileRole(
        name=name,
        department_id=department_id,
        hierarchy_level=hierarchy_level,
        default_permissions=perms,
        description=description,
        is_active=True,
    )
    db.add(pr)
    db.flush()
    return pr


def upsert_admin_user(db: Session, superadmin_role: ProfileRole, admin_dept_id: int) -> UserDetails:
    """
    Create or update ADMIN001 with SUPERADMIN role and ALL permissions.
    """
    admin_code = "ADMIN001"
    admin_email = "admin@company.com"
    full_perms = enum_permissions()

    user = db.query(UserDetails).filter_by(employee_code=admin_code).first()
    if user:
        # Ensure correct role and permissions; fill essential fields if missing
        user.role_id = superadmin_role.id
        user.department_id = admin_dept_id
        user.is_active = True
        user.permissions = full_perms

        user.email = user.email or admin_email
        user.name = user.name or "SUPERADMIN"
        user.father_name = user.father_name or "System"
        user.phone_number = user.phone_number or "9999999999"
        user.address = user.address or "System Address"
        user.city = user.city or "System City"
        user.state = user.state or "System State"
        user.pincode = user.pincode or "000000"
        user.comment = user.comment or "Auto-updated super admin user"
        db.flush()
        return user

    # fresh user
    user = UserDetails(
        employee_code=admin_code,
        phone_number="9999999999",
        email=admin_email,
        name="SUPERADMIN",
        password=hash_password("admin123"),
        role_id=superadmin_role.id,
        department_id=admin_dept_id,
        father_name="System",
        is_active=True,
        experience=0.0,
        date_of_joining=date.today(),
        date_of_birth=date(1990, 1, 1),
        permissions=full_perms,
    )
    db.add(user)
    db.flush()
    return user


# ----------------------------- Main initializer -----------------------------

def initialize_complete_system() -> bool:
    """
    Complete initialization function:
      1) Create tables
      2) Create Departments (with validated available_permissions)
      3) Create ProfileRoles (with validated default_permissions)
      4) Create/Update Super Admin user (ADMIN001) with ALL permissions
    """
    try:
        # Ensure tables exist
        Base.metadata.create_all(bind=engine)
        logger.info("DB tables verified.")

        with Session(engine) as db:
            logger.info("Starting complete system initialization...")

            # STEP 1: Departments
            logger.info("Step 1: Creating/updating departments...")
            departments = {}

            departments["ADMIN"] = upsert_department(
                db,
                name="ADMIN",
                description="Administrative Department",
                available_permissions=get_role_permissions("SUPERADMIN"),  # admin dept: all perms
            )

            departments["ACCOUNTING"] = upsert_department(
                db,
                name="ACCOUNTING",
                description="Accounting Department",
                available_permissions=get_role_permissions("ACCOUNTANT"),
            )

            departments["HR"] = upsert_department(
                db,
                name="HR",
                description="Human Resources Department",
                available_permissions=get_role_permissions("HR"),
            )

            sales_team_perms = list(set(
                get_role_permissions("SALES_MANAGER")
                + get_role_permissions("TL")
                + get_role_permissions("SBA")
                + get_role_permissions("BA")
            ))
            departments["SALES_TEAM"] = upsert_department(
                db,
                name="SALES_TEAM",
                description="Sales Team Department",
                available_permissions=sales_team_perms,
            )

            departments["RESEARCH_TEAM"] = upsert_department(
                db,
                name="RESEARCH_TEAM",
                description="Research Team Department",
                available_permissions=get_role_permissions("RESEARCHER"),
            )

            departments["COMPLIANCE_TEAM"] = upsert_department(
                db,
                name="COMPLIANCE_TEAM",
                description="Compliance Team Department",
                available_permissions=get_role_permissions("COMPLIANCE_OFFICER"),
            )

            db.commit()
            logger.info(f"Departments created/updated: {len(departments)}")

            # STEP 2: Profile Roles
            logger.info("Step 2: Creating/updating profile roles...")

            roles_to_create = [
                ("SUPERADMIN",        "ADMIN",            1, "Super Administrator with full access"),
                ("BRANCH_MANAGER",    "ADMIN",            2, "Branch Manager"),
                ("HR",                "HR",               3, "Human Resources"),
                ("ACCOUNTANT",        "ACCOUNTING",       3, "Accountant"),
                ("SALES_MANAGER",     "SALES_TEAM",       3, "Sales Manager"),
                ("TL",                "SALES_TEAM",       4, "Team Leader"),
                ("SBA",               "SALES_TEAM",       5, "Senior Business Associate"),
                ("BA",                "SALES_TEAM",       6, "Business Associate"),
                ("RESEARCHER",        "RESEARCH_TEAM",    4, "Research Analyst"),
                ("COMPLIANCE_OFFICER","COMPLIANCE_TEAM",  3, "Compliance Officer"),
            ]

            superadmin_profile = None
            for role_name, dept_key, level, desc in roles_to_create:
                pr = upsert_profile_role(
                    db,
                    name=role_name,
                    department_id=departments[dept_key].id,
                    hierarchy_level=level,
                    default_permissions=get_role_permissions(role_name),
                    description=desc,
                )
                if role_name == "SUPERADMIN":
                    superadmin_profile = pr
                logger.info(f"Profile ensured: {role_name} (dept={dept_key}, level={level})")

            if not superadmin_profile:
                # Should not happen, but guard anyway
                superadmin_profile = db.query(ProfileRole).filter_by(name="SUPERADMIN").first()

            db.commit()

            # STEP 3: Admin user
            logger.info("Step 3: Creating/updating super admin user...")
            admin_user = upsert_admin_user(db, superadmin_profile, departments["ADMIN"].id)
            db.commit()

            logger.info("Super admin user ensured.")
            logger.info("Login Details:")
            logger.info(f"Employee Code: {admin_user.employee_code}")
            logger.info(f"Email: {admin_user.email}")
            logger.info("Password: admin123 (change after first login)")

            # Summary
            logger.info("\n" + "=" * 50)
            logger.info("SYSTEM INITIALIZATION COMPLETE!")
            logger.info("=" * 50)
            logger.info(f"Departments ensured: {len(departments)}")
            logger.info(f"Profile Roles ensured: {len(roles_to_create)}")
            logger.info("Admin user: Created/updated")
            logger.info("\nAdmin Login:")
            logger.info("Employee Code: ADMIN001")
            logger.info("Email: admin@company.com")
            logger.info("Password: admin123")
            logger.info("=" * 50)

            return True

    except Exception as e:
        logger.error(f"System initialization failed: {str(e)}")
        return False


# Simple function to call from main.py
def setup_complete_system():
    """Simple wrapper function to call from main.py"""
    return initialize_complete_system()
