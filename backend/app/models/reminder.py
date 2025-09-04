from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base
import uuid


class Reminder(Base):
    __tablename__ = "reminder"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    text = Column(String, nullable=False)
    due_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String, default="scheduled")  # scheduled, completed, cancelled
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user = relationship("User")
    
    def __repr__(self):
        return f"<Reminder(text='{self.text[:30]}...', due_at='{self.due_at}')>"


class Timer(Base):
    __tablename__ = "timer"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    label = Column(String)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String, default="running")  # running, completed, cancelled
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user = relationship("User")
    
    def __repr__(self):
        return f"<Timer(label='{self.label}', ends_at='{self.ends_at}')>"