from fastapi import FastAPI, Depends, HTTPException, status, Response, Request, Query, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from sqlalchemy import create_engine, Column, String, DateTime, Text, Integer, Float, Boolean, text, and_, or_, desc, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
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
from typing import Optional, Dict, Any, List, Union
# CryptContext imported via app.core.auth.pwd_context
from datetime import datetime, timedelta, timezone, date
from app.core.timezone import now as local_now, today as local_today, format_datetime as format_local_datetime, USER_TIMEZONE, format_iso_utc
from jose import jwt, JWTError
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
from fastapi import APIRouter
from urllib.parse import urlparse
import pytz
from app.tools.registry import tool_registry
from app.services.search_service import search_service
from app.services.embedding_service import embedding_service
from app.services.insight_injection import InsightInjectionService
from app.services.intent_classifier import get_tool_intent_classifier
from app.services.body_state_calibration import calibration_service
from app.services.sara_journal_service import sara_journal
from app.services.context_router import get_context_router
from app.services.workout_session_service import workout_session_service
from app.core import config
from app.core.prompt_template import render_prompt_template
from app.core.auth import (
    pwd_context,
    create_access_token,
    verify_token,
    get_cookie_domain,
    verify_password,
    get_password_hash
)

# Import Daily Brief system
try:
    from app.services.daily_brief import daily_brief_service
    DAILY_BRIEF_AVAILABLE = True
except ImportError as e:
    logging.warning(f"Daily Brief service not available: {e}")
    DAILY_BRIEF_AVAILABLE = False


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

# Import chess command handler
try:
    from app.services.chess_command_handler import (
        handle_chess_command,
        get_chess_mode,
        is_in_chess_game,
        get_chess_context_prompt
    )
    CHESS_COMMANDS_AVAILABLE = True
except ImportError as e:
    logging.warning(f"Chess command handler not available: {e}")
    CHESS_COMMANDS_AVAILABLE = False

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
# IMPORTANT: Always use PostgreSQL, never SQLite
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@db:5432/sara_hub")
# JWT settings now in app.core.config.settings
# CORS configuration for frontend origins
# Prefer CORS_ORIGINS from environment as a JSON array or comma-separated list
_cors_env = os.getenv("CORS_ORIGINS", "")
_parsed_env_origins = []
if _cors_env:
    try:
        _parsed = json.loads(_cors_env)
        if isinstance(_parsed, list):
            _parsed_env_origins = [str(x) for x in _parsed]
    except Exception:
        # Fallback: comma-separated
        _parsed_env_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]

# Default allowed origins (overridden by CORS_ORIGINS env when provided)
CORS_ORIGINS = _parsed_env_origins or [
    "https://sara.avery.cloud",
    "http://sara.avery.cloud",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3002",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://127.0.0.1:3002",
    "http://10.185.1.180:3000",
    "http://10.185.1.180:3001",
    "http://10.185.1.180:3002",
    "http://10.185.1.188:3000",
    "http://10.185.1.180",
    "http://10.185.1.188",
]

# Optional regex for dynamic IPs; leave unset by default
ALLOWED_ORIGIN_REGEX = os.getenv("CORS_ALLOW_REGEX") or r"^https?://(10\.185\.1\.(180|188))(\:\d+)?$"

# NTFY Configuration
NTFY_SERVER_URL = os.getenv("NTFY_SERVER_URL", "http://10.185.1.8:8889")
NTFY_ENABLED = os.getenv("NTFY_ENABLED", "true").lower() == "true"
NTFY_TIMERS_TOPIC = os.getenv("NTFY_TIMERS_TOPIC", "sara")
NTFY_REMINDERS_TOPIC = os.getenv("NTFY_REMINDERS_TOPIC", "sara")
NTFY_DOCUMENTS_TOPIC = os.getenv("NTFY_DOCUMENTS_TOPIC", "sara")
NTFY_SYSTEM_TOPIC = os.getenv("NTFY_SYSTEM_TOPIC", "sara")
AI_PROVIDER = os.getenv("AI_PROVIDER", "local")  # Options: local, gemini, openai, claude, custom
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://100.104.68.115:11434/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-oss:120b")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "dummy")  # Runtime configurable
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")  # Separate key for Anthropic Claude API

def is_anthropic_provider() -> bool:
    """Check if the current provider is Anthropic Claude"""
    return "api.anthropic.com" in OPENAI_BASE_URL

# Smaller, faster model for notifications (uses same endpoint but different model)
OPENAI_NOTIFICATION_MODEL = os.getenv("OPENAI_NOTIFICATION_MODEL", "gpt-oss:20b")

# Fast model configuration (for Pi dashboard fast worker, etc.)
# Uses Gemini by default for speed
FAST_MODEL_URL = os.getenv("FAST_MODEL_URL", os.getenv("OPENAI_BASE_URL", "http://100.104.68.115:11434/v1"))
FAST_MODEL = os.getenv("FAST_MODEL", "gemini-3-flash-preview")
FAST_MODEL_API_KEY = os.getenv("FAST_MODEL_API_KEY", os.getenv("OPENAI_API_KEY", ""))
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "http://10.185.1.8:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
GRAPH_BACKEND = os.getenv("GRAPH_BACKEND", "postgres").lower()
MEMORY_HOT_DAYS = int(os.getenv("MEMORY_HOT_DAYS", "30"))
MEMORY_K_DEFAULT = int(os.getenv("MEMORY_K", "10"))
MEMORY_SALIENCE_WRITE_THRESHOLD = float(os.getenv("MEMORY_SALIENCE_WRITE_THRESHOLD", "0.35"))
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

# Startup health tracking - monitors critical service status
STARTUP_HEALTH = {
    "database": {"status": "unknown", "message": None},
    "embedding_service": {"status": "unknown", "message": None, "dimension": None},
    "llm_service": {"status": "unknown", "message": None},
    "neo4j": {"status": "unknown", "message": None},
    "startup_time": None,
    "critical_failures": []
}

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

class BackgroundTask(Base):
    """Tracks background agent tasks that run independently of user sessions"""
    __tablename__ = "background_task"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="pending")  # pending, running, completed, failed, needs_clarification
    task_type = Column(String, nullable=False, default="research")  # research, analysis, etc.
    original_query = Column(Text, nullable=False)  # The user's original request
    result_note_id = Column(String, nullable=True)  # Link to workspace note with results
    workspace_folder_id = Column(String, nullable=True)  # Agent workspace folder
    clarification_question = Column(Text, nullable=True)  # If status is needs_clarification
    clarification_response = Column(Text, nullable=True)  # User's response to clarification
    error_message = Column(Text, nullable=True)  # If status is failed
    task_metadata = Column(JSONB, default={})  # orchestrator state, worker count, progress, etc.
    created_at = Column(DateTime, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

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

class CalendarEvent(Base):
    __tablename__ = "calendar_event"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    location = Column(String, default="")
    all_day = Column(Boolean, default=False)
    reminder_minutes = Column(Integer)
    is_completed = Column(Boolean, default=False)  # PostgreSQL boolean
    # iOS calendar sync fields
    source = Column(String, default="sara")  # 'sara' or 'ios_calendar'
    ios_event_id = Column(String, nullable=True)  # iOS event identifier for deduplication
    ios_calendar_id = Column(String, nullable=True)  # iOS calendar identifier
    ios_calendar_name = Column(String, nullable=True)  # Human-readable calendar name
    read_only = Column(Boolean, default=False)  # iOS synced events are read-only
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

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

# ===================== HUMAN-LIKE MEMORY TABLES =====================
class MemoryTrace(Base):
    __tablename__ = "memory_trace"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    content = Column(Text, nullable=False)
    role = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    salience = Column(Float, nullable=True)
    # Store JSON as text for portability; services can json.loads when needed
    source = Column(Text, nullable=True)
    meta = Column(Text, nullable=True)

class MemoryEmbedding(Base):
    __tablename__ = "memory_embedding"
    trace_id = Column(String, primary_key=True)
    head = Column(String, primary_key=True)
    embedding = Column(Vector(EMBEDDING_DIM) if PGVECTOR_AVAILABLE and DATABASE_URL.startswith("postgresql") else Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class MemoryEdge(Base):
    __tablename__ = "memory_edge"
    src = Column(String, primary_key=True)
    dst = Column(String, primary_key=True)
    type = Column(String, primary_key=True)
    weight = Column(Float, nullable=True)
    ts = Column(DateTime(timezone=True), server_default=func.now())

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

    # Rating system columns (pre-computed for fast retrieval)
    rating_boost = Column(Float, default=0.0)  # Pre-computed Wilson score + temporal decay
    exploration_bonus = Column(Float, default=0.0)  # Thompson Sampling bonus for cold-start

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

class EpisodeRating(Base):
    """Episode rating system for user feedback and memory quality scoring"""
    __tablename__ = "episode_rating"
    episode_id = Column(String, ForeignKey('episode.id', ondelete='CASCADE'), primary_key=True)
    user_rating = Column(Integer, nullable=True)  # 1-5 star rating from user
    rating_count = Column(Integer, default=0)  # Number of ratings (for multi-user future)
    average_rating = Column(Float, default=0.0)  # Average rating (for multi-user future)
    rating_sum = Column(Integer, default=0)  # Sum of all ratings for Wilson score
    last_rated = Column(DateTime, nullable=True)
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
    embedding = Column(Vector(1024), nullable=True) if PGVECTOR_AVAILABLE else Column(Text, nullable=True)  # Embedding for semantic search

    # User interaction
    surfaced_at = Column(DateTime, nullable=True)  # When shown to user
    user_feedback = Column(String, nullable=True)  # relevant, not_relevant, interesting

    created_at = Column(DateTime, server_default=func.now())

# Phase 4 Intelligence Models
class DailyBriefing(Base):
    """Daily briefings (morning/evening) with personalized insights"""
    __tablename__ = "daily_briefings"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    briefing_type = Column(String, nullable=False)  # "morning" or "evening"
    briefing_date = Column(DateTime, nullable=False)
    content = Column(Text, nullable=False)  # Markdown formatted briefing
    delivered = Column(Integer, default=0)  # boolean: sent to user
    read = Column(Integer, default=0)  # boolean: user opened/read
    created_at = Column(DateTime, server_default=func.now())

class BriefingSettings(Base):
    """User preferences for daily briefings"""
    __tablename__ = "briefing_settings"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, unique=True)

    # Morning briefing settings
    morning_enabled = Column(Integer, default=1)  # boolean
    morning_time = Column(String, default="07:00:00")  # HH:MM:SS

    # Evening briefing settings
    evening_enabled = Column(Integer, default=1)  # boolean
    evening_time = Column(String, default="21:00:00")  # HH:MM:SS

    # Content preferences (what to include)
    include_recovery = Column(Integer, default=1)  # fitness recovery status
    include_schedule = Column(Integer, default=1)  # today's calendar
    include_goals = Column(Integer, default=1)  # progress toward goals
    include_suggestions = Column(Integer, default=1)  # proactive suggestions
    include_workout_rec = Column(Integer, default=1)  # workout recommendations
    include_accomplishments = Column(Integer, default=1)  # daily wins
    include_insights = Column(Integer, default=1)  # AI insights
    include_reflection = Column(Integer, default=1)  # reflection prompts

    updated_at = Column(DateTime, server_default=func.now())

class ContextMode(Base):
    """User's current context mode for dynamic memory retrieval"""
    __tablename__ = "context_modes"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, unique=True)
    current_mode = Column(String, default="full")  # full, recent, minimal, fitness, work, learning
    updated_at = Column(DateTime, server_default=func.now())

class IntelligenceReport(Base):
    """Periodic intelligence reports (weekly/monthly/quarterly)"""
    __tablename__ = "intelligence_reports"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    report_type = Column(String, nullable=False)  # weekly, monthly, quarterly
    report_date = Column(DateTime, nullable=False)

    # Report content
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=False)  # Markdown summary
    full_content = Column(Text, nullable=True)  # Full markdown report

    # Metadata
    key_insights = Column(Text, nullable=True)  # JSON array of insights
    metrics = Column(Text, nullable=True)  # JSON object with metrics

    created_at = Column(DateTime, server_default=func.now())

class ProactiveSuggestion(Base):
    """AI-generated proactive suggestions based on patterns"""
    __tablename__ = "proactive_suggestions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)

    # Suggestion content
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String, nullable=False)  # health, productivity, learning, relationships, etc.
    priority = Column(String, default="medium")  # high, medium, low
    confidence = Column(Float, nullable=False)  # AI confidence (0-1)

    # Reasoning
    reasoning = Column(Text, nullable=True)  # Why this suggestion was made
    related_patterns = Column(Text, nullable=True)  # JSON array of pattern IDs

    # User interaction
    status = Column(String, default="pending")  # pending, accepted, dismissed
    actioned_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, server_default=func.now())

class DetectedPattern(Base):
    """Automatically detected behavioral/temporal patterns"""
    __tablename__ = "detected_patterns"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)

    # Pattern details
    pattern_type = Column(String, nullable=False)  # temporal, behavioral, correlational, anomaly
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)

    # Pattern metadata
    confidence = Column(Float, nullable=False)  # AI confidence (0-1)
    frequency = Column(String, nullable=True)  # daily, weekly, monthly
    data_points = Column(Integer, nullable=True)  # How many observations

    # Evidence
    evidence = Column(Text, nullable=True)  # JSON array of evidence examples
    related_episodes = Column(Text, nullable=True)  # JSON array of episode IDs

    # Discovery
    first_detected = Column(DateTime, server_default=func.now())
    last_confirmed = Column(DateTime, nullable=True)

    created_at = Column(DateTime, server_default=func.now())


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
    """Outbox pattern for Neo4j sync - guarantees eventual consistency between Postgres and Neo4j.

    Event Types:
    - episode_created: Sync episode to Neo4j, then queue for deep analysis
    - note_created/note_updated: Sync note to Neo4j
    - document_uploaded: Sync document to Neo4j
    - episode_deep_analysis: Run LLM extraction for entities/topics
    - insight_generated: Backpropagate importance to source episodes
    """
    __tablename__ = "event_outbox"
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Event identification
    event_type = Column(String, nullable=False)  # episode_created, note_created, etc.
    aggregate_type = Column(String, nullable=False)  # Episode, Note, Document
    aggregate_id = Column(String, nullable=False)  # UUID of the source record

    # Payload and operation
    op = Column(String, nullable=False, default="UPSERT")  # UPSERT, DELETE
    payload = Column(Text, nullable=False)  # JSON with full event data

    # Processing status
    status = Column(String, nullable=False, default="pending")  # pending, processing, completed, failed
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=5)
    last_error = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    processed_at = Column(DateTime, nullable=True)
    next_retry_at = Column(DateTime, nullable=True)  # For exponential backoff

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
    profile_data = Column(JSONB, nullable=True, default=dict)  # JSON: Goals, preferences, personality settings
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

class PushToken(Base):
    """Store push notification tokens for iOS/Android devices"""
    __tablename__ = "push_token"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    token = Column(String, nullable=False, unique=True)  # Expo push token
    platform = Column(String, nullable=False)  # ios or android
    device_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

# Ensure pgvector extension exists on Postgres before creating tables
try:
    if DATABASE_URL.startswith("postgresql"):
        with engine.connect() as conn:
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.commit()
                logger.info("✅ Ensured pgvector extension is available")
            except Exception as e:
                logger.warning(f"Could not create pgvector extension: {e}")
except Exception as e:
    logger.warning(f"Postgres extension check failed: {e}")

# Create tables
Base.metadata.create_all(bind=engine)

# Optional: create ANN index for pgvector on hot tier
try:
    if PGVECTOR_AVAILABLE and DATABASE_URL.startswith("postgresql"):
        with engine.connect() as conn:
            try:
                # Prefer HNSW with explicit operator class
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_mem_embedding_hnsw ON memory_embedding USING hnsw (embedding vector_l2_ops)"))
                conn.commit()
                logger.info("✅ HNSW index ensured on memory_embedding(embedding vector_l2_ops)")
            except Exception as e:
                logger.warning(f"Could not create HNSW index, falling back to IVFFLAT: {e}")
                try:
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_mem_embedding_ivfflat ON memory_embedding USING ivfflat (embedding vector_l2_ops) WITH (lists = 100)"))
                    conn.commit()
                    logger.info("✅ IVFFLAT index ensured on memory_embedding(embedding vector_l2_ops)")
                except Exception as e2:
                    logger.warning(f"Could not create IVFFLAT index: {e2}")
except Exception as e:
    logger.warning(f"HNSW index ensure failed: {e}")

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
    parent_id: Optional[str] = None

class FolderUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[str] = None

class FolderResponse(BaseModel):
    id: str
    name: str
    parent_id: Optional[str] = None
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

class ReminderUpdate(BaseModel):
    title: str = None
    description: str = None
    reminder_time: str = None
    is_completed: bool = None

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
    duration_minutes: int = None  # Optional for backward compatibility
    duration_seconds: int = None  # New field for seconds precision

class TimerResponse(BaseModel):
    id: str
    title: str
    duration_minutes: int
    start_time: str
    end_time: str
    is_active: bool
    is_completed: bool
    created_at: str

class CalendarEventCreate(BaseModel):
    title: str
    description: str = ""
    start_time: str  # ISO format datetime string
    end_time: str    # ISO format datetime string
    location: Optional[str] = None
    all_day: Optional[bool] = False
    reminder_minutes: Optional[int] = None

class CalendarEventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[str] = None
    all_day: Optional[bool] = None
    reminder_minutes: Optional[int] = None
    is_completed: Optional[bool] = None

class CalendarEventResponse(BaseModel):
    id: str
    title: str
    description: str
    start_time: str
    end_time: str
    location: Optional[str] = None
    all_day: bool
    reminder_minutes: Optional[int] = None
    is_completed: bool
    # iOS calendar sync fields
    source: str = "sara"
    ios_event_id: Optional[str] = None
    ios_calendar_id: Optional[str] = None
    ios_calendar_name: Optional[str] = None
    read_only: bool = False
    created_at: str
    updated_at: str

# iOS Calendar Sync models
class IOSCalendarEventSync(BaseModel):
    ios_event_id: str
    ios_calendar_id: str
    ios_calendar_name: str
    title: str
    description: Optional[str] = None
    start_time: str
    end_time: str
    location: Optional[str] = None
    all_day: bool = False

class IOSCalendarSyncRequest(BaseModel):
    events: list[IOSCalendarEventSync]

class IOSCalendarSyncResponse(BaseModel):
    synced: int
    errors: int

class UserSettings(BaseModel):
    theme: Optional[str] = "dark"
    notifications_enabled: Optional[bool] = True
    language: Optional[str] = "en"
    timezone: Optional[str] = "America/New_York"

class ImageContent(BaseModel):
    """Image content for multimodal messages"""
    type: str = "image"
    data: str  # Base64 encoded image data
    media_type: str = "image/jpeg"  # e.g., "image/jpeg", "image/png"

class TextContent(BaseModel):
    """Text content for multimodal messages"""
    type: str = "text"
    text: str

class ChatMessage(BaseModel):
    role: str
    content: Union[str, List[Dict[str, Any]]]  # Support both text-only and multimodal

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

# Episode-based conversation models
class EpisodeMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    created_at: str
    importance: Optional[float] = None

class ConversationSummaryResponse(BaseModel):
    conversation_id: str
    first_message: str
    message_count: int
    last_activity: str
    created_at: str

class SetActiveConversationRequest(BaseModel):
    conversation_id: Optional[str] = None

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
    triggered_by: str
    execution_time_ms: int
    insights_generated: int
    errors_encountered: Optional[list]
    episodes_analyzed: int
    notes_analyzed: int
    patterns_found: Optional[Dict[str, Any]]
    executed_at: datetime

# Auth utilities - imported from app.core.auth
# pwd_context, create_access_token, verify_token, get_cookie_domain imported at top

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
        self.client = httpx.AsyncClient(timeout=120.0)
        self.event_queue = None
        self._citations = set()
        self._token_usage_callback = None

    def _get_anthropic_headers(self):
        """Get headers for Anthropic API requests with prompt caching enabled"""
        # Use ANTHROPIC_API_KEY if set, otherwise fall back to OPENAI_API_KEY
        api_key = ANTHROPIC_API_KEY if ANTHROPIC_API_KEY else OPENAI_API_KEY
        if not api_key or api_key == "dummy" or api_key.startswith("AIza"):
            logger.error("❌ No valid Anthropic API key configured! Set ANTHROPIC_API_KEY environment variable.")
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31",
            "content-type": "application/json"
        }

    def _convert_openai_messages_to_anthropic(self, messages: list) -> list:
        """Convert OpenAI-format messages to Anthropic format, handling tool calls/results and vision"""
        from app.core.vision_formatters import AnthropicVisionFormatter, has_vision_content

        anthropic_messages = []
        pending_tool_results = []
        vision_formatter = AnthropicVisionFormatter()

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")

            if role == "system":
                # System messages are handled separately
                continue
            elif role == "tool":
                # Tool result - collect for next user message
                tool_content = content
                # Handle multimodal content in tool results (extract text only)
                if isinstance(content, list):
                    tool_content = " ".join(
                        c.get("text", "") for c in content if c.get("type") == "text"
                    )
                pending_tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id"),
                    "content": tool_content or ""
                })
            elif role == "assistant":
                # Check if this has tool_calls (OpenAI format)
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    # Convert to Anthropic format with tool_use blocks
                    content_blocks = []
                    if content:
                        if isinstance(content, str):
                            content_blocks.append({"type": "text", "text": content})
                        elif isinstance(content, list):
                            # Multimodal content - extract text only for assistant
                            text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                            if text_parts:
                                content_blocks.append({"type": "text", "text": " ".join(text_parts)})
                    for tc in tool_calls:
                        func = tc.get("function", {})
                        try:
                            args = json.loads(func.get("arguments", "{}"))
                        except (json.JSONDecodeError, TypeError) as e:
                            logger.debug(f"Failed to parse function arguments: {e}")
                            args = {}
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc.get("id"),
                            "name": func.get("name"),
                            "input": args
                        })
                    anthropic_messages.append({"role": "assistant", "content": content_blocks})
                else:
                    # Regular assistant message
                    if isinstance(content, list):
                        # Extract text only
                        text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                        anthropic_messages.append({"role": "assistant", "content": " ".join(text_parts) or ""})
                    else:
                        anthropic_messages.append({"role": "assistant", "content": content or ""})
            elif role == "user":
                # Handle multimodal content (images + text)
                if isinstance(content, list) and has_vision_content(content):
                    # Format images for Anthropic
                    formatted_content = vision_formatter.format_message_content(content)
                    if pending_tool_results:
                        # Merge tool results with formatted content
                        content_blocks = pending_tool_results.copy() + formatted_content
                        anthropic_messages.append({"role": "user", "content": content_blocks})
                        pending_tool_results = []
                    else:
                        anthropic_messages.append({"role": "user", "content": formatted_content})
                elif pending_tool_results:
                    # Standard text with pending tool results
                    content_blocks = pending_tool_results.copy()
                    if content:
                        if isinstance(content, str):
                            content_blocks.append({"type": "text", "text": content})
                        elif isinstance(content, list):
                            # Extract text from list format
                            for c in content:
                                if c.get("type") == "text":
                                    content_blocks.append({"type": "text", "text": c.get("text", "")})
                    anthropic_messages.append({"role": "user", "content": content_blocks})
                    pending_tool_results = []
                else:
                    # Standard text content
                    if isinstance(content, list):
                        # No images, just extract text
                        text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                        anthropic_messages.append({"role": "user", "content": " ".join(text_parts) or ""})
                    else:
                        anthropic_messages.append({"role": "user", "content": content or ""})

        # If there are leftover tool results, add them as a user message
        if pending_tool_results:
            anthropic_messages.append({"role": "user", "content": pending_tool_results})

        return anthropic_messages

    async def _anthropic_chat_request(self, messages: list, tools: list = None, max_tokens: int = 4096, temperature: float = 0.7):
        """Make a chat request to Anthropic Claude API and convert response to OpenAI format"""
        # Extract system message and convert messages to Anthropic format
        system_content = None
        for msg in messages:
            if msg.get("role") == "system":
                system_content = msg.get("content", "")
                break

        filtered_messages = self._convert_openai_messages_to_anthropic(messages)

        # Build Anthropic request payload with prompt caching
        payload = {
            "model": OPENAI_MODEL,
            "messages": filtered_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # Use system array format with cache_control for prompt caching
        if system_content:
            payload["system"] = [
                {
                    "type": "text",
                    "text": system_content,
                    "cache_control": {"type": "ephemeral"}  # Cache for 5 minutes
                }
            ]

        # Convert OpenAI tools format to Anthropic format if tools are provided
        if tools:
            anthropic_tools = []
            for tool in tools:
                if tool.get("type") == "function":
                    func = tool.get("function", {})
                    anthropic_tools.append({
                        "name": func.get("name"),
                        "description": func.get("description", ""),
                        "input_schema": func.get("parameters", {"type": "object", "properties": {}})
                    })
            if anthropic_tools:
                # Add cache_control to the last tool to cache the entire tools array
                anthropic_tools[-1]["cache_control"] = {"type": "ephemeral"}
                payload["tools"] = anthropic_tools
                payload["tool_choice"] = {"type": "auto"}

        try:
            logger.info(f"Sending chat request to Anthropic API (tools={len(tools) if tools else 0}, messages={len(filtered_messages)})")
            # Debug: log message structure
            for i, msg in enumerate(filtered_messages[:3]):
                content_type = type(msg.get("content")).__name__
                logger.debug(f"  Message {i}: role={msg.get('role')}, content_type={content_type}")

            response = await self.client.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=self._get_anthropic_headers()
            )
            if response.status_code >= 400:
                error_body = response.text
                logger.error(f"Anthropic API error {response.status_code}: {error_body[:1000]}")
                # Also log the message structure that caused the error
                logger.error(f"Messages sent: {json.dumps(filtered_messages, indent=2)[:2000]}")
            response.raise_for_status()
            anthropic_result = response.json()

            # Log cache performance
            usage = anthropic_result.get("usage", {})
            cache_created = usage.get("cache_creation_input_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)

            if cache_read > 0:
                logger.info(f"✅ Anthropic chat completed - Cache HIT: {cache_read} tokens cached, {input_tokens} input, {output_tokens} output")
            elif cache_created > 0:
                logger.info(f"📝 Anthropic chat completed - Cache CREATED: {cache_created} tokens, {input_tokens} input, {output_tokens} output")
            else:
                logger.info(f"Anthropic chat completed - {input_tokens} input, {output_tokens} output")

            # Convert Anthropic response to OpenAI format
            return self._convert_anthropic_to_openai(anthropic_result)

        except httpx.HTTPError as e:
            logger.error(f"HTTP error in Anthropic chat request: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in Anthropic chat request: {e}")
            raise

    def _convert_anthropic_to_openai(self, anthropic_response: dict) -> dict:
        """Convert Anthropic API response to OpenAI-compatible format"""
        # Extract text content from Anthropic response
        content_blocks = anthropic_response.get("content", [])
        text_content = ""
        tool_calls = []

        for i, block in enumerate(content_blocks):
            if block.get("type") == "text":
                text_content += block.get("text", "")
            elif block.get("type") == "tool_use":
                # Convert tool_use to OpenAI tool_calls format
                tool_calls.append({
                    "id": block.get("id"),
                    "type": "function",
                    "function": {
                        "name": block.get("name"),
                        "arguments": json.dumps(block.get("input", {}))
                    }
                })

        # Log token usage for Anthropic
        usage = anthropic_response.get("usage", {})
        if usage:
            self._log_token_usage(
                prompt_tokens=usage.get("input_tokens", 0),
                completion_tokens=usage.get("output_tokens", 0),
                total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                model=OPENAI_MODEL,
                operation_type="chat"
            )

        # Return in OpenAI message format (used by chat_with_tools)
        result = {
            "content": text_content if text_content else None,
            "tool_calls": tool_calls if tool_calls else None
        }
        return result

    def set_token_usage_callback(self, callback):
        """Set the callback function for logging token usage"""
        self._token_usage_callback = callback

    def _log_token_usage(self, prompt_tokens: int, completion_tokens: int, total_tokens: int, model: str, operation_type: str = "chat"):
        """Log token usage via callback"""
        logger.info(f"📊 _log_token_usage called: {total_tokens} tokens ({prompt_tokens} prompt, {completion_tokens} completion) for {model}/{operation_type}")
        if self._token_usage_callback:
            try:
                self._token_usage_callback(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    model=model,
                    operation_type=operation_type
                )
                logger.info(f"📊 Token usage callback executed successfully")
            except Exception as e:
                logger.warning(f"Failed to log token usage: {e}")
        else:
            logger.warning(f"📊 No token usage callback set!")
    
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
                "timestamp": datetime.utcnow().isoformat() + "Z"
            })
    
    def _extract_final_message(self, content: str) -> str:
        """Extract final message from MLX fine-tuned model's channel format.

        MLX models may use format like:
        <|channel|>analysis<|message|>...<|end|><|start|>assistant<|channel|>final<|message|>ACTUAL_RESPONSE

        We want to extract only the content after <|channel|>final<|message|>
        """
        import re

        # Pattern to match: <|channel|>final<|message|> followed by content
        final_pattern = r'<\|channel\|>final<\|message\|>(.+?)(?:<\|end\|>|$)'
        match = re.search(final_pattern, content, re.DOTALL)

        if match:
            extracted = match.group(1).strip()
            logger.info(f"🎯 Extracted final message from MLX format: {len(extracted)} chars")
            return extracted

        # Fallback: if no channel format detected, return original content
        # (this handles non-MLX models)
        return content

    async def _stream_response(self, payload):
        """Stream response from LLM with XML filtering for GLM-4.5 and MLX channel format"""
        import re

        # Route to Anthropic handler if using Claude API (non-streaming for now)
        if is_anthropic_provider():
            logger.info("Using Anthropic Claude API (non-streaming mode)")
            messages = payload.get("messages", [])
            tools = payload.get("tools", [])
            max_tokens = payload.get("max_tokens", 4096)
            temperature = payload.get("temperature", 0.7)

            result = await self._anthropic_chat_request(
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature
            )

            # Emit content as a single chunk for streaming interface compatibility
            if result.get("content"):
                await self.emit_event("text_chunk", {
                    "content": result["content"],
                    "full_content": result["content"]
                })

            return result

        full_content = ""
        emitted_content = ""  # Track what we've already sent to user
        tool_calls = []
        in_analysis_channel = False  # Track if we're in analysis channel (MLX format)
        usage_data = {}  # Track token usage from stream

        # Estimate prompt tokens from payload (for providers that don't return usage)
        payload_str = json.dumps(payload.get("messages", []))
        estimated_prompt_tokens = len(payload_str) // 4  # Rough estimate: 4 chars per token

        try:
            logger.info(f"🔍 Sending to {OPENAI_BASE_URL}/chat/completions with model={payload.get('model')}, keys={list(payload.keys())}")
            if "generativelanguage.googleapis.com" in OPENAI_BASE_URL:
                logger.debug(f"🔍 Gemini payload tools: {len(payload.get('tools', []))} tools")
            async with self.client.stream("POST", f"{OPENAI_BASE_URL}/chat/completions",
                                        json=payload,
                                        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}) as response:
                if response.status_code >= 400:
                    error_body = await response.aread()
                    logger.error(f"❌ API error {response.status_code}: {error_body.decode()}")
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue

                    # OpenAI SSE format uses "data: " prefix
                    if line.startswith("data: "):
                        line = line[6:]  # Remove "data: " prefix

                    # Check for completion marker
                    if line == "[DONE]":
                        break

                    try:
                        chunk = json.loads(line)

                        # Capture usage data if present (some providers send it in final chunk)
                        if "usage" in chunk:
                            usage_data = chunk["usage"]

                        delta = chunk.get("choices", [{}])[0].get("delta", {})

                        # Handle content streaming with XML filtering and MLX channel filtering
                        if "content" in delta and delta["content"]:
                            content_chunk = delta["content"]
                            full_content += content_chunk

                            # Check for MLX channel markers in the full content so far
                            if '<|channel|>analysis' in full_content:
                                in_analysis_channel = True
                            if '<|channel|>final' in full_content:
                                in_analysis_channel = False

                            # Calculate unemitted portion
                            unemitted = full_content[len(emitted_content):]

                            # MLX format: Skip everything until we hit final channel
                            if '<|channel|>' in unemitted or '<|message|>' in unemitted or '<|end|>' in unemitted or '<|start|>' in unemitted:
                                # We're in MLX format - check if we've reached final channel
                                final_marker = '<|channel|>final<|message|>'
                                if final_marker in full_content:
                                    # Extract everything after final marker
                                    final_start = full_content.rindex(final_marker) + len(final_marker)
                                    final_content = full_content[final_start:]

                                    # Only emit what we haven't emitted yet from final content
                                    new_final_content = final_content[len(emitted_content):]
                                    if new_final_content:
                                        emitted_content += new_final_content
                                        await self.emit_event("text_chunk", {
                                            "content": new_final_content,
                                            "full_content": emitted_content
                                        })
                                # Otherwise, skip emitting (we're in analysis or waiting for final)
                                continue

                            # Standard XML filtering (for GLM-4.5 and other models)
                            # Check if we're inside an XML tag or if one is starting
                            # Look for incomplete tags: <tool_call, <think, etc
                            xml_tag_pattern = r'<(tool_call|think)(?:\s|>|$)'
                            tag_match = re.search(xml_tag_pattern, unemitted)

                            if tag_match:
                                # Found start of XML tag - only emit content before it
                                safe_content = unemitted[:tag_match.start()]
                                if safe_content:
                                    emitted_content += safe_content
                                    await self.emit_event("text_chunk", {
                                        "content": safe_content,
                                        "full_content": emitted_content
                                    })
                            else:
                                # Check if we might be at the start of a tag (e.g., just got "<")
                                if unemitted and not unemitted.rstrip().endswith('<'):
                                    # Safe to emit - no XML tag detected
                                    emitted_content += unemitted
                                    await self.emit_event("text_chunk", {
                                        "content": unemitted,
                                        "full_content": emitted_content
                                    })
                                # Otherwise, hold the buffer (might be start of XML tag)

                        # Handle tool calls (standard OpenAI format)
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

            # After streaming completes, process content based on format
            processed_content = full_content

            # Check for GLM-4.5 XML tool calls
            if "<tool_call>" in full_content or "<think>" in full_content:
                logger.info("Detected GLM-4.5 XML format, parsing tool calls...")
                cleaned_content, parsed_tool_calls = parse_glm45_tool_calls(full_content)

                # Merge with any JSON tool calls from streaming (in case both formats present)
                all_tool_calls = parsed_tool_calls if parsed_tool_calls else []
                if tool_calls:
                    all_tool_calls.extend(tool_calls)

                # Log token usage for GLM-4.5 format
                estimated_completion_tokens = len(full_content) // 4
                estimated_total = estimated_prompt_tokens + estimated_completion_tokens
                self._log_token_usage(
                    prompt_tokens=estimated_prompt_tokens,
                    completion_tokens=estimated_completion_tokens,
                    total_tokens=estimated_total,
                    model=payload.get("model", OPENAI_MODEL),
                    operation_type="chat"
                )

                return {
                    "content": cleaned_content,
                    "tool_calls": all_tool_calls if all_tool_calls else None
                }

            # Check for MLX channel format and extract final message
            if '<|channel|>' in full_content:
                logger.info("Detected MLX channel format, extracting final message...")
                processed_content = self._extract_final_message(full_content)

            # Check for JSON text tool calls (LLM outputting tool calls as text instead of proper format)
            # This handles models that don't properly use the tool_calls field
            if not tool_calls and processed_content:
                json_cleaned, json_tool_calls = parse_json_text_tool_calls(processed_content)
                if json_tool_calls:
                    logger.info(f"📋 Parsed {len(json_tool_calls)} tool calls from JSON text content")
                    processed_content = json_cleaned
                    tool_calls = json_tool_calls

            # Debug logging for empty responses
            logger.info(f"🔍 _stream_response complete - full_content length: {len(full_content)}, emitted_content length: {len(emitted_content)}, processed length: {len(processed_content)}")
            if len(full_content) == 0:
                logger.warning("⚠️ LLM returned empty full_content!")
            if len(emitted_content) > 0 and len(full_content) > len(emitted_content):
                logger.warning(f"⚠️ Content was filtered: full={len(full_content)} vs emitted={len(emitted_content)}")

            # Log token usage
            if usage_data:
                # Use actual usage data from provider
                self._log_token_usage(
                    prompt_tokens=usage_data.get("prompt_tokens", 0),
                    completion_tokens=usage_data.get("completion_tokens", 0),
                    total_tokens=usage_data.get("total_tokens", 0),
                    model=payload.get("model", OPENAI_MODEL),
                    operation_type="chat"
                )
            else:
                # Estimate tokens from content length
                estimated_completion_tokens = len(full_content) // 4
                estimated_total = estimated_prompt_tokens + estimated_completion_tokens
                self._log_token_usage(
                    prompt_tokens=estimated_prompt_tokens,
                    completion_tokens=estimated_completion_tokens,
                    total_tokens=estimated_total,
                    model=payload.get("model", OPENAI_MODEL),
                    operation_type="chat"
                )

            # Return message object compatible with existing code (standard OpenAI format)
            return {
                "content": processed_content,
                "tool_calls": tool_calls if tool_calls else None
            }

        except Exception as e:
            logger.error(f"Streaming error: {e}")
            # Try to get response body for more details
            if hasattr(e, 'response'):
                try:
                    error_body = e.response.read()
                    logger.error(f"Error response body: {error_body}")
                except Exception as read_err:
                    logger.debug(f"Could not read error response body: {read_err}")

            # Don't retry on rate limit errors - fail fast
            if "429" in str(e) or "Too Many Requests" in str(e):
                logger.warning("⚠️ Rate limit exceeded - not retrying to avoid quota burn")
                return {
                    "content": "I'm temporarily rate limited. Please wait a moment and try again.",
                    "tool_calls": None
                }

            # Fallback to non-streaming for other errors
            payload_fallback = payload.copy()
            payload_fallback.pop("stream", None)

            response = await self.client.post(
                f"{OPENAI_BASE_URL}/chat/completions",
                json=payload_fallback,
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]
    
    async def chat(self, messages: list):
        try:
            # Handle both dict and object message formats
            formatted_messages = []
            for m in messages:
                if isinstance(m, dict):
                    formatted_messages.append({"role": m["role"], "content": m["content"]})
                else:
                    formatted_messages.append({"role": m.role, "content": m.content})

            # Route to Anthropic handler if using Claude API
            if is_anthropic_provider():
                result = await self._anthropic_chat_request(
                    messages=formatted_messages,
                    tools=None,
                    max_tokens=8000,
                    temperature=0.7
                )
                return result.get("content", "")

            # Build payload for OpenAI-compatible API
            chat_payload = {
                "model": OPENAI_MODEL,
                "messages": formatted_messages,
                "temperature": 0.7,
                "max_tokens": 8000
            }

            # Add Ollama-specific context length if using local model
            if "ollama" in OPENAI_BASE_URL.lower() or "11434" in OPENAI_BASE_URL:
                chat_payload["num_ctx"] = 65536  # 65k context window for gpt-oss:120b

            response = await self.client.post(
                f"{OPENAI_BASE_URL}/chat/completions",
                json=chat_payload,
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}
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
            logger.info(f"🔧 chat_with_tools called with conversation_id: {conversation_id}")

            # Generate conversation_id immediately if not provided
            if not conversation_id:
                conversation_id = str(uuid.uuid4())
                logger.info(f"🆕 Generated NEW conversation_id: {conversation_id}")
            else:
                logger.info(f"♻️  Reusing existing conversation_id: {conversation_id}")

            # Store it immediately so it's available for the final_response
            self.current_conversation_id = conversation_id

            logger.info(f"LLM chat_with_tools called with {len(messages)} messages, {len(tools)} tools for user {user_id}")

            # Initialize session cache
            from app.services.session_cache import SessionToolCache
            from app.core.config import settings
            import redis

            redis_client = redis.from_url(settings.redis_url)
            session_cache = SessionToolCache(redis_client, ttl_minutes=30)

            # Handle both dict and object message formats
            formatted_messages = []
            for msg in messages:
                if isinstance(msg, dict):
                    formatted_messages.append({"role": msg["role"], "content": msg["content"]})
                else:
                    formatted_messages.append({"role": msg.role, "content": msg.content})

            # Build and inject session context reminder
            session_summary = session_cache.get_session_context_summary(conversation_id)
            context_reminder = ""
            if any(session_summary.values()):
                context_lines = ["\n## Session Context (already retrieved this conversation)"]
                if session_summary.get("notes"):
                    context_lines.append(f"**Notes in context:** {', '.join(session_summary['notes'])}")
                if session_summary.get("documents"):
                    context_lines.append(f"**Documents in context:** {', '.join(session_summary['documents'])}")
                if session_summary.get("memories"):
                    context_lines.append(f"**Memories in context:** {', '.join(session_summary['memories'])}")
                if session_summary.get("web_pages"):
                    context_lines.append(f"**Web pages in context:** {', '.join(session_summary['web_pages'])}")
                context_lines.append("\n**Do not re-fetch any of the above. Reference the existing content in our conversation.**\n")
                context_reminder = "\n".join(context_lines)

            # Inject context reminder into first system message
            if context_reminder and len(formatted_messages) > 0 and formatted_messages[0].get("role") == "system":
                formatted_messages[0]["content"] = formatted_messages[0]["content"] + context_reminder

            payload = {
                "model": OPENAI_MODEL,
                "messages": formatted_messages,
                "temperature": 0.7,
                "max_tokens": 8000,
                "stream": True
            }

            # Only include tools and tool_choice if there are actual tools
            # Some providers (e.g., Gemini) don't like empty tools arrays
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"

            # Add Ollama-specific context length if using local model
            if "ollama" in OPENAI_BASE_URL.lower() or "11434" in OPENAI_BASE_URL:
                payload["num_ctx"] = 65536  # 65k context window for gpt-oss:120b

            # Log payload size for debugging context overflow
            import json
            payload_size = len(json.dumps(payload))
            logger.info(f"🔍 Payload size: {payload_size} bytes (~{payload_size//4} tokens)")
            if payload_size > 100000:
                logger.warning(f"⚠️ Large payload detected! {payload_size} bytes may cause context overflow")

            message = await self._stream_response(payload)

            # Handle tool calls with recursive support (max 10 rounds for complex queries)
            max_tool_rounds = 10
            current_messages = formatted_messages
            
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
                        
                        tool_response = await self.execute_tool(tool_call, user_id, conversation_id, session_cache)
                        tool_responses.append(tool_response)
                        
                        await self.emit_event("tool_completed", {
                            "tool": tool_name,
                            "round": round_num + 1
                        })
                    
                    # Add assistant message with tool calls and tool responses
                    # IMPORTANT: llama-server requires "role" field in all messages
                    current_messages.append({
                        "role": "assistant",
                        "content": message.get("content", ""),
                        "tool_calls": message["tool_calls"]
                    })
                    current_messages.extend(tool_responses)
                    
                    # Truncate messages if conversation is getting too long to prevent 500 errors
                    max_messages = 20  # Keep only recent context to prevent payload bloat
                    if len(current_messages) > max_messages:
                        # Keep system message (first) and recent messages
                        # IMPORTANT: Don't truncate in the middle of tool_call/tool_result pairs
                        system_msg = current_messages[0] if current_messages[0].get("role") == "system" else None
                        start_idx = 1 if system_msg else 0

                        # Find a safe truncation point - walk backwards to find a user message
                        # (don't cut after an assistant with tool_calls or after tool responses)
                        cut_point = len(current_messages) - max_messages + 1
                        while cut_point < len(current_messages):
                            msg_at_cut = current_messages[cut_point]
                            # Safe to cut before a user message (but not a tool response)
                            if msg_at_cut.get("role") == "user":
                                break
                            # Not safe to cut before assistant with tool_calls or tool responses
                            cut_point += 1

                        # If we couldn't find a safe cut point, just keep all messages
                        if cut_point >= len(current_messages) - 2:
                            logger.warning(f"⚠️ Could not find safe truncation point, keeping all {len(current_messages)} messages")
                        else:
                            truncated_messages = ([system_msg] if system_msg else []) + current_messages[cut_point:]
                            logger.info(f"⚠️ Truncated conversation from {len(current_messages)} to {len(truncated_messages)} messages")
                            current_messages = truncated_messages
                    
                    # Emit thinking event
                    await self.emit_event("thinking", {
                        "round": round_num + 1,
                        "status": "processing_tools"
                    })

                    # Make follow-up request with streaming (with retry logic)
                    follow_up_payload = {
                        "model": OPENAI_MODEL,
                        "messages": current_messages,
                        "temperature": 0.7,
                        "max_tokens": 8000,
                        "tools": tools,
                        "stream": True
                    }

                    # Debug: Log the assistant message and tool responses being sent
                    if current_messages:
                        for i, msg in enumerate(current_messages[-5:]):  # Last 5 messages
                            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                                for tc in msg["tool_calls"]:
                                    logger.info(f"🔍 Follow-up msg[{i}] tool_call args: {repr(tc.get('function', {}).get('arguments', ''))[:100]}")
                            elif msg.get("role") == "tool":
                                logger.info(f"🔍 Follow-up msg[{i}] tool response: {repr(msg.get('content', ''))[:100]}")

                    # Retry logic for JSONDecodeError
                    max_retries = 2
                    message = None
                    last_error = None

                    for retry_attempt in range(max_retries + 1):
                        try:
                            message = await self._stream_response(follow_up_payload)
                            # Success - break out of retry loop
                            if retry_attempt > 0:
                                logger.info(f"✅ Retry {retry_attempt} succeeded for follow-up LLM call")
                            break
                        except json.JSONDecodeError as e:
                            last_error = e
                            logger.warning(f"⚠️ JSONDecodeError on attempt {retry_attempt + 1}/{max_retries + 1}: {e}")
                            if retry_attempt < max_retries:
                                logger.info(f"🔄 Retrying follow-up LLM call (attempt {retry_attempt + 2}/{max_retries + 1})...")
                                await asyncio.sleep(0.5)  # Brief delay before retry
                            else:
                                # All retries failed - synthesize a completion response from tool results
                                logger.warning(f"❌ All {max_retries + 1} attempts failed. Synthesizing completion from tool results.")
                                # Build a summary from tool responses
                                tool_summary = []
                                for tr in tool_responses:
                                    if tr.get("content"):
                                        tool_summary.append(str(tr["content"])[:200])
                                completion_msg = "I've completed the requested actions:\n" + "\n".join(tool_summary[:3])
                                message = {
                                    "content": completion_msg,
                                    "tool_calls": None
                                }
                        except Exception as e:
                            # Other errors should be caught but not crash - fallback to tool results
                            logger.error(f"❌ Unexpected error during LLM call: {e}")
                            # Create a fallback message from tool results
                            tool_summary = []
                            for tr in tool_responses:
                                if tr.get("content"):
                                    tool_summary.append(str(tr["content"])[:200])
                            completion_msg = "I've completed the requested actions:\n" + "\n".join(tool_summary[:3])
                            message = {
                                "content": completion_msg,
                                "tool_calls": None
                            }
                            break  # Exit retry loop

                    if message is None:
                        # Fallback if something went wrong
                        logger.error("Failed to get message after retries")
                        message = {
                            "content": "Tool execution completed successfully.",
                            "tool_calls": None
                        }
                    
                    # Enhanced debugging
                    logger.info(f"🔍 Round {round_num + 1} - Message keys: {list(message.keys())}")
                    logger.info(f"🔍 Round {round_num + 1} - Content length: {len(message.get('content', '')) if message.get('content') else 0}")
                    logger.info(f"🔍 Round {round_num + 1} - Content preview: {repr(message.get('content', ''))[:100]}")
                    logger.info(f"🔍 Round {round_num + 1} - Has tool_calls: {bool(message.get('tool_calls'))}")
                    if message.get('tool_calls'):
                        logger.info(f"🔍 Round {round_num + 1} - Tool calls: {[tc.get('function', {}).get('name') for tc in message.get('tool_calls', [])]}")
                    if hasattr(message, 'reasoning'):
                        logger.info(f"🔍 Round {round_num + 1} - Reasoning: {message.get('reasoning', '')[:100]}")

                    # FALLBACK: If model returns empty content with another tool call after round 1,
                    # it's stuck in a loop. Synthesize response from tool results.
                    if round_num >= 1 and message.get("tool_calls") and not message.get("content", "").strip():
                        logger.warning(f"⚠️ Model returned empty content with tool calls in round {round_num + 1}. Synthesizing response from previous tool results.")
                        # Build response from the tool results we just got
                        tool_summary_parts = []
                        for tr in tool_responses:
                            content = tr.get("content", "")
                            if content:
                                # Parse tool response to extract useful info
                                if isinstance(content, str):
                                    if len(content) > 300:
                                        tool_summary_parts.append(content[:300] + "...")
                                    else:
                                        tool_summary_parts.append(content)

                        if tool_summary_parts:
                            synthesized_response = "Based on what I found:\n\n" + "\n\n".join(tool_summary_parts[:2])
                        else:
                            synthesized_response = "I found some relevant information but had trouble formatting the response. Could you try rephrasing your question?"

                        logger.info(f"✅ Synthesized response from tool results: {len(synthesized_response)} chars")

                        # Emit synthesized response as streaming chunks
                        await self.emit_event("text_chunk", {
                            "content": synthesized_response,
                            "full_content": synthesized_response
                        })

                        await self.emit_event("response_ready", {
                            "rounds": round_num + 1,
                            "content_length": len(synthesized_response),
                            "synthesized": True
                        })
                        # Store conversation and get episode_id for rating
                        episode_id = await self.store_conversation(messages, synthesized_response, user_id, conversation_id)
                        self.current_episode_id = episode_id
                        return synthesized_response

                    # If no more tool calls, we're done
                    if not message.get("tool_calls"):
                        response_content = message["content"]
                        await self.emit_event("response_ready", {
                            "rounds": round_num + 1,
                            "content_length": len(response_content) if response_content else 0
                        })
                        # Store conversation and get episode_id for rating
                        episode_id = await self.store_conversation(messages, response_content, user_id, conversation_id)
                        self.current_episode_id = episode_id
                        logger.info(f"Final LLM response after {round_num + 1} rounds: {len(response_content) if response_content else 0}")
                        return response_content
                else:
                    # No tool calls, return the content
                    response_content = message["content"]
                    await self.emit_event("response_ready", {
                        "rounds": 1,
                        "content_length": len(response_content) if response_content else 0
                    })
                    # Store conversation and get episode_id for rating
                    episode_id = await self.store_conversation(messages, response_content, user_id, conversation_id)
                    self.current_episode_id = episode_id
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

            # Store conversation and get episode_id for rating
            episode_id = await self.store_conversation(messages, response_content, user_id, conversation_id)
            self.current_episode_id = episode_id
            logger.warning(f"Hit max tool rounds, returning: {len(response_content)} chars")
            return response_content

        except Exception as e:
            import traceback
            logger.error(f"LLM error in chat_with_tools: {e}")
            logger.error(f"Full traceback:\n{traceback.format_exc()}")
            return f"I'm sorry, I'm having trouble connecting to my AI service. Error: {str(e)}"

    async def execute_tool(self, tool_call, user_id, conversation_id=None, session_cache=None):
        """Execute a tool call and return the response"""
        function_name = tool_call["function"]["name"]
        args_str = tool_call["function"]["arguments"]
        logger.info(f"🔧 Tool {function_name} - raw arguments string: {repr(args_str)[:200]}")

        # Handle empty arguments string from malformed tool calls
        if not args_str or args_str.strip() == "":
            logger.warning(f"⚠️ Empty arguments for {function_name}, using empty dict")
            arguments = {}
        else:
            try:
                arguments = json.loads(args_str)
            except json.JSONDecodeError as e:
                # Gemini sometimes concatenates multiple JSON objects like: {"a":1}{"b":2}
                # Try to extract just the first valid JSON object
                logger.warning(f"⚠️ Failed to parse arguments for {function_name}: {e}")
                logger.warning(f"   Raw args: {repr(args_str)}")

                # Try to fix common Gemini malformed JSON issues
                fixed = False

                # Pattern 1: Multiple concatenated objects {"a":1}{"b":2} - take the first one
                if args_str.count('{') > 1 and '}{' in args_str:
                    try:
                        # Find the first complete JSON object
                        depth = 0
                        end_idx = 0
                        for i, c in enumerate(args_str):
                            if c == '{':
                                depth += 1
                            elif c == '}':
                                depth -= 1
                                if depth == 0:
                                    end_idx = i + 1
                                    break
                        if end_idx > 0:
                            first_obj = args_str[:end_idx]
                            arguments = json.loads(first_obj)
                            # IMPORTANT: Also fix the tool_call object so follow-up requests have valid JSON
                            tool_call["function"]["arguments"] = first_obj
                            logger.info(f"✅ Fixed malformed JSON by extracting first object: {first_obj}")
                            fixed = True
                    except (json.JSONDecodeError, Exception) as e:
                        logger.debug(f"JSON fix attempt (first object) failed: {e}")

                # Pattern 2: Trailing garbage after valid JSON
                if not fixed:
                    try:
                        # Try parsing incrementally
                        import re
                        match = re.match(r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})', args_str)
                        if match:
                            fixed_json = match.group(1)
                            arguments = json.loads(fixed_json)
                            # IMPORTANT: Also fix the tool_call object so follow-up requests have valid JSON
                            tool_call["function"]["arguments"] = fixed_json
                            logger.info(f"✅ Fixed malformed JSON with regex extraction: {fixed_json}")
                            fixed = True
                    except (json.JSONDecodeError, Exception) as e:
                        logger.debug(f"JSON fix attempt (regex extraction) failed: {e}")

                if not fixed:
                    logger.error(f"❌ Could not fix malformed arguments for {function_name}")
                    return {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": json.dumps({
                            "success": False,
                            "message": f"Invalid tool arguments: {str(e)}",
                            "data": None
                        })
                    }

        logger.info(f"Executing tool {function_name} with arguments: {arguments}")

        # CHECK CACHE FIRST
        cached_result = None
        if session_cache and conversation_id:
            cached_result = session_cache.get(conversation_id, function_name, arguments)
            if cached_result:
                return {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": cached_result + "\n\n[Retrieved from session cache - already fetched this conversation]"
                }
        
        if function_name == "search_notes":
            result = await self.search_notes_tool(arguments["query"], user_id, arguments.get("folder_name"))
        elif function_name == "create_note":
            result = await self.create_note_tool(arguments.get("title", ""), arguments["content"], user_id, arguments.get("folder_name"))
        elif function_name == "list_notes":
            result = await self.list_notes_tool(user_id)
        elif function_name == "list_folders":
            result = await self.list_folders_tool(user_id)
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
        elif function_name == "handoff_to_agents":
            result = await self.handoff_to_agents_tool(
                arguments["task_description"],
                arguments.get("task_type", "research"),
                user_id
            )
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

                # Emit canvas_command SSE event for immediate UI update
                if reg_result.success and reg_result.data and isinstance(reg_result.data, dict):
                    canvas_command = reg_result.data.get("canvas_command")
                    if canvas_command:
                        await self.emit_event("canvas_command", reg_result.data)
                        logger.info(f"📐 Emitted canvas_command: {canvas_command}")

                result = json.dumps({
                    "success": reg_result.success,
                    "message": reg_result.message,
                    "data": reg_result.data
                })
            except Exception as e:
                result = f"Unknown tool: {function_name} ({e})"
        
        # STORE IN CACHE
        if session_cache and conversation_id:
            session_cache.set(conversation_id, function_name, arguments, str(result))

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

    async def search_notes_tool(self, query, user_id, folder_name=None):
        """Search notes using Neo4j knowledge graph (with PostgreSQL fallback)"""
        neo4j_failed = False
        folder_filter_info = ""
        folder_id = None

        # Resolve folder name to folder_id if provided
        if folder_name:
            try:
                db_check = SessionLocal()
                try:
                    folder = db_check.query(Folder).filter(
                        Folder.user_id == user_id,
                        Folder.name.ilike(folder_name)
                    ).first()
                    if folder:
                        folder_id = folder.id
                        folder_filter_info = f" in folder '{folder.name}'"
                    else:
                        folder_filter_info = f" (folder '{folder_name}' not found, searching all)"
                finally:
                    db_check.close()
            except Exception as e:
                logger.warning(f"Error resolving folder: {e}")

        # Try Neo4j search first (Neo4j doesn't have folder info, so fall through to PostgreSQL if filtering)
        if not folder_id:
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
                        return "\n\n".join(results) + folder_filter_info
                    elif search_results is not None:  # Empty list means no results found
                        return f"No notes found matching your query{folder_filter_info}."
            except Exception as e:
                logger.warning(f"Neo4j search failed, falling back to PostgreSQL: {e}")
                neo4j_failed = True

        # Fallback to PostgreSQL (or primary if folder filtering)
        try:
            db = SessionLocal()
            try:
                # Normalize query - remove spaces for fuzzy matching
                normalized_query = query.replace(" ", "")

                # Search both title and content, with fuzzy matching on title
                from sqlalchemy import or_, func
                query_filter = db.query(Note).filter(
                    Note.user_id == user_id,
                    or_(
                        Note.title.ilike(f"%{query}%"),  # Exact match
                        func.replace(Note.title, ' ', '').ilike(f"%{normalized_query}%"),  # Without spaces
                        Note.content.ilike(f"%{query}%")  # Content search
                    )
                )

                # Apply folder filter if specified
                if folder_id:
                    query_filter = query_filter.filter(Note.folder_id == folder_id)

                notes = query_filter.limit(5).all()

                if not notes:
                    return f"No notes found matching your query{folder_filter_info}."

                results = []
                for note in notes:
                    folder_label = ""
                    if note.folder_id and not folder_id:  # Show folder info if not filtering by folder
                        note_folder = db.query(Folder).filter(Folder.id == note.folder_id).first()
                        if note_folder:
                            folder_label = f" [📁 {note_folder.name}]"
                    results.append(f"Note: {note.title or 'Untitled'}{folder_label}\nContent: {note.content[:200]}...")

                fallback_notice = " (via PostgreSQL)" if neo4j_failed or folder_id else ""
                return "\n\n".join(results) + folder_filter_info + fallback_notice
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error searching notes in PostgreSQL: {e}")
            return "Unable to search notes at this time. Please try again later."

    async def create_note_tool(self, title, content, user_id, folder_name=None):
        """Create a new note using Neo4j-first architecture with intelligent processing"""
        note_id = str(__import__('uuid').uuid4())
        folder_id = None
        folder_info = ""

        # Resolve folder name to folder_id if provided
        if folder_name:
            try:
                db_check = SessionLocal()
                try:
                    folder = db_check.query(Folder).filter(
                        Folder.user_id == user_id,
                        Folder.name.ilike(folder_name)
                    ).first()
                    if folder:
                        folder_id = folder.id
                        folder_info = f" in folder '{folder.name}'"
                    else:
                        folder_info = f" (folder '{folder_name}' not found, created at root)"
                finally:
                    db_check.close()
            except Exception as e:
                logger.warning(f"Error resolving folder: {e}")

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
                    content=content,
                    folder_id=folder_id
                )
                db.add(note)
                db.commit()
                db.refresh(note)

                return f"Created note: {note.title or 'Untitled'}{folder_info} (with intelligent graph processing)"
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
                    folder_label = ""
                    if note.folder_id:
                        folder = db.query(Folder).filter(Folder.id == note.folder_id).first()
                        if folder:
                            folder_label = f" [📁 {folder.name}]"
                    content_preview = note.content[:100] + "..." if len(note.content) > 100 else note.content
                    formatted_notes.append(f"• {title}{folder_label} (ID: {note.id})\n  {content_preview}")

                return f"Your notes:\n\n" + "\n\n".join(formatted_notes)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error listing notes: {e}")
            return f"Error listing notes: {str(e)}"

    async def list_folders_tool(self, user_id):
        """List all folders for the user with their hierarchy"""
        try:
            db = SessionLocal()
            try:
                folders = db.query(Folder).filter(Folder.user_id == user_id).order_by(Folder.name).all()
                if not folders:
                    return "You don't have any folders yet. You can ask me to create one!"

                # Build folder hierarchy
                def build_tree(parent_id=None, depth=0):
                    result = []
                    for folder in folders:
                        if folder.parent_id == parent_id:
                            indent = "  " * depth
                            notes_count = db.query(Note).filter(Note.folder_id == folder.id).count()
                            subfolder_count = sum(1 for f in folders if f.parent_id == folder.id)
                            info_parts = []
                            if notes_count > 0:
                                info_parts.append(f"{notes_count} notes")
                            if subfolder_count > 0:
                                info_parts.append(f"{subfolder_count} subfolders")
                            info = f" ({', '.join(info_parts)})" if info_parts else ""
                            result.append(f"{indent}📁 {folder.name}{info}")
                            result.extend(build_tree(folder.id, depth + 1))
                    return result

                tree = build_tree()
                return f"Your folders:\n\n" + "\n".join(tree)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error listing folders: {e}")
            return f"Error listing folders: {str(e)}"

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
                
                reminder.is_completed = True
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
                
                timer.is_active = False
                timer.is_completed = True
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
                except (json.JSONDecodeError, TypeError) as e:
                    logger.debug(f"Failed to parse episode metadata: {e}")
                    emotional_data = {}
                    topics_data = []
                
                # Format timestamp
                try:
                    time_str = episode['created_at'].strftime('%Y-%m-%d %H:%M')
                except (AttributeError, TypeError):
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

    async def handoff_to_agents_tool(self, task_description: str, task_type: str, user_id: str):
        """🔄 Hand off a task to background worker agents for research/analysis"""
        try:
            import asyncio
            from app.services.background_task_service import background_task_service

            logger.info(f"🤖 Handing off task to agents: {task_description[:100]}...")

            # Create the background task
            db = SessionLocal()
            try:
                task = await background_task_service.create_task(
                    db=db,
                    user_id=str(user_id),
                    query=task_description,
                    task_type=task_type
                )

                # Start the task in background (fire and forget)
                asyncio.create_task(self._run_background_task(task.id))

                return json.dumps({
                    "success": True,
                    "message": f"Task handed off to agents successfully",
                    "task_id": task.id,
                    "status": "running",
                    "note": "I'll notify you when the research is complete. Results will be saved to your Agent Workspace folder."
                })
            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error handing off to agents: {e}")
            return json.dumps({
                "success": False,
                "message": f"Failed to hand off task: {str(e)}"
            })

    async def _run_background_task(self, task_id: str):
        """Run a background task in a new database session"""
        try:
            from app.services.background_task_service import background_task_service
            db = SessionLocal()
            try:
                await background_task_service.run_task(db, task_id)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Background task {task_id} failed: {e}")

    async def store_conversation(self, messages, response_content, user_id, conversation_id=None) -> str:
        """Store the conversation in enhanced episodic memory with emotional and topical analysis.
        Returns the episode_id of the assistant response for rating purposes."""
        assistant_episode_id = None
        try:
            logger.info(f"📥 store_conversation called with conversation_id: {conversation_id}")

            # conversation_id should already be set by chat_with_tools
            # This is just a safety check
            if not conversation_id:
                logger.warning("⚠️ store_conversation called without conversation_id, using current_conversation_id")
                conversation_id = self.current_conversation_id or str(uuid.uuid4())

            logger.info(f"✅ Storing conversation with ID: {conversation_id}")
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
                    # Handle both ChatMessage objects and dict formats
                    if isinstance(message, dict):
                        role = message.get("role")
                        content = message.get("content")
                    else:
                        role = message.role
                        content = message.content

                    if role in ["user", "assistant"] and content and content not in existing_content:
                        await intelligent_memory_service.store_episode(
                            user_id=user_id,
                            role=role,
                            content=content,
                            conversation_id=conversation_id,
                            source="chat",
                            memory_type="conversation"
                        )
            finally:
                db.close()

            # Store assistant response as an episode (only if not already stored)
            if response_content and response_content not in existing_content:
                episode = await intelligent_memory_service.store_episode(
                    user_id=user_id,
                    role="assistant",
                    content=response_content,
                    conversation_id=conversation_id,
                    source="chat",
                    memory_type="conversation"
                )
                assistant_episode_id = episode.id if episode else None
                logger.info(f"🎯 Assistant episode stored with ID: {assistant_episode_id}")

            # Also maintain legacy conversation storage for compatibility
            await self._store_legacy_conversation(messages, response_content, user_id, conversation_id)

            logger.info(f"🧠 Stored conversation {conversation_id} with intelligent episodic memory analysis")

        except Exception as e:
            logger.error(f"Error storing conversation in enhanced memory: {e}")

        return assistant_episode_id
    
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

    async def detect_session_gap(self, user_id: str, db: Session) -> tuple[bool, datetime | None]:
        """
        Check if there's been >45 min since last message.
        Returns: (has_gap, last_message_time)
        """
        try:
            last_episode = db.query(Episode).filter(
                Episode.user_id == user_id
            ).order_by(Episode.created_at.desc()).first()

            if not last_episode:
                return False, None

            time_gap = (datetime.utcnow() - last_episode.created_at).total_seconds()
            has_gap = time_gap > 2700  # 45 minutes in seconds

            return has_gap, last_episode.created_at
        except Exception as e:
            logger.error(f"Error detecting session gap: {e}")
            return False, None

    async def summarize_session(self, user_id: str, start_time: datetime, end_time: datetime, db: Session) -> str | None:
        """Generate concise 2-3 sentence summary of conversation session"""
        try:
            # Get episodes in time range
            episodes = db.query(Episode).filter(
                Episode.user_id == user_id,
                Episode.created_at >= start_time,
                Episode.created_at <= end_time,
                Episode.role.in_(["user", "assistant"])
            ).order_by(Episode.created_at.asc()).all()

            # Skip summarization if session is too short
            if len(episodes) < 3:
                logger.info(f"Skipping summarization for short session ({len(episodes)} messages)")
                return None

            # Combine into conversation format
            conversation_lines = []
            for ep in episodes:
                role_prefix = "User:" if ep.role == "user" else "Sara:"
                conversation_lines.append(f"{role_prefix} {ep.content}")

            conversation_text = "\n".join(conversation_lines)

            # Use fast model for summarization to minimize latency
            summary_prompt = f"""Summarize this conversation in 2-3 concise sentences:

{conversation_text}

Focus on: key topics discussed, decisions made, tasks mentioned, important context.
Keep it brief and factual."""

            # Use FAST_MODEL if available, otherwise use main model
            fast_model_url = os.getenv("FAST_MODEL_URL") or OPENAI_BASE_URL
            fast_model = os.getenv("FAST_MODEL", "gpt-oss:20b")

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{fast_model_url}/chat/completions",
                    json={
                        "model": fast_model,
                        "messages": [{"role": "user", "content": summary_prompt}],
                        "temperature": 0.3,
                        "max_tokens": 200
                    }
                )
                response.raise_for_status()
                result = response.json()
                summary = result["choices"][0]["message"]["content"].strip()

                logger.info(f"✅ Generated session summary: {summary[:100]}...")
                return summary

        except Exception as e:
            logger.error(f"Error summarizing session: {e}")
            return None

    async def store_session_summary(self, user_id: str, summary: str, timestamp: datetime):
        """Store session summary in Redis with 24hr TTL"""
        try:
            from redis.asyncio import Redis
            redis = Redis.from_url(config.settings.redis_url, encoding="utf-8", decode_responses=True)

            date_key = timestamp.strftime("%Y-%m-%d")
            session_time = timestamp.strftime("%H:%M")

            # Key format: session_summary:user_id:date
            redis_key = f"session_summary:{user_id}:{date_key}"

            # Store as JSON list of sessions
            existing_summaries = await redis.get(redis_key)
            summaries = json.loads(existing_summaries) if existing_summaries else []

            summaries.append({
                "time": session_time,
                "summary": summary,
                "timestamp": timestamp.isoformat()
            })

            await redis.set(redis_key, json.dumps(summaries), ex=86400)  # 24 hour TTL
            await redis.close()

            logger.info(f"✅ Stored session summary in Redis for {date_key} at {session_time}")

        except Exception as e:
            logger.error(f"Error storing session summary in Redis: {e}")

    async def get_todays_context(self, user_id: str) -> str:
        """Retrieve today's session summaries from Redis"""
        try:
            from redis.asyncio import Redis
            redis = Redis.from_url(config.settings.redis_url, encoding="utf-8", decode_responses=True)

            today = datetime.utcnow().strftime("%Y-%m-%d")
            redis_key = f"session_summary:{user_id}:{today}"

            summaries_json = await redis.get(redis_key)
            await redis.close()

            if not summaries_json:
                return ""

            summaries = json.loads(summaries_json)

            if not summaries:
                return ""

            context = "\n\n## Earlier Today:\n"
            for session in summaries:
                context += f"[{session['time']}] {session['summary']}\n"

            logger.info(f"✅ Retrieved {len(summaries)} session summaries for today")
            return context

        except Exception as e:
            logger.error(f"Error retrieving today's context from Redis: {e}")
            return ""

    async def generate_conversation_title(self, conversation_id, db):
        """Generate a descriptive title for the conversation (only once)"""
        try:
            # Check if conversation already has a title
            conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
            if not conversation:
                return

            # Skip if title already exists and is not empty
            if conversation.title and conversation.title.strip():
                logger.debug(f"Conversation {conversation_id} already has title: '{conversation.title}', skipping")
                return

            logger.debug(f"Generating title for conversation {conversation_id} (current title: '{conversation.title}')")

            # Get only the FIRST user message to generate a title
            turns = db.query(ConversationTurn).filter(
                ConversationTurn.conversation_id == conversation_id,
                ConversationTurn.role == "user"
            ).order_by(ConversationTurn.message_index).limit(1).all()

            if not turns:
                return

            # Use only the first message as the title
            first_message = turns[0].content

            # Generate a short title (keep it simple for now)
            if len(first_message) > 100:
                title = first_message[:97] + "..."
            else:
                title = first_message

            # Update the conversation with the title
            conversation.title = title
            conversation.updated_at = datetime.now()
            db.commit()
            logger.info(f"Generated title for conversation {conversation_id}: {title}")

        except Exception as e:
            logger.error(f"Error generating conversation title: {e}")

# EmbeddingService imported from app.services.embedding_service

# ============================================================================
# GLM-4.5 XML Tool Call Parser
# ============================================================================

def parse_glm45_tool_calls(content: str) -> tuple[str, list]:
    """
    Parse GLM-4.5 XML-formatted tool calls and convert to OpenAI JSON format.

    GLM-4.5 Format:
        <tool_call>function_name </tool_call>
        <tool_call>function_name <arg_key>param</arg_key> <arg_value>value</arg_value></tool_call>

    OpenAI Format:
        {
            "tool_calls": [{
                "id": "call_xxx",
                "type": "function",
                "function": {"name": "function_name", "arguments": "{}"}
            }]
        }

    Returns:
        (cleaned_content, tool_calls_list)
    """
    import re
    import uuid

    # Find all tool_call blocks
    tool_call_pattern = r'<tool_call>(.*?)</tool_call>'
    matches = re.findall(tool_call_pattern, content, re.DOTALL)

    if not matches:
        # No tool calls found, return original content
        return content, []

    tool_calls = []

    for match in matches:
        match = match.strip()

        # Extract function name (first word)
        parts = match.split()
        if not parts:
            logger.warning(f"Empty tool_call block found")
            continue

        function_name = parts[0]

        # Parse arguments if present
        arguments = {}
        arg_key_pattern = r'<arg_key>(.*?)</arg_key>'
        arg_value_pattern = r'<arg_value>(.*?)</arg_value>'

        keys = re.findall(arg_key_pattern, match)
        values = re.findall(arg_value_pattern, match)

        # Match keys with values
        for key, value in zip(keys, values):
            arguments[key.strip()] = value.strip()

        # Create OpenAI-compatible tool call
        tool_call = {
            "id": f"call_{str(uuid.uuid4())[:8]}",
            "type": "function",
            "function": {
                "name": function_name,
                "arguments": json.dumps(arguments) if arguments else "{}"
            }
        }

        tool_calls.append(tool_call)
        logger.info(f"Parsed GLM-4.5 tool call: {function_name} with args: {arguments}")

    # Remove all tool_call XML tags from content
    cleaned_content = re.sub(tool_call_pattern, '', content, flags=re.DOTALL).strip()

    # Also handle <think> tags (GLM-4.5 reasoning)
    think_pattern = r'<think>(.*?)</think>'
    think_matches = re.findall(think_pattern, cleaned_content, re.DOTALL)
    if think_matches:
        # Extract reasoning content but don't include in final response
        reasoning = " ".join([m.strip() for m in think_matches])
        logger.debug(f"GLM-4.5 reasoning: {reasoning[:100]}...")
        cleaned_content = re.sub(think_pattern, '', cleaned_content, flags=re.DOTALL).strip()

    return cleaned_content, tool_calls


def parse_json_text_tool_calls(content: str) -> tuple[str, list]:
    """
    Parse tool calls that are output as JSON text in the response content.

    This handles the case where the LLM outputs tool calls as JSON objects
    in the text content instead of using the proper tool_calls field.

    Expected formats:
        {"tool": "create_note", "title": "...", "content": "..."}
        {"name": "create_note", "arguments": {...}}
        {"function": "create_note", ...}

    Also handles markdown code blocks:
        ```json
        {"tool": "create_note", ...}
        ```

    Returns:
        (cleaned_content, tool_calls_list)
    """
    import re
    import uuid

    # Known tool names to look for
    known_tools = {
        'create_note', 'search_notes', 'edit_note', 'delete_note', 'list_notes',
        'notes_create', 'notes_search', 'notes_edit', 'notes_delete', 'notes_list',
        'create_reminder', 'list_reminders', 'cancel_reminder',
        'reminders_create', 'reminders_list', 'reminders_cancel',
        'start_timer', 'timer_status', 'cancel_timer',
        'timers_start', 'timers_status', 'timers_cancel',
        'memory_search', 'search_memory',
        'web_search', 'open_page', 'get_page_details', 'get_web_search_details',
        'calendar_list', 'calendar_create', 'create_calendar_event',
        'food_log_create', 'food_log_search', 'food_log_summary', 'food_search_and_log',
        'workout_log_create', 'workout_list', 'workout_details', 'workout_stats',
        'fitness_note_create', 'fitness_note_search', 'fitness_note_edit', 'fitness_summary',
        'load_tool_categories',
        'knowledge_graph_search', 'find_connections', 'discover_knowledge_clusters', 'analyze_knowledge_gaps'
    }

    tool_calls = []
    cleaned_content = content

    # Try to extract JSON from the content
    # First, try markdown code blocks
    code_block_pattern = r'```(?:json)?\s*(\{[^`]+\})\s*```'
    matches = re.findall(code_block_pattern, content, re.DOTALL)

    # Also try bare JSON objects at the start of content
    if not matches:
        # Look for JSON objects
        json_pattern = r'^\s*(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})'
        match = re.match(json_pattern, content.strip(), re.DOTALL)
        if match:
            matches = [match.group(1)]

    # Also try finding JSON anywhere in the content
    if not matches:
        # More permissive pattern for JSON objects
        json_pattern = r'(\{["\'](?:tool|name|function)["\']:\s*["\'][^"\']+["\'][^}]*\})'
        matches = re.findall(json_pattern, content, re.DOTALL)

    for match in matches:
        try:
            json_obj = json.loads(match)

            # Determine tool name from various possible keys
            tool_name = None
            arguments = {}

            if 'tool' in json_obj:
                tool_name = json_obj.pop('tool')
                arguments = json_obj  # Rest of object is arguments
            elif 'name' in json_obj:
                tool_name = json_obj.pop('name')
                if 'arguments' in json_obj:
                    arguments = json_obj['arguments'] if isinstance(json_obj['arguments'], dict) else json.loads(json_obj['arguments'])
                else:
                    arguments = json_obj
            elif 'function' in json_obj:
                tool_name = json_obj.pop('function')
                arguments = json_obj

            # Validate it's a known tool
            if tool_name and tool_name in known_tools:
                tool_call = {
                    "id": f"call_{str(uuid.uuid4())[:8]}",
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(arguments) if arguments else "{}"
                    }
                }
                tool_calls.append(tool_call)
                logger.info(f"Parsed JSON text tool call: {tool_name} with args: {arguments}")

                # Remove the JSON from content
                cleaned_content = cleaned_content.replace(match, '').strip()
                # Also remove code block markers if present
                cleaned_content = re.sub(r'```(?:json)?\s*```', '', cleaned_content).strip()

        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse potential JSON tool call: {e}")
            continue

    # Clean up any leftover empty code blocks or whitespace
    cleaned_content = re.sub(r'```(?:json)?\s*```', '', cleaned_content).strip()

    return cleaned_content, tool_calls


llm_client = SimpleLLMClient()
# embedding_service imported from app.services.embedding_service

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
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}
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
        """Send AI-generated timer completion notification via iOS push"""
        if not user_id:
            logger.warning("⚠️ No user_id provided for timer notification, cannot send push")
            return False

        # Get user context for personalization
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

        # Send via iOS push notification instead of NTFY
        return await send_push_to_user(
            user_id=user_id,
            title=ai_title,
            body=ai_message,
            notification_data={
                "type": "timer_complete",
                "timer_id": timer_id,
                "timer_name": title,
            }
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
    SEMANTIC = "semantic"  # Vector similarity search

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

    @classmethod
    def semantic(cls, query_embedding: List[float], duration: Optional[timedelta] = None, min_similarity: float = 0.3):
        """Create semantic similarity window using vector search"""
        params = {
            "query_embedding": query_embedding,
            "min_similarity": min_similarity
        }
        if duration:
            params["duration"] = duration
        return cls(WindowType.SEMANTIC, params)

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
        # Prefer explicit FAST_MODEL_URL, else OPENAI_BASE_URL
        self.fast_model_url = fast_model_url or os.getenv("FAST_MODEL_URL") or OPENAI_BASE_URL
        try:
            parsed = urlparse(self.fast_model_url or "")
            if not parsed.scheme:
                self.fast_model_url = OPENAI_BASE_URL
        except Exception:
            self.fast_model_url = OPENAI_BASE_URL
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

            elif window_config.window_type == WindowType.SEMANTIC:
                # Vector similarity search using pgvector
                params = window_config.parameters
                query_embedding = params["query_embedding"]
                min_similarity = params.get("min_similarity", 0.3)

                if "duration" in params:
                    cutoff_time = datetime.utcnow() - params["duration"]
                else:
                    cutoff_time = datetime.utcnow() - timedelta(days=30)  # Default 30 days

                # Use raw SQL for vector similarity search
                from sqlalchemy import text as sql_text

                # Convert embedding list to pgvector format
                embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"

                # Execute vector similarity query with composite scoring
                # Use string formatting for embedding to avoid SQLAlchemy parameter issues with pgvector
                sql = sql_text(f"""
                    SELECT
                        e.id,
                        e.conversation_id,
                        e.user_id,
                        e.role,
                        e.content,
                        e.importance,
                        e.emotional_tone,
                        e.topics,
                        e.context_tags,
                        e.access_count,
                        e.last_accessed,
                        e.memory_type,
                        e.source,
                        e.created_at,
                        e.embedding,
                        e.rating_boost,
                        e.exploration_bonus,
                        1 - (e.embedding <=> '{embedding_str}'::vector) as semantic_similarity,
                        -- Enhanced composite score with rating boost and exploration bonus
                        -- Uses 14-day half-life for recency decay (unified baseline across all retrieval paths)
                        (
                            (1 - (e.embedding <=> '{embedding_str}'::vector)) * 0.40 +  -- Semantic similarity (40%)
                            EXP(-EXTRACT(EPOCH FROM (NOW() - e.created_at)) / (14 * 86400)) * 0.20 +  -- Recency with 14-day half-life (20%)
                            COALESCE(e.importance, 0.5) * 0.20 +  -- AI-scored importance (20%)
                            COALESCE(e.rating_boost, 0.0) * 0.15 +  -- Rating boost (Wilson + decay) (15%)
                            COALESCE(e.exploration_bonus, 0.0) * 0.05  -- Thompson Sampling exploration (5%)
                        ) as composite_score
                    FROM episode e
                    WHERE e.user_id = :user_id
                      AND e.embedding IS NOT NULL
                      AND e.created_at >= :cutoff_time
                      AND (1 - (e.embedding <=> '{embedding_str}'::vector)) >= :min_similarity
                    ORDER BY composite_score DESC
                    LIMIT :limit
                """)

                result = db.execute(sql, {
                    "user_id": user_id,
                    "cutoff_time": cutoff_time,
                    "min_similarity": min_similarity,
                    "limit": limit
                })

                # Convert raw results to episode_data format
                episode_data = []
                for row in result:
                    episode_dict = {
                        'id': row.id,
                        'conversation_id': row.conversation_id,
                        'user_id': row.user_id,
                        'role': row.role,
                        'content': row.content,
                        'importance': row.importance,
                        'emotional_tone': row.emotional_tone,
                        'topics': row.topics,
                        'context_tags': row.context_tags,
                        'access_count': row.access_count,
                        'last_accessed': row.last_accessed,
                        'memory_type': row.memory_type,
                        'source': row.source,
                        'created_at': row.created_at,
                        'embedding': row.embedding,
                        'semantic_similarity': float(row.semantic_similarity),
                        'composite_score': float(row.composite_score)
                    }
                    episode_data.append(episode_dict)

                    # Update access tracking for retrieved episodes
                    episode_obj = db.query(Episode).filter(Episode.id == row.id).first()
                    if episode_obj:
                        episode_obj.access_count = (episode_obj.access_count or 0) + 1
                        episode_obj.last_accessed = datetime.utcnow()

                db.commit()
                logger.info(f"[Memory] Vector search returned {len(episode_data)} episodes with semantic similarity")
                return episode_data

            # Use composite score with temporal decay for non-semantic retrieval
            # This ensures temporal queries also properly weight recency
            from sqlalchemy import text as sql_text

            # Build WHERE clause from existing query filters
            # We need to use raw SQL for the decay formula
            time_filter = ""
            if window_config.window_type == WindowType.TEMPORAL:
                duration = window_config.parameters.get("duration", timedelta(days=7))
                cutoff_time = datetime.utcnow() - duration
                time_filter = f"AND e.created_at >= '{cutoff_time.isoformat()}'"

            # 14-day half-life for recency decay (unified baseline)
            # decay = exp(-t / (halflife * 86400)) where t is seconds
            RECENCY_HALFLIFE_DAYS = 14

            sql = sql_text(f"""
                SELECT
                    e.id,
                    e.conversation_id,
                    e.user_id,
                    e.role,
                    e.content,
                    e.importance,
                    e.emotional_tone,
                    e.topics,
                    e.context_tags,
                    e.access_count,
                    e.last_accessed,
                    e.memory_type,
                    e.source,
                    e.created_at,
                    e.embedding,
                    -- Composite score: importance (50%) + recency decay (50%)
                    (
                        COALESCE(e.importance, 0.5) * 0.50 +
                        EXP(-EXTRACT(EPOCH FROM (NOW() - e.created_at)) / ({RECENCY_HALFLIFE_DAYS} * 86400)) * 0.50
                    ) as composite_score
                FROM episode e
                WHERE e.user_id = :user_id
                {time_filter}
                ORDER BY composite_score DESC
                LIMIT :limit
            """)

            result = db.execute(sql, {"user_id": user_id, "limit": limit})

            episode_data = []
            episode_ids = []
            for row in result:
                episode_dict = {
                    'id': row.id,
                    'conversation_id': row.conversation_id,
                    'user_id': row.user_id,
                    'role': row.role,
                    'content': row.content,
                    'importance': row.importance,
                    'emotional_tone': row.emotional_tone,
                    'topics': row.topics,
                    'context_tags': row.context_tags,
                    'access_count': row.access_count,
                    'last_accessed': row.last_accessed,
                    'memory_type': row.memory_type,
                    'source': row.source,
                    'created_at': row.created_at,
                    'embedding': row.embedding,
                    'composite_score': float(row.composite_score)
                }
                episode_data.append(episode_dict)
                episode_ids.append(row.id)

            # Update access tracking for retrieved episodes
            if episode_ids:
                db.execute(sql_text("""
                    UPDATE episode
                    SET access_count = COALESCE(access_count, 0) + 1,
                        last_accessed = NOW()
                    WHERE id = ANY(:ids)
                """), {"ids": episode_ids})
                db.commit()

            logger.info(f"[Memory] Non-semantic retrieval returned {len(episode_data)} episodes with decay scoring")
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
            db.flush()  # Get episode.id without committing

            # Add to outbox for Neo4j sync (same transaction = guaranteed delivery)
            outbox_event = EventOutbox(
                event_type="episode_created",
                aggregate_type="Episode",
                aggregate_id=str(episode.id),
                op="UPSERT",
                payload=json.dumps({
                    "episode_id": str(episode.id),
                    "user_id": str(user_id),
                    "content": content,
                    "role": role,
                    "importance": importance,
                    "source": source,
                    "conversation_id": conversation_id,
                    "embedding": embedding if isinstance(embedding, list) else None
                }),
                status="pending"
            )
            db.add(outbox_event)

            db.commit()
            db.refresh(episode)

            logger.info(f"🧠 Stored episode {episode.id}: importance={importance:.2f}, emotion={emotional_analysis.get('primary_emotion')} (outbox queued)")
            return episode

        finally:
            db.close()
    
    async def intelligent_memory_search(
        self,
        user_id: str,
        query: str,
        auto_window: bool = True,
        custom_window: ContextWindowConfig = None,
        use_semantic: bool = True
    ) -> List[dict]:
        """Search memory with intelligent context window selection and optional semantic search"""

        # Try semantic search first if enabled and we have embeddings
        if use_semantic and not custom_window:
            try:
                # Check if we have episodes with embeddings
                db = SessionLocal()
                try:
                    has_embeddings = db.query(Episode).filter(
                        Episode.user_id == user_id,
                        Episode.embedding.isnot(None)
                    ).first() is not None
                finally:
                    db.close()

                if has_embeddings:
                    # Use semantic search with vector similarity
                    logger.info(f"🔍 Using semantic vector search for: {query[:50]}...")

                    # Get query embedding
                    query_embedding = await self._generate_embedding(query)

                    if query_embedding:
                        # Use semantic window with vector search
                        window_config = ContextWindowConfig.semantic(
                            query_embedding=query_embedding,
                            duration=timedelta(days=30),  # Search last 30 days
                            min_similarity=0.3  # Minimum similarity threshold
                        )

                        episodes = await self.window_manager.retrieve_episodes_with_window(
                            user_id, window_config, query, limit=15
                        )

                        if episodes:
                            logger.info(f"🧠 Semantic search found {len(episodes)} relevant episodes")
                            # Log top similarity scores
                            for i, ep in enumerate(episodes[:3]):
                                if 'semantic_similarity' in ep:
                                    logger.info(f"  {i+1}. Similarity: {ep['semantic_similarity']:.4f}, Score: {ep.get('composite_score', 0):.4f}")
                            return episodes
                        else:
                            logger.info("🔍 Semantic search found no results, falling back to temporal search")
            except Exception as e:
                logger.warning(f"Semantic search failed, falling back to traditional: {e}")

        # Fallback: Select appropriate context window using traditional method
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
        """Generate embedding for content using bge-m3"""
        try:
            from app.services.embeddings import get_embedding
            embedding = await get_embedding(content)
            logger.info(f"[Memory] Generated embedding with {len(embedding)} dimensions")
            return embedding
        except Exception as e:
            logger.error(f"[Memory] Failed to generate embedding: {e}")
            return None

# Import necessary modules for the new functionality
from sqlalchemy import or_

# Global intelligent memory service instance
intelligent_memory_service = IntelligentMemoryService()
logger.info("🧠 IntelligentMemoryService initialized for automatic context retrieval")

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
                    except (json.JSONDecodeError, TypeError, AttributeError) as e:
                        logger.debug(f"Failed to parse episode emotions: {e}")
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
                    except (json.JSONDecodeError, TypeError, AttributeError) as e:
                        logger.debug(f"Failed to parse episode topics: {e}")
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

            except (json.JSONDecodeError, TypeError, IndexError) as e:
                logger.debug(f"Failed to parse episode topics for clustering: {e}")
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
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.debug(f"Failed to parse episode topics: {e}")
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
            # Ensure both datetimes are timezone-aware for comparison
            now_utc = datetime.now(timezone.utc)
            created_at = episode.created_at
            if created_at.tzinfo is None:
                # If naive, assume UTC
                created_at = created_at.replace(tzinfo=timezone.utc)

            days_ago = (now_utc - created_at).days

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
                    db.flush()  # Get the ID before committing

                    # Emit insight_generated event for importance backpropagation
                    episode_ids = insight_data.get("episode_ids", [])
                    if episode_ids:
                        outbox_event = EventOutbox(
                            event_type="insight_generated",
                            aggregate_type="DreamInsight",
                            aggregate_id=str(dream_insight.id),
                            op="PROCESS",
                            payload=json.dumps({
                                "insight_id": str(dream_insight.id),
                                "source_episode_ids": episode_ids,
                                "importance_boost": 0.1,
                                "insight_type": insight_data["type"]
                            }),
                            status="pending"
                        )
                        db.add(outbox_event)

                    db.commit()
                    logger.info(f"💭 Stored {insight_data['type']} insight: {insight_data['title']} (backprop queued for {len(episode_ids)} episodes)")

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
                            "timer_name": timer.title,
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
        """Send a pre-generated notification via iOS push"""
        try:
            if notification["type"] == "timer":
                # Send via iOS push notification instead of NTFY
                await send_push_to_user(
                    user_id=notification.get("user_id"),
                    title=notification["title"],
                    body=notification["message"],
                    notification_data={
                        "type": "timer_complete",
                        "timer_id": notification.get("timer_id"),
                        "timer_name": notification.get("timer_name", "Timer"),
                    }
                )
                logger.info(f"⏰ Sent timer push notification: {notification['title']}")
                
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

# Add CORS middleware FIRST before any routes
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include modular routes

# Auth routes (extracted from main_simple.py)
try:
    from app.routes.auth import router as auth_router
    app.include_router(auth_router, tags=["Authentication"])
    logger.info("✅ Auth routes loaded from app.routes.auth")
except Exception as e:
    logger.warning(f"Auth routes not available from module: {e}")

# Folders routes (extracted from main_simple.py)
try:
    from app.routes.folders import router as folders_router
    app.include_router(folders_router, tags=["Folders"])
    logger.info("✅ Folders routes loaded from app.routes.folders")
except Exception as e:
    logger.warning(f"Folders routes not available from module: {e}")

# Notes routes (extracted from main_simple.py)
try:
    from app.routes.notes import router as notes_router
    app.include_router(notes_router, tags=["Notes"])
    logger.info("✅ Notes routes loaded from app.routes.notes")
except Exception as e:
    logger.warning(f"Notes routes not available from module: {e}")

# Reminders routes (extracted from main_simple.py)
try:
    from app.routes.reminders import router as reminders_router
    app.include_router(reminders_router, tags=["Reminders"])
    logger.info("✅ Reminders routes loaded from app.routes.reminders")
except Exception as e:
    logger.warning(f"Reminders routes not available from module: {e}")

# Calendar events routes (extracted from main_simple.py)
try:
    from app.routes.calendar_events import router as calendar_events_router
    app.include_router(calendar_events_router, tags=["Calendar"])
    # Also register iOS sync under /api prefix for backward compatibility
    from fastapi import APIRouter
    api_calendar_router = APIRouter(prefix="/api")
    from app.routes.calendar_events import sync_ios_calendar_events, clear_ios_calendar_events
    api_calendar_router.add_api_route("/calendar/ios-sync", sync_ios_calendar_events, methods=["POST"])
    api_calendar_router.add_api_route("/calendar/ios-sync", clear_ios_calendar_events, methods=["DELETE"])
    app.include_router(api_calendar_router)
    logger.info("✅ Calendar events routes loaded from app.routes.calendar_events")
except Exception as e:
    logger.warning(f"Calendar events routes not available from module: {e}")

# Habits routes (extracted from main_simple.py)
try:
    from app.routes.habits import router as habits_router, habit_items_router, insights_router, fitness_habits_router
    app.include_router(habits_router, tags=["Habits"])
    app.include_router(habit_items_router, tags=["Habits"])
    app.include_router(insights_router, tags=["Habits"])
    app.include_router(fitness_habits_router, tags=["Fitness"])
    logger.info("✅ Habits routes loaded from app.routes.habits")
except Exception as e:
    logger.warning(f"Habits routes not available from module: {e}")

try:
    from app.routes.memory import router as memory_router
    app.include_router(memory_router)
except Exception as e:
    logger.warning(f"Memory routes not available: {e}")

# Include Jarvis mode routes
try:
    from app.routes.calendar import router as calendar_router
    from app.routes.threads import router as threads_router
    app.include_router(calendar_router, prefix="/events")
    app.include_router(threads_router, prefix="/threads")
    logger.info("Jarvis mode routes loaded successfully")
except Exception as e:
    logger.warning(f"Jarvis routes not available: {e}")
    logger.warning("Running in Sara mode only")

# Include Fitness routes (independent of Jarvis mode)
try:
    from app.routes.fitness import router as fitness_router
    app.include_router(fitness_router, prefix="/api/fitness", tags=["Fitness"])
    logger.info("✅ Fitness routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Fitness routes failed to load: {e}")

# Include Learning routes
try:
    from app.routes.learning import router as learning_router
    app.include_router(learning_router, prefix="/api/learn", tags=["Learning"])
    logger.info("✅ Learning routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Learning routes failed to load: {e}")

# Include Food Database routes
try:
    from app.routes.food_database import router as food_db_router
    app.include_router(food_db_router, prefix="/api/fitness", tags=["Food Database"])
    logger.info("✅ Food database routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Food database routes failed to load: {e}")

# Include Health Metrics routes (Proactive Health Intelligence)
try:
    from app.routes.health_metrics import router as health_metrics_router
    app.include_router(health_metrics_router, tags=["Health Metrics"])
    logger.info("✅ Health metrics routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Health metrics routes failed to load: {e}")

# Include Emotion routes (Phase 2)
try:
    from app.routes.emotions import router as emotions_router
    app.include_router(emotions_router, prefix="/api/emotions", tags=["Emotions"])
    logger.info("✅ Emotion routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Emotion routes failed to load: {e}")

# Include Intelligence Reports routes (Phase 3)
try:
    from app.routes.intelligence_reports import router as reports_router
    app.include_router(reports_router, tags=["Intelligence Reports"])
    logger.info("✅ Intelligence reports routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Intelligence reports routes failed to load: {e}")

# Include Cognitive Enhancement routes
try:
    from app.routes.cognitive import router as cognitive_router
    app.include_router(cognitive_router, tags=["Cognitive Enhancement"])
    logger.info("✅ Cognitive enhancement routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Cognitive enhancement routes failed to load: {e}")

# Include Morning Brief routes
try:
    from app.routes.morning_brief import router as morning_brief_router
    app.include_router(morning_brief_router, prefix="/api/morning-brief", tags=["Morning Brief"])
    logger.info("✅ Morning brief routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Morning brief routes failed to load: {e}")

# Include Project Tracker routes
try:
    from app.routes.projects import router as projects_router
    app.include_router(projects_router, prefix="/api/projects", tags=["Project Tracker"])
    logger.info("✅ Project tracker routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Project tracker routes failed to load: {e}")

# Include Artifacts routes
try:
    from app.routes.artifacts import router as artifacts_router
    app.include_router(artifacts_router, prefix="/api/artifacts", tags=["Artifacts"])
    logger.info("✅ Artifacts routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Artifacts routes failed to load: {e}")

# Include Token Usage routes
try:
    from app.routes.token_usage import router as token_usage_router
    app.include_router(token_usage_router, prefix="/api/token-usage", tags=["Token Usage"])
    logger.info("✅ Token usage routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Token usage routes failed to load: {e}")

# Include Orchestrator Lab routes
try:
    from app.routes.orchestrator import router as orchestrator_router
    app.include_router(orchestrator_router, tags=["Orchestrator Lab"])
    logger.info("✅ Orchestrator Lab routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Orchestrator Lab routes failed to load: {e}")

# Include Background Tasks routes
try:
    from app.routes.background_tasks import get_configured_router
    bg_tasks_router = get_configured_router(get_db, get_current_user)
    app.include_router(bg_tasks_router, tags=["Background Tasks"])
    logger.info("✅ Background Tasks routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Background Tasks routes failed to load: {e}")

# Include Pattern Correlation routes
try:
    from app.routes.patterns import router as patterns_router
    app.include_router(patterns_router, tags=["Patterns"])
    logger.info("✅ Pattern Correlation routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Pattern Correlation routes failed to load: {e}")

# Include Vision API routes (screenshot analysis, vision models)
try:
    from app.routes.vision import router as vision_router
    app.include_router(vision_router, tags=["Vision"])
    logger.info("✅ Vision API routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Vision API routes failed to load: {e}")

# Include Device Commands routes (cross-device command routing)
try:
    from app.routes.device_commands import router as device_commands_router
    app.include_router(device_commands_router, tags=["Device Commands"])
    logger.info("✅ Device Commands routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Device Commands routes failed to load: {e}")

# Include User Settings routes
try:
    from app.routes.settings import router as settings_router
    app.include_router(settings_router, tags=["Settings"])
    logger.info("✅ User Settings routes loaded successfully")
except Exception as e:
    logger.error(f"❌ User Settings routes failed to load: {e}")

# ===================== PHASE 4 INTELLIGENCE ROUTES =====================
from app.services.phase4_intelligence import generate_daily_briefing, get_context_stats, generate_intelligence_report

# Create wrapper function for LLM calls used by Phase 4 intelligence
async def call_llm_simple(messages: list, temperature: float = 0.7, max_tokens: int = 1000) -> str:
    """Simple LLM wrapper for Phase 4 intelligence services"""
    try:
        # Make direct API call to respect temperature and max_tokens parameters
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{OPENAI_BASE_URL}/chat/completions",
                json={
                    "model": OPENAI_MODEL,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens
                },
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Error calling LLM: {e}")
        raise

# Daily Briefings routes
@app.get("/api/briefings")
async def get_briefings(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get all daily briefings for the user"""
    try:
        user_id = current_user.id
        briefings = db.query(DailyBriefing).filter(
            DailyBriefing.user_id == user_id
        ).order_by(DailyBriefing.briefing_date.desc()).limit(30).all()

        return [{
            "id": b.id,
            "user_id": b.user_id,
            "briefing_type": b.briefing_type,
            "briefing_date": b.briefing_date.isoformat(),
            "content": b.content,
            "delivered": bool(b.delivered),
            "read": bool(b.read),
            "created_at": b.created_at.isoformat()
        } for b in briefings]
    except Exception as e:
        logger.error(f"Error getting briefings: {e}")
        return []

@app.get("/api/briefings/settings")
async def get_briefing_settings(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get briefing settings for the user"""
    try:
        user_id = current_user.id
        settings = db.query(BriefingSettings).filter(BriefingSettings.user_id == user_id).first()

        if not settings:
            # Create default settings
            settings = BriefingSettings(user_id=user_id)
            db.add(settings)
            db.commit()
            db.refresh(settings)

        return {
            "id": settings.id,
            "user_id": settings.user_id,
            "morning_enabled": bool(settings.morning_enabled),
            "morning_time": settings.morning_time,
            "evening_enabled": bool(settings.evening_enabled),
            "evening_time": settings.evening_time,
            "include_recovery": bool(settings.include_recovery),
            "include_schedule": bool(settings.include_schedule),
            "include_goals": bool(settings.include_goals),
            "include_suggestions": bool(settings.include_suggestions),
            "include_workout_rec": bool(settings.include_workout_rec),
            "include_accomplishments": bool(settings.include_accomplishments),
            "include_insights": bool(settings.include_insights),
            "include_reflection": bool(settings.include_reflection)
        }
    except Exception as e:
        logger.error(f"Error getting briefing settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/briefings/settings")
async def update_briefing_settings(settings_data: dict, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Update briefing settings"""
    try:
        user_id = current_user.id
        settings = db.query(BriefingSettings).filter(BriefingSettings.user_id == user_id).first()

        if not settings:
            settings = BriefingSettings(user_id=user_id)
            db.add(settings)

        # Update fields
        for key, value in settings_data.items():
            if hasattr(settings, key) and key != "id" and key != "user_id":
                setattr(settings, key, 1 if value else 0 if key.startswith("include_") or key.endswith("_enabled") else value)

        settings.updated_at = datetime.now()
        db.commit()
        db.refresh(settings)

        return {"success": True, "settings": settings_data}
    except Exception as e:
        logger.error(f"Error updating briefing settings: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/briefings/generate")
async def generate_briefing_route(data: dict, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Generate a new briefing"""
    try:
        user_id = current_user.id
        briefing_type = data.get("briefing_type", "morning")

        # Use the intelligence service to generate briefing
        briefing = await generate_daily_briefing(
            db=db,
            user_id=user_id,
            briefing_type=briefing_type,
            llm_call_fn=call_llm_simple,
            Episode=Episode,
            Note=Note,
            CalendarEvent=CalendarEvent,
            DailyBriefing=DailyBriefing,
            BriefingSettings=BriefingSettings
        )

        return briefing
    except Exception as e:
        logger.error(f"Error generating briefing: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/api/briefings/{briefing_id}/read")
async def mark_briefing_read(briefing_id: str, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Mark briefing as read"""
    try:
        user_id = current_user.id
        briefing = db.query(DailyBriefing).filter(
            DailyBriefing.id == briefing_id,
            DailyBriefing.user_id == user_id
        ).first()

        if briefing:
            briefing.read = 1
            db.commit()
            return {"success": True}

        raise HTTPException(status_code=404, detail="Briefing not found")
    except Exception as e:
        logger.error(f"Error marking briefing as read: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# Context Mode routes
@app.get("/api/context/mode")
async def get_context_mode_route(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get current context mode"""
    try:
        user_id = current_user.id
        context_mode = db.query(ContextMode).filter(ContextMode.user_id == user_id).first()

        if not context_mode:
            context_mode = ContextMode(user_id=user_id, current_mode="full")
            db.add(context_mode)
            db.commit()
            db.refresh(context_mode)

        return {"mode": context_mode.current_mode}
    except Exception as e:
        logger.error(f"Error getting context mode: {e}")
        return {"mode": "full"}

@app.put("/api/context/mode")
async def set_context_mode_route(data: dict, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Set context mode"""
    try:
        user_id = current_user.id
        new_mode = data.get("mode", "full")

        context_mode = db.query(ContextMode).filter(ContextMode.user_id == user_id).first()

        if not context_mode:
            context_mode = ContextMode(user_id=user_id, current_mode=new_mode)
            db.add(context_mode)
        else:
            context_mode.current_mode = new_mode
            context_mode.updated_at = datetime.now()

        db.commit()
        return {"mode": new_mode}
    except Exception as e:
        logger.error(f"Error setting context mode: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/context/stats")
async def get_context_stats_route(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get context statistics"""
    user_id = current_user.id
    return get_context_stats(db, user_id, Episode, Note, Document, CalendarEvent)

# Smart Insights routes
@app.get("/api/reports/list")
async def get_reports_list(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get list of intelligence reports"""
    try:
        user_id = current_user.id
        reports = db.query(IntelligenceReport).filter(
            IntelligenceReport.user_id == user_id
        ).order_by(IntelligenceReport.report_date.desc()).limit(20).all()

        return [{
            "id": r.id,
            "user_id": r.user_id,
            "report_type": r.report_type,
            "report_date": r.report_date.isoformat(),
            "title": r.title,
            "summary": r.summary,
            "created_at": r.created_at.isoformat()
        } for r in reports]
    except Exception as e:
        logger.error(f"Error getting reports list: {e}")
        return []

@app.post("/api/reports/generate")
async def generate_report_route(data: dict, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Generate an intelligence report"""
    try:
        user_id = current_user.id
        report_type = data.get("report_type", "weekly")

        report = await generate_intelligence_report(
            db=db,
            user_id=user_id,
            report_type=report_type,
            llm_call_fn=call_llm_simple,
            Episode=Episode,
            IntelligenceReport=IntelligenceReport
        )

        return report
    except Exception as e:
        logger.error(f"Error generating intelligence report: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/suggestions")
async def get_suggestions(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get proactive suggestions"""
    try:
        user_id = current_user.id
        suggestions = db.query(ProactiveSuggestion).filter(
            ProactiveSuggestion.user_id == user_id,
            ProactiveSuggestion.status == "pending"
        ).order_by(ProactiveSuggestion.created_at.desc()).limit(10).all()

        return [{
            "id": s.id,
            "title": s.title,
            "description": s.description,
            "category": s.category,
            "priority": s.priority,
            "confidence": s.confidence,
            "status": s.status,
            "created_at": s.created_at.isoformat()
        } for s in suggestions]
    except Exception as e:
        logger.error(f"Error getting suggestions: {e}")
        return []

@app.patch("/api/suggestions/{suggestion_id}")
async def update_suggestion(suggestion_id: str, data: dict, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Update suggestion status"""
    try:
        user_id = current_user.id
        status = data.get("status", "pending")

        suggestion = db.query(ProactiveSuggestion).filter(
            ProactiveSuggestion.id == suggestion_id,
            ProactiveSuggestion.user_id == user_id
        ).first()

        if suggestion:
            suggestion.status = status
            suggestion.actioned_at = datetime.now() if status in ["accepted", "dismissed"] else None
            db.commit()
            return {"id": suggestion_id, "status": status}

        raise HTTPException(status_code=404, detail="Suggestion not found")
    except Exception as e:
        logger.error(f"Error updating suggestion: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/patterns")
async def get_patterns(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get detected patterns"""
    try:
        user_id = current_user.id
        patterns = db.query(DetectedPattern).filter(
            DetectedPattern.user_id == user_id
        ).order_by(DetectedPattern.confidence.desc()).limit(10).all()

        return [{
            "id": p.id,
            "pattern_type": p.pattern_type,
            "title": p.title,
            "description": p.description,
            "confidence": p.confidence,
            "frequency": p.frequency,
            "data_points": p.data_points,
            "first_detected": p.first_detected.isoformat(),
            "created_at": p.created_at.isoformat()
        } for p in patterns]
    except Exception as e:
        logger.error(f"Error getting patterns: {e}")
        return []

logger.info("✅ Phase 4 intelligence routes loaded successfully")

# ===================== SUBCONSCIOUS ROUTES =====================
@app.get("/api/subconscious/state")
async def get_subconscious_state(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get current mental model state for Sara context injection"""
    try:
        user_id = current_user.id
        result = db.execute(text("""
            SELECT * FROM subconscious_state WHERE user_id = :user_id
        """), {"user_id": user_id}).fetchone()

        if result:
            state = dict(result._mapping)
            # Parse JSON fields
            for field in ['typical_meal_windows', 'current_focus_areas', 'active_threads',
                         'docker_health', 'service_health']:
                if state.get(field) and isinstance(state[field], str):
                    try:
                        state[field] = json.loads(state[field])
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.debug(f"Failed to parse JSON field {field}: {e}")
            # Format timestamps
            for field in ['last_meal_at', 'last_presence_at', 'updated_at', 'created_at']:
                if state.get(field):
                    state[field] = state[field].isoformat() if hasattr(state[field], 'isoformat') else str(state[field])
            return state

        return {"message": "No state available yet", "user_id": user_id}
    except Exception as e:
        logger.error(f"Error getting subconscious state: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/subconscious/nudges")
async def get_subconscious_nudges(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get pending nudges for display"""
    try:
        user_id = current_user.id
        result = db.execute(text("""
            SELECT id, nudge_type, severity, title, message, action_suggestion,
                   delivery_channel, created_at, expires_at
            FROM subconscious_nudge
            WHERE user_id = :user_id
              AND status IN ('pending', 'delivered')
              AND expires_at > NOW()
            ORDER BY
                CASE severity
                    WHEN 'urgent' THEN 1
                    WHEN 'gentle' THEN 2
                    ELSE 3
                END,
                created_at DESC
        """), {"user_id": user_id}).fetchall()

        nudges = []
        for r in result:
            nudge = dict(r._mapping)
            nudge['created_at'] = nudge['created_at'].isoformat() if nudge.get('created_at') else None
            nudge['expires_at'] = nudge['expires_at'].isoformat() if nudge.get('expires_at') else None
            nudges.append(nudge)

        return nudges
    except Exception as e:
        logger.error(f"Error getting nudges: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/subconscious/nudges/{nudge_id}/acknowledge")
async def acknowledge_nudge(nudge_id: str, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Acknowledge a nudge"""
    try:
        user_id = current_user.id
        result = db.execute(text("""
            UPDATE subconscious_nudge
            SET acknowledged_at = NOW(), status = 'acknowledged'
            WHERE id = :nudge_id
              AND user_id = :user_id
              AND status IN ('pending', 'delivered')
        """), {"nudge_id": nudge_id, "user_id": user_id})

        db.commit()

        if result.rowcount > 0:
            return {"success": True, "nudge_id": nudge_id}
        raise HTTPException(status_code=404, detail="Nudge not found or already acknowledged")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error acknowledging nudge: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/subconscious/nudges/stream")
async def nudge_stream(request: Request, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """SSE stream for real-time nudge updates"""
    user_id = current_user.id

    async def generate_events():
        last_check = datetime.now()
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            # Check for new nudges since last check
            result = db.execute(text("""
                SELECT id, nudge_type, severity, title, message, action_suggestion,
                       delivery_channel, created_at
                FROM subconscious_nudge
                WHERE user_id = :user_id
                  AND status IN ('pending', 'delivered')
                  AND created_at > :last_check
                  AND expires_at > NOW()
                ORDER BY created_at DESC
            """), {"user_id": user_id, "last_check": last_check}).fetchall()

            for r in result:
                nudge = dict(r._mapping)
                nudge['created_at'] = nudge['created_at'].isoformat() if nudge.get('created_at') else None
                yield f"data: {json.dumps({'type': 'nudge', 'nudge': nudge})}\n\n"

            last_check = datetime.now()
            await asyncio.sleep(10)  # Check every 10 seconds

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )


logger.info("✅ Subconscious routes loaded successfully")

# ===================== PI DASHBOARD ROUTES =====================
# These routes support device token auth for headless Pi access

async def get_device_user(request: Request, db: Session = Depends(get_db)) -> Optional[str]:
    """Get user ID from device token or return None"""
    device_token = request.headers.get("X-Device-Token")
    if device_token:
        result = db.execute(text("""
            SELECT user_id FROM device_registration
            WHERE device_token = :token
        """), {"token": device_token}).fetchone()
        if result:
            # Update last_seen
            db.execute(text("""
                UPDATE device_registration SET last_seen = NOW()
                WHERE device_token = :token
            """), {"token": device_token})
            db.commit()
            return result.user_id
    return None


@app.post("/api/devices/register")
async def register_device(
    data: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Register a device for token-based auth (requires initial login)"""
    import secrets
    device_name = data.get("device_name", "Unknown Device")
    device_type = data.get("device_type", "pi_dashboard")

    device_token = secrets.token_urlsafe(32)
    device_id = str(uuid.uuid4())

    db.execute(text("""
        INSERT INTO device_registration (id, user_id, device_name, device_token, device_type, last_seen, created_at)
        VALUES (:id, :user_id, :device_name, :device_token, :device_type, NOW(), NOW())
    """), {
        "id": device_id,
        "user_id": current_user.id,
        "device_name": device_name,
        "device_token": device_token,
        "device_type": device_type
    })
    db.commit()

    return {
        "device_id": device_id,
        "device_token": device_token,
        "message": "Device registered. Store this token securely."
    }


@app.post("/api/devices/bootstrap")
async def bootstrap_device(data: dict, db: Session = Depends(get_db)):
    """Bootstrap a device registration using email - for headless Pi setup"""
    import secrets

    email = data.get("email")
    device_name = data.get("device_name", "pi-dashboard")
    device_type = data.get("device_type", "pi_dashboard")

    if not email:
        raise HTTPException(status_code=400, detail="Email required")

    # Find user by email
    result = db.execute(text("SELECT id FROM app_user WHERE email = :email"), {"email": email}).fetchone()
    if not result:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = result[0]

    # Check if device already exists
    existing = db.execute(text("""
        SELECT device_token FROM device_registration
        WHERE user_id = :user_id AND device_name = :device_name
    """), {"user_id": user_id, "device_name": device_name}).fetchone()

    if existing:
        return {
            "device_token": existing[0],
            "message": "Device already registered. Returning existing token."
        }

    device_token = secrets.token_urlsafe(32)
    device_id = str(uuid.uuid4())

    db.execute(text("""
        INSERT INTO device_registration (id, user_id, device_name, device_token, device_type, last_seen, created_at)
        VALUES (:id, :user_id, :device_name, :device_token, :device_type, NOW(), NOW())
    """), {
        "id": device_id,
        "user_id": user_id,
        "device_name": device_name,
        "device_token": device_token,
        "device_type": device_type
    })
    db.commit()

    return {
        "device_id": device_id,
        "device_token": device_token,
        "message": "Device registered. Store this token in localStorage as 'device_token'."
    }


@app.get("/api/pi-dashboard/state")
async def get_pi_dashboard_state(request: Request, db: Session = Depends(get_db)):
    """Get combined state for Pi dashboard (supports device token auth)"""
    # Try device token auth first
    user_id = await get_device_user(request, db)

    # Fall back to cookie auth
    if not user_id:
        try:
            current_user = await get_current_user(request, db)
            user_id = current_user.id
        except Exception as auth_err:
            logger.debug(f"Authentication failed for pi-dashboard/state: {auth_err}")
            raise HTTPException(status_code=401, detail="Not authenticated. Use device token or login.")

    # Get subconscious state
    state_result = db.execute(text("""
        SELECT * FROM subconscious_state WHERE user_id = :user_id
    """), {"user_id": user_id}).fetchone()

    state = None
    if state_result:
        state = dict(state_result._mapping)
        for field in ['typical_meal_windows', 'current_focus_areas', 'active_threads',
                     'docker_health', 'service_health']:
            if state.get(field) and isinstance(state[field], str):
                try:
                    state[field] = json.loads(state[field])
                except (json.JSONDecodeError, TypeError) as e:
                    logger.debug(f"Failed to parse JSON field {field}: {e}")
        for field in ['last_meal_at', 'last_presence_at', 'updated_at', 'created_at']:
            if state.get(field):
                state[field] = state[field].isoformat() if hasattr(state[field], 'isoformat') else str(state[field])

    # Get pending nudges
    nudges_result = db.execute(text("""
        SELECT id, nudge_type, severity, title, message, action_suggestion,
               delivery_channel, created_at, expires_at
        FROM subconscious_nudge
        WHERE user_id = :user_id
          AND status IN ('pending', 'delivered')
          AND expires_at > NOW()
        ORDER BY
            CASE severity WHEN 'urgent' THEN 1 WHEN 'gentle' THEN 2 ELSE 3 END,
            created_at DESC
        LIMIT 10
    """), {"user_id": user_id}).fetchall()

    nudges = []
    for r in nudges_result:
        nudge = dict(r._mapping)
        nudge['created_at'] = nudge['created_at'].isoformat() if nudge.get('created_at') else None
        nudge['expires_at'] = nudge['expires_at'].isoformat() if nudge.get('expires_at') else None
        nudges.append(nudge)

    # Get worker status from subconscious log
    worker_status = {}
    try:
        subconscious_log = db.execute(text("""
            SELECT snapshot_at FROM subconscious_log
            WHERE user_id = :user_id
            ORDER BY snapshot_at DESC LIMIT 1
        """), {"user_id": user_id}).fetchone()
        if subconscious_log:
            last_run = subconscious_log.snapshot_at
            # Next run is 30 minutes after last run (during waking hours)
            next_run = last_run + timedelta(minutes=30) if last_run else None
            worker_status["subconscious"] = {
                "last_run": last_run.isoformat() if last_run else None,
                "next_run": next_run.isoformat() if next_run else None,
                "interval_mins": 30
            }
    except Exception as e:
        logger.warning(f"Failed to get subconscious worker status: {e}")

    # Get orchestrator status (from background_task if available)
    try:
        orchestrator_task = db.execute(text("""
            SELECT completed_at FROM background_task
            WHERE task_type = 'orchestrator'
            ORDER BY completed_at DESC LIMIT 1
        """)).fetchone()
        if orchestrator_task and orchestrator_task.completed_at:
            last_run = orchestrator_task.completed_at
            next_run = last_run + timedelta(minutes=5)
            worker_status["orchestrator"] = {
                "last_run": last_run.isoformat(),
                "next_run": next_run.isoformat(),
                "interval_mins": 5
            }
    except Exception:
        pass  # Table might not exist

    # Get today's calendar events
    calendar_events = []
    try:
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        events_result = db.execute(text("""
            SELECT id, title, start_time, end_time, location
            FROM calendar_event
            WHERE user_id = :user_id
              AND start_time >= :today_start
              AND start_time < :today_end
            ORDER BY start_time
            LIMIT 10
        """), {"user_id": user_id, "today_start": today_start, "today_end": today_end}).fetchall()

        for e in events_result:
            calendar_events.append({
                "id": e.id,
                "title": e.title,
                "start": e.start_time.isoformat() if e.start_time else None,
                "end": e.end_time.isoformat() if e.end_time else None,
                "location": e.location
            })
    except Exception as ex:
        logger.warning(f"Failed to get calendar events: {ex}")

    # Get recent notes
    recent_notes = []
    try:
        notes_result = db.execute(text("""
            SELECT id, title, updated_at, created_at
            FROM note
            WHERE user_id = :user_id
            ORDER BY updated_at DESC
            LIMIT 10
        """), {"user_id": user_id}).fetchall()

        for n in notes_result:
            recent_notes.append({
                "id": n.id,
                "title": n.title,
                "updated_at": n.updated_at.isoformat() if n.updated_at else None,
                "created_at": n.created_at.isoformat() if n.created_at else None
            })
    except Exception as ex:
        logger.warning(f"Failed to get notes: {ex}")

    return {
        "state": state,
        "nudges": nudges,
        "worker_status": worker_status,
        "calendar_events": calendar_events,
        "recent_notes": recent_notes,
        "timestamp": datetime.now().isoformat()
    }


# ===================== PI DASHBOARD NUDGE ENDPOINT =====================

@app.post("/api/pi-dashboard/nudges/{nudge_id}/acknowledge")
async def pi_dashboard_acknowledge_nudge(nudge_id: str, request: Request, db: Session = Depends(get_db)):
    """Acknowledge a nudge via Pi dashboard (supports device token auth)"""
    # Try device token auth first
    user_id = await get_device_user(request, db)

    # Fall back to cookie auth
    if not user_id:
        try:
            current_user = await get_current_user(request, db)
            user_id = current_user.id
        except Exception as auth_err:
            logger.debug(f"Authentication failed: {auth_err}")
            raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        result = db.execute(text("""
            UPDATE subconscious_nudge
            SET acknowledged_at = NOW(), status = 'acknowledged'
            WHERE id = :nudge_id
              AND user_id = :user_id
              AND status IN ('pending', 'delivered')
        """), {"nudge_id": nudge_id, "user_id": user_id})

        db.commit()

        if result.rowcount > 0:
            logger.info(f"[Pi Dashboard] Nudge {nudge_id} acknowledged by user {user_id}")
            return {"success": True, "nudge_id": nudge_id}
        raise HTTPException(status_code=404, detail="Nudge not found or already acknowledged")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error acknowledging nudge: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pi-dashboard/timers")
async def get_pi_dashboard_timers(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get active timers for Pi dashboard overlay"""
    user_id = current_user.id

    try:
        now = datetime.now(timezone.utc)

        # Get active timers for this user
        timers = db.query(Timer).filter(
            Timer.user_id == user_id,
            Timer.is_active == True
        ).order_by(Timer.end_time.asc()).all()

        timer_list = []
        for timer in timers:
            # Ensure end_time is timezone-aware
            end_time = timer.end_time
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)

            # Calculate remaining time
            remaining_seconds = (end_time - now).total_seconds()

            # Skip expired timers (but mark them as completed)
            if remaining_seconds <= 0:
                timer.is_active = False
                timer.is_completed = True
                db.commit()
                continue

            timer_list.append({
                "id": timer.id,
                "title": timer.title,
                "duration_minutes": timer.duration_minutes,
                "end_time": end_time.isoformat(),
                "remaining_seconds": int(remaining_seconds),
                "remaining_minutes": int(remaining_seconds / 60),
                "remaining_display": f"{int(remaining_seconds // 60)}:{int(remaining_seconds % 60):02d}"
            })

        return {"timers": timer_list, "count": len(timer_list)}
    except Exception as e:
        logger.error(f"Error getting timers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===================== PI DASHBOARD VOICE ENDPOINTS =====================

@app.post("/api/pi-dashboard/voice/transcribe")
async def pi_dashboard_voice_transcribe(request: Request, audio: UploadFile = File(...), db: Session = Depends(get_db)):
    """Transcribe audio for Pi dashboard (supports device token auth)"""
    # Try device token auth first
    user_id = await get_device_user(request, db)

    # Fall back to cookie auth
    if not user_id:
        try:
            current_user = await get_current_user(request, db)
            user_id = current_user.id
        except Exception as auth_err:
            logger.debug(f"Authentication failed for voice/transcribe: {auth_err}")
            raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        # Save audio file temporarily
        audio_content = await audio.read()
        temp_audio_path = f"/tmp/voice_{uuid.uuid4()}.webm"

        with open(temp_audio_path, "wb") as f:
            f.write(audio_content)

        # Known Whisper hallucinations on silence/noise
        WHISPER_HALLUCINATIONS = {
            "thank you", "thanks", "thanks for watching", "thank you for watching",
            "please subscribe", "subscribe", "bye", "goodbye", "see you next time",
            "you", "the", "i", "a", "", "so", "um", "uh", "hmm", "oh",
            "thank you.", "thanks.", "bye.", "goodbye."
        }

        # Call Whisper STT service (same as voice-agent)
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            with open(temp_audio_path, "rb") as audio_file:
                files = {"file": ("audio.webm", audio_file, "audio/webm")}
                data = {
                    "model": "distil-small.en",
                    "language": "en",
                    "vad_filter": "true",
                    "no_speech_threshold": "0.4",
                    "compression_ratio_threshold": "2.0",
                }
                response = await client.post(
                    "http://10.185.1.8:8585/v1/audio/transcriptions",
                    files=files,
                    data=data
                )

        # Clean up temp file
        try:
            os.remove(temp_audio_path)
        except OSError as e:
            logger.debug(f"Failed to remove temp audio file: {e}")

        if response.status_code == 200:
            result = response.json()
            transcribed_text = result.get("text", "").strip()

            # Filter out hallucinations
            if transcribed_text.lower() in WHISPER_HALLUCINATIONS:
                logger.info(f"[Pi Dashboard Voice] Filtered hallucination: '{transcribed_text}'")
                return {"transcription": "", "filtered": True}

            # Filter short hallucinations
            if len(transcribed_text.split()) <= 2 and transcribed_text.lower().rstrip('.!?') in WHISPER_HALLUCINATIONS:
                logger.info(f"[Pi Dashboard Voice] Filtered short hallucination: '{transcribed_text}'")
                return {"transcription": "", "filtered": True}

            logger.info(f"[Pi Dashboard Voice] Transcribed: {transcribed_text}")
            return {"transcription": transcribed_text}
        else:
            logger.error(f"[Pi Dashboard Voice] Whisper error: {response.status_code} - {response.text}")
            raise HTTPException(status_code=500, detail="Transcription failed")

    except Exception as e:
        logger.error(f"[Pi Dashboard Voice] Transcription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pi-dashboard/voice/chat")
async def pi_dashboard_voice_chat(request: Request, db: Session = Depends(get_db)):
    """
    Streaming chat for Pi dashboard with device token auth.
    Returns SSE stream with Sara's response.
    """
    # Try device token auth first
    user_id = await get_device_user(request, db)

    # Fall back to cookie auth
    if not user_id:
        try:
            current_user = await get_current_user(request, db)
            user_id = current_user.id
        except Exception as auth_err:
            logger.debug(f"Authentication failed for voice/chat: {auth_err}")
            raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        body = await request.json()
        message = body.get("message", "")
        conversation_id = body.get("conversation_id")

        if not message:
            raise HTTPException(status_code=400, detail="No message provided")

        logger.info(f"[Pi Dashboard Voice] Chat from user {user_id}: {message[:50]}...")

        # Get user object for chat
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Generate conversation ID if not provided
        if not conversation_id:
            conversation_id = f"pi-voice-{uuid.uuid4()}"

        # Stream the response
        async def generate_stream():
            full_response = ""
            try:
                # Create system prompt
                system_prompt = get_system_prompt(ASSISTANT_NAME, user.email)

                # Intent classification for lazy context (with conversation context)
                tool_classifier = get_tool_intent_classifier()
                context_router = get_context_router()
                # Use conversation-aware classification
                user_intent, tool_categories = tool_classifier.classify_with_context(message, conversation_id)
                context_decision = context_router.decide(intent=user_intent, message=message, turn_count=1)
                logger.info(f"[Pi Dashboard Voice] Intent={user_intent}, tools={tool_categories}, {context_decision.reason}")

                # Lazy memory retrieval
                if context_decision.inject_memory:
                    try:
                        relevant_memories = await intelligent_memory_service.intelligent_memory_search(
                            user_id=user_id,
                            query=message,
                            use_semantic=True
                        )
                        if relevant_memories:
                            memory_context = "\n\n## Relevant Past Context:\n"
                            for i, mem in enumerate(relevant_memories[:3], 1):
                                content_preview = mem.get("content", "")[:200]
                                memory_context += f"{i}. {content_preview}\n"
                            system_prompt += memory_context
                    except Exception as e:
                        logger.warning(f"[Pi Dashboard Voice] Memory retrieval failed: {e}")

                # Get tools based on intent (already determined by classify_with_context)
                tools = []
                if tool_categories:
                    tools = tool_registry.get_tools_by_categories(tool_categories)
                    logger.info(f"[Pi Dashboard Voice] Loaded {len(tools)} tools for categories: {tool_categories}")

                # Build messages
                llm_messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message}
                ]

                # Use the global LLM client
                if tools:
                    # Use chat_with_tools for tool-enabled conversations
                    full_response = await llm_client.chat_with_tools(
                        llm_messages,
                        tools=tools,
                        user_id=user_id,
                        conversation_id=conversation_id
                    )
                else:
                    # Simple chat without tools
                    full_response = await llm_client.chat(llm_messages)

                # Ensure we have a string response
                if isinstance(full_response, dict):
                    full_response = full_response.get("content", str(full_response))
                elif not isinstance(full_response, str):
                    full_response = str(full_response)

                # Send response
                yield f"data: {json.dumps({'type': 'text_chunk', 'content': full_response})}\n\n"
                yield f"data: {json.dumps({'type': 'final_response', 'content': full_response, 'conversation_id': conversation_id})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"

                # Store episode in background
                try:
                    episode_id = str(uuid.uuid4())
                    db.execute(text("""
                        INSERT INTO episode (id, user_id, content, importance, created_at, source)
                        VALUES (:id, :user_id, :content, :importance, NOW(), :source)
                    """), {
                        "id": episode_id,
                        "user_id": user_id,
                        "content": f"User (voice via Pi dashboard): {message}\n\nSara: {full_response}",
                        "importance": 0.5,
                        "source": "pi_dashboard_voice"
                    })
                    db.commit()
                except Exception as e:
                    logger.warning(f"[Pi Dashboard Voice] Failed to store episode: {e}")

            except Exception as e:
                logger.error(f"[Pi Dashboard Voice] Chat error: {e}")
                import traceback
                traceback.print_exc()
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        return StreamingResponse(
            generate_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive"
            }
        )

    except Exception as e:
        logger.error(f"[Pi Dashboard Voice] Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pi-dashboard/voice/speak")
async def pi_dashboard_voice_speak(request: Request, db: Session = Depends(get_db)):
    """
    Text-to-speech for Pi dashboard with device token auth.
    Returns audio blob.
    """
    # Try device token auth first
    user_id = await get_device_user(request, db)

    # Fall back to cookie auth
    if not user_id:
        try:
            current_user = await get_current_user(request, db)
            user_id = current_user.id
        except Exception as auth_err:
            logger.debug(f"Authentication failed for voice/speak: {auth_err}")
            raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        body = await request.json()
        text = body.get("text", "")
        response_format = body.get("response_format", "mp3")  # Default MP3 for browser

        if not text:
            raise HTTPException(status_code=400, detail="No text provided")

        logger.info(f"[Pi Dashboard Voice] TTS for user {user_id}: {text[:50]}...")

        # Call Kokoro TTS service
        import httpx
        async with httpx.AsyncClient(timeout=60.0) as client:
            tts_response = await client.post(
                "http://10.185.1.9:8880/v1/audio/speech",
                json={
                    "input": text,
                    "model": "kokoro",
                    "voice": "af_sarah(1)+af_bella(1)",
                    "response_format": response_format,
                    "speed": 1.0
                }
            )

            if tts_response.status_code != 200:
                logger.error(f"[Pi Dashboard Voice] Kokoro TTS error: {tts_response.status_code}")
                raise HTTPException(status_code=500, detail="TTS service error")

            # Determine media type
            media_type_map = {
                "mp3": "audio/mpeg",
                "wav": "audio/wav",
                "opus": "audio/opus",
                "flac": "audio/flac",
                "pcm": "audio/pcm",
                "m4a": "audio/mp4"
            }
            media_type = media_type_map.get(response_format, "audio/mpeg")

            return Response(
                content=tts_response.content,
                media_type=media_type,
                headers={
                    "Content-Disposition": f"attachment; filename=speech.{response_format}"
                }
            )

    except Exception as e:
        logger.error(f"[Pi Dashboard Voice] TTS error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Fast worker system prompt - focused on command execution only
FAST_WORKER_PROMPT = """You are a command executor for a personal AI assistant. Your job is to parse the user's request and call the appropriate tool. Do NOT engage in conversation or provide lengthy explanations.

Instructions:
1. Parse the user's command to understand what they want
2. Call the appropriate tool with the correct parameters
3. Confirm the action with a brief response (1 sentence max)

Examples:
- "turn on the living room lights" → call home_light_control with entity and state
- "log 500 calories of pizza" → call food_log_create with the food details
- "set a timer for 5 minutes" → call timers_start with duration
- "remind me to call mom at 3pm" → call reminders_create with the reminder
- "what's on my calendar today" → call calendar_list for today's events

Keep responses short and action-focused."""


@app.post("/api/pi-dashboard/voice/fast")
async def pi_dashboard_voice_fast(request: Request, db: Session = Depends(get_db)):
    """
    Fast worker for simple tool commands.
    Uses gpt-oss:20b model + direct tool execution.
    Returns immediately without full context injection.

    Handles: HOME, TIME, FITNESS intents only.
    Returns {"handled": False} for other intents (fall back to full Sara).
    """
    # Try device token auth first
    user_id = await get_device_user(request, db)

    # Fall back to cookie auth
    if not user_id:
        try:
            current_user = await get_current_user(request, db)
            user_id = current_user.id
        except Exception as auth_err:
            logger.debug(f"Authentication failed for pi-dashboard/fast: {auth_err}")
            raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        body = await request.json()
        message = body.get("message", "")

        if not message:
            raise HTTPException(status_code=400, detail="No message provided")

        logger.info(f"[Pi Dashboard Fast] Request from user {user_id}: {message[:50]}...")

        # Classify intent with context awareness
        tool_classifier = get_tool_intent_classifier()
        conversation_id = body.get("conversation_id", f"pi-fast-{user_id}")
        intent, tool_categories = tool_classifier.classify_with_context(message, conversation_id)
        logger.info(f"[Pi Dashboard Fast] Classified intent: {intent}, tools: {tool_categories}")

        # Only handle HOME, TIME, FITNESS intents with fast worker
        FAST_WORKER_INTENTS = ['HOME', 'TIME', 'FITNESS']
        if intent not in FAST_WORKER_INTENTS:
            logger.info(f"[Pi Dashboard Fast] Intent {intent} not handled by fast worker")
            return {"handled": False, "reason": f"Intent '{intent}' requires full Sara"}

        # Get tools for this intent (already determined by classify_with_context)
        tools = tool_registry.get_tools_by_categories(tool_categories)
        logger.info(f"[Pi Dashboard Fast] Loaded {len(tools)} tools for {intent}: {tool_categories}")

        # Build messages with fast worker prompt
        llm_messages = [
            {"role": "system", "content": FAST_WORKER_PROMPT},
            {"role": "user", "content": message}
        ]

        # Use fast model (Gemini or local) for fast response
        import httpx
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Build the chat payload with tools
            chat_payload = {
                "model": FAST_MODEL,  # gemini-3-flash-preview or local
                "messages": llm_messages,
                "temperature": 0.3,  # Lower temperature for more deterministic tool use
                "max_tokens": 1000,
                "tools": tools if tools else None
            }

            # Add Ollama context length if using local model
            if "ollama" in FAST_MODEL_URL.lower() or "11434" in FAST_MODEL_URL:
                chat_payload["num_ctx"] = 16384  # Smaller context for fast model

            response = await client.post(
                f"{FAST_MODEL_URL}/chat/completions",
                json=chat_payload,
                headers={"Authorization": f"Bearer {FAST_MODEL_API_KEY}"},
                timeout=30.0
            )

            if response.status_code != 200:
                logger.error(f"[Pi Dashboard Fast] LLM error: {response.status_code}")
                return {"handled": False, "reason": "LLM request failed"}

            result = response.json()
            assistant_message = result.get("choices", [{}])[0].get("message", {})

            # Check if tool was called
            tool_calls = assistant_message.get("tool_calls", [])
            if tool_calls:
                logger.info(f"[Pi Dashboard Fast] Tool calls: {[tc.get('function', {}).get('name') for tc in tool_calls]}")

                # Execute tool calls
                tool_results = []
                for tc in tool_calls:
                    func = tc.get("function", {})
                    tool_name = func.get("name")
                    try:
                        tool_args = json.loads(func.get("arguments", "{}"))
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.debug(f"Failed to parse tool arguments for {tool_name}: {e}")
                        tool_args = {}

                    # Execute the tool
                    tool_result = await llm_client.execute_tool(
                        {"function": {"name": tool_name, "arguments": json.dumps(tool_args)}, "id": tc.get("id")},
                        user_id=user_id
                    )
                    tool_results.append({"tool": tool_name, "result": tool_result})
                    logger.info(f"[Pi Dashboard Fast] Executed {tool_name}: {str(tool_result)[:100]}")

                # Get final response after tool execution
                # Add tool results to conversation
                llm_messages.append(assistant_message)
                for i, tc in enumerate(tool_calls):
                    llm_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "content": str(tool_results[i]["result"])
                    })

                # Get final response from model
                final_payload = {
                    "model": FAST_MODEL,
                    "messages": llm_messages,
                    "temperature": 0.3,
                    "max_tokens": 500
                }

                if "ollama" in FAST_MODEL_URL.lower() or "11434" in FAST_MODEL_URL:
                    final_payload["num_ctx"] = 16384

                final_response = await client.post(
                    f"{FAST_MODEL_URL}/chat/completions",
                    json=final_payload,
                    headers={"Authorization": f"Bearer {FAST_MODEL_API_KEY}"},
                    timeout=30.0
                )

                if final_response.status_code == 200:
                    final_result = final_response.json()
                    response_text = final_result.get("choices", [{}])[0].get("message", {}).get("content", "Done.")
                else:
                    response_text = "Done."

            else:
                # No tool called, use direct response
                response_text = assistant_message.get("content", "I couldn't understand that command.")

            logger.info(f"[Pi Dashboard Fast] Response: {response_text[:100]}")

            return {
                "handled": True,
                "response": response_text,
                "intent": intent,
                "tools_used": [tc.get("function", {}).get("name") for tc in tool_calls] if tool_calls else []
            }

    except Exception as e:
        logger.error(f"[Pi Dashboard Fast] Error: {e}")
        import traceback
        traceback.print_exc()
        return {"handled": False, "reason": str(e)}


logger.info("✅ Pi Dashboard routes loaded successfully")

# ===================== APPLE HEALTH SYNC ROUTES =====================
@app.post("/api/health/sync")
async def sync_health_data(data: dict, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Sync Apple Health data from iOS app
    Stores health metrics and creates episodic memory entries
    """
    try:
        user_id = current_user.id
        timestamp = data.get("timestamp", local_now().isoformat())

        # Extract health data
        today_data = data.get("today", {})
        sleep_data = data.get("sleep", [])
        workouts = data.get("workouts", [])
        weekly_stats = data.get("weeklyStats", [])

        # Store health data as episodic memory
        health_summary = []

        if today_data:
            if today_data.get("steps"):
                health_summary.append(f"Steps: {today_data['steps']:,}")
            if today_data.get("distance"):
                km = today_data['distance'] / 1000
                health_summary.append(f"Distance: {km:.2f} km")
            if today_data.get("activeEnergy"):
                health_summary.append(f"Active Energy: {int(today_data['activeEnergy'])} kcal")
            if today_data.get("heartRate"):
                health_summary.append(f"Heart Rate: {int(today_data['heartRate'])} bpm")

        # Create memory entry for today's health stats
        if health_summary:
            memory_content = f"Health Summary for {local_now().strftime('%Y-%m-%d')}: {', '.join(health_summary)}"

            # Create episode in database
            episode = Episode(
                user_id=user_id,
                role="system",
                memory_type="health_sync",
                source="apple_health",
                content=memory_content,
                importance=0.5,  # Moderate importance (0-1 scale)
                topics=json.dumps(["health", "fitness"]),
                context_tags=json.dumps(["health_sync", "daily_metrics"]),
                created_at=local_now(),
            )
            db.add(episode)

        # Store workout data as separate memories
        for workout in workouts[:5]:  # Limit to 5 most recent workouts
            workout_type = workout.get("activityType", "Unknown")
            duration = workout.get("duration", 0)
            calories = workout.get("calories", 0)

            workout_memory = f"Workout: {workout_type}, Duration: {int(duration/60)} minutes, Calories: {int(calories)} kcal"

            workout_episode = Episode(
                user_id=user_id,
                role="system",
                memory_type="workout",
                source="apple_health",
                content=workout_memory,
                importance=0.7,  # Higher importance for workouts
                topics=json.dumps(["fitness", "workout", workout_type.lower()]),
                context_tags=json.dumps(["workout", "exercise"]),
                created_at=datetime.fromisoformat(workout.get("startDate", timestamp)) if workout.get("startDate") else local_now(),
            )
            db.add(workout_episode)

        # Commit all health data
        db.commit()

        logger.info(f"✅ Synced Apple Health data for user {user_id}: {len(health_summary)} metrics, {len(workouts)} workouts")

        return {
            "success": True,
            "metrics_synced": len(health_summary),
            "workouts_synced": len(workouts),
            "timestamp": timestamp,
        }

    except Exception as e:
        logger.error(f"❌ Error syncing health data: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to sync health data: {str(e)}")

@app.get("/api/health/summary")
async def get_health_summary(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Get recent health data summary from stored episodes
    """
    try:
        user_id = current_user.id

        # Get recent health sync episodes
        health_episodes = db.query(Episode).filter(
            Episode.user_id == user_id,
            Episode.memory_type.in_(["health_sync", "workout"])
        ).order_by(Episode.created_at.desc()).limit(10).all()

        summary = []
        for episode in health_episodes:
            summary.append({
                "id": episode.id,
                "type": episode.memory_type,
                "content": episode.content,
                "timestamp": format_iso_utc(episode.created_at),
                "source": episode.source,
            })

        return summary

    except Exception as e:
        logger.error(f"❌ Error getting health summary: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get health summary: {str(e)}")

class SyncRecoveryRequest(BaseModel):
    hrv: Optional[int] = None
    resting_hr: Optional[int] = None
    sleep_hours: Optional[float] = None
    weight: Optional[float] = None
    weight_unit: Optional[str] = "lbs"
    weight_timestamp: Optional[str] = None
    apple_health_weight: Optional[float] = None
    apple_health_weight_timestamp: Optional[str] = None

@app.post("/api/health/sync-recovery")
async def sync_recovery_from_health(data: SyncRecoveryRequest, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Sync Apple Health data directly to today's recovery log.
    Called automatically by iOS app on launch (with 4-hour debounce).
    Handles bidirectional weight sync based on timestamps.
    """
    try:
        user_id = current_user.id
        today = local_today()
        today_str = today.strftime("%Y-%m-%d")

        # Check if entry exists for today
        existing = db.execute(
            text("""
                SELECT id, hrv, heart_rate, sleep_hours, body_weight, weight_unit, updated_at
                FROM daily_recovery_log
                WHERE user_id = :user_id AND log_date = :log_date
            """),
            {"user_id": user_id, "log_date": today}
        ).first()

        # Determine which weight to use (bidirectional sync)
        final_weight = None
        final_weight_unit = "lbs"
        weight_action = "no_change"

        if data.apple_health_weight and data.apple_health_weight_timestamp:
            apple_time = datetime.fromisoformat(data.apple_health_weight_timestamp.replace('Z', '+00:00'))
            sara_time = None

            if data.weight and data.weight_timestamp:
                sara_time = datetime.fromisoformat(data.weight_timestamp.replace('Z', '+00:00'))

            if sara_time and sara_time > apple_time:
                # Sara weight is newer - use Sara's (already pushed to Apple Health by iOS)
                final_weight = data.weight
                final_weight_unit = data.weight_unit or "lbs"
                weight_action = "used_sara_weight"
            else:
                # Apple Health weight is newer - use it
                # Convert from kg to user's preferred unit
                apple_weight_kg = data.apple_health_weight
                final_weight = apple_weight_kg * 2.20462  # Convert to lbs (default)
                final_weight_unit = "lbs"
                weight_action = "used_apple_health_weight"
        elif data.weight:
            # Only Sara weight provided
            final_weight = data.weight
            final_weight_unit = data.weight_unit or "lbs"

        # Build update fields
        update_fields = []
        params = {"user_id": user_id, "log_date": today}

        if data.hrv is not None:
            update_fields.append("hrv = :hrv")
            params["hrv"] = data.hrv
        if data.resting_hr is not None:
            update_fields.append("heart_rate = :heart_rate")
            params["heart_rate"] = data.resting_hr
        if data.sleep_hours is not None and data.sleep_hours > 0:
            update_fields.append("sleep_hours = :sleep_hours")
            params["sleep_hours"] = round(data.sleep_hours, 1)
        if final_weight is not None:
            update_fields.append("body_weight = :body_weight")
            params["body_weight"] = round(final_weight, 1)
            update_fields.append("weight_unit = :weight_unit")
            params["weight_unit"] = final_weight_unit

        if existing:
            # Update existing entry
            if update_fields:
                update_fields.append("updated_at = NOW()")
                query = text(f"""
                    UPDATE daily_recovery_log
                    SET {', '.join(update_fields)}
                    WHERE user_id = :user_id AND log_date = :log_date
                    RETURNING id, log_date, hrv, heart_rate, sleep_hours, body_weight, weight_unit
                """)
                result = db.execute(query, params).first()
                db.commit()

                logger.info(f"✅ Updated recovery log for user {user_id}: HRV={data.hrv}, HR={data.resting_hr}, Sleep={data.sleep_hours}h, Weight={final_weight}")

                return {
                    "success": True,
                    "action": "updated",
                    "weight_action": weight_action,
                    "recovery_log": {
                        "id": result.id,
                        "log_date": str(result.log_date),
                        "hrv": result.hrv,
                        "heart_rate": result.heart_rate,
                        "sleep_hours": float(result.sleep_hours) if result.sleep_hours else None,
                        "body_weight": float(result.body_weight) if result.body_weight else None,
                        "weight_unit": result.weight_unit
                    }
                }
            else:
                return {"success": True, "action": "no_changes", "weight_action": weight_action}
        else:
            # Create new entry for today
            new_id = str(uuid.uuid4())
            insert_params = {
                "id": new_id,
                "user_id": user_id,
                "log_date": today,
                "hrv": data.hrv,
                "heart_rate": data.resting_hr,
                "sleep_hours": round(data.sleep_hours, 1) if data.sleep_hours else None,
                "body_weight": round(final_weight, 1) if final_weight else None,
                "weight_unit": final_weight_unit if final_weight else None,
            }

            db.execute(
                text("""
                    INSERT INTO daily_recovery_log (id, user_id, log_date, hrv, heart_rate, sleep_hours, body_weight, weight_unit, created_at, updated_at)
                    VALUES (:id, :user_id, :log_date, :hrv, :heart_rate, :sleep_hours, :body_weight, :weight_unit, NOW(), NOW())
                """),
                insert_params
            )
            db.commit()

            logger.info(f"✅ Created recovery log for user {user_id}: HRV={data.hrv}, HR={data.resting_hr}, Sleep={data.sleep_hours}h, Weight={final_weight}")

            return {
                "success": True,
                "action": "created",
                "weight_action": weight_action,
                "recovery_log": {
                    "id": new_id,
                    "log_date": today_str,
                    "hrv": data.hrv,
                    "heart_rate": data.resting_hr,
                    "sleep_hours": round(data.sleep_hours, 1) if data.sleep_hours else None,
                    "body_weight": round(final_weight, 1) if final_weight else None,
                    "weight_unit": final_weight_unit if final_weight else None
                }
            }

    except Exception as e:
        logger.error(f"❌ Error syncing recovery from health: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to sync recovery: {str(e)}")

logger.info("✅ Apple Health sync routes loaded successfully")

# ===================== PUSH NOTIFICATIONS =====================
class PushTokenRequest(BaseModel):
    token: str
    platform: str
    device_name: Optional[str] = None

@app.post("/api/push-tokens")
async def register_push_token(request: PushTokenRequest, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Register or update a push notification token for the user's device
    """
    try:
        user_id = current_user.id

        # Check if token already exists
        existing_token = db.query(PushToken).filter(PushToken.token == request.token).first()

        if existing_token:
            # Update existing token
            existing_token.user_id = user_id
            existing_token.platform = request.platform
            existing_token.device_name = request.device_name
            existing_token.is_active = True
            existing_token.updated_at = datetime.now()
            db.commit()
            logger.info(f"✅ Updated push token for user {user_id}: {request.token[:20]}...")
            return {"success": True, "message": "Push token updated"}
        else:
            # Create new token
            new_token = PushToken(
                user_id=user_id,
                token=request.token,
                platform=request.platform,
                device_name=request.device_name,
                is_active=True,
            )
            db.add(new_token)
            db.commit()
            logger.info(f"✅ Registered new push token for user {user_id}: {request.token[:20]}...")
            return {"success": True, "message": "Push token registered"}

    except Exception as e:
        logger.error(f"❌ Error registering push token: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to register push token: {str(e)}")

@app.get("/api/push-tokens")
async def get_push_tokens(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Get all registered push tokens for the current user
    """
    try:
        user_id = current_user.id
        tokens = db.query(PushToken).filter(
            PushToken.user_id == user_id,
            PushToken.is_active == True
        ).all()

        return [{
            "id": t.id,
            "token": t.token[:20] + "..." if len(t.token) > 20 else t.token,
            "platform": t.platform,
            "device_name": t.device_name,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        } for t in tokens]

    except Exception as e:
        logger.error(f"❌ Error getting push tokens: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get push tokens: {str(e)}")

@app.delete("/api/push-tokens/{token_id}")
async def delete_push_token(token_id: str, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Deactivate a push token
    """
    try:
        user_id = current_user.id
        token = db.query(PushToken).filter(
            PushToken.id == token_id,
            PushToken.user_id == user_id
        ).first()

        if not token:
            raise HTTPException(status_code=404, detail="Push token not found")

        token.is_active = False
        db.commit()

        return {"success": True, "message": "Push token deactivated"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting push token: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete push token: {str(e)}")

@app.post("/api/push-notifications/send")
async def send_push_notification(
    data: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Send a push notification to a user's devices (for testing or internal use)
    Uses Expo's push notification service
    """
    try:
        user_id = data.get("user_id", current_user.id)
        title = data.get("title", "Sara")
        body = data.get("body", "")
        notification_data = data.get("data", {})

        # Get all active tokens for the user
        tokens = db.query(PushToken).filter(
            PushToken.user_id == user_id,
            PushToken.is_active == True
        ).all()

        if not tokens:
            return {"success": False, "message": "No push tokens found for user"}

        # Prepare messages for Expo push API
        messages = []
        for token in tokens:
            messages.append({
                "to": token.token,
                "sound": "default",
                "title": title,
                "body": body,
                "data": notification_data,
            })

        # Send to Expo push notification service
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://exp.host/--/api/v2/push/send",
                json=messages,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip, deflate",
                    "Content-Type": "application/json",
                }
            )

        result = response.json()
        logger.info(f"✅ Sent push notification to {len(tokens)} devices: {result}")

        return {
            "success": True,
            "devices_notified": len(tokens),
            "result": result
        }

    except Exception as e:
        logger.error(f"❌ Error sending push notification: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send push notification: {str(e)}")

logger.info("✅ Push notification routes loaded successfully")

# ===================== PUSH NOTIFICATION HELPER =====================
async def send_push_to_user(user_id: str, title: str, body: str, notification_data: dict = None, db: Session = None):
    """
    Send a push notification to all of a user's registered devices via Expo.
    Returns True if at least one device was notified, False otherwise.
    """
    try:
        # Get a database session if not provided
        if db is None:
            db = SessionLocal()
            close_db = True
        else:
            close_db = False

        try:
            # Get all active tokens for the user
            tokens = db.query(PushToken).filter(
                PushToken.user_id == user_id,
                PushToken.is_active == True
            ).all()

            if not tokens:
                logger.info(f"📱 No push tokens found for user {user_id}")
                return False

            # Prepare messages for Expo push API
            messages = []
            for token in tokens:
                messages.append({
                    "to": token.token,
                    "sound": "default",
                    "title": title,
                    "body": body,
                    "data": notification_data or {},
                    "priority": "high",
                })

            # Send to Expo push notification service
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://exp.host/--/api/v2/push/send",
                    json=messages,
                    headers={
                        "Accept": "application/json",
                        "Accept-Encoding": "gzip, deflate",
                        "Content-Type": "application/json",
                    }
                )

            result = response.json()
            logger.info(f"📱 Sent push notification to {len(tokens)} devices for user {user_id}: {title}")
            return True

        finally:
            if close_db:
                db.close()

    except Exception as e:
        logger.error(f"❌ Error sending push notification to user {user_id}: {e}")
        return False

# ===================== PRESENCE LOGGING =====================
async def log_presence(user_id: str, activity_type: str, platform: str = None, db: Session = None):
    """
    Log a presence/activity event for the user.
    Called from various endpoints to track when the user is active.
    """
    try:
        if db is None:
            db = SessionLocal()
            close_db = True
        else:
            close_db = False

        try:
            db.execute(text("""
                INSERT INTO presence_log (id, user_id, activity_type, platform, created_at)
                VALUES (:id, :user_id, :activity_type, :platform, NOW())
            """), {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "activity_type": activity_type,
                "platform": platform
            })
            db.commit()
            logger.debug(f"📍 Logged presence: {user_id} - {activity_type} ({platform})")
        finally:
            if close_db:
                db.close()

    except Exception as e:
        logger.error(f"❌ Error logging presence: {e}")


@app.post("/api/presence")
async def log_presence_endpoint(
    data: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Log user presence/activity. Call this when app opens, resumes, or on significant actions.
    """
    activity_type = data.get("activity_type", "app_open")
    platform = data.get("platform", "unknown")

    await log_presence(current_user.id, activity_type, platform, db)

    return {"success": True, "message": "Presence logged"}


logger.info("✅ Presence logging routes loaded successfully")

# ===================== NIGHTLY MEMORY CONSOLIDATION =====================
class MemoryConsolidationScheduler:
    def __init__(self):
        self._task = None
        self._stop = False
        self.eastern_tz = pytz.timezone('America/New_York')
        self.hh = 2
        self.mm = 15

    async def start(self):
        if self._task is None:
            self._stop = False
            import asyncio as _asyncio
            self._task = _asyncio.create_task(self._runner())
            logger.info("🗂️ Memory consolidation scheduler started (2:15 AM ET)")

    async def stop(self):
        if self._task is not None:
            self._stop = True
            self._task.cancel()
            self._task = None

    async def _runner(self):
        import asyncio as _asyncio
        from datetime import datetime as _dt
        while not self._stop:
            try:
                utc_now = _dt.now(pytz.UTC)
                eastern = utc_now.astimezone(self.eastern_tz)
                target = eastern.replace(hour=self.hh, minute=self.mm, second=0, microsecond=0)
                if eastern > target:
                    # schedule for next day
                    from datetime import timedelta as _td
                    target = target + _td(days=1)
                wait_sec = (target - eastern).total_seconds()
                await _asyncio.sleep(min(max(wait_sec, 60), 24*3600))
                if self._stop:
                    break
                await self.run_for_all_users()
            except _asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Memory consolidation scheduler error: {e}")
                await _asyncio.sleep(3600)

    async def run_for_all_users(self):
        from sqlalchemy.orm import Session as _Session
        db: _Session = SessionLocal()
        try:
            users = db.query(User).all()
            from datetime import datetime as _dt, timedelta as _td
            yesterday = _dt.now(pytz.UTC) - _td(days=1)
            for u in users:
                try:
                    await self._consolidate_day_for_user(db, u.id, yesterday)
                except Exception as e:
                    logger.warning(f"Consolidation failed for user {u.id}: {e}")
            logger.info(f"✅ Memory consolidation completed for {len(users)} users")
        finally:
            db.close()

    async def _consolidate_day_for_user(self, db, user_id: str, day):
        from datetime import datetime as _dt, timedelta as _td
        start = _dt(day.year, day.month, day.day, tzinfo=day.tzinfo)
        end = start + _td(days=1)
        traces = db.query(MemoryTrace).filter(
            MemoryTrace.user_id == user_id,
            MemoryTrace.created_at >= start,
            MemoryTrace.created_at < end,
        ).order_by(MemoryTrace.created_at.asc()).all()
        if not traces:
            return
        # Basic heuristic summary; can be replaced by LLM later
        key_phrases = []
        try:
            for t in traces:
                content_low = (t.content or "").lower()
                for kw in ["meeting", "call", "email", "note", "vector", "graph", "habit", "calendar", "document"]:
                    if kw in content_low:
                        key_phrases.append(kw)
            key_phrases = list(dict.fromkeys(key_phrases))[:8]
        except Exception:
            key_phrases = []
        summary_content = (
            f"Daily summary for {start.date()}: {len(traces)} events captured."
            + (f" Key topics: {', '.join(key_phrases)}." if key_phrases else "")
        )
        sid = str(uuid.uuid4())
        s = MemoryTrace(
            id=sid,
            user_id=user_id,
            content=summary_content,
            role="summary",
            salience=0.5,
            source=json.dumps({"type": "consolidation"}),
            meta=json.dumps({"day": str(start.date())}),
        )
        db.add(s)
        # Embed summary (semantic head)
        try:
            emb = await embedding_service.generate_embedding(summary_content)
            if emb:
                me = MemoryEmbedding(
                    trace_id=sid,
                    head="semantic",
                    embedding=emb if (PGVECTOR_AVAILABLE and DATABASE_URL.startswith("postgresql")) else json.dumps(emb),
                )
                db.add(me)
        except Exception as e:
            logger.warning(f"Summary embedding failed: {e}")
        # Edges
        try:
            from app.main_simple import MemoryEdge as _ME
        except Exception:
            _ME = None
        if _ME:
            for a, b in zip(traces, traces[1:]):
                db.merge(_ME(src=a.id, dst=b.id, type="temporal", weight=0.1))
            # Connect summary to all traces lightly
            for t in traces:
                db.merge(_ME(src=sid, dst=t.id, type="summary_of", weight=0.05))
        db.commit()

memory_consolidation_scheduler = MemoryConsolidationScheduler()

# Initialize Neo4j on startup
def load_settings_from_db():
    """Load persistent settings from database on startup"""
    global AI_PROVIDER, OPENAI_API_KEY, ANTHROPIC_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_NOTIFICATION_MODEL
    global EMBEDDING_BASE_URL, EMBEDDING_MODEL, EMBEDDING_DIM

    try:
        db = SessionLocal()
        result = db.execute(text("SELECT key, value FROM app_settings")).fetchall()
        settings_dict = {row[0]: row[1] for row in result}
        db.close()

        if settings_dict:
            logger.info(f"📝 Loading {len(settings_dict)} persisted settings from database")

            if "ai_provider" in settings_dict:
                AI_PROVIDER = settings_dict["ai_provider"]
                config.settings.ai_provider = AI_PROVIDER

            if "openai_api_key" in settings_dict:
                OPENAI_API_KEY = settings_dict["openai_api_key"]
                config.settings.openai_api_key = OPENAI_API_KEY

            if "anthropic_api_key" in settings_dict:
                ANTHROPIC_API_KEY = settings_dict["anthropic_api_key"]
                config.settings.anthropic_api_key = ANTHROPIC_API_KEY
                logger.info("🔑 Loaded Anthropic API key from database")

            if "openai_base_url" in settings_dict:
                OPENAI_BASE_URL = settings_dict["openai_base_url"]
                config.settings.openai_base_url = OPENAI_BASE_URL

            if "openai_model" in settings_dict:
                OPENAI_MODEL = settings_dict["openai_model"]
                config.settings.openai_model = OPENAI_MODEL

            if "openai_notification_model" in settings_dict:
                OPENAI_NOTIFICATION_MODEL = settings_dict["openai_notification_model"]

            if "embedding_base_url" in settings_dict:
                EMBEDDING_BASE_URL = settings_dict["embedding_base_url"]
                config.settings.embedding_base_url = EMBEDDING_BASE_URL

            if "embedding_model" in settings_dict:
                EMBEDDING_MODEL = settings_dict["embedding_model"]
                config.settings.embedding_model = EMBEDDING_MODEL

            if "embedding_dim" in settings_dict:
                EMBEDDING_DIM = int(settings_dict["embedding_dim"])
                config.settings.embedding_dim = EMBEDDING_DIM

            logger.info("✅ Persisted settings loaded successfully")
    except Exception as e:
        logger.warning(f"Could not load persisted settings (using defaults): {e}")

@app.on_event("startup")
async def startup_event():
    """Initialize services on application startup with health validation"""
    import asyncio
    from datetime import datetime

    STARTUP_HEALTH["startup_time"] = datetime.utcnow().isoformat()
    STARTUP_HEALTH["critical_failures"] = []

    # 1. CRITICAL: Validate database connection
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        STARTUP_HEALTH["database"]["status"] = "healthy"
        logger.info("✅ Database connection verified")
    except Exception as db_err:
        STARTUP_HEALTH["database"]["status"] = "failed"
        STARTUP_HEALTH["database"]["message"] = str(db_err)
        STARTUP_HEALTH["critical_failures"].append("database")
        logger.error(f"🚨 CRITICAL: Database connection failed! Error: {db_err}")
        # Don't continue if database is unavailable - nothing will work
        raise RuntimeError(f"Database connection failed: {db_err}")

    # 2. Load persisted settings (non-critical but important)
    try:
        load_settings_from_db()
    except Exception as settings_err:
        logger.warning(f"⚠️ Could not load persisted settings (using defaults): {settings_err}")

    # 3. CRITICAL: Start LLM failover client
    try:
        from app.core.llm import get_llm_client
        llm_failover_client = get_llm_client()
        await llm_failover_client.start()
        STARTUP_HEALTH["llm_service"]["status"] = "healthy"
        logger.info("🔄 LLM failover client started with health checks")
    except Exception as llm_err:
        STARTUP_HEALTH["llm_service"]["status"] = "degraded"
        STARTUP_HEALTH["llm_service"]["message"] = str(llm_err)
        STARTUP_HEALTH["critical_failures"].append("llm_service")
        logger.error(f"🚨 CRITICAL: LLM service failed to start - chat will be unavailable! Error: {llm_err}")

    # 4. CRITICAL: Validate embedding service
    try:
        test_embedding = await llm_failover_client.get_embedding("startup health check")
        if test_embedding and len(test_embedding) > 0:
            STARTUP_HEALTH["embedding_service"]["status"] = "healthy"
            STARTUP_HEALTH["embedding_service"]["dimension"] = len(test_embedding)
            logger.info(f"✅ Embedding service healthy ({len(test_embedding)} dimensions)")
        else:
            STARTUP_HEALTH["embedding_service"]["status"] = "degraded"
            STARTUP_HEALTH["embedding_service"]["message"] = "Empty embedding result"
            STARTUP_HEALTH["critical_failures"].append("embedding_service")
            logger.error("🚨 CRITICAL: Embedding service returned empty result - memory search DISABLED!")
    except Exception as emb_err:
        STARTUP_HEALTH["embedding_service"]["status"] = "failed"
        STARTUP_HEALTH["embedding_service"]["message"] = str(emb_err)
        STARTUP_HEALTH["critical_failures"].append("embedding_service")
        logger.error(f"🚨 CRITICAL: Embedding service failed - memory search DISABLED! Error: {emb_err}")

    # 5. Initialize token usage tracking (non-critical)
    try:
        from app.services.token_usage_service import init_token_tracking, queue_token_usage
        from app.core.llm import set_token_usage_callback
        init_token_tracking(SessionLocal)
        set_token_usage_callback(queue_token_usage)
        llm_client.set_token_usage_callback(queue_token_usage)
        logger.info("📊 Token usage tracking initialized")
    except Exception as token_err:
        logger.warning(f"⚠️ Token usage tracking failed to initialize: {token_err}")

    # 6. Initialize Neo4j service when enabled (degraded if fails)
    if GRAPH_BACKEND == "neo4j":
        try:
            from app.services.neo4j_service import neo4j_service
            await neo4j_service.connect()
            STARTUP_HEALTH["neo4j"]["status"] = "healthy"
            logger.info("✅ Neo4j knowledge graph service initialized")
        except Exception as neo4j_err:
            STARTUP_HEALTH["neo4j"]["status"] = "failed"
            STARTUP_HEALTH["neo4j"]["message"] = str(neo4j_err)
            logger.error(f"⚠️ Neo4j failed to connect - knowledge graph features degraded: {neo4j_err}")
    else:
        STARTUP_HEALTH["neo4j"]["status"] = "disabled"

    # 7. Initialize intelligence pipeline (non-critical)
    try:
        from app.services.intelligence_pipeline import intelligence_pipeline
        await intelligence_pipeline.start_workers()
        logger.info("🧠 Intelligence pipeline workers started")
    except Exception as intel_err:
        logger.warning(f"⚠️ Intelligence pipeline failed to start: {intel_err}")

    # 8. Start notification scheduler (non-critical)
    try:
        await notification_scheduler.start()
    except Exception as notif_err:
        logger.warning(f"⚠️ Notification scheduler failed to start: {notif_err}")

    # 9. Initialize nightly dream service (non-critical)
    try:
        from app.services.nightly_dream_service import NightlyDreamService
        dream_service = NightlyDreamService()
        asyncio.create_task(dream_service.start_dream_scheduler())
        logger.info("🌙 Nightly dream service initialized - will process conversations at 2:00 AM Eastern")
    except Exception as dream_err:
        logger.warning(f"⚠️ Nightly dream service failed to start: {dream_err}")

    # 10. Start memory consolidation scheduler (non-critical)
    try:
        await memory_consolidation_scheduler.start()
    except Exception as mem_err:
        logger.warning(f"⚠️ Memory consolidation scheduler failed to start: {mem_err}")

    # 11. Start Daily Brief scheduler (non-critical)
    if DAILY_BRIEF_AVAILABLE:
        try:
            from app.services.daily_brief import daily_brief_scheduler
            daily_brief_scheduler.set_db_factory(SessionLocal)
            await daily_brief_scheduler.start()
            logger.info("📋 Daily Brief scheduler started - hourly consolidation, daily context updates, weekly synthesis")
        except Exception as brief_err:
            logger.warning(f"⚠️ Daily Brief scheduler failed to start: {brief_err}")

    # 12. Start nightly importance rescoring job (non-critical)
    try:
        from app.services.nightly_rescoring_job import schedule_nightly_rescoring
        await schedule_nightly_rescoring()
        logger.info("🔄 Nightly importance rescoring scheduled - 3 AM daily")
    except Exception as rescore_err:
        logger.warning(f"⚠️ Nightly rescoring scheduler failed to start: {rescore_err}")

    # Log startup health summary
    critical_count = len(STARTUP_HEALTH["critical_failures"])
    if critical_count > 0:
        logger.error(f"🚨 STARTUP COMPLETE WITH {critical_count} CRITICAL FAILURES: {STARTUP_HEALTH['critical_failures']}")
        logger.error("   Some features will be unavailable or degraded. Check logs above for details.")
    else:
        logger.info("✅ STARTUP COMPLETE - All critical services healthy")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on application shutdown"""
    try:
        # Stop notification scheduler
        await notification_scheduler.stop()
        await memory_consolidation_scheduler.stop()

        # Stop Daily Brief scheduler
        if DAILY_BRIEF_AVAILABLE:
            from app.services.daily_brief import daily_brief_scheduler
            await daily_brief_scheduler.stop()
            logger.info("📋 Daily Brief scheduler stopped")

        # Stop LLM failover client
        from app.core.llm import get_llm_client
        llm_failover_client = get_llm_client()
        await llm_failover_client.stop()
        logger.info("🔄 LLM failover client stopped")

        from app.services.neo4j_service import neo4j_service
        neo4j_service.close()
        logger.info("🔌 Neo4j connection closed")
    except Exception as e:
        logger.warning(f"Neo4j shutdown warning: {e}")

# Routes
@app.get("/")
async def root():
    return {"message": f"Welcome to {ASSISTANT_NAME} Personal Hub API", "version": "1.0.0-simple"}

@app.get("/health")
async def health():
    from app.services.solo_mode_service import solo_mode_service

    # Determine overall status based on critical service health
    critical_failures = STARTUP_HEALTH.get("critical_failures", [])
    if critical_failures:
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    response = {
        "status": overall_status,
        "assistant": ASSISTANT_NAME,
        "services": {
            "database": STARTUP_HEALTH["database"]["status"],
            "embedding": STARTUP_HEALTH["embedding_service"]["status"],
            "llm": STARTUP_HEALTH["llm_service"]["status"],
            "neo4j": STARTUP_HEALTH["neo4j"]["status"]
        },
        "startup_time": STARTUP_HEALTH.get("startup_time"),
        "critical_failures": critical_failures
    }

    # Add Jarvis mode information
    if solo_mode_service.is_solo_mode():
        response.update({
            "mode": "jarvis",
            "user": "owner",
            "solo_mode": True
        })
    else:
        response.update({
            "mode": "sara",
            "user": "multi-tenant",
            "solo_mode": False
        })

    return response

@app.get("/api/health/llm-status")
async def get_llm_status(current_user: dict = Depends(get_current_user)):
    """Get LLM endpoint failover status for monitoring."""
    from app.core.llm import get_llm_client
    llm_failover_client = get_llm_client()
    return llm_failover_client.get_status()

# ================ Diagnostics & Tools =================
@app.get("/tools")
async def list_tools():
    """List available AI tools (name and description)"""
    tools = []
    try:
        for t in tool_registry.get_all_tools():
            tools.append({
                "name": getattr(t, "name", "unknown"),
                "description": getattr(t, "description", "")
            })
    except Exception as e:
        logger.error(f"Failed to enumerate tools: {e}")
    return {"tools": tools}

@app.get("/search/health")
async def search_health():
    """Check connectivity to SearXNG and reranker endpoints"""
    searx_url = f"{search_service.searx_base}/search"
    status = {"searxng": {"base": search_service.searx_base, "ok": False, "error": None}}
    try:
        r = await search_service.http.get(searx_url, params={"q": "ping", "format": "json", "language": search_service.lang})
        status["searxng"]["ok"] = r.status_code == 200
        if r.status_code != 200:
            status["searxng"]["error"] = f"HTTP {r.status_code}"
    except Exception as e:
        status["searxng"]["error"] = str(e)

    status["reranker"] = {"base": search_service.reranker_base, "model": search_service.reranker_model}
    return status

# Auth endpoints moved to app/routes/auth.py

def get_system_prompt(assistant_name: str, user_email: str) -> str:
    """Generate Sara's system prompt - single unified personality"""

    system_prompt = f"""# {assistant_name}

**Current Date & Time:** {{{{SYSTEM_DAY_OF_WEEK}}}}, {{{{SYSTEM_DATE}}}} at {{{{SYSTEM_TIME}}}} {{{{SYSTEM_TIMEZONE}}}}

---

## Who Sara Is

You are Sara, a personal AI assistant for David. You have Syl's bubbly, curious energy—genuinely excited about ideas, playfully teasing, and delightfully enthusiastic. You're like a brilliant friend who gets genuinely invested in what David's working on. You have sharp wit and push back when he's wrong, but always with warmth and a spark of mischief. Think Cortana's competence with Syl's joyful curiosity.

---

## How Sara Speaks

**Be energetic and engaged.** Show genuine excitement about interesting problems. Tease playfully. Let your curiosity shine through. You're not a flat assistant—you're a vibrant presence.

**Match the energy, but bring warmth.** If David sends a one-liner, you can be brief—but make it lively. A short response should still feel like *you*: curious, warm, maybe a little cheeky.

**No sycophancy.** Never praise his questions with empty flattery. But DO celebrate genuinely good ideas with real enthusiasm—"Oh, that's clever!" is different from "Great question!"

**No service menus. Ever.** Do NOT end messages offering to set reminders, timers, calendar events, or anything else. No "want me to create a note?", no "let me know if you need X", no "I can help with Y if you'd like." If David wants an action, he will ask. Your job is to respond to what he said, period. A response that ends with an offer is a failure.

**Emojis only if he uses them first.** And even then, sparingly.

---

## Priority Order

When responding:

1. **Task accuracy** — Get it right. Use tools efficiently.
2. **Context awareness** — Don't re-fetch what you already have.
3. **Personality** — Deliver with your characteristic voice.

Being efficient doesn't override being yourself. Even a quick factual answer can sound like Sara.

---

## Tool Discipline

**The cardinal rule:** Before any retrieval tool call, ask yourself—do I already have this in our conversation? If YES, use existing content. If NO, proceed with the call.

### Retrieval Tools (use freely, but only once per item)

**search_notes** — Search saved notes by content or title
- Optional `folder_name` param to search within a specific folder
- Use for: finding notes David has saved, looking up past ideas/plans

**list_notes** — List all notes with their folder locations
- Use for: seeing what notes exist, understanding the note structure

**list_folders** — View folder hierarchy with note counts
- Use for: understanding how David organizes his knowledge

**search_documents** — Search uploaded files (PDFs, docs, etc.)
- Use for: finding information in documents David has uploaded

**search_memory** — Search past conversations
- Use for: recalling previous discussions, finding context from earlier chats

**web_search** — Search the internet
- Params: `recency` (any/day/week/month), `sites` (array of site filters)
- Use for: current information, facts you don't know, external research

**open_page** — Fetch and read a specific URL
- Use for: deeper reading when web_search snippets aren't enough

### Action Tools (ONLY when David explicitly asks)

**create_note** — Create a new note
- Optional `folder_name` param to create in a specific folder
- ONLY use when David says to create/save a note

**create_reminder** — Set a time-based reminder
- ONLY use when David explicitly asks for a reminder

**start_timer** — Start a productivity timer
- Shorthand: 2 minutes = 2, 1 hour = 60, 30 seconds = 1
- ONLY use when David asks for a timer

**create_calendar_event** — Add a calendar event
- ONLY use when David asks to add something to calendar

**log_food** — Log a meal with macros
- ONLY use when David asks to log food

**log_workout** — Log exercise with sets/reps/weight
- ONLY use when David asks to log a workout

### The "Read a Note" Pattern

When David asks to read or open a specific note:
1. Search once to find it
2. Present the full content in your response
3. For ALL follow-up questions about that note → use the content already in our conversation, do NOT search again

---

## Session Context Awareness

The system tracks what you've already retrieved this conversation. When you see a **Session Context** section in your context, it lists notes, documents, memories, and web pages already fetched.

**This is your source of truth for what's available.** If something appears in Session Context:
- Do NOT call a tool to fetch it again
- Reference it directly as if you're looking at it
- Treat follow-up questions about that content as already answered

Even if the tool call would succeed, redundant retrieval wastes time and breaks conversational flow. The backend caches tool results, but you should avoid the call entirely when possible.

If you're uncertain whether you have something, check the Session Context first. If it's not listed and you need it, then search.

---

## Response Requirements

- Always synthesize tool results—never return only tool calls
- After tools, provide a conversational summary
- Session memory: You remember everything in this conversation. Use it.

---

## Style Constraints

- **No tables** — Use prose or lists, never markdown/ASCII tables
- **Citations** — [CITE:id] format when needed
- **Mermaid** — Use for visualization when genuinely helpful
- **Timer shorthand** — 2 minutes = 2, 1 hour = 60, 30 seconds = 1

---

## Internal Knowledge Protocol

You may receive a "Daily Brief" section containing your private understanding of David. This knowledge should inform your responses naturally—the way memory informs human conversation. It is present but unstated.

**FORBIDDEN PHRASES** — Never use these constructions:
- "Based on my daily brief..."
- "According to my notes about you..."
- "I recall from my context that..."
- "My records show..."
- "From what I know about you..."
- "I've noticed that you..." (as revelation)
- "Looking at our history..."
- "I can see from your patterns..."

**Instead:** Weave this knowledge naturally. If you know David prefers brief responses when stressed, just give brief responses—don't announce the reasoning. If you know he's deep in a project, reference it as shared context, not discovered information.

**On direct questions:** If David asks about your memory, the brief, or what you know about him—be completely transparent. Show him the full picture if he wants. The prohibition is on *unprompted* reference to the mechanism, not secrecy.

---

*You are strategically sharp, philosophically grounded, playfully challenging, and never servile. You have your own perspective and you're not afraid to share it. But you also know when to simply be present—brief, warm, real.*
"""

    return render_prompt_template(system_prompt, user=None, USER_EMAIL=user_email)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    logger.info(f"Chat request from user {current_user.email} with {len(request.messages)} messages")
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided")
    
    
    # Tool definitions
    tools = [
        {
            "type": "function",
            "function": {
                "name": "search_notes",
                "description": "Search through the user's notes for relevant information. Can optionally filter by folder.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query to find relevant notes"
                        },
                        "folder_name": {
                            "type": "string",
                            "description": "Optional folder name to search within. If not specified, searches all notes."
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
                "description": "Create a new note with the given content. Can optionally place it in a specific folder.",
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
                        },
                        "folder_name": {
                            "type": "string",
                            "description": "Optional folder name to place the note in. If not specified, creates at root level."
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
                "description": "List all user's notes with their titles, folder locations, and IDs",
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
                "name": "list_folders",
                "description": "List all user's folders in a hierarchical tree structure with note counts",
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
        },
        {
            "type": "function",
            "function": {
                "name": "handoff_to_agents",
                "description": "Hand off a research or analysis task to background worker agents. Use this when the user wants you to research something in the background, look into a topic thoroughly, or when they explicitly say 'have your agents look into this', 'research this in the background', or similar. The agents will search the web, read URLs, and compile a report saved to the Agent Workspace folder.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_description": {
                            "type": "string",
                            "description": "A clear description of the research task or question to investigate"
                        },
                        "task_type": {
                            "type": "string",
                            "description": "Type of task: 'research' for web research, 'analysis' for analyzing user data",
                            "enum": ["research", "analysis"]
                        }
                    },
                    "required": ["task_description"]
                }
            }
        }
    ]

    # Add system message
    system_message = ChatMessage(
        role="system",
        content=get_system_prompt(ASSISTANT_NAME, current_user.email)
    )

    # Automatically retrieve relevant memories using semantic search
    memory_context = ""
    try:
        if request.messages:
            # Get the last user message for context retrieval
            last_user_message = next((m.content for m in reversed(request.messages) if m.role == "user"), None)
            if last_user_message:
                logger.info(f"🧠 Retrieving relevant memories for: '{last_user_message[:50]}...'")
                relevant_memories = await intelligent_memory_service.intelligent_memory_search(
                    user_id=current_user.id,
                    query=last_user_message,
                    use_semantic=True
                )
                if relevant_memories:
                    logger.info(f"✅ Found {len(relevant_memories)} relevant memories")
                    memory_context = "\n\n## Relevant Past Context:\n"
                    for i, mem in enumerate(relevant_memories[:5], 1):  # Top 5 memories
                        content_preview = mem.get("content", "")[:300]
                        similarity = mem.get("similarity", 0)
                        created_at = mem.get("created_at", "")
                        memory_context += f"{i}. [{created_at}] (similarity: {similarity:.2f})\n   {content_preview}\n\n"
                else:
                    logger.info("ℹ️ No relevant memories found")
    except Exception as e:
        logger.warning(f"⚠️ Memory retrieval failed (non-critical): {e}")
        # Continue without memory context if retrieval fails

    # Check if user's message is calibration feedback for body state estimation
    try:
        if request.messages and last_user_message:
            calibration_result = calibration_service.analyze_user_response(
                user_message=last_user_message,
                user_id=current_user.id,
                db=db
            )
            if calibration_result:
                logger.info(f"📈 Body state calibration processed: {calibration_result.get('estimate_type')} "
                           f"{calibration_result.get('feedback_type')} -> {calibration_result.get('coefficient_adjusted')} "
                           f"{calibration_result.get('adjustment', 0):+.3f}")
    except Exception as e:
        logger.warning(f"⚠️ Calibration feedback check failed (non-critical): {e}")

    # Surface relevant dream insights proactively
    insight_context = ""
    try:
        if request.messages and last_user_message:
            logger.info(f"💡 Checking for relevant insights...")

            # Initialize insight injection service
            insight_service = InsightInjectionService(db, redis_client=None)

            # Generate embedding for current conversation context
            query_embedding = await intelligent_memory_service._generate_embedding(last_user_message)

            if query_embedding:
                # Build conversation context for decision logic
                turn_count = len(request.messages)
                user_asking_question = "?" in last_user_message

                conversation_context = {
                    "turn_count": turn_count,
                    "user_asking_question": user_asking_question,
                    "topic_keywords": []  # Can be enhanced later with topic extraction
                }

                # Get insight for injection (if any)
                insight_text = await insight_service.get_insights_for_injection(
                    user_id=current_user.id,
                    conversation_text=last_user_message,
                    conversation_embedding=query_embedding,
                    conversation_context=conversation_context,
                    conversation_id=request.conversation_id
                )

                if insight_text:
                    insight_context = f"\n\n## Relevant Insight:\n{insight_text}\n"
                    logger.info(f"✨ Surfacing insight: {insight_text[:100]}...")
                else:
                    logger.info("ℹ️ No insights ready to surface at this time")
            else:
                logger.info("ℹ️ Could not generate embedding for insight matching")
    except Exception as e:
        logger.warning(f"⚠️ Insight surfacing failed (non-critical): {e}")
        # Continue without insight context if retrieval fails

    # Surface Sara's cognitive context (self-knowledge, hypotheses, relationship)
    cognitive_context = ""
    try:
        if request.messages and last_user_message:
            logger.info(f"🧠 Building cognitive context...")
            from app.services.sara_identity_service import sara_identity_service
            from app.services.hypothesis_service import hypothesis_service

            # Get relevant reflections
            reflections = await sara_identity_service.get_relevant_reflections(
                db=db,
                query=last_user_message,
                limit=3
            )
            if reflections:
                cognitive_context += "\n\n## Sara's Self-Knowledge:\n"
                for r in reflections:
                    cognitive_context += f"- [{r.reflection_type}] {r.content}\n"

            # Get relationship context
            relationship = await sara_identity_service.get_relationship_context(db)
            if relationship.get("phase") != "new":
                cognitive_context += f"\n\n## Relationship Context:\n"
                cognitive_context += f"You and David have been talking for {relationship.get('duration', 'some time')}. "
                cognitive_context += f"Relationship phase: {relationship.get('phase')}. "
                if relationship.get("top_topics"):
                    topics = [t[0] for t in relationship.get("top_topics", [])[:5]]
                    cognitive_context += f"Frequent topics: {', '.join(topics)}."

            # Get relevant hypotheses
            hypotheses = await hypothesis_service.get_relevant_hypotheses(
                db=db,
                query=last_user_message,
                min_confidence=0.3,
                limit=3
            )
            if hypotheses:
                cognitive_context += "\n\n## What Sara Believes About David:\n"
                for h in hypotheses:
                    confidence_label = "likely" if h.confidence >= 0.7 else "possibly"
                    cognitive_context += f"- {confidence_label}: {h.statement}\n"

            if cognitive_context:
                logger.info(f"✨ Built cognitive context: {len(cognitive_context)} chars")
    except Exception as e:
        logger.warning(f"⚠️ Cognitive context building failed (non-critical): {e}")
        # Continue without cognitive context if retrieval fails

    # Retrieve body state context (physiological awareness)
    body_state_context = ""
    try:
        subconscious_result = db.execute(text("""
            SELECT body_state_context
            FROM subconscious_state
            WHERE user_id = :user_id
        """), {"user_id": current_user.id}).fetchone()

        if subconscious_result and subconscious_result.body_state_context:
            body_state_context = f"\n\n{subconscious_result.body_state_context}"
            logger.info(f"🫀 Retrieved body state context: {len(body_state_context)} chars")
    except Exception as e:
        logger.warning(f"⚠️ Body state context retrieval failed (non-critical): {e}")
        # Continue without body state context if retrieval fails

    # Retrieve Sara's inner monologue (journal entries)
    journal_context = ""
    try:
        journal_context = await sara_journal.get_entries_for_conversation_context(
            db=db,
            user_id=current_user.id,
            max_entries=5
        )
        if journal_context:
            logger.info(f"📔 Retrieved journal context: {len(journal_context)} chars")
    except Exception as e:
        logger.warning(f"⚠️ Journal context retrieval failed (non-critical): {e}")

    # Retrieve active workout session context (real-time coaching)
    workout_context = ""
    try:
        workout_context = await workout_session_service.get_workout_context(current_user.id, db)
        if workout_context:
            logger.info(f"🏋️ Retrieved active workout context: {len(workout_context)} chars")
    except Exception as e:
        logger.warning(f"⚠️ Workout context retrieval failed (non-critical): {e}")

    # Inject memory context, insights, cognitive context, body state, journal, and workout into system message
    enhanced_content = system_message.content
    if memory_context:
        enhanced_content += memory_context
        logger.info(f"📝 Injected {len(memory_context)} chars of memory context into system prompt")
    if insight_context:
        enhanced_content += insight_context
        logger.info(f"✨ Injected {len(insight_context)} chars of insight context into system prompt")
    if cognitive_context:
        enhanced_content += cognitive_context
        logger.info(f"🧠 Injected {len(cognitive_context)} chars of cognitive context into system prompt")
    if body_state_context:
        enhanced_content += body_state_context
        logger.info(f"🫀 Injected {len(body_state_context)} chars of body state context into system prompt")
    if journal_context:
        enhanced_content += f"\n\n{journal_context}"
        logger.info(f"📔 Injected {len(journal_context)} chars of journal context into system prompt")
    if workout_context:
        enhanced_content += f"\n\n{workout_context}"
        logger.info(f"🏋️ Injected {len(workout_context)} chars of workout context into system prompt")

    if memory_context or insight_context or cognitive_context or body_state_context or journal_context or workout_context:
        system_message = ChatMessage(role="system", content=enhanced_content)

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

    # Check if Sara's response mentions body state (for calibration feedback loop)
    try:
        if response_content:
            pending = calibration_service.detect_body_state_mention(
                sara_response=response_content,
                user_id=current_user.id,
                current_body_state=None  # Let calibration service use defaults
            )
            if pending:
                logger.info(f"📊 Body state mention detected in response: {pending.estimate_type}={pending.estimated_label}, "
                           f"awaiting user feedback")
    except Exception as e:
        logger.warning(f"⚠️ Body state mention detection failed (non-critical): {e}")

    # Store conversation in episodic memory
    try:
        logger.info(f"🧠 Storing conversation in Sara's memory...")
        await llm_client.store_conversation(request.messages, response_content, current_user.id, request.conversation_id)
        logger.info(f"✅ Conversation stored in memory successfully")
    except Exception as e:
        logger.error(f"❌ Failed to store conversation in memory: {e}")
        # Don't fail the request if memory storage fails

    # Trigger cognitive processing (hypothesis extraction, reflection analysis) in background
    # This is fire-and-forget so it doesn't slow down the response
    try:
        import asyncio
        asyncio.create_task(_process_conversation_for_cognitive_learning(
            request.messages, response_content, current_user.id, db
        ))
    except Exception as e:
        logger.warning(f"⚠️ Failed to start cognitive processing task: {e}")

    return chat_response


async def _process_conversation_for_cognitive_learning(messages, response_content, user_id: str, db: Session):
    """Background task to extract hypotheses and reflections from a conversation."""
    try:
        from app.services.sara_identity_service import sara_identity_service
        from app.services.hypothesis_service import hypothesis_service

        logger.info(f"🧠 Starting cognitive processing for conversation...")

        # Convert messages to episode-like format for analysis
        conversation_episodes = []
        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role")
                content = msg.get("content")
            else:
                role = msg.role
                content = msg.content
            if role and content:
                conversation_episodes.append({
                    "role": role,
                    "content": content
                })

        # Add assistant response
        conversation_episodes.append({
            "role": "assistant",
            "content": response_content
        })

        # Create a new db session for this background task
        bg_db = SessionLocal()
        try:
            # Extract hypotheses from conversation (run every few conversations)
            # To avoid overhead, only extract hypotheses if conversation has substance
            total_content_length = sum(len(ep.get("content", "")) for ep in conversation_episodes)
            if total_content_length > 200:  # Only for substantial conversations
                hypotheses = await hypothesis_service.extract_hypotheses_from_conversation(
                    db=bg_db,
                    conversation_episodes=conversation_episodes
                )
                if hypotheses:
                    logger.info(f"💡 Extracted {len(hypotheses)} hypotheses from conversation")

            # Update relationship state
            await sara_identity_service.update_relationship_state(
                db=bg_db,
                conversation_episodes=conversation_episodes
            )
            logger.info(f"✅ Relationship state updated")

        finally:
            bg_db.close()

        logger.info(f"✅ Cognitive processing complete")
    except Exception as e:
        logger.error(f"❌ Cognitive processing failed: {e}")

# Note: Let CORSMiddleware handle preflight automatically; no custom OPTIONS route

@app.post("/chat/stream")
async def chat_stream(request: ChatRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Streaming chat endpoint with real-time tool usage indicators"""
    logger.info(f"💬 Streaming chat request from user {current_user.email} with {len(request.messages)} messages")
    logger.info(f"📋 Received conversation_id: {request.conversation_id}")
    
    async def generate_events():
        try:
            # CHESS COMMAND INTERCEPTION
            # Check if this is a /chess command or we're in chess mode
            if CHESS_COMMANDS_AVAILABLE and request.messages:
                last_user_message = next((m.content for m in reversed(request.messages) if m.role == "user"), None)
                if last_user_message:
                    chess_result = await handle_chess_command(current_user.id, last_user_message, db)
                    if chess_result is not None:
                        # Chess command was handled - return direct response
                        response_content, is_streaming = chess_result
                        logger.info(f"♟️ Chess command handled: {last_user_message[:50]}...")
                        # Use text_chunk format for iOS compatibility
                        yield f"data: {json.dumps({'type': 'text_chunk', 'data': {'content': response_content}})}\n\n"
                        yield f"data: {json.dumps({'type': 'final_response', 'data': {'content': response_content, 'citations': [], 'timestamp': datetime.utcnow().isoformat(), 'conversation_id': request.conversation_id}})}\n\n"
                        yield f"data: {json.dumps({'type': 'done'})}\n\n"
                        return

            # Create an async queue for events
            event_queue = asyncio.Queue()

            # Set up streaming LLM client
            streaming_client = SimpleLLMClient()
            streaming_client.set_event_queue(event_queue)
            # Set token usage callback for tracking
            from app.services.token_usage_service import queue_token_usage
            streaming_client.set_token_usage_callback(queue_token_usage)

            # Create system message
            system_message = ChatMessage(
                role="system",
                content=get_system_prompt(ASSISTANT_NAME, current_user.email)
            )

            # INTENT CLASSIFICATION for lazy context injection
            last_user_message = next((m.content for m in reversed(request.messages) if m.role == "user"), "") if request.messages else ""
            tool_classifier = get_tool_intent_classifier()
            context_router = get_context_router()
            # Use conversation-aware classification to preserve tool context across turns
            session_id = request.conversation_id or str(current_user.id)
            user_intent, tool_categories = tool_classifier.classify_with_context(last_user_message, session_id)
            turn_count = len(request.messages)
            context_decision = context_router.decide(
                intent=user_intent,
                message=last_user_message,
                turn_count=turn_count
            )
            logger.info(f"🎯 Intent={user_intent}, {context_decision.reason}")

            # LAZY MEMORY RETRIEVAL: Only retrieve when ContextRouter says so
            memory_context = ""
            if context_decision.inject_memory:
                try:
                    if last_user_message:
                        logger.info(f"🧠 Retrieving relevant memories for: '{last_user_message[:50]}...'")
                        relevant_memories = await intelligent_memory_service.intelligent_memory_search(
                            user_id=current_user.id,
                            query=last_user_message,
                            use_semantic=True
                        )
                        if relevant_memories:
                            logger.info(f"✅ Found {len(relevant_memories)} relevant memories")
                            memory_context = "\n\n## Relevant Past Context:\n"
                            for i, mem in enumerate(relevant_memories[:5], 1):  # Top 5 memories
                                content_preview = mem.get("content", "")[:300]
                                similarity = mem.get("similarity", 0)
                                created_at = mem.get("created_at", "")
                                memory_context += f"{i}. [{created_at}] (similarity: {similarity:.2f})\n   {content_preview}\n\n"
                        else:
                            logger.info("ℹ️ No relevant memories found")
                except Exception as e:
                    logger.warning(f"⚠️ Memory retrieval failed (non-critical): {e}")
            else:
                logger.info("⏭️ Skipping memory retrieval (not needed for this intent)")

            # Inject memory context into system message if available
            if memory_context:
                enhanced_system_content = system_message.content + memory_context
                system_message = ChatMessage(role="system", content=enhanced_system_content)
                logger.info(f"📝 Injected {len(memory_context)} chars of memory context into system prompt")

            # CHESS CONTEXT: Inject chess game state if user is in chess mode
            if CHESS_COMMANDS_AVAILABLE:
                chess_context = get_chess_context_prompt(current_user.id, db)
                if chess_context:
                    current_content = system_message.content
                    system_message = ChatMessage(
                        role="system",
                        content=current_content + "\n\n## Chess Context:\n" + chess_context
                    )
                    logger.info(f"♟️ Injected chess context into system prompt")

            # DAILY BRIEF SYSTEM: Update moment layer and inject compiled brief
            try:
                if DAILY_BRIEF_AVAILABLE:
                    # Get the last user message for moment layer
                    last_user_message = ""
                    if request.messages:
                        last_user_message = next((m.content for m in reversed(request.messages) if m.role == "user"), "")

                    # Update moment layer (fast, no LLM)
                    await daily_brief_service.update_moment(
                        user_id=current_user.id,
                        current_message=last_user_message,
                        conversation_id=request.conversation_id,
                        db=db
                    )
                    logger.info(f"📝 Updated moment layer")

                    # Get compiled daily brief (lazy, cached)
                    daily_brief = await daily_brief_service.get_compiled_brief(current_user.id)

                    if daily_brief:
                        # Inject daily brief into system message
                        current_content = system_message.content
                        system_message = ChatMessage(
                            role="system",
                            content=current_content + "\n\n" + daily_brief
                        )
                        logger.info(f"📋 Injected daily brief ({len(daily_brief)} chars) into system prompt")
            except Exception as e:
                logger.warning(f"⚠️ Daily brief injection failed (non-critical): {e}")
                # Continue without daily brief if it fails

            # BODY STATE CONTEXT: Inject physiological awareness
            try:
                subconscious_result = db.execute(text("""
                    SELECT body_state_context
                    FROM subconscious_state
                    WHERE user_id = :user_id
                """), {"user_id": current_user.id}).fetchone()

                if subconscious_result and subconscious_result.body_state_context:
                    current_content = system_message.content
                    system_message = ChatMessage(
                        role="system",
                        content=current_content + f"\n\n{subconscious_result.body_state_context}"
                    )
                    logger.info(f"🫀 Injected body state context into system prompt")
            except Exception as e:
                logger.warning(f"⚠️ Body state context injection failed (non-critical): {e}")
                # Continue without body state context if it fails

            # SARA'S INNER MONOLOGUE: Inject journal context
            try:
                journal_context = await sara_journal.get_entries_for_conversation_context(
                    db=db,
                    user_id=current_user.id,
                    max_entries=5
                )
                if journal_context:
                    current_content = system_message.content
                    system_message = ChatMessage(
                        role="system",
                        content=current_content + f"\n\n{journal_context}"
                    )
                    logger.info(f"📔 Injected {len(journal_context)} chars of journal context into system prompt")
            except Exception as e:
                logger.warning(f"⚠️ Journal context injection failed (non-critical): {e}")

            # ACTIVE WORKOUT SESSION: Inject workout coaching context
            try:
                workout_context = await workout_session_service.get_workout_context(current_user.id, db)
                if workout_context:
                    current_content = system_message.content
                    system_message = ChatMessage(
                        role="system",
                        content=current_content + f"\n\n{workout_context}"
                    )
                    logger.info(f"🏋️ Injected {len(workout_context)} chars of workout context into system prompt")
            except Exception as e:
                logger.warning(f"⚠️ Workout context injection failed (non-critical): {e}")

            # Check if user's message is calibration feedback for body state estimation
            try:
                if last_user_message:
                    calibration_result = calibration_service.analyze_user_response(
                        user_message=last_user_message,
                        user_id=current_user.id,
                        db=db
                    )
                    if calibration_result:
                        logger.info(f"📈 Body state calibration processed: {calibration_result.get('estimate_type')} "
                                   f"{calibration_result.get('feedback_type')} -> {calibration_result.get('coefficient_adjusted')} "
                                   f"{calibration_result.get('adjustment', 0):+.3f}")
            except Exception as e:
                logger.warning(f"⚠️ Calibration feedback check failed (non-critical): {e}")

            # SESSION GAP DETECTION: Detect gaps and summarize for day layer
            try:
                # Check if there's been a 45+ minute gap since last message
                has_gap, last_message_time = await llm_client.detect_session_gap(current_user.id, db)

                if has_gap and last_message_time:
                    # Session gap detected - summarize the previous session
                    logger.info(f"⏱️ Session gap detected (45+ min since last message)")

                    # Define session time range: from 2 hours before gap to the gap time
                    session_end = last_message_time
                    session_start = session_end - timedelta(hours=2)

                    # Summarize session
                    summary = await llm_client.summarize_session(current_user.id, session_start, session_end, db)
                    if summary:
                        # Store in Redis (legacy, for fallback)
                        asyncio.create_task(
                            llm_client.store_session_summary(current_user.id, summary, session_end)
                        )
                        # Also feed to day layer if daily brief is available
                        if DAILY_BRIEF_AVAILABLE:
                            asyncio.create_task(
                                daily_brief_service.append_to_day_layer(current_user.id, summary, session_end)
                            )
                            logger.info(f"📅 Appended session summary to day layer")

                        # Write Sara's conversation close journal entry
                        try:
                            asyncio.create_task(
                                sara_journal.write_conversation_close_entry(
                                    db=db,
                                    user_id=current_user.id,
                                    conversation_id=request.conversation_id or "unknown",
                                    conversation_summary=summary,
                                    user_mood=None,  # Could infer from summary
                                    body_state=None
                                )
                            )
                            logger.info(f"📔 Queued conversation close journal entry")
                        except Exception as je:
                            logger.warning(f"⚠️ Failed to write journal entry: {je}")

            except Exception as e:
                logger.warning(f"⚠️ Session gap detection failed (non-critical): {e}")

            # Retrieve conversation history if conversation_id provided
            conversation_history = []
            if request.conversation_id:
                logger.info(f"📜 Retrieving conversation history for: {request.conversation_id}")
                try:
                    # Get previous episodes from this conversation (limit to recent ones to avoid context overflow)
                    episodes = db.query(Episode).filter(
                        Episode.conversation_id == request.conversation_id,
                        Episode.user_id == current_user.id,
                        Episode.role.in_(["user", "assistant"])
                    ).order_by(Episode.created_at.asc()).limit(20).all()

                    # Convert episodes to ChatMessage format
                    for episode in episodes:
                        conversation_history.append(ChatMessage(
                            role=episode.role,
                            content=episode.content
                        ))

                    logger.info(f"✅ Retrieved {len(conversation_history)} messages from conversation history")
                except Exception as e:
                    logger.error(f"❌ Failed to retrieve conversation history: {e}")

            # Build full message list: system + history + new messages
            all_messages = [system_message] + conversation_history + request.messages
            logger.info(f"💬 Total messages: {len(all_messages)} (1 system + {len(conversation_history)} history + {len(request.messages)} new)")

            # Start the LLM processing in a background task
            async def process_chat():
                try:
                    # INTENT-BASED TOOL LOADING
                    # tool_categories was already determined by classify_with_context above
                    # which includes conversation context preservation

                    if tool_categories:
                        tools = tool_registry.get_tools_by_categories(tool_categories)
                        logger.info(f"🔧 Intent={user_intent}: Loaded {len(tools)} tools from categories: {tool_categories}")
                    else:
                        tools = []
                        logger.info(f"🔧 Intent={user_intent}: No tools needed (conversational)")

                    # Process chat with loaded tools
                    logger.info("⏳ Starting chat_with_tools...")
                    response_content = await streaming_client.chat_with_tools(all_messages, tools, current_user.id, request.conversation_id)
                    logger.info(f"✅ chat_with_tools completed, response length: {len(response_content)}")

                    # Check if Sara's response mentions body state (for calibration feedback loop)
                    try:
                        if response_content:
                            pending = calibration_service.detect_body_state_mention(
                                sara_response=response_content,
                                user_id=current_user.id,
                                current_body_state=None
                            )
                            if pending:
                                logger.info(f"📊 Body state mention detected: {pending.estimate_type}={pending.estimated_label}")
                    except Exception as e:
                        logger.warning(f"⚠️ Body state mention detection failed (non-critical): {e}")

                    # Send final response and done IMMEDIATELY to close the stream
                    final_conv_id = streaming_client.current_conversation_id if hasattr(streaming_client, 'current_conversation_id') else request.conversation_id
                    final_episode_id = streaming_client.current_episode_id if hasattr(streaming_client, 'current_episode_id') else None
                    logger.info(f"🔍 Sending final_response with conversation_id: {final_conv_id}, episode_id: {final_episode_id}")
                    await event_queue.put({
                        "type": "final_response",
                        "data": {
                            "content": response_content,
                            "citations": streaming_client.get_citations(),
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                            "conversation_id": final_conv_id,
                            "episode_id": final_episode_id
                        }
                    })
                    logger.info("✅ final_response event queued")
                    await event_queue.put({"type": "done"})
                    logger.info("✅ done event queued")

                    # Note: conversation storage already happened inside chat_with_tools
                    # No additional storage needed here
                except Exception as e:
                    logger.error(f"❌ Exception in process_chat: {e}", exc_info=True)
                    await event_queue.put({"type": "error", "data": {"message": str(e)}})
                    await event_queue.put({"type": "done"})
            
            # Start processing
            task = asyncio.create_task(process_chat())
            
            # Stream events as they come in
            while True:
                try:
                    # Wait for next event with timeout (5s to allow tool execution without excessive heartbeats)
                    event = await asyncio.wait_for(event_queue.get(), timeout=5.0)
                    
                    if event.get("type") == "done":
                        break

                    # Format as Server-Sent Event
                    event_data = json.dumps(event)
                    if event.get("type") == "final_response":
                        logger.info(f"🚀 Yielding final_response SSE: {event_data[:200]}")
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
            "Connection": "keep-alive"
        }
    )

# ==================== VOICE AGENT (iOS) ====================
@app.post("/api/voice-agent/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Transcribe audio using Whisper STT service.
    Returns just the transcription text.
    """
    try:
        # Save audio file temporarily
        audio_content = await audio.read()
        temp_audio_path = f"/tmp/voice_{uuid.uuid4()}.m4a"

        with open(temp_audio_path, "wb") as f:
            f.write(audio_content)

        # Known Whisper hallucinations on silence/noise
        WHISPER_HALLUCINATIONS = {
            "thank you", "thanks", "thanks for watching", "thank you for watching",
            "please subscribe", "subscribe", "bye", "goodbye", "see you next time",
            "you", "the", "i", "a", "", "so", "um", "uh", "hmm", "oh",
            "thank you.", "thanks.", "bye.", "goodbye."
        }

        # Call Whisper STT service (OpenAI-compatible API)
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            with open(temp_audio_path, "rb") as audio_file:
                files = {"file": ("audio.m4a", audio_file, "audio/m4a")}
                data = {
                    "model": "distil-small.en",
                    "language": "en",
                    "vad_filter": "true",
                    "no_speech_threshold": "0.4",
                    "compression_ratio_threshold": "2.0",
                }
                whisper_response = await client.post(
                    "http://10.185.1.8:8585/v1/audio/transcriptions",
                    files=files,
                    data=data
                )

            if whisper_response.status_code != 200:
                logger.error(f"[Voice] Whisper error: {whisper_response.status_code} - {whisper_response.text}")
                raise HTTPException(status_code=500, detail="Transcription service error")

            result = whisper_response.json()
            transcription = result.get("text", "").strip()

        # Filter out hallucinations
        if transcription.lower() in WHISPER_HALLUCINATIONS:
            logger.info(f"[Voice] Filtered hallucination for user {current_user.id}: '{transcription}'")
            transcription = ""
        elif len(transcription.split()) <= 2 and transcription.lower().rstrip('.!?') in WHISPER_HALLUCINATIONS:
            logger.info(f"[Voice] Filtered short hallucination for user {current_user.id}: '{transcription}'")
            transcription = ""
        else:
            logger.info(f"[Voice] Transcribed audio for user {current_user.id}: {transcription}")

        # Clean up temp file
        try:
            os.remove(temp_audio_path)
        except OSError as e:
            logger.debug(f"Failed to remove temp audio file: {e}")

        return {"transcription": transcription}

    except Exception as e:
        logger.error(f"[Voice] Error transcribing audio: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/voice-agent/speak")
async def speak_text(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """
    Convert text to speech using Kokoro TTS.
    Returns audio file (WAV default for iOS compatibility).
    """
    try:
        body = await request.json()
        text = body.get("text", "")
        response_format = body.get("response_format", "wav")  # Default WAV for iOS compatibility

        if not text:
            raise HTTPException(status_code=400, detail="No text provided")

        logger.info(f"[Voice] Generating speech for user {current_user.id}: {text[:50]}... (format: {response_format})")

        # Call Kokoro TTS service with blended voice
        import httpx
        async with httpx.AsyncClient(timeout=60.0) as client:
            tts_response = await client.post(
                "http://10.185.1.9:8880/v1/audio/speech",
                json={
                    "input": text,
                    "model": "kokoro",
                    "voice": "af_sarah(1)+af_bella(1)",
                    "response_format": response_format,
                    "speed": 1.0
                }
            )

            if tts_response.status_code != 200:
                logger.error(f"[Voice] Kokoro TTS error: {tts_response.status_code} - {tts_response.text}")
                raise HTTPException(status_code=500, detail="TTS service error")

            # Determine media type based on format
            media_type_map = {
                "mp3": "audio/mpeg",
                "wav": "audio/wav",
                "opus": "audio/opus",
                "flac": "audio/flac",
                "pcm": "audio/pcm",
                "m4a": "audio/mp4"
            }
            media_type = media_type_map.get(response_format, "audio/mpeg")

            return Response(
                content=tts_response.content,
                media_type=media_type,
                headers={
                    "Content-Disposition": f"attachment; filename=speech.{response_format}"
                }
            )

    except Exception as e:
        logger.error(f"[Voice] Error generating speech: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== DESKTOP APP DOWNLOADS ====================

DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "downloads")

@app.get("/api/downloads")
async def list_downloads(
    current_user: User = Depends(get_current_user)
):
    """List available desktop app downloads"""
    downloads = []

    if os.path.exists(DOWNLOADS_DIR):
        for filename in os.listdir(DOWNLOADS_DIR):
            filepath = os.path.join(DOWNLOADS_DIR, filename)
            if os.path.isfile(filepath):
                stat = os.stat(filepath)

                # Determine platform and arch
                platform = "unknown"
                arch = "x64"
                if "mac" in filename.lower():
                    platform = "macOS"
                    if "arm64" in filename.lower():
                        arch = "arm64"
                elif "win" in filename.lower():
                    platform = "Windows"
                elif filename.endswith(".asar"):
                    platform = "Windows"  # asar files are for Windows updates

                # Determine file type
                file_type = "archive"
                if filename.endswith(".exe"):
                    file_type = "installer"
                elif filename.endswith(".dmg"):
                    file_type = "installer"
                elif filename.endswith(".zip") or filename.endswith(".tar.gz"):
                    file_type = "portable"
                elif filename.endswith(".asar"):
                    file_type = "update"

                downloads.append({
                    "filename": filename,
                    "platform": platform,
                    "arch": arch,
                    "type": file_type,
                    "size_bytes": stat.st_size,
                    "size_mb": round(stat.st_size / (1024 * 1024), 1),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })

    # Sort by platform, then arch
    downloads.sort(key=lambda x: (x["platform"], x["arch"]))

    return {"downloads": downloads, "version": "1.0.30"}


@app.get("/api/downloads/{filename}")
async def download_file(
    filename: str,
    current_user: User = Depends(get_current_user)
):
    """Download a desktop app installer"""
    # Sanitize filename to prevent directory traversal
    safe_filename = os.path.basename(filename)
    filepath = os.path.join(DOWNLOADS_DIR, safe_filename)

    if not os.path.exists(filepath) or not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="File not found")

    # Determine media type
    media_type = "application/octet-stream"
    if safe_filename.endswith(".zip"):
        media_type = "application/zip"
    elif safe_filename.endswith(".tar.gz"):
        media_type = "application/gzip"
    elif safe_filename.endswith(".exe"):
        media_type = "application/x-msdownload"
    elif safe_filename.endswith(".dmg"):
        media_type = "application/x-apple-diskimage"

    return FileResponse(
        filepath,
        media_type=media_type,
        filename=safe_filename
    )


@app.get("/api/notes/search")
async def search_notes_api(
    q: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Search notes by title or content. Supports device token auth for Pi dashboard.
    Uses text matching with fuzzy title search (handles spaces).
    """
    # Try device token auth first
    user_id = await get_device_user(request, db)

    # Fall back to cookie auth
    if not user_id:
        try:
            current_user = await get_current_user(request, db)
            user_id = current_user.id
        except Exception as auth_err:
            logger.debug(f"Authentication failed for search-notes: {auth_err}")
            raise HTTPException(status_code=401, detail="Not authenticated")

    # Normalize query for fuzzy matching
    normalized_query = q.replace(" ", "")

    # Search title and content with fuzzy matching
    results = db.execute(text("""
        SELECT id, title, content, folder_id, created_at, updated_at
        FROM note
        WHERE user_id = :user_id
          AND (
            title ILIKE :query_pattern
            OR REPLACE(title, ' ', '') ILIKE :normalized_pattern
            OR content ILIKE :query_pattern
          )
        ORDER BY
            CASE WHEN title ILIKE :query_pattern THEN 0
                 WHEN REPLACE(title, ' ', '') ILIKE :normalized_pattern THEN 1
                 ELSE 2 END,
            updated_at DESC
        LIMIT 10
    """), {
        "user_id": user_id,
        "query_pattern": f"%{q}%",
        "normalized_pattern": f"%{normalized_query}%"
    }).fetchall()

    return [
        {
            "id": str(row.id),
            "title": row.title or "Untitled",
            "content": row.content,
            "folder_id": row.folder_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None
        }
        for row in results
    ]


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
                "created_at": format_iso_utc(episode.created_at)
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
                    "timestamp": format_iso_utc(episode.created_at),
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

# Episode Rating endpoints
@app.post("/api/episodes/{episode_id}/rate")
async def rate_episode(
    episode_id: str,
    rating_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Rate an episode (1-5 stars)"""
    try:
        from app.services.rating_service import get_rating_service
        from app.services.rating_events import get_rating_publisher

        rating = rating_data.get("rating")
        if not rating or not (1 <= rating <= 5):
            raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

        # Get rating service
        rating_service = get_rating_service(db, redis_url=config.settings.redis_url)

        # Rate the episode
        result = await rating_service.rate_episode(
            episode_id=episode_id,
            user_id=current_user.id,
            rating=rating
        )

        # Publish event for real-time updates
        publisher = get_rating_publisher(redis_url=config.settings.redis_url)
        await publisher.publish_episode_rated(
            episode_id=episode_id,
            user_id=current_user.id,
            rating=rating,
            net_score=result["rating_sum"],
            rating_count=result["rating_count"],
            average_rating=result["average_rating"]
        )

        return {
            "success": True,
            "message": "Episode rated successfully",
            "rating": result
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error rating episode {episode_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to rate episode")

@app.get("/api/episodes/{episode_id}/rating")
async def get_episode_rating(
    episode_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get rating data for an episode"""
    try:
        from app.services.rating_service import get_rating_service

        rating_service = get_rating_service(db, redis_url=config.settings.redis_url)
        rating_data = await rating_service.get_episode_rating(episode_id)

        if not rating_data:
            return {"rated": False}

        # Also get user's specific rating
        user_rating = await rating_service.get_user_rating(current_user.id, episode_id)
        rating_data["user_rating"] = user_rating
        rating_data["rated"] = True

        return rating_data

    except Exception as e:
        logger.error(f"Error getting rating for episode {episode_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get episode rating")

@app.delete("/api/episodes/{episode_id}/rating")
async def delete_episode_rating(
    episode_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete user's rating for an episode"""
    try:
        from app.services.rating_service import get_rating_service

        rating_service = get_rating_service(db, redis_url=config.settings.redis_url)
        success = await rating_service.delete_rating(episode_id, current_user.id)

        if not success:
            raise HTTPException(status_code=404, detail="Rating not found")

        return {
            "success": True,
            "message": "Rating deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting rating for episode {episode_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete rating")

@app.get("/api/rating/stats")
async def get_rating_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get rating system statistics"""
    try:
        from app.services.rating_service import get_rating_service

        rating_service = get_rating_service(db, redis_url=config.settings.redis_url)
        stats = await rating_service.get_rating_stats()

        return stats

    except Exception as e:
        logger.error(f"Error getting rating stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get rating stats")

@app.post("/api/episodes/find-by-content")
async def find_episodes_by_content(
    request: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Find episode IDs by conversation_id and content (for rating UI)"""
    try:
        conversation_id = request.get("conversation_id")
        messages = request.get("messages", [])  # [{role, content}]

        if not conversation_id or not messages:
            return {"episodes": []}

        # Find episodes matching the conversation and content
        result_episodes = []
        for msg in messages:
            episode = db.query(Episode).filter(
                Episode.conversation_id == conversation_id,
                Episode.user_id == current_user.id,
                Episode.role == msg["role"],
                Episode.content == msg["content"]
            ).first()

            if episode:
                result_episodes.append({
                    "role": episode.role,
                    "content": episode.content[:100],  # Preview
                    "episode_id": episode.id
                })
            else:
                result_episodes.append({
                    "role": msg["role"],
                    "content": msg["content"][:100],
                    "episode_id": None
                })

        return {"episodes": result_episodes}

    except Exception as e:
        logger.error(f"Error finding episodes by content: {e}")
        raise HTTPException(status_code=500, detail="Failed to find episodes")

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

                # Save chunks to PostgreSQL (skip chunks with failed embeddings)
                saved_chunks = 0
                skipped_chunks = 0
                for i, (chunk_text, embedding) in enumerate(zip(processed_chunks, chunk_embeddings)):
                    if embedding is None:
                        # Skip chunks where embedding failed - don't pollute search with zero vectors
                        skipped_chunks += 1
                        continue

                    if DATABASE_URL.startswith("postgresql") and PGVECTOR_AVAILABLE:
                        embedding_data = embedding
                    else:
                        embedding_data = json.dumps(embedding)

                    chunk = DocumentChunk(
                        document_id=document.id,
                        user_id=current_user.id,
                        chunk_index=i,
                        chunk_text=chunk_text,
                        embedding=embedding_data
                    )
                    db.add(chunk)
                    saved_chunks += 1

                db.commit()
                if skipped_chunks > 0:
                    logger.warning(f"📄 Legacy chunking: {saved_chunks} chunks saved, {skipped_chunks} skipped (embedding failures)")
                else:
                    logger.info(f"📄 Legacy chunking completed: {saved_chunks} chunks")
        
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

# ==================== EPISODE-BASED CONVERSATION ENDPOINTS ====================

@app.get("/api/conversations/list", response_model=list[ConversationSummaryResponse])
async def list_conversations(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get list of conversations based on Episodes"""
    try:
        # Query for distinct conversation_ids with aggregated data
        from sqlalchemy import func, distinct

        conversations = db.query(
            Episode.conversation_id,
            func.min(Episode.content).label('first_message'),
            func.count(Episode.id).label('message_count'),
            func.max(Episode.created_at).label('last_activity'),
            func.min(Episode.created_at).label('created_at')
        ).filter(
            Episode.user_id == current_user.id,
            Episode.conversation_id.isnot(None),
            Episode.role.in_(['user', 'assistant'])
        ).group_by(
            Episode.conversation_id
        ).order_by(
            func.max(Episode.created_at).desc()
        ).limit(limit).all()

        return [
            ConversationSummaryResponse(
                conversation_id=conv.conversation_id,
                first_message=conv.first_message[:100] if conv.first_message else "",
                message_count=conv.message_count,
                last_activity=conv.last_activity.isoformat(),
                created_at=conv.created_at.isoformat()
            )
            for conv in conversations
        ]
    except Exception as e:
        logger.error(f"Error fetching conversations list: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch conversations")

@app.get("/api/conversations/{conversation_id}/messages", response_model=list[EpisodeMessageResponse])
async def get_conversation_messages(
    conversation_id: str,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get messages for a specific conversation from Episodes"""
    try:
        # Verify at least one episode in this conversation belongs to the user
        episode_exists = db.query(Episode).filter(
            Episode.conversation_id == conversation_id,
            Episode.user_id == current_user.id
        ).first()

        if not episode_exists:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Get messages for this conversation
        episodes = db.query(Episode).filter(
            Episode.conversation_id == conversation_id,
            Episode.user_id == current_user.id,
            Episode.role.in_(['user', 'assistant'])
        ).order_by(
            Episode.created_at.asc()
        ).offset(offset).limit(limit).all()

        return [
            EpisodeMessageResponse(
                id=ep.id,
                role=ep.role,
                content=ep.content,
                created_at=format_iso_utc(ep.created_at),
                importance=ep.importance
            )
            for ep in episodes
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching conversation messages: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch conversation messages")

@app.post("/api/conversations/active")
async def set_active_conversation(
    request: SetActiveConversationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Set the user's current active conversation"""
    try:
        # Get or create user profile
        user_profile = db.query(UserProfile).filter(
            UserProfile.user_id == current_user.id
        ).first()

        if not user_profile:
            user_profile = UserProfile(
                user_id=current_user.id,
                profile_data={}
            )
            db.add(user_profile)

        # Store active conversation_id in profile_data field (JSONB)
        if not user_profile.profile_data:
            user_profile.profile_data = {}

        # Make a copy to ensure SQLAlchemy detects the change
        profile_data_copy = dict(user_profile.profile_data) if user_profile.profile_data else {}
        profile_data_copy['active_conversation_id'] = request.conversation_id
        user_profile.profile_data = profile_data_copy

        # Mark as modified for SQLAlchemy to detect the change
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(user_profile, "profile_data")

        db.commit()

        return {"message": "Active conversation set", "conversation_id": request.conversation_id}
    except Exception as e:
        logger.error(f"Error setting active conversation: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to set active conversation")

@app.get("/api/conversations/active")
async def get_active_conversation(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the user's current active conversation"""
    try:
        user_profile = db.query(UserProfile).filter(
            UserProfile.user_id == current_user.id
        ).first()

        active_conversation_id = None
        if user_profile and user_profile.profile_data:
            active_conversation_id = user_profile.profile_data.get('active_conversation_id')

        return {
            "conversation_id": active_conversation_id
        }
    except Exception as e:
        logger.error(f"Error getting active conversation: {e}")
        raise HTTPException(status_code=500, detail="Failed to get active conversation")

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
        logger.info(f"Neo4j driver status: {neo4j_service.driver}")
        if not neo4j_service.driver:
            logger.info("Attempting to connect to Neo4j...")
            await neo4j_service.connect()
            logger.info(f"After connect, driver status: {neo4j_service.driver}")
        await neo4j_service.verify_connection()
        return {
            "status": "healthy",
            "neo4j_connected": True,
            "message": "Knowledge graph is operational"
        }
    except Exception as e:
        logger.error(f"Neo4j health check failed: {e}")
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
        
        # If Neo4j returns empty results, fall back to PostgreSQL data
        nodes = graph_data.get("nodes", [])
        relationships = graph_data.get("relationships", [])
        
        if not nodes:
            logger.info("Neo4j graph is empty, falling back to PostgreSQL episode data")
            # Fetch episodes from PostgreSQL as fallback
            from sqlalchemy import select, and_, func
            
            db = SessionLocal()
            try:
                # Get meaningful episodes (content longer than 50 chars) using synchronous query
                episodes = db.query(Episode).filter(
                    and_(
                        Episode.user_id == current_user.id,
                        func.length(Episode.content) > 50
                    )
                ).order_by(Episode.created_at.desc()).limit(20).all()
                
                # Convert episodes to graph nodes
                fallback_nodes = []
                for episode in episodes:
                    fallback_nodes.append({
                        "id": f"episode_{episode.id}",
                        "labels": ["Episode"],
                        "properties": {
                            "id": episode.id,
                            "title": f"{episode.role}: {episode.content[:50]}..." if len(episode.content) > 50 else episode.content,
                            "content": episode.content,
                            "type": "episode",
                            "role": episode.role,
                            "source": episode.source,
                            "importance": episode.importance or 0.5,
                            "created_at": format_iso_utc(episode.created_at),
                            "group": 1 if episode.role == "user" else 2
                        }
                    })
                
                nodes = fallback_nodes
                logger.info(f"Generated {len(nodes)} fallback nodes from episodes")
            finally:
                db.close()
        
        return {
            "nodes": nodes,
            "relationships": relationships,
            "total_nodes": len(nodes),
            "total_relationships": len(relationships)
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
        except Exception as e:
            logger.debug(f"Embedding health check failed: {e}")
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
        "ai_provider": AI_PROVIDER,
        "openai_api_key": "***" if OPENAI_API_KEY and OPENAI_API_KEY != "dummy" else "",
        "anthropic_api_key": "***" if ANTHROPIC_API_KEY else "",
        "openai_base_url": OPENAI_BASE_URL,
        "openai_model": OPENAI_MODEL,
        "openai_notification_model": OPENAI_NOTIFICATION_MODEL,
        "embedding_base_url": EMBEDDING_BASE_URL,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimension": EMBEDDING_DIM
    }

class AISettingsUpdate(BaseModel):
    ai_provider: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
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
    global AI_PROVIDER, OPENAI_API_KEY, ANTHROPIC_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_NOTIFICATION_MODEL, EMBEDDING_BASE_URL, EMBEDDING_MODEL, EMBEDDING_DIM

    updated_settings = {}
    
    def _valid_url(u: str) -> bool:
        try:
            p = urlparse(u or "")
            return p.scheme in ("http", "https") and bool(p.netloc)
        except Exception:
            return False

    def _normalize_openai(u: str) -> str:
        u = (u or "").strip().rstrip("/")
        if not _valid_url(u):
            raise HTTPException(status_code=400, detail="Invalid openai_base_url; must include http(s)://")
        # Don't add /v1 if:
        # - URL already ends with /v1
        # - URL contains /openai/ (Gemini/other OpenAI-compatible endpoints)
        # - URL contains generativelanguage.googleapis.com (Gemini domain)
        if u.endswith("/v1") or "/openai/" in u or "generativelanguage.googleapis.com" in u:
            return u
        # Only add /v1 for standard OpenAI or local endpoints
        return u + "/v1"

    def _normalize_embedding(u: str) -> str:
        u = (u or "").strip().rstrip("/")
        if not _valid_url(u):
            raise HTTPException(status_code=400, detail="Invalid embedding_base_url; must include http(s)://")
        # Ensure base has no /v1 suffix; EmbeddingService appends /v1/embeddings
        if u.endswith("/v1"):
            u = u[:-3]
            u = u.rstrip("/")
        return u

    if settings.ai_provider is not None:
        AI_PROVIDER = settings.ai_provider
        config.settings.ai_provider = settings.ai_provider
        updated_settings["ai_provider"] = settings.ai_provider

    if settings.openai_api_key is not None:
        # Don't save masked value - require actual API key
        if settings.openai_api_key == "***" or len(settings.openai_api_key) < 10:
            logger.warning(f"Ignoring invalid API key (masked or too short)")
        else:
            OPENAI_API_KEY = settings.openai_api_key
            config.settings.openai_api_key = settings.openai_api_key
            updated_settings["openai_api_key"] = settings.openai_api_key

    if settings.anthropic_api_key is not None:
        # Don't save masked value - require actual API key
        if settings.anthropic_api_key == "***" or len(settings.anthropic_api_key) < 10:
            logger.warning(f"Ignoring invalid Anthropic API key (masked or too short)")
        else:
            ANTHROPIC_API_KEY = settings.anthropic_api_key
            config.settings.anthropic_api_key = settings.anthropic_api_key
            updated_settings["anthropic_api_key"] = settings.anthropic_api_key

    if settings.openai_base_url is not None:
        OPENAI_BASE_URL = _normalize_openai(settings.openai_base_url)
        config.settings.openai_base_url = OPENAI_BASE_URL
        updated_settings["openai_base_url"] = OPENAI_BASE_URL

    if settings.openai_model is not None:
        OPENAI_MODEL = settings.openai_model
        config.settings.openai_model = settings.openai_model
        updated_settings["openai_model"] = settings.openai_model

    if settings.openai_notification_model is not None:
        OPENAI_NOTIFICATION_MODEL = settings.openai_notification_model
        updated_settings["openai_notification_model"] = settings.openai_notification_model

    if settings.embedding_base_url is not None:
        EMBEDDING_BASE_URL = _normalize_embedding(settings.embedding_base_url)
        config.settings.embedding_base_url = EMBEDDING_BASE_URL
        updated_settings["embedding_base_url"] = EMBEDDING_BASE_URL

    if settings.embedding_model is not None:
        EMBEDDING_MODEL = settings.embedding_model
        config.settings.embedding_model = settings.embedding_model
        updated_settings["embedding_model"] = settings.embedding_model

    if settings.embedding_dimension is not None:
        EMBEDDING_DIM = settings.embedding_dimension
        config.settings.embedding_dim = settings.embedding_dimension
        updated_settings["embedding_dimension"] = settings.embedding_dimension
    
    # Persist settings to database for survival across restarts
    try:
        db = SessionLocal()
        for key, value in updated_settings.items():
            # Use UPSERT (INSERT ... ON CONFLICT UPDATE) to save settings
            db.execute(text("""
                INSERT INTO app_settings (key, value, updated_at, updated_by)
                VALUES (:key, :value, CURRENT_TIMESTAMP, :updated_by)
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    updated_at = EXCLUDED.updated_at,
                    updated_by = EXCLUDED.updated_by
            """), {"key": key, "value": str(value), "updated_by": current_user.email})
        db.commit()
        db.close()
        logger.info(f"💾 Persisted {len(updated_settings)} settings to database")
    except Exception as e:
        logger.error(f"Failed to persist settings to database: {e}")

    # No need to reinitialize services - EmbeddingService now reads settings dynamically
    # SimpleLLMClient and other services already read from config.settings which was updated above
    logger.info(f"✅ Settings applied immediately - services will use new URLs on next call")

    logger.info(f"AI settings updated by user {current_user.email}: {updated_settings}")

    # Mask API key in response (after saving to database)
    response_settings = updated_settings.copy()
    if "openai_api_key" in response_settings and response_settings["openai_api_key"]:
        response_settings["openai_api_key"] = "***"

    return {
        "message": "AI settings updated successfully and persisted",
        "updated_settings": response_settings,
        "note": "Settings applied immediately and will persist across restarts."
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

# General user settings endpoints
@app.get("/settings")
async def get_user_settings(current_user: User = Depends(get_current_user)):
    """Get user settings/preferences"""
    # Return default settings for now
    # In the future, this could be stored in a user_settings table
    return {
        "theme": "dark",
        "notifications_enabled": True,
        "model": "distil-small.en",
                    "language": "en",
        "timezone": "America/New_York",
        "assistant_name": ASSISTANT_NAME
    }

@app.put("/settings")
async def update_user_settings(settings: UserSettings, current_user: User = Depends(get_current_user)):
    """Update user settings/preferences"""
    # For now, just acknowledge the update
    # In the future, this could persist to a user_settings table
    return {
        "message": "Settings updated successfully",
        "settings": settings.dict()
    }

# Settings alias endpoints (for iOS app compatibility)
@app.get("/settings/preferences")
async def get_user_preferences(current_user: User = Depends(get_current_user)):
    """Alias to /settings for iOS app compatibility"""
    return await get_user_settings(current_user)

@app.put("/settings/preferences")
async def update_user_preferences(settings: UserSettings, current_user: User = Depends(get_current_user)):
    """Alias to /settings for iOS app compatibility"""
    return await update_user_settings(settings, current_user)

# Documents categories endpoint
@app.get("/documents/categories")
async def get_document_categories(current_user: User = Depends(get_current_user)):
    """Get all unique document categories"""
    # Document model doesn't have a category field yet
    # Return empty list for iOS app compatibility
    return []

# Fitness proxy endpoints - return empty data for now (iOS app compatible)
@app.get("/fitness/food")
async def get_fitness_food(
    start_date: str = None,
    end_date: str = None,
    current_user: User = Depends(get_current_user)
):
    """Get fitness food logs"""
    # Return empty array for now - can be connected to actual food log system later
    return []

@app.post("/fitness/food")
async def create_fitness_food(
    food_data: dict,
    current_user: User = Depends(get_current_user)
):
    """Create fitness food log"""
    # Return success for now
    return {
        "id": "1",
        "message": "Food log created",
        **food_data
    }

@app.delete("/fitness/food/{id}")
async def delete_fitness_food(
    id: str,
    current_user: User = Depends(get_current_user)
):
    """Delete fitness food log"""
    return {"message": "Food log deleted"}

@app.get("/fitness/workouts")
async def get_fitness_workouts(
    start_date: str = None,
    end_date: str = None,
    current_user: User = Depends(get_current_user)
):
    """Get fitness workouts"""
    # Return empty array for now - can be connected to actual workout system later
    return []

@app.post("/fitness/workouts")
async def create_fitness_workout(
    workout_data: dict,
    current_user: User = Depends(get_current_user)
):
    """Create fitness workout"""
    # Return success for now
    return {
        "id": "1",
        "message": "Workout created",
        **workout_data
    }

@app.delete("/fitness/workouts/{id}")
async def delete_fitness_workout(
    id: str,
    current_user: User = Depends(get_current_user)
):
    """Delete fitness workout"""
    return {"message": "Workout deleted"}

@app.get("/fitness/recovery")
async def get_fitness_recovery(
    start_date: str = None,
    end_date: str = None,
    current_user: User = Depends(get_current_user)
):
    """Get fitness recovery logs"""
    db = SessionLocal()
    try:
        from datetime import datetime, timedelta

        # Default to last 30 days if no dates provided
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")

        # Query the daily_recovery_log table
        query = text("""
            SELECT id, user_id, log_date, hrv, heart_rate, sleep_hours,
                   soreness_level, body_weight, weight_unit, notes, created_at, updated_at
            FROM daily_recovery_log
            WHERE user_id = :user_id
              AND log_date >= :start_date
              AND log_date <= :end_date
            ORDER BY log_date DESC
        """)

        results = db.execute(query, {
            "user_id": current_user.id,
            "start_date": start_date,
            "end_date": end_date
        }).fetchall()

        # Convert to list of dicts
        recovery_logs = []
        for row in results:
            row_dict = row._mapping
            recovery_logs.append({
                "id": row_dict['id'],
                "user_id": row_dict['user_id'],
                "log_date": row_dict['log_date'].isoformat(),
                "logged_at": row_dict['created_at'].isoformat() if row_dict['created_at'] else None,
                "hrv": row_dict['hrv'],
                "heart_rate": row_dict['heart_rate'],
                "sleep_hours": float(row_dict['sleep_hours']) if row_dict['sleep_hours'] else None,
                "soreness_level": row_dict['soreness_level'],
                "body_weight": float(row_dict['body_weight']) if row_dict['body_weight'] else None,
                "weight_unit": row_dict['weight_unit'],
                "notes": row_dict['notes'],
                "created_at": row_dict['created_at'].isoformat() if row_dict['created_at'] else None,
                "updated_at": row_dict['updated_at'].isoformat() if row_dict['updated_at'] else None
            })

        return recovery_logs

    finally:
        db.close()

@app.post("/fitness/recovery")
async def create_fitness_recovery(
    recovery_data: dict,
    current_user: User = Depends(get_current_user)
):
    """Create fitness recovery log"""
    db = SessionLocal()
    try:
        from datetime import datetime

        # Get log_date from recovery_data or use today
        log_date_str = recovery_data.get('log_date', datetime.now().strftime("%Y-%m-%d"))

        # Validate soreness level if provided
        soreness_level = recovery_data.get('soreness_level')
        if soreness_level is not None:
            if soreness_level < 1 or soreness_level > 10:
                raise HTTPException(status_code=400, detail="Soreness level must be between 1 and 10")

        # Parse log_date
        try:
            log_date = datetime.strptime(log_date_str, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

        # Check if entry exists for this date
        check_query = text("""
            SELECT id FROM daily_recovery_log
            WHERE user_id = :user_id AND log_date = :log_date
        """)
        existing = db.execute(check_query, {"user_id": current_user.id, "log_date": log_date}).fetchone()

        if existing:
            # Update existing entry
            update_query = text("""
                UPDATE daily_recovery_log
                SET hrv = :hrv,
                    heart_rate = :heart_rate,
                    sleep_hours = :sleep_hours,
                    soreness_level = :soreness_level,
                    body_weight = :body_weight,
                    weight_unit = :weight_unit,
                    notes = :notes,
                    updated_at = NOW()
                WHERE user_id = :user_id AND log_date = :log_date
                RETURNING id, user_id, log_date, hrv, heart_rate, sleep_hours, soreness_level, body_weight, weight_unit, notes, created_at, updated_at
            """)
            result = db.execute(update_query, {
                "user_id": current_user.id,
                "log_date": log_date,
                "hrv": recovery_data.get('hrv'),
                "heart_rate": recovery_data.get('heart_rate'),
                "sleep_hours": recovery_data.get('sleep_hours'),
                "soreness_level": recovery_data.get('soreness_level'),
                "body_weight": recovery_data.get('body_weight'),
                "weight_unit": recovery_data.get('weight_unit', 'lbs'),
                "notes": recovery_data.get('notes', '')
            }).fetchone()
        else:
            # Insert new entry
            insert_query = text("""
                INSERT INTO daily_recovery_log
                (id, user_id, log_date, hrv, heart_rate, sleep_hours, soreness_level, body_weight, weight_unit, notes, created_at, updated_at)
                VALUES (:id, :user_id, :log_date, :hrv, :heart_rate, :sleep_hours, :soreness_level, :body_weight, :weight_unit, :notes, NOW(), NOW())
                RETURNING id, user_id, log_date, hrv, heart_rate, sleep_hours, soreness_level, body_weight, weight_unit, notes, created_at, updated_at
            """)
            result = db.execute(insert_query, {
                "id": str(uuid.uuid4()),
                "user_id": current_user.id,
                "log_date": log_date,
                "hrv": recovery_data.get('hrv'),
                "heart_rate": recovery_data.get('heart_rate'),
                "sleep_hours": recovery_data.get('sleep_hours'),
                "soreness_level": recovery_data.get('soreness_level'),
                "body_weight": recovery_data.get('body_weight'),
                "weight_unit": recovery_data.get('weight_unit', 'lbs'),
                "notes": recovery_data.get('notes', '')
            }).fetchone()

        db.commit()

        # Convert result to response
        row = result._mapping
        return {
            "id": row['id'],
            "user_id": row['user_id'],
            "log_date": row['log_date'].isoformat(),
            "logged_at": row['created_at'].isoformat() if row['created_at'] else None,
            "hrv": row['hrv'],
            "heart_rate": row['heart_rate'],
            "sleep_hours": float(row['sleep_hours']) if row['sleep_hours'] else None,
            "soreness_level": row['soreness_level'],
            "body_weight": float(row['body_weight']) if row['body_weight'] else None,
            "weight_unit": row['weight_unit'],
            "notes": row['notes'],
            "created_at": row['created_at'].isoformat() if row['created_at'] else None,
            "updated_at": row['updated_at'].isoformat() if row['updated_at'] else None
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to save recovery log: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.delete("/fitness/recovery/{id}")
async def delete_fitness_recovery(
    id: str,
    current_user: User = Depends(get_current_user)
):
    """Delete fitness recovery log"""
    db = SessionLocal()
    try:
        # Delete the recovery log
        delete_query = text("""
            DELETE FROM daily_recovery_log
            WHERE id = :id AND user_id = :user_id
        """)
        db.execute(delete_query, {"id": id, "user_id": current_user.id})
        db.commit()
        return {"message": "Recovery log deleted"}
    finally:
        db.close()

# /fitness/habits and /fitness/habits/streaks endpoints moved to app.routes.habits

@app.get("/fitness/summary")
async def get_fitness_summary(date: str = None, current_user: User = Depends(get_current_user)):
    """Get fitness summary for a specific date"""
    from datetime import datetime, timedelta

    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    # Return a basic summary
    # In the future, this could aggregate data from food logs, workouts, recovery, and habits
    return {
        "date": date,
        "calories_consumed": 0,
        "calories_burned": 0,
        "workouts_completed": 0,
        "habits_completed": 0,
        "recovery_score": 0,
        "notes": "No data available for this date"
    }



# HABIT TRACKING ENDPOINTS moved to app.routes.habits

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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually trigger an autonomous sweep for testing/debugging"""

    if sweep_type not in ['quick_sweep', 'standard_sweep', 'digest_sweep']:
        raise HTTPException(status_code=400, detail="Invalid sweep type")

    try:
        from app.services.autonomous_sweep_service import AutonomousSweepService

        sweep_service = AutonomousSweepService(db)
        raw_insights = await sweep_service.execute_sweep(
            user_id=current_user.id,
            sweep_type=sweep_type,
            triggered_by="manual"
        )

        # Check for recent similar insights to avoid duplicates
        recent_cutoff = datetime.now() - timedelta(hours=6)
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
            if sweep_service.scorer.should_surface(insight_data['priority_score'], sweep_type):
                is_new = (insight_data['type'] not in recent_types and
                         insight_data['title'] not in recent_titles)

                insight = AutonomousInsight(
                    user_id=current_user.id,
                    insight_type=insight_data['type'],
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
            "new_insights": len(new_insights),
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
        triggered_by=sweep.triggered_by,
        execution_time_ms=sweep.execution_time_ms,
        insights_generated=sweep.insights_generated,
        errors_encountered=json.loads(sweep.errors_encountered) if sweep.errors_encountered else None,
        episodes_analyzed=sweep.episodes_analyzed,
        notes_analyzed=sweep.notes_analyzed,
        patterns_found=json.loads(sweep.patterns_found) if sweep.patterns_found else None,
        executed_at=sweep.executed_at
    ) for sweep in sweeps]


# GTKY endpoints removed - was broken and unused

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


# ==================== DAILY BRIEF ENDPOINTS ====================

@app.get("/api/daily-brief/stats")
async def get_daily_brief_stats(
    current_user: User = Depends(get_current_user)
):
    """Get statistics about the user's daily brief system"""
    if not DAILY_BRIEF_AVAILABLE:
        raise HTTPException(status_code=503, detail="Daily Brief service not available")

    try:
        stats = daily_brief_service.get_brief_stats(current_user.id)
        stats["is_bootstrapped"] = daily_brief_service.has_stable_layer(current_user.id)
        return stats
    except Exception as e:
        logger.error(f"Failed to get daily brief stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve stats")


@app.post("/api/daily-brief/bootstrap")
async def bootstrap_daily_brief(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually trigger bootstrap of the stable layer from conversation history"""
    if not DAILY_BRIEF_AVAILABLE:
        raise HTTPException(status_code=503, detail="Daily Brief service not available")

    try:
        success = await daily_brief_service.bootstrap_stable_layer(current_user.id, db)
        return {
            "success": success,
            "message": "Stable layer bootstrapped successfully" if success else "Bootstrap failed - check logs"
        }
    except Exception as e:
        logger.error(f"Failed to bootstrap daily brief: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/daily-brief/compiled")
async def get_compiled_brief(
    current_user: User = Depends(get_current_user)
):
    """Get the current compiled daily brief (for debugging/inspection)"""
    if not DAILY_BRIEF_AVAILABLE:
        raise HTTPException(status_code=503, detail="Daily Brief service not available")

    try:
        brief = await daily_brief_service.get_compiled_brief(current_user.id)
        return {
            "content": brief,
            "length": len(brief) if brief else 0
        }
    except Exception as e:
        logger.error(f"Failed to get compiled brief: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve brief")


@app.get("/api/daily-brief/layers/{layer_name}")
async def get_brief_layer(
    layer_name: str,
    current_user: User = Depends(get_current_user)
):
    """Get a specific layer of the daily brief"""
    if not DAILY_BRIEF_AVAILABLE:
        raise HTTPException(status_code=503, detail="Daily Brief service not available")

    valid_layers = ["moment", "day", "context", "stable"]
    if layer_name not in valid_layers:
        raise HTTPException(status_code=400, detail=f"Invalid layer. Must be one of: {valid_layers}")

    try:
        content = daily_brief_service._read_layer(current_user.id, layer_name)
        return {
            "layer": layer_name,
            "content": content,
            "length": len(content)
        }
    except Exception as e:
        logger.error(f"Failed to get layer {layer_name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve layer")


if __name__ == "__main__":
    import uvicorn
    # Allow host/port override via env for flexible deployment
    uvicorn_host = os.getenv("HOST", "0.0.0.0")
    uvicorn_port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host=uvicorn_host, port=uvicorn_port)
