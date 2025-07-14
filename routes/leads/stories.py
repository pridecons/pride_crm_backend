# routes/lead/stories.py

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from db.connection import get_db
from db.models import LeadStory, Lead, UserDetails

router = APIRouter(
    prefix="/leads/{lead_id}/stories",
    tags=["lead-stories"],
)


# Pydantic schemas

class LeadStoryCreate(BaseModel):
    user_id: str
    title: Optional[str] = None
    msg: str
    lead_response_id: Optional[int] = None

class LeadStoryRead(BaseModel):
    id: int
    lead_id: int
    user_id: str
    title: Optional[str]
    msg: str
    lead_response_id: Optional[int]
    timestamp: datetime

    class Config:
        from_attributes = True


# Create a new story for a lead
@router.post(
    "",
    response_model=LeadStoryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new story/note to a lead",
)
async def create_lead_story(
    lead_id: int,
    payload: LeadStoryCreate,
    db: Session = Depends(get_db),
):
    # 1) ensure lead exists
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # 2) ensure user exists
    user = db.query(UserDetails).filter(UserDetails.employee_code == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 3) build and persist the LeadStory
    story = LeadStory(
        lead_id          = lead_id,
        user_id          = payload.user_id,
        title            = payload.title,
        msg              = payload.msg,
        lead_response_id = payload.lead_response_id,
        timestamp        = datetime.utcnow(),
    )
    db.add(story)
    db.commit()
    db.refresh(story)

    return story


# List all stories for a lead
@router.get(
    "",
    response_model=List[LeadStoryRead],
    status_code=status.HTTP_200_OK,
    summary="Get all stories/notes for a lead",
)
async def list_lead_stories(
    lead_id: int,
    db: Session = Depends(get_db),
):
    # verify lead exists
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    stories = (
        db.query(LeadStory)
          .filter(LeadStory.lead_id == lead_id)
          .order_by(LeadStory.timestamp.desc())
          .all()
    )
    return stories


