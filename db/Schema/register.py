# db/Schema/register.py

from pydantic import BaseModel, EmailStr, constr, validator, ConfigDict
from typing import Optional, List
from datetime import date, datetime

class UserBase(BaseModel):
    phone_number: constr(strip_whitespace=True, min_length=10, max_length=10)
    email: EmailStr
    name: constr(strip_whitespace=True, min_length=1, max_length=100)
    father_name: constr(strip_whitespace=True, min_length=1, max_length=100)
    is_active: bool = True
    experience: float
    date_of_joining: date
    date_of_birth: date
    pan: Optional[constr(strip_whitespace=True, min_length=10, max_length=10)] = None
    aadhaar: Optional[constr(strip_whitespace=True, min_length=12, max_length=12)] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[constr(strip_whitespace=True, min_length=6, max_length=6)] = None
    comment: Optional[str] = None

    @validator('phone_number')
    def validate_phone(cls, v):
        if not v.isdigit():
            raise ValueError('Phone number must contain only digits')
        return v

    @validator('pan')
    def validate_pan(cls, v):
        if v and len(v) != 10:
            raise ValueError('PAN must be exactly 10 characters')
        return v.upper() if v else v

    @validator('aadhaar')
    def validate_aadhaar(cls, v):
        if v and (len(v) != 12):
            raise ValueError('Aadhaar must be exactly 12 digits')
        return v

    @validator('pincode')
    def validate_pincode(cls, v):
        if v and (len(v) != 6 or not v.isdigit()):
            raise ValueError('Pincode must be exactly 6 digits')
        return v

class UserCreate(UserBase):
    password: constr(min_length=6)
    role_id: str = "0"                      # keep as string input; we will coerce to int when saving
    branch_id: Optional[int] = None
    senior_profile_id: Optional[str] = None # <-- STRING employee_code

    vbc_extension_id: Optional[str] = None
    vbc_user_username: Optional[str] = None
    vbc_user_password: Optional[str] = None
    permissions: Optional[List[str]] = None

class UserUpdate(BaseModel):
    phone_number: Optional[constr(strip_whitespace=True, min_length=10, max_length=10)] = None
    email: Optional[EmailStr] = None
    name: Optional[constr(strip_whitespace=True, min_length=1, max_length=100)] = None
    father_name: Optional[constr(strip_whitespace=True, min_length=1, max_length=100)] = None
    is_active: Optional[bool] = None
    experience: Optional[float] = None
    date_of_joining: Optional[date] = None
    date_of_birth: Optional[date] = None
    pan: Optional[constr(strip_whitespace=True, min_length=10, max_length=10)] = None
    aadhaar: Optional[constr(strip_whitespace=True, min_length=12, max_length=12)] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[constr(strip_whitespace=True, min_length=6, max_length=6)] = None
    comment: Optional[str] = None
    password: Optional[constr(min_length=6)] = None
    role_id: Optional[str] = None          # we’ll coerce to int in the route
    branch_id: Optional[int] = None
    senior_profile_id: Optional[str] = None# <-- STRING employee_code

    vbc_extension_id: Optional[str] = None
    vbc_user_username: Optional[str] = None
    vbc_user_password: Optional[str] = None
    permissions: Optional[List[str]] = None

    @validator('phone_number')
    def validate_phone(cls, v):
        if v and not v.isdigit():
            raise ValueError('Phone number must contain only digits')
        return v

    @validator('pan')
    def validate_pan(cls, v):
        if v and len(v) != 10:
            raise ValueError('PAN must be exactly 10 characters')
        return v.upper() if v else v

    @validator('aadhaar')
    def validate_aadhaar(cls, v):
        if v and (len(v) != 12):
            raise ValueError('Aadhaar must be exactly 12 digits')
        return v

    @validator('pincode')
    def validate_pincode(cls, v):
        if v and (len(v) != 6 or not v.isdigit()):
            raise ValueError('Pincode must be exactly 6 digits')
        return v

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employee_code: str
    phone_number: str
    email: str
    name: str
    role_id: str
    father_name: str
    is_active: bool
    experience: float
    date_of_joining: date
    date_of_birth: date
    pan: Optional[str] = None
    aadhaar: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    comment: Optional[str] = None
    branch_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    senior_profile_id: Optional[str] = None   # <-- STRING employee_code
    vbc_extension_id: Optional[str] = None
    vbc_user_username: Optional[str] = None
    vbc_user_password: Optional[str] = None
    permissions: Optional[List[str]] = None

# Response models for specific operations
class UserCreateResponse(BaseModel):
    message: str
    user: UserOut

class UserHierarchy(BaseModel):
    user: dict
    manager_chain: list
    subordinates: list

class RoleInfo(BaseModel):
    value: str
    name: str
    hierarchy_level: int

class RolesResponse(BaseModel):
    roles: list[RoleInfo]

class UserStatusResponse(BaseModel):
    message: str
    employee_code: str
    is_active: bool