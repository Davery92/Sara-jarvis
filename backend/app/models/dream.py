"""Dream insight model."""
from sqlalchemy import Column, String, Text, DateTime, Float
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class DreamInsight(Base):
    """Background consolidation insights from Sara's dreaming process."""
    __tablename__ = "dream_insight"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    dream_date = Column(DateTime, nullable=False)
    insight_type = Column(String, nullable=False)  # pattern, connection, summary, trend, forgotten_gem
    confidence = Column(Float, nullable=False)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    related_episodes = Column(Text, nullable=True)  # JSON list of episode IDs
    embedding = Column(Text, nullable=True)  # Vector handled at runtime
    surfaced_at = Column(DateTime, nullable=True)
    user_feedback = Column(String, nullable=True)  # relevant, not_relevant, interesting
    created_at = Column(DateTime, server_default=func.now())
