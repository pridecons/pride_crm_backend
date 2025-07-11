# routes/auth/register.py

from datetime import datetime, date
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, constr
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from db.connection import get_db
from db.models import UserDetails

router = APIRouter(
    prefix="/users",
    tags=["users"],
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# --- Pydantic Schemas --------------------------------

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
    branch_id: int
    manager_id: Optional[str] = None


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


class UserOut(UserBase):
    employee_code: str
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


# --- CRUD Endpoints ---------------------------------

@router.post("/", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(user_in: UserCreate, db: Session = Depends(get_db)):
    # ensure unique constraints
    if db.query(UserDetails).filter_by(phone_number=user_in.phone_number).first():
        raise HTTPException(400, "Phone number already registered")
    if db.query(UserDetails).filter_by(email=user_in.email).first():
        raise HTTPException(400, "Email already registered")

    # auto-generate employee_code
    count = db.query(UserDetails).count() or 0
    emp_code = f"EMP{count+1:03d}"

    hashed_pw = pwd_context.hash(user_in.password)
    user = UserDetails(
        employee_code=emp_code,
        phone_number=user_in.phone_number,
        email=user_in.email,
        name=user_in.name,
        password=hashed_pw,
        role=user_in.role,
        father_name=user_in.father_name,
        is_active=user_in.is_active,
        experience=user_in.experience,
        date_of_joining=user_in.date_of_joining,
        date_of_birth=user_in.date_of_birth,
        pan=user_in.pan,
        aadhaar=user_in.aadhaar,
        address=user_in.address,
        city=user_in.city,
        state=user_in.state,
        pincode=user_in.pincode,
        comment=user_in.comment,
        branch_id=user_in.branch_id,
        manager_id=user_in.manager_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/{employee_code}", response_model=UserOut)
def update_user(
    employee_code: str,
    user_in: UserUpdate,
    db: Session = Depends(get_db),
):
    user = db.query(UserDetails).filter_by(employee_code=employee_code).first()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    # update only provided fields
    data = user_in.dict(exclude_unset=True)
    if "password" in data:
        data["password"] = pwd_context.hash(data["password"])
    for field, value in data.items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


@router.delete("/{employee_code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    employee_code: str,
    db: Session = Depends(get_db),
):
    user = db.query(UserDetails).filter_by(employee_code=employee_code).first()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    db.delete(user)
    db.commit()
    return None
