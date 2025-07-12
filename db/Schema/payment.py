# schemas/payment.py
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Dict, Any, List

class CustomerDetails(BaseModel):
    customer_id: str = Field(..., example="CUST123")
    customer_phone: str = Field(..., example="9000000000")
    customer_email: Optional[EmailStr] = Field(None, example="user@example.com")
    customer_name: Optional[str] = Field(None, example="John Doe")

class CreateOrderRequest(BaseModel):
    order_currency: str = Field(..., example="INR")
    order_amount: float = Field(..., example=100.00)
    customer_details: CustomerDetails
    order_note: Optional[str] = Field(None, example="Optional note")
    order_meta: Optional[Dict[str, Any]] = Field(None, example={"promo_code": "OFF10"})

class CreatePaymentRequest(BaseModel):
    order_id: str = Field(..., example="2149460581")
    payment_method: str = Field(..., example="card")
    payment_amount: float = Field(..., example=100.00)
    data: Optional[Dict[str, Any]] = Field(
        None,
        example={
            "url": "https://sandbox.cashfree.com/pg/view/…",
            "payload": {"name": "card"},
            "content_type": "application/x-www-form-urlencoded",
            "method": "post",
        },
    )

class CreatePaymentLinkRequest(BaseModel):
    link_amount: float = Field(..., example=500.00)
    link_currency: str = Field(..., example="INR")
    link_purpose: Optional[str] = Field(None, example="For service X")
    customer_details: Optional[CustomerDetails] = None

class CreateRefundRequest(BaseModel):
    payment_id: str = Field(..., example="PAY12345")
    refund_amount: float = Field(..., example=50.00)
    cf_merchant_refund_id: Optional[str] = Field(None, example="REF123")
    refund_note: Optional[str] = Field(None, example="Partial refund")

class CreateCustomerRequest(BaseModel):
    customer_id: str = Field(..., example="CUST123")
    customer_phone: str = Field(..., example="9000000000")
    customer_email: Optional[EmailStr] = Field(None, example="user@example.com")
    customer_name: Optional[str] = Field(None, example="John Doe")

class CreateSubscriptionRequest(BaseModel):
    plan_id: str = Field(..., example="PLAN_BASIC")
    customer_id: str = Field(..., example="CUST123")
    subscription_note: Optional[str] = Field(None, example="Monthly plan")

class CreateMandateRequest(BaseModel):
    subscription_id: str = Field(..., example="SUB12345")
    payment_method: str = Field(..., example="upi")
    data: Optional[Dict[str, Any]] = None

class SettlementReconRequest(BaseModel):
    filters: Dict[str, List[str]] = Field(
        ...,
        example={"settlement_utrs": ["UTR123", "UTR456"]}
    )
