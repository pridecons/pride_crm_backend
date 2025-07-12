# db/Schema/branch.py - Updated with additional schemas

from pydantic import BaseModel, EmailStr, constr, validator
from typing import Optional, List
from datetime import date, datetime
from enum import Enum

class UserRoleEnum(str, Enum):
    SUPERADMIN = "SUPERADMIN"
    BRANCH_MANAGER = "BRANCH MANAGER"
    HR = "HR"
    SALES_MANAGER = "SALES MANAGER"
    TL = "TL"
    BA = "BA"
    SBA = "SBA"

# Existing schemas (keeping them as they are)
class BranchBase(BaseModel):
    name: constr(strip_whitespace=True, min_length=1, max_length=100)
    address: str
    authorized_person: constr(strip_whitespace=True, min_length=1, max_length=100)
    pan: constr(strip_whitespace=True, min_length=10, max_length=10)
    aadhaar: constr(strip_whitespace=True, min_length=12, max_length=12)
    active: bool = True

class BranchCreate(BranchBase):
    manager_id: Optional[str] = None

class BranchUpdate(BaseModel):
    name: Optional[constr(strip_whitespace=True, min_length=1, max_length=100)] = None
    address: Optional[str] = None
    authorized_person: Optional[constr(strip_whitespace=True, min_length=1, max_length=100)] = None
    pan: Optional[constr(strip_whitespace=True, min_length=10, max_length=10)] = None
    aadhaar: Optional[constr(strip_whitespace=True, min_length=12, max_length=12)] = None
    active: Optional[bool] = None
    manager_id: Optional[str] = None

class BranchOut(BaseModel):
    id: int
    name: str
    address: str
    authorized_person: str
    pan: str
    aadhaar: str
    agreement_url: Optional[str] = None
    active: bool
    manager_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Manager and User Info schemas
class ManagerInfo(BaseModel):
    employee_code: str
    name: str
    email: str
    phone_number: str

class UserInfo(BaseModel):
    employee_code: str
    name: str
    role: str
    email: str
    is_active: bool

class BranchDetailsOut(BaseModel):
    branch: BranchOut
    manager: Optional[ManagerInfo] = None
    users: List[UserInfo] = []
    total_users: int

# NEW: Branch with Manager Creation Schema
class BranchManagerCreateForm(BaseModel):
    """Schema for creating branch with manager - used for validation"""
    # Branch Details
    branch_name: constr(strip_whitespace=True, min_length=1, max_length=100)
    branch_address: str
    authorized_person: constr(strip_whitespace=True, min_length=1, max_length=100)
    branch_pan: constr(strip_whitespace=True, min_length=10, max_length=10)
    branch_aadhaar: constr(strip_whitespace=True, min_length=12, max_length=12)
    branch_active: bool = True
    
    # Manager Details
    manager_name: constr(strip_whitespace=True, min_length=1, max_length=100)
    manager_email: EmailStr
    manager_phone: constr(strip_whitespace=True, min_length=10, max_length=10)
    manager_father_name: constr(strip_whitespace=True, min_length=1, max_length=100)
    manager_experience: float
    manager_dob: date
    manager_password: constr(min_length=6)
    
    # Optional Manager Details
    manager_pan: Optional[constr(strip_whitespace=True, min_length=10, max_length=10)] = None
    manager_aadhaar: Optional[constr(strip_whitespace=True, min_length=12, max_length=12)] = None
    manager_address: Optional[str] = None
    manager_city: Optional[str] = None
    manager_state: Optional[str] = None
    manager_pincode: Optional[constr(strip_whitespace=True, min_length=6, max_length=6)] = None
    manager_comment: Optional[str] = None

    @validator('manager_phone')
    def validate_phone(cls, v):
        if not v.isdigit():
            raise ValueError('Phone number must contain only digits')
        return v

    @validator('branch_pan', 'manager_pan')
    def validate_pan(cls, v):
        if v and len(v) != 10:
            raise ValueError('PAN must be exactly 10 characters')
        return v.upper() if v else v

    @validator('branch_aadhaar', 'manager_aadhaar')
    def validate_aadhaar(cls, v):
        if v and (len(v) != 12 or not v.isdigit()):
            raise ValueError('Aadhaar must be exactly 12 digits')
        return v

    @validator('manager_pincode')
    def validate_pincode(cls, v):
        if v and (len(v) != 6 or not v.isdigit()):
            raise ValueError('Pincode must be exactly 6 digits')
        return v

# Response Schemas for Branch + Manager Creation
class ManagerCreateResponse(BaseModel):
    employee_code: str
    name: str
    email: str
    phone_number: str
    role: str
    branch_id: int
    is_active: bool
    date_of_joining: date
    created_at: datetime

class LoginCredentials(BaseModel):
    employee_code: str
    email: str
    password: str
    role: str

class BranchWithManagerResponse(BaseModel):
    message: str
    branch: BranchOut
    manager: ManagerCreateResponse
    login_credentials: LoginCredentials

# Existing schemas (keeping them as they are)
class AvailableManager(BaseModel):
    employee_code: str
    name: str
    email: str
    phone_number: str

class ManagerAssignment(BaseModel):
    manager_id: str

class ManagerAssignmentResponse(BaseModel):
    message: str
    branch_id: int
    manager_id: str

class AgreementUpdateResponse(BaseModel):
    message: str
    agreement_url: str