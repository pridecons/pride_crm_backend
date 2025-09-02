# db/Schema/payment.py - Fixed for Pydantic V2

from pydantic import BaseModel, Field, EmailStr, ConfigDict, field_validator
from typing import Optional, Dict
from datetime import datetime
from typing import Any, Dict, List, Union


def to_camel(string: str) -> str:
    parts = string.split('_')
    return parts[0] + ''.join(word.capitalize() for word in parts[1:])

class CustomerDetails(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True
    )
    
    customer_id: str = Field(..., alias="customerId")
    customer_name: Optional[str] = Field(None, max_length=100, alias="customerName")
    customer_phone: str = Field(..., pattern=r"^\d{10}$", alias="customerPhone")

class OrderMeta(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True
    )
    
    return_url: Optional[str] = Field(
        default="https://pridebuzz.in/payment/return",
        description="URL to which user is redirected after payment",
        alias="returnUrl",
    )
    notify_url: Optional[str] = Field(
        default="https://crm.24x7techelp.com/api/v1/payment/webhook",
        description="Webhook URL for server‐to‐server notifications",
        alias="notifyUrl",
    )

    payment_methods: Optional[str]= None

class CreateOrderRequest(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True
    )
    
    order_amount: float = Field(..., gt=0, alias="orderAmount")
    order_currency: str = Field(default="INR", alias="orderCurrency")
    customer_details: CustomerDetails = Field(..., alias="customerDetails")
    order_meta: Optional[OrderMeta] = Field("https://crm.24x7techelp.com/api/v1/payment/webhook", alias="orderMeta")

class FrontCreate(BaseModel):
    name: str
    email: EmailStr
    phone: str
    service: str
    amount: float
    payment_methods: Optional[str]= None


class FrontUserCreate(BaseModel):
    name: Optional[str]
    email: Optional[EmailStr]
    phone: str
    service: str
    amount: float
    payment_methods: Optional[str]= None
    call : int = None
    duration_day : int = None
    service_id: int = None
    description: str = None
    user_id: Optional[str]   = None
    lead_id: Optional[int]   = None
    branch_id: Optional[str] = None


class PaymentOut(BaseModel):
    id: int
    name: Optional[str]
    email: Optional[str]
    phone_number: str
    order_id: str
    Service: str  # final output as a string ("Cash" or "A, B" if list)
    paid_amount: float
    call: int
    duration_day: Optional[int]
    plan: List[Dict[str, Any]]
    status: str
    mode: str
    is_send_invoice: bool
    description: Optional[str]
    transaction_id: Optional[str]
    user_id: Optional[str]
    branch_id: Optional[str]
    lead_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    raised_by: Optional[str]
    raised_by_role: Optional[str]
    raised_by_phone: Optional[str]
    raised_by_email: Optional[str]
    invoice: Optional[str] = None  # keep as string after normalization

    model_config = ConfigDict(from_attributes=True)

    @field_validator("Service", mode="before")
    def normalize_service(cls, v):
        if v is None:
            return v
        # If it came in as list of single characters like ['C','a','s','h']
        if isinstance(v, list):
            if all(isinstance(c, str) and len(c) == 1 for c in v):
                return "".join(v)
            # If list of strings, join with comma+space
            return ", ".join(str(item) for item in v)
        # If it's already a string
        if isinstance(v, str):
            return v
        # Fallback coercion
        return str(v)

    @field_validator("invoice", mode="before")
    def normalize_invoice(cls, v):
        if v is None:
            return None
        if isinstance(v, bool):
            return "true" if v else "false"
        return str(v)

    @field_validator("status", mode="before")
    def uppercase_status(cls, v):
        if isinstance(v, str):
            return v.upper()
        return v

