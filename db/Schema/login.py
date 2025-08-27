# db/Schema/login.py - Updated for ProfileRole system

from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_info: Dict[str, Any]


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LoginRequest(BaseModel):
    username: str  # Can be phone_number or email
    password: str


class UserInfoResponse(BaseModel):
    employee_code: str
    name: str
    email: EmailStr
    phone_number: str
    role_id: int  # Changed from profile_role to role_id
    role_name: str
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    branch_id: Optional[int] = None
    branch_name: Optional[str] = None
    is_active: bool
    permissions: Optional[List[str]] = []
    legacy_permissions: Optional[Dict[str, Any]] = None