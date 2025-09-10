# routes/chat_ws.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from typing import Dict, Set, DefaultDict
from collections import defaultdict

from db.connection import get_db
from db.Models.models_chat import ChatThread
from sqlalchemy.orm import Session

router = APIRouter(prefix="/ws", tags=["Chat WS"])

# thread_id -> set of websockets
thread_rooms: DefaultDict[int, Set[WebSocket]] = defaultdict(set)

@router.websocket("/chat/{thread_id}")
async def chat_ws(websocket: WebSocket, thread_id: int,
                  db: Session = Depends(get_db)):
    thread = db.get(ChatThread, thread_id)
    if not thread:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    thread_rooms[thread_id].add(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            # here you can parse, persist message, then broadcast
            for ws in list(thread_rooms[thread_id]):
                try:
                    await ws.send_text(data)
                except:
                    pass
    except WebSocketDisconnect:
        pass
    finally:
        thread_rooms[thread_id].discard(websocket)
