from sqlalchemy import Column, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base
import uuid


class Achievement(Base):
    __tablename__ = "achievement"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    type = Column(String, nullable=False)  # 'productivity', 'milestone', 'learning', 'collaboration'
    title = Column(String, nullable=False)
    description = Column(Text)
    icon = Column(String)  # emoji or icon name
    earned_at = Column(DateTime(timezone=True), server_default=func.now())
    celebrated = Column(Boolean, default=False)

    # Relationships
    user = relationship("User")

    def __repr__(self):
        return f"<Achievement(title='{self.title}', type='{self.type}')>"
