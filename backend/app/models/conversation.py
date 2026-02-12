"""Conversation and turn models."""
from sqlalchemy import Column, String, Text, DateTime, Integer
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class Conversation(Base):
    """Tracks conversation sessions."""
    __tablename__ = "conversation"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    title = Column(String, default="")
    summary = Column(Text, default="")
    total_messages = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())


class ConversationTurn(Base):
    """Individual message in a conversation."""
    __tablename__ = "conversation_turn"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    message_index = Column(Integer, nullable=False)
    embedding = Column(Text, nullable=True)  # Vector handled at runtime
    created_at = Column(DateTime, server_default=func.now())
