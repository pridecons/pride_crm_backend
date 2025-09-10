# routes/chat_ws.py
from typing import Dict, Set, DefaultDict, Optional
from collections import defaultdict
import json
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session
from sqlalchemy import and_, exists

from db.connection import SessionLocal  # use a real session in WS
from db.Models.models_chat import ChatThread, ChatParticipant, ChatMessage, ThreadType
from db.models import UserDetails

# ⚠️ Adjust this import to your real token decoder / verifier.
# For example, if you have: from routes.auth.auth_dependency import decode_access_token
from routes.auth.auth_dependency import decode_access_token  # <-- change if different

router = APIRouter(prefix="/ws", tags=["Chat WS"])

# thread_id -> set of websockets
thread_rooms: DefaultDict[int, Set[WebSocket]] = defaultdict(set)


# ---------- helpers ----------
def _role(u: UserDetails) -> str:
    return (getattr(u, "role_name", "") or "").upper()

def _is_participant(db: Session, user_code: str, thread_id: int) -> bool:
    return db.query(
        exists().where(and_(
            ChatParticipant.thread_id == thread_id,
            ChatParticipant.user_id == user_code
        ))
    ).scalar()

def _can_view_thread(db: Session, u: UserDetails, thread: ChatThread) -> bool:
    role = _role(u)
    if role == "SUPERADMIN":
        return True
    if role == "BRANCH_MANAGER":
        # Manager can see all threads of their branch or where they are a participant
        return (thread.branch_id == u.branch_id) or _is_participant(db, u.employee_code, thread.id)
    # Employee must be a participant
    return _is_participant(db, u.employee_code, thread.id)

def _extract_bearer_token(websocket: WebSocket) -> Optional[str]:
    # Try Authorization header first
    auth = websocket.headers.get("authorization") or websocket.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    # Fallback to ?token=... query param
    token = websocket.query_params.get("token")
    return token

async def _auth_user_ws(websocket: WebSocket, db: Session) -> Optional[UserDetails]:
    token = _extract_bearer_token(websocket)
    if not token:
        return None
    try:
        payload = decode_access_token(token)  # must return claims incl. user id / employee_code
    except Exception:
        return None

    # Adjust according to your JWT payload keys
    emp_code = payload.get("sub") or payload.get("employee_code") or payload.get("user_id")
    if not emp_code:
        return None

    user = db.query(UserDetails).filter(
        UserDetails.employee_code == emp_code,
        UserDetails.is_active.is_(True)
    ).first()
    return user


# ---------- WebSocket endpoint ----------
@router.websocket("/chat/{thread_id}")
async def chat_ws(websocket: WebSocket, thread_id: int):
    """
    Connect with either:
      - Header: Authorization: Bearer <access_token>
      - or query param:  wss://.../ws/chat/123?token=<access_token>
    """
    # Accept the connection first to be able to close with a code later
    await websocket.accept()

    db: Session = SessionLocal()
    try:
        # Auth user
        me = await _auth_user_ws(websocket, db)
        if not me:
            await websocket.close(code=4401)  # unauthorized
            return

        # Load thread & permission
        thread = db.get(ChatThread, thread_id)
        if not thread:
            await websocket.close(code=4404)  # not found
            return

        if not _can_view_thread(db, me, thread):
            await websocket.close(code=4403)  # forbidden
            return

        # Register in room
        thread_rooms[thread_id].add(websocket)

        # Event loop
        while True:
            raw = await websocket.receive_text()
            # simple protocol: either plain text body or JSON { "body": "..."}
            try:
                parsed = json.loads(raw)
                body = (parsed.get("body") or "").strip()
            except Exception:
                body = raw.strip()

            if not body:
                # ignore empty messages
                continue

            # Persist message
            msg = ChatMessage(
                thread_id=thread_id,
                sender_id=me.employee_code,
                body=body,
            )
            db.add(msg)

            # bump thread updated time
            thread.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(msg)

            # Broadcast as JSON
            payload = {
                "id": msg.id,
                "thread_id": thread_id,
                "sender_id": me.employee_code,
                "body": msg.body,
                "created_at": msg.created_at.isoformat(),
            }

            # Fanout to current room
            dead: Set[WebSocket] = set()
            for ws in list(thread_rooms[thread_id]):
                try:
                    await ws.send_text(json.dumps(payload))
                except Exception:
                    dead.add(ws)
            # cleanup broken sockets
            for ws in dead:
                thread_rooms[thread_id].discard(ws)

    except WebSocketDisconnect:
        # client disconnected
        pass
    except Exception:
        # any server error -> best-effort close
        try:
            await websocket.close(code=1011)  # internal error
        except Exception:
            pass
    finally:
        # cleanup room and DB session
        thread_rooms[thread_id].discard(websocket)
        db.close()
