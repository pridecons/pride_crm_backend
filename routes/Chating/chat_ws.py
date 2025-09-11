# # routes/chat_ws.py
# from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
# from typing import Dict, Set, DefaultDict
# from collections import defaultdict

# from db.connection import get_db
# from db.Models.models_chat import ChatThread
# from sqlalchemy.orm import Session

# router = APIRouter(prefix="/ws", tags=["Chat WS"])

# # thread_id -> set of websockets
# thread_rooms: DefaultDict[int, Set[WebSocket]] = defaultdict(set)

# @router.websocket("/chat/{thread_id}")
# async def chat_ws(websocket: WebSocket, thread_id: int,
#                   db: Session = Depends(get_db)):
#     thread = db.get(ChatThread, thread_id)
#     if not thread:
#         await websocket.close(code=4404)
#         return

#     await websocket.accept()
#     thread_rooms[thread_id].add(websocket)

#     try:
#         while True:
#             data = await websocket.receive_text()
#             # here you can parse, persist message, then broadcast
#             for ws in list(thread_rooms[thread_id]):
#                 try:
#                     await ws.send_text(data)
#                 except:
#                     pass
#     except WebSocketDisconnect:
#         pass
#     finally:
#         thread_rooms[thread_id].discard(websocket)
# routes/chat_ws.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from typing import Dict, Set, DefaultDict, Any
from collections import defaultdict
import json

from db.connection import get_db
from db.Models.models_chat import ChatThread
from sqlalchemy.orm import Session

router = APIRouter(prefix="/ws", tags=["Chat WS"])

class RoomHub:
    """
    thread_id -> set[WebSocket]
    Provides broadcast helpers so REST handlers can push events to sockets.
    """
    def __init__(self) -> None:
        self._rooms: DefaultDict[int, Set[WebSocket]] = defaultdict(set)

    def add(self, thread_id: int, ws: WebSocket) -> None:
        self._rooms[thread_id].add(ws)

    def discard(self, thread_id: int, ws: WebSocket) -> None:
        room = self._rooms.get(thread_id)
        if room is not None:
            room.discard(ws)
            if not room:
                # optional: free empty set
                self._rooms.pop(thread_id, None)

    async def broadcast_text(self, thread_id: int, text: str) -> None:
        for ws in list(self._rooms.get(thread_id, ())):
            try:
                await ws.send_text(text)
            except Exception:
                # best-effort: drop broken sockets
                self.discard(thread_id, ws)

    async def broadcast_json(self, thread_id: int, payload: Any) -> None:
        # ensure JSON serializable (pydantic dumps are fine too)
        text = json.dumps(payload, default=str)
        await self.broadcast_text(thread_id, text)

room_hub = RoomHub()  # <-- import this in REST module


@router.websocket("/chat/{thread_id}")
async def chat_ws(
    websocket: WebSocket,
    thread_id: int,
    db: Session = Depends(get_db),
):
    # Validate thread exists
    thread = db.get(ChatThread, thread_id)
    if not thread:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    room_hub.add(thread_id, websocket)

    try:
        # We don't require clients to send anything over WS.
        # Keep the connection alive; optionally handle pings or client events.
        while True:
            try:
                # Receive and ignore (could be typing/ping in future)
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
            except Exception:
                # ignore malformed frames; keep loop
                pass
    finally:
        room_hub.discard(thread_id, websocket)
