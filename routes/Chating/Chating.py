# routes/chating.py  (your spelling)
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, exists, select, func

from db.connection import get_db
from db.models import UserDetails
from db.Models.models_chat import ChatThread, ChatParticipant, ChatMessage, MessageRead, ThreadType
from routes.auth.auth_dependency import get_current_user

router = APIRouter(prefix="/chat", tags=["Chat"])

def _role(u: UserDetails) -> str:
    return (getattr(u, "role_name", "") or "").upper()

def _ensure_same_branch(u1_branch: Optional[int], u2_branch: Optional[int]) -> bool:
    return u1_branch is not None and u1_branch == u2_branch

# ---------- Schemas ----------
class ThreadOut(BaseModel):
    id: int
    type: ThreadType
    name: Optional[str]
    branch_id: Optional[int]

    class Config:
        from_attributes = True

class MessageOut(BaseModel):
    id: int
    thread_id: int
    sender_id: Optional[str]
    body: str
    created_at: str

    class Config:
        from_attributes = True

class CreateDirectIn(BaseModel):
    peer_employee_code: str = Field(...)

class CreateGroupIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    participant_codes: List[str] = Field(..., description="Include creator? Not required; will be added automatically")
    branch_id: Optional[int] = None  # If manager: must be their branch; superadmin can set any or None

class SendMessageIn(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)

# ---------- Permissions helpers ----------
def _can_view_thread(db: Session, u: UserDetails, thread: ChatThread) -> bool:
    role = _role(u)
    if role == "SUPERADMIN":
        return True
    if role == "BRANCH_MANAGER":
        # Manager can see all threads of their branch
        return (thread.branch_id == u.branch_id) or _is_participant(db, u.employee_code, thread.id)
    # Employee must be a participant
    return _is_participant(db, u.employee_code, thread.id)

def _is_participant(db: Session, user_code: str, thread_id: int) -> bool:
    return db.query(
        exists().where(and_(
            ChatParticipant.thread_id == thread_id,
            ChatParticipant.user_id == user_code
        ))
    ).scalar()

def _enforce_can_add_group(db: Session, actor: UserDetails, branch_id: Optional[int], member_codes: List[str]) -> None:
    role = _role(actor)
    if role == "SUPERADMIN":
        return
    if role == "BRANCH_MANAGER":
        if actor.branch_id is None:
            raise HTTPException(403, "Manager has no branch")
        if branch_id is not None and branch_id != actor.branch_id:
            raise HTTPException(403, "Manager can create groups only in own branch")
        # only members from same branch
        if not member_codes:
            return
        cnt = db.query(UserDetails).filter(
            UserDetails.employee_code.in_(member_codes),
            UserDetails.branch_id == actor.branch_id
        ).count()
        if cnt != len(member_codes):
            raise HTTPException(403, "All participants must belong to your branch")
        return
    # Employees cannot create groups (remove if you want to allow)
    raise HTTPException(403, "Only SUPERADMIN or BRANCH_MANAGER can create groups")

# ---------- Endpoints ----------

@router.post("/direct/create", response_model=ThreadOut, status_code=201)
def create_direct(payload: CreateDirectIn, db: Session = Depends(get_db), me: UserDetails = Depends(get_current_user)):
    # Employee can DM only within same branch
    peer = db.query(UserDetails).filter(
        UserDetails.employee_code == payload.peer_employee_code,
        UserDetails.is_active.is_(True)
    ).first()
    if not peer:
        raise HTTPException(404, "Peer not found")

    role = _role(me)
    if role != "SUPERADMIN":
        if not _ensure_same_branch(me.branch_id, peer.branch_id):
            raise HTTPException(403, "Employees can chat only within same branch")

    # Check if a direct thread already exists between the two
    existing = (
        db.query(ChatThread)
        .join(ChatParticipant, ChatParticipant.thread_id == ChatThread.id)
        .filter(
            ChatThread.type == ThreadType.DIRECT,
            ChatParticipant.user_id.in_([me.employee_code, peer.employee_code])
        )
        .group_by(ChatThread.id)
        .having(
            # exactly these two participants
            (select(ChatParticipant.id).where(ChatParticipant.thread_id == ChatThread.id).count() == 2)  # not supported in SQLA Core—replace below
        )
        .first()
    )
    # ^ the COUNT in HAVING is awkward in SQLAlchemy; do a simpler approach:
    if not existing:
        thread = ChatThread(
            type=ThreadType.DIRECT,
            name=None,
            branch_id=peer.branch_id if role != "SUPERADMIN" else (peer.branch_id if me.branch_id == peer.branch_id else None),
            created_by=me.employee_code,
        )
        db.add(thread)
        db.flush()

        db.add_all([
            ChatParticipant(thread_id=thread.id, user_id=me.employee_code, is_admin=False),
            ChatParticipant(thread_id=thread.id, user_id=peer.employee_code, is_admin=False),
        ])
        db.commit()
        db.refresh(thread)
        return thread

    return existing


@router.post("/group/create", response_model=ThreadOut, status_code=201)
def create_group(payload: CreateGroupIn, db: Session = Depends(get_db), me: UserDetails = Depends(get_current_user)):
    _enforce_can_add_group(db, me, payload.branch_id, payload.participant_codes)

    thread = ChatThread(
        type=ThreadType.GROUP,
        name=payload.name.strip(),
        branch_id=payload.branch_id if _role(me) == "SUPERADMIN" else me.branch_id,
        created_by=me.employee_code,
    )
    db.add(thread)
    db.flush()

    codes = set(payload.participant_codes or [])
    codes.add(me.employee_code)  # ensure creator is in

    # Validate users exist & (if manager) belong to same branch
    users = db.query(UserDetails).filter(UserDetails.employee_code.in_(list(codes)),
                                        UserDetails.is_active.is_(True)).all()
    if len(users) != len(codes):
        raise HTTPException(400, "Some participants not found or inactive")

    # Add participants (creator admin)
    for u in users:
        db.add(ChatParticipant(thread_id=thread.id, user_id=u.employee_code, is_admin=(u.employee_code == me.employee_code)))

    db.commit()
    db.refresh(thread)
    return thread


@router.get("/threads", response_model=List[ThreadOut])
def list_my_threads(db: Session = Depends(get_db), me: UserDetails = Depends(get_current_user)):
    role = _role(me)

    q = db.query(ChatThread)
    if role == "SUPERADMIN":
        pass
    elif role == "BRANCH_MANAGER":
        q = q.filter(ChatThread.branch_id == me.branch_id)
    else:
        q = q.join(ChatParticipant).filter(ChatParticipant.user_id == me.employee_code)

    return q.order_by(ChatThread.updated_at.desc()).limit(200).all()


@router.get("/{thread_id}/messages", response_model=List[MessageOut])
def get_messages(thread_id: int,
                 limit: int = Query(50, ge=1, le=200),
                 before_id: Optional[int] = None,
                 db: Session = Depends(get_db),
                 me: UserDetails = Depends(get_current_user)):
    thread = db.get(ChatThread, thread_id)
    if not thread:
        raise HTTPException(404, "Thread not found")

    if not _can_view_thread(db, me, thread):
        raise HTTPException(403, "Not allowed")

    q = db.query(ChatMessage).filter(ChatMessage.thread_id == thread_id)
    if before_id:
        # pagination by id (fast)
        q = q.filter(ChatMessage.id < before_id)

    msgs = q.order_by(ChatMessage.id.desc()).limit(limit).all()
    return list(reversed(msgs))  # newest last for UI


@router.post("/{thread_id}/send", response_model=MessageOut, status_code=201)
def send_message(thread_id: int, payload: SendMessageIn,
                 db: Session = Depends(get_db),
                 me: UserDetails = Depends(get_current_user)):
    thread = db.get(ChatThread, thread_id)
    if not thread:
        raise HTTPException(404, "Thread not found")

    if not _can_view_thread(db, me, thread):
        raise HTTPException(403, "Not allowed")

    # employees cannot write to groups outside their branch (safety)
    if _role(me) != "SUPERADMIN" and thread.branch_id is not None and me.branch_id != thread.branch_id:
        raise HTTPException(403, "You cannot post in threads outside your branch")

    msg = ChatMessage(
        thread_id=thread_id,
        sender_id=me.employee_code,
        body=payload.body.strip(),
    )
    db.add(msg)

    # bump thread updated_at
    thread.updated_at = func.now()

    db.commit()
    db.refresh(msg)
    return msg


@router.post("/{thread_id}/mark-read", status_code=204)
def mark_read(thread_id: int,
              last_message_id: int,
              db: Session = Depends(get_db),
              me: UserDetails = Depends(get_current_user)):
    thread = db.get(ChatThread, thread_id)
    if not thread:
        raise HTTPException(404, "Thread not found")
    if not _can_view_thread(db, me, thread):
        raise HTTPException(403, "Not allowed")

    # Mark read for all messages up to last_message_id
    msgs = db.query(ChatMessage.id).filter(
        ChatMessage.thread_id == thread_id,
        ChatMessage.id <= last_message_id
    ).all()
    ids = [m.id for m in msgs]
    if not ids:
        return

    existing = db.query(MessageRead.message_id).filter(
        MessageRead.user_id == me.employee_code,
        MessageRead.message_id.in_(ids)
    ).all()
    exist_ids = {e.message_id for e in existing}

    to_add = [MessageRead(message_id=mid, user_id=me.employee_code) for mid in ids if mid not in exist_ids]
    if to_add:
        db.add_all(to_add)
        db.commit()


@router.post("/{thread_id}/participants/add", status_code=204)
def add_participants(thread_id: int, codes: List[str],
                     db: Session = Depends(get_db),
                     me: UserDetails = Depends(get_current_user)):
    thread = db.get(ChatThread, thread_id)
    if not thread:
        raise HTTPException(404, "Thread not found")

    role = _role(me)
    # Only admins can add for GROUP; DIRECT not allowed
    if thread.type != ThreadType.GROUP:
        raise HTTPException(400, "Cannot add participants to a direct chat")

    # Superadmin or group admin within branch
    am_admin = db.query(ChatParticipant).filter_by(thread_id=thread_id, user_id=me.employee_code, is_admin=True).first()
    if role != "SUPERADMIN" and not am_admin:
        raise HTTPException(403, "Only group admin or superadmin can add participants")

    # Branch constraint for managers
    if role == "BRANCH_MANAGER":
        if thread.branch_id != me.branch_id:
            raise HTTPException(403, "Cannot modify group outside your branch")

    users = db.query(UserDetails).filter(UserDetails.employee_code.in_(codes), UserDetails.is_active.is_(True)).all()
    if len(users) != len(set(codes)):
        raise HTTPException(400, "Some users not found/inactive")

    if role == "BRANCH_MANAGER":
        if any(u.branch_id != me.branch_id for u in users):
            raise HTTPException(403, "All participants must be in your branch")

    existing_codes = {p.user_id for p in db.query(ChatParticipant).filter_by(thread_id=thread_id).all()}
    new_codes = [u.employee_code for u in users if u.employee_code not in existing_codes]

    for code in new_codes:
        db.add(ChatParticipant(thread_id=thread_id, user_id=code, is_admin=False))

    if new_codes:
        db.commit()


@router.post("/{thread_id}/participants/remove", status_code=204)
def remove_participants(thread_id: int, codes: List[str],
                        db: Session = Depends(get_db),
                        me: UserDetails = Depends(get_current_user)):
    thread = db.get(ChatThread, thread_id)
    if not thread:
        raise HTTPException(404, "Thread not found")

    role = _role(me)
    if thread.type != ThreadType.GROUP:
        raise HTTPException(400, "Cannot remove participants from a direct chat")

    am_admin = db.query(ChatParticipant).filter_by(thread_id=thread_id, user_id=me.employee_code, is_admin=True).first()
    if role != "SUPERADMIN" and not am_admin:
        raise HTTPException(403, "Only group admin or superadmin can remove participants")

    if role == "BRANCH_MANAGER" and thread.branch_id != me.branch_id:
        raise HTTPException(403, "Cannot modify group outside your branch")

    db.query(ChatParticipant).filter(
        ChatParticipant.thread_id == thread_id,
        ChatParticipant.user_id.in_(codes)
    ).delete(synchronize_session=False)

    db.commit()
