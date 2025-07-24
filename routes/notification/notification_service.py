# notification_service.py

import json
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional

from fastapi import WebSocket
from collections import defaultdict
import asyncio

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

    async def _send_to_socket(self, websocket: WebSocket, text: str, user_id: str) -> bool:
        """Send message to a single socket with error handling."""
        try:
            await websocket.send_text(text)
            return True
        except Exception as e:
            logger.error(f"Error sending to {user_id} on socket: {e}")
            return False

    async def _cleanup_dead_sockets(self, user_id: str, dead_sockets: List[WebSocket]):
        """Clean up dead sockets after sending is complete."""
        if not dead_sockets:
            return
            
        for ws in dead_sockets:
            try:
                # Remove from connection_info
                self.connection_info.pop(ws, None)
                # Remove from active_connections
                if user_id in self.active_connections:
                    self.active_connections[user_id] = [
                        socket for socket in self.active_connections[user_id] 
                        if socket is not ws
                    ]
            except Exception as e:
                logger.error(f"Error cleaning up dead socket for {user_id}: {e}")
        
        # Clean up empty user entry
        if user_id in self.active_connections and not self.active_connections[user_id]:
            del self.active_connections[user_id]
            
        logger.info(f"Cleaned up {len(dead_sockets)} dead sockets for user {user_id}")

    async def send_to_user(self, user_id: str, data: Dict[str, Any]) -> bool:
        """
        Broadcast a single `data` payload to *all* live sockets for `user_id`.
        Cleans up dead sockets after sending is complete.
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

        # Send to all sockets concurrently
        tasks = [
            self._send_to_socket(ws, text, user_id) 
            for ws in sockets
        ]
        
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error(f"Error in concurrent sending for user {user_id}: {e}")
            return False

        # Collect results and identify dead sockets
        delivered = False
        dead_sockets = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Exception sending to {user_id}: {result}")
                dead_sockets.append(sockets[i])
            elif result is True:
                delivered = True
            else:  # result is False
                dead_sockets.append(sockets[i])

        # Clean up dead sockets after sending is complete
        if dead_sockets:
            await self._cleanup_dead_sockets(user_id, dead_sockets)

        # Log delivery status
        success_count = len(results) - len(dead_sockets)
        logger.info(f"Notification sent to user {user_id}: {success_count}/{len(sockets)} sockets successful")

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
        """Check if user has any active connections."""
        return user_id in self.active_connections and len(self.active_connections[user_id]) > 0

    def get_connection_count(self) -> int:
        return sum(len(lst) for lst in self.active_connections.values())

    async def notify(
        self,
        user_id: str,
        title: str,
        message: str,
        at_time: Optional[str] = None,
        retry_count: int = 1
    ) -> bool:
        """
        High‑level: send a titled notification with retry logic.
        - user_id: who to send it to  
        - title:   headline  
        - message: rich‑text or HTML body  
        - at_time: optional ISO timestamp override
        - retry_count: number of retry attempts if sending fails
        """
        payload: Dict[str, Any] = {
            "user_id": user_id,
            "title":   title,
            "message": message,
        }
        if at_time:
            payload["timestamp"] = at_time

        for attempt in range(retry_count + 1):
            try:
                success = await self.send_to_user(user_id, payload)
                if success:
                    return True
                
                if attempt < retry_count:
                    logger.info(f"Retry {attempt + 1}/{retry_count} for user {user_id}")
                    await asyncio.sleep(0.1)  # Small delay before retry
                    
            except Exception as e:
                logger.error(f"Error in notify attempt {attempt + 1} for user {user_id}: {e}")
                if attempt < retry_count:
                    await asyncio.sleep(0.1)

        return False

# singleton for import
notification_service = NotificationService()