"""Event outbox model for Neo4j sync."""
from sqlalchemy import Column, String, Text, DateTime, Integer
from sqlalchemy.sql import func
from app.db.base import Base


class EventOutbox(Base):
    """Outbox pattern for Neo4j sync - guarantees eventual consistency."""
    __tablename__ = "event_outbox"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String, nullable=False)
    aggregate_type = Column(String, nullable=False)
    aggregate_id = Column(String, nullable=False)
    op = Column(String, nullable=False, default="UPSERT")
    payload = Column(Text, nullable=False)  # JSON
    status = Column(String, nullable=False, default="pending")  # pending, processing, completed, failed
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=5)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    processed_at = Column(DateTime, nullable=True)
    next_retry_at = Column(DateTime, nullable=True)
