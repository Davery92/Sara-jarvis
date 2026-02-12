"""
Heartbeat models.

DEPRECATED: Use HEARTBEAT.md for heartbeat policy. The heartbeat_items table
is no longer read by unified_agent. These models are kept for historical
reference and read-only access. No code path should create new HeartbeatItem rows.

Legacy watchlist that the old subconscious worker read. Contained:
- Monitors: Persistent checks (e.g., background task completion)
- Time-bound: Items that expire (e.g., follow up on X by Friday)
- Conditional: Trigger-based items (e.g., if HRV < 40, suggest recovery)
"""
from sqlalchemy import Column, String, Text, DateTime, Integer, Boolean, ForeignKey, ARRAY
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base
import uuid


class HeartbeatItem(Base):
    """
    A single item in Sara's heartbeat checklist.

    Item types:
    - monitor: Persistent check that runs every cycle
    - time_bound: Expires after a date, then auto-removes
    - conditional: Only triggers when condition is met

    Check logic types:
    - background_tasks: Check for completed background tasks
    - meal_logging: Check if meals logged today
    - home_assistant: Query Home Assistant entity state
    - reminder: Simple reminder to surface to user
    - hrv_threshold: Compare HRV to threshold
    - conversation_gap: Hours since last conversation
    - custom: Sara figures it out from description
    """
    __tablename__ = "heartbeat_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    item_type = Column(String(20), nullable=False)  # monitor, time_bound, conditional
    description = Column(Text, nullable=False)
    check_logic = Column(String(50), nullable=False)

    # For time-bound items
    expires_at = Column(DateTime(timezone=True))

    # For conditional items
    condition = Column(Text)

    # Extra configuration (JSON)
    config = Column(JSONB, default={})

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(String(50), nullable=False)  # david, sara
    source_context = Column(Text)  # What conversation spawned this

    # Tracking
    last_checked_at = Column(DateTime(timezone=True))
    last_triggered_at = Column(DateTime(timezone=True))
    times_checked = Column(Integer, default=0)
    times_triggered = Column(Integer, default=0)

    # State
    is_active = Column(Boolean, default=True)

    # Notification settings
    notification_channel = Column(String(20), default='both')  # ios_push, context, both
    priority = Column(String(10), default='normal')  # low, normal, high

    # Relationships
    user = relationship("User")

    def __repr__(self):
        return f"<HeartbeatItem(id={self.id}, type='{self.item_type}', desc='{self.description[:30]}...')>"


class HeartbeatLog(Base):
    """
    Log of heartbeat runs for auditing and debugging.

    Each time the subconscious worker runs a heartbeat cycle, it logs:
    - Which items were checked
    - Which items triggered
    - What actions were taken
    """
    __tablename__ = "heartbeat_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    run_at = Column(DateTime(timezone=True), server_default=func.now())
    items_checked = Column(Integer, default=0)
    items_triggered = Column(Integer, default=0)
    triggered_item_ids = Column(ARRAY(Integer))  # Array of item IDs that triggered
    actions_taken = Column(JSONB, default=[])  # What Sara did
    notification_sent = Column(Boolean, default=False)
    run_duration_ms = Column(Integer)  # How long the check took
    error_message = Column(Text)  # If something went wrong

    # Relationships
    user = relationship("User")

    def __repr__(self):
        return f"<HeartbeatLog(run_at='{self.run_at}', triggered={self.items_triggered})>"
