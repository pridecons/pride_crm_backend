# db/schema.py

from pydantic import BaseModel, Field, EmailStr, constr
from typing import Optional
from datetime import date

# --- Branch Schemas ---

class BranchBase(BaseModel):
    name: constr(strip_whitespace=True, min_length=1, max_length=100)
    address: str
    authorized_person: constr(strip_whitespace=True, min_length=1, max_length=100)
    pan: constr(strip_whitespace=True, min_length=1, max_length=10)
    aadhaar: constr(strip_whitespace=True, min_length=12, max_length=12)
    agreement_url: Optional[str] = None
    active: Optional[bool] = True

class BranchCreate(BranchBase):
    """Exactly the same as BranchBase; kept separate for clarity."""
    pass

class BranchUpdate(BaseModel):
    name: Optional[constr(strip_whitespace=True, min_length=1, max_length=100)]
    address: Optional[str]
    authorized_person: Optional[constr(strip_whitespace=True, min_length=1, max_length=100)]
    pan: Optional[constr(strip_whitespace=True, min_length=1, max_length=10)]
    aadhaar: Optional[constr(strip_whitespace=True, min_length=12, max_length=12)]
    agreement_url: Optional[str]
    active: Optional[bool]

class BranchOut(BranchBase):
    id: int

    class Config:
        from_attributes = True  # in Pydantic v2 use from_attributes instead of orm_mode
