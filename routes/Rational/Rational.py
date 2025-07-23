# routes/narration.py

from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.connection import get_db
from db.models import NARRATION

router = APIRouter(
    prefix="/narrations",
    tags=["narrations"],
)


# Pydantic schemas
class NarrationBase(BaseModel):
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    targets: Optional[float] = None
    rational: Optional[str] = None
    stock_name: Optional[str] = None
    recommendation_type: Optional[str] = None


class NarrationCreate(NarrationBase):
    pass


class NarrationUpdate(NarrationBase):
    pass


class NarrationOut(NarrationBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# CRUD endpoints

@router.post(
    "/",
    response_model=NarrationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new narration",
)
def create_narration(
    payload: NarrationCreate,
    db: Session = Depends(get_db),
):
    new_item = NARRATION(**payload.dict())
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return new_item


@router.get(
    "/",
    response_model=List[NarrationOut],
    summary="List all narrations",
)
def list_narrations(db: Session = Depends(get_db)):
    return db.query(NARRATION).order_by(NARRATION.created_at.desc()).all()


@router.get(
    "/{item_id}",
    response_model=NarrationOut,
    summary="Get a narration by ID",
)
def get_narration(item_id: int, db: Session = Depends(get_db)):
    item = db.query(NARRATION).filter_by(id=item_id).first()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Narration not found",
        )
    return item


@router.put(
    "/{item_id}",
    response_model=NarrationOut,
    summary="Replace a narration",
)
def update_narration(
    item_id: int,
    payload: NarrationUpdate,
    db: Session = Depends(get_db),
):
    item = db.query(NARRATION).filter_by(id=item_id).first()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Narration not found",
        )
    for field, value in payload.dict(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a narration",
)
def delete_narration(item_id: int, db: Session = Depends(get_db)):
    item = db.query(NARRATION).filter_by(id=item_id).first()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Narration not found",
        )
    db.delete(item)
    db.commit()
    return None
