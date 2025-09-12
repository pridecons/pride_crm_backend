# utils/files.py
import os, uuid
from typing import Tuple
from fastapi import UploadFile

CHAT_UPLOAD_DIR = os.getenv("CHAT_UPLOAD_DIR", "static/uploads/chat")
STATIC_BASE_URL = os.getenv("STATIC_BASE_URL", "/static/uploads/chat")

os.makedirs(CHAT_UPLOAD_DIR, exist_ok=True)

def _safe_name(name: str) -> str:
    name = os.path.basename(name or "").strip() or "file"
    return name.replace("\\", "_").replace("/", "_")

async def save_chat_upload(file: UploadFile, thread_id: int) -> Tuple[str, str, int]:
    """
    Save the uploaded file under static/uploads/chat/{thread_id}/<uuid>__orig.ext
    Return (public_url, original_filename, size_bytes)
    """
    folder = os.path.join(CHAT_UPLOAD_DIR, str(thread_id))
    os.makedirs(folder, exist_ok=True)

    orig = _safe_name(file.filename)
    uid = uuid.uuid4().hex
    fname = f"{uid}__{orig}"
    path = os.path.join(folder, fname)

    size = 0
    with open(path, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            out.write(chunk)
    await file.close()

    url = f"{STATIC_BASE_URL}/{thread_id}/{fname}"
    return url, orig, size
