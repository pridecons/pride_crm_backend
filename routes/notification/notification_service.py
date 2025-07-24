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
logging.basicConfig(level=logging.DEBUG)  # Changed to DEBUG for more detailed logs
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
        try:
            await websocket.accept()
            # register
            self.active_connections[user_id].append(websocket)
            self.connection_info[websocket] = user_id
            logger.info(f"▶ User {user_id} connected ({len(self.active_connections[user_id])} sockets).")
            logger.debug(f"Active connections: {list(self.active_connections.keys())}")

            # drain any pending notifications
            for pending in load_pending(user_id):
                await self.send_to_user(user_id, pending)
                mark_delivered(pending)

            # confirm connection
            confirmation_sent = await self.send_to_user(user_id, {
                "type":    "connection_confirmed",
                "message": "Connected to notification service",
                "user_id": user_id
            })
            logger.info(f"Connection confirmation sent to {user_id}: {confirmation_sent}")
            
        except Exception as e:
            logger.error(f"Error during connection for user {user_id}: {e}")
            raise

    def disconnect(self, websocket: WebSocket):
        """Remove one socket from its user bucket; clean up if empty."""
        user_id = self.connection_info.pop(websocket, None)
        if not user_id:
            logger.warning("Disconnect called for unknown websocket")
            return
            
        sockets = self.active_connections.get(user_id, [])
        original_count = len(sockets)
        self.active_connections[user_id] = [ws for ws in sockets if ws is not websocket]
        new_count = len(self.active_connections[user_id])
        
        logger.info(f"◀ User {user_id} disconnected one socket ({original_count} -> {new_count} remain).")
        
        if not self.active_connections[user_id]:
            del self.active_connections[user_id]
            logger.info(f"User {user_id} completely disconnected - removed from active connections")

    async def _send_to_socket(self, websocket: WebSocket, text: str, user_id: str) -> bool:
        """Send message to a single socket with error handling."""
        try:
            # Check if websocket is still valid
            if websocket.client_state.name != 'CONNECTED':
                logger.warning(f"Socket for {user_id} is not in CONNECTED state: {websocket.client_state.name}")
                return False
                
            await websocket.send_text(text)
            logger.debug(f"Successfully sent to {user_id} socket")
            return True
        except Exception as e:
            logger.error(f"Error sending to {user_id} on socket: {e}")
            logger.debug(f"Socket state: {getattr(websocket, 'client_state', 'unknown')}")
            return False

    async def _cleanup_dead_sockets(self, user_id: str, dead_sockets: List[WebSocket]):
        """Clean up dead sockets after sending is complete."""
        if not dead_sockets:
            return
            
        logger.info(f"Cleaning up {len(dead_sockets)} dead sockets for user {user_id}")
        
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
            logger.info(f"Removed user {user_id} from active connections (no remaining sockets)")

    async def send_to_user(self, user_id: str, data: Dict[str, Any]) -> bool:
        """
        Broadcast a single `data` payload to *all* live sockets for `user_id`.
        Cleans up dead sockets after sending is complete.
        """
        logger.debug(f"Attempting to send notification to user: {user_id}")
        logger.debug(f"Current active connections: {list(self.active_connections.keys())}")
        
        sockets = list(self.active_connections.get(user_id, []))
        if not sockets:
            logger.warning(f"No active sockets for user {user_id}")
            logger.debug(f"All active users: {list(self.active_connections.keys())}")
            return False

        logger.info(f"Found {len(sockets)} sockets for user {user_id}")

        envelope = {
            "id":        str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "type":      "notification",
            **data
        }
        text = json.dumps(envelope)
        logger.debug(f"Notification envelope: {text}")

        # Send to all sockets concurrently
        tasks = [
            self._send_to_socket(ws, text, user_id) 
            for ws in sockets
        ]
        
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            logger.debug(f"Send results: {results}")
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
                logger.debug(f"Successfully delivered to socket {i} for user {user_id}")
            else:  # result is False
                logger.warning(f"Failed to deliver to socket {i} for user {user_id}")
                dead_sockets.append(sockets[i])

        # Clean up dead sockets after sending is complete
        if dead_sockets:
            await self._cleanup_dead_sockets(user_id, dead_sockets)

        # Log delivery status
        success_count = len(results) - len(dead_sockets)
        logger.info(f"Notification sent to user {user_id}: {success_count}/{len(sockets)} sockets successful, delivered: {delivered}")

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
        users = list(self.active_connections.keys())
        logger.debug(f"Connected users: {users}")
        return users

    def is_user_connected(self, user_id: str) -> bool:
        """Check if user has any active connections."""
        connected = user_id in self.active_connections and len(self.active_connections[user_id]) > 0
        logger.debug(f"Is user {user_id} connected: {connected}")
        if user_id in self.active_connections:
            logger.debug(f"User {user_id} has {len(self.active_connections[user_id])} sockets")
        return connected

    def get_connection_count(self) -> int:
        count = sum(len(lst) for lst in self.active_connections.values())
        logger.debug(f"Total connection count: {count}")
        return count

    def debug_connections(self):
        """Debug method to log all connection info."""
        logger.info("=== CONNECTION DEBUG INFO ===")
        logger.info(f"Active connections: {dict(self.active_connections)}")
        logger.info(f"Connection info: {list(self.connection_info.values())}")
        logger.info(f"Total users: {len(self.active_connections)}")
        logger.info(f"Total sockets: {self.get_connection_count()}")
        logger.info("=============================")

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
        logger.info(f"Notify called for user {user_id} with {retry_count} retries")
        
        # Debug connection status before attempting to send
        self.debug_connections()
        is_connected = self.is_user_connected(user_id)
        logger.info(f"User {user_id} connection status: {is_connected}")
        
        if not is_connected:
            logger.warning(f"User {user_id} is not connected, cannot send notification")
            return False
        
        payload: Dict[str, Any] = {
            "user_id": user_id,
            "title":   title,
            "message": message,
        }
        if at_time:
            payload["timestamp"] = at_time

        for attempt in range(retry_count + 1):
            try:
                logger.info(f"Attempt {attempt + 1}/{retry_count + 1} to send notification to {user_id}")
                success = await self.send_to_user(user_id, payload)
                logger.info(f"Send attempt {attempt + 1} result: {success}")
                
                if success:
                    logger.info(f"Notification successfully sent to {user_id} on attempt {attempt + 1}")
                    return True
                
                if attempt < retry_count:
                    logger.info(f"Retry {attempt + 1}/{retry_count} for user {user_id} in 0.1s")
                    await asyncio.sleep(0.1)  # Small delay before retry
                    
            except Exception as e:
                logger.error(f"Error in notify attempt {attempt + 1} for user {user_id}: {e}")
                if attempt < retry_count:
                    await asyncio.sleep(0.1)

        logger.error(f"Failed to send notification to {user_id} after {retry_count + 1} attempts")
        return False

# singleton for import
notification_service = NotificationService()

