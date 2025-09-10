# routes/chat_ws.py
import os
import json
import asyncio
from typing import Set, DefaultDict, Dict, List, Optional
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from db.connection import SessionLocal
from db.Models.models_chat import ChatThread, ChatParticipant, ChatMessage, ThreadType

router = APIRouter(prefix="/ws", tags=["Chat WS"])

# In-process rooms (still used even with Redis, for local sockets)
thread_rooms: DefaultDict[int, Set[WebSocket]] = defaultdict(set)
# One Redis listener task per thread
thread_listeners: Dict[int, asyncio.Task] = {}

# --- Redis (optional) ---
REDIS_URL = os.getenv("REDIS_URL")  # e.g. redis://localhost:6379/0
redis = None
if REDIS_URL:
    try:
        from redis.asyncio import Redis
        redis = Redis.from_url(REDIS_URL, decode_responses=True)
    except Exception:
        redis = None  # fallback to in-memory if import or connection fails


def _get_sender(websocket: WebSocket) -> str:
    """Sender id from query or header (replace with JWT validation if needed)."""
    sender = websocket.headers.get("x-sender") or websocket.query_params.get("sender")
    return (sender or "").strip()


async def _ensure_listener(thread_id: int):
    """Start a Redis pub/sub listener per thread that rebroadcasts to local sockets."""
    if not redis:
        return
    if thread_id in thread_listeners and not thread_listeners[thread_id].done():
        return

    async def _listen():
        pubsub = redis.pubsub()
        channel = f"chat:{thread_id}"
        await pubsub.subscribe(channel)
        try:
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                payload = msg.get("data")
                # Fan-out to all local sockets
                for ws in list(thread_rooms[thread_id]):
                    try:
                        await ws.send_text(payload)
                    except Exception:
                        thread_rooms[thread_id].discard(ws)
        finally:
            try:
                await pubsub.unsubscribe(channel)
            finally:
                await pubsub.close()

    task = asyncio.create_task(_listen(), name=f"chat-listener-{thread_id}")
    thread_listeners[thread_id] = task


async def _publish(thread_id: int, payload: dict):
    """Publish via Redis if available; else local broadcast."""
    text = json.dumps(payload, ensure_ascii=False)
    if redis:
        await redis.publish(f"chat:{thread_id}", text)
    else:
        for ws in list(thread_rooms[thread_id]):
            try:
                await ws.send_text(text)
            except Exception:
                thread_rooms[thread_id].discard(ws)


def _participants_of_thread(db: Session, thread_id: int) -> List[str]:
    return [
        r.user_id
        for r in db.query(ChatParticipant.user_id)
                  .filter(ChatParticipant.thread_id == thread_id).all()
    ]


def _direct_peer(participants: List[str], me: str) -> Optional[str]:
    if len(participants) == 2 and me in participants:
        return participants[0] if participants[1] == me else participants[1]
    return None


@router.websocket("/chat/{thread_id}")
async def chat_ws(websocket: WebSocket, thread_id: int):
    """
    Connect with:
      wss://.../ws/chat/{thread_id}?sender=EMP001

    Send JSON:
      {"type":"send","data":{"body":"hello"}}
    Pings:
      {"type":"ping"}  -> ignored
    Plain text "hello" also works.
    """
    await websocket.accept()

    db: Session = SessionLocal()
    try:
        # Validate thread
        thread = db.get(ChatThread, thread_id)
        if not thread:
            await websocket.close(code=4404)
            return

        # Identify sender and enforce membership
        sender_id = _get_sender(websocket)
        if not sender_id:
            await websocket.close(code=4401)  # unauthorized
            return

        participants = _participants_of_thread(db, thread_id)
        if sender_id not in participants:
            await websocket.close(code=4403)  # forbidden
            return

        # Join local room & ensure Redis listener
        thread_rooms[thread_id].add(websocket)
        await _ensure_listener(thread_id)

        # Precompute recipients list for this sender
        recipients_all = [u for u in participants if u != sender_id]
        direct_peer = _direct_peer(participants, sender_id) if thread.type == ThreadType.DIRECT else None

        while True:
            raw = await websocket.receive_text()

            # Parse JSON or treat as plain text
            msg_type = None
            body = None
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    msg_type = obj.get("type")
                    if msg_type == "ping":
                        continue  # ignore keepalives
                    if msg_type == "send":
                        data = obj.get("data") or {}
                        body = (data.get("body") or "").strip()
            except Exception:
                # plain text
                body = raw.strip()

            if not body:
                continue

            # Persist (optional)
            msg = ChatMessage(thread_id=thread_id, sender_id=sender_id, body=body)
            db.add(msg)
            thread.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(msg)

            # Build unified envelope
            payload = {
                "type": "message",
                "id": msg.id,
                "thread_id": thread_id,
                "body": msg.body,
                "sender_id": sender_id,
                "recipients": recipients_all,            # all others in thread
                "direct_recipient_id": direct_peer,      # only for DIRECT
                "created_at": msg.created_at.isoformat(),
            }

            # Publish to everyone (clients can check sender_id/recipients)
            await _publish(thread_id, payload)

    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        thread_rooms[thread_id].discard(websocket)
        db.close()
