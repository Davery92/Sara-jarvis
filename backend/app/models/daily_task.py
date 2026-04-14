"""Daily task model for per-day task management."""
from sqlalchemy import Column, String, Text, DateTime, Date, Boolean, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base
import uuid
from datetime import date as date_type


class DailyTask(Base):
    """A task for a specific day, with priority and completion tracking."""
    __tablename__ = "daily_task"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    task_date = Column(Date, nullable=False, default=date_type.today)
    priority = Column(String, default="normal")  # low, normal, high
    is_completed = Column(Boolean, default=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")

    def __repr__(self):
        status = "done" if self.is_completed else "pending"
        return f"<DailyTask(title='{self.title[:30]}', date={self.task_date}, {status})>"
