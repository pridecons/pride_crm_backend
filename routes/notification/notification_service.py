# notification_service.py
import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from fastapi import WebSocket

import uuid

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class NotificationService:
    def __init__(self):
        # Store active connections: user_id -> websocket
        self.active_connections: Dict[str, WebSocket] = {}
        # Store connection info: websocket -> user_id  
        self.connection_info: Dict[WebSocket, str] = {}
    
    async def connect(self, websocket: WebSocket, user_id: str):
        """Accept WebSocket connection and store user mapping"""
        await websocket.accept()
        self.active_connections[user_id] = websocket
        self.connection_info[websocket] = user_id
        logger.info(f"User {user_id} connected. Total connections: {len(self.active_connections)}")
        
        # Send connection confirmation
        await self.send_to_user(user_id, {
            "type": "connection_confirmed",
            "message": "Successfully connected to notifications",
            "user_id": user_id
        })
    
    def disconnect(self, websocket: WebSocket):
        """Remove connection when user disconnects"""
        if websocket in self.connection_info:
            user_id = self.connection_info[websocket]
            del self.active_connections[user_id]
            del self.connection_info[websocket]
            logger.info(f"User {user_id} disconnected. Total connections: {len(self.active_connections)}")
    
    async def send_to_user(self, user_id: str, data: Dict[str, Any]) -> bool:
        """Low-level: send a JSON‐notification to a single connected user"""
        try:
            if user_id in self.active_connections:
                ws = self.active_connections[user_id]
                # build envelope (id + timestamp + type + payload)
                notification = {
                    "id":        str(uuid.uuid4()),
                    "timestamp": datetime.now().isoformat(),
                    "type":      "notification",
                    **data
                }
                await ws.send_text(json.dumps(notification))
                logger.info(f"Notification sent to {user_id}: {data.get('title','(no title)')}")
                return True
            else:
                logger.warning(f"User {user_id} not connected, cannot deliver notification")
                return False
        except Exception as e:
            logger.error(f"Error sending to {user_id}: {e}")
            # clean up broken connection
            if user_id in self.active_connections:
                del self.active_connections[user_id]
            return False

    async def send_to_multiple(self, user_ids: List[str], data: Dict[str, Any]) -> Dict[str,bool]:
        """Fan‐out a notification to multiple users"""
        results = {}
        for uid in user_ids:
            results[uid] = await self.send_to_user(uid, data)
        return results

    async def broadcast(self, data: Dict[str, Any]) -> Dict[str,bool]:
        """Send to everyone"""
        return await self.send_to_multiple(list(self.active_connections), data)

    def get_connected_users(self) -> List[str]:
        return list(self.active_connections.keys())

    def is_user_connected(self, user_id: str) -> bool:
        return user_id in self.active_connections

    def get_connection_count(self) -> int:
        return len(self.active_connections)

    # ─── your new high‐level helper ────────────────────────────────────────────
    async def notify(
        self,
        user_id: str,
        title: str,
        message: str,
        at_time: Optional[str] = None
    ) -> bool:
        """
        Send a standard notification to one employee.
        - user_id: who to send to
        - title:       headline text
        - message:     body text
        - at_time:     optional ISO timestamp (defaults to now)
        """
        payload: Dict[str, Any] = {
            "user_id": user_id,
            "title":       title,
            "message":     message,
        }
        # if caller provided a timestamp, let it override
        if at_time:
            payload["timestamp"] = at_time
        return await self.send_to_user(user_id, payload)
    # ──────────────────────────────────────────────────────────────────────────

# singleton instance you import from routes…
notification_service = NotificationService()
