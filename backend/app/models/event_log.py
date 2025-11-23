"""
Event Log Model
Persistent storage for events
"""
from sqlalchemy import Column, String, JSON, DateTime, Integer, Index
from sqlalchemy.sql import func
from app.db.session import Base


class EventLog(Base):
    """Event log for tracking all events in the system"""
    __tablename__ = "event_log"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String, unique=True, index=True, nullable=False)
    event_type = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)
    payload = Column(JSON, nullable=False, default={})
    source = Column(String, nullable=False, default="system")
    metadata = Column(JSON, nullable=False, default={})
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Indexes for common queries
    __table_args__ = (
        Index('ix_event_log_user_type', 'user_id', 'event_type'),
        Index('ix_event_log_timestamp', 'timestamp'),
    )

    def to_dict(self):
        """Convert to dictionary"""
        return {
            "id": self.id,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "user_id": self.user_id,
            "payload": self.payload,
            "source": self.source,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None
        }
