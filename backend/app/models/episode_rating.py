"""Episode rating model."""
from sqlalchemy import Column, String, DateTime, Integer, Float, ForeignKey
from sqlalchemy.sql import func
from app.db.base import Base


class EpisodeRating(Base):
    """Episode rating system for user feedback and memory quality scoring."""
    __tablename__ = "episode_rating"
    __table_args__ = {'extend_existing': True}

    episode_id = Column(String, ForeignKey('episode.id', ondelete='CASCADE'), primary_key=True)
    user_rating = Column(Integer, nullable=True)  # 1-5 star rating
    rating_count = Column(Integer, default=0)
    average_rating = Column(Float, default=0.0)
    rating_sum = Column(Integer, default=0)
    last_rated = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())
