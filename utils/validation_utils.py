# utils/validation_utils.py
"""
Comprehensive validation utilities for email, mobile, and PAN across UserDetails and Lead modules
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from db.models import UserDetails, Lead
import re
from typing import Optional, Dict, Any


class ValidationError(Exception):
    """Custom exception for validation errors"""
    def __init__(self, message: str, field: str = None):
        self.message = message
        self.field = field
        super().__init__(self.message)


class UniquenessValidator:
    """Handles uniqueness validation across UserDetails and Lead tables"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def check_email_uniqueness(self, email: str, exclude_user_id: str = None, exclude_lead_id: int = None) -> Dict[str, Any]:
        """
        Check if email is unique across UserDetails and Lead tables
        
        Args:
            email: Email to check
            exclude_user_id: Employee code to exclude from UserDetails check (for updates)
            exclude_lead_id: Lead ID to exclude from Lead check (for updates)
            
        Returns:
            Dict with conflict information if found, None if unique
        """
        if not email or not email.strip():
            return None
            
        email = email.strip().lower()
        
        # Check UserDetails table
        user_query = self.db.query(UserDetails).filter(UserDetails.email.ilike(email))
        if exclude_user_id:
            user_query = user_query.filter(UserDetails.employee_code != exclude_user_id)
        
        existing_user = user_query.first()
        if existing_user:
            return {
                "exists_in": "UserDetails",
                "table": "crm_user_details", 
                "employee_code": existing_user.employee_code,
                "name": existing_user.name,
                "message": f"Email already registered with employee {existing_user.employee_code} ({existing_user.name})"
            }
        
        # Check Lead table
        lead_query = self.db.query(Lead).filter(Lead.email.ilike(email))
        if exclude_lead_id:
            lead_query = lead_query.filter(Lead.id != exclude_lead_id)
            
        existing_lead = lead_query.first()
        if existing_lead:
            return {
                "exists_in": "Lead",
                "table": "crm_lead",
                "lead_id": existing_lead.id,
                "name": existing_lead.full_name,
                "message": f"Email already exists in lead #{existing_lead.id} ({existing_lead.full_name or 'No Name'})"
            }
        
        return None
    
    def check_mobile_uniqueness(self, mobile: str, exclude_user_id: str = None, exclude_lead_id: int = None) -> Dict[str, Any]:
        """
        Check if mobile is unique across UserDetails and Lead tables
        
        Args:
            mobile: Mobile number to check
            exclude_user_id: Employee code to exclude from UserDetails check (for updates)
            exclude_lead_id: Lead ID to exclude from Lead check (for updates)
            
        Returns:
            Dict with conflict information if found, None if unique
        """
        if not mobile or not mobile.strip():
            return None
            
        mobile = mobile.strip()
        
        # Check UserDetails table
        user_query = self.db.query(UserDetails).filter(UserDetails.phone_number == mobile)
        if exclude_user_id:
            user_query = user_query.filter(UserDetails.employee_code != exclude_user_id)
        
        existing_user = user_query.first()
        if existing_user:
            return {
                "exists_in": "UserDetails",
                "table": "crm_user_details",
                "employee_code": existing_user.employee_code,
                "name": existing_user.name,
                "message": f"Mobile number already registered with employee {existing_user.employee_code} ({existing_user.name})"
            }
        
        # Check Lead table (both mobile and alternate_mobile)
        lead_query = self.db.query(Lead).filter(
            or_(Lead.mobile == mobile, Lead.alternate_mobile == mobile)
        )
        if exclude_lead_id:
            lead_query = lead_query.filter(Lead.id != exclude_lead_id)
            
        existing_lead = lead_query.first()
        if existing_lead:
            mobile_type = "primary" if existing_lead.mobile == mobile else "alternate"
            return {
                "exists_in": "Lead",
                "table": "crm_lead",
                "lead_id": existing_lead.id,
                "name": existing_lead.full_name,
                "mobile_type": mobile_type,
                "message": f"Mobile number already exists in lead #{existing_lead.id} ({existing_lead.full_name or 'No Name'}) as {mobile_type} mobile"
            }
        
        return None
    
    def check_pan_uniqueness(self, pan: str, exclude_user_id: str = None, exclude_lead_id: int = None) -> Dict[str, Any]:
        """
        Check if PAN is unique across UserDetails and Lead tables
        
        Args:
            pan: PAN number to check
            exclude_user_id: Employee code to exclude from UserDetails check (for updates)
            exclude_lead_id: Lead ID to exclude from Lead check (for updates)
            
        Returns:
            Dict with conflict information if found, None if unique
        """
        if not pan or not pan.strip():
            return None
            
        pan = pan.strip().upper()
        
        # Check UserDetails table
        user_query = self.db.query(UserDetails).filter(UserDetails.pan == pan)
        if exclude_user_id:
            user_query = user_query.filter(UserDetails.employee_code != exclude_user_id)
        
        existing_user = user_query.first()
        if existing_user:
            return {
                "exists_in": "UserDetails",
                "table": "crm_user_details",
                "employee_code": existing_user.employee_code,
                "name": existing_user.name,
                "message": f"PAN already registered with employee {existing_user.employee_code} ({existing_user.name})"
            }
        
        # Check Lead table
        lead_query = self.db.query(Lead).filter(Lead.pan == pan)
        if exclude_lead_id:
            lead_query = lead_query.filter(Lead.id != exclude_lead_id)
            
        existing_lead = lead_query.first()
        if existing_lead:
            return {
                "exists_in": "Lead", 
                "table": "crm_lead",
                "lead_id": existing_lead.id,
                "name": existing_lead.full_name,
                "message": f"PAN already exists in lead #{existing_lead.id} ({existing_lead.full_name or 'No Name'})"
            }
        
        return None
    
    def validate_all_unique_fields(self, data: Dict[str, Any], exclude_user_id: str = None, exclude_lead_id: int = None) -> None:
        """
        Validate all unique fields (email, mobile, pan) at once
        
        Args:
            data: Dictionary containing fields to validate
            exclude_user_id: Employee code to exclude from UserDetails check (for updates)
            exclude_lead_id: Lead ID to exclude from Lead check (for updates)
            
        Raises:
            HTTPException: If any duplicate is found
        """
        errors = []
        
        # Check email
        if 'email' in data and data['email']:
            email_conflict = self.check_email_uniqueness(
                data['email'], exclude_user_id, exclude_lead_id
            )
            if email_conflict:
                errors.append(email_conflict['message'])
        
        # Check mobile/phone_number
        mobile_field = 'phone_number' if 'phone_number' in data else 'mobile'
        if mobile_field in data and data[mobile_field]:
            mobile_conflict = self.check_mobile_uniqueness(
                data[mobile_field], exclude_user_id, exclude_lead_id
            )
            if mobile_conflict:
                errors.append(mobile_conflict['message'])
        
        # Check PAN
        if 'pan' in data and data['pan']:
            pan_conflict = self.check_pan_uniqueness(
                data['pan'], exclude_user_id, exclude_lead_id
            )
            if pan_conflict:
                errors.append(pan_conflict['message'])
        
        if errors:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Duplicate data found", "errors": errors}
            )


class FormatValidator:
    """Handles format validation for email, mobile, and PAN"""
    
    @staticmethod
    def validate_email_format(email: str) -> bool:
        """Validate email format"""
        if not email:
            return True  # Allow None/empty for optional fields
        
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email.strip()) is not None
    
    @staticmethod
    def validate_mobile_format(mobile: str) -> bool:
        """Validate Indian mobile number format"""
        if not mobile:
            return True  # Allow None/empty for optional fields
            
        mobile = mobile.strip()
        # Indian mobile numbers: exactly 10 digits
        return mobile.isdigit() and len(mobile) == 10
    
    @staticmethod
    def validate_pan_format(pan: str) -> bool:
        """Validate PAN format"""
        if not pan:
            return True  # Allow None/empty for optional fields
            
        pan = pan.strip().upper()
        # PAN format: ABCDE1234F (5 letters, 4 numbers, 1 letter)
        pattern = r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$'
        return re.match(pattern, pan) is not None
    
    @staticmethod
    def validate_all_formats(data: Dict[str, Any]) -> None:
        """
        Validate all field formats at once
        
        Args:
            data: Dictionary containing fields to validate
            
        Raises:
            HTTPException: If any format validation fails
        """
        errors = []
        
        # Check email format
        if 'email' in data and data['email']:
            if not FormatValidator.validate_email_format(data['email']):
                errors.append("Invalid email format")
        
        # Check mobile format (check both mobile and phone_number fields)
        mobile_field = None
        if 'phone_number' in data and data['phone_number']:
            mobile_field = 'phone_number'
        elif 'mobile' in data and data['mobile']:
            mobile_field = 'mobile'
            
        if mobile_field and not FormatValidator.validate_mobile_format(data[mobile_field]):
            errors.append("Mobile number must be exactly 10 digits")
        
        # Check PAN format
        if 'pan' in data and data['pan']:
            if not FormatValidator.validate_pan_format(data['pan']):
                errors.append("Invalid PAN format. PAN must be in format ABCDE1234F")
        
        if errors:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Format validation failed", "errors": errors}
            )


def validate_user_data(db: Session, data: Dict[str, Any], exclude_user_id: str = None) -> None:
    """
    Complete validation for user data (format + uniqueness)
    
    Args:
        db: Database session
        data: User data to validate
        exclude_user_id: Employee code to exclude from uniqueness check (for updates)
        
    Raises:
        HTTPException: If validation fails
    """
    # Format validation first
    FormatValidator.validate_all_formats(data)
    
    # Uniqueness validation
    validator = UniquenessValidator(db)
    validator.validate_all_unique_fields(data, exclude_user_id=exclude_user_id)


def validate_lead_data(db: Session, data: Dict[str, Any], exclude_lead_id: int = None) -> None:
    """
    Complete validation for lead data (format + uniqueness)
    
    Args:
        db: Database session
        data: Lead data to validate
        exclude_lead_id: Lead ID to exclude from uniqueness check (for updates)
        
    Raises:
        HTTPException: If validation fails
    """
    # Format validation first
    FormatValidator.validate_all_formats(data)
    
    # Uniqueness validation
    validator = UniquenessValidator(db)
    validator.validate_all_unique_fields(data, exclude_lead_id=exclude_lead_id)