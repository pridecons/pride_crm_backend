from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from db.connection import get_db
from db.models import Service
from typing import List
from db.Schema.service import (
    ServiceCreate,
    ServiceOut,
    ServiceUpdate,
    BillingCycleEnum,
    PlanTypeEnum,
)

router = APIRouter(prefix="/services", tags=["Services"])


@router.get(
    "/billing-cycles",
    response_model=List[BillingCycleEnum],
    summary="List available billing cycles for dropdown",
)
def list_billing_cycles() -> List[BillingCycleEnum]:
    return list(BillingCycleEnum)


@router.get(
    "/plan-types",
    response_model=List[PlanTypeEnum],
    summary="List available plan types for dropdown",
)
def list_plan_types() -> List[PlanTypeEnum]:
    return list(PlanTypeEnum)


@router.post("/", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
def create_service(
    payload: ServiceCreate,
    db: Session = Depends(get_db),
):
    if db.query(Service).filter_by(name=payload.name).first():
        raise HTTPException(status_code=409, detail="Service already exists")
    svc = Service(**payload.dict())
    db.add(svc)
    db.commit()
    db.refresh(svc)
    return svc


@router.get("/", response_model=list[ServiceOut])
def list_services(db: Session = Depends(get_db)):
    return db.query(Service).all()


@router.patch("/{service_id}", response_model=ServiceOut)
def update_service(
    service_id: int,
    payload: ServiceUpdate,
    db: Session = Depends(get_db),
):
    svc = db.query(Service).get(service_id)
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    for field, value in payload.dict(exclude_unset=True).items():
        setattr(svc, field, value)
    db.commit()
    db.refresh(svc)
    return svc


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_service(service_id: int, db: Session = Depends(get_db)):
    svc = db.query(Service).get(service_id)
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    db.delete(svc)
    db.commit()
