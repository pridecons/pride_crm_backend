from sqlalchemy.orm import Session
from db.connection import SessionLocal
from db.models import LeadStory

def AddLeadStory(lead_id: int, user_id: str, msg: str) -> LeadStory:
    """
    Create a LeadStory entry for the given lead + user + message.
    Opens its own DB session, commits, and returns the new story.
    """
    db: Session = SessionLocal()
    try:
        story = LeadStory(
            lead_id=lead_id,
            user_id=user_id,
            msg=msg
        )
        db.add(story)
        db.commit()
        db.refresh(story)
        return story
    finally:
        db.close()

