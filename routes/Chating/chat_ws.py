# routes/Chating/chat_ws.py
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
                self._rooms.pop(thread_id, None)

    async def broadcast_text(self, thread_id: int, text: str) -> None:
        for ws in list(self._rooms.get(thread_id, ())):
            try:
                await ws.send_text(text)
            except Exception:
                self.discard(thread_id, ws)

    async def broadcast_json(self, thread_id: int, payload: Any) -> None:
        text = json.dumps(payload, default=str)
        await self.broadcast_text(thread_id, text)

room_hub = RoomHub()

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
        while True:
            try:
                await websocket.receive_text()  # ignore/keepalive
            except WebSocketDisconnect:
                break
            except Exception:
                pass
    finally:
        room_hub.discard(thread_id, websocket)
