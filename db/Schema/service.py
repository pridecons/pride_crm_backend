# schemas/service.py
from pydantic import BaseModel, Field, condecimal
from typing import Optional
from db.models import BillingCycleEnum

class ServiceBase(BaseModel):
    name: str = Field(..., example="Lead Validation")
    description: Optional[str] = Field(None, example="Validate lead data integrity")
    price: condecimal(gt=0) = Field(..., example=250.0)
    discount_percent: condecimal(ge=0, le=100) = Field(
        0.0, example=10.0, description="Discount as percentage"
    )
    billing_cycle: BillingCycleEnum = Field(
        BillingCycleEnum.MONTHLY, description="Charge interval"
    )
    CALL: Optional[int] = Field(None, example=0)

class ServiceCreate(ServiceBase):
    pass

class ServiceUpdate(BaseModel):
    name: Optional[str]
    description: Optional[str]
    price: Optional[condecimal(gt=0)]
    discount_percent: Optional[condecimal(ge=0, le=100)]
    billing_cycle: Optional[BillingCycleEnum]
    CALL: Optional[int]

class ServiceOut(ServiceBase):
    id: int
    discounted_price: float = Field(..., description="Computed price after discount")

    class Config:
        orm_mode = True
