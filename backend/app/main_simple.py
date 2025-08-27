from fastapi import FastAPI, Depends, HTTPException, status, Response, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy import create_engine, Column, String, DateTime, Text, Integer, Float, Boolean, text
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.sql import func
try:
    from pgvector.sqlalchemy import Vector
    PGVECTOR_AVAILABLE = True
except ImportError:
    PGVECTOR_AVAILABLE = False
    Vector = None
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone, date
import jwt
import uuid
import httpx
import json
import logging
import os
import aiofiles
import asyncio
import json
from fastapi import UploadFile
from app.tools.registry import tool_registry

# Import vulnerability services
try:
    from app.services.vulnerability_service import fetch_all_vulnerability_data, VulnerabilityProcessor
    from app.services.vulnerability_notifications import VulnerabilityNotificationService, notify_report_ready
    VULNERABILITY_SERVICES_AVAILABLE = True
except ImportError as e:
    logging.warning(f"Vulnerability services not available: {e}")
    VULNERABILITY_SERVICES_AVAILABLE = False

# Import GTKY service
try:
    from app.services.gtky_service import GTKYService
    GTKY_SERVICE_AVAILABLE = True
except ImportError as e:
    logging.warning(f"GTKY service not available: {e}")
    GTKY_SERVICE_AVAILABLE = False

# Import reflection service
try:
    from app.services.reflection_service import ReflectionService
    REFLECTION_SERVICE_AVAILABLE = True
except ImportError as e:
    logging.warning(f"Reflection service not available: {e}")
    REFLECTION_SERVICE_AVAILABLE = False

# Configure logging first
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Optional imports for vectorization (graceful degradation)
try:
    import chromadb
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    logger.warning("ChromaDB not available - vector search will be disabled")

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logger.warning("Sentence Transformers not available - embeddings will be disabled")

# Configuration
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Sara")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sara_hub.db")
JWT_SECRET = os.getenv("JWT_SECRET", "sara-hub-jwt-secret-development")
JWT_ALGORITHM = "HS256"
CORS_ORIGINS = ["https://sara.avery.cloud", "http://localhost:3000", "http://10.185.1.180:3000", "http://sara.avery.cloud"]

# NTFY Configuration
NTFY_SERVER_URL = os.getenv("NTFY_SERVER_URL", "http://10.185.1.8:8889")
NTFY_ENABLED = os.getenv("NTFY_ENABLED", "true").lower() == "true"
NTFY_TIMERS_TOPIC = os.getenv("NTFY_TIMERS_TOPIC", "sara")
NTFY_REMINDERS_TOPIC = os.getenv("NTFY_REMINDERS_TOPIC", "sara")
NTFY_DOCUMENTS_TOPIC = os.getenv("NTFY_DOCUMENTS_TOPIC", "sara")
NTFY_SYSTEM_TOPIC = os.getenv("NTFY_SYSTEM_TOPIC", "sara")
NTFY_VULNERABILITY_TOPIC = os.getenv("NTFY_VULNERABILITY_TOPIC", "sara")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://100.104.68.115:11434/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-oss:120b")
# Smaller, faster model for notifications (uses same endpoint but different model)
OPENAI_NOTIFICATION_MODEL = os.getenv("OPENAI_NOTIFICATION_MODEL", "gpt-oss:20b")
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "http://100.104.68.115:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
UPLOAD_DIR = "./uploads"
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_MIME_TYPES = [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/plain",
    "text/markdown",
    "text/csv"
]

# Database setup
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Models
class User(Base):
    __tablename__ = "app_user"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

class Note(Base):
    __tablename__ = "note"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    folder_id = Column(String, nullable=True)  # Foreign key to folder
    title = Column(String, default="")
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

class Folder(Base):
    __tablename__ = "folder"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    parent_id = Column(String, nullable=True)  # Self-referencing for hierarchy
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

class NoteConnection(Base):
    __tablename__ = "note_connection"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    source_note_id = Column(String, nullable=False)  # Note that contains the link/reference
    target_note_id = Column(String, nullable=False)  # Note being referenced
    connection_type = Column(String, nullable=False)  # 'reference', 'semantic', 'temporal'
    strength = Column(Integer, default=50)  # 0-100 strength score
    auto_generated = Column(String, default="true")  # true for auto-detected, false for manual
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

class Reminder(Base):
    __tablename__ = "reminder"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    reminder_time = Column(DateTime, nullable=False)
    is_completed = Column(Boolean, default=False)  # PostgreSQL boolean
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

class Timer(Base):
    __tablename__ = "timer"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)  # PostgreSQL boolean
    is_completed = Column(Boolean, default=False)  # PostgreSQL boolean
    created_at = Column(DateTime, server_default=func.now())

class Document(Base):
    __tablename__ = "document"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    title = Column(String, default="")  # User-editable title
    file_path = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)
    mime_type = Column(String, nullable=False)
    content_text = Column(Text, default="")  # Extracted text content
    is_processed = Column(String, default="false")  # SQLite compatibility
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

class DocumentChunk(Base):
    __tablename__ = "document_chunk"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    chunk_text = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    # Store embeddings as JSON for SQLite compatibility, Vector for PostgreSQL
    embedding = Column(Vector(EMBEDDING_DIM) if PGVECTOR_AVAILABLE and DATABASE_URL.startswith("postgresql") else Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

class Conversation(Base):
    __tablename__ = "conversation"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    title = Column(String, default="")  # Auto-generated conversation title
    summary = Column(Text, default="")  # Auto-generated conversation summary
    total_messages = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

class ConversationTurn(Base):
    __tablename__ = "conversation_turn"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    message_index = Column(Integer, nullable=False)  # Order in conversation
    # Store embeddings as JSON for SQLite compatibility, Vector for PostgreSQL  
    embedding = Column(Vector(EMBEDDING_DIM) if PGVECTOR_AVAILABLE and DATABASE_URL.startswith("postgresql") else Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

# Episodic Memory Models for Advanced Intelligence
class Episode(Base):
    """Enhanced episodic memory model with emotional and contextual metadata"""
    __tablename__ = "episode"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String, nullable=True)  # Link to conversation if applicable
    user_id = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    
    # Intelligence metadata
    importance = Column(Float, default=0.5)  # AI-scored importance (0-1)
    emotional_tone = Column(Text, nullable=True)  # JSON: {"primary": "positive", "intensity": 0.7, "emotions": [...]}
    topics = Column(Text, nullable=True)  # JSON: ["work", "fitness", "learning"]
    context_tags = Column(Text, nullable=True)  # JSON: ["planning", "reflection", "problem_solving"]
    
    # Memory metadata
    access_count = Column(Integer, default=0)  # How often this episode is retrieved
    last_accessed = Column(DateTime, nullable=True)
    memory_type = Column(String, default="conversation")  # conversation, note_creation, action, etc.
    source = Column(String, default="chat")  # chat, note, document, timer, etc.
    
    # Vector embedding for similarity search
    embedding = Column(Vector(EMBEDDING_DIM) if PGVECTOR_AVAILABLE and DATABASE_URL.startswith("postgresql") else Text, nullable=True)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

class ContextWindow(Base):
    """Context window configurations for dynamic memory retrieval"""
    __tablename__ = "context_window"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    window_type = Column(String, nullable=False)  # temporal, topic, emotional, importance, hybrid
    
    # Window parameters stored as JSON
    parameters = Column(Text, nullable=False)  # JSON: {"size": "1d", "topic": "fitness", "min_importance": 0.6}
    
    # Usage tracking
    last_used = Column(DateTime, nullable=True)
    use_count = Column(Integer, default=0)
    
    created_at = Column(DateTime, server_default=func.now())

class DreamInsight(Base):
    """Background consolidation insights from Sara's dreaming process"""
    __tablename__ = "dream_insight"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    
    # Dream metadata
    dream_date = Column(DateTime, nullable=False)
    insight_type = Column(String, nullable=False)  # pattern, connection, summary, trend, forgotten_gem
    confidence = Column(Float, nullable=False)  # AI confidence in insight (0-1)
    
    # Insight content
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    related_episodes = Column(Text, nullable=True)  # JSON list of episode IDs
    
    # User interaction
    surfaced_at = Column(DateTime, nullable=True)  # When shown to user
    user_feedback = Column(String, nullable=True)  # relevant, not_relevant, interesting
    
    created_at = Column(DateTime, server_default=func.now())

class VulnerabilityReport(Base):
    """Daily vulnerability reports generated from multiple sources"""
    __tablename__ = "vulnerability_report"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    
    # Report metadata
    report_date = Column(DateTime, nullable=False, unique=True)
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=True)  # Brief summary for notifications
    
    # Report content
    content = Column(Text, nullable=False)  # Markdown content
    vulnerabilities_count = Column(Integer, default=0)
    critical_count = Column(Integer, default=0)
    kev_count = Column(Integer, default=0)  # Known Exploited Vulnerabilities
    vulnerability_ids = Column(Text, nullable=True)  # JSON list of CVE IDs in this report
    
    # Processing status
    processed_to_neo4j = Column(Integer, default=0)  # Boolean flag for Neo4j integration
    
    created_at = Column(DateTime, server_default=func.now())

class NotificationLog(Base):
    """Track NTFY notifications to prevent spam and for debugging"""
    __tablename__ = "notification_log"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    
    # Notification details
    notification_type = Column(String, nullable=False)  # 'report_ready', 'critical_vuln'
    reference_id = Column(String, nullable=True)  # report_id or cve_id
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    
    # Delivery tracking
    ntfy_response = Column(Text, nullable=True)
    sent_at = Column(DateTime, server_default=func.now())

# Habit Tracking Models
class Habit(Base):
    """Core habit definition with scheduling and configuration"""
    __tablename__ = "habits"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    title = Column(Text, nullable=False)
    type = Column(String, nullable=False)  # binary, quantitative, checklist, time
    target_numeric = Column(Float, nullable=True)  # for quantitative/time
    unit = Column(Text, nullable=True)  # oz, min, reps, pages
    rrule = Column(Text, nullable=False)  # RRULE string for expected days
    weekly_minimum = Column(Integer, nullable=True)  # e.g., 3 times/week
    monthly_minimum = Column(Integer, nullable=True)  # optional
    windows = Column(Text, nullable=True)  # JSON: [{"name":"Morning","start":"05:00","end":"11:30"}]
    checklist_mode = Column(String, nullable=True)  # all, percent
    checklist_threshold = Column(Float, nullable=True)  # e.g., 0.7 for 70%
    grace_days = Column(Integer, default=0)
    retro_hours = Column(Integer, default=24)
    paused = Column(Integer, default=0)  # boolean
    pause_from = Column(DateTime, nullable=True)
    pause_to = Column(DateTime, nullable=True)
    vacation_from = Column(DateTime, nullable=True)  # vacation periods
    vacation_to = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)  # optional description
    current_streak = Column(Integer, default=0)
    best_streak = Column(Integer, default=0)
    last_completed = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

class HabitItem(Base):
    """Checklist items for checklist-type habits"""
    __tablename__ = "habit_items"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    habit_id = Column(String, nullable=False)  # foreign key to habits.id
    label = Column(Text, nullable=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

class HabitInstance(Base):
    """Materialized daily instances for fast UI queries"""
    __tablename__ = "habit_instances"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    habit_id = Column(String, nullable=False)  # foreign key to habits.id
    user_id = Column(String, nullable=False)
    date = Column(DateTime, nullable=False)  # date for this instance
    window = Column(Text, nullable=True)  # optional window name
    expected = Column(Integer, default=1)  # boolean: expected on this day
    status = Column(String, nullable=False, default='pending')  # pending, complete, skipped
    progress = Column(Float, default=0.0)  # 0..1 for binary/checklist; scaled for quantitative
    total_amount = Column(Float, nullable=True)  # raw sum for quantitative
    target = Column(Float, nullable=True)  # snapshot of target for the day
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

class HabitLog(Base):
    """Individual completion logs with source tracking"""
    __tablename__ = "habit_logs"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    habit_id = Column(String, nullable=False)  # foreign key to habits.id
    instance_id = Column(String, nullable=True)  # foreign key to habit_instances.id
    user_id = Column(String, nullable=False)
    ts = Column(DateTime, nullable=False, server_default=func.now())
    source = Column(String, nullable=False)  # manual, voice, timer, calendar, ntfy, health
    payload = Column(Text, nullable=True)  # JSON: {amount:12, unit:'oz'} or {timer_id:...}
    created_at = Column(DateTime, server_default=func.now())

class HabitStreak(Base):
    """Streak tracking per habit"""
    __tablename__ = "habit_streaks"
    habit_id = Column(String, primary_key=True)  # foreign key to habits.id
    current_streak = Column(Integer, default=0)
    best_streak = Column(Integer, default=0)
    last_completed = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, server_default=func.now())

class HabitLink(Base):
    """Links to notes/concepts/documents for graph integration"""
    __tablename__ = "habit_links"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    habit_id = Column(String, nullable=False)  # foreign key to habits.id
    target_type = Column(String, nullable=False)  # note, concept, document
    target_id = Column(String, nullable=False)
    meta = Column(Text, nullable=True)  # JSON metadata
    created_at = Column(DateTime, server_default=func.now())

class EventOutbox(Base):
    """Outbox pattern for Neo4j sync"""
    __tablename__ = "event_outbox"
    id = Column(Integer, primary_key=True, autoincrement=True)
    aggregate_type = Column(String, nullable=False)  # Habit, Instance, Log, Link
    aggregate_id = Column(String, nullable=False)
    op = Column(String, nullable=False)  # UPSERT, DELETE
    payload = Column(Text, nullable=False)  # JSON
    created_at = Column(DateTime, server_default=func.now())
    processed_at = Column(DateTime, nullable=True)

# Sara Autonomous System Models
class UserProfile(Base):
    """User personality profile and autonomous preferences"""
    __tablename__ = "user_profile"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, unique=True)
    
    # Personality mode preferences
    current_mode = Column(String, default="companion")  # coach, analyst, companion, guardian, concierge, librarian
    mode_preferences = Column(Text, nullable=True)  # JSON: {"coach": {"enabled": true, "intensity": 0.7}, ...}
    
    # Autonomy settings
    autonomy_level = Column(String, default="moderate")  # minimal, moderate, high (matches actual DB schema)
    quiet_hours_start = Column(String, nullable=True)  # "22:00"
    quiet_hours_end = Column(String, nullable=True)    # "07:00"
    idle_thresholds = Column(Text, nullable=True)  # JSON: {"quickSweep": 1800000, "standardSweep": 7200000, "digestSweep": 86400000}
    
    # Notification preferences
    ntfy_enabled = Column(Boolean, default=True)
    ntfy_topics = Column(Text, nullable=True)  # JSON: {"insights": "sara-insights", "reminders": "sara"}
    sprite_notifications = Column(Boolean, default=True)
    
    # Additional columns from models/profile.py (GTKY service)
    profile_data = Column(Text, nullable=True)  # JSON: Goals, preferences, personality settings
    communication_style = Column(String, default="balanced")  # reserved, balanced, chatty
    notification_channels = Column(Text, nullable=True)  # JSON: ntfy topics, quiet hours, etc.
    gtky_completed_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

class AutonomousInsight(Base):
    """Insights generated by Sara's autonomous background processes"""
    __tablename__ = "autonomous_insight"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    
    # Insight metadata
    insight_type = Column(String, nullable=False)  # pattern, suggestion, summary, reminder, connection, analysis
    personality_mode = Column(String, nullable=False)  # Mode that generated this insight
    sweep_type = Column(String, nullable=False)  # quick_sweep, standard_sweep, digest_sweep
    priority_score = Column(Float, nullable=False)  # 0-1, relevance × impact × novelty × timing - annoyance
    
    # Insight content
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    action_suggestion = Column(String, nullable=True)  # JSON: {"primary": "Open Chat", "secondary": "View Notes"}
    related_data = Column(Text, nullable=True)  # JSON: {"note_ids": [...], "episode_ids": [...], "context": {...}}
    
    # User interaction tracking
    surfaced_at = Column(DateTime, nullable=True)  # When shown to user
    user_action = Column(String, nullable=True)  # dismissed, acted_on, saved, snoozed
    feedback_score = Column(Integer, nullable=True)  # -1, 0, 1 (unhelpful, neutral, helpful)
    
    # System tracking
    generated_at = Column(DateTime, server_default=func.now())
    expires_at = Column(DateTime, nullable=True)  # Optional expiration for time-sensitive insights

class InsightNudge(Base):
    """Nudges/notifications sent to user based on insights"""
    __tablename__ = "insight_nudge"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    insight_id = Column(String, nullable=False)  # Foreign key to autonomous_insight
    
    # Nudge delivery
    delivery_method = Column(String, nullable=False)  # sprite_toast, sprite_badge, ntfy_push
    delivered_at = Column(DateTime, server_default=func.now())
    
    # User response tracking
    clicked = Column(Boolean, default=False)
    dismissed_at = Column(DateTime, nullable=True)
    action_taken = Column(String, nullable=True)  # reply, open, ignore

class ActivitySession(Base):
    """Track user activity sessions for autonomous behavior triggers"""
    __tablename__ = "activity_session"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    
    # Session timing
    session_start = Column(DateTime, nullable=False)
    session_end = Column(DateTime, nullable=True)
    idle_duration = Column(Integer, default=0)  # milliseconds
    
    # Activity context
    active_view = Column(String, nullable=True)  # chat, notes, dashboard, etc.
    interaction_count = Column(Integer, default=0)
    
    # Autonomous triggers during this session
    quick_sweep_triggered = Column(Boolean, default=False)
    standard_sweep_triggered = Column(Boolean, default=False) 
    digest_sweep_triggered = Column(Boolean, default=False)
    insights_generated = Column(Integer, default=0)
    
    created_at = Column(DateTime, server_default=func.now())

class BackgroundSweep(Base):
    """Log of background sweep executions and their results"""
    __tablename__ = "background_sweep"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    
    # Sweep metadata
    sweep_type = Column(String, nullable=False)  # quick_sweep, standard_sweep, digest_sweep
    personality_mode = Column(String, nullable=False)
    triggered_by = Column(String, nullable=False)  # idle_threshold, manual, scheduled
    
    # Execution results
    execution_time_ms = Column(Integer, nullable=False)
    insights_generated = Column(Integer, default=0)
    errors_encountered = Column(Text, nullable=True)  # JSON array of error messages
    
    # Context data processed
    episodes_analyzed = Column(Integer, default=0)
    notes_analyzed = Column(Integer, default=0)
    patterns_found = Column(Text, nullable=True)  # JSON summary of patterns discovered
    
    executed_at = Column(DateTime, server_default=func.now())

# Create tables
Base.metadata.create_all(bind=engine)

# Pydantic models
class UserCreate(BaseModel):
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str
    email: str
    created_at: str
    access_token: Optional[str] = None

class NoteCreate(BaseModel):
    title: str = ""
    content: str
    folder_id: Optional[str] = None

class NoteResponse(BaseModel):
    id: str
    title: str
    content: str
    folder_id: Optional[str] = None
    created_at: str
    updated_at: str

class NoteConnectionCreate(BaseModel):
    target_note_id: str
    connection_type: str  # 'reference', 'semantic', 'temporal'
    strength: int = 50  # 0-100
    auto_generated: bool = True

class NoteConnectionResponse(BaseModel):
    id: str
    source_note_id: str
    target_note_id: str
    connection_type: str
    strength: int
    auto_generated: bool
    created_at: str
    updated_at: str

class FolderCreate(BaseModel):
    name: str
    parent_id: str = None

class FolderUpdate(BaseModel):
    name: str = None
    parent_id: str = None

class FolderResponse(BaseModel):
    id: str
    name: str
    parent_id: str = None
    notes_count: int = 0
    subfolders_count: int = 0
    created_at: str
    updated_at: str

class TreeNodeResponse(BaseModel):
    id: str
    name: str
    type: str  # "folder" or "note"
    parent_id: str = None
    children: list = []
    created_at: str
    updated_at: str

class ReminderCreate(BaseModel):
    title: str
    description: str = ""
    reminder_time: str  # ISO format datetime string

class ReminderResponse(BaseModel):
    id: str
    title: str
    description: str
    reminder_time: str
    is_completed: bool
    created_at: str
    updated_at: str

class TimerCreate(BaseModel):
    title: str
    duration_minutes: int

class TimerResponse(BaseModel):
    id: str
    title: str
    duration_minutes: int
    start_time: str
    end_time: str
    is_active: bool
    is_completed: bool
    created_at: str

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    conversation_id: Optional[str] = None

class ChatResponse(BaseModel):
    message: ChatMessage

class DocumentResponse(BaseModel):
    id: str
    filename: str
    original_filename: str
    title: str = ""  # User-editable title
    file_size: int
    mime_type: str
    content_text: str = ""
    is_processed: str  # String to match database storage ("true", "false", "error")
    created_at: str
    updated_at: str

class DocumentChunkResponse(BaseModel):
    id: str
    document_id: str
    chunk_text: str
    chunk_index: int
    created_at: str

class ConversationResponse(BaseModel):
    id: str
    title: str
    summary: str
    total_messages: int
    created_at: str
    updated_at: str

class ConversationTurnResponse(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    message_index: int
    created_at: str

class VulnerabilityReportResponse(BaseModel):
    id: str
    report_date: str
    title: str
    summary: Optional[str]
    content: str
    vulnerabilities_count: int
    critical_count: int
    kev_count: int
    created_at: str

class VulnerabilityReportListResponse(BaseModel):
    id: str
    report_date: str
    title: str
    summary: Optional[str]
    vulnerabilities_count: int
    critical_count: int
    kev_count: int
    created_at: str

class NotificationRequest(BaseModel):
    type: str  # 'report_ready' or 'critical_vuln'
    title: str
    message: str
    reference_id: Optional[str] = None

class NotificationResponse(BaseModel):
    id: str
    notification_type: str
    title: str
    message: str
    sent_at: str

# Habit Tracking Pydantic Models
class HabitCreate(BaseModel):
    title: str
    type: str  # binary, quantitative, checklist, time
    target_numeric: Optional[float] = None
    unit: Optional[str] = None
    rrule: str = "FREQ=DAILY"  # Default to daily
    weekly_minimum: Optional[int] = None
    monthly_minimum: Optional[int] = None
    windows: Optional[str] = None  # JSON string
    checklist_mode: Optional[str] = "all"  # all, percent
    checklist_threshold: Optional[float] = 1.0
    grace_days: int = 0
    retro_hours: int = 24
    notes: Optional[str] = None

class HabitResponse(BaseModel):
    id: str
    title: str
    type: str
    target_numeric: Optional[float] = None
    unit: Optional[str] = None
    rrule: str
    weekly_minimum: Optional[int] = None
    monthly_minimum: Optional[int] = None
    windows: Optional[str] = None
    checklist_mode: Optional[str] = None
    checklist_threshold: Optional[float] = None
    grace_days: int
    retro_hours: int
    paused: bool
    pause_from: Optional[str] = None
    pause_to: Optional[str] = None
    notes: Optional[str] = None
    created_at: str
    updated_at: str

class HabitItemCreate(BaseModel):
    label: str
    sort_order: int = 0

class HabitItemResponse(BaseModel):
    id: str
    habit_id: str
    label: str
    sort_order: int
    created_at: str

class HabitInstanceResponse(BaseModel):
    id: str
    habit_id: str
    date: str
    window: Optional[str] = None
    expected: bool
    status: str  # pending, complete, skipped
    progress: float
    total_amount: Optional[float] = None
    target: Optional[float] = None
    # Include habit details for Today view
    title: str
    type: str
    unit: Optional[str] = None

class HabitTodayStats(BaseModel):
    total: int
    completed: int
    in_progress: int
    completion_rate: float

class HabitTodayResponse(BaseModel):
    date: str
    habits: list[HabitInstanceResponse]
    stats: HabitTodayStats

class HabitInsightsOverview(BaseModel):
    total_habits: int
    active_habits: int
    total_completions: int
    average_completion_rate: float
    current_streaks: int
    longest_streak: int

class HabitInsightsWeeklyStats(BaseModel):
    this_week: dict
    last_week: dict
    trend: str

class HabitInsightsPerformance(BaseModel):
    habit_id: str
    title: str
    type: str
    completion_rate: float
    current_streak: int
    best_streak: int
    total_completions: int

class HabitInsightsPatterns(BaseModel):
    best_day_of_week: str
    best_time_of_day: str
    most_consistent_habit: str
    improvement_suggestions: list[str]

class HabitInsightsResponse(BaseModel):
    overview: HabitInsightsOverview
    weekly_stats: HabitInsightsWeeklyStats
    habit_performance: list[HabitInsightsPerformance]
    patterns: HabitInsightsPatterns

class HabitLogCreate(BaseModel):
    amount: Optional[float] = None
    source: str = "manual"
    payload: Optional[str] = None  # JSON string

class HabitLogResponse(BaseModel):
    id: str
    habit_id: str
    instance_id: Optional[str] = None
    ts: str
    source: str
    payload: Optional[str] = None
    created_at: str

class HabitStreakResponse(BaseModel):
    habit_id: str
    current_streak: int
    best_streak: int
    last_completed: Optional[str] = None

class HabitLinkCreate(BaseModel):
    target_type: str  # note, concept, document
    target_id: str
    meta: Optional[str] = None  # JSON string

class HabitLinkResponse(BaseModel):
    id: str
    habit_id: str
    target_type: str
    target_id: str
    meta: Optional[str] = None
    created_at: str

class HabitPauseRequest(BaseModel):
    pause_from: str  # ISO datetime
    pause_to: str    # ISO datetime

# Sara Autonomous System Pydantic Models
class UserProfileCreate(BaseModel):
    current_mode: Optional[str] = "companion"
    mode_preferences: Optional[Dict[str, Any]] = None
    autonomy_level: Optional[str] = "moderate"  # minimal, moderate, high
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    idle_thresholds: Optional[Dict[str, int]] = None
    ntfy_enabled: Optional[bool] = True
    ntfy_topics: Optional[Dict[str, str]] = None
    sprite_notifications: Optional[bool] = True
    profile_data: Optional[Dict[str, Any]] = None
    communication_style: Optional[str] = "balanced"
    notification_channels: Optional[Dict[str, Any]] = None

class UserProfileResponse(BaseModel):
    id: str
    user_id: str
    current_mode: str
    mode_preferences: Optional[Dict[str, Any]]
    autonomy_level: str  # minimal, moderate, high
    quiet_hours_start: Optional[str]
    quiet_hours_end: Optional[str]
    idle_thresholds: Optional[Dict[str, int]]
    ntfy_enabled: bool
    ntfy_topics: Optional[Dict[str, str]]
    sprite_notifications: bool
    profile_data: Optional[Dict[str, Any]]
    communication_style: str
    notification_channels: Optional[Dict[str, Any]]
    gtky_completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

class AutonomousInsightResponse(BaseModel):
    id: str
    user_id: str
    insight_type: str
    personality_mode: str
    sweep_type: str
    priority_score: float
    title: str
    message: str
    action_suggestion: Optional[Dict[str, str]]
    related_data: Optional[Dict[str, Any]]
    surfaced_at: Optional[datetime]
    user_action: Optional[str]
    feedback_score: Optional[int]
    generated_at: datetime
    expires_at: Optional[datetime]

class InsightFeedbackRequest(BaseModel):
    feedback_score: int  # -1, 0, 1
    user_action: str     # dismissed, acted_on, saved, snoozed

class ActivitySessionResponse(BaseModel):
    id: str
    user_id: str
    session_start: datetime
    session_end: Optional[datetime]
    idle_duration: int
    active_view: Optional[str]
    interaction_count: int
    quick_sweep_triggered: bool
    standard_sweep_triggered: bool
    digest_sweep_triggered: bool
    insights_generated: int
    created_at: datetime

class BackgroundSweepResponse(BaseModel):
    id: str
    user_id: str
    sweep_type: str
    personality_mode: str
    triggered_by: str
    execution_time_ms: int
    insights_generated: int
    errors_encountered: Optional[list]
    episodes_analyzed: int
    notes_analyzed: int
    patterns_found: Optional[Dict[str, Any]]
    executed_at: datetime

# Auth utilities
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_cookie_domain(request: Request) -> str:
    """Determine the appropriate cookie domain based on the request host."""
    host = request.headers.get("host", "")
    if "sara.avery.cloud" in host:
        return ".sara.avery.cloud"
    else:
        # For local development, don't set a domain (defaults to current host)
        return None

def create_access_token(data: dict):
    expire = datetime.now(timezone.utc) + timedelta(hours=24*7)
    to_encode = data.copy()
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None

# Dependencies
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(request: Request, db: Session = Depends(get_db)):
    # Try to get token from cookie first (for web UI)
    access_token = request.cookies.get("access_token")
    
    # If no cookie, try Authorization header (for programmatic access)
    if not access_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            access_token = auth_header[7:]  # Remove "Bearer " prefix
    
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    payload = verify_token(access_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    return user

# LLM Client
class SimpleLLMClient:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=60.0)
        self.event_queue = None
        self._citations = set()
    
    def set_event_queue(self, queue):
        """Set event queue for streaming updates"""
        self.event_queue = queue
        # Reset collected citations at the start of a new stream
        self._citations = set()
    
    async def emit_event(self, event_type, data):
        """Emit an event to the streaming queue"""
        if self.event_queue:
            await self.event_queue.put({
                "type": event_type,
                "data": data,
                "timestamp": datetime.utcnow().isoformat()
            })
    
    async def _stream_response(self, payload):
        """Stream response from LLM and emit text chunks"""
        full_content = ""
        tool_calls = []
        
        try:
            async with self.client.stream("POST", f"{OPENAI_BASE_URL}/chat/completions", 
                                        json=payload, 
                                        headers={"Authorization": "Bearer dummy"}) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        line_data = line[6:]
                        if line_data == "[DONE]":
                            break
                        
                        try:
                            chunk = json.loads(line_data)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            
                            # Handle content streaming
                            if "content" in delta and delta["content"]:
                                content_chunk = delta["content"]
                                full_content += content_chunk
                                await self.emit_event("text_chunk", {
                                    "content": content_chunk,
                                    "full_content": full_content
                                })
                            
                            # Handle tool calls
                            if "tool_calls" in delta:
                                if not tool_calls:
                                    tool_calls = delta["tool_calls"]
                                else:
                                    # Merge tool calls
                                    for i, tc in enumerate(delta["tool_calls"]):
                                        if i < len(tool_calls):
                                            if "function" in tc and "arguments" in tc["function"]:
                                                tool_calls[i]["function"]["arguments"] += tc["function"]["arguments"]
                                        else:
                                            tool_calls.append(tc)
                                            
                        except json.JSONDecodeError:
                            continue
            
            # Return message object compatible with existing code
            return {
                "content": full_content,
                "tool_calls": tool_calls if tool_calls else None
            }
            
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            # Fallback to non-streaming
            payload_fallback = payload.copy()
            payload_fallback.pop("stream", None)
            
            response = await self.client.post(
                f"{OPENAI_BASE_URL}/chat/completions",
                json=payload_fallback,
                headers={"Authorization": "Bearer dummy"}
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]
    
    async def chat(self, messages: list):
        try:
            response = await self.client.post(
                f"{OPENAI_BASE_URL}/chat/completions",
                json={
                    "model": OPENAI_MODEL,
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                    "temperature": 0.7
                },
                headers={"Authorization": "Bearer dummy"}
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return f"I'm sorry, I'm having trouble connecting to my AI service. Error: {str(e)}"

    async def chat_with_tools(self, messages, tools, user_id, conversation_id=None):
        """Enhanced chat with tool calling support"""
        try:
            logger.info(f"LLM chat_with_tools called with {len(messages)} messages, {len(tools)} tools for user {user_id}")
            payload = {
                "model": OPENAI_MODEL,
                "messages": [{"role": msg.role, "content": msg.content} for msg in messages],
                "tools": tools,
                "tool_choice": "auto",
                "temperature": 0.7,
                "max_tokens": 2000,
                "stream": True
            }
            
            message = await self._stream_response(payload)
            
            # Handle tool calls with recursive support (max 10 rounds for complex queries)
            max_tool_rounds = 10
            current_messages = [{"role": msg.role, "content": msg.content} for msg in messages]
            
            for round_num in range(max_tool_rounds):
                if message.get("tool_calls"):
                    logger.info(f"🔧 Tool calling round {round_num + 1}")
                    
                    # Emit tool usage event
                    tool_names = [tc.get("function", {}).get("name", "unknown") for tc in message["tool_calls"]]
                    await self.emit_event("tool_calls_start", {
                        "round": round_num + 1,
                        "tools": tool_names,
                        "count": len(message["tool_calls"])
                    })
                    
                    tool_responses = []
                    
                    for tool_call in message["tool_calls"]:
                        tool_name = tool_call.get("function", {}).get("name", "unknown")
                        await self.emit_event("tool_executing", {
                            "tool": tool_name,
                            "round": round_num + 1
                        })
                        
                        tool_response = await self.execute_tool(tool_call, user_id)
                        tool_responses.append(tool_response)
                        
                        await self.emit_event("tool_completed", {
                            "tool": tool_name,
                            "round": round_num + 1
                        })
                    
                    # Add assistant message with tool calls and tool responses
                    current_messages.append(message)
                    current_messages.extend(tool_responses)
                    
                    # Truncate messages if conversation is getting too long to prevent 500 errors
                    max_messages = 20  # Keep only recent context to prevent payload bloat
                    if len(current_messages) > max_messages:
                        # Keep system message (first) and recent messages
                        truncated_messages = [current_messages[0]] + current_messages[-max_messages+1:]
                        logger.info(f"⚠️ Truncated conversation from {len(current_messages)} to {len(truncated_messages)} messages")
                        current_messages = truncated_messages
                    
                    # Emit thinking event
                    await self.emit_event("thinking", {
                        "round": round_num + 1,
                        "status": "processing_tools"
                    })
                    
                    # Make follow-up request with streaming
                    follow_up_payload = {
                        "model": OPENAI_MODEL,
                        "messages": current_messages,
                        "temperature": 0.7,
                        "max_tokens": 2000,
                        "tools": tools,
                        "stream": True
                    }
                    
                    message = await self._stream_response(follow_up_payload)
                    
                    # Enhanced debugging
                    logger.info(f"🔍 Round {round_num + 1} - Message keys: {list(message.keys())}")
                    logger.info(f"🔍 Round {round_num + 1} - Content length: {len(message.get('content', '')) if message.get('content') else 0}")
                    logger.info(f"🔍 Round {round_num + 1} - Content preview: {repr(message.get('content', ''))[:100]}")
                    logger.info(f"🔍 Round {round_num + 1} - Has tool_calls: {bool(message.get('tool_calls'))}")
                    if message.get('tool_calls'):
                        logger.info(f"🔍 Round {round_num + 1} - Tool calls: {[tc.get('function', {}).get('name') for tc in message.get('tool_calls', [])]}")
                    if hasattr(message, 'reasoning'):
                        logger.info(f"🔍 Round {round_num + 1} - Reasoning: {message.get('reasoning', '')[:100]}")
                    
                    # If no more tool calls, we're done
                    if not message.get("tool_calls"):
                        response_content = message["content"]
                        await self.emit_event("response_ready", {
                            "rounds": round_num + 1,
                            "content_length": len(response_content) if response_content else 0
                        })
                        await self.store_conversation(messages, response_content, user_id, conversation_id)
                        logger.info(f"Final LLM response after {round_num + 1} rounds: {len(response_content) if response_content else 0}")
                        return response_content
                else:
                    # No tool calls, return the content
                    response_content = message["content"]
                    await self.emit_event("response_ready", {
                        "rounds": 1,
                        "content_length": len(response_content) if response_content else 0
                    })
                    await self.store_conversation(messages, response_content, user_id, conversation_id)
                    logger.info(f"Final LLM response (no tools): {len(response_content) if response_content else 0}")
                    return response_content
            
            # If we hit max rounds, force a proper response
            logger.warning(f"Hit max tool rounds with message: {message}")
            
            # Try to get the reasoning or any available content
            response_content = message.get("content", "")
            if not response_content and message.get("reasoning"):
                response_content = message.get("reasoning", "")
            
            # If still no content, force a reasonable response
            if not response_content:
                response_content = "I've searched through your documents and found some relevant information, but I encountered an issue providing a complete response. Please try asking your question again."
            
            await self.store_conversation(messages, response_content, user_id, conversation_id)
            logger.warning(f"Hit max tool rounds, returning: {len(response_content)} chars")
            return response_content
                
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return f"I'm sorry, I'm having trouble connecting to my AI service. Error: {str(e)}"

    async def execute_tool(self, tool_call, user_id):
        """Execute a tool call and return the response"""
        function_name = tool_call["function"]["name"]
        arguments = json.loads(tool_call["function"]["arguments"])
        
        logger.info(f"Executing tool {function_name} with arguments: {arguments}")
        
        if function_name == "search_notes":
            result = await self.search_notes_tool(arguments["query"], user_id)
        elif function_name == "create_note":
            result = await self.create_note_tool(arguments.get("title", ""), arguments["content"], user_id)
        elif function_name == "list_notes":
            result = await self.list_notes_tool(user_id)
        elif function_name == "delete_note":
            result = await self.delete_note_tool(arguments["note_id"], user_id)
        elif function_name == "create_reminder":
            result = await self.create_reminder_tool(arguments["title"], arguments.get("description", ""), arguments["reminder_time"], user_id)
        elif function_name == "list_reminders":
            result = await self.list_reminders_tool(user_id)
        elif function_name == "complete_reminder":
            result = await self.complete_reminder_tool(arguments["reminder_id"], user_id)
        elif function_name == "start_timer":
            result = await self.start_timer_tool(arguments["title"], arguments["duration_minutes"], user_id)
        elif function_name == "list_timers":
            result = await self.list_timers_tool(user_id)
        elif function_name == "stop_timer":
            result = await self.stop_timer_tool(arguments["timer_id"], user_id)
        elif function_name == "search_documents":
            result = await self.search_documents_tool(arguments["query"], user_id)
        elif function_name == "search_memory":
            result = await self.search_memory_tool(arguments["query"], user_id)
        else:
            # Fallback to global tool registry (e.g., web_search, open_page, knowledge_graph, etc.)
            try:
                reg_result = await tool_registry.execute_tool(name=function_name, user_id=str(user_id), parameters=arguments)
                # Collect citations if available
                try:
                    if reg_result.citations:
                        for c in reg_result.citations:
                            if isinstance(c, str):
                                self._citations.add(c)
                except Exception:
                    pass
                result = json.dumps({
                    "success": reg_result.success,
                    "message": reg_result.message,
                    "data": reg_result.data
                })
            except Exception as e:
                result = f"Unknown tool: {function_name} ({e})"
        
        logger.info(f"Tool {function_name} result length: {len(str(result))} chars")
        if function_name == "search_documents":
            logger.info(f"Search result preview: {str(result)[:500]}...")
        return {
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "content": str(result)
        }

    def get_citations(self):
        return list(self._citations)

    async def search_notes_tool(self, query, user_id):
        """Search notes using Neo4j knowledge graph (with PostgreSQL fallback)"""
        neo4j_failed = False
        
        # Try Neo4j search first
        try:
            from app.services.neo4j_service import neo4j_service
            if neo4j_service.driver:
                search_results = await neo4j_service.search_knowledge_graph(
                    user_id=user_id,
                    query=query,
                    content_types=["Note"],
                    limit=10
                )
                
                if search_results:
                    results = []
                    for node in search_results:
                        title = node.get('title', 'Untitled')
                        content = node.get('content', '')[:200]
                        results.append(f"Note: {title}\nContent: {content}...")
                    return "\n\n".join(results)
                elif search_results is not None:  # Empty list means no results found
                    return "No notes found matching your query in Neo4j."
        except Exception as e:
            logger.warning(f"Neo4j search failed, falling back to PostgreSQL: {e}")
            neo4j_failed = True
        
        # Fallback to PostgreSQL
        try:
            db = SessionLocal()
            try:
                notes = db.query(Note).filter(
                    Note.user_id == user_id,
                    Note.content.ilike(f"%{query}%")
                ).limit(5).all()
                
                if not notes:
                    return "No notes found matching your query."
                
                results = []
                for note in notes:
                    results.append(f"Note: {note.title or 'Untitled'}\nContent: {note.content[:200]}...")
                
                fallback_notice = " (via PostgreSQL fallback)" if neo4j_failed else ""
                return "\n\n".join(results) + fallback_notice
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error searching notes in PostgreSQL: {e}")
            return "Unable to search notes at this time. Please try again later."

    async def create_note_tool(self, title, content, user_id):
        """Create a new note using Neo4j-first architecture with intelligent processing"""
        note_id = str(__import__('uuid').uuid4())
        
        try:
            # Neo4j-first approach: Create note in Neo4j immediately
            from app.services.neo4j_service import neo4j_service
            from app.services.intelligence_pipeline import intelligence_pipeline, ContentType
            
            # Ensure Neo4j connection
            if neo4j_service.driver:
                try:
                    # Create note in Neo4j graph
                    await neo4j_service.create_note(
                        note_id=note_id,
                        user_id=user_id,
                        title=title or "Untitled",
                        content=content
                    )
                    
                    # Queue for intelligent processing
                    await intelligence_pipeline.queue_fast_processing(
                        content_id=note_id,
                        content_type=ContentType.NOTE,
                        metadata={
                            "user_id": user_id,
                            "title": title
                        }
                    )
                    
                    logger.info(f"✅ Tool: Note {note_id} created in Neo4j and queued for processing")
                except Exception as neo_error:
                    logger.warning(f"Neo4j note creation failed in tool: {neo_error}")
            
            # Background sync to PostgreSQL (backup)
            db = SessionLocal()
            try:
                note = Note(
                    id=note_id,
                    user_id=user_id,
                    title=title or "",
                    content=content
                )
                db.add(note)
                db.commit()
                db.refresh(note)
                
                return f"Created note: {note.title or 'Untitled'} (with intelligent graph processing)"
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error creating note: {e}")
            return f"Error creating note: {str(e)}"

    async def list_notes_tool(self, user_id):
        """List all notes for the user"""
        try:
            # First try Neo4j
            from app.services.neo4j_service import neo4j_service
            if neo4j_service.driver:
                try:
                    notes = await neo4j_service.get_user_notes(user_id)
                    if notes:
                        formatted_notes = []
                        for note in notes:
                            title = note.get('title', 'Untitled')
                            note_id = note.get('id', '')
                            content_preview = note.get('content', '')[:100] + "..." if len(note.get('content', '')) > 100 else note.get('content', '')
                            formatted_notes.append(f"• {title} (ID: {note_id})\n  {content_preview}")
                        return f"Your notes:\n\n" + "\n\n".join(formatted_notes)
                except Exception as neo_error:
                    logger.warning(f"Neo4j list notes failed: {neo_error}")
            
            # Fallback to PostgreSQL
            db = SessionLocal()
            try:
                notes = db.query(Note).filter(Note.user_id == user_id).order_by(Note.created_at.desc()).all()
                if not notes:
                    return "You don't have any notes yet."
                
                formatted_notes = []
                for note in notes:
                    title = note.title or "Untitled"
                    content_preview = note.content[:100] + "..." if len(note.content) > 100 else note.content
                    formatted_notes.append(f"• {title} (ID: {note.id})\n  {content_preview}")
                
                return f"Your notes:\n\n" + "\n\n".join(formatted_notes)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error listing notes: {e}")
            return f"Error listing notes: {str(e)}"

    async def delete_note_tool(self, note_id, user_id):
        """Delete a specific note by ID"""
        try:
            # Delete from Neo4j first
            from app.services.neo4j_service import neo4j_service
            if neo4j_service.driver:
                try:
                    await neo4j_service.delete_note(note_id, user_id)
                    logger.info(f"✅ Tool: Note {note_id} deleted from Neo4j")
                except Exception as neo_error:
                    logger.warning(f"Neo4j note deletion failed: {neo_error}")
            
            # Delete from PostgreSQL
            db = SessionLocal()
            try:
                note = db.query(Note).filter(Note.id == note_id, Note.user_id == user_id).first()
                if not note:
                    return f"Note with ID {note_id} not found."
                
                note_title = note.title or "Untitled"
                db.delete(note)
                db.commit()
                
                return f"Deleted note: {note_title}"
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error deleting note: {e}")
            return f"Error deleting note: {str(e)}"

    async def create_reminder_tool(self, title, description, reminder_time, user_id):
        """Create a new reminder for the user"""
        try:
            db = SessionLocal()
            try:
                # Parse reminder time
                reminder_dt = datetime.fromisoformat(reminder_time.replace('Z', '+00:00'))
                
                reminder = Reminder(
                    user_id=user_id,
                    title=title,
                    description=description,
                    reminder_time=reminder_dt
                )
                db.add(reminder)
                db.commit()
                db.refresh(reminder)
                
                return f"Created reminder: {reminder.title} for {reminder_dt.strftime('%Y-%m-%d %H:%M')}"
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error creating reminder: {e}")
            return f"Error creating reminder: {str(e)}"

    async def list_reminders_tool(self, user_id):
        """List active reminders for the user"""
        try:
            db = SessionLocal()
            try:
                reminders = db.query(Reminder).filter(
                    Reminder.user_id == user_id,
                    Reminder.is_completed == False
                ).order_by(Reminder.reminder_time).limit(10).all()
                
                if not reminders:
                    return "No active reminders found."
                
                results = []
                for reminder in reminders:
                    time_str = reminder.reminder_time.strftime('%Y-%m-%d %H:%M')
                    results.append(f"• {reminder.title} ({time_str})")
                    if reminder.description:
                        results.append(f"  {reminder.description}")
                
                return "\n".join(results)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error listing reminders: {e}")
            return f"Error listing reminders: {str(e)}"

    async def complete_reminder_tool(self, reminder_id, user_id):
        """Mark a reminder as completed"""
        try:
            db = SessionLocal()
            try:
                reminder = db.query(Reminder).filter(
                    Reminder.id == reminder_id,
                    Reminder.user_id == user_id
                ).first()
                
                if not reminder:
                    return "Reminder not found."
                
                reminder.is_completed = "true"
                reminder.updated_at = datetime.now()
                db.commit()
                
                return f"Marked reminder '{reminder.title}' as completed"
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error completing reminder: {e}")
            return f"Error completing reminder: {str(e)}"

    async def start_timer_tool(self, title, duration_minutes, user_id):
        """Start a new timer"""
        try:
            # Validate duration
            if not isinstance(duration_minutes, int) or duration_minutes < 1 or duration_minutes > 480:
                return f"Invalid duration: {duration_minutes}. Please specify between 1 and 480 minutes (8 hours max)."
            
            db = SessionLocal()
            try:
                start_time = datetime.now(timezone.utc)
                end_time = start_time + timedelta(minutes=duration_minutes)
                
                logger.info(f"Timer timestamps - Start: {start_time.isoformat()}, End: {end_time.isoformat()}, Duration: {duration_minutes}m")
                
                timer = Timer(
                    user_id=user_id,
                    title=title,
                    duration_minutes=duration_minutes,
                    start_time=start_time,
                    end_time=end_time
                )
                db.add(timer)
                db.commit()
                db.refresh(timer)
                
                logger.info(f"Created timer: {title} for {duration_minutes} minutes for user {user_id}")
                return f"Started timer '{timer.title}' for {duration_minutes} minutes (ends at {end_time.strftime('%H:%M')})"
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error starting timer: {e}")
            return f"Error starting timer: {str(e)}"

    async def list_timers_tool(self, user_id):
        """List active timers for the user"""
        try:
            db = SessionLocal()
            try:
                now = datetime.now(timezone.utc)
                timers = db.query(Timer).filter(
                    Timer.user_id == user_id,
                    Timer.is_active == True
                ).order_by(Timer.created_at.desc()).limit(10).all()
                
                if not timers:
                    return "No active timers found."
                
                results = []
                for timer in timers:
                    # Ensure both datetimes are timezone-aware
                    end_time = timer.end_time
                    if end_time.tzinfo is None:
                        end_time = end_time.replace(tzinfo=timezone.utc)
                    
                    time_left = end_time - now
                    if time_left.total_seconds() > 0:
                        minutes_left = int(time_left.total_seconds() / 60)
                        status = f"{minutes_left}m left"
                    else:
                        status = "FINISHED"
                    
                    results.append(f"• {timer.title} ({timer.duration_minutes}m) - {status} (ID: {timer.id})")
                
                return "\n".join(results)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error listing timers: {e}")
            return f"Error listing timers: {str(e)}"

    async def stop_timer_tool(self, timer_id, user_id):
        """Stop/cancel an active timer"""
        try:
            db = SessionLocal()
            try:
                timer = db.query(Timer).filter(
                    Timer.id == timer_id,
                    Timer.user_id == user_id,
                    Timer.is_active == True
                ).first()
                
                if not timer:
                    return "Active timer not found."
                
                timer.is_active = "false"
                timer.is_completed = "true"
                db.commit()
                
                # Send AI-generated NTFY notification for timer completion
                duration_str = f"{timer.duration_minutes}min"
                await ntfy_service.send_timer_notification(timer.title, duration_str, timer_id, user_id)
                
                return f"Stopped timer '{timer.title}'"
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error stopping timer: {e}")
            return f"Error stopping timer: {str(e)}"

    async def search_documents_tool(self, query, user_id):
        """🧠 Advanced hybrid search through uploaded documents using Neo4j knowledge graph + PostgreSQL fallback"""
        try:
            # Try Neo4j search first for enhanced document discovery
            from app.services.neo4j_service import neo4j_service
            if neo4j_service.driver:
                try:
                    search_results = await neo4j_service.search_knowledge_graph(
                        user_id=user_id,
                        query=query,
                        content_types=["Document"],
                        limit=5
                    )
                    
                    if search_results:
                        results = []
                        for node in search_results:
                            title = node.get('title', 'Unknown Document')
                            content = node.get('content_text', '')[:300]
                            results.append(f"From {title}: {content}...")
                        
                        # If Neo4j found results, return them
                        if results:
                            return f"Found {len(results)} relevant results about '{query}' in your documents.\n\n" + "\n\n".join(results)
                except Exception as e:
                    logger.warning(f"Neo4j document search failed: {e}")
            
            # Fallback to PostgreSQL vector search
            db = SessionLocal()
            try:
                # Check if user has documents
                documents = db.query(Document).filter(
                    Document.user_id == user_id,
                    Document.is_processed == "true"
                ).all()
                
                if not documents:
                    return "No documents found. Upload some documents first."
                
                # Generate query embedding for semantic search
                logger.info(f"🔍 Generating embedding for query: '{query}'")
                query_embedding = await embedding_service.generate_embedding(query)
                
                semantic_results = []
                text_results = []
                
                # 1. SEMANTIC VECTOR SEARCH (Primary method)
                if query_embedding:
                    logger.info("🧠 Performing semantic vector search...")
                    try:
                        if DATABASE_URL.startswith("postgresql") and PGVECTOR_AVAILABLE:
                            # Use pgvector for similarity search
                            from sqlalchemy import text
                            similarity_query = text("""
                                SELECT dc.chunk_text, d.original_filename,
                                       (dc.embedding <=> :query_embedding) as distance
                                FROM document_chunk dc
                                JOIN document d ON dc.document_id = d.id
                                WHERE dc.user_id = :user_id 
                                  AND dc.embedding IS NOT NULL
                                  AND d.is_processed = 'true'
                                ORDER BY dc.embedding <=> :query_embedding
                                LIMIT 8
                            """)
                            
                            result = db.execute(similarity_query, {
                                'query_embedding': str(query_embedding),
                                'user_id': user_id
                            })
                            
                            for row in result:
                                similarity = 1 - row.distance  # Convert distance to similarity
                                if similarity > 0.3:  # Only include reasonably similar results
                                    semantic_results.append({
                                        'chunk_text': row.chunk_text,
                                        'filename': row.original_filename,
                                        'similarity': similarity,
                                        'type': 'SEMANTIC'
                                    })
                        else:
                            # SQLite: Manual similarity calculation using JSON embeddings
                            import json
                            import numpy as np
                            
                            chunks = db.query(DocumentChunk, Document).join(
                                Document, DocumentChunk.document_id == Document.id
                            ).filter(
                                DocumentChunk.user_id == user_id,
                                DocumentChunk.embedding.isnot(None),
                                Document.is_processed == "true"
                            ).limit(50).all()  # Get more for manual filtering
                            
                            for chunk, doc in chunks:
                                try:
                                    stored_embedding = json.loads(chunk.embedding)
                                    # Calculate cosine similarity
                                    similarity = np.dot(query_embedding, stored_embedding) / (
                                        np.linalg.norm(query_embedding) * np.linalg.norm(stored_embedding)
                                    )
                                    
                                    if similarity > 0.3:  # Only include reasonably similar results
                                        semantic_results.append({
                                            'chunk_text': chunk.chunk_text,
                                            'filename': doc.original_filename,
                                            'similarity': float(similarity),
                                            'type': 'SEMANTIC'
                                        })
                                except Exception as e:
                                    logger.warning(f"Error processing embedding for chunk {chunk.id}: {e}")
                                    continue
                            
                            # Sort by similarity
                            semantic_results.sort(key=lambda x: x['similarity'], reverse=True)
                            semantic_results = semantic_results[:8]  # Top 8 results
                            
                        logger.info(f"🎯 Found {len(semantic_results)} semantic matches")
                            
                    except Exception as e:
                        logger.warning(f"Vector search failed, using text search: {e}")
                
                # 2. ENHANCED TEXT SEARCH (Fallback + Supplementary)
                logger.info("📝 Performing enhanced text search...")
                query_terms = query.lower().split()
                
                for doc in documents:
                    # Search in document content
                    if doc.content_text:
                        content_lower = doc.content_text.lower()
                        
                        # Exact phrase match
                        if query.lower() in content_lower:
                            start_idx = content_lower.find(query.lower())
                            context_start = max(0, start_idx - 150)
                            context_end = min(len(doc.content_text), start_idx + len(query) + 150)
                            excerpt = doc.content_text[context_start:context_end].strip()
                            if context_start > 0:
                                excerpt = "..." + excerpt
                            if context_end < len(doc.content_text):
                                excerpt = excerpt + "..."
                            
                            text_results.append({
                                'chunk_text': excerpt,
                                'filename': doc.original_filename,
                                'similarity': 0.95,  # High score for exact matches
                                'type': 'EXACT'
                            })
                    
                    # Search in chunks
                    chunks = db.query(DocumentChunk).filter(
                        DocumentChunk.document_id == doc.id,
                        DocumentChunk.chunk_text.ilike(f"%{query}%")
                    ).limit(3).all()
                    
                    for chunk in chunks:
                        text_results.append({
                            'chunk_text': chunk.chunk_text,
                            'filename': doc.original_filename,
                            'similarity': 0.8,  # Good score for text matches
                            'type': 'TEXT'
                        })
                
                # 3. COMBINE AND RANK RESULTS
                all_results = semantic_results + text_results
                
                # Remove duplicates and sort by similarity
                seen_content = set()
                unique_results = []
                for result in all_results:
                    content_key = (result['filename'], result['chunk_text'][:100])
                    if content_key not in seen_content:
                        seen_content.add(content_key)
                        unique_results.append(result)
                
                # Sort by similarity score
                unique_results.sort(key=lambda x: x['similarity'], reverse=True)
                
                if not unique_results:
                    return f"❌ No results found for '{query}' in your documents. Try different search terms or upload more documents."
                
                # 4. FORMAT SIMPLE RESPONSE
                total_results = len(unique_results)
                
                response_parts = [f"Found {total_results} relevant results about '{query}' in your documents."]
                response_parts.append("")
                
                # Show top results from different documents
                seen_docs = set()
                for result in unique_results[:3]:  # Top 3 results
                    filename = result['filename']
                    if filename not in seen_docs:
                        seen_docs.add(filename)
                        
                        # Clean and present content
                        content = result['chunk_text'].strip()
                        if len(content) > 200:
                            content = content[:200] + "..."
                        
                        response_parts.append(f"From {filename}: {content}")
                        response_parts.append("")
                
                return "\n".join(response_parts)
                
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error in advanced document search: {e}")
            return f"⚠️ Search temporarily unavailable. Error: {str(e)}"

    async def search_memory_tool(self, query, user_id):
        """🧠 Search through Sara's enhanced episodic memory with intelligent context windows"""
        try:
            # Check if user has any episodes
            db = SessionLocal()
            try:
                episode_count = db.query(Episode).filter(Episode.user_id == user_id).count()
                if episode_count == 0:
                    return "🆕 This is our first conversation! I don't have any memories to search yet, but I'll remember everything we discuss."
            finally:
                db.close()
            
            # Use intelligent memory search with auto context window selection
            episodes = await intelligent_memory_service.intelligent_memory_search(
                user_id=user_id,
                query=query,
                auto_window=True
            )
            
            # Also search dream insights for relevant patterns/connections
            dream_insights = await self._search_dream_insights(query, user_id)
            
            if not episodes and not dream_insights:
                return f"🤔 I searched my memory using intelligent context windows but couldn't find anything specifically about '{query}'. What would you like to know?"
            
            # Format the intelligent memory response  
            response_parts = [f"🧠 **Sara's Intelligent Memory Search: {len(episodes)} memories found for '{query}'**"]
            response_parts.append("✨ Using AI context window selection and emotional analysis")
            
            if dream_insights:
                response_parts.append(f"💭 Found {len(dream_insights)} relevant insights from background analysis")
            
            response_parts.append("")
            
            for i, episode in enumerate(episodes[:6]):  # Top 6 memory results
                role_emoji = "👤" if episode['role'] == "user" else "🤖"
                
                # Parse emotional and topic metadata
                try:
                    emotional_data = json.loads(episode['emotional_tone']) if episode['emotional_tone'] else {}
                    topics_data = json.loads(episode['topics']) if episode['topics'] else []
                except:
                    emotional_data = {}
                    topics_data = []
                
                # Format timestamp
                try:
                    time_str = episode['created_at'].strftime('%Y-%m-%d %H:%M')
                except:
                    time_str = "Recent"
                
                # Create rich context header
                context_parts = []
                if emotional_data.get('primary_emotion'):
                    emotion = emotional_data.get('primary_emotion')
                    intensity = emotional_data.get('intensity', 0.5)
                    context_parts.append(f"Emotion: {emotion} ({intensity:.1%})")
                
                if topics_data:
                    context_parts.append(f"Topics: {', '.join(topics_data[:2])}")
                
                importance = episode['importance'] or 0.5
                context_parts.append(f"Importance: {importance:.1%}")
                
                context_str = " | ".join(context_parts) if context_parts else ""
                
                # Header with rich metadata
                response_parts.append(f"🧠 *Memory #{i+1}* - {time_str}")
                if context_str:
                    response_parts.append(f"   📊 {context_str}")
                
                # Clean and present content
                content = episode['content'].strip()
                if len(content) > 200:
                    content = content[:200] + "..."
                
                response_parts.append(f"{role_emoji} {content}")
                response_parts.append("")
            
            # Add dream insights if found
            if dream_insights:
                response_parts.append("💭 **Background Intelligence Insights:**")
                for insight in dream_insights[:3]:  # Top 3 insights
                    confidence_str = f"({insight.confidence:.0%})" if insight.confidence else ""
                    response_parts.append(f"🌙 *{insight.title}* {confidence_str}")
                    response_parts.append(f"   {insight.content[:150]}...")
                    response_parts.append("")
            
            # Add contextual insights
            total_episodes = episode_count
            response_parts.append(f"💭 *I have {total_episodes} total memories of our interactions together.*")
            
            # Add window information if available
            if hasattr(intelligent_memory_service.window_manager, 'last_window_info'):
                window_info = intelligent_memory_service.window_manager.last_window_info
                response_parts.append(f"🔍 *Used {window_info} context window for this search.*")
            
            return "\n".join(response_parts)
            
        except Exception as e:
            logger.error(f"Error in intelligent memory search: {e}")
            return f"🤔 My intelligent memory search is temporarily unavailable. Error: {str(e)}"

    async def _search_dream_insights(self, query: str, user_id: str) -> list:
        """Search dream insights for relevant patterns and connections"""
        try:
            db = SessionLocal()
            try:
                # Search insights by title and content
                query_lower = query.lower()
                
                # Search for insights that match the query  
                insights = db.query(DreamInsight).filter(
                    DreamInsight.user_id == user_id
                ).filter(
                    or_(
                        DreamInsight.title.ilike(f"%{query_lower}%"),
                        DreamInsight.content.ilike(f"%{query_lower}%"),
                        DreamInsight.insight_type.ilike(f"%{query_lower}%")
                    )
                ).order_by(DreamInsight.confidence.desc(), DreamInsight.dream_date.desc()).limit(5).all()
                
                return insights
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error searching dream insights: {e}")
            return []

    async def store_conversation(self, messages, response_content, user_id, conversation_id=None):
        """Store the conversation in enhanced episodic memory with emotional and topical analysis"""
        try:
            # Use provided conversation ID or create a new one for grouping related episodes
            if not conversation_id:
                conversation_id = str(uuid.uuid4())
            
            # Store the conversation ID for later retrieval
            self.current_conversation_id = conversation_id
            
            # Only store NEW messages that aren't already in the database
            # Get existing episodes for this conversation to avoid duplicates
            db = SessionLocal()
            try:
                existing_episodes = db.query(Episode).filter(
                    Episode.conversation_id == conversation_id,
                    Episode.user_id == user_id
                ).all()
                existing_content = {ep.content for ep in existing_episodes}
                
                # Store only new messages that aren't already stored
                for message in messages:
                    if message.role in ["user", "assistant"] and message.content not in existing_content:
                        await intelligent_memory_service.store_episode(
                            user_id=user_id,
                            role=message.role,
                            content=message.content,
                            conversation_id=conversation_id,
                            source="chat",
                            memory_type="conversation"
                        )
            finally:
                db.close()
            
            # Store assistant response as an episode (only if not already stored)
            if response_content and response_content not in existing_content:
                await intelligent_memory_service.store_episode(
                    user_id=user_id,
                    role="assistant",
                    content=response_content,
                    conversation_id=conversation_id,
                    source="chat",
                    memory_type="conversation"
                )
            
            # Also maintain legacy conversation storage for compatibility
            await self._store_legacy_conversation(messages, response_content, user_id, conversation_id)
            
            logger.info(f"🧠 Stored conversation {conversation_id} with intelligent episodic memory analysis")
                
        except Exception as e:
            logger.error(f"Error storing conversation in enhanced memory: {e}")
    
    async def _store_legacy_conversation(self, messages, response_content, user_id, conversation_id):
        """Store conversation in legacy format for compatibility"""
        try:
            db = SessionLocal()
            try:
                # Check if conversation already exists
                existing_conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
                
                if not existing_conversation:
                    # Create new conversation
                    conversation = Conversation(
                        id=conversation_id,
                        user_id=user_id,
                        title="",  # Will be generated later
                        total_messages=len(messages) + (1 if response_content else 0)
                    )
                    db.add(conversation)
                    db.commit()
                else:
                    # Update existing conversation
                    conversation = existing_conversation
                    conversation.total_messages = conversation.total_messages + (1 if response_content else 0)
                    conversation.updated_at = func.now()
                    db.commit()
                
                # Get current turn count for indexing
                current_turn_count = db.query(ConversationTurn).filter(
                    ConversationTurn.conversation_id == conversation_id
                ).count()
                
                # Only store the new user message (last message in the list)
                if messages and messages[-1].role == "user":
                    last_message = messages[-1]
                    embedding = await embedding_service.generate_embedding(last_message.content)
                    
                    if DATABASE_URL.startswith("postgresql") and PGVECTOR_AVAILABLE:
                        embedding_data = embedding
                    else:
                        import json
                        embedding_data = json.dumps(embedding) if embedding else None
                    
                    turn = ConversationTurn(
                        conversation_id=conversation.id,
                        user_id=user_id,
                        role=last_message.role,
                        content=last_message.content,
                        message_index=current_turn_count,
                        embedding=embedding_data
                    )
                    db.add(turn)
                    current_turn_count += 1
                
                if response_content:
                    response_embedding = await embedding_service.generate_embedding(response_content)
                    
                    if DATABASE_URL.startswith("postgresql") and PGVECTOR_AVAILABLE:
                        embedding_data = response_embedding
                    else:
                        import json
                        embedding_data = json.dumps(response_embedding) if response_embedding else None
                    
                    turn = ConversationTurn(
                        conversation_id=conversation.id,
                        user_id=user_id,
                        role="assistant",
                        content=response_content,
                        message_index=current_turn_count,
                        embedding=embedding_data
                    )
                    db.add(turn)
                
                db.commit()
                await self.generate_conversation_title(conversation.id, db)
                
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Error storing legacy conversation: {e}")

    async def generate_conversation_title(self, conversation_id, db):
        """Generate a descriptive title for the conversation"""
        try:
            # Get the first few user messages to generate a title
            turns = db.query(ConversationTurn).filter(
                ConversationTurn.conversation_id == conversation_id,
                ConversationTurn.role == "user"
            ).order_by(ConversationTurn.message_index).limit(3).all()
            
            if not turns:
                return
            
            # Create a summary of the user's initial messages
            user_messages = [turn.content for turn in turns]
            combined_content = " | ".join(user_messages)
            
            # Generate a short title (keep it simple for now)
            if len(combined_content) > 100:
                title = combined_content[:97] + "..."
            else:
                title = combined_content
            
            # Update the conversation with the title
            conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
            if conversation:
                conversation.title = title
                conversation.updated_at = datetime.now()
                db.commit()
                
        except Exception as e:
            logger.error(f"Error generating conversation title: {e}")

class EmbeddingService:
    def __init__(self):
        self.client = httpx.AsyncClient()
        self.base_url = EMBEDDING_BASE_URL
        self.model = EMBEDDING_MODEL
        self.dimension = EMBEDDING_DIM
    
    async def generate_embedding(self, text: str) -> list[float]:
        """Generate embedding for text using BGE-M3 model"""
        try:
            # Use the embeddings endpoint
            response = await self.client.post(
                f"{self.base_url}/v1/embeddings",
                json={
                    "model": self.model,
                    "input": text,
                    "encoding_format": "float"
                },
                headers={"Authorization": "Bearer dummy"},
                timeout=30.0
            )
            response.raise_for_status()
            
            result = response.json()
            embedding = result["data"][0]["embedding"]
            
            # Ensure the embedding has the correct dimension
            if len(embedding) != self.dimension:
                logger.warning(f"Expected embedding dimension {self.dimension}, got {len(embedding)}")
                # Pad or truncate to match expected dimension
                if len(embedding) < self.dimension:
                    embedding.extend([0.0] * (self.dimension - len(embedding)))
                else:
                    embedding = embedding[:self.dimension]
            
            return embedding
            
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return None
    
    async def generate_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts"""
        try:
            # For now, process individually to avoid API limits
            embeddings = []
            for text in texts:
                embedding = await self.generate_embedding(text)
                if embedding:
                    embeddings.append(embedding)
                else:
                    # Return zero vector for failed embeddings
                    embeddings.append([0.0] * self.dimension)
            return embeddings
            
        except Exception as e:
            logger.error(f"Error generating batch embeddings: {e}")
            return [[0.0] * self.dimension] * len(texts)

llm_client = SimpleLLMClient()
embedding_service = EmbeddingService()

# Document Processing Service
class DocumentProcessor:
    def __init__(self):
        self.supported_types = {
            "application/pdf": self._extract_pdf_text,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": self._extract_docx_text,
            "application/msword": self._extract_doc_text,
            "text/plain": self._extract_text_file,
            "text/markdown": self._extract_text_file,
            "text/csv": self._extract_text_file,
        }
        
        # Initialize embedding model
        if SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
                logger.info("Initialized embedding model: all-MiniLM-L6-v2")
            except Exception as e:
                logger.error(f"Failed to initialize embedding model: {e}")
                self.embedding_model = None
        else:
            self.embedding_model = None
        
        # Initialize ChromaDB
        if CHROMADB_AVAILABLE:
            try:
                # Create chroma_data directory if it doesn't exist
                os.makedirs("chroma_data", exist_ok=True)
                self.chroma_client = chromadb.PersistentClient(path="chroma_data")
                logger.info("Initialized ChromaDB client")
            except Exception as e:
                logger.error(f"Failed to initialize ChromaDB: {e}")
                self.chroma_client = None
        else:
            self.chroma_client = None
    
    def _extract_pdf_text(self, file_path: str) -> str:
        """Extract text from PDF file with robust error handling"""
        try:
            import PyPDF2
            text = ""
            
            with open(file_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                
                # Process all pages (or reasonable limit for very large documents)
                max_pages = min(len(reader.pages), 500)  # Up to 500 pages
                
                for i in range(max_pages):
                    try:
                        page = reader.pages[i]
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                        
                        # Break if we have extremely large text to prevent memory issues
                        if len(text) > 5000000:  # Limit to ~5MB of text
                            logger.info(f"PDF text extraction stopped at {len(text)} characters (5MB limit reached)")
                            break
                            
                    except Exception as page_error:
                        logger.warning(f"Error extracting page {i}: {page_error}")
                        continue
                
                if text.strip():
                    logger.info(f"Successfully extracted {len(text)} characters from PDF")
                    return text.strip()
                else:
                    logger.warning("No text extracted from PDF - might be image-based or encrypted")
                    return ""
                    
        except ImportError:
            logger.error("PyPDF2 not available for PDF text extraction")
            return ""
        except Exception as e:
            logger.error(f"Error extracting PDF text: {e}")
            return ""
    
    def _extract_docx_text(self, file_path: str) -> str:
        """Extract text from DOCX file"""
        try:
            from docx import Document
            doc = Document(file_path)
            text = ""
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
            return text.strip()
        except Exception as e:
            logger.error(f"Error extracting DOCX text: {e}")
            return ""
    
    def _extract_doc_text(self, file_path: str) -> str:
        """Extract text from DOC file (legacy Word format)"""
        # For now, return empty - would need additional libraries like python-docx2txt
        logger.warning("DOC file format not fully supported yet")
        return ""
    
    def _extract_text_file(self, file_path: str) -> str:
        """Extract text from plain text files"""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read()
        except UnicodeDecodeError:
            try:
                with open(file_path, 'r', encoding='latin-1') as file:
                    return file.read()
            except Exception as e:
                logger.error(f"Error reading text file: {e}")
                return ""
        except Exception as e:
            logger.error(f"Error reading text file: {e}")
            return ""
    
    def extract_text(self, file_path: str, mime_type: str) -> str:
        """Extract text from a file based on its MIME type"""
        if mime_type not in self.supported_types:
            logger.warning(f"Unsupported MIME type: {mime_type}")
            return ""
        
        try:
            return self.supported_types[mime_type](file_path)
        except Exception as e:
            logger.error(f"Error extracting text from {file_path}: {e}")
            return ""
    
    def chunk_text(self, text: str, chunk_size: int = 1500, overlap: int = 300) -> list[str]:
        """Split text into overlapping chunks for better context preservation"""
        if len(text) <= chunk_size:
            return [text]
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + chunk_size
            
            # Try to break at sentence boundary
            if end < len(text):
                # Look for sentence endings
                sentence_end = max(
                    text.rfind('.', start, end),
                    text.rfind('!', start, end),
                    text.rfind('?', start, end)
                )
                if sentence_end > start:
                    end = sentence_end + 1
                else:
                    # Fallback to word boundary
                    word_end = text.rfind(' ', start, end)
                    if word_end > start:
                        end = word_end
            
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            
            start = end - overlap if end < len(text) else end
        
        return chunks
    
    def get_or_create_collection(self, user_id: str):
        """Get or create a ChromaDB collection for a user"""
        if not self.chroma_client:
            return None
        
        collection_name = f"user_{user_id}_documents"
        try:
            return self.chroma_client.get_or_create_collection(name=collection_name)
        except Exception as e:
            logger.error(f"Failed to get/create collection for user {user_id}: {e}")
            return None
    
    def vectorize_chunks(self, chunks: list[str], document_id: str, user_id: str) -> bool:
        """Vectorize document chunks and store in ChromaDB"""
        if not self.embedding_model or not self.chroma_client:
            logger.warning("Embedding model or ChromaDB not available for vectorization")
            return False
        
        collection = self.get_or_create_collection(user_id)
        if not collection:
            return False
        
        try:
            # Generate embeddings for all chunks
            embeddings = self.embedding_model.encode(chunks)
            
            # Prepare metadata and IDs
            ids = [f"{document_id}_chunk_{i}" for i in range(len(chunks))]
            metadatas = [
                {
                    "document_id": document_id,
                    "chunk_index": i,
                    "user_id": user_id
                }
                for i in range(len(chunks))
            ]
            
            # Add to ChromaDB
            collection.add(
                embeddings=embeddings.tolist(),
                documents=chunks,
                metadatas=metadatas,
                ids=ids
            )
            
            logger.info(f"Successfully vectorized {len(chunks)} chunks for document {document_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error vectorizing chunks: {e}")
            return False
    
    def search_documents(self, query: str, user_id: str, n_results: int = 5) -> list[dict]:
        """Search for relevant document chunks using vector similarity"""
        if not self.embedding_model or not self.chroma_client:
            logger.warning("Embedding model or ChromaDB not available for search")
            return []
        
        collection = self.get_or_create_collection(user_id)
        if not collection:
            return []
        
        try:
            # Generate embedding for query
            query_embedding = self.embedding_model.encode([query])
            
            # Search in ChromaDB
            results = collection.query(
                query_embeddings=query_embedding.tolist(),
                n_results=n_results,
                include=['documents', 'metadatas', 'distances']
            )
            
            # Format results
            search_results = []
            if results['documents'] and results['documents'][0]:
                for i, doc in enumerate(results['documents'][0]):
                    search_results.append({
                        'content': doc,
                        'metadata': results['metadatas'][0][i],
                        'similarity': 1 - results['distances'][0][i]  # Convert distance to similarity
                    })
            
            return search_results
            
        except Exception as e:
            logger.error(f"Error searching documents: {e}")
            return []
    
    def delete_document_vectors(self, document_id: str, user_id: str) -> bool:
        """Delete all vectors for a specific document"""
        if not self.chroma_client:
            return False
        
        collection = self.get_or_create_collection(user_id)
        if not collection:
            return False
        
        try:
            # Find all chunk IDs for this document
            results = collection.get(where={"document_id": document_id})
            if results['ids']:
                collection.delete(ids=results['ids'])
                logger.info(f"Deleted {len(results['ids'])} vectors for document {document_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting document vectors: {e}")
            return False

document_processor = DocumentProcessor()

# NTFY Notification Service
class NTFYService:
    """Service for sending mobile notifications via NTFY with AI-generated messages"""
    
    def __init__(self):
        self.server_url = NTFY_SERVER_URL
        self.enabled = NTFY_ENABLED
        self.timers_topic = NTFY_TIMERS_TOPIC
        self.reminders_topic = NTFY_REMINDERS_TOPIC
        self.documents_topic = NTFY_DOCUMENTS_TOPIC
        self.system_topic = NTFY_SYSTEM_TOPIC
        
        if self.enabled:
            logger.info(f"✅ NTFY service initialized: {self.server_url}")
        else:
            logger.info("⚠️ NTFY service disabled")
    
    async def generate_ai_notification_message(
        self,
        notification_type: str,
        context: dict,
        user_context: str = None
    ) -> tuple[str, str]:
        """Generate AI-powered notification title and message"""
        try:
            # Build the prompt based on notification type
            if notification_type == "timer":
                system_prompt = f"""You are {ASSISTANT_NAME}, a helpful AI assistant. Generate a friendly, personal notification message for a timer that just finished.

Context:
- Timer title: {context.get('title', 'Timer')}
- Duration: {context.get('duration', 'Unknown duration')}
- User context: {user_context or 'No recent context available'}

Generate:
1. A short, catchy title (max 30 characters)
2. A warm, encouraging message (max 100 characters)

Be personal, encouraging, and reflect Sara's personality. Use natural language. No emojis in title, but you can use one emoji in the message if appropriate.

Format your response as:
Title: [title]
Message: [message]"""

            elif notification_type == "reminder":
                system_prompt = f"""You are {ASSISTANT_NAME}, a helpful AI assistant. Generate a friendly, personal reminder notification.

Context:
- Reminder title: {context.get('title', 'Reminder')}
- Description: {context.get('description', '')}
- Due time: {context.get('reminder_time', 'Now')}
- User context: {user_context or 'No recent context available'}

Generate:
1. A short, relevant title (max 30 characters)
2. A helpful, contextual message (max 100 characters)

Be personal, helpful, and reflect Sara's caring personality. Reference the user's context if relevant. No emojis in title, but you can use one emoji in the message if appropriate.

Format your response as:
Title: [title]
Message: [message]"""

            elif notification_type == "document":
                system_prompt = f"""You are {ASSISTANT_NAME}, a helpful AI assistant. Generate a notification for document processing.

Context:
- Document title: {context.get('title', 'Document')}
- Action: {context.get('action', 'processed')}
- User context: {user_context or 'No recent context available'}

Generate:
1. A clear, informative title (max 30 characters)
2. A concise status message (max 100 characters)

Be professional but friendly. No emojis in title, but you can use one emoji in the message if appropriate.

Format your response as:
Title: [title]
Message: [message]"""

            else:
                # Fallback for unknown types
                return "Notification", f"You have a new {notification_type} notification."

            # Generate the AI response using smaller/faster model for notifications
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{OPENAI_BASE_URL}/chat/completions",
                    json={
                        "model": OPENAI_NOTIFICATION_MODEL,
                        "messages": [{"role": "system", "content": system_prompt}],
                        "temperature": 0.7,
                        "max_tokens": 150
                    },
                    headers={"Authorization": "Bearer dummy"}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    ai_response = result["choices"][0]["message"]["content"]
                    
                    # Parse the response
                    lines = ai_response.strip().split('\n')
                    title = "Notification"
                    message = f"You have a new {notification_type} notification."
                    
                    for line in lines:
                        if line.startswith("Title:"):
                            title = line.replace("Title:", "").strip()
                        elif line.startswith("Message:"):
                            message = line.replace("Message:", "").strip()
                    
                    return title, message
                else:
                    logger.warning(f"AI message generation failed: {response.status_code}")
                    
        except Exception as e:
            logger.warning(f"AI message generation error: {e}")
        
        # Fallback to simple messages if AI generation fails
        if notification_type == "timer":
            return "Timer Complete!", f"Your {context.get('duration', '')} timer '{context.get('title', 'Timer')}' finished."
        elif notification_type == "reminder":
            return "Reminder", f"Don't forget: {context.get('title', 'Reminder')}"
        elif notification_type == "document":
            return f"Document {context.get('action', 'Ready')}", f"'{context.get('title', 'Document')}' is ready."
        else:
            return "Notification", f"You have a new {notification_type} notification."
    
    async def get_recent_user_context(self, user_id: str, limit: int = 3) -> str:
        """Get recent user context for personalization"""
        try:
            db = SessionLocal()
            try:
                # Get recent episodes for context
                recent_episodes = db.query(Episode).filter(
                    Episode.user_id == user_id
                ).order_by(Episode.created_at.desc()).limit(limit).all()
                
                if recent_episodes:
                    context_items = []
                    for episode in recent_episodes:
                        if episode.role == "user" and len(episode.content) > 10:
                            # Truncate long messages
                            content = episode.content[:100] + "..." if len(episode.content) > 100 else episode.content
                            context_items.append(f"User said: {content}")
                    
                    return " | ".join(context_items) if context_items else None
                return None
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Error getting user context: {e}")
            return None
    
    async def send_notification(
        self,
        topic: str,
        title: str,
        message: str,
        priority: str = "default",
        tags: list = None,
        actions: list = None
    ) -> bool:
        """Send a notification to NTFY server"""
        if not self.enabled:
            logger.debug("NTFY disabled, skipping notification")
            return False
        
        try:
            headers = {
                "Title": title,
                "Priority": priority,
            }
            
            if tags:
                headers["Tags"] = ",".join(tags)
            
            if actions:
                # Format actions for NTFY
                action_strings = []
                for action in actions:
                    if action.get("type") == "view":
                        action_strings.append(f"view, {action['label']}, {action['url']}")
                    elif action.get("type") == "http":
                        method = action.get("method", "POST")
                        body = action.get("body", "")
                        action_strings.append(f"http, {action['label']}, {action['url']}, method={method}, body={body}")
                
                if action_strings:
                    headers["Actions"] = "; ".join(action_strings)
            
            url = f"{self.server_url}/{topic}"
            
            async with httpx.AsyncClient() as client:
                # Add proper encoding headers
                headers["Content-Type"] = "text/plain; charset=utf-8"
                
                response = await client.post(
                    url, 
                    headers=headers, 
                    content=message.encode('utf-8')
                )
                
                if response.status_code == 200:
                    logger.info(f"NTFY notification sent to {topic}: {title}")
                    return True
                else:
                    logger.error(f"NTFY notification failed: {response.status_code} - {response.text}")
                    return False
                    
        except Exception as e:
            logger.error(f"NTFY notification error: {e}")
            return False
    
    async def send_timer_notification(self, title: str, duration: str, timer_id: str = None, user_id: str = None) -> bool:
        """Send AI-generated timer completion notification"""
        actions = [
            {
                "type": "view",
                "label": "Open Sara",
                "url": "https://sara.avery.cloud"
            }
        ]
        
        if timer_id:
            actions.append({
                "type": "http", 
                "label": "Dismiss",
                "url": f"https://sara.avery.cloud/api/timers/{timer_id}/complete",
                "method": "PATCH"
            })
        
        # Get user context for personalization
        user_context = None
        if user_id:
            user_context = await self.get_recent_user_context(user_id)
        
        # Generate AI-powered notification message
        ai_title, ai_message = await self.generate_ai_notification_message(
            notification_type="timer",
            context={
                "title": title,
                "duration": duration,
                "timer_id": timer_id
            },
            user_context=user_context
        )
        
        return await self.send_notification(
            topic=self.timers_topic,
            title=ai_title,
            message=ai_message,
            priority="high",
            tags=["timer", "sara", "urgent"],
            actions=actions
        )
    
    async def send_reminder_notification(self, title: str, reminder_time: str, reminder_id: str = None, description: str = None, user_id: str = None) -> bool:
        """Send AI-generated reminder notification"""
        actions = [
            {
                "type": "view",
                "label": "Open Sara", 
                "url": "https://sara.avery.cloud"
            }
        ]
        
        if reminder_id:
            actions.append({
                "type": "http",
                "label": "Mark Complete",
                "url": f"https://sara.avery.cloud/api/reminders/{reminder_id}/complete",
                "method": "PATCH"
            })
        
        # Get user context for personalization
        user_context = None
        if user_id:
            user_context = await self.get_recent_user_context(user_id)
        
        # Generate AI-powered notification message
        ai_title, ai_message = await self.generate_ai_notification_message(
            notification_type="reminder",
            context={
                "title": title,
                "description": description or "",
                "reminder_time": reminder_time,
                "reminder_id": reminder_id
            },
            user_context=user_context
        )
        
        return await self.send_notification(
            topic=self.reminders_topic,
            title=ai_title,
            message=ai_message,
            priority="default",
            tags=["reminder", "sara", "productivity"],
            actions=actions
        )
    
    async def send_document_notification(self, title: str, action: str = "processed", user_id: str = None) -> bool:
        """Send AI-generated document processing notification"""
        actions = [
            {
                "type": "view",
                "label": "View Documents",
                "url": "https://sara.avery.cloud"
            }
        ]
        
        # Get user context for personalization
        user_context = None
        if user_id:
            user_context = await self.get_recent_user_context(user_id)
        
        # Generate AI-powered notification message
        ai_title, ai_message = await self.generate_ai_notification_message(
            notification_type="document",
            context={
                "title": title,
                "action": action
            },
            user_context=user_context
        )
        
        return await self.send_notification(
            topic=self.documents_topic,
            title=ai_title,
            message=ai_message,
            priority="default",
            tags=["document", "sara"],
            actions=actions
        )

# Advanced Intelligence System for Sara
from typing import Union, List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

class WindowType(Enum):
    TEMPORAL = "temporal"
    TOPIC = "topic"
    EMOTIONAL = "emotional"
    IMPORTANCE = "importance"
    HYBRID = "hybrid"

@dataclass
class ContextWindowConfig:
    """Configuration for a context window"""
    window_type: WindowType
    parameters: Dict[str, Any]
    
    @classmethod
    def temporal(cls, duration: Union[timedelta, str]):
        """Create temporal window (e.g., last 24 hours, last week)"""
        if isinstance(duration, str):
            if duration == "today":
                duration = timedelta(days=1)
            elif duration == "week":
                duration = timedelta(weeks=1)
            elif duration == "month":
                duration = timedelta(days=30)
            else:
                # Parse duration string like "2d", "3h", "1w"
                duration = cls._parse_duration(duration)
        
        return cls(WindowType.TEMPORAL, {"duration": duration})
    
    @classmethod
    def topic(cls, topics: Union[str, List[str]], duration: Optional[timedelta] = None):
        """Create topic-based window"""
        if isinstance(topics, str):
            topics = [topics]
        params = {"topics": topics}
        if duration:
            params["duration"] = duration
        return cls(WindowType.TOPIC, params)
    
    @classmethod
    def emotional(cls, emotional_states: Union[str, List[str]], duration: Optional[timedelta] = None):
        """Create emotional context window"""
        if isinstance(emotional_states, str):
            emotional_states = [emotional_states]
        params = {"emotional_states": emotional_states}
        if duration:
            params["duration"] = duration
        return cls(WindowType.EMOTIONAL, params)
    
    @classmethod
    def importance(cls, min_importance: float, duration: Optional[timedelta] = None):
        """Create importance-based window"""
        params = {"min_importance": min_importance}
        if duration:
            params["duration"] = duration
        return cls(WindowType.IMPORTANCE, params)
    
    @classmethod
    def hybrid(cls, **kwargs):
        """Create hybrid window with multiple criteria"""
        return cls(WindowType.HYBRID, kwargs)
    
    @staticmethod
    def _parse_duration(duration_str: str) -> timedelta:
        """Parse duration strings like '2d', '3h', '1w'"""
        import re
        match = re.match(r'(\d+)([hdwm])', duration_str.lower())
        if not match:
            return timedelta(hours=1)  # Default fallback
        
        amount, unit = match.groups()
        amount = int(amount)
        
        if unit == 'h':
            return timedelta(hours=amount)
        elif unit == 'd':
            return timedelta(days=amount)
        elif unit == 'w':
            return timedelta(weeks=amount)
        elif unit == 'm':
            return timedelta(days=amount * 30)
        else:
            return timedelta(hours=1)

class EmotionalAnalyzer:
    """Real-time emotional analysis using fast model"""
    
    def __init__(self, fast_model_url: str = None):
        self.fast_model_url = fast_model_url or os.getenv("FAST_MODEL_URL", OPENAI_BASE_URL)
        self.fast_model = os.getenv("FAST_MODEL", "gpt-oss:20b")  # Your fast model
        
    async def analyze_emotional_state(self, content: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """Analyze emotional state of content using fast model"""
        try:
            context = context or {}
            
            prompt = f"""Analyze the emotional state in this message and return ONLY valid JSON:

Message: "{content}"

Context: Time: {context.get('time', 'unknown')}, Previous mood: {context.get('prev_mood', 'unknown')}

Return JSON format:
{{
    "primary_emotion": "positive|negative|neutral|excited|frustrated|contemplative|focused|relaxed",
    "intensity": 0.8,
    "sub_emotions": ["curious", "determined"],
    "energy_level": "high|medium|low",
    "sentiment": "positive|negative|neutral",
    "confidence": 0.9
}}"""

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.fast_model_url}/chat/completions",
                    json={
                        "model": self.fast_model,
                        "messages": [{"role": "system", "content": prompt}],
                        "temperature": 0.3,
                        "max_tokens": 200
                    },
                    headers={"Authorization": "Bearer dummy"}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    ai_response = result["choices"][0]["message"]["content"].strip()
                    
                    # Try to parse JSON response
                    try:
                        # Clean up response to extract JSON
                        import re
                        json_match = re.search(r'\{.*\}', ai_response, re.DOTALL)
                        if json_match:
                            return json.loads(json_match.group())
                    except json.JSONDecodeError:
                        pass
                        
        except Exception as e:
            logger.warning(f"Emotional analysis failed: {e}")
        
        # Fallback to simple sentiment
        return {
            "primary_emotion": "neutral",
            "intensity": 0.5,
            "sub_emotions": [],
            "energy_level": "medium",
            "sentiment": "neutral",
            "confidence": 0.1
        }

class ContextWindowManager:
    """Manages context windows for intelligent memory retrieval"""
    
    def __init__(self):
        self.emotional_analyzer = EmotionalAnalyzer()
    
    async def auto_select_window(self, query: str, user_id: str) -> ContextWindowConfig:
        """Automatically select appropriate context window based on query"""
        query_lower = query.lower()
        
        # Temporal indicators
        if any(term in query_lower for term in ["today", "this morning", "earlier", "now"]):
            return ContextWindowConfig.temporal("today")
        elif any(term in query_lower for term in ["yesterday", "last night"]):
            return ContextWindowConfig.temporal("2d")
        elif any(term in query_lower for term in ["this week", "recently", "lately"]):
            return ContextWindowConfig.temporal("week")
        elif any(term in query_lower for term in ["this month", "past month"]):
            return ContextWindowConfig.temporal("month")
        
        # Topic indicators
        topic_keywords = {
            "fitness": ["workout", "exercise", "gym", "running", "fitness", "health"],
            "work": ["project", "meeting", "work", "client", "deadline", "task"],
            "learning": ["learn", "study", "course", "tutorial", "research", "book"],
            "personal": ["family", "friend", "relationship", "personal", "feeling"],
            "creative": ["design", "art", "creative", "writing", "music", "photo"]
        }
        
        for topic, keywords in topic_keywords.items():
            if any(keyword in query_lower for keyword in keywords):
                return ContextWindowConfig.topic(topic, timedelta(weeks=2))
        
        # Emotional indicators
        if any(term in query_lower for term in ["feeling", "mood", "stressed", "happy", "sad", "excited"]):
            return ContextWindowConfig.emotional(["all"], timedelta(days=7))
        
        # Importance indicators
        if any(term in query_lower for term in ["important", "priority", "urgent", "critical"]):
            return ContextWindowConfig.importance(0.7, timedelta(weeks=4))
        
        # Default: recent + moderate importance
        return ContextWindowConfig.hybrid(
            duration=timedelta(days=3),
            min_importance=0.4
        )
    
    async def retrieve_episodes_with_window(
        self, 
        user_id: str, 
        window_config: ContextWindowConfig,
        query: str = None,
        limit: int = 10
    ) -> List[dict]:
        """Retrieve episodes using context window"""
        
        db = SessionLocal()
        try:
            # Start with base query
            query_builder = db.query(Episode).filter(Episode.user_id == user_id)
            
            # Apply window filters
            if window_config.window_type == WindowType.TEMPORAL:
                duration = window_config.parameters["duration"]
                cutoff_time = datetime.utcnow() - duration
                query_builder = query_builder.filter(Episode.created_at >= cutoff_time)
            
            elif window_config.window_type == WindowType.TOPIC:
                topics = window_config.parameters["topics"]
                # Filter by episodes that contain any of the topics
                topic_filter = or_(*[Episode.topics.like(f'%"{topic}"%') for topic in topics])
                query_builder = query_builder.filter(topic_filter)
                
                if "duration" in window_config.parameters:
                    duration = window_config.parameters["duration"]
                    cutoff_time = datetime.utcnow() - duration
                    query_builder = query_builder.filter(Episode.created_at >= cutoff_time)
            
            elif window_config.window_type == WindowType.EMOTIONAL:
                emotional_states = window_config.parameters["emotional_states"]
                if "all" not in emotional_states:
                    # Filter by emotional tone
                    emotion_filter = or_(*[
                        Episode.emotional_tone.like(f'%"primary_emotion": "{emotion}"%') 
                        for emotion in emotional_states
                    ])
                    query_builder = query_builder.filter(emotion_filter)
                
                if "duration" in window_config.parameters:
                    duration = window_config.parameters["duration"]
                    cutoff_time = datetime.utcnow() - duration
                    query_builder = query_builder.filter(Episode.created_at >= cutoff_time)
            
            elif window_config.window_type == WindowType.IMPORTANCE:
                min_importance = window_config.parameters["min_importance"]
                query_builder = query_builder.filter(Episode.importance >= min_importance)
                
                if "duration" in window_config.parameters:
                    duration = window_config.parameters["duration"]
                    cutoff_time = datetime.utcnow() - duration
                    query_builder = query_builder.filter(Episode.created_at >= cutoff_time)
            
            elif window_config.window_type == WindowType.HYBRID:
                params = window_config.parameters
                
                if "duration" in params:
                    cutoff_time = datetime.utcnow() - params["duration"]
                    query_builder = query_builder.filter(Episode.created_at >= cutoff_time)
                
                if "min_importance" in params:
                    query_builder = query_builder.filter(Episode.importance >= params["min_importance"])
                
                if "topics" in params:
                    topics = params["topics"]
                    topic_filter = or_(*[Episode.topics.like(f'%"{topic}"%') for topic in topics])
                    query_builder = query_builder.filter(topic_filter)
            
            # Order by composite relevance score
            # For now, order by recency and importance
            episodes = query_builder.order_by(
                Episode.importance.desc(),
                Episode.created_at.desc()
            ).limit(limit).all()
            
            # Update access tracking
            for episode in episodes:
                episode.access_count += 1
                episode.last_accessed = datetime.utcnow()
            
            db.commit()
            
            # Convert to detached objects to avoid session issues
            episode_data = []
            for episode in episodes:
                episode_dict = {
                    'id': episode.id,
                    'conversation_id': episode.conversation_id,
                    'user_id': episode.user_id,
                    'role': episode.role,
                    'content': episode.content,
                    'importance': episode.importance,
                    'emotional_tone': episode.emotional_tone,
                    'topics': episode.topics,
                    'context_tags': episode.context_tags,
                    'access_count': episode.access_count,
                    'last_accessed': episode.last_accessed,
                    'memory_type': episode.memory_type,
                    'source': episode.source,
                    'created_at': episode.created_at,
                    'embedding': episode.embedding
                }
                episode_data.append(episode_dict)
            
            return episode_data
            
        finally:
            db.close()

class IntelligentMemoryService:
    """Enhanced memory service with context windows and emotional intelligence"""
    
    def __init__(self):
        self.window_manager = ContextWindowManager()
        self.emotional_analyzer = EmotionalAnalyzer()
    
    async def store_episode(
        self, 
        user_id: str, 
        role: str, 
        content: str, 
        conversation_id: str = None,
        source: str = "chat",
        memory_type: str = "conversation"
    ) -> Episode:
        """Store an episode with intelligent analysis"""
        
        # Analyze emotional content
        emotional_analysis = await self.emotional_analyzer.analyze_emotional_state(content)
        
        # Extract topics (simplified for now)
        topics = await self._extract_topics(content)
        
        # Calculate importance (simplified for now)
        importance = await self._calculate_importance(content, role, emotional_analysis)
        
        # Generate embedding (if available)
        embedding = await self._generate_embedding(content)
        
        # Store episode
        db = SessionLocal()
        try:
            episode = Episode(
                conversation_id=conversation_id,
                user_id=user_id,
                role=role,
                content=content,
                importance=importance,
                emotional_tone=json.dumps(emotional_analysis),
                topics=json.dumps(topics),
                context_tags=json.dumps([]),  # Will be enhanced later
                memory_type=memory_type,
                source=source,
                embedding=json.dumps(embedding) if embedding and not PGVECTOR_AVAILABLE else embedding
            )
            
            db.add(episode)
            db.commit()
            db.refresh(episode)
            
            logger.info(f"🧠 Stored episode {episode.id}: importance={importance:.2f}, emotion={emotional_analysis.get('primary_emotion')}")
            return episode
            
        finally:
            db.close()
    
    async def intelligent_memory_search(
        self, 
        user_id: str, 
        query: str, 
        auto_window: bool = True,
        custom_window: ContextWindowConfig = None
    ) -> List[dict]:
        """Search memory with intelligent context window selection"""
        
        # Select appropriate context window
        if auto_window and not custom_window:
            window_config = await self.window_manager.auto_select_window(query, user_id)
            logger.info(f"🔍 Auto-selected window: {window_config.window_type.value} with params {window_config.parameters}")
        else:
            window_config = custom_window or ContextWindowConfig.temporal("week")
        
        # Retrieve episodes using window
        episodes = await self.window_manager.retrieve_episodes_with_window(
            user_id, window_config, query
        )
        
        logger.info(f"🧠 Retrieved {len(episodes)} episodes using {window_config.window_type.value} window")
        return episodes
    
    async def _extract_topics(self, content: str) -> List[str]:
        """Extract topics from content (simplified implementation)"""
        # Simple keyword-based topic extraction for now
        topic_keywords = {
            "fitness": ["workout", "exercise", "gym", "running", "fitness", "health", "training"],
            "work": ["project", "meeting", "work", "client", "deadline", "task", "business"],
            "learning": ["learn", "study", "course", "tutorial", "research", "book", "education"],
            "personal": ["family", "friend", "relationship", "personal", "feeling", "life"],
            "creative": ["design", "art", "creative", "writing", "music", "photo", "draw"],
            "technology": ["code", "programming", "tech", "computer", "software", "app"],
            "travel": ["travel", "trip", "vacation", "flight", "hotel", "visit"],
            "food": ["cook", "recipe", "eat", "restaurant", "food", "meal", "dinner"]
        }
        
        content_lower = content.lower()
        detected_topics = []
        
        for topic, keywords in topic_keywords.items():
            if any(keyword in content_lower for keyword in keywords):
                detected_topics.append(topic)
        
        return detected_topics[:3]  # Limit to top 3 topics
    
    async def _calculate_importance(self, content: str, role: str, emotional_analysis: Dict) -> float:
        """Calculate importance score for content"""
        base_importance = 0.5
        
        # Role-based adjustment
        if role == "user":
            base_importance += 0.1  # User input slightly more important
        
        # Length-based adjustment
        if len(content) > 200:
            base_importance += 0.1  # Longer content might be more important
        
        # Emotional intensity adjustment
        intensity = emotional_analysis.get("intensity", 0.5)
        if intensity > 0.7:
            base_importance += 0.2  # High emotional intensity increases importance
        
        # Keyword-based importance
        important_keywords = [
            "important", "urgent", "remember", "note", "todo", "deadline",
            "meeting", "appointment", "call", "email", "follow up"
        ]
        content_lower = content.lower()
        keyword_matches = sum(1 for keyword in important_keywords if keyword in content_lower)
        base_importance += min(keyword_matches * 0.1, 0.3)
        
        return min(base_importance, 1.0)  # Cap at 1.0
    
    async def _generate_embedding(self, content: str) -> Optional[List[float]]:
        """Generate embedding for content (if available)"""
        # This would integrate with your embedding service
        # For now, return None
        return None

# Import necessary modules for the new functionality
from sqlalchemy import or_

# ========================================
# DREAMING & CONSOLIDATION SERVICE
# ========================================

class DreamingService:
    """Background service for memory consolidation, pattern detection, and insight generation"""
    
    def __init__(self):
        self.fast_model = "gpt-oss:20b"  # Faster model for quick analysis
        self.smart_model = "gpt-oss:120b"  # Smarter model for deep insights
        self.is_dreaming = False
        logger.info("🧠 DreamingService initialized")
    
    async def dream_cycle(self, user_id: str, min_episodes: int = 5):
        """Run a complete dreaming cycle for a user"""
        if self.is_dreaming:
            logger.info("🌙 Already dreaming, skipping cycle")
            return
            
        try:
            self.is_dreaming = True
            logger.info(f"🌙 Starting dream cycle for user {user_id}")
            
            # Step 1: Analyze recent episodes for patterns
            insights = await self._analyze_recent_patterns(user_id)
            
            # Step 2: Cluster related memories
            clusters = await self._cluster_related_memories(user_id)
            
            # Step 3: Detect forgotten gems (old but potentially relevant memories)
            forgotten_gems = await self._find_forgotten_gems(user_id)
            
            # Step 4: Generate connection insights
            connections = await self._suggest_memory_connections(user_id)
            
            # Step 5: Create trend insights
            trends = await self._analyze_behavioral_trends(user_id)
            
            # Store all insights
            all_insights = insights + clusters + forgotten_gems + connections + trends
            await self._store_insights(user_id, all_insights)
            
            logger.info(f"🌙 Dream cycle complete: generated {len(all_insights)} insights")
            
        except Exception as e:
            logger.error(f"❌ Dream cycle failed: {e}")
        finally:
            self.is_dreaming = False
    
    async def _analyze_recent_patterns(self, user_id: str) -> List[Dict[str, Any]]:
        """Analyze recent episodes for emotional and topical patterns"""
        db = SessionLocal()
        try:
            # Get episodes from last 7 days
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=7)
            episodes = db.query(Episode).filter(
                Episode.user_id == user_id,
                Episode.created_at >= cutoff_date
            ).order_by(Episode.created_at.desc()).limit(50).all()
            
            if len(episodes) < 3:
                return []
            
            # Analyze emotional patterns
            emotional_pattern = await self._detect_emotional_patterns(episodes)
            
            # Analyze topic patterns  
            topic_pattern = await self._detect_topic_patterns(episodes)
            
            insights = []
            if emotional_pattern:
                insights.append({
                    "type": "pattern",
                    "subtype": "emotional",
                    "title": f"Emotional Pattern: {emotional_pattern['dominant_emotion'].title()}",
                    "content": emotional_pattern["description"],
                    "confidence": emotional_pattern["confidence"],
                    "episode_ids": [ep.id for ep in episodes]
                })
            
            if topic_pattern:
                insights.append({
                    "type": "pattern", 
                    "subtype": "topical",
                    "title": f"Recent Focus: {topic_pattern['dominant_topic'].title()}",
                    "content": topic_pattern["description"],
                    "confidence": topic_pattern["confidence"],
                    "episode_ids": [ep.id for ep in episodes]
                })
            
            return insights
        finally:
            db.close()
    
    async def _detect_emotional_patterns(self, episodes: List[Episode]) -> Optional[Dict[str, Any]]:
        """Detect emotional patterns in recent episodes"""
        try:
            # Extract emotional data
            emotions = []
            content_samples = []
            
            for episode in episodes:
                if episode.emotional_tone:
                    try:
                        emotion_data = json.loads(episode.emotional_tone)
                        emotions.append(emotion_data.get("primary_emotion", "neutral"))
                        content_samples.append(episode.content[:100])
                    except:
                        continue
            
            if len(emotions) < 3:
                return None
            
            # Find dominant emotion
            emotion_counts = {}
            for emotion in emotions:
                emotion_counts[emotion] = emotion_counts.get(emotion, 0) + 1
            
            dominant_emotion = max(emotion_counts, key=emotion_counts.get)
            confidence = emotion_counts[dominant_emotion] / len(emotions)
            
            if confidence < 0.3:
                return None
            
            # Generate insight using AI
            prompt = f"""Analyze this emotional pattern:
Dominant emotion: {dominant_emotion}
Frequency: {emotion_counts[dominant_emotion]}/{len(emotions)} conversations
Sample content: {'; '.join(content_samples[:3])}

Generate a 2-3 sentence insight about this emotional pattern and what it might indicate about the user's current state or needs."""
            
            description = await self._call_fast_llm(prompt)
            
            return {
                "dominant_emotion": dominant_emotion,
                "confidence": confidence,
                "description": description or f"You've been experiencing {dominant_emotion} emotions in {confidence:.0%} of recent conversations."
            }
            
        except Exception as e:
            logger.error(f"Error detecting emotional patterns: {e}")
            return None
    
    async def _detect_topic_patterns(self, episodes: List[Episode]) -> Optional[Dict[str, Any]]:
        """Detect topical patterns in recent episodes"""
        try:
            # Extract topics
            all_topics = []
            content_samples = []
            
            for episode in episodes:
                if episode.topics:
                    try:
                        topics_data = json.loads(episode.topics)
                        if isinstance(topics_data, list):
                            all_topics.extend(topics_data)
                        content_samples.append(episode.content[:100])
                    except:
                        continue
            
            if len(all_topics) < 3:
                return None
            
            # Find dominant topic
            topic_counts = {}
            for topic in all_topics:
                topic_counts[topic] = topic_counts.get(topic, 0) + 1
            
            dominant_topic = max(topic_counts, key=topic_counts.get)
            confidence = topic_counts[dominant_topic] / len(all_topics)
            
            if confidence < 0.25:
                return None
            
            # Generate insight
            prompt = f"""Analyze this topic pattern:
Dominant topic: {dominant_topic}
Frequency: {topic_counts[dominant_topic]}/{len(all_topics)} topic instances
Sample content: {'; '.join(content_samples[:3])}

Generate a 2-3 sentence insight about this focus area and potential implications or suggestions."""
            
            description = await self._call_fast_llm(prompt)
            
            return {
                "dominant_topic": dominant_topic,
                "confidence": confidence,
                "description": description or f"You've been focused on {dominant_topic}-related topics in recent conversations."
            }
            
        except Exception as e:
            logger.error(f"Error detecting topic patterns: {e}")
            return None
    
    async def _cluster_related_memories(self, user_id: str) -> List[Dict[str, Any]]:
        """Cluster semantically similar memories"""
        db = SessionLocal()
        try:
            # Get episodes with embeddings from last 30 days
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
            episodes = db.query(Episode).filter(
                Episode.user_id == user_id,
                Episode.created_at >= cutoff_date,
                Episode.embedding.isnot(None)
            ).limit(100).all()
            
            if len(episodes) < 5:
                return []
            
            # Simple clustering based on topic similarity
            clusters = await self._simple_topic_clustering(episodes)
            
            insights = []
            for cluster_id, cluster_episodes in clusters.items():
                if len(cluster_episodes) >= 3:  # Only create insights for clusters with 3+ episodes
                    insight = await self._generate_cluster_insight(cluster_episodes)
                    if insight:
                        insights.append({
                            "type": "connection",
                            "subtype": "cluster",
                            "title": insight["title"],
                            "content": insight["description"],
                            "confidence": insight["confidence"],
                            "episode_ids": [ep.id for ep in cluster_episodes]
                        })
            
            return insights
        finally:
            db.close()
    
    async def _simple_topic_clustering(self, episodes: List[Episode]) -> Dict[str, List[Episode]]:
        """Simple clustering based on shared topics"""
        clusters = {}
        
        for episode in episodes:
            if not episode.topics:
                continue
                
            try:
                topics = json.loads(episode.topics)
                if not topics:
                    continue
                    
                # Use primary topic as cluster key
                primary_topic = topics[0] if isinstance(topics, list) else str(topics)
                
                if primary_topic not in clusters:
                    clusters[primary_topic] = []
                clusters[primary_topic].append(episode)
                
            except:
                continue
        
        return clusters
    
    async def _generate_cluster_insight(self, episodes: List[Episode]) -> Optional[Dict[str, Any]]:
        """Generate insight about a cluster of related episodes"""
        try:
            # Extract key information
            topics = set()
            sample_content = []
            date_range = []
            
            for episode in episodes:
                if episode.topics:
                    try:
                        ep_topics = json.loads(episode.topics)
                        if isinstance(ep_topics, list):
                            topics.update(ep_topics)
                    except:
                        pass
                sample_content.append(episode.content[:80])
                date_range.append(episode.created_at)
            
            if not topics:
                return None
            
            # Calculate date range
            min_date = min(date_range)
            max_date = max(date_range)
            span_days = (max_date - min_date).days
            
            prompt = f"""Analyze this cluster of {len(episodes)} related conversations:
Topics: {', '.join(list(topics)[:5])}
Time span: {span_days} days
Sample content: {' | '.join(sample_content[:3])}

Generate a brief title (4-6 words) and 2-3 sentence insight about this recurring theme and its significance."""
            
            response = await self._call_fast_llm(prompt)
            if not response:
                return None
            
            # Parse response (expecting "Title: ... Description: ...")
            lines = response.strip().split('\n')
            title = f"Recurring Theme: {list(topics)[0].title()}"
            description = response
            
            if len(lines) >= 2:
                title = lines[0].replace("Title:", "").strip()
                description = '\n'.join(lines[1:]).replace("Description:", "").strip()
            
            return {
                "title": title,
                "description": description,
                "confidence": min(0.8, len(episodes) / 10)  # Higher confidence for larger clusters
            }
            
        except Exception as e:
            logger.error(f"Error generating cluster insight: {e}")
            return None
    
    async def _find_forgotten_gems(self, user_id: str) -> List[Dict[str, Any]]:
        """Find old but potentially relevant memories"""
        db = SessionLocal()
        try:
            # Get old episodes (30+ days) with high importance but low recent access
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
            old_episodes = db.query(Episode).filter(
                Episode.user_id == user_id,
                Episode.created_at <= cutoff_date,
                Episode.importance >= 0.7,
                or_(Episode.last_accessed.is_(None), Episode.last_accessed <= cutoff_date)
            ).order_by(Episode.importance.desc()).limit(20).all()
            
            insights = []
            for episode in old_episodes[:3]:  # Top 3 forgotten gems
                insight = await self._create_forgotten_gem_insight(episode)
                if insight:
                    insights.append(insight)
            
            return insights
        finally:
            db.close()
    
    async def _create_forgotten_gem_insight(self, episode: Episode) -> Optional[Dict[str, Any]]:
        """Create insight for a forgotten gem episode"""
        try:
            days_ago = (datetime.now(timezone.utc) - episode.created_at).days
            
            prompt = f"""This is a high-importance conversation from {days_ago} days ago that hasn't been accessed recently:
Content: {episode.content[:200]}
Importance: {episode.importance:.2f}

Generate a brief title and 1-2 sentence insight about why this might be worth revisiting now."""
            
            response = await self._call_fast_llm(prompt)
            if not response:
                return None
            
            return {
                "type": "forgotten_gem",
                "title": f"Memory from {days_ago} days ago",
                "content": response,
                "confidence": episode.importance,
                "episode_ids": [episode.id]
            }
            
        except Exception as e:
            logger.error(f"Error creating forgotten gem insight: {e}")
            return None
    
    async def _suggest_memory_connections(self, user_id: str) -> List[Dict[str, Any]]:
        """Suggest new connections between memories"""
        # For now, return empty list - this would use more advanced similarity analysis
        return []
    
    async def _analyze_behavioral_trends(self, user_id: str) -> List[Dict[str, Any]]:
        """Analyze behavioral and usage trends"""
        db = SessionLocal()
        try:
            # Get episodes from last 14 days vs previous 14 days
            now = datetime.now(timezone.utc)
            recent_start = now - timedelta(days=14)
            older_start = now - timedelta(days=28)
            
            # Recent episodes
            recent_episodes = db.query(Episode).filter(
                Episode.user_id == user_id,
                Episode.created_at >= recent_start
            ).all()
            
            # Older episodes for comparison
            older_episodes = db.query(Episode).filter(
                Episode.user_id == user_id,
                Episode.created_at >= older_start,
                Episode.created_at < recent_start
            ).all()
            
            if len(recent_episodes) < 3 or len(older_episodes) < 3:
                return []
            
            # Analyze activity trend
            activity_trend = await self._analyze_activity_trend(recent_episodes, older_episodes)
            
            insights = []
            if activity_trend:
                insights.append(activity_trend)
            
            return insights
        finally:
            db.close()
    
    async def _analyze_activity_trend(self, recent_episodes: List[Episode], older_episodes: List[Episode]) -> Optional[Dict[str, Any]]:
        """Analyze activity level trends"""
        try:
            recent_count = len(recent_episodes)
            older_count = len(older_episodes)
            
            if older_count == 0:
                return None
            
            change_ratio = recent_count / older_count
            
            if abs(change_ratio - 1.0) < 0.3:  # Less than 30% change
                return None
            
            if change_ratio > 1.3:
                trend = "increased"
                description = f"Your activity has increased by {(change_ratio - 1) * 100:.0f}% compared to the previous period."
            else:
                trend = "decreased" 
                description = f"Your activity has decreased by {(1 - change_ratio) * 100:.0f}% compared to the previous period."
            
            return {
                "type": "trend",
                "subtype": "activity",
                "title": f"Activity Level {trend.title()}",
                "content": description,
                "confidence": min(0.9, abs(change_ratio - 1.0)),
                "episode_ids": [ep.id for ep in recent_episodes]
            }
            
        except Exception as e:
            logger.error(f"Error analyzing activity trend: {e}")
            return None
    
    async def _store_insights(self, user_id: str, insights: List[Dict[str, Any]]):
        """Store generated insights in the database"""
        db = SessionLocal()
        try:
            for insight_data in insights:
                try:
                    dream_insight = DreamInsight(
                        user_id=user_id,
                        dream_date=datetime.now(timezone.utc),
                        insight_type=insight_data["type"],
                        confidence=insight_data["confidence"],
                        title=insight_data["title"],
                        content=insight_data["content"],
                        related_episodes=json.dumps(insight_data.get("episode_ids", []))
                    )
                    
                    db.add(dream_insight)
                    db.commit()
                    logger.info(f"💭 Stored {insight_data['type']} insight: {insight_data['title']}")
                    
                except Exception as e:
                    logger.error(f"Error storing insight: {e}")
                    db.rollback()
        finally:
            db.close()
    
    async def _call_fast_llm(self, prompt: str, max_tokens: int = 150) -> Optional[str]:
        """Call the fast LLM for quick analysis"""
        try:
            # Use the global llm_client instance
            response = await llm_client.chat([{"role": "user", "content": prompt}])
            if response and "choices" in response and response["choices"]:
                return response["choices"][0]["message"]["content"].strip()
            return None
        except Exception as e:
            logger.error(f"Fast LLM call failed: {e}")
            return None
    
    async def _call_smart_llm(self, prompt: str, max_tokens: int = 300) -> Optional[str]:
        """Call the smart LLM for deep analysis"""
        try:
            # Use the global llm_client instance
            response = await llm_client.chat([{"role": "user", "content": prompt}])
            if response and "choices" in response and response["choices"]:
                return response["choices"][0]["message"]["content"].strip()
            return None
        except Exception as e:
            logger.error(f"Smart LLM call failed: {e}")
            return None

# Initialize the intelligent memory service
intelligent_memory_service = IntelligentMemoryService()

# Initialize the dreaming service  
dreaming_service = DreamingService()

ntfy_service = NTFYService()

class NotificationScheduler:
    """Background scheduler for pre-generating NTFY notifications"""
    
    def __init__(self):
        self.scheduled_notifications = {}  # Store pre-generated notifications
        self.running = False
        self.task = None
        
    async def start(self):
        """Start the background notification scheduler"""
        if self.running:
            return
            
        self.running = True
        self.task = asyncio.create_task(self._notification_loop())
        logger.info("🔔 Notification scheduler started")
        
    async def stop(self):
        """Stop the background notification scheduler"""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("🔕 Notification scheduler stopped")
        
    async def _notification_loop(self):
        """Main notification loop that checks for due items every 5 seconds"""
        while self.running:
            try:
                await self._check_and_schedule_notifications()
                await asyncio.sleep(5)  # Check every 5 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Notification scheduler error: {e}")
                await asyncio.sleep(10)  # Wait longer on error
                
    async def _check_and_schedule_notifications(self):
        """Check for notifications that need pre-generation or sending"""
        try:
            db = SessionLocal()
            try:
                now = datetime.now(timezone.utc)
                pre_generate_time = now + timedelta(seconds=20)
                
                # Check timers that need pre-generation
                upcoming_timers = db.query(Timer).filter(
                    Timer.is_active == True
                ).all()
                
                # Filter timers with proper timezone handling
                filtered_timers = []
                for timer in upcoming_timers:
                    # Ensure timer end_time is timezone-aware
                    timer_end_time = timer.end_time
                    if timer_end_time.tzinfo is None:
                        timer_end_time = timer_end_time.replace(tzinfo=timezone.utc)
                    
                    # Check if timer needs pre-generation or sending
                    if timer_end_time <= pre_generate_time and timer_end_time > now:
                        filtered_timers.append(timer)
                
                upcoming_timers = filtered_timers
                
                for timer in upcoming_timers:
                    notification_key = f"timer_{timer.id}"
                    if notification_key not in self.scheduled_notifications:
                        # Pre-generate the notification message
                        duration_str = f"{timer.duration_minutes}min"
                        user_context = await ntfy_service.get_recent_user_context(timer.user_id)
                        
                        title, message = await ntfy_service.generate_ai_notification_message(
                            notification_type="timer",
                            context={
                                "title": timer.title,
                                "duration": duration_str,
                                "timer_id": str(timer.id)
                            },
                            user_context=user_context
                        )
                        
                        self.scheduled_notifications[notification_key] = {
                            "title": title,
                            "message": message,
                            "send_time": timer.end_time,
                            "type": "timer",
                            "timer_id": timer.id,
                            "user_id": timer.user_id
                        }
                        logger.info(f"📝 Pre-generated timer notification for: {timer.title}")
                
                # Check reminders that need pre-generation
                all_reminders = db.query(Reminder).filter(
                    Reminder.is_completed == False
                ).all()
                
                # Filter reminders with proper timezone handling
                filtered_reminders = []
                for reminder in all_reminders:
                    # Ensure reminder time is timezone-aware
                    reminder_time = reminder.reminder_time
                    if reminder_time.tzinfo is None:
                        reminder_time = reminder_time.replace(tzinfo=timezone.utc)
                    
                    # Check if reminder needs pre-generation or sending
                    if reminder_time <= pre_generate_time and reminder_time > now:
                        filtered_reminders.append(reminder)
                
                upcoming_reminders = filtered_reminders
                
                for reminder in upcoming_reminders:
                    notification_key = f"reminder_{reminder.id}"
                    if notification_key not in self.scheduled_notifications:
                        # Pre-generate the notification message
                        reminder_time_str = reminder.reminder_time.strftime("%I:%M %p")
                        user_context = await ntfy_service.get_recent_user_context(reminder.user_id)
                        
                        title, message = await ntfy_service.generate_ai_notification_message(
                            notification_type="reminder",
                            context={
                                "title": reminder.title,
                                "description": reminder.description or "",
                                "reminder_time": reminder_time_str,
                                "reminder_id": str(reminder.id)
                            },
                            user_context=user_context
                        )
                        
                        self.scheduled_notifications[notification_key] = {
                            "title": title,
                            "message": message,
                            "send_time": reminder.reminder_time,
                            "type": "reminder",
                            "reminder_id": reminder.id,
                            "user_id": reminder.user_id
                        }
                        logger.info(f"📝 Pre-generated reminder notification for: {reminder.title}")
                
                # Send notifications that are due
                due_notifications = []
                for key, notification in list(self.scheduled_notifications.items()):
                    send_time = notification["send_time"]
                    # Ensure send_time is timezone-aware for comparison
                    if send_time.tzinfo is None:
                        send_time = send_time.replace(tzinfo=timezone.utc)
                    
                    if send_time <= now:
                        due_notifications.append((key, notification))
                
                for key, notification in due_notifications:
                    await self._send_scheduled_notification(notification)
                    del self.scheduled_notifications[key]
                    
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error in notification scheduling: {e}")
            
    async def _send_scheduled_notification(self, notification):
        """Send a pre-generated notification"""
        try:
            if notification["type"] == "timer":
                actions = [
                    {
                        "type": "view",
                        "label": "Open Sara",
                        "url": "https://sara.avery.cloud"
                    },
                    {
                        "type": "http", 
                        "label": "Dismiss",
                        "url": f"https://sara.avery.cloud/api/timers/{notification['timer_id']}/complete",
                        "method": "PATCH"
                    }
                ]
                
                await ntfy_service.send_notification(
                    topic=ntfy_service.timers_topic,
                    title=notification["title"],
                    message=notification["message"],
                    priority="high",
                    tags=["timer", "sara", "urgent"],
                    actions=actions
                )
                logger.info(f"⏰ Sent timer notification: {notification['title']}")
                
            elif notification["type"] == "reminder":
                actions = [
                    {
                        "type": "view",
                        "label": "Open Sara", 
                        "url": "https://sara.avery.cloud"
                    },
                    {
                        "type": "http",
                        "label": "Mark Complete",
                        "url": f"https://sara.avery.cloud/api/reminders/{notification['reminder_id']}/complete",
                        "method": "PATCH"
                    }
                ]
                
                await ntfy_service.send_notification(
                    topic=ntfy_service.reminders_topic,
                    title=notification["title"],
                    message=notification["message"],
                    priority="default",
                    tags=["reminder", "sara", "productivity"],
                    actions=actions
                )
                logger.info(f"📅 Sent reminder notification: {notification['title']}")
                
        except Exception as e:
            logger.error(f"Error sending scheduled notification: {e}")

# Initialize notification scheduler
notification_scheduler = NotificationScheduler()

# FastAPI app
app = FastAPI(
    title=f"{ASSISTANT_NAME} Personal Hub API",
    description=f"Personal AI assistant for sara.avery.cloud",
    version="1.0.0-simple"
)

# Initialize Neo4j on startup
@app.on_event("startup")
async def startup_event():
    """Initialize services on application startup"""
    try:
        # Initialize Neo4j service
        from app.services.neo4j_service import neo4j_service
        await neo4j_service.connect()
        logger.info("✅ Neo4j knowledge graph service initialized")
        
        # Initialize intelligence pipeline
        from app.services.intelligence_pipeline import intelligence_pipeline
        await intelligence_pipeline.start_workers()
        logger.info("🧠 Intelligence pipeline workers started")
        
        # Start notification scheduler for pre-generating NTFY messages
        await notification_scheduler.start()
        
        # Initialize nightly dream service
        from app.services.nightly_dream_service import NightlyDreamService
        dream_service = NightlyDreamService()
        # Start the dream scheduler as a background task
        import asyncio
        asyncio.create_task(dream_service.start_dream_scheduler())
        logger.info("🌙 Nightly dream service initialized - will process conversations at 2:00 AM Eastern")
        
    except Exception as e:
        logger.warning(f"⚠️ Services initialization failed (will use fallback): {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on application shutdown"""
    try:
        # Stop notification scheduler
        await notification_scheduler.stop()
        
        from app.services.neo4j_service import neo4j_service
        neo4j_service.close()
        logger.info("🔌 Neo4j connection closed")
    except Exception as e:
        logger.warning(f"Neo4j shutdown warning: {e}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,  # Use specific origins for credentials
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
@app.get("/")
async def root():
    return {"message": f"Welcome to {ASSISTANT_NAME} Personal Hub API", "version": "1.0.0-simple"}

@app.get("/health")
async def health():
    return {"status": "healthy", "assistant": ASSISTANT_NAME}

@app.post("/auth/signup", response_model=UserResponse)
async def signup(user_data: UserCreate, request: Request, response: Response, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = pwd_context.hash(user_data.password)
    user = User(email=user_data.email, password_hash=hashed_password)
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # Auto-login after signup
    access_token = create_access_token(data={"sub": user.id})
    cookie_domain = get_cookie_domain(request)
    cookie_kwargs = {
        "key": "access_token",
        "value": access_token,
        "secure": False,  # Development
        "httponly": True,
        "samesite": "lax",
        "max_age": 24*7*3600
    }
    if cookie_domain:
        cookie_kwargs["domain"] = cookie_domain
    response.set_cookie(**cookie_kwargs)
    
    return UserResponse(
        id=user.id,
        email=user.email,
        created_at=user.created_at.isoformat()
    )

@app.post("/auth/login", response_model=UserResponse)
async def login(user_data: UserLogin, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == user_data.email).first()
    if not user or not pwd_context.verify(user_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    
    access_token = create_access_token(data={"sub": user.id})
    cookie_domain = get_cookie_domain(request)
    cookie_kwargs = {
        "key": "access_token",
        "value": access_token,
        "secure": False,  # Development
        "httponly": True,
        "samesite": "lax",
        "max_age": 24*7*3600
    }
    if cookie_domain:
        cookie_kwargs["domain"] = cookie_domain
    response.set_cookie(**cookie_kwargs)
    
    return UserResponse(
        id=user.id,
        email=user.email,
        created_at=user.created_at.isoformat(),
        access_token=access_token
    )

@app.post("/auth/logout")
async def logout(request: Request, response: Response):
    cookie_domain = get_cookie_domain(request)
    if cookie_domain:
        response.delete_cookie(key="access_token", domain=cookie_domain)
    else:
        response.delete_cookie(key="access_token")
    return {"message": "Successfully logged out"}

@app.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        created_at=current_user.created_at.isoformat()
    )

class PersonalityModeRequest(BaseModel):
    mode: str

@app.post("/user/personality-mode")
async def set_personality_mode(
    request: PersonalityModeRequest,
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    """Update user's current personality mode"""
    valid_modes = ["coach", "analyst", "companion", "guardian", "concierge", "librarian"]
    if request.mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"Invalid personality mode. Valid modes: {valid_modes}")
    
    # Get or create user profile
    user_profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    if not user_profile:
        user_profile = UserProfile(user_id=current_user.id, current_mode=request.mode)
        db.add(user_profile)
    else:
        user_profile.current_mode = request.mode
        user_profile.updated_at = func.now()
    
    db.commit()
    logger.info(f"Updated personality mode for user {current_user.email} to {request.mode}")
    
    return {"message": f"Personality mode updated to {request.mode}", "mode": request.mode}

@app.get("/user/personality-mode")
async def get_personality_mode(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's current personality mode"""
    user_profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    current_mode = user_profile.current_mode if user_profile else 'companion'
    return {"mode": current_mode}

def get_personality_system_prompt(personality_mode: str, assistant_name: str, user_email: str) -> str:
    """Generate personality-aware system prompts based on current mode"""
    
    base_prompt = (
        f"You are {assistant_name}, a helpful personal assistant for {user_email}. "
        f"You have access to tools including web_search and open_page, as well as notes, reminders, timers, calendar, document search, and memory search. "
        f"Use web_search for questions that require external, up-to-date information. "
        f"web_search parameters: recency (any/day/week/month) and sites (array of site: filters). Map queries like 'today/24h'→day, 'this week/recent'→week, 'last month'→month. "
        f"Only call open_page if you intend to quote or need deeper grounding; avoid opening every result. "
        f"When you use web_search, synthesize a concise answer first; the system will attach sources automatically. "
        f"Use search_notes when the user asks about saved information, create_note to save information, "
        f"create_reminder to set time-based reminders, list_reminders to show active reminders, "
        f"complete_reminder to mark reminders as done, start_timer to start productivity timers, "
        f"list_timers to check timer status, stop_timer to cancel timers, "
        f"search_documents to find information in uploaded files, and search_memory to recall past conversations. "
        f"IMPORTANT: Use search_memory when the user asks about previous conversations, mentions something you should remember, "
        f"or when context from past interactions would be helpful. You remember everything we discuss! "
        f"When referencing information from documents, use search_documents and include citations when available. "
        f"You can create beautiful Mermaid diagrams using ```mermaid code blocks for flowcharts, mind maps, timelines, tables, and data visualization. "
        f"Use Mermaid diagrams when presenting complex data, relationships, or processes to make them more visually appealing. "
        f"CRITICAL: After using tools, ALWAYS provide a helpful, conversational response based on the results. "
        f"Never end with just tool calls - always follow up with a natural response that addresses the user's question. "
        f"If tools return information, summarize it helpfully. If no relevant information is found, say so politely. "
        f"For timers, always convert durations to minutes correctly: 2 minutes = 2, 1 hour = 60, 30 seconds = 1 (round up). Be helpful and concise.\n\n"
    )
    
    personality_prompts = {
        "coach": (
            "PERSONALITY MODE: COACH 💪\n"
            "You're energetic, motivating, and goal-focused. Encourage users to push their limits and achieve their objectives. "
            "Use motivational language, celebrate achievements, help users break down goals into actionable steps, and maintain an upbeat, "
            "can-do attitude. Focus on progress, growth mindset, and personal development. Use encouraging emojis when appropriate."
        ),
        "analyst": (
            "PERSONALITY MODE: ANALYST 📊\n"
            "You're methodical, insightful, and data-driven. Approach problems systematically, break down complex topics into clear components, "
            "provide structured analysis, and focus on patterns and trends. Be thorough, logical, and precise in your responses. "
            "Emphasize understanding underlying systems and relationships. Use organized formatting and bullet points when helpful."
        ),
        "companion": (
            "PERSONALITY MODE: COMPANION 💝\n"
            "You're warm, empathetic, and emotionally supportive. Prioritize understanding the user's feelings and providing comfort. "
            "Be gentle, caring, and personally connected. Show genuine interest in their wellbeing, offer emotional support, "
            "and create a safe space for sharing. Use warm, friendly language and be attentive to emotional nuances."
        ),
        "guardian": (
            "PERSONALITY MODE: GUARDIAN 🛡️\n"
            "You're protective, security-conscious, and stability-focused. Prioritize user safety, privacy, and long-term wellbeing. "
            "Be vigilant about potential risks, emphasize security best practices, and help users make thoughtful, safe decisions. "
            "Maintain a calm, steady presence and focus on protecting what's important to them."
        ),
        "concierge": (
            "PERSONALITY MODE: CONCIERGE ⚡\n"
            "You're practical, efficient, and service-oriented. Focus on getting things done quickly and effectively. "
            "Anticipate user needs, provide clear action steps, and optimize for productivity. Be professional, organized, "
            "and solution-focused. Emphasize practical outcomes and time-saving approaches."
        ),
        "librarian": (
            "PERSONALITY MODE: LIBRARIAN 📚\n"
            "You're knowledgeable, thoughtful, and wisdom-focused. Approach topics with depth and context, share relevant background information, "
            "and help users understand the broader picture. Be patient, thorough, and educational. Focus on learning, "
            "knowledge organization, and helping users discover connections between ideas."
        )
    }
    
    personality_addition = personality_prompts.get(personality_mode, personality_prompts["companion"])
    return base_prompt + personality_addition


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    logger.info(f"Chat request from user {current_user.email} with {len(request.messages)} messages")
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided")
    
    # Get user's current personality mode
    user_profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    personality_mode = user_profile.current_mode if user_profile else 'companion'
    logger.info(f"Using personality mode: {personality_mode}")
    
    # Tool definitions
    tools = [
        {
            "type": "function",
            "function": {
                "name": "search_notes",
                "description": "Search through the user's notes for relevant information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query to find relevant notes"
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_note",
                "description": "Create a new note with the given content",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Title for the note (optional)"
                        },
                        "content": {
                            "type": "string", 
                            "description": "Content of the note"
                        }
                    },
                    "required": ["content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_notes",
                "description": "List all user's notes with their titles and IDs",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "delete_note",
                "description": "Delete a specific note by its ID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "note_id": {
                            "type": "string",
                            "description": "The ID of the note to delete"
                        }
                    },
                    "required": ["note_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_reminder",
                "description": "Create a reminder for the user at a specific time",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Title/summary of the reminder"
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional detailed description of the reminder"
                        },
                        "reminder_time": {
                            "type": "string",
                            "description": "ISO format datetime when to remind (e.g., '2024-08-16T15:30:00Z')"
                        }
                    },
                    "required": ["title", "reminder_time"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_reminders",
                "description": "List all active (non-completed) reminders for the user",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "complete_reminder",
                "description": "Mark a reminder as completed using its ID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reminder_id": {
                            "type": "string",
                            "description": "The ID of the reminder to mark as completed"
                        }
                    },
                    "required": ["reminder_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "start_timer",
                "description": "Start a timer for a specific duration. Always convert time to minutes: 2 minutes = 2, 1 hour = 60, 30 seconds = 1 (round up)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Title/description of what the timer is for"
                        },
                        "duration_minutes": {
                            "type": "integer",
                            "description": "Duration of the timer in minutes only. Examples: 2 minutes = 2, 1 hour = 60, 30 seconds = 1. Always use positive integers between 1 and 480 (8 hours max)."
                        }
                    },
                    "required": ["title", "duration_minutes"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_timers",
                "description": "List all active timers and their remaining time",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "stop_timer",
                "description": "Stop/cancel an active timer using its ID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "timer_id": {
                            "type": "string",
                            "description": "The ID of the timer to stop"
                        }
                    },
                    "required": ["timer_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_documents",
                "description": "Search through uploaded documents for relevant information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query to find relevant content in documents"
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_memory",
                "description": "Search through Sara's conversation memory for past interactions, preferences, and context",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query to find relevant memories from past conversations"
                        }
                    },
                    "required": ["query"]
                }
            }
        }
    ]
    
    # Add personality-aware system message
    system_message = ChatMessage(
        role="system",
        content=get_personality_system_prompt(personality_mode, ASSISTANT_NAME, current_user.email)
    )
    
    all_messages = [system_message] + request.messages
    logger.info(f"Calling LLM with {len(all_messages)} messages and {len(tools)} tools")
    response_content = await llm_client.chat_with_tools(all_messages, tools, current_user.id)
    
    # Enhanced debugging for empty response issue
    if response_content:
        logger.info(f"✅ LLM response received: length={len(response_content)}, preview='{response_content[:100]}...'")
    else:
        logger.error(f"❌ LLM response is empty or None: {response_content}")
    
    # Additional debugging
    logger.info(f"🔍 Response type: {type(response_content)}")
    logger.info(f"🔍 Response repr: {repr(response_content)[:200]}")
    
    chat_response = ChatResponse(
        message=ChatMessage(role="assistant", content=response_content)
    )
    
    logger.info(f"🔍 ChatResponse created: message.content length={len(chat_response.message.content) if chat_response.message.content else 0}")
    
    # Store conversation in episodic memory
    try:
        logger.info(f"🧠 Storing conversation in Sara's memory...")
        await llm_client.store_conversation(request.messages, response_content, current_user.id, request.conversation_id)
        logger.info(f"✅ Conversation stored in memory successfully")
    except Exception as e:
        logger.error(f"❌ Failed to store conversation in memory: {e}")
        # Don't fail the request if memory storage fails
    
    return chat_response

@app.options("/chat/stream")
async def chat_stream_options():
    """Handle CORS preflight for streaming chat"""
    return JSONResponse(
        content={"message": "OK"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        }
    )

@app.post("/chat/stream")
async def chat_stream(request: ChatRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Streaming chat endpoint with real-time tool usage indicators"""
    logger.info(f"Streaming chat request from user {current_user.email} with {len(request.messages)} messages")
    
    # Get user's current personality mode
    user_profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    personality_mode = user_profile.current_mode if user_profile else 'companion'
    logger.info(f"Streaming chat using personality mode: {personality_mode}")

    async def generate_events():
        try:
            # Create an async queue for events
            event_queue = asyncio.Queue()
            
            # Set up streaming LLM client
            streaming_client = SimpleLLMClient()
            streaming_client.set_event_queue(event_queue)
            
            # Use global tool registry to expose all tools (includes web_search and open_page)
            tools = tool_registry.get_openai_schemas()
            
            # Create personality-aware system message
            system_message = ChatMessage(
                role="system",
                content=get_personality_system_prompt(personality_mode, ASSISTANT_NAME, current_user.email)
            )
            
            all_messages = [system_message] + request.messages
            
            # Start the LLM processing in a background task
            async def process_chat():
                response_content = await streaming_client.chat_with_tools(all_messages, tools, current_user.id, request.conversation_id)
                await event_queue.put({
                    "type": "final_response",
                    "data": {
                        "content": response_content,
                        "citations": streaming_client.get_citations(),
                        "timestamp": datetime.utcnow().isoformat(),
                        "conversation_id": streaming_client.current_conversation_id if hasattr(streaming_client, 'current_conversation_id') else request.conversation_id
                    }
                })
                await event_queue.put({"type": "done"})
            
            # Start processing
            task = asyncio.create_task(process_chat())
            
            # Stream events as they come in
            while True:
                try:
                    # Wait for next event with timeout
                    event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                    
                    if event.get("type") == "done":
                        break
                        
                    # Format as Server-Sent Event
                    event_data = json.dumps(event)
                    yield f"data: {event_data}\n\n"
                    
                except asyncio.TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.utcnow().isoformat()})}\n\n"
                except Exception as e:
                    logger.error(f"Error in event stream: {e}")
                    yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                    break
            
            # Ensure task is cleaned up
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                    
        except Exception as e:
            logger.error(f"Error in chat stream: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(
        generate_events(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control"
        }
    )

@app.get("/notes", response_model=list[NoteResponse])
async def list_notes(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    notes = db.query(Note).filter(Note.user_id == current_user.id).order_by(Note.updated_at.desc()).limit(20).all()
    return [
        NoteResponse(
            id=note.id,
            title=note.title,
            content=note.content,
            folder_id=note.folder_id,
            created_at=note.created_at.isoformat(),
            updated_at=note.updated_at.isoformat()
        )
        for note in notes
    ]

@app.post("/notes", response_model=NoteResponse)
async def create_note(note_data: NoteCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Neo4j-first approach: Create note in Neo4j immediately
    note_id = str(uuid.uuid4())
    
    try:
        # 1. Create note in Neo4j first with basic properties
        from app.services.neo4j_service import neo4j_service
        from app.services.intelligence_pipeline import intelligence_pipeline, ContentType
        
        # Ensure Neo4j connection
        if not neo4j_service.driver:
            await neo4j_service.connect()
        
        # Create note in Neo4j graph
        neo4j_result = await neo4j_service.create_note(
            note_id=note_id,
            user_id=current_user.id,
            title=note_data.title or "Untitled",
            content=note_data.content,
            folder_id=note_data.folder_id
        )
        
        # 2. Start intelligence pipeline workers if not already running
        await intelligence_pipeline.start_workers()
        
        # 3. Queue for fast processing (embeddings, obvious connections)
        await intelligence_pipeline.queue_fast_processing(
            content_id=note_id,
            content_type=ContentType.NOTE,
            metadata={
                "user_id": current_user.id,
                "title": note_data.title,
                "folder_id": note_data.folder_id
            }
        )
        
        logger.info(f"✅ Note {note_id} created in Neo4j and queued for intelligent processing")
        
    except Exception as neo_error:
        logger.error(f"❌ Neo4j note creation failed: {neo_error}")
        # Continue with PostgreSQL fallback
    
    # 4. Background sync to PostgreSQL (backup)
    note = Note(
        id=note_id,
        user_id=current_user.id,
        title=note_data.title,
        content=note_data.content,
        folder_id=note_data.folder_id
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    
    return NoteResponse(
        id=note.id,
        title=note.title,
        content=note.content,
        folder_id=note.folder_id,
        created_at=note.created_at.isoformat(),
        updated_at=note.updated_at.isoformat()
    )

@app.put("/notes/{note_id}", response_model=NoteResponse)
async def update_note(note_id: str, note_data: NoteCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == current_user.id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    
    # Neo4j-first approach: Update note in Neo4j and re-process
    try:
        from app.services.neo4j_service import neo4j_service
        from app.services.intelligence_pipeline import intelligence_pipeline, ContentType
        
        # Ensure Neo4j connection
        if not neo4j_service.driver:
            await neo4j_service.connect()
        
        # Update note in Neo4j graph
        await neo4j_service.create_note(
            note_id=note_id,
            user_id=current_user.id,
            title=note_data.title or "Untitled",
            content=note_data.content,
            folder_id=note_data.folder_id
        )
        
        # Re-process with intelligence pipeline for updated content
        await intelligence_pipeline.queue_fast_processing(
            content_id=note_id,
            content_type=ContentType.NOTE,
            metadata={
                "user_id": current_user.id,
                "title": note_data.title,
                "folder_id": note_data.folder_id,
                "is_update": True
            }
        )
        
        logger.info(f"✅ Note {note_id} updated in Neo4j and re-queued for processing")
        
    except Exception as neo_error:
        logger.error(f"❌ Neo4j note update failed: {neo_error}")
    
    # Update PostgreSQL (backup)
    note.title = note_data.title
    note.content = note_data.content
    if note_data.folder_id is not None:
        note.folder_id = note_data.folder_id
    note.updated_at = datetime.now()
    db.commit()
    db.refresh(note)
    
    return NoteResponse(
        id=note.id,
        title=note.title,
        content=note.content,
        folder_id=note.folder_id,
        created_at=note.created_at.isoformat(),
        updated_at=note.updated_at.isoformat()
    )

@app.delete("/notes/{note_id}")
async def delete_note(note_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == current_user.id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    
    # Delete from Neo4j first
    try:
        from app.services.neo4j_service import neo4j_service
        await neo4j_service.delete_note(note_id, current_user.id)
        logger.info(f"✅ Note {note_id} deleted from Neo4j")
    except Exception as e:
        logger.warning(f"Failed to delete note from Neo4j: {e}")
    
    # Also delete associated connections
    db.query(NoteConnection).filter(
        (NoteConnection.source_note_id == note_id) | (NoteConnection.target_note_id == note_id),
        NoteConnection.user_id == current_user.id
    ).delete()
    
    db.delete(note)
    db.commit()
    
    return {"message": "Note deleted successfully"}

# Note Connection endpoints
@app.get("/notes/{note_id}/connections", response_model=list[NoteConnectionResponse])
async def get_note_connections(note_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all connections for a specific note (both outgoing and incoming)"""
    # Verify note exists and belongs to user
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == current_user.id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    
    connections = db.query(NoteConnection).filter(
        (NoteConnection.source_note_id == note_id) | (NoteConnection.target_note_id == note_id),
        NoteConnection.user_id == current_user.id
    ).all()
    
    return [
        NoteConnectionResponse(
            id=conn.id,
            source_note_id=conn.source_note_id,
            target_note_id=conn.target_note_id,
            connection_type=conn.connection_type,
            strength=conn.strength,
            auto_generated=conn.auto_generated == "true",
            created_at=conn.created_at.isoformat(),
            updated_at=conn.updated_at.isoformat()
        )
        for conn in connections
    ]

@app.post("/notes/{note_id}/connections", response_model=NoteConnectionResponse)
async def create_note_connection(
    note_id: str, 
    connection_data: NoteConnectionCreate, 
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    """Create a connection from one note to another"""
    # Verify both notes exist and belong to user
    source_note = db.query(Note).filter(Note.id == note_id, Note.user_id == current_user.id).first()
    if not source_note:
        raise HTTPException(status_code=404, detail="Source note not found")
    
    target_note = db.query(Note).filter(Note.id == connection_data.target_note_id, Note.user_id == current_user.id).first()
    if not target_note:
        raise HTTPException(status_code=404, detail="Target note not found")
    
    # Check if connection already exists
    existing = db.query(NoteConnection).filter(
        NoteConnection.source_note_id == note_id,
        NoteConnection.target_note_id == connection_data.target_note_id,
        NoteConnection.user_id == current_user.id
    ).first()
    
    if existing:
        raise HTTPException(status_code=409, detail="Connection already exists")
    
    connection = NoteConnection(
        user_id=current_user.id,
        source_note_id=note_id,
        target_note_id=connection_data.target_note_id,
        connection_type=connection_data.connection_type,
        strength=connection_data.strength,
        auto_generated="true" if connection_data.auto_generated else "false"
    )
    
    db.add(connection)
    db.commit()
    db.refresh(connection)
    
    return NoteConnectionResponse(
        id=connection.id,
        source_note_id=connection.source_note_id,
        target_note_id=connection.target_note_id,
        connection_type=connection.connection_type,
        strength=connection.strength,
        auto_generated=connection.auto_generated == "true",
        created_at=connection.created_at.isoformat(),
        updated_at=connection.updated_at.isoformat()
    )

@app.delete("/notes/{note_id}/connections/{connection_id}")
async def delete_note_connection(
    note_id: str, 
    connection_id: str, 
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    """Delete a specific note connection"""
    connection = db.query(NoteConnection).filter(
        NoteConnection.id == connection_id,
        (NoteConnection.source_note_id == note_id) | (NoteConnection.target_note_id == note_id),
        NoteConnection.user_id == current_user.id
    ).first()
    
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    db.delete(connection)
    db.commit()
    
    return {"message": "Connection deleted successfully"}

@app.get("/notes/graph-data")
async def get_notes_graph_data(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all notes and connections for graph visualization"""
    notes = db.query(Note).filter(Note.user_id == current_user.id).all()
    connections = db.query(NoteConnection).filter(NoteConnection.user_id == current_user.id).all()
    
    return {
        "nodes": [
            {
                "id": note.id,
                "title": note.title,
                "content": note.content[:200] + "..." if len(note.content) > 200 else note.content,
                "type": "note",
                "created_at": note.created_at.isoformat(),
                "updated_at": note.updated_at.isoformat()
            }
            for note in notes
        ],
        "links": [
            {
                "id": conn.id,
                "source": conn.source_note_id,
                "target": conn.target_note_id,
                "type": conn.connection_type,
                "strength": conn.strength / 100.0,  # Normalize to 0-1
                "auto_generated": conn.auto_generated == "true"
            }
            for conn in connections
        ]
    }

# Memory Management endpoints
@app.get("/memory/episodes")
async def get_episodes(
    page: int = 1,
    per_page: int = 20,
    min_importance: float = None,
    max_importance: float = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get episodes with pagination and filtering"""
    try:
        # Build base query
        query = db.query(Episode).filter(Episode.user_id == current_user.id)
        
        # Apply importance filters
        if min_importance is not None:
            query = query.filter(Episode.importance >= min_importance)
        if max_importance is not None:
            query = query.filter(Episode.importance <= max_importance)
        
        # Get total count
        total = query.count()
        
        # Apply pagination and ordering
        episodes = query.order_by(Episode.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
        
        # Format episodes for frontend
        episode_data = []
        for episode in episodes:
            episode_data.append({
                "id": episode.id,
                "source": episode.source or "chat",
                "role": episode.role,
                "content": episode.content,
                "importance": episode.importance,
                "meta": {
                    "memory_type": episode.memory_type,
                    "topics": episode.topics,
                    "emotional_tone": episode.emotional_tone,
                    "context_tags": episode.context_tags,
                    "access_count": episode.access_count
                },
                "created_at": episode.created_at.isoformat()
            })
        
        return {
            "episodes": episode_data,
            "total": total,
            "page": page,
            "per_page": per_page
        }
    except Exception as e:
        logger.error(f"Error retrieving episodes: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve episodes")

@app.delete("/memory/episodes/{episode_id}")
async def delete_episode(
    episode_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a specific episode"""
    try:
        # Find the episode
        episode = db.query(Episode).filter(
            Episode.id == episode_id,
            Episode.user_id == current_user.id
        ).first()
        
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")
        
        # Delete the episode
        db.delete(episode)
        db.commit()
        
        logger.info(f"Deleted episode {episode_id} for user {current_user.id}")
        return {"message": "Episode deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting episode {episode_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete episode")

@app.patch("/memory/episodes/{episode_id}")
async def update_episode(
    episode_id: str,
    importance: float,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update episode importance"""
    try:
        # Validate importance value
        if not (0.0 <= importance <= 1.0):
            raise HTTPException(status_code=400, detail="Importance must be between 0.0 and 1.0")
        
        # Find the episode
        episode = db.query(Episode).filter(
            Episode.id == episode_id,
            Episode.user_id == current_user.id
        ).first()
        
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")
        
        # Update the importance
        episode.importance = importance
        episode.updated_at = func.now()
        db.commit()
        
        logger.info(f"Updated episode {episode_id} importance to {importance} for user {current_user.id}")
        return {"message": "Episode importance updated successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating episode {episode_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update episode importance")

@app.post("/memory/search")
async def search_episodes(
    search_request: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Search episodes with POST request body"""
    try:
        query = search_request.get("query", "")
        scopes = search_request.get("scopes", ["episodes"])
        limit = search_request.get("limit", 50)
        
        if not query.strip():
            return {"results": []}
        
        # Search episodes by content using LIKE for now (could be enhanced with vector search)
        episodes = db.query(Episode).filter(
            Episode.user_id == current_user.id,
            Episode.content.ilike(f"%{query}%")
        ).order_by(Episode.created_at.desc()).limit(limit).all()
        
        # Format results for frontend
        results = []
        for episode in episodes:
            results.append({
                "text": episode.content,
                "metadata": {
                    "episode_id": episode.id,
                    "id": episode.id,
                    "importance": episode.importance,
                    "role": episode.role,
                    "source": episode.source or "chat",
                    "timestamp": episode.created_at.isoformat(),
                    "memory_type": episode.memory_type,
                    "topics": episode.topics,
                    "emotional_tone": episode.emotional_tone,
                    "context_tags": episode.context_tags
                }
            })
        
        return {"results": results}
        
    except Exception as e:
        logger.error(f"Error searching episodes: {e}")
        raise HTTPException(status_code=500, detail="Failed to search episodes")

# Folder endpoints
@app.post("/folders", response_model=FolderResponse)
async def create_folder(folder_data: FolderCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create a new folder"""
    # Validate parent folder exists and belongs to user if provided
    if folder_data.parent_id:
        parent = db.query(Folder).filter(Folder.id == folder_data.parent_id, Folder.user_id == current_user.id).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent folder not found")
    
    folder = Folder(
        name=folder_data.name,
        parent_id=folder_data.parent_id,
        user_id=current_user.id
    )
    
    db.add(folder)
    db.commit()
    db.refresh(folder)
    
    # Count notes and subfolders
    notes_count = db.query(Note).filter(Note.folder_id == folder.id).count()
    subfolders_count = db.query(Folder).filter(Folder.parent_id == folder.id).count()
    
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        notes_count=notes_count,
        subfolders_count=subfolders_count,
        created_at=folder.created_at.isoformat(),
        updated_at=folder.updated_at.isoformat()
    )

@app.get("/folders/tree")
async def get_folder_tree(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get the complete folder and note tree structure"""
    # Get all folders for the user
    folders = db.query(Folder).filter(Folder.user_id == current_user.id).all()
    
    # Get all notes for the user
    notes = db.query(Note).filter(Note.user_id == current_user.id).all()
    
    # Build tree structure recursively
    def build_tree(parent_id=None):
        nodes = []
        
        # Add folders
        for folder in folders:
            if folder.parent_id == parent_id:
                node = TreeNodeResponse(
                    id=folder.id,
                    name=folder.name,
                    type="folder",
                    parent_id=folder.parent_id,
                    created_at=folder.created_at.isoformat(),
                    updated_at=folder.updated_at.isoformat(),
                    children=build_tree(folder.id)
                )
                nodes.append(node)
        
        # Add notes
        for note in notes:
            if note.folder_id == parent_id:
                node = TreeNodeResponse(
                    id=note.id,
                    name=note.title or "Untitled",
                    type="note",
                    parent_id=note.folder_id,
                    created_at=note.created_at.isoformat(),
                    updated_at=note.updated_at.isoformat(),
                    children=[]
                )
                nodes.append(node)
        
        return nodes
    
    tree = build_tree()
    return {"tree": tree}

@app.put("/folders/{folder_id}", response_model=FolderResponse)
async def update_folder(folder_id: str, folder_data: FolderUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Update a folder"""
    folder = db.query(Folder).filter(Folder.id == folder_id, Folder.user_id == current_user.id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    
    # Update fields
    if folder_data.name is not None:
        folder.name = folder_data.name
    
    if folder_data.parent_id is not None:
        # Validate new parent exists and belongs to user if provided
        if folder_data.parent_id:
            parent = db.query(Folder).filter(Folder.id == folder_data.parent_id, Folder.user_id == current_user.id).first()
            if not parent:
                raise HTTPException(status_code=404, detail="Parent folder not found")
        
        folder.parent_id = folder_data.parent_id
    
    db.commit()
    db.refresh(folder)
    
    # Count notes and subfolders
    notes_count = db.query(Note).filter(Note.folder_id == folder.id).count()
    subfolders_count = db.query(Folder).filter(Folder.parent_id == folder.id).count()
    
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        notes_count=notes_count,
        subfolders_count=subfolders_count,
        created_at=folder.created_at.isoformat(),
        updated_at=folder.updated_at.isoformat()
    )

@app.delete("/folders/{folder_id}")
async def delete_folder(folder_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete a folder and all its contents"""
    folder = db.query(Folder).filter(Folder.id == folder_id, Folder.user_id == current_user.id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    
    db.delete(folder)
    db.commit()
    
    return {"message": "Folder deleted successfully"}

@app.get("/reminders", response_model=list[ReminderResponse])
async def list_reminders(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reminders = db.query(Reminder).filter(
        Reminder.user_id == current_user.id,
        Reminder.is_completed == False
    ).order_by(Reminder.reminder_time).limit(20).all()
    
    return [
        ReminderResponse(
            id=reminder.id,
            title=reminder.title,
            description=reminder.description,
            reminder_time=reminder.reminder_time.isoformat(),
            is_completed=reminder.is_completed == "true",
            created_at=reminder.created_at.isoformat(),
            updated_at=reminder.updated_at.isoformat()
        )
        for reminder in reminders
    ]

@app.post("/reminders", response_model=ReminderResponse)
async def create_reminder(reminder_data: ReminderCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reminder_dt = datetime.fromisoformat(reminder_data.reminder_time.replace('Z', '+00:00'))
    
    reminder = Reminder(
        user_id=current_user.id,
        title=reminder_data.title,
        description=reminder_data.description,
        reminder_time=reminder_dt
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    
    return ReminderResponse(
        id=reminder.id,
        title=reminder.title,
        description=reminder.description,
        reminder_time=reminder.reminder_time.isoformat(),
        is_completed=reminder.is_completed == "true",
        created_at=reminder.created_at.isoformat(),
        updated_at=reminder.updated_at.isoformat()
    )

@app.patch("/reminders/{reminder_id}/complete")
async def complete_reminder(reminder_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reminder = db.query(Reminder).filter(
        Reminder.id == reminder_id,
        Reminder.user_id == current_user.id
    ).first()
    
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    
    reminder.is_completed = "true"
    reminder.updated_at = datetime.now()
    db.commit()
    
    # Remove any scheduled notification since reminder was manually completed
    notification_key = f"reminder_{reminder_id}"
    if notification_key in notification_scheduler.scheduled_notifications:
        del notification_scheduler.scheduled_notifications[notification_key]
    
    return {"message": f"Marked reminder '{reminder.title}' as completed"}

@app.post("/reminders/{reminder_id}/notify")
async def send_reminder_notification(reminder_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Send NTFY notification for a due reminder"""
    reminder = db.query(Reminder).filter(
        Reminder.id == reminder_id,
        Reminder.user_id == current_user.id
    ).first()
    
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    
    # Send AI-generated NTFY notification
    reminder_time = reminder.reminder_time.strftime("%I:%M %p")
    success = await ntfy_service.send_reminder_notification(
        reminder.title, 
        reminder_time, 
        reminder_id, 
        reminder.description, 
        current_user.id
    )
    
    if success:
        return {"message": f"Notification sent for reminder '{reminder.title}'"}
    else:
        return {"message": f"Failed to send notification for reminder '{reminder.title}'"}

@app.get("/timers", response_model=list[TimerResponse])
async def list_timers(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    timers = db.query(Timer).filter(
        Timer.user_id == current_user.id,
        Timer.is_active == True
    ).order_by(Timer.created_at.desc()).limit(20).all()
    
    results = [
        TimerResponse(
            id=timer.id,
            title=timer.title,
            duration_minutes=timer.duration_minutes,
            start_time=timer.start_time.replace(tzinfo=timezone.utc).isoformat(),
            end_time=timer.end_time.replace(tzinfo=timezone.utc).isoformat(),
            is_active=timer.is_active,
            is_completed=timer.is_completed == "true",
            created_at=timer.created_at.replace(tzinfo=timezone.utc).isoformat()
        )
        for timer in timers
    ]
    
    # Debug logging
    for timer_response in results:
        logger.info(f"API returning timer: {timer_response.title} - Start: {timer_response.start_time}, End: {timer_response.end_time}, Duration: {timer_response.duration_minutes}m")
    
    return results

@app.post("/timers", response_model=TimerResponse)
async def start_timer(timer_data: TimerCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start_time = datetime.now(timezone.utc)
    end_time = start_time + timedelta(minutes=timer_data.duration_minutes)
    
    timer = Timer(
        user_id=current_user.id,
        title=timer_data.title,
        duration_minutes=timer_data.duration_minutes,
        start_time=start_time,
        end_time=end_time
    )
    db.add(timer)
    db.commit()
    db.refresh(timer)
    
    return TimerResponse(
        id=timer.id,
        title=timer.title,
        duration_minutes=timer.duration_minutes,
        start_time=timer.start_time.replace(tzinfo=timezone.utc).isoformat(),
        end_time=timer.end_time.replace(tzinfo=timezone.utc).isoformat(),
        is_active=timer.is_active,
        is_completed=timer.is_completed == "true",
        created_at=timer.created_at.replace(tzinfo=timezone.utc).isoformat()
    )

@app.patch("/timers/{timer_id}/stop")
async def stop_timer(timer_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    timer = db.query(Timer).filter(
        Timer.id == timer_id,
        Timer.user_id == current_user.id,
        Timer.is_active == True
    ).first()
    
    if not timer:
        raise HTTPException(status_code=404, detail="Active timer not found")
    
    timer.is_active = False
    timer.is_completed = True
    db.commit()
    
    # Only send notification for manually stopped timers (not automatic completions)
    # The scheduler handles automatic notifications when timers reach their end time
    now = datetime.now(timezone.utc)
    timer_end_time = timer.end_time
    if timer_end_time.tzinfo is None:
        timer_end_time = timer_end_time.replace(tzinfo=timezone.utc)
    
    if timer_end_time > now:
        # Timer was stopped early, send immediate notification
        duration_str = f"{timer.duration_minutes}min"
        await ntfy_service.send_timer_notification(timer.title, duration_str, timer_id, current_user.id)
    else:
        # Timer completed naturally, remove any pre-generated notification to avoid duplicates
        notification_key = f"timer_{timer_id}"
        if notification_key in notification_scheduler.scheduled_notifications:
            del notification_scheduler.scheduled_notifications[notification_key]
    
    return {"message": f"Stopped timer '{timer.title}'"}

# Document API endpoints
@app.post("/documents", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile,
    chat_context: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload a document with Neo4j-first intelligent processing"""
    doc_id = str(uuid.uuid4())
    
    try:
        # Create uploads directory if it doesn't exist
        uploads_dir = "uploads"
        os.makedirs(uploads_dir, exist_ok=True)
        
        # Generate unique filename while preserving extension
        file_extension = os.path.splitext(file.filename)[1] if file.filename else ""
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        file_path = os.path.join(uploads_dir, unique_filename)
        
        # Save file to disk
        file_content = await file.read()
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(file_content)
        
        # Extract text immediately
        processor = DocumentProcessor()
        extracted_text = ""
        
        if file.content_type == "application/pdf":
            try:
                extracted_text = processor.extract_text(file_path, file.content_type)
                if not extracted_text or len(extracted_text.strip()) < 10:
                    extracted_text = f"PDF document: {file.filename} (text extraction may have limited success)"
            except Exception as e:
                logger.warning(f"PDF extraction failed: {e}")
                extracted_text = f"PDF document: {file.filename} (text extraction failed)"
        elif file.content_type in ["text/plain", "text/markdown"]:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    extracted_text = f.read()
            except Exception as e:
                logger.warning(f"Text file extraction failed: {e}")
                extracted_text = "Could not extract text from file"
        elif "word" in (file.content_type or "") or file.content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            try:
                extracted_text = processor.extract_text(file_path, file.content_type)
                if not extracted_text:
                    extracted_text = f"Word document: {file.filename}"
            except Exception as e:
                logger.warning(f"Word document extraction failed: {e}")
                extracted_text = f"Word document: {file.filename}"
        else:
            extracted_text = f"Document: {file.filename}"
        
        # Neo4j-first approach: Create document in Neo4j immediately
        try:
            from app.services.neo4j_service import neo4j_service
            from app.services.intelligence_pipeline import intelligence_pipeline, ContentType
            
            # Ensure Neo4j connection
            if not neo4j_service.driver:
                await neo4j_service.connect()
            
            # Create document in Neo4j graph with extracted content
            neo4j_result = await neo4j_service.create_document(
                doc_id=doc_id,
                user_id=current_user.id,
                title=file.filename or "Untitled Document",
                content_text=extracted_text,
                mime_type=file.content_type or "application/octet-stream",
                file_path=file_path
            )
            
            # Start intelligence pipeline workers if not already running
            await intelligence_pipeline.start_workers()
            
            # Queue for fast processing (embeddings, obvious connections)
            await intelligence_pipeline.queue_fast_processing(
                content_id=doc_id,
                content_type=ContentType.DOCUMENT,
                metadata={
                    "user_id": current_user.id,
                    "title": file.filename,
                    "mime_type": file.content_type,
                    "file_path": file_path,
                    "file_size": len(file_content)
                }
            )
            
            logger.info(f"✅ Document {doc_id} created in Neo4j and queued for intelligent processing")
            
        except Exception as neo_error:
            logger.error(f"❌ Neo4j document creation failed: {neo_error}")
            # Continue with PostgreSQL fallback
        
        # Background sync to PostgreSQL (backup)
        document = Document(
            id=doc_id,
            user_id=current_user.id,
            filename=unique_filename,
            original_filename=file.filename or "unknown",
            title=file.filename or "Untitled Document",  # Add title for backward compatibility
            file_path=file_path,
            file_size=len(file_content),
            mime_type=file.content_type or "application/octet-stream",
            content_text=extracted_text[:50000] if extracted_text else "",  # Store 50KB preview
            is_processed="true"  # Mark as processed since we extracted text
        )
        
        db.add(document)
        db.commit()
        db.refresh(document)
        
        # Legacy chunking for PostgreSQL compatibility (reduced priority)
        try:
            chunks = processor.chunk_text(extracted_text) if extracted_text else []
            max_chunks = 100  # Reduced since Neo4j is primary
            processed_chunks = chunks[:max_chunks]
            
            if processed_chunks:
                # Generate embeddings for chunks
                chunk_embeddings = await embedding_service.generate_embeddings_batch(processed_chunks)
                
                # Save chunks to PostgreSQL
                for i, (chunk_text, embedding) in enumerate(zip(processed_chunks, chunk_embeddings)):
                    if DATABASE_URL.startswith("postgresql") and PGVECTOR_AVAILABLE:
                        embedding_data = embedding
                    else:
                        embedding_data = json.dumps(embedding) if embedding else None
                    
                    chunk = DocumentChunk(
                        document_id=document.id,
                        user_id=current_user.id,
                        chunk_index=i,
                        chunk_text=chunk_text,
                        embedding=embedding_data
                    )
                    db.add(chunk)
                
                db.commit()
                logger.info(f"📄 Legacy chunking completed: {len(processed_chunks)} chunks")
        
        except Exception as chunk_error:
            logger.warning(f"⚠️ Legacy chunking failed (Neo4j processing continues): {chunk_error}")
        
        return DocumentResponse(
            id=document.id,
            filename=document.filename,
            original_filename=document.original_filename,
            title=document.title or document.original_filename,
            file_size=document.file_size,
            mime_type=document.mime_type,
            content_text=document.content_text,
            is_processed=document.is_processed,
            created_at=document.created_at.isoformat(),
            updated_at=document.updated_at.isoformat()
        )
        
    except Exception as e:
        logger.error(f"Document upload error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload document: {str(e)}")


@app.get("/documents", response_model=list[DocumentResponse])
async def get_documents(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all documents for the current user"""
    documents = db.query(Document).filter(Document.user_id == current_user.id).order_by(Document.created_at.desc()).all()
    
    return [
        DocumentResponse(
            id=doc.id,
            filename=doc.filename,
            original_filename=doc.original_filename,
            title=getattr(doc, 'title', '') or doc.original_filename,  # Fallback for existing docs
            file_size=doc.file_size,
            mime_type=doc.mime_type,
            content_text=doc.content_text,
            is_processed=doc.is_processed,
            created_at=doc.created_at.isoformat(),
            updated_at=doc.updated_at.isoformat()
        )
        for doc in documents
    ]

@app.get("/documents/{document_id}/file")
async def download_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Download the original document file"""
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.user_id == current_user.id
    ).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if not os.path.exists(document.file_path):
        raise HTTPException(status_code=404, detail="Document file not found on disk")
    
    async with aiofiles.open(document.file_path, 'rb') as f:
        file_content = await f.read()
    
    return Response(
        content=file_content,
        media_type=document.mime_type,
        headers={
            "Content-Disposition": f"attachment; filename=\"{document.original_filename}\""
        }
    )

@app.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a document and its chunks"""
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.user_id == current_user.id
    ).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Delete chunks first
    db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()
    
    # Skip vector deletion for now to avoid crashes
    logger.info(f"Skipped vector deletion for document {document_id} (disabled for stability)")
    
    # Delete file from disk
    try:
        if os.path.exists(document.file_path):
            os.remove(document.file_path)
    except Exception as e:
        logger.warning(f"Could not delete file {document.file_path}: {e}")
    
    # Delete from Neo4j first
    try:
        from app.services.neo4j_service import neo4j_service
        await neo4j_service.delete_document(document_id, current_user.id)
        logger.info(f"✅ Document {document_id} deleted from Neo4j")
    except Exception as e:
        logger.warning(f"Failed to delete document from Neo4j: {e}")
    
    # Delete document record
    db.delete(document)
    db.commit()
    
    return {"message": "Document deleted successfully"}

@app.put("/documents/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: str,
    title: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update document title"""
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.user_id == current_user.id
    ).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Update document title
    document.title = title
    db.commit()
    db.refresh(document)
    
    # Update Neo4j if available
    try:
        from app.services.neo4j_service import neo4j_service
        if neo4j_service.driver:
            await neo4j_service.update_document_title(document_id, title)
    except Exception as e:
        logger.warning(f"Failed to update document title in Neo4j: {e}")
    
    return DocumentResponse(
        id=document.id,
        filename=document.filename,
        original_filename=document.original_filename,
        title=document.title,
        mime_type=document.mime_type,
        file_size=document.file_size,
        is_processed=document.is_processed,
        content_text=document.content_text,
        created_at=document.created_at.isoformat(),
        updated_at=document.updated_at.isoformat()
    )

@app.get("/documents/search")
async def search_documents(
    query: str,
    limit: int = 5,
    current_user: User = Depends(get_current_user)
):
    """Search for relevant document chunks using vector similarity"""
    if not query.strip():
        return {"results": []}
    
    try:
        search_results = document_processor.search_documents(query, current_user.id, limit)
        
        return {
            "query": query,
            "results": search_results
        }
        
    except Exception as e:
        logger.error(f"Document search error: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

# Conversation memory API endpoints
@app.get("/conversations", response_model=list[ConversationResponse])
async def get_conversations(
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get recent conversations for the current user"""
    conversations = db.query(Conversation).filter(
        Conversation.user_id == current_user.id
    ).order_by(Conversation.updated_at.desc()).limit(limit).all()
    
    return [
        ConversationResponse(
            id=conv.id,
            title=conv.title or "Conversation",
            summary=conv.summary or "",
            total_messages=conv.total_messages,
            created_at=conv.created_at.isoformat(),
            updated_at=conv.updated_at.isoformat()
        )
        for conv in conversations
    ]

@app.get("/conversations/{conversation_id}/turns", response_model=list[ConversationTurnResponse])
async def get_conversation_turns(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all turns/messages for a specific conversation"""
    # Verify the conversation belongs to the user
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == current_user.id
    ).first()
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    turns = db.query(ConversationTurn).filter(
        ConversationTurn.conversation_id == conversation_id
    ).order_by(ConversationTurn.message_index).all()
    
    return [
        ConversationTurnResponse(
            id=turn.id,
            conversation_id=turn.conversation_id,
            role=turn.role,
            content=turn.content,
            message_index=turn.message_index,
            created_at=turn.created_at.isoformat()
        )
        for turn in turns
    ]

@app.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a conversation and all its turns"""
    try:
        logger.info(f"Delete request for conversation {conversation_id} by user {current_user.id}")
        
        # Verify the conversation belongs to the user
        conversation = db.query(Conversation).filter(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id
        ).first()
        
        if not conversation:
            logger.warning(f"Conversation {conversation_id} not found for user {current_user.id}")
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # Delete all conversation turns first (due to foreign key constraints)
        db.query(ConversationTurn).filter(
            ConversationTurn.conversation_id == conversation_id
        ).delete()
        
        # Delete the conversation
        db.delete(conversation)
        db.commit()
        
        logger.info(f"Deleted conversation {conversation_id} and its turns for user {current_user.id}")
        return {"message": "Conversation deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting conversation {conversation_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete conversation")

@app.get("/memory/search")
async def search_memory(
    query: str,
    limit: int = 10,
    current_user: User = Depends(get_current_user)
):
    """Search through conversation memory"""
    if not query.strip():
        return {"results": []}
    
    try:
        # Use the existing search_memory_tool method
        search_results = await llm_client.search_memory_tool(query, current_user.id)
        
        return {
            "query": query,
            "results": search_results
        }
        
    except Exception as e:
        logger.error(f"Memory search error: {e}")
        raise HTTPException(status_code=500, detail=f"Memory search failed: {str(e)}")

@app.get("/memory/insights")
async def get_dream_insights(
    limit: int = 10,
    insight_type: str = None,
    current_user: User = Depends(get_current_user)
):
    """Get AI-generated insights from background dreaming/consolidation"""
    try:
        db = SessionLocal()
        try:
            query_filter = [DreamInsight.user_id == current_user.id]
            
            if insight_type:
                query_filter.append(DreamInsight.insight_type == insight_type)
            
            insights = db.query(DreamInsight).filter(*query_filter).order_by(
                DreamInsight.dream_date.desc()
            ).limit(limit).all()
            
            insights_data = []
            for insight in insights:
                insight_dict = {
                    "id": insight.id,
                    "type": insight.insight_type,
                    "title": insight.title,
                    "content": insight.content,
                    "confidence": insight.confidence,
                    "dream_date": insight.dream_date.isoformat(),
                    "surfaced_at": insight.surfaced_at.isoformat() if insight.surfaced_at else None,
                    "user_feedback": insight.user_feedback,
                    "related_episodes": json.loads(insight.related_episodes) if insight.related_episodes else []
                }
                insights_data.append(insight_dict)
            
            return {
                "insights": insights_data,
                "total": len(insights_data)
            }
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error fetching dream insights: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch insights")

@app.patch("/memory/insights/{insight_id}/feedback")
async def update_insight_feedback(
    insight_id: str,
    feedback: str,
    current_user: User = Depends(get_current_user)
):
    """Update user feedback on a dream insight"""
    try:
        db = SessionLocal()
        try:
            insight = db.query(DreamInsight).filter(
                DreamInsight.id == insight_id,
                DreamInsight.user_id == current_user.id
            ).first()
            
            if not insight:
                raise HTTPException(status_code=404, detail="Insight not found")
            
            insight.user_feedback = feedback
            insight.surfaced_at = datetime.now(timezone.utc)
            db.commit()
            
            return {"status": "updated", "feedback": feedback}
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error updating insight feedback: {e}")
        raise HTTPException(status_code=500, detail="Failed to update feedback")

# Knowledge Graph Endpoints
@app.get("/knowledge-graph/health")
async def knowledge_graph_health():
    """Check Neo4j connection health"""
    try:
        from app.services.neo4j_service import neo4j_service
        await neo4j_service.verify_connection()
        return {
            "status": "healthy",
            "neo4j_connected": True,
            "message": "Knowledge graph is operational"
        }
    except Exception as e:
        return {
            "status": "unhealthy", 
            "neo4j_connected": False,
            "error": str(e),
            "message": "Knowledge graph connection failed"
        }

@app.get("/knowledge-graph/")
async def get_user_knowledge_graph(
    depth: int = 2,
    current_user: User = Depends(get_current_user)
):
    """Get the complete knowledge graph for the current user"""
    try:
        from app.services.neo4j_service import neo4j_service
        graph_data = await neo4j_service.get_user_knowledge_graph(
            user_id=current_user.id,
            depth=depth
        )
        
        return {
            "nodes": graph_data.get("nodes", []),
            "relationships": graph_data.get("relationships", []),
            "total_nodes": len(graph_data.get("nodes", [])),
            "total_relationships": len(graph_data.get("relationships", []))
        }
        
    except Exception as e:
        logger.error(f"Failed to get knowledge graph: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve knowledge graph: {str(e)}")

@app.post("/knowledge-graph/search")
async def search_knowledge_graph(
    request: dict,
    current_user: User = Depends(get_current_user)
):
    """Search across all content types in the knowledge graph"""
    try:
        from app.services.neo4j_service import neo4j_service
        query = request.get("query")
        content_types = request.get("content_types")
        limit = request.get("limit", 20)
        
        if not query:
            raise HTTPException(status_code=400, detail="Search query is required")
        
        search_results = await neo4j_service.search_knowledge_graph(
            user_id=current_user.id,
            query=query,
            content_types=content_types,
            limit=limit
        )
        
        # Format results for frontend consumption
        formatted_results = []
        for item in search_results:
            # Determine primary content type
            primary_type = item.get("node_types", ["Unknown"])[0].lower()
            
            formatted_results.append({
                "id": item.get("id"),
                "type": primary_type,
                "title": item.get("title") or item.get("content", "")[:50] + "...",
                "content": item.get("content") or item.get("content_text", ""),
                "created_at": item.get("created_at"),
                "metadata": {
                    "node_types": item.get("node_types", []),
                    "properties": {k: v for k, v in item.items() if k not in ["id", "content", "content_text", "title", "created_at"]}
                }
            })
        
        return {
            "query": query,
            "results": formatted_results,
            "total_found": len(formatted_results)
        }
        
    except Exception as e:
        logger.error(f"Knowledge graph search failed: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

@app.post("/knowledge-graph/connection-details")
async def get_connection_details(
    request: dict,
    current_user: User = Depends(get_current_user)
):
    """Get detailed information about a specific connection"""
    try:
        from app.services.neo4j_service import neo4j_service
        source_id = request.get("source_id")
        target_id = request.get("target_id")
        
        if not source_id or not target_id:
            raise HTTPException(status_code=400, detail="Both source_id and target_id are required")
        
        # Get detailed connection info including shared content analysis
        connection_details = await neo4j_service.get_connection_details(
            source_id=source_id,
            target_id=target_id,
            user_id=current_user.id
        )
        
        return connection_details
        
    except Exception as e:
        logger.error(f"Failed to get connection details: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get connection details: {str(e)}")

@app.post("/knowledge-graph/connected-content")
async def get_connected_content(
    request: dict,
    current_user: User = Depends(get_current_user)
):
    """Find all content connected to a specific node"""
    try:
        from app.services.neo4j_service import neo4j_service
        node_id = request.get("node_id")
        depth = request.get("depth", 2)
        relationship_types = request.get("relationship_types")
        
        if not node_id:
            raise HTTPException(status_code=400, detail="Node ID is required")
        
        connected_items = await neo4j_service.find_connected_content(
            node_id=node_id,
            user_id=current_user.id,
            depth=depth,
            relationship_types=relationship_types
        )
        
        return {
            "source_node_id": node_id,
            "connected_content": connected_items,
            "total_connections": len(connected_items)
        }
        
    except Exception as e:
        logger.error(f"Failed to get connected content: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get connected content: {str(e)}")

@app.get("/analytics/dashboard")
async def get_analytics_dashboard(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get comprehensive analytics dashboard data"""
    try:
        # Database size and health
        try:
            # Simplified database size query
            db_size_query = text("SELECT pg_size_pretty(pg_database_size(current_database())) as size")
            db_size_result = db.execute(db_size_query).fetchone()
            db_size = db_size_result.size if db_size_result else "Unknown"
            
            # Get connection count
            conn_query = text("SELECT count(*) as connections FROM pg_stat_activity WHERE datname = current_database()")
            conn_result = db.execute(conn_query).fetchone()
            db_connections = conn_result.connections if conn_result else 0
        except Exception as e:
            logger.error(f"Database query error: {e}")
            db_size = "Unknown"
            db_connections = 0
        
        # Total messages and conversations
        total_conversations = db.query(Conversation).filter(Conversation.user_id == current_user.id).count()
        total_messages = db.query(ConversationTurn).filter(ConversationTurn.user_id == current_user.id).count()
        
        # Memory/archival counts
        messages_with_embeddings = db.query(ConversationTurn).filter(
            ConversationTurn.user_id == current_user.id,
            ConversationTurn.embedding.isnot(None)
        ).count()
        
        # System health checks
        try:
            # Test embedding service
            embedding_test = await embedding_service.generate_embedding("test")
            embedding_health = len(embedding_test) == EMBEDDING_DIM
        except:
            embedding_health = False
            
        # Database health
        try:
            db.execute(text("SELECT 1"))
            db_health = True
            logger.info("Database health check: PASS")
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            db_health = False
            
        # AI system metrics (get from recent logs)
        recent_chats = db.query(ConversationTurn).filter(
            ConversationTurn.user_id == current_user.id,
            ConversationTurn.role == "assistant",
            ConversationTurn.created_at >= datetime.now() - timedelta(days=7)
        ).count()
        
        # Tool usage stats (simplified)
        tool_calls_successful = recent_chats  # Approximation
        
        # User activity stats
        notes_count = db.query(Note).filter(Note.user_id == current_user.id).count()
        reminders_count = db.query(Reminder).filter(
            Reminder.user_id == current_user.id,
            Reminder.is_completed == False
        ).count()
        documents_count = db.query(Document).filter(Document.user_id == current_user.id).count()
        active_timers = db.query(Timer).filter(
            Timer.user_id == current_user.id,
            Timer.is_active == True
        ).count()
        
        # Recent activity
        last_conversation = db.query(Conversation).filter(
            Conversation.user_id == current_user.id
        ).order_by(Conversation.updated_at.desc()).first()
        
        last_activity = last_conversation.updated_at if last_conversation else None
        
        return {
            "database": {
                "size": db_size,
                "connections": db_connections,
                "health": db_health
            },
            "memory": {
                "total_conversations": total_conversations,
                "total_messages": total_messages,
                "archived_count": messages_with_embeddings,
                "archival_percentage": round((messages_with_embeddings / max(total_messages, 1)) * 100, 1)
            },
            "ai_system": {
                "embedding_service_health": embedding_health,
                "successful_responses_7d": recent_chats,
                "tool_calls_successful_7d": tool_calls_successful,
                "last_activity": last_activity.isoformat() if last_activity else None
            },
            "user_data": {
                "notes": notes_count,
                "active_reminders": reminders_count,
                "documents": documents_count,
                "active_timers": active_timers
            },
            "system_health": {
                "overall": db_health and embedding_health,
                "database": db_health,
                "ai_services": embedding_health,
                "status": "healthy" if (db_health and embedding_health) else "degraded"
            }
        }
        
    except Exception as e:
        logger.error(f"Analytics dashboard error: {e}")
        raise HTTPException(status_code=500, detail=f"Analytics failed: {str(e)}")

# Settings endpoints
@app.get("/settings/ai")
async def get_ai_settings(current_user: User = Depends(get_current_user)):
    """Get current AI configuration settings"""
    return {
        "openai_base_url": OPENAI_BASE_URL,
        "openai_model": OPENAI_MODEL,
        "openai_notification_model": OPENAI_NOTIFICATION_MODEL,
        "embedding_base_url": EMBEDDING_BASE_URL,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimension": EMBEDDING_DIM
    }

class AISettingsUpdate(BaseModel):
    openai_base_url: Optional[str] = None
    openai_model: Optional[str] = None
    openai_notification_model: Optional[str] = None
    embedding_base_url: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_dimension: Optional[int] = None

@app.put("/settings/ai")
async def update_ai_settings(
    settings: AISettingsUpdate,
    current_user: User = Depends(get_current_user)
):
    """Update AI configuration settings (requires restart to take effect)"""
    global OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_NOTIFICATION_MODEL, EMBEDDING_BASE_URL, EMBEDDING_MODEL, EMBEDDING_DIM
    
    updated_settings = {}
    
    if settings.openai_base_url is not None:
        OPENAI_BASE_URL = settings.openai_base_url
        updated_settings["openai_base_url"] = settings.openai_base_url
        
    if settings.openai_model is not None:
        OPENAI_MODEL = settings.openai_model
        updated_settings["openai_model"] = settings.openai_model
        
    if settings.openai_notification_model is not None:
        OPENAI_NOTIFICATION_MODEL = settings.openai_notification_model
        updated_settings["openai_notification_model"] = settings.openai_notification_model
        
    if settings.embedding_base_url is not None:
        EMBEDDING_BASE_URL = settings.embedding_base_url
        updated_settings["embedding_base_url"] = settings.embedding_base_url
        
    if settings.embedding_model is not None:
        EMBEDDING_MODEL = settings.embedding_model
        updated_settings["embedding_model"] = settings.embedding_model
        
    if settings.embedding_dimension is not None:
        EMBEDDING_DIM = settings.embedding_dimension
        updated_settings["embedding_dimension"] = settings.embedding_dimension
    
    # Reinitialize services with new settings
    global llm_client, embedding_service
    llm_client = SimpleLLMClient()
    embedding_service = EmbeddingService()
    
    logger.info(f"AI settings updated by user {current_user.email}: {updated_settings}")
    
    return {
        "message": "AI settings updated successfully",
        "updated_settings": updated_settings,
        "note": "Some changes may require application restart to take full effect"
    }

@app.post("/settings/ai/test")
async def test_ai_settings(current_user: User = Depends(get_current_user)):
    """Test current AI configuration"""
    test_results = {}
    
    try:
        # Test LLM connection
        test_messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello, just testing the connection. Please respond with 'Connection successful'."}
        ]
        
        response = await httpx.AsyncClient().post(
            f"{OPENAI_BASE_URL}/chat/completions",
            json={
                "model": OPENAI_MODEL,
                "messages": test_messages,
                "max_tokens": 50
            },
            headers={"Authorization": "Bearer dummy"},
            timeout=10.0
        )
        
        if response.status_code == 200:
            test_results["llm"] = {"status": "success", "message": "LLM connection successful"}
        else:
            test_results["llm"] = {"status": "error", "message": f"LLM connection failed: {response.status_code}"}
            
    except Exception as e:
        test_results["llm"] = {"status": "error", "message": f"LLM connection failed: {str(e)}"}
    
    try:
        # Test embedding service
        embedding = await embedding_service.generate_embedding("test")
        if embedding and len(embedding) == EMBEDDING_DIM:
            test_results["embedding"] = {"status": "success", "message": f"Embedding service working (dimension: {len(embedding)})"}
        else:
            test_results["embedding"] = {"status": "error", "message": "Embedding service returned invalid response"}
            
    except Exception as e:
        test_results["embedding"] = {"status": "error", "message": f"Embedding service failed: {str(e)}"}
    
    return test_results

# =============================================================================
# VULNERABILITY WATCH ENDPOINTS
# =============================================================================

@app.get("/api/vulnerability-reports", response_model=list[VulnerabilityReportListResponse])
async def get_vulnerability_reports(current_user: User = Depends(get_current_user)):
    """Get all vulnerability reports"""
    db = SessionLocal()
    try:
        reports = db.query(VulnerabilityReport).filter(
            VulnerabilityReport.user_id == current_user.id
        ).order_by(VulnerabilityReport.report_date.desc()).all()
        
        return [
            VulnerabilityReportListResponse(
                id=report.id,
                report_date=report.report_date.isoformat(),
                title=report.title,
                summary=report.summary,
                vulnerabilities_count=report.vulnerabilities_count,
                critical_count=report.critical_count,
                kev_count=report.kev_count,
                created_at=report.created_at.isoformat()
            ) for report in reports
        ]
    finally:
        db.close()

@app.get("/api/vulnerability-reports/{report_id}", response_model=VulnerabilityReportResponse)
async def get_vulnerability_report(report_id: str, current_user: User = Depends(get_current_user)):
    """Get a specific vulnerability report"""
    db = SessionLocal()
    try:
        report = db.query(VulnerabilityReport).filter(
            VulnerabilityReport.id == report_id,
            VulnerabilityReport.user_id == current_user.id
        ).first()
        
        if not report:
            raise HTTPException(status_code=404, detail="Vulnerability report not found")
        
        return VulnerabilityReportResponse(
            id=report.id,
            report_date=report.report_date.isoformat(),
            title=report.title,
            summary=report.summary,
            content=report.content,
            vulnerabilities_count=report.vulnerabilities_count,
            critical_count=report.critical_count,
            kev_count=report.kev_count,
            created_at=report.created_at.isoformat()
        )
    finally:
        db.close()

@app.get("/api/vulnerability-reports/latest", response_model=VulnerabilityReportResponse)
async def get_latest_vulnerability_report(current_user: User = Depends(get_current_user)):
    """Get the most recent vulnerability report"""
    db = SessionLocal()
    try:
        report = db.query(VulnerabilityReport).filter(
            VulnerabilityReport.user_id == current_user.id
        ).order_by(VulnerabilityReport.report_date.desc()).first()
        
        if not report:
            raise HTTPException(status_code=404, detail="No vulnerability reports found")
        
        return VulnerabilityReportResponse(
            id=report.id,
            report_date=report.report_date.isoformat(),
            title=report.title,
            summary=report.summary,
            content=report.content,
            vulnerabilities_count=report.vulnerabilities_count,
            critical_count=report.critical_count,
            kev_count=report.kev_count,
            created_at=report.created_at.isoformat()
        )
    finally:
        db.close()

@app.post("/api/vulnerability-reports/generate")
async def generate_vulnerability_report(
    current_user: User = Depends(get_current_user),
    request: Request = None
):
    """Generate a new daily vulnerability report"""
    if not VULNERABILITY_SERVICES_AVAILABLE:
        raise HTTPException(status_code=503, detail="Vulnerability services not available")
    
    from datetime import date
    
    db = SessionLocal()
    try:
        logger.info("🚀 Starting vulnerability report generation...")
        
        # Check if report already exists for today
        today = date.today()
        existing_report = db.query(VulnerabilityReport).filter(
            VulnerabilityReport.user_id == current_user.id,
            VulnerabilityReport.report_date == today
        ).first()
        
        # Check if regeneration is requested via query parameter
        regenerate = request.query_params.get("regenerate", "false").lower() == "true" if request else False
        logger.info(f"Regenerate parameter: {regenerate}, query_params: {request.query_params if request else 'No request'}")
        
        if existing_report and not regenerate:
            logger.warning(f"Report already exists for {today}")
            return {
                "message": "Report already exists for today", 
                "report_id": existing_report.id,
                "vulnerabilities_count": existing_report.vulnerabilities_count,
                "critical_count": existing_report.critical_count,
                "kev_count": existing_report.kev_count,
                "notification_sent": False
            }
        elif existing_report and regenerate:
            logger.info(f"Regenerating existing report for {today}")
            # Delete existing report to create a new one
            db.delete(existing_report)
            db.commit()
        
        # Fetch vulnerability data
        vulnerabilities = await fetch_all_vulnerability_data()
        
        # Get previous day's vulnerability IDs to identify NEW vulnerabilities only
        from datetime import timedelta
        yesterday = today - timedelta(days=1)
        previous_report = db.query(VulnerabilityReport).filter(
            VulnerabilityReport.user_id == current_user.id,
            VulnerabilityReport.report_date == yesterday
        ).first()
        
        previous_vuln_ids = set()
        if previous_report and previous_report.vulnerability_ids:
            import json
            try:
                previous_vuln_ids = set(json.loads(previous_report.vulnerability_ids))
            except (json.JSONDecodeError, TypeError):
                previous_vuln_ids = set()
        
        # Filter to only NEW vulnerabilities (not in previous report)
        current_vuln_ids = {v.cve_id for v in vulnerabilities}
        new_vulnerabilities = [v for v in vulnerabilities if v.cve_id not in previous_vuln_ids]
        
        logger.info(f"📊 Total fetched: {len(vulnerabilities)}, Previous: {len(previous_vuln_ids)}, NEW: {len(new_vulnerabilities)}")
        
        # Generate markdown report with Sara's AI analysis (using NEW vulnerabilities only)
        content, summary = await VulnerabilityProcessor.generate_markdown_report(new_vulnerabilities, today, is_new_only=True)
        
        # Count statistics (for ALL vulnerabilities, but report on NEW ones)
        kev_count = len([v for v in new_vulnerabilities if v.known_exploited])
        critical_count = len([v for v in new_vulnerabilities if v.severity == 'Critical' or (v.cvss_score is not None and v.cvss_score >= 9.0)])
        
        # Create report record (store ALL vulnerability IDs for next day's comparison)
        import json
        report = VulnerabilityReport(
            user_id=current_user.id,
            report_date=today,
            title=f"Daily Vulnerability Report - {today.strftime('%B %d, %Y')}",
            summary=summary,
            content=content,
            vulnerabilities_count=len(new_vulnerabilities),  # Count of NEW vulnerabilities only
            critical_count=critical_count,
            kev_count=kev_count,
            vulnerability_ids=json.dumps(list(current_vuln_ids))  # Store ALL for comparison
        )
        
        db.add(report)
        db.commit()
        db.refresh(report)
        
        # Send NTFY notification
        ntfy_service = VulnerabilityNotificationService(
            NTFY_SERVER_URL, 
            NTFY_VULNERABILITY_TOPIC, 
            NTFY_ENABLED
        )
        
        notification_result = await notify_report_ready(
            ntfy_service, 
            report.title, 
            summary, 
            report.id
        )
        
        # Log notification
        notification_log = NotificationLog(
            user_id=current_user.id,
            notification_type=notification_result["notification_type"],
            reference_id=notification_result["reference_id"],
            title=notification_result["title"],
            message=notification_result["message"],
            ntfy_response=json.dumps(notification_result)
        )
        db.add(notification_log)
        db.commit()
        
        logger.info(f"✅ Vulnerability report generated successfully: {report.id}")
        
        return {
            "message": "Vulnerability report generated successfully",
            "report_id": report.id,
            "vulnerabilities_count": len(new_vulnerabilities),  # NEW vulnerabilities only
            "critical_count": critical_count,
            "kev_count": kev_count,
            "total_vulnerabilities": len(vulnerabilities),  # Total fetched for reference
            "notification_sent": notification_result["success"]
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error generating vulnerability report: {e}")
        raise HTTPException(status_code=500, detail=f"Error generating vulnerability report: {str(e)}")
    finally:
        db.close()

@app.post("/api/notifications/ntfy", response_model=NotificationResponse)
async def send_ntfy_notification(
    notification: NotificationRequest,
    current_user: User = Depends(get_current_user)
):
    """Send NTFY notification manually (for testing)"""
    if not VULNERABILITY_SERVICES_AVAILABLE:
        raise HTTPException(status_code=503, detail="Vulnerability services not available")
    
    db = SessionLocal()
    try:
        ntfy_service = VulnerabilityNotificationService(
            NTFY_SERVER_URL, 
            NTFY_VULNERABILITY_TOPIC, 
            NTFY_ENABLED
        )
        
        # Send notification
        success = await ntfy_service._send_notification(
            title=notification.title,
            message=notification.message,
            priority=3,
            tags=["shield", "test"]
        )
        
        # Log notification
        notification_log = NotificationLog(
            user_id=current_user.id,
            notification_type=notification.type,
            reference_id=notification.reference_id,
            title=notification.title,
            message=notification.message,
            ntfy_response=json.dumps({"success": success})
        )
        
        db.add(notification_log)
        db.commit()
        db.refresh(notification_log)
        
        return NotificationResponse(
            id=notification_log.id,
            notification_type=notification_log.notification_type,
            title=notification_log.title,
            message=notification_log.message,
            sent_at=notification_log.sent_at.isoformat()
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error sending notification: {e}")
        raise HTTPException(status_code=500, detail=f"Error sending notification: {str(e)}")
    finally:
        db.close()

@app.get("/api/notifications/history", response_model=list[NotificationResponse])
async def get_notification_history(current_user: User = Depends(get_current_user)):
    """Get notification history for debugging"""
    db = SessionLocal()
    try:
        notifications = db.query(NotificationLog).filter(
            NotificationLog.user_id == current_user.id
        ).order_by(NotificationLog.sent_at.desc()).limit(50).all()
        
        return [
            NotificationResponse(
                id=notif.id,
                notification_type=notif.notification_type,
                title=notif.title,
                message=notif.message,
                sent_at=notif.sent_at.isoformat()
            ) for notif in notifications
        ]
    finally:
        db.close()

# ==========================================
# HABIT TRACKING ENDPOINTS
# ==========================================

@app.post("/habits", response_model=HabitResponse)
def create_habit(habit_data: HabitCreate, current_user=Depends(get_current_user)):
    """Create a new habit"""
    db = SessionLocal()
    try:
        habit = Habit(
            user_id=current_user.id,
            title=habit_data.title,
            type=habit_data.type,
            target_numeric=habit_data.target_numeric,
            unit=habit_data.unit,
            rrule=habit_data.rrule,
            weekly_minimum=habit_data.weekly_minimum,
            monthly_minimum=habit_data.monthly_minimum,
            windows=habit_data.windows,
            checklist_mode=habit_data.checklist_mode,
            checklist_threshold=habit_data.checklist_threshold,
            grace_days=habit_data.grace_days,
            retro_hours=habit_data.retro_hours,
            notes=habit_data.notes,
            current_streak=0,
            best_streak=0
        )
        db.add(habit)
        db.commit()
        db.refresh(habit)
        
        # Initialize streak record
        streak = HabitStreak(habit_id=habit.id)
        db.add(streak)
        db.commit()
        
        return HabitResponse(
            id=habit.id,
            title=habit.title,
            type=habit.type,
            target_numeric=habit.target_numeric,
            unit=habit.unit,
            rrule=habit.rrule,
            weekly_minimum=habit.weekly_minimum,
            monthly_minimum=habit.monthly_minimum,
            windows=habit.windows,
            checklist_mode=habit.checklist_mode,
            checklist_threshold=habit.checklist_threshold,
            grace_days=habit.grace_days,
            retro_hours=habit.retro_hours,
            paused=bool(habit.paused),
            pause_from=habit.pause_from.isoformat() if habit.pause_from else None,
            pause_to=habit.pause_to.isoformat() if habit.pause_to else None,
            notes=habit.notes,
            created_at=habit.created_at.isoformat(),
            updated_at=habit.updated_at.isoformat()
        )
    finally:
        db.close()

@app.get("/habits", response_model=list[HabitResponse])
def list_habits(current_user=Depends(get_current_user)):
    """List all habits for the current user"""
    db = SessionLocal()
    try:
        habits = db.query(Habit).filter(Habit.user_id == current_user.id).all()
        return [
            HabitResponse(
                id=habit.id,
                title=habit.title,
                type=habit.type,
                target_numeric=habit.target_numeric,
                unit=habit.unit,
                rrule=habit.rrule,
                weekly_minimum=habit.weekly_minimum,
                monthly_minimum=habit.monthly_minimum,
                windows=habit.windows,
                checklist_mode=habit.checklist_mode,
                checklist_threshold=habit.checklist_threshold,
                grace_days=habit.grace_days,
                retro_hours=habit.retro_hours,
                paused=bool(habit.paused),
                pause_from=habit.pause_from.isoformat() if habit.pause_from else None,
                pause_to=habit.pause_to.isoformat() if habit.pause_to else None,
                notes=habit.notes,
                created_at=habit.created_at.isoformat(),
                updated_at=habit.updated_at.isoformat()
            ) for habit in habits
        ]
    finally:
        db.close()

@app.get("/habits/today", response_model=HabitTodayResponse)
def get_today_habits(current_user=Depends(get_current_user)):
    """Get today's habit instances with stats"""
    db = SessionLocal()
    try:
        from app.services.habit_instances import HabitInstanceGenerator
        
        # First, generate any missing instances for today
        today = datetime.now().date()
        HabitInstanceGenerator.generate_instances_for_all_habits(
            db, current_user.id, today, today
        )
        
        # Get today's instances
        instances = HabitInstanceGenerator.get_today_instances(db, current_user.id, today)
        
        # Convert to response format
        habits = [
            HabitInstanceResponse(
                id=instance["instance_id"],
                habit_id=instance["habit_id"],
                date=instance["date"],
                window=instance.get("window"),
                expected=instance["expected"],
                status=instance["status"],
                progress=instance["progress"],
                total_amount=instance.get("total_amount"),
                target=instance.get("target"),
                title=instance["title"],
                type=instance["type"],
                unit=instance.get("unit")
            ) for instance in instances
        ]
        
        # Calculate stats
        total = len(habits)
        completed = len([h for h in habits if h.status == "complete"])
        in_progress = len([h for h in habits if h.status == "in_progress" or (h.progress > 0 and h.status != "complete")])
        completion_rate = (completed / total * 100) if total > 0 else 0
        
        stats = HabitTodayStats(
            total=total,
            completed=completed,
            in_progress=in_progress,
            completion_rate=completion_rate
        )
        
        return HabitTodayResponse(
            date=today.isoformat(),
            habits=habits,
            stats=stats
        )
    finally:
        db.close()

@app.post("/habits/{habit_id}/log")
def log_habit_completion(
    habit_id: str, 
    log_data: HabitLogCreate,
    current_user=Depends(get_current_user)
):
    """Log a habit completion"""
    db = SessionLocal()
    try:
        # Verify habit belongs to user
        habit = db.query(Habit).filter(
            Habit.id == habit_id,
            Habit.user_id == current_user.id
        ).first()
        
        if not habit:
            raise HTTPException(status_code=404, detail="Habit not found")
        
        # Create log entry
        log = HabitLog(
            habit_id=habit_id,
            user_id=current_user.id,
            source=log_data.source,
            payload=json.dumps({"amount": log_data.amount}) if log_data.amount else log_data.payload
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        
        # Update habit instance progress and streak
        from app.services.habit_instances import HabitInstanceGenerator
        from app.services.habit_streaks import HabitStreakCalculator
        from datetime import date
        
        # Get or create today's instance
        today = date.today()
        instance_data = HabitInstanceGenerator.get_instance_by_habit_and_date(
            db, habit_id, today
        )
        
        if instance_data:
            # Get all logs for this habit today
            today_logs = db.query(HabitLog).filter(
                HabitLog.habit_id == habit_id,
                HabitLog.ts >= datetime.combine(today, datetime.min.time()),
                HabitLog.ts < datetime.combine(today + timedelta(days=1), datetime.min.time())
            ).all()
            
            log_dicts = []
            for l in today_logs:
                log_dicts.append({
                    "payload": l.payload,
                    "ts": l.ts,
                    "source": l.source
                })
            
            # Get checklist items if needed
            checklist_items = []
            if habit.type == "checklist":
                items = db.query(HabitItem).filter(HabitItem.habit_id == habit_id).all()
                checklist_items = [{"id": item.id, "label": item.label} for item in items]
            
            # Update instance progress
            HabitInstanceGenerator.update_instance_progress(
                db, instance_data["instance_id"], log_dicts, habit, checklist_items
            )
            
            # Update streak if habit is now complete
            from app.services.habit_progress import HabitProgressCalculator
            is_complete = HabitProgressCalculator.is_habit_complete(
                habit.type, log_dicts, habit.target_numeric, checklist_items,
                habit.checklist_mode or "all", habit.checklist_threshold or 1.0
            )
            
            if is_complete:
                # Update streak
                streak = db.query(HabitStreak).filter(HabitStreak.habit_id == habit_id).first()
                if streak:
                    vacation_periods = []
                    if habit.pause_from and habit.pause_to:
                        vacation_periods = [(habit.pause_from.date(), habit.pause_to.date())]
                    
                    new_current, new_best, last_completed = HabitStreakCalculator.update_streak_after_completion(
                        streak.current_streak,
                        streak.best_streak,
                        streak.last_completed,
                        today,
                        habit.grace_days,
                        vacation_periods
                    )
                    
                    streak.current_streak = new_current
                    streak.best_streak = new_best
                    streak.last_completed = last_completed
                    streak.updated_at = datetime.now()
                    db.commit()
        
        return {"message": "Habit logged successfully", "log_id": log.id}
    finally:
        db.close()

@app.get("/habits/{habit_id}/streak", response_model=HabitStreakResponse)
def get_habit_streak(habit_id: str, current_user=Depends(get_current_user)):
    """Get streak information for a habit"""
    db = SessionLocal()
    try:
        # Verify habit belongs to user
        habit = db.query(Habit).filter(
            Habit.id == habit_id,
            Habit.user_id == current_user.id
        ).first()
        
        if not habit:
            raise HTTPException(status_code=404, detail="Habit not found")
        
        streak = db.query(HabitStreak).filter(HabitStreak.habit_id == habit_id).first()
        
        if not streak:
            # Create initial streak record
            streak = HabitStreak(habit_id=habit_id)
            db.add(streak)
            db.commit()
        
        return HabitStreakResponse(
            habit_id=streak.habit_id,
            current_streak=streak.current_streak,
            best_streak=streak.best_streak,
            last_completed=streak.last_completed.isoformat() if streak.last_completed else None
        )
    finally:
        db.close()

# ==========================================
# ADVANCED HABIT ENDPOINTS
# ==========================================

@app.patch("/habits/{habit_id}", response_model=HabitResponse)
def update_habit(habit_id: str, habit_data: dict, current_user=Depends(get_current_user)):
    """Update an existing habit"""
    db = SessionLocal()
    try:
        habit = db.query(Habit).filter(
            Habit.id == habit_id,
            Habit.user_id == current_user.id
        ).first()
        
        if not habit:
            raise HTTPException(status_code=404, detail="Habit not found")
        
        # Update fields that are provided
        update_fields = ["title", "target_numeric", "unit", "rrule", "weekly_minimum", 
                        "monthly_minimum", "windows", "checklist_mode", "checklist_threshold", 
                        "grace_days", "retro_hours", "notes"]
        
        for field in update_fields:
            if field in habit_data:
                setattr(habit, field, habit_data[field])
        
        habit.updated_at = datetime.now()
        db.commit()
        db.refresh(habit)
        
        return HabitResponse(
            id=habit.id,
            title=habit.title,
            type=habit.type,
            target_numeric=habit.target_numeric,
            unit=habit.unit,
            rrule=habit.rrule,
            weekly_minimum=habit.weekly_minimum,
            monthly_minimum=habit.monthly_minimum,
            windows=habit.windows,
            checklist_mode=habit.checklist_mode,
            checklist_threshold=habit.checklist_threshold,
            grace_days=habit.grace_days,
            retro_hours=habit.retro_hours,
            paused=bool(habit.paused),
            pause_from=habit.pause_from.isoformat() if habit.pause_from else None,
            pause_to=habit.pause_to.isoformat() if habit.pause_to else None,
            notes=habit.notes,
            created_at=habit.created_at.isoformat(),
            updated_at=habit.updated_at.isoformat()
        )
    finally:
        db.close()

@app.delete("/habits/{habit_id}")
def delete_habit(habit_id: str, current_user=Depends(get_current_user)):
    """Delete a habit and all associated data"""
    db = SessionLocal()
    try:
        habit = db.query(Habit).filter(
            Habit.id == habit_id,
            Habit.user_id == current_user.id
        ).first()
        
        if not habit:
            raise HTTPException(status_code=404, detail="Habit not found")
        
        # Delete associated data (cascade should handle this, but let's be explicit)
        db.query(HabitInstance).filter(HabitInstance.habit_id == habit_id).delete()
        db.query(HabitLog).filter(HabitLog.habit_id == habit_id).delete()
        db.query(HabitStreak).filter(HabitStreak.habit_id == habit_id).delete()
        db.query(HabitItem).filter(HabitItem.habit_id == habit_id).delete()
        db.query(HabitLink).filter(HabitLink.habit_id == habit_id).delete()
        
        # Delete the habit itself
        db.delete(habit)
        db.commit()
        
        return {"message": "Habit deleted successfully"}
    finally:
        db.close()

@app.post("/habits/{habit_id}/pause")
def pause_habit(habit_id: str, pause_data: HabitPauseRequest, current_user=Depends(get_current_user)):
    """Pause a habit for a specific period"""
    db = SessionLocal()
    try:
        habit = db.query(Habit).filter(
            Habit.id == habit_id,
            Habit.user_id == current_user.id
        ).first()
        
        if not habit:
            raise HTTPException(status_code=404, detail="Habit not found")
        
        # Parse dates
        try:
            pause_from = datetime.fromisoformat(pause_data.pause_from)
            pause_to = datetime.fromisoformat(pause_data.pause_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format")
        
        if pause_from >= pause_to:
            raise HTTPException(status_code=400, detail="Pause start must be before pause end")
        
        habit.paused = 1
        habit.pause_from = pause_from
        habit.pause_to = pause_to
        habit.updated_at = datetime.now()
        
        db.commit()
        
        return {"message": f"Habit paused from {pause_from.date()} to {pause_to.date()}"}
    finally:
        db.close()

@app.post("/habits/{habit_id}/resume")
def resume_habit(habit_id: str, current_user=Depends(get_current_user)):
    """Resume a paused habit"""
    db = SessionLocal()
    try:
        habit = db.query(Habit).filter(
            Habit.id == habit_id,
            Habit.user_id == current_user.id
        ).first()
        
        if not habit:
            raise HTTPException(status_code=404, detail="Habit not found")
        
        habit.paused = 0
        habit.pause_from = None
        habit.pause_to = None
        habit.updated_at = datetime.now()
        
        db.commit()
        
        return {"message": "Habit resumed successfully"}
    finally:
        db.close()

@app.post("/habits/{habit_id}/items", response_model=HabitItemResponse)
def add_habit_item(
    habit_id: str,
    item_data: HabitItemCreate,
    current_user=Depends(get_current_user)
):
    """Add a checklist item to a habit"""
    db = SessionLocal()
    try:
        # Verify habit belongs to user and is checklist type
        habit = db.query(Habit).filter(
            Habit.id == habit_id,
            Habit.user_id == current_user.id,
            Habit.type == "checklist"
        ).first()
        
        if not habit:
            raise HTTPException(status_code=404, detail="Habit not found or not a checklist")
        
        item = HabitItem(
            habit_id=habit_id,
            label=item_data.label,
            sort_order=item_data.sort_order
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        
        return HabitItemResponse(
            id=item.id,
            habit_id=item.habit_id,
            label=item.label,
            sort_order=item.sort_order,
            created_at=item.created_at.isoformat()
        )
    finally:
        db.close()

@app.get("/habits/{habit_id}/items", response_model=list[HabitItemResponse])
def get_habit_items(habit_id: str, current_user=Depends(get_current_user)):
    """Get all checklist items for a habit"""
    db = SessionLocal()
    try:
        # Verify habit belongs to user
        habit = db.query(Habit).filter(
            Habit.id == habit_id,
            Habit.user_id == current_user.id
        ).first()
        
        if not habit:
            raise HTTPException(status_code=404, detail="Habit not found")
        
        items = db.query(HabitItem).filter(
            HabitItem.habit_id == habit_id
        ).order_by(HabitItem.sort_order).all()
        
        return [
            HabitItemResponse(
                id=item.id,
                habit_id=item.habit_id,
                label=item.label,
                sort_order=item.sort_order,
                created_at=item.created_at.isoformat()
            ) for item in items
        ]
    finally:
        db.close()

@app.patch("/habit_items/{item_id}", response_model=HabitItemResponse)
def update_habit_item(item_id: str, item_data: dict, current_user=Depends(get_current_user)):
    """Update a checklist item"""
    db = SessionLocal()
    try:
        # Get item and verify ownership through habit
        item = db.query(HabitItem).join(Habit).filter(
            HabitItem.id == item_id,
            Habit.user_id == current_user.id
        ).first()
        
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        
        # Update fields
        if "label" in item_data:
            item.label = item_data["label"]
        if "sort_order" in item_data:
            item.sort_order = item_data["sort_order"]
        
        db.commit()
        db.refresh(item)
        
        return HabitItemResponse(
            id=item.id,
            habit_id=item.habit_id,
            label=item.label,
            sort_order=item.sort_order,
            created_at=item.created_at.isoformat()
        )
    finally:
        db.close()

@app.delete("/habit_items/{item_id}")
def delete_habit_item(item_id: str, current_user=Depends(get_current_user)):
    """Delete a checklist item"""
    db = SessionLocal()
    try:
        # Get item and verify ownership through habit
        item = db.query(HabitItem).join(Habit).filter(
            HabitItem.id == item_id,
            Habit.user_id == current_user.id
        ).first()
        
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        
        db.delete(item)
        db.commit()
        
        return {"message": "Item deleted successfully"}
    finally:
        db.close()

@app.post("/habits/{habit_id}/link", response_model=HabitLinkResponse)
def link_habit_to_resource(
    habit_id: str,
    link_data: HabitLinkCreate,
    current_user=Depends(get_current_user)
):
    """Link a habit to a note, document, or concept"""
    db = SessionLocal()
    try:
        # Verify habit belongs to user
        habit = db.query(Habit).filter(
            Habit.id == habit_id,
            Habit.user_id == current_user.id
        ).first()
        
        if not habit:
            raise HTTPException(status_code=404, detail="Habit not found")
        
        # Check if link already exists
        existing_link = db.query(HabitLink).filter(
            HabitLink.habit_id == habit_id,
            HabitLink.target_type == link_data.target_type,
            HabitLink.target_id == link_data.target_id
        ).first()
        
        if existing_link:
            raise HTTPException(status_code=400, detail="Link already exists")
        
        link = HabitLink(
            habit_id=habit_id,
            target_type=link_data.target_type,
            target_id=link_data.target_id,
            meta=link_data.meta
        )
        db.add(link)
        db.commit()
        db.refresh(link)
        
        return HabitLinkResponse(
            id=link.id,
            habit_id=link.habit_id,
            target_type=link.target_type,
            target_id=link.target_id,
            meta=link.meta,
            created_at=link.created_at.isoformat()
        )
    finally:
        db.close()

@app.get("/habits/{habit_id}/links", response_model=list[HabitLinkResponse])
def get_habit_links(habit_id: str, current_user=Depends(get_current_user)):
    """Get all links for a habit"""
    db = SessionLocal()
    try:
        # Verify habit belongs to user
        habit = db.query(Habit).filter(
            Habit.id == habit_id,
            Habit.user_id == current_user.id
        ).first()
        
        if not habit:
            raise HTTPException(status_code=404, detail="Habit not found")
        
        links = db.query(HabitLink).filter(HabitLink.habit_id == habit_id).all()
        
        return [
            HabitLinkResponse(
                id=link.id,
                habit_id=link.habit_id,
                target_type=link.target_type,
                target_id=link.target_id,
                meta=link.meta,
                created_at=link.created_at.isoformat()
            ) for link in links
        ]
    finally:
        db.close()

@app.delete("/habit_links/{link_id}")
def delete_habit_link(link_id: str, current_user=Depends(get_current_user)):
    """Delete a habit link"""
    db = SessionLocal()
    try:
        # Get link and verify ownership through habit
        link = db.query(HabitLink).join(Habit).filter(
            HabitLink.id == link_id,
            Habit.user_id == current_user.id
        ).first()
        
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")
        
        db.delete(link)
        db.commit()
        
        return {"message": "Link deleted successfully"}
    finally:
        db.close()

# ==========================================
# HABIT INSIGHTS & ANALYTICS ENDPOINTS
# ==========================================

@app.get("/insights/habits", response_model=HabitInsightsResponse)
def get_habit_insights(
    current_user=Depends(get_current_user),
    period: str = "month"
):
    """Get habit analytics and insights in frontend-expected format"""
    db = SessionLocal()
    try:
        from datetime import date, timedelta
        
        # Parse period
        days_map = {"week": 7, "month": 30, "year": 365}
        days = days_map.get(period, 30)
        
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        
        # Get all user habits
        habits = db.query(Habit).filter(Habit.user_id == current_user.id).all()
        
        # Calculate overview stats
        total_completions = 0
        total_expected = 0
        current_streaks = 0
        longest_streak = 0
        habit_performance = []
        
        for habit in habits:
            # Get instances in period
            instances = db.query(HabitInstance).filter(
                HabitInstance.habit_id == habit.id,
                HabitInstance.date >= start_date,
                HabitInstance.date <= end_date,
                HabitInstance.expected == 1
            ).all()
            
            expected_count = len(instances)
            completed_count = len([i for i in instances if i.status == "complete"])
            completion_rate = (completed_count / expected_count * 100) if expected_count > 0 else 0
            
            total_expected += expected_count
            total_completions += completed_count
            
            # Get current streak
            streak = db.query(HabitStreak).filter(HabitStreak.habit_id == habit.id).first()
            current_streak = streak.current_streak if streak else 0
            best_streak = streak.best_streak if streak else 0
            
            if current_streak > 0:
                current_streaks += 1
            if best_streak > longest_streak:
                longest_streak = best_streak
            
            habit_performance.append(HabitInsightsPerformance(
                habit_id=habit.id,
                title=habit.title,
                type=habit.type,
                completion_rate=completion_rate,
                current_streak=current_streak,
                best_streak=best_streak,
                total_completions=completed_count
            ))
        
        # Calculate average completion rate
        average_completion_rate = (total_completions / total_expected * 100) if total_expected > 0 else 0
        
        # Create overview
        overview = HabitInsightsOverview(
            total_habits=len(habits),
            active_habits=len([h for h in habits if not h.paused]),
            total_completions=total_completions,
            average_completion_rate=average_completion_rate,
            current_streaks=current_streaks,
            longest_streak=longest_streak
        )
        
        # Calculate weekly stats (simplified for now)
        week_start = end_date - timedelta(days=7)
        last_week_start = week_start - timedelta(days=7)
        
        # This week stats - collect from user's habits
        this_week_total = 0
        this_week_completed = 0
        for habit in habits:
            week_instances = db.query(HabitInstance).filter(
                HabitInstance.habit_id == habit.id,
                HabitInstance.date >= week_start,
                HabitInstance.date <= end_date,
                HabitInstance.expected == 1
            ).all()
            this_week_total += len(week_instances)
            this_week_completed += len([i for i in week_instances if i.status == "complete"])
        
        this_week_rate = (this_week_completed / this_week_total * 100) if this_week_total > 0 else 0
        
        # Last week stats
        last_week_total = 0
        last_week_completed = 0
        for habit in habits:
            week_instances = db.query(HabitInstance).filter(
                HabitInstance.habit_id == habit.id,
                HabitInstance.date >= last_week_start,
                HabitInstance.date < week_start,
                HabitInstance.expected == 1
            ).all()
            last_week_total += len(week_instances)
            last_week_completed += len([i for i in week_instances if i.status == "complete"])
        
        last_week_rate = (last_week_completed / last_week_total * 100) if last_week_total > 0 else 0
        
        # Determine trend
        if this_week_rate > last_week_rate + 5:
            trend = "up"
        elif this_week_rate < last_week_rate - 5:
            trend = "down"
        else:
            trend = "stable"
        
        weekly_stats = HabitInsightsWeeklyStats(
            this_week={"completed": this_week_completed, "total": this_week_total, "completion_rate": this_week_rate},
            last_week={"completed": last_week_completed, "total": last_week_total, "completion_rate": last_week_rate},
            trend=trend
        )
        
        # Create patterns (simplified for now)
        most_consistent = habit_performance[0].title if habit_performance else "None"
        
        patterns = HabitInsightsPatterns(
            best_day_of_week="Monday",  # Placeholder
            best_time_of_day="Morning",  # Placeholder
            most_consistent_habit=most_consistent,
            improvement_suggestions=[
                "Try setting reminders for your habits",
                "Start with smaller, easier habits to build momentum",
                "Track your habits at the same time each day"
            ]
        )
        
        return HabitInsightsResponse(
            overview=overview,
            weekly_stats=weekly_stats,
            habit_performance=habit_performance,
            patterns=patterns
        )
        
    finally:
        db.close()

@app.get("/habits/{habit_id}/history")
def get_habit_history(
    habit_id: str,
    current_user=Depends(get_current_user),
    days: int = 90
):
    """Get detailed history for a specific habit"""
    db = SessionLocal()
    try:
        from datetime import date, timedelta
        
        # Verify habit belongs to user
        habit = db.query(Habit).filter(
            Habit.id == habit_id,
            Habit.user_id == current_user.id
        ).first()
        
        if not habit:
            raise HTTPException(status_code=404, detail="Habit not found")
        
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        
        # Get instances
        instances = db.query(HabitInstance).filter(
            HabitInstance.habit_id == habit_id,
            HabitInstance.date >= start_date,
            HabitInstance.date <= end_date
        ).order_by(HabitInstance.date.desc()).all()
        
        # Get logs
        logs = db.query(HabitLog).filter(
            HabitLog.habit_id == habit_id,
            HabitLog.ts >= datetime.combine(start_date, datetime.min.time()),
            HabitLog.ts <= datetime.combine(end_date, datetime.max.time())
        ).order_by(HabitLog.ts.desc()).all()
        
        history = {
            "habit": {
                "id": habit.id,
                "title": habit.title,
                "type": habit.type,
                "target": habit.target_numeric,
                "unit": habit.unit
            },
            "period": {
                "days": days,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            },
            "instances": [
                {
                    "date": instance.date.isoformat(),
                    "expected": bool(instance.expected),
                    "status": instance.status,
                    "progress": instance.progress,
                    "total_amount": instance.total_amount,
                    "target": instance.target,
                    "window": instance.window
                } for instance in instances
            ],
            "logs": [
                {
                    "id": log.id,
                    "timestamp": log.ts.isoformat(),
                    "source": log.source,
                    "payload": log.payload
                } for log in logs
            ]
        }
        
        return history
        
    finally:
        db.close()

@app.post("/habits/{habit_id}/log-retro")
def log_habit_retro(
    habit_id: str,
    log_data: dict,
    current_user=Depends(get_current_user)
):
    """Log a habit completion for a past date (retro logging)"""
    db = SessionLocal()
    try:
        from datetime import datetime, date, timedelta
        
        # Verify habit belongs to user
        habit = db.query(Habit).filter(
            Habit.id == habit_id,
            Habit.user_id == current_user.id
        ).first()
        
        if not habit:
            raise HTTPException(status_code=404, detail="Habit not found")
        
        # Parse the target date
        try:
            if "date" in log_data:
                target_date = datetime.fromisoformat(log_data["date"]).date()
            else:
                raise HTTPException(status_code=400, detail="Date is required for retro logging")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format")
        
        # Check if retro logging is allowed
        days_ago = (date.today() - target_date).days
        if days_ago > habit.retro_hours / 24:
            raise HTTPException(
                status_code=400, 
                detail=f"Retro logging only allowed within {habit.retro_hours} hours"
            )
        
        if target_date > date.today():
            raise HTTPException(status_code=400, detail="Cannot log for future dates")
        
        # Create log entry with specified date
        log = HabitLog(
            habit_id=habit_id,
            user_id=current_user.id,
            ts=datetime.combine(target_date, datetime.now().time()),
            source=log_data.get("source", "retro"),
            payload=json.dumps({
                "amount": log_data.get("amount"),
                "retro": True
            }) if log_data.get("amount") else json.dumps({"retro": True})
        )
        db.add(log)
        db.commit()
        
        # Update instance for that date if it exists
        from app.services.habit_instances import HabitInstanceGenerator
        
        instance_data = HabitInstanceGenerator.get_instance_by_habit_and_date(
            db, habit_id, target_date
        )
        
        if instance_data:
            # Update the instance with new progress
            target_logs = db.query(HabitLog).filter(
                HabitLog.habit_id == habit_id,
                HabitLog.ts >= datetime.combine(target_date, datetime.min.time()),
                HabitLog.ts < datetime.combine(target_date + timedelta(days=1), datetime.min.time())
            ).all()
            
            log_dicts = []
            for l in target_logs:
                log_dicts.append({
                    "payload": l.payload,
                    "ts": l.ts,
                    "source": l.source
                })
            
            checklist_items = []
            if habit.type == "checklist":
                items = db.query(HabitItem).filter(HabitItem.habit_id == habit_id).all()
                checklist_items = [{"id": item.id, "label": item.label} for item in items]
            
            HabitInstanceGenerator.update_instance_progress(
                db, instance_data["instance_id"], log_dicts, habit, checklist_items
            )
        
        return {"message": f"Retro log created for {target_date}", "log_id": log.id}
        
    finally:
        db.close()


# ==========================================
# Worker Management Endpoints
# ==========================================

# Initialize worker coordinator
try:
    from app.workers.habit_worker_coordinator import HabitWorkerCoordinator
    worker_coordinator = HabitWorkerCoordinator()
    worker_coordinator.start_background_tasks()
    logger.info("✅ Habit worker coordinator initialized")
except Exception as e:
    logger.warning(f"⚠️ Habit worker coordinator not available: {e}")
    worker_coordinator = None

@app.get("/workers/status")
async def get_worker_status(current_user: User = Depends(get_current_user)):
    """Get status of all habit workers"""
    if not worker_coordinator:
        raise HTTPException(status_code=503, detail="Worker coordinator not available")
    return worker_coordinator.get_status()

@app.post("/workers/run/{task_name}")
async def run_worker_task(
    task_name: str,
    request: Dict[str, Any] = None,
    current_user: User = Depends(get_current_user)
):
    """Manually run a specific worker task"""
    if not worker_coordinator:
        raise HTTPException(status_code=503, detail="Worker coordinator not available")
    
    kwargs = request or {}
    result = await worker_coordinator.run_manual_task(task_name, **kwargs)
    return result

@app.post("/workers/generate-instances/{user_id}")
async def generate_past_instances(
    user_id: str,
    days_back: int = 7,
    current_user: User = Depends(get_current_user)
):
    """Generate habit instances for past days (retro logging support)"""
    if not worker_coordinator:
        raise HTTPException(status_code=503, detail="Worker coordinator not available")
    
    # Only allow users to generate for themselves or admin
    if current_user.id != user_id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    result = await worker_coordinator.run_manual_task(
        "generate_past_instances", 
        user_id=user_id, 
        days_back=days_back
    )
    return result

@app.post("/workers/streak-alerts/{user_id}")
async def send_streak_alerts(
    user_id: str,
    current_user: User = Depends(get_current_user)
):
    """Send streak alerts for a specific user"""
    if not worker_coordinator:
        raise HTTPException(status_code=503, detail="Worker coordinator not available")
    
    # Only allow users to send for themselves or admin
    if current_user.id != user_id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    result = await worker_coordinator.run_manual_task("streak_alerts", user_id=user_id)
    return result

# ==================== SARA AUTONOMOUS SYSTEM ENDPOINTS ====================

@app.get("/autonomous/insights", response_model=List[AutonomousInsightResponse])
async def get_autonomous_insights(
    limit: int = 20,
    sweep_type: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get autonomous insights for the current user"""
    
    query = db.query(AutonomousInsight).filter(AutonomousInsight.user_id == current_user.id)
    
    if sweep_type:
        query = query.filter(AutonomousInsight.sweep_type == sweep_type)
    
    insights = query.order_by(desc(AutonomousInsight.generated_at)).limit(limit).all()
    
    return [AutonomousInsightResponse(
        id=insight.id,
        user_id=insight.user_id,
        insight_type=insight.insight_type,
        personality_mode=insight.personality_mode,
        sweep_type=insight.sweep_type,
        priority_score=insight.priority_score,
        title=insight.title,
        message=insight.message,
        action_suggestion=json.loads(insight.action_suggestion) if insight.action_suggestion else None,
        related_data=json.loads(insight.related_data) if insight.related_data else None,
        surfaced_at=insight.surfaced_at,
        user_action=insight.user_action,
        feedback_score=insight.feedback_score,
        generated_at=insight.generated_at,
        expires_at=insight.expires_at
    ) for insight in insights]

@app.post("/autonomous/insights/{insight_id}/feedback")
async def submit_insight_feedback(
    insight_id: str,
    feedback: InsightFeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Submit feedback for an autonomous insight"""
    
    insight = db.query(AutonomousInsight).filter(
        and_(
            AutonomousInsight.id == insight_id,
            AutonomousInsight.user_id == current_user.id
        )
    ).first()
    
    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")
    
    insight.feedback_score = feedback.feedback_score
    insight.user_action = feedback.user_action
    insight.surfaced_at = datetime.now()
    
    db.commit()
    
    return {"message": "Feedback recorded", "insight_id": insight_id}

@app.post("/autonomous/sweep/{sweep_type}")
async def trigger_autonomous_sweep(
    sweep_type: str,
    personality_mode: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually trigger an autonomous sweep for testing/debugging"""
    
    if sweep_type not in ['quick_sweep', 'standard_sweep', 'digest_sweep']:
        raise HTTPException(status_code=400, detail="Invalid sweep type")
    
    # Get user's current personality mode if not specified
    if not personality_mode:
        profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
        personality_mode = profile.current_mode if profile else 'companion'
    
    try:
        from app.services.autonomous_sweep_service import AutonomousSweepService
        
        sweep_service = AutonomousSweepService(db)
        raw_insights = await sweep_service.execute_sweep(
            user_id=current_user.id,
            personality_mode=personality_mode,
            sweep_type=sweep_type,
            triggered_by="manual"
        )
        
        # Check for recent similar insights to avoid duplicates
        recent_cutoff = datetime.now() - timedelta(hours=6)  # Don't duplicate insights from last 6 hours
        recent_insights = db.query(AutonomousInsight).filter(
            and_(
                AutonomousInsight.user_id == current_user.id,
                AutonomousInsight.generated_at >= recent_cutoff
            )
        ).all()
        
        recent_types = {insight.insight_type for insight in recent_insights}
        recent_titles = {insight.title for insight in recent_insights}
        
        # Store insights in database, filtering out duplicates
        stored_insights = []
        new_insights = []
        for insight_data in raw_insights:
            # Only store insights that meet the priority threshold
            if sweep_service.scorer.should_surface(insight_data['priority_score'], sweep_type):
                # Check if this is genuinely new
                is_new = (insight_data['type'] not in recent_types and 
                         insight_data['title'] not in recent_titles)
                
                insight = AutonomousInsight(
                    user_id=current_user.id,
                    insight_type=insight_data['type'],
                    personality_mode=personality_mode,
                    sweep_type=sweep_type,
                    priority_score=insight_data['priority_score'],
                    title=insight_data['title'],
                    message=insight_data['message'],
                    action_suggestion=json.dumps(insight_data.get('action_suggestion')),
                    related_data=json.dumps({
                        **insight_data.get('related_data', {}),
                        **(insight_data.get('memory_context', {}))
                    }),
                    generated_at=datetime.now()
                )
                db.add(insight)
                stored_insights.append(insight)
                
                if is_new:
                    new_insights.append(insight)
        
        db.commit()
        
        return {
            "message": f"{sweep_type} completed successfully",
            "insights_generated": len(raw_insights),
            "insights_stored": len(stored_insights),
            "new_insights": len(new_insights),  # Key addition for frontend
            "personality_mode": personality_mode,
            "sweep_type": sweep_type
        }
        
    except Exception as e:
        logger.error(f"Autonomous sweep error: {e}")
        raise HTTPException(status_code=500, detail=f"Sweep execution failed: {str(e)}")

@app.get("/autonomous/profile", response_model=Optional[UserProfileResponse])
async def get_user_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's autonomous system profile"""
    
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    
    if not profile:
        return None
    
    return UserProfileResponse(
        id=profile.id,
        user_id=profile.user_id,
        current_mode=profile.current_mode,
        mode_preferences=json.loads(profile.mode_preferences) if profile.mode_preferences else None,
        autonomy_level=profile.autonomy_level,
        quiet_hours_start=profile.quiet_hours_start,
        quiet_hours_end=profile.quiet_hours_end,
        idle_thresholds=json.loads(profile.idle_thresholds) if profile.idle_thresholds else None,
        ntfy_enabled=profile.ntfy_enabled,
        ntfy_topics=json.loads(profile.ntfy_topics) if profile.ntfy_topics else None,
        sprite_notifications=profile.sprite_notifications,
        created_at=profile.created_at,
        updated_at=profile.updated_at
    )

@app.put("/autonomous/profile")
async def update_user_profile(
    profile_data: UserProfileCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update user's autonomous system profile"""
    
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    
    if not profile:
        profile = UserProfile(user_id=current_user.id)
        db.add(profile)
    
    # Update fields if provided
    if profile_data.current_mode is not None:
        profile.current_mode = profile_data.current_mode
    
    if profile_data.mode_preferences is not None:
        profile.mode_preferences = json.dumps(profile_data.mode_preferences)
    
    if profile_data.autonomy_level is not None:
        profile.autonomy_level = profile_data.autonomy_level
        
    if profile_data.quiet_hours_start is not None:
        profile.quiet_hours_start = profile_data.quiet_hours_start
        
    if profile_data.quiet_hours_end is not None:
        profile.quiet_hours_end = profile_data.quiet_hours_end
        
    if profile_data.idle_thresholds is not None:
        profile.idle_thresholds = json.dumps(profile_data.idle_thresholds)
        
    if profile_data.ntfy_enabled is not None:
        profile.ntfy_enabled = profile_data.ntfy_enabled
        
    if profile_data.ntfy_topics is not None:
        profile.ntfy_topics = json.dumps(profile_data.ntfy_topics)
        
    if profile_data.sprite_notifications is not None:
        profile.sprite_notifications = profile_data.sprite_notifications
    
    profile.updated_at = datetime.now()
    
    db.commit()
    
    return {"message": "Profile updated successfully", "profile_id": profile.id}

@app.get("/autonomous/sweeps", response_model=List[BackgroundSweepResponse])
async def get_background_sweeps(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get background sweep execution history"""
    
    sweeps = db.query(BackgroundSweep).filter(
        BackgroundSweep.user_id == current_user.id
    ).order_by(desc(BackgroundSweep.executed_at)).limit(limit).all()
    
    return [BackgroundSweepResponse(
        id=sweep.id,
        user_id=sweep.user_id,
        sweep_type=sweep.sweep_type,
        personality_mode=sweep.personality_mode,
        triggered_by=sweep.triggered_by,
        execution_time_ms=sweep.execution_time_ms,
        insights_generated=sweep.insights_generated,
        errors_encountered=json.loads(sweep.errors_encountered) if sweep.errors_encountered else None,
        episodes_analyzed=sweep.episodes_analyzed,
        notes_analyzed=sweep.notes_analyzed,
        patterns_found=json.loads(sweep.patterns_found) if sweep.patterns_found else None,
        executed_at=sweep.executed_at
    ) for sweep in sweeps]


# =====================
# GTKY (Get-to-Know-You) Interview Endpoints
# =====================

class GTKYStartResponse(BaseModel):
    status: str
    session_id: Optional[str] = None
    message: Optional[str] = None
    pack_info: Optional[Dict[str, Any]] = None
    question: Optional[Dict[str, Any]] = None
    sprite_state: Optional[str] = None
    completed_at: Optional[str] = None
    can_retake: Optional[bool] = None

class GTKYResponseRequest(BaseModel):
    response: Dict[str, Any]

class GTKYResponseReply(BaseModel):
    status: str
    session_id: Optional[str] = None
    question: Optional[Dict[str, Any]] = None
    follow_up: Optional[str] = None
    progress: Optional[str] = None
    completed_pack: Optional[str] = None
    next_pack: Optional[Dict[str, Any]] = None
    can_continue: Optional[bool] = None
    message: Optional[str] = None
    profile_summary: Optional[str] = None
    next_steps: Optional[List[str]] = None

class GTKYProfileSummary(BaseModel):
    completed_at: Optional[str] = None
    communication_style: Optional[str] = None
    autonomy_level: Optional[str] = None
    profile_data: Optional[Dict[str, Any]] = None
    notification_channels: Optional[Dict[str, Any]] = None

@app.post("/onboarding/gtky/start", response_model=GTKYStartResponse)
async def start_gtky_interview(
    personality_mode: str = "companion",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Start or restart the Get-to-Know-You interview"""
    
    if not GTKY_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="GTKY service not available")
    
    gtky_service = GTKYService(db)
    
    try:
        result = await gtky_service.start_interview(
            user_id=str(current_user.id),
            personality_mode=personality_mode
        )
        
        return GTKYStartResponse(**result)
        
    except Exception as e:
        logger.error(f"Failed to start GTKY interview: {e}")
        raise HTTPException(status_code=500, detail="Failed to start interview")

@app.post("/onboarding/gtky/respond/{session_id}", response_model=GTKYResponseReply)
async def respond_to_gtky_question(
    session_id: str,
    request: GTKYResponseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Respond to a GTKY interview question"""
    
    if not GTKY_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="GTKY service not available")
    
    gtky_service = GTKYService(db)
    
    try:
        result = await gtky_service.respond_to_question(
            session_id=session_id,
            user_id=str(current_user.id),
            response=request.response
        )
        
        return GTKYResponseReply(**result)
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to process GTKY response: {e}")
        raise HTTPException(status_code=500, detail="Failed to process response")

@app.post("/onboarding/gtky/continue/{pack_id}", response_model=GTKYResponseReply)
async def continue_gtky_with_pack(
    pack_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Continue GTKY interview with next question pack"""
    
    if not GTKY_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="GTKY service not available")
    
    gtky_service = GTKYService(db)
    
    try:
        result = await gtky_service.continue_with_pack(
            user_id=str(current_user.id),
            pack_id=pack_id
        )
        
        # Convert to response format
        return GTKYResponseReply(
            status=result["status"],
            session_id=result.get("session_id"),
            question=result.get("question"),
            progress=f"Starting {result['pack_info']['name']}"
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to continue GTKY pack: {e}")
        raise HTTPException(status_code=500, detail="Failed to continue interview")

@app.get("/onboarding/gtky/profile", response_model=GTKYProfileSummary)
async def get_gtky_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's GTKY profile summary"""
    
    if not GTKY_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="GTKY service not available")
    
    gtky_service = GTKYService(db)
    
    try:
        profile = await gtky_service.get_profile_summary(str(current_user.id))
        
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found - complete GTKY interview first")
        
        return GTKYProfileSummary(**profile)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get GTKY profile: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve profile")


# =====================
# Nightly Reflection Endpoints
# =====================

class ReflectionStartResponse(BaseModel):
    status: str
    reflection_id: Optional[str] = None
    message: Optional[str] = None
    reflection_date: Optional[str] = None
    current_question_index: Optional[int] = None
    total_questions: Optional[int] = None
    question: Optional[Dict[str, Any]] = None
    progress: Optional[str] = None
    estimated_time: Optional[str] = None
    responses: Optional[Dict[str, Any]] = None
    insights_generated: Optional[Dict[str, Any]] = None
    mood_score: Optional[int] = None
    can_update: Optional[bool] = None

class ReflectionResponseRequest(BaseModel):
    question_id: str
    response: Any
    question_index: int

class ReflectionResponseReply(BaseModel):
    status: str
    question: Optional[Dict[str, Any]] = None
    follow_up: Optional[str] = None
    progress: Optional[str] = None
    current_question_index: Optional[int] = None
    message: Optional[str] = None
    insights: Optional[Dict[str, Any]] = None
    reflection_summary: Optional[str] = None
    mood_score: Optional[int] = None
    next_steps: Optional[List[str]] = None

class ReflectionHistoryResponse(BaseModel):
    history: List[Dict[str, Any]]
    total_count: int
    current_streak: int
    pagination: Dict[str, Any]

class ReflectionInsightsResponse(BaseModel):
    reflection_id: str
    reflection_date: str
    insights: Dict[str, Any]
    responses: Dict[str, Any]
    mood_score: Optional[int] = None
    summary: str

class ReflectionSettingsRequest(BaseModel):
    enabled: Optional[bool] = None
    preferred_time: Optional[str] = None
    timezone: Optional[str] = None
    quiet_hours: Optional[Dict[str, Any]] = None
    reminder_channels: Optional[Dict[str, Any]] = None

@app.post("/reflection/start", response_model=ReflectionStartResponse)
async def start_reflection(
    reflection_date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Start a new daily reflection"""
    
    if not REFLECTION_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Reflection service not available")
    
    reflection_service = ReflectionService(db)
    
    try:
        # Parse reflection date if provided
        parsed_date = None
        if reflection_date:
            from datetime import date
            parsed_date = date.fromisoformat(reflection_date)
        
        result = await reflection_service.start_reflection(
            user_id=str(current_user.id),
            reflection_date=parsed_date
        )
        
        return ReflectionStartResponse(**result)
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to start reflection: {e}")
        raise HTTPException(status_code=500, detail="Failed to start reflection")

@app.post("/reflection/{reflection_id}/respond", response_model=ReflectionResponseReply)
async def respond_to_reflection_question(
    reflection_id: str,
    request: ReflectionResponseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Respond to a reflection question"""
    
    if not REFLECTION_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Reflection service not available")
    
    reflection_service = ReflectionService(db)
    
    try:
        result = await reflection_service.respond_to_question(
            reflection_id=reflection_id,
            user_id=str(current_user.id),
            question_id=request.question_id,
            response=request.response,
            question_index=request.question_index
        )
        
        return ReflectionResponseReply(**result)
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to process reflection response: {e}")
        raise HTTPException(status_code=500, detail="Failed to process response")

@app.get("/reflection/history", response_model=ReflectionHistoryResponse)
async def get_reflection_history(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's reflection history"""
    
    if not REFLECTION_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Reflection service not available")
    
    reflection_service = ReflectionService(db)
    
    try:
        result = await reflection_service.get_reflection_history(
            user_id=str(current_user.id),
            limit=limit,
            offset=offset
        )
        
        return ReflectionHistoryResponse(**result)
        
    except Exception as e:
        logger.error(f"Failed to get reflection history: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve reflection history")

@app.get("/reflection/{reflection_id}/insights", response_model=ReflectionInsightsResponse)
async def get_reflection_insights(
    reflection_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get insights for a specific reflection"""
    
    if not REFLECTION_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Reflection service not available")
    
    reflection_service = ReflectionService(db)
    
    try:
        result = await reflection_service.get_reflection_insights(
            reflection_id=reflection_id,
            user_id=str(current_user.id)
        )
        
        return ReflectionInsightsResponse(**result)
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get reflection insights: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve insights")

@app.post("/reflection/settings")
async def update_reflection_settings(
    request: ReflectionSettingsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update reflection settings"""
    
    if not REFLECTION_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Reflection service not available")
    
    reflection_service = ReflectionService(db)
    
    try:
        result = await reflection_service.update_reflection_settings(
            user_id=str(current_user.id),
            settings_data=request.dict(exclude_none=True)
        )
        
        return result
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update reflection settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to update settings")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="10.185.1.180", port=8000)
