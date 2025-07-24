from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
import logging

from routes.notification.notification_service import notification_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/notification",
    tags=["send-notification"],
)

class NotifyIn(BaseModel):
    user_id: str
    title: str
    message: str

class NotifyOut(BaseModel):
    success: bool
    debug_info: dict = {}

@router.post("/", response_model=NotifyOut)
async def send_notification(payload: NotifyIn):
    """
    Send a one‑off notification to a connected user.
    Returns {"success":true} if at least one socket got it.
    """
    logger.info(f"API: Received notification request for user {payload.user_id}")
    
    # Pre-send debug info
    connected_users = notification_service.get_connected_users()
    is_connected = notification_service.is_user_connected(payload.user_id)
    connection_count = notification_service.get_connection_count()
    
    debug_info = {
        "user_id": payload.user_id,
        "is_connected_before": is_connected,
        "connected_users": connected_users,
        "total_connections": connection_count,
        "user_in_connected_list": payload.user_id in connected_users
    }
    
    logger.info(f"API: Pre-send debug info: {debug_info}")
    
    try:
        ok = await notification_service.notify(
            user_id=payload.user_id,
            title=payload.title,
            message=payload.message,
            retry_count=3  # Reduced from 10 for faster testing
        )
        
        # Post-send debug info
        is_connected_after = notification_service.is_user_connected(payload.user_id)
        debug_info.update({
            "is_connected_after": is_connected_after,
            "send_result": ok
        })
        
        logger.info(f"API: Notification result for {payload.user_id}: {ok}")
        logger.info(f"API: Post-send debug info: {debug_info}")
        
        return NotifyOut(success=ok, debug_info=debug_info)
        
    except Exception as e:
        logger.error(f"API: Error sending notification to {payload.user_id}: {e}")
        debug_info.update({
            "error": str(e),
            "send_result": False
        })
        return NotifyOut(success=False, debug_info=debug_info)

@router.get("/debug/{user_id}")
async def debug_user_connection(user_id: str):
    """Debug endpoint to check user connection status"""
    logger.info(f"Debug endpoint called for user {user_id}")
    
    notification_service.debug_connections()
    
    return {
        "user_id": user_id,
        "is_connected": notification_service.is_user_connected(user_id),
        "connected_users": notification_service.get_connected_users(),
        "total_connections": notification_service.get_connection_count(),
        "active_connections": {
            uid: len(sockets) 
            for uid, sockets in notification_service.active_connections.items()
        }
    }

@router.get("/debug/all")
async def debug_all_connections():
    """Debug endpoint to see all connections"""
    notification_service.debug_connections()
    
    return {
        "connected_users": notification_service.get_connected_users(),
        "total_connections": notification_service.get_connection_count(),
        "active_connections": {
            uid: len(sockets) 
            for uid, sockets in notification_service.active_connections.items()
        }
    }