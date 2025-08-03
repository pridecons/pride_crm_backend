# db/Schema/service.py - Fixed for Pydantic V2
from pydantic import BaseModel, Field, ConfigDict, condecimal
from typing import Optional, List
from db.models import BillingCycleEnum

class ServiceBase(BaseModel):
    name: str = Field(..., examples=["Lead Validation"])
    description: Optional[str] = Field(None, examples=["Validate lead data integrity"])
    price: condecimal(gt=0) = Field(..., examples=[250.0])
    discount_percent: condecimal(ge=0, le=100) = Field(
        0.0, examples=[10.0], description="Discount as percentage"
    )
    billing_cycle: BillingCycleEnum = Field(
        BillingCycleEnum.MONTHLY, description="Charge interval"
    )
    CALL: Optional[int] = Field(None, examples=[0])
    service_type: Optional[List[str]] = Field(
        None,
        examples=[["consulting", "support"]],
        description="Service types / categories as an array of strings",
    )

class ServiceCreate(ServiceBase):
    pass

class ServiceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[condecimal(gt=0)] = None
    discount_percent: Optional[condecimal(ge=0, le=100)] = None
    billing_cycle: Optional[BillingCycleEnum] = None
    CALL: Optional[int] = None
    service_type: Optional[List[str]] = None

class ServiceOut(ServiceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    discounted_price: float = Field(..., description="Computed price after discount")
