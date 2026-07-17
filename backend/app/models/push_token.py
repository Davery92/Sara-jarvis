"""Push notification token model."""
from sqlalchemy import Column, String, DateTime, Boolean
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class PushToken(Base):
    """Store push notification tokens for iOS/Android devices."""
    __tablename__ = "push_token"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    token = Column(String, nullable=False, unique=True)
    platform = Column(String, nullable=False)  # ios or android
    device_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
