# db/models_chat.py

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Enum, Index, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from db.connection import Base
from db.models import UserDetails  # reuse existing

class ThreadType(str, enum.Enum):
    DIRECT = "DIRECT"
    GROUP = "GROUP"

class ChatThread(Base):
    __tablename__ = "chat_threads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(Enum(ThreadType), nullable=False, index=True)
    name = Column(String(120), nullable=True)        # only for GROUP
    branch_id = Column(Integer, nullable=True, index=True)  # for DIRECT: shared branch; for GROUP: group branch; can be NULL for superadmin multi-branch groups

    created_by = Column(String(100), ForeignKey("crm_user_details.employee_code"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # relationships
    participants = relationship("ChatParticipant", back_populates="thread", cascade="all, delete-orphan")
    messages = relationship("ChatMessage", back_populates="thread", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_chat_threads_type_branch", "type", "branch_id"),
    )

class ChatParticipant(Base):
    __tablename__ = "chat_participants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(Integer, ForeignKey("chat_threads.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(100), ForeignKey("crm_user_details.employee_code", ondelete="CASCADE"), nullable=False, index=True)
    is_admin = Column(Boolean, default=False, nullable=False)

    joined_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    thread = relationship("ChatThread", back_populates="participants")
    user = relationship("UserDetails")

    __table_args__ = (
        UniqueConstraint("thread_id", "user_id", name="uq_chat_participant_thread_user"),
        Index("ix_chat_participants_user_thread", "user_id", "thread_id"),
    )

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(Integer, ForeignKey("chat_threads.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id = Column(String(100), ForeignKey("crm_user_details.employee_code", ondelete="SET NULL"), nullable=True, index=True)

    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    thread = relationship("ChatThread", back_populates="messages")
    sender = relationship("UserDetails")

    __table_args__ = (
        Index("ix_chat_messages_thread_time", "thread_id", "created_at"),
    )

class MessageRead(Base):
    __tablename__ = "chat_message_reads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(Integer, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(100), ForeignKey("crm_user_details.employee_code", ondelete="CASCADE"), nullable=False, index=True)
    read_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_msg_read_user"),
    )
