"""Background task model."""
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class BackgroundTask(Base):
    """Tracks background agent tasks that run independently of user sessions."""
    __tablename__ = "background_task"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="pending")  # pending, running, completed, failed, needs_clarification
    task_type = Column(String, nullable=False, default="research")
    original_query = Column(Text, nullable=False)
    result_note_id = Column(String, nullable=True)
    workspace_folder_id = Column(String, nullable=True)
    clarification_question = Column(Text, nullable=True)
    clarification_response = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    task_metadata = Column(JSONB, default={})
    created_at = Column(DateTime, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
