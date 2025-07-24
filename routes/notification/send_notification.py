from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from routes.notification.notification_service import notification_service

router = APIRouter(
    prefix="/notification",
    tags=["send-notification"],
)

class NotifyIn(BaseModel):
    user_id: str
    title:   str
    message: str

class NotifyOut(BaseModel):
    success: bool

@router.post("/", response_model=NotifyOut)
async def send_notification(payload: NotifyIn):
    """
    Send a one‑off notification to a connected user.
    Returns {"success":true} if at least one socket got it.
    """
    ok = await notification_service.notify(
        user_id=payload.user_id,
        title=payload.title,
        message=payload.message,
        retry_count=10
    )
    return NotifyOut(success=ok)
