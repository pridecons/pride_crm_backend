# db/Schema/payment.py - Fixed for Pydantic V2

from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import Optional, Dict
from datetime import datetime
from typing import Any, Dict, List


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
        default="https://2edf77cfd7e2.ngrok-free.app/api/v1/payment/webhook",
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
    name: str
    email: EmailStr
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
    name: str
    email: str
    phone_number: str
    order_id: str
    Service: str
    paid_amount: float
    call: int
    duration_day: int | None
    plan: List[Dict[str, Any]]
    status: str
    mode: str
    is_send_invoice: bool
    description: str | None
    transaction_id: str | None
    user_id: str | None
    branch_id: str | None
    lead_id: int | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

