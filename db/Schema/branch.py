# db/Schema/branch.py

from pydantic import BaseModel, Field, constr
from typing import Optional
from datetime import datetime

class BranchBase(BaseModel):
    name: constr(strip_whitespace=True, min_length=1, max_length=100)
    address: str
    authorized_person: constr(strip_whitespace=True, min_length=1, max_length=100)
    pan: constr(strip_whitespace=True, min_length=1, max_length=10)
    aadhaar: constr(strip_whitespace=True, min_length=12, max_length=12)
    agreement_url: Optional[str] = None
    active: Optional[bool] = True

class BranchCreate(BranchBase):
    """Schema for creating a branch"""
    manager_id: Optional[str] = None

class BranchUpdate(BaseModel):
    """Schema for updating a branch"""
    name: Optional[constr(strip_whitespace=True, min_length=1, max_length=100)] = None
    address: Optional[str] = None
    authorized_person: Optional[constr(strip_whitespace=True, min_length=1, max_length=100)] = None
    pan: Optional[constr(strip_whitespace=True, min_length=1, max_length=10)] = None
    aadhaar: Optional[constr(strip_whitespace=True, min_length=12, max_length=12)] = None
    agreement_url: Optional[str] = None
    active: Optional[bool] = None
    manager_id: Optional[str] = None

class BranchOut(BaseModel):
    """Schema for branch response"""
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
        from_attributes = True  # For Pydantic v2
        # If using Pydantic v1, use:
        # orm_mode = True

class ManagerInfo(BaseModel):
    """Schema for manager information"""
    employee_code: str
    name: str
    email: str
    phone_number: str

class UserInfo(BaseModel):
    """Schema for user information"""
    employee_code: str
    name: str
    role: str
    email: str
    is_active: bool

class BranchDetailsOut(BaseModel):
    """Schema for detailed branch response with manager and users"""
    branch: BranchOut
    manager: Optional[ManagerInfo] = None
    users: list[UserInfo] = []
    total_users: int

    class Config:
        from_attributes = True