"""System event model — durable side of the narrator's broadcast channel.

The narrator service writes a row here for every utterance (and every
intentionally-silent moment). The ticker, audit endpoints, and
anti-repetition prompt context all read from this table.
"""
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.db.base import Base


class SystemEvent(Base):
    __tablename__ = "system_event"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('roast','observation','achievement','patch_note',"
            "'sponsored','grudging','deflected')",
            name="ck_system_event_severity_valid",
        ),
        Index("ix_system_event_user_created", "user_id", "created_at"),
        Index("ix_system_event_trigger_created", "trigger_name", "created_at"),
        {"extend_existing": True},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id = Column(String(64), nullable=False)
    type = Column(String(32), nullable=False)
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    subtitle = Column(Text, nullable=True)
    severity = Column(String(32), nullable=False)
    trigger_name = Column(String(64), nullable=False)
    trigger_context = Column(JSONB, nullable=False, default=dict)
    ttl_seconds = Column(Integer, nullable=False, default=30)
    sound = Column(String(64), nullable=True)
    delivered_to = Column(JSONB, nullable=False, default=list)
    suppressed = Column(Boolean, nullable=False, default=False)
    suppression_reason = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
