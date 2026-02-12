"""Context window and mode models."""
from sqlalchemy import Column, String, Text, DateTime, Integer
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class ContextWindow(Base):
    """Context window configurations for dynamic memory retrieval."""
    __tablename__ = "context_window"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    window_type = Column(String, nullable=False)  # temporal, topic, emotional, importance, hybrid
    parameters = Column(Text, nullable=False)  # JSON
    last_used = Column(DateTime, nullable=True)
    use_count = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())


class ContextMode(Base):
    """User's current context mode for dynamic memory retrieval."""
    __tablename__ = "context_modes"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, unique=True)
    current_mode = Column(String, default="full")  # full, recent, minimal, fitness, work, learning
    updated_at = Column(DateTime, server_default=func.now())
