from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from routes.notification.notification_service import notification_service

router = APIRouter()

@router.websocket("/ws/notification/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """WebSocket connection endpoint"""
    await notification_service.connect(websocket, user_id)
    try:
        while True:
            # Keep connection alive and listen for messages
            data = await websocket.receive_text()
            # You can handle incoming messages here if needed
            print(f"Received message from {user_id}: {data}")
            
    except WebSocketDisconnect:
        notification_service.disconnect(websocket)

