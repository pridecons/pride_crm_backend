from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from routes.notification.notification_service import notification_service

router = APIRouter(
    prefix="/notification",
    tags=["send-notification"],
)

class NotificationPayload(BaseModel):
    user_id: str
    title: str
    message: str

class NotificationPayloadAll(BaseModel):
    title: str
    message: str
    user_id: Optional[str]
    branch_id: Optional[str]

@router.post("/", status_code=status.HTTP_200_OK)
async def send_notification(payload: NotificationPayload):
    """
    Send a single notification to a connected user.
    """
    success = await notification_service.notify(
        user_id=payload.user_id,
        title= payload.title,
        message= payload.message,
    )
    if not success:
        # e.g. user not connected
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {payload.user_id} is not connected"
        )
    return {"success": True}

    # await notification_service.notify(
    #     user_id="Admin001",
    #     title="New Task Assigned",
    #     message="Please follow up with lead #1234."
    # )


@router.post("/all", status_code=status.HTTP_200_OK)
async def send_notification(payload: NotificationPayloadAll):
    """
    Send a single notification to a connected user.
    """
    success = await notification_service.notify_all(
        title= payload.title,
        message= payload.message,
    )
    if not success:
        # e.g. user not connected
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {payload.user_id} is not connected"
        )
    return {"success": True}





