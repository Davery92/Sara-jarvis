"""
Jarvis Background Tasks Model - For autonomous multi-tool tasks

This model tracks background research, analysis, and multi-step tasks 
that Jarvis performs autonomously.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base
import enum
import uuid


class TaskKind(str, enum.Enum):
    RESEARCH = "research"
    DRAFT = "draft"
    COMPARE = "compare"
    SUMMARIZE = "summarize"
    ANALYZE = "analyze"


class TaskState(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_CONFIRM = "waiting_confirm"  # High-impact actions need approval
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JarvisTask(Base):
    __tablename__ = "jarvis_tasks"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id"), nullable=False)
    
    # Task Definition
    kind = Column(Enum(TaskKind), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    inputs = Column(JSONB, default=dict)  # Task input parameters
    
    # Execution State
    state = Column(Enum(TaskState), default=TaskState.QUEUED, nullable=False)
    progress = Column(Integer, default=0)  # 0-100 percentage
    estimated_duration_minutes = Column(Integer)
    
    # Results and Output
    result = Column(JSONB, default=dict)  # Task outputs
    summary = Column(Text)  # Human-readable summary
    artifacts = Column(JSONB, default=list)  # Created files, notes, etc.
    
    # Audit and Confirmation
    audit_log = Column(JSONB, default=list)  # [{ts, actor, action, payload, rationale}]
    pending_confirmations = Column(JSONB, default=list)  # High-impact actions awaiting approval
    
    # Metadata
    priority = Column(Integer, default=5)
    timeout_minutes = Column(Integer, default=8)  # Max execution time
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=2)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Worker Information
    worker_id = Column(String(50))  # Which worker is processing this
    queue_name = Column(String(50), default="default")
    
    def __repr__(self):
        return f"<JarvisTask(id={self.id}, kind={self.kind}, state={self.state}, title='{self.title[:30]}')>"
    
    @property
    def is_running(self) -> bool:
        return self.state in [TaskState.RUNNING, TaskState.WAITING_CONFIRM]
    
    @property
    def is_complete(self) -> bool:
        return self.state in [TaskState.DONE, TaskState.FAILED, TaskState.CANCELLED]
    
    def add_audit_entry(self, actor: str, action: str, payload: dict = None, rationale: str = None):
        """Add an entry to the audit log"""
        entry = {
            "timestamp": func.now(),
            "actor": actor,  # "jarvis" or "user"
            "action": action,
            "payload": payload or {},
            "rationale": rationale
        }
        
        if not self.audit_log:
            self.audit_log = []
        
        self.audit_log = self.audit_log + [entry]