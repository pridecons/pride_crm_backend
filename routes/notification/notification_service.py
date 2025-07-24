import json
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional

from fastapi import WebSocket
from collections import defaultdict

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class NotificationService:
    def __init__(self):
        # allow many sockets per user
        self.active_connections: Dict[str, List[WebSocket]] = defaultdict(list)
        # reverse map: websocket -> user_id
        self.connection_info: Dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        """Accept WebSocket and register it under user_id."""
        await websocket.accept()
        # *** FIX: append the actual websocket, not `ws`! ***
        self.active_connections[user_id].append(websocket)
        self.connection_info[websocket] = user_id
        logger.info(f"User {user_id} connected ({len(self.active_connections[user_id])} sockets).")

        # send confirmation
        await self.send_to_user(user_id, {
            "type": "connection_confirmed",
            "message": "Connected to notification service",
            "user_id": user_id
        })

    def disconnect(self, websocket: WebSocket):
        """Remove a single WebSocket from its user bucket."""
        user_id = self.connection_info.get(websocket)
        if not user_id:
            return
        # remove this socket
        sockets = self.active_connections.get(user_id, [])
        self.active_connections[user_id] = [ws for ws in sockets if ws is not websocket]
        del self.connection_info[websocket]
        logger.info(f"User {user_id} disconnected one socket ({len(self.active_connections[user_id])} remain).")
        # if none remain, clean up the key
        if not self.active_connections[user_id]:
            del self.active_connections[user_id]

    async def send_to_user(self, user_id: str, data: Dict[str, Any]) -> bool:
        """
        Send a JSON notification to *all* sockets of a user,
        removing any that have died.
        """
        sockets = list(self.active_connections.get(user_id, []))
        if not sockets:
            logger.warning(f"No active sockets for user {user_id}")
            return False

        payload = {
            "id":        str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "type":      "notification",
            **data
        }
        text = json.dumps(payload)

        sent = False
        for ws in sockets:
            try:
                await ws.send_text(text)
                sent = True
            except Exception as e:
                logger.error(f"Error sending to {user_id} on one socket: {e}")
                # drop the bad socket
                self.disconnect(ws)

        return sent

    async def send_to_multiple(self, user_ids: List[str], data: Dict[str, Any]) -> Dict[str, bool]:
        results: Dict[str, bool] = {}
        for uid in user_ids:
            results[uid] = await self.send_to_user(uid, data)
        return results

    async def broadcast(self, data: Dict[str, Any]) -> Dict[str, bool]:
        return await self.send_to_multiple(list(self.active_connections.keys()), data)

    def get_connected_users(self) -> List[str]:
        return list(self.active_connections.keys())

    def is_user_connected(self, user_id: str) -> bool:
        return user_id in self.active_connections

    def get_connection_count(self) -> int:
        return sum(len(sockets) for sockets in self.active_connections.values())

    async def notify(
        self,
        user_id: str,
        title: str,
        message: str,
        at_time: Optional[str] = None
    ) -> bool:
        """
        High‑level helper:
        - user_id: who to send to
        - title:   headline
        - message: body HTML/text
        - at_time: override timestamp (ISO)
        """
        payload: Dict[str, Any] = {
            "user_id": user_id,
            "title":   title,
            "message": message,
        }
        if at_time:
            payload["timestamp"] = at_time
        return await self.send_to_user(user_id, payload)

# singleton instance
notification_service = NotificationService()
