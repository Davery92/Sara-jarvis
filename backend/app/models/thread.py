from sqlalchemy import Column, String, Text, DateTime, Integer, Boolean, ARRAY, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base
import uuid


class ConversationThread(Base):
    __tablename__ = "conversation_thread"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    summary = Column(Text)
    auto_generated = Column(Boolean, default=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    last_activity = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    message_count = Column(Integer, default=0)
    tags = Column(ARRAY(String), default=[])
    archived = Column(Boolean, default=False)

    # Relationships
    user = relationship("User")

    def __repr__(self):
        return f"<ConversationThread(title='{self.title}', messages={self.message_count})>"


class EpisodeThreadMapping(Base):
    __tablename__ = "episode_thread_mapping"

    episode_id = Column(String, ForeignKey("episode.id", ondelete="CASCADE"), primary_key=True)
    thread_id = Column(String, ForeignKey("conversation_thread.id", ondelete="CASCADE"), primary_key=True)

    def __repr__(self):
        return f"<EpisodeThreadMapping(episode={self.episode_id}, thread={self.thread_id})>"
