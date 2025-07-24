# notification_service.py

import json
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional

from fastapi import WebSocket
from collections import defaultdict

# ——— Setup logging —————————————————————————————————————————
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ——— Pending queue stubs ——————————————————————————————————
# Replace these with your real storage (Redis, database, etc.)
def load_pending(user_id: str) -> List[Dict[str, Any]]:
    """Load any notifications that were queued while user was offline."""
    return []

def mark_delivered(notif: Dict[str, Any]) -> None:
    """Mark a pending notification as delivered so you don't redeliver it."""
    pass

# ——— NotificationService —————————————————————————————————
class NotificationService:
    def __init__(self):
        # Many websockets per user_id
        self.active_connections: Dict[str, List[WebSocket]] = defaultdict(list)
        # Reverse lookup: websocket -> user_id
        self.connection_info: Dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        """Accept the socket and re‑deliver any pending messages."""
        await websocket.accept()
        # register
        self.active_connections[user_id].append(websocket)
        self.connection_info[websocket] = user_id
        logger.info(f"▶ User {user_id} connected ({len(self.active_connections[user_id])} sockets).")

        # drain any pending notifications
        for pending in load_pending(user_id):
            await self.send_to_user(user_id, pending)
            mark_delivered(pending)

        # confirm
        await self.send_to_user(user_id, {
            "type":    "connection_confirmed",
            "message": "Connected to notification service",
            "user_id": user_id
        })

    def disconnect(self, websocket: WebSocket):
        """Remove one socket from its user bucket; clean up if empty."""
        user_id = self.connection_info.pop(websocket, None)
        if not user_id:
            return
        sockets = self.active_connections.get(user_id, [])
        self.active_connections[user_id] = [ws for ws in sockets if ws is not websocket]
        logger.info(f"◀ User {user_id} disconnected one socket ({len(self.active_connections[user_id])} remain).")
        if not self.active_connections[user_id]:
            del self.active_connections[user_id]

    async def send_to_user(self, user_id: str, data: Dict[str, Any]) -> bool:
        """
        Broadcast a single `data` payload to *all* live sockets for `user_id`.
        Cleans up any dead sockets automatically.
        """
        sockets = list(self.active_connections.get(user_id, []))
        if not sockets:
            logger.warning(f"No active sockets for user {user_id}")
            return False

        envelope = {
            "id":        str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "type":      "notification",
            **data
        }
        text = json.dumps(envelope)

        delivered = False
        for ws in sockets:
            try:
                await ws.send_text(text)
                delivered = True
            except Exception as e:
                logger.error(f"Error sending to {user_id} on one socket: {e}")
                # drop that socket
                self.disconnect(ws)

        return delivered

    async def send_to_multiple(self, user_ids: List[str], data: Dict[str, Any]) -> Dict[str, bool]:
        """Fan‑out to several users."""
        results: Dict[str, bool] = {}
        for uid in user_ids:
            results[uid] = await self.send_to_user(uid, data)
        return results

    async def broadcast(self, data: Dict[str, Any]) -> Dict[str, bool]:
        """Send to everyone currently connected."""
        return await self.send_to_multiple(list(self.active_connections.keys()), data)

    def get_connected_users(self) -> List[str]:
        return list(self.active_connections.keys())

    def is_user_connected(self, user_id: str) -> bool:
        return user_id in self.active_connections

    def get_connection_count(self) -> int:
        return sum(len(lst) for lst in self.active_connections.values())

    async def notify(
        self,
        user_id: str,
        title: str,
        message: str,
        at_time: Optional[str] = None
    ) -> bool:
        """
        High‑level: send a titled notification.  
        - user_id: who to send it to  
        - title:   headline  
        - message: rich‑text or HTML body  
        - at_time: optional ISO timestamp override  
        """
        payload: Dict[str, Any] = {
            "user_id": user_id,
            "title":   title,
            "message": message,
        }
        if at_time:
            payload["timestamp"] = at_time
        return await self.send_to_user(user_id, payload)

# singleton for import
notification_service = NotificationService()
