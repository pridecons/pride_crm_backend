from pydantic import BaseModel, Field, validator, EmailStr
from typing import List, Optional, Literal, Union
from datetime import datetime, date
from pydantic import ConfigDict

from random import randint

    
# Schema for OTP request (for phone login).
class OTPRequest(BaseModel):
    phone_number: str = Field(..., pattern=r"^\d{10}$", example="9876543210")

