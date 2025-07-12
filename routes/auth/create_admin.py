#!/usr/bin/env python3
"""
Standalone utility to create admin user
Run this script: python create_admin.py
"""

import sys
import os
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

# Add the parent directory to the path to import models
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from db.connection import get_db, engine
    from db.models import UserDetails, PermissionDetails, UserRoleEnum, Base
    from passlib.context import CryptContext
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure you're running this from the correct directory and all dependencies are installed")
    sys.exit(1)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    return pwd_context.hash(password)

def create_admin():
    """Create admin user with error handling"""
    print("🚀 Creating admin user...")
    
    try:
        # Create tables
        Base.metadata.create_all(bind=engine)
        print("✅ Database tables verified")
        
        # Get database session
        db = next(get_db())
        
        try:
            # Check if admin exists
            existing_admin = db.query(UserDetails).filter(
                UserDetails.employee_code == "Admin001"
            ).first()
            
            if existing_admin:
                print("ℹ️  Admin user already exists!")
                print(f"   Employee Code: {existing_admin.employee_code}")
                print(f"   Email: {existing_admin.email}")
                print(f"   Role: {existing_admin.role}")
                return
            
            # Create admin user
            admin_user = UserDetails(
                employee_code="Admin001",
                phone_number="9999999999",
                email="admin@gmail.com", 
                name="System Administrator",
                password=hash_password("Admin@123"),
                role=UserRoleEnum.SUPERADMIN,
                father_name="System",
                is_active=True,
                experience=5.0,
                date_of_joining=date.today(),
                date_of_birth=date(1990, 1, 1),
                address="System Address",
                city="System City",
                state="System State", 
                pincode="000000",
                comment="Auto-created system administrator"
            )
            
            db.add(admin_user)
            db.flush()
            
            # Create permissions
            admin_permissions = PermissionDetails(
                user_id="Admin001",
                **PermissionDetails.get_default_permissions(UserRoleEnum.SUPERADMIN)
            )
            
            db.add(admin_permissions)
            db.commit()
            
            print("🎉 ADMIN USER CREATED SUCCESSFULLY!")
            print("=" * 50)
            print("📧 Email: admin@gmail.com")
            print("🔑 Password: Admin@123") 
            print("👤 Employee Code: Admin001")
            print("🔐 Role: SUPERADMIN")
            print("=" * 50)
            print("✅ You can now login with these credentials!")
            
        except IntegrityError as e:
            db.rollback()
            print(f"❌ Database integrity error: {str(e)}")
            print("This usually means the admin user already exists or there's a constraint violation")
        except Exception as e:
            db.rollback()
            print(f"❌ Error creating admin user: {str(e)}")
        finally:
            db.close()
            
    except Exception as e:
        print(f"❌ Database connection error: {str(e)}")
        print("Make sure your database is running and connection settings are correct")
