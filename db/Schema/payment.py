# db/Schema/payment.py

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Dict
from datetime import datetime

def to_camel(string: str) -> str:
    parts = string.split('_')
    return parts[0] + ''.join(word.capitalize() for word in parts[1:])

class CustomerDetails(BaseModel):
    customer_id:   str           = Field(...,      alias="customerId")
    customer_name: Optional[str] = Field(None,      max_length=100, alias="customerName")
    customer_phone: str          = Field(...,      pattern=r"^\d{10}$", alias="customerPhone")

    class Config:
        alias_generator = to_camel
        allow_population_by_field_name = True
        populate_by_name = True


class OrderMeta(BaseModel):
    return_url: Optional[str] = Field(
        default="https://pridebuzz.in/payment/return",
        description="URL to which user is redirected after payment",
        alias="returnUrl",
    )
    notify_url: Optional[str] = Field(
        default="http://127.0.0.1:8000/payment/webhook",
        description="Webhook URL for server‐to‐server notifications",
        alias="notifyUrl",
    )

    class Config:
        alias_generator = to_camel
        allow_population_by_field_name = True
        populate_by_name = True

class CreateOrderRequest(BaseModel):
    order_amount: float = Field(..., gt=0, alias="orderAmount")
    order_currency: str = Field(default="INR", alias="orderCurrency")
    customer_details: CustomerDetails = Field(..., alias="customerDetails")
    order_meta: Optional[OrderMeta] = Field(None, alias="orderMeta")

    class Config:
        alias_generator = to_camel
        allow_population_by_field_name = True
        populate_by_name = True


class FrontCreate(BaseModel):
    name: str
    email: EmailStr
    phone: str
    service: str
    amount: float

