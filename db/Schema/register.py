from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, EmailStr, constr

class UserBase(BaseModel):
    phone_number: constr(min_length=10, max_length=10)
    email: EmailStr
    name: str
    role: Optional[str] = "user"
    father_name: str
    is_active: Optional[bool] = True
    experience: float
    date_of_joining: date
    date_of_birth: date
    pan: constr(max_length=10)
    aadhaar: constr(min_length=12, max_length=12)
    address: str
    city: str
    state: str
    pincode: constr(min_length=6, max_length=6)
    comment: Optional[str] = None
    branch_id: Optional[int] = None
    manager_id: Optional[str] = None
    sales_manager_id: Optional[str] = None
    tl_id: Optional[str] = None


class UserCreate(UserBase):
    password: constr(min_length=6)


class UserUpdate(BaseModel):
    phone_number: Optional[constr(min_length=10, max_length=10)]
    email: Optional[EmailStr]
    name: Optional[str]
    password: Optional[constr(min_length=6)]
    role: Optional[str]
    father_name: Optional[str]
    is_active: Optional[bool]
    experience: Optional[float]
    date_of_joining: Optional[date]
    date_of_birth: Optional[date]
    pan: Optional[constr(max_length=10)]
    aadhaar: Optional[constr(min_length=12, max_length=12)]
    address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    pincode: Optional[constr(min_length=6, max_length=6)]
    comment: Optional[str]
    branch_id: Optional[int]
    manager_id: Optional[str]
    sales_manager_id: Optional[str]
    tl_id: Optional[str]


class UserOut(UserBase):
    employee_code: str
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
