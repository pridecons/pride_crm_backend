# db/complete_initialization.py
"""
Single function to initialize everything - Departments, ProfileRoles, and Admin user
"""
import logging
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from db.connection import engine
from db.models import Department, ProfileRole, UserDetails
from passlib.context import CryptContext
from datetime import date

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    return pwd_context.hash(password)

def get_role_permissions(role_name: str) -> list[str]:
    """Get TRUE permissions for each role based on the document provided"""
    
    role_permissions = {
        "SUPERADMIN": [
            # All TRUE permissions from document
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
            # Only TRUE permissions from document
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
        ]
    }
    
    return role_permissions.get(role_name, [])

def initialize_complete_system():
    """
    Complete initialization function:
    1. Create Departments with permissions
    2. Create ProfileRoles with role-based permissions
    3. Create Super Admin user
    """
    
    try:
        with Session(engine) as db:
            logger.info("Starting complete system initialization...")
            
            # STEP 1: Create Departments
            logger.info("Step 1: Creating departments...")
            
            departments_data = [
                {
                    "name": "ADMIN",
                    "description": "Administrative Department",
                    "available_permissions": get_role_permissions("SUPERADMIN")  # Admin dept gets all permissions
                },
                {
                    "name": "ACCOUNTING", 
                    "description": "Accounting Department",
                    "available_permissions": get_role_permissions("ACCOUNTANT")
                },
                {
                    "name": "HR",
                    "description": "Human Resources Department",
                    "available_permissions": get_role_permissions("HR")
                },
                {
                    "name": "SALES_TEAM",
                    "description": "Sales Team Department", 
                    "available_permissions": list(set(
                        get_role_permissions("SALES_MANAGER") + 
                        get_role_permissions("TL") + 
                        get_role_permissions("SBA") + 
                        get_role_permissions("BA")
                    ))
                },
                {
                    "name": "RESEARCH_TEAM",
                    "description": "Research Team Department",
                    "available_permissions": get_role_permissions("RESEARCHER")
                },
                {
                    "name": "COMPLIANCE_TEAM", 
                    "description": "Compliance Team Department",
                    "available_permissions": get_role_permissions("COMPLIANCE_OFFICER")
                }
            ]
            
            dept_count = 0
            departments = {}
            
            for dept_data in departments_data:
                existing_dept = db.query(Department).filter_by(name=dept_data["name"]).first()
                if not existing_dept:
                    dept = Department(**dept_data)
                    db.add(dept)
                    db.flush()  # Get ID immediately
                    departments[dept_data["name"]] = dept
                    dept_count += 1
                    logger.info(f"Created department: {dept_data['name']}")
                else:
                    departments[dept_data["name"]] = existing_dept
                    logger.info(f"Department already exists: {dept_data['name']}")
            
            db.commit()
            logger.info(f"Departments created: {dept_count}")
            
            # STEP 2: Create Profile Roles
            logger.info("Step 2: Creating profile roles...")
            
            profiles_data = [
                {
                    "name": "SUPERADMIN",
                    "department_id": departments["ADMIN"].id,
                    "hierarchy_level": 1,
                    "default_permissions": get_role_permissions("SUPERADMIN"),
                    "description": "Super Administrator with full access"
                },
                {
                    "name": "BRANCH_MANAGER", 
                    "department_id": departments["ADMIN"].id,
                    "hierarchy_level": 2,
                    "default_permissions": get_role_permissions("BRANCH_MANAGER"),
                    "description": "Branch Manager"
                },
                {
                    "name": "HR",
                    "department_id": departments["HR"].id,
                    "hierarchy_level": 3,
                    "default_permissions": get_role_permissions("HR"),
                    "description": "Human Resources"
                },
                {
                    "name": "ACCOUNTANT",
                    "department_id": departments["ACCOUNTING"].id,
                    "hierarchy_level": 3,
                    "default_permissions": get_role_permissions("ACCOUNTANT"),
                    "description": "Accountant"
                },
                {
                    "name": "SALES_MANAGER",
                    "department_id": departments["SALES_TEAM"].id,
                    "hierarchy_level": 3,
                    "default_permissions": get_role_permissions("SALES_MANAGER"),
                    "description": "Sales Manager"
                },
                {
                    "name": "TL",
                    "department_id": departments["SALES_TEAM"].id,
                    "hierarchy_level": 4,
                    "default_permissions": get_role_permissions("TL"),
                    "description": "Team Leader"
                },
                {
                    "name": "SBA",
                    "department_id": departments["SALES_TEAM"].id,
                    "hierarchy_level": 5,
                    "default_permissions": get_role_permissions("SBA"),
                    "description": "Senior Business Associate"
                },
                {
                    "name": "BA",
                    "department_id": departments["SALES_TEAM"].id,
                    "hierarchy_level": 6,
                    "default_permissions": get_role_permissions("BA"),
                    "description": "Business Associate"
                },
                {
                    "name": "RESEARCHER",
                    "department_id": departments["RESEARCH_TEAM"].id,
                    "hierarchy_level": 4,
                    "default_permissions": get_role_permissions("RESEARCHER"),
                    "description": "Research Analyst"
                },
                {
                    "name": "COMPLIANCE_OFFICER",
                    "department_id": departments["COMPLIANCE_TEAM"].id,
                    "hierarchy_level": 3,
                    "default_permissions": get_role_permissions("COMPLIANCE_OFFICER"),
                    "description": "Compliance Officer"
                }
            ]
            
            profile_count = 0
            superadmin_profile = None
            
            for profile_data in profiles_data:
                existing_profile = db.query(ProfileRole).filter_by(name=profile_data["name"]).first()
                if not existing_profile:
                    profile = ProfileRole(**profile_data)
                    db.add(profile)
                    db.flush()
                    
                    if profile_data["name"] == "SUPERADMIN":
                        superadmin_profile = profile
                    
                    profile_count += 1
                    logger.info(f"Created profile: {profile_data['name']} with {len(profile_data['default_permissions'])} permissions")
                else:
                    if profile_data["name"] == "SUPERADMIN":
                        superadmin_profile = existing_profile
                    logger.info(f"Profile already exists: {profile_data['name']}")
            
            db.commit()
            logger.info(f"Profile roles created: {profile_count}")
            
            # STEP 3: Create Super Admin User
            logger.info("Step 3: Creating super admin user...")
            
            existing_admin = db.query(UserDetails).filter_by(employee_code="ADMIN001").first()
            if not existing_admin:
                if not superadmin_profile:
                    superadmin_profile = db.query(ProfileRole).filter_by(name="SUPERADMIN").first()
                
                if superadmin_profile:
                    admin_user = UserDetails(
                        employee_code="ADMIN001",
                        phone_number="9999999999",
                        email="admin@company.com",
                        name="Super Administrator",
                        password=hash_password("admin123"),
                        role_id=superadmin_profile.id,
                        department_id=departments["ADMIN"].id,
                        father_name="System",
                        is_active=True,
                        experience=0.0,
                        date_of_joining=date.today(),
                        date_of_birth=date(1990, 1, 1)
                    )
                    
                    db.add(admin_user)
                    db.commit()
                    db.refresh(admin_user)
                    
                    logger.info("Super admin user created successfully!")
                    logger.info("Login Details:")
                    logger.info(f"Employee Code: {admin_user.employee_code}")
                    logger.info(f"Email: {admin_user.email}")
                    logger.info("Password: admin123")
                    logger.info("PLEASE CHANGE THE PASSWORD AFTER FIRST LOGIN!")
                else:
                    logger.error("SUPERADMIN profile not found, cannot create admin user")
            else:
                logger.info("Super admin user already exists")
                logger.info("Login Details:")
                logger.info(f"Employee Code: {existing_admin.employee_code}")
                logger.info(f"Email: {existing_admin.email}")
            
            # Summary
            logger.info("\n" + "="*50)
            logger.info("SYSTEM INITIALIZATION COMPLETE!")
            logger.info("="*50)
            logger.info(f"Departments: {len(departments)} created/verified")
            logger.info(f"Profile Roles: {len(profiles_data)} created/verified")
            logger.info("Admin user: Created/verified")
            logger.info("\nAdmin Login:")
            logger.info("Employee Code: ADMIN001")
            logger.info("Email: admin@company.com")
            logger.info("Password: admin123")
            logger.info("="*50)
            
            return True
            
    except Exception as e:
        logger.error(f"System initialization failed: {str(e)}")
        return False

# Simple function to call from main.py
def setup_complete_system():
    """Simple wrapper function to call from main.py"""
    return initialize_complete_system()

