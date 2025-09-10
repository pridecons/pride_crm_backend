# routes/chat_ws.py
import os
import json
import asyncio
from typing import Set, DefaultDict, Dict, List, Optional
from collections import defaultdict
from datetime import datetime

import jwt  # PyJWT
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from db.connection import SessionLocal
from db.Models.models_chat import ChatThread, ChatParticipant, ChatMessage, ThreadType

router = APIRouter(prefix="/ws", tags=["Chat WS"])

# In-process rooms
thread_rooms: DefaultDict[int, Set[WebSocket]] = defaultdict(set)
thread_listeners: Dict[int, asyncio.Task] = {}

# Optional Redis fanout (multi-worker)
REDIS_URL = os.getenv("REDIS_URL")
redis = None
if REDIS_URL:
    try:
        from redis.asyncio import Redis
        redis = Redis.from_url(REDIS_URL, decode_responses=True)
    except Exception:
        redis = None

JWT_SECRET = os.getenv("JWT_SECRET", "")          # MUST match your API
JWT_ALG = os.getenv("JWT_ALGORITHM", "HS256")


def _decode_sender_from_token(token: str) -> Optional[str]:
    if not token or not JWT_SECRET:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        return (payload.get("sub") or "").strip() or None
    except Exception:
        return None


def _get_sender(websocket: WebSocket) -> Optional[str]:
    # 1) Explicit sender query/header
    s = websocket.headers.get("x-sender") or websocket.query_params.get("sender")
    if s and s.strip():
        return s.strip()
    # 2) JWT in query ?token=... (or header x-token)
    tok = websocket.query_params.get("token") or websocket.headers.get("x-token")
    sid = _decode_sender_from_token(tok) if tok else None
    return sid


async def _ensure_listener(thread_id: int):
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

    thread_listeners[thread_id] = asyncio.create_task(_listen())


async def _publish(thread_id: int, payload: dict):
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
        row.user_id
        for row in db.query(ChatParticipant.user_id)
                     .filter(ChatParticipant.thread_id == thread_id).all()
    ]


def _direct_peer(participants: List[str], me: str) -> Optional[str]:
    if len(participants) == 2 and me in participants:
        return participants[0] if participants[1] == me else participants[1]
    return None


@router.websocket("/chat/{thread_id}")
async def chat_ws(websocket: WebSocket, thread_id: int):
    """
    Connect examples:
      wss://.../ws/chat/3?sender=EMP001
      wss://.../ws/chat/3?token=JWT

    Send:
      {"type":"send","data":{"body":"hello"}}
      {"type":"ping"} -> server replies {"type":"pong"}
    """
    db: Session = SessionLocal()
    try:
        # --- AuthN/AuthZ BEFORE accept() ---
        thread = db.get(ChatThread, thread_id)
        if not thread:
            await websocket.close(code=4404)  # Not Found
            return

        sender_id = _get_sender(websocket)
        if not sender_id:
            await websocket.close(code=4401)  # Unauthorized
            return

        participants = _participants_of_thread(db, thread_id)
        if sender_id not in participants:
            await websocket.close(code=4403)  # Forbidden
            return

        # Accept only after successful validation
        await websocket.accept()

        # Join & start Redis listener if any
        thread_rooms[thread_id].add(websocket)
        await _ensure_listener(thread_id)

        recipients_all = [u for u in participants if u != sender_id]
        direct_peer = _direct_peer(participants, sender_id) if thread.type == ThreadType.DIRECT else None

        while True:
            raw = await websocket.receive_text()

            # Default
            body = None
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    t = obj.get("type")
                    if t == "ping":
                        await websocket.send_text(json.dumps({"type": "pong", "at": int(datetime.utcnow().timestamp()*1000)}))
                        continue
                    if t == "send":
                        data = obj.get("data") or {}
                        body = (data.get("body") or "").strip()
                else:
                    body = str(obj).strip()
            except Exception:
                body = raw.strip()

            if not body:
                continue

            # Persist message
            msg = ChatMessage(thread_id=thread_id, sender_id=sender_id, body=body)
            db.add(msg)
            thread.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(msg)

            # Broadcast unified payload
            payload = {
                "type": "message",
                "id": msg.id,
                "thread_id": thread_id,
                "body": msg.body,
                "sender_id": sender_id,
                "recipients": recipients_all,
                "direct_recipient_id": direct_peer,
                "created_at": msg.created_at.isoformat(),
            }
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
