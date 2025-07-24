from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from routes.notification.notification_service import notification_service
import logging
import json
from datetime import datetime
import asyncio

logger = logging.getLogger(__name__)
router = APIRouter()

@router.websocket("/ws/notification/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """WebSocket connection endpoint with enhanced debugging"""
    logger.info(f"WebSocket connection attempt for user {user_id}")
    
    try:
        await notification_service.connect(websocket, user_id)
        logger.info(f"WebSocket successfully connected for user {user_id}")
        
        while True:
            try:
                # Wait for messages with timeout to check connection health
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                logger.info(f"Received message from {user_id}: {data}")
                
                # Handle ping/pong for connection health
                if data.strip().lower() == 'ping':
                    await websocket.send_text(json.dumps({
                        "type": "pong",
                        "user_id": user_id,
                        "timestamp": datetime.utcnow().isoformat()
                    }))
                else:
                    # Echo back other messages for debugging
                    await websocket.send_text(json.dumps({
                        "type": "echo",
                        "original_message": data,
                        "user_id": user_id,
                        "timestamp": datetime.utcnow().isoformat()
                    }))
                
            except asyncio.TimeoutError:
                # Send ping to check if connection is still alive
                try:
                    await websocket.send_text(json.dumps({
                        "type": "ping",
                        "message": "Connection health check",
                        "timestamp": datetime.utcnow().isoformat()
                    }))
                except Exception as e:
                    logger.error(f"Failed to send ping to {user_id}: {e}")
                    break
                    
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnect for user {user_id}")
                break
            except Exception as e:
                logger.error(f"Error in WebSocket loop for user {user_id}: {e}")
                break
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected during connection for user {user_id}")
    except Exception as e:
        logger.error(f"Error in WebSocket endpoint for user {user_id}: {e}")
    finally:
        logger.info(f"Cleaning up WebSocket connection for user {user_id}")
        notification_service.disconnect(websocket)