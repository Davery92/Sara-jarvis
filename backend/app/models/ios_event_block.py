"""Blocklist for iOS calendar events the user has suppressed in Sara."""
from sqlalchemy import Column, String, DateTime, ForeignKey, PrimaryKeyConstraint
from sqlalchemy.sql import func
from app.db.base import Base


class IOSEventBlock(Base):
    """An iOS event the user removed in Sara; sync handler must not re-insert it."""
    __tablename__ = "ios_event_block"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "ios_event_id"),
        {"extend_existing": True},
    )

    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    ios_event_id = Column(String, nullable=False)
    ios_calendar_id = Column(String, nullable=True)
    title = Column(String, nullable=True)
    suppressed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
