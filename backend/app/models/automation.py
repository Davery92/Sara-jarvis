"""
Automation models for natural language automation system.

Supports scheduled and event-driven automation tasks with
limited, safe primitives for home control, notifications, and state tracking.
"""
from sqlalchemy import (
    Column, String, Text, DateTime, Boolean, Integer,
    ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base
import uuid


class AutomationTask(Base):
    """
    User-defined automation task with schedule, actions, and conditions.

    Lifecycle: pending_confirmation -> active -> (paused|completed|failed|cancelled)
    """
    __tablename__ = "automation_task"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True)

    # Definition
    name = Column(String(255), nullable=False)  # Human-readable name
    original_intent = Column(Text, nullable=False)  # Original NL request from user
    description = Column(Text)  # Sara's parsed understanding for confirmation

    # Schedule definition (JSONB)
    # {"type": "interval", "interval_seconds": 7200, "duration_seconds": 3600}
    # {"type": "cron", "cron_expr": "0 22 * * *"}
    # {"type": "one_time", "run_at": "2024-01-15T10:00:00Z"}
    # {"type": "state_change", "entity_id": "sensor.door", "from_state": "closed", "to_state": "open"}
    schedule_definition = Column(JSONB, nullable=False)

    # Actions sequence (JSONB array)
    # [{"primitive": "home_assistant", "entity_id": "climate.thermostat", "service": "set_hvac_mode", "params": {"hvac_mode": "heat"}}]
    actions = Column(JSONB, nullable=False)

    # Optional conditions that must be met (JSONB array)
    # [{"type": "time_window", "start": "22:00", "end": "06:00"}]
    # [{"type": "state_check", "entity_id": "person.david", "state": "home"}]
    conditions = Column(JSONB, default=[])

    # Current status
    # pending_confirmation: Created but not yet confirmed by user
    # active: Running on schedule
    # paused: Temporarily paused
    # completed: Finished (hit max executions or expiration)
    # failed: Too many consecutive errors
    # cancelled: User cancelled
    status = Column(String(20), nullable=False, default="pending_confirmation", index=True)

    # Wake-up scheduling
    next_wake_at = Column(DateTime(timezone=True), nullable=True, index=True)
    current_step = Column(Integer, default=0)  # Current step in multi-step action sequence
    step_state = Column(JSONB, default={})  # Temporary state for current execution

    # Safety limits
    expires_at = Column(DateTime(timezone=True), nullable=True)  # When automation stops (default 24h)
    max_executions = Column(Integer, nullable=True)  # Max number of runs (null = unlimited)
    execution_count = Column(Integer, default=0)  # How many times it has run
    consecutive_errors = Column(Integer, default=0)  # Errors in a row (resets on success)
    last_error = Column(Text, nullable=True)  # Most recent error message

    # Audit timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    last_executed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User")
    execution_logs = relationship("AutomationExecutionLog", back_populates="task", cascade="all, delete-orphan")
    state_entries = relationship("AutomationStateStore", back_populates="task", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<AutomationTask(id='{self.id[:8]}', name='{self.name}', status='{self.status}')>"


class AutomationExecutionLog(Base):
    """
    Log of each automation execution attempt for debugging and monitoring.
    """
    __tablename__ = "automation_execution_log"

    id = Column(Integer, primary_key=True)
    task_id = Column(String, ForeignKey("automation_task.id", ondelete="CASCADE"), nullable=False, index=True)

    # Timing
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Execution details
    step_executed = Column(Integer, nullable=False)  # Which step in the actions array
    action_primitive = Column(String(50), nullable=False)  # e.g., "home_assistant", "notify"
    action_details = Column(JSONB, nullable=True)  # The full action definition

    # Result
    status = Column(String(20), nullable=False)  # success | failed | skipped | condition_not_met
    result = Column(JSONB, nullable=True)  # Return data from primitive
    error_message = Column(Text, nullable=True)

    # Relationships
    task = relationship("AutomationTask", back_populates="execution_logs")

    def __repr__(self):
        return f"<AutomationExecutionLog(task_id='{self.task_id[:8]}', step={self.step_executed}, status='{self.status}')>"


class AutomationStateStore(Base):
    """
    Key-value store for automation tasks to track state between executions.
    Used for change detection (e.g., "alert if garage door opens").
    """
    __tablename__ = "automation_state_store"

    id = Column(Integer, primary_key=True)
    task_id = Column(String, ForeignKey("automation_task.id", ondelete="CASCADE"), nullable=False, index=True)

    key = Column(String(255), nullable=False)  # State key (e.g., "garage_state")
    value = Column(JSONB, nullable=True)  # Current value
    previous_value = Column(JSONB, nullable=True)  # Previous value for comparison

    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Unique constraint on (task_id, key)
    __table_args__ = (
        UniqueConstraint("task_id", "key", name="uq_automation_state_task_key"),
    )

    # Relationships
    task = relationship("AutomationTask", back_populates="state_entries")

    def __repr__(self):
        return f"<AutomationStateStore(task_id='{self.task_id[:8]}', key='{self.key}')>"


class RegisteredEndpoint(Base):
    """
    Allowlisted HTTP endpoints that automations can call.
    Managed by admin to ensure safety.
    """
    __tablename__ = "registered_endpoint"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)  # e.g., "staging_api"
    description = Column(Text, nullable=True)  # What this endpoint is for

    # Connection details
    base_url = Column(String(500), nullable=False)  # e.g., "https://staging.example.com"

    # Authentication
    auth_type = Column(String(20), nullable=False, default="none")  # bearer, api_key, basic, none
    auth_header = Column(String(100), nullable=True)  # Header name for auth (e.g., "Authorization", "X-API-Key")
    auth_secret_env = Column(String(100), nullable=True)  # Environment variable name holding the secret

    # Rate limiting
    rate_limit_per_minute = Column(Integer, default=60)

    # Path restrictions
    allowed_paths = Column(JSONB, default=[])  # e.g., ["/health", "/api/status"]
    allowed_methods = Column(JSONB, default=["GET"])  # e.g., ["GET", "POST"]

    # Status
    is_active = Column(Boolean, default=True)

    # Audit
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<RegisteredEndpoint(name='{self.name}', base_url='{self.base_url}')>"


# Indexes for common queries
Index("idx_automation_task_next_wake", AutomationTask.next_wake_at, AutomationTask.status)
Index("idx_automation_task_user_status", AutomationTask.user_id, AutomationTask.status)
Index("idx_automation_log_task_started", AutomationExecutionLog.task_id, AutomationExecutionLog.started_at.desc())
