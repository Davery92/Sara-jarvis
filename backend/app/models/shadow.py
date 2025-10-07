"""
Shadow Mode Models
Time-boxed work capture with intelligent session summaries
"""
from sqlalchemy import Column, String, Text, DateTime, Integer, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class ShadowSession(Base):
    """Shadow Mode work capture session"""
    __tablename__ = "shadow_session"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    device_id = Column(String, nullable=True)  # Which device is capturing (for multi-device future)

    # Session metadata
    status = Column(String, default="active")  # active, paused, wrapped, committed
    duration_minutes = Column(Integer, nullable=True)  # Planned duration (null = no limit)
    privacy_mode = Column(Boolean, default=False)  # Redact titles/URLs if True

    # Lifecycle timestamps
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    paused_at = Column(DateTime(timezone=True), nullable=True)
    resumed_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)

    # Optional context
    context = Column(String, nullable=True)  # e.g., "standup meeting", "deep work"
    calendar_event_id = Column(String, ForeignKey("event.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User")
    calendar_event = relationship("Event", foreign_keys=[calendar_event_id])
    events = relationship("ShadowEvent", back_populates="session", cascade="all, delete-orphan")
    notes = relationship("ShadowNote", back_populates="session", cascade="all, delete-orphan")
    summary = relationship("ShadowSummary", back_populates="session", uselist=False, cascade="all, delete-orphan")


class ShadowEvent(Base):
    """Raw metadata events captured during session"""
    __tablename__ = "shadow_event"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("shadow_session.id", ondelete="CASCADE"), nullable=False)

    # Event identification
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    event_type = Column(String, nullable=False)  # browser, editor, terminal, fs, calendar, presence
    app_name = Column(String, nullable=True)  # Chrome, VS Code, Terminal, etc.

    # Event payload (flexible JSON)
    event_metadata = Column("event_metadata", JSON, nullable=True)  # {title, url, file_path, command, etc.}

    # Classification (populated by classifier)
    classified_as = Column(String, nullable=True)  # task, decision, question, idea, reference
    tags = Column(JSON, default=list)  # ["coding", "debugging", "authentication"]

    # Relationships
    session = relationship("ShadowSession", back_populates="events")


class ShadowNote(Base):
    """User-provided notes during session (chat or voice)"""
    __tablename__ = "shadow_note"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("shadow_session.id", ondelete="CASCADE"), nullable=False)

    # Note metadata
    note_type = Column(String, nullable=False)  # task, decision, question, idea, bookmark
    content = Column(Text, nullable=False)
    source = Column(String, default="chat")  # chat, voice

    # Optional structured data
    due_date = Column(DateTime(timezone=True), nullable=True)  # For tasks
    priority = Column(String, nullable=True)  # low, medium, high

    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    session = relationship("ShadowSession", back_populates="notes")


class ShadowSummary(Base):
    """Generated end-of-session summary"""
    __tablename__ = "shadow_summary"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("shadow_session.id", ondelete="CASCADE"), nullable=False, unique=True)

    # Summary sections (JSON lists)
    decisions = Column(JSON, default=list)  # ["Chose Redis for session state", ...]
    tasks = Column(JSON, default=list)  # [{"task": "...", "due": "..."}, ...]
    questions = Column(JSON, default=list)  # ["How to handle offline mode?", ...]
    ideas = Column(JSON, default=list)  # ["Auto-raise wake threshold during media", ...]
    refs = Column(JSON, default=list)  # [{"type": "file", "path": "..."}, ...] - renamed from 'references'

    # Timeline (compressed 2-5min windows)
    timeline = Column(JSON, default=list)  # [{"time": "14:30", "activity": "..."}, ...]

    # Changeset (files modified, commits)
    changeset = Column(JSON, default=dict)  # {"files": [...], "commits": [...]}

    # Full text summary (markdown)
    full_text = Column(Text, nullable=True)

    # Commit status
    committed = Column(Boolean, default=False)
    committed_note_id = Column(String, ForeignKey("note.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    session = relationship("ShadowSession", back_populates="summary")
    committed_note = relationship("Note", foreign_keys=[committed_note_id])
