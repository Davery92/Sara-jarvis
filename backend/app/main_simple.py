from fastapi import FastAPI, Depends, HTTPException, status, Response, Request, Query, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.routing import APIRoute
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
from app.core.timezone import naive_local_now
from zoneinfo import ZoneInfo
from app.core.timezone import now as local_now, today as local_today, format_datetime as format_local_datetime, USER_TIMEZONE, format_iso_utc, format_memory_timestamp, relative_time
from jose import jwt, JWTError
import uuid
import httpx
import json
import logging
import os
import base64
import hashlib
import secrets
import aiofiles
import asyncio
import json
from fastapi import UploadFile
from app.tools.registry import tool_registry
from fastapi import APIRouter
from urllib.parse import urlparse, parse_qsl, urlencode
import pytz
from app.tools.registry import tool_registry
from app.services.search_service import search_service
from app.services.soul_loader import load_soul_for_prompt
from app.services.embedding_service import embedding_service
from app.services.insight_injection import InsightInjectionService
from app.services.intent_classifier import get_tool_intent_classifier
# body_state_calibration removed — body state no longer injected into chat
from app.services.sara_journal_service import sara_journal
from app.services.context_router import get_context_router
from app.services.workout_session_service import workout_session_service
from app.services.cognitive.working_memory import get_working_memory_service
from app.services.cognitive.raw_buffer import get_raw_buffer_service, StreamType
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

# Configure structured logging
import os as _os
from app.core.logging import setup_logging, RequestLoggingMiddleware
setup_logging(
    service_name="sara-backend",
    environment=_os.environ.get("SENTRY_ENVIRONMENT", "development"),
    log_level=_os.environ.get("LOG_LEVEL", "INFO"),
    json_output=_os.environ.get("LOG_FORMAT", "text") == "json",
)
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

# ── Centralized app state (Phase 6A extraction foundation) ──
from app.core.app_state import get_app_state, AppState
_app_state = get_app_state()

# Backward-compatible aliases — existing code reads these globals directly.
# New code should use get_app_state() instead.
ASSISTANT_NAME = _app_state.assistant_name
# Backward-compatible global aliases — all values sourced from _app_state.
# Code that mutates these (e.g. `global OPENAI_MODEL; OPENAI_MODEL = x`)
# must ALSO update _app_state to keep them in sync.
DATABASE_URL = _app_state.database_url
CORS_ORIGINS = _app_state.cors_origins
ALLOWED_ORIGIN_REGEX = _app_state.allowed_origin_regex
NTFY_SERVER_URL = _app_state.ntfy_server_url
NTFY_ENABLED = _app_state.ntfy_enabled
NTFY_TIMERS_TOPIC = _app_state.ntfy_timers_topic
NTFY_REMINDERS_TOPIC = _app_state.ntfy_reminders_topic
NTFY_DOCUMENTS_TOPIC = _app_state.ntfy_documents_topic
# SARA_ALIVE_BUILD_PLAN Arc 3.4 — the hand-picked "always useful" tool core
# for the presence tool diet (Flag.PRESENCE_TOOL_DIET), replacing the 25-tool
# "always add" category list. dispatch_and_monitor is the escape hatch for
# anything beyond this set — already wired to kernel.focused_turn().
_PRESENCE_CORE_TOOL_NAMES = [
    "memory_search", "notes_create", "notes_search",
    "list_add", "list_view", "reminders_create", "calendar_list",
    "dispatch_and_monitor",
]

NTFY_SYSTEM_TOPIC = _app_state.ntfy_system_topic
AI_PROVIDER = _app_state.ai_provider
OPENAI_BASE_URL = _app_state.openai_base_url
OPENAI_MODEL = _app_state.openai_model
CHAT_DEFAULT_MODEL = _app_state.chat_default_model
OPENAI_API_KEY = _app_state.openai_api_key
ANTHROPIC_API_KEY = _app_state.anthropic_api_key
GOOGLE_API_KEY = _app_state.google_api_key
CODEX_OAUTH_CLIENT_ID = _app_state.codex_oauth_client_id
CODEX_OAUTH_AUTHORIZE_URL = _app_state.codex_oauth_authorize_url
CODEX_OAUTH_TOKEN_URL = _app_state.codex_oauth_token_url
CODEX_OAUTH_SCOPE = _app_state.codex_oauth_scope
CODEX_OAUTH_ORIGINATOR = _app_state.codex_oauth_originator
CODEX_OAUTH_REDIRECT_URI = _app_state.codex_oauth_redirect_uri
CODEX_DEFAULT_BASE_URL = _app_state.codex_default_base_url
CODEX_DEFAULT_MODEL = _app_state.codex_default_model
CODEX_JWT_CLAIM_PATH = "https://api.openai.com/auth"
CODEX_OAUTH_ACCESS_TOKEN = _app_state.codex_oauth_access_token
CODEX_OAUTH_REFRESH_TOKEN = _app_state.codex_oauth_refresh_token
CODEX_OAUTH_EXPIRES_AT = _app_state.codex_oauth_expires_at
CODEX_OAUTH_ACCOUNT_ID = _app_state.codex_oauth_account_id
CODEX_OAUTH_EMAIL = _app_state.codex_oauth_email
AVAILABLE_MODELS = _app_state.available_models

# Text utilities extracted to app.core.text_utils
from app.core.text_utils import extract_text_content as _extract_text_content
from app.core.text_utils import is_local_base_url as _is_local_base_url
from app.core.text_utils import safe_parse_iso_datetime as _safe_parse_iso_datetime
from app.core.text_utils import parse_glm45_tool_calls, parse_json_text_tool_calls, strip_tool_markup
from app.core.text_utils import claude_rejects_sampling_params, claude_thinking_always_on


async def _mark_shown_discoveries(user_id: str, response_text: str):
    """Mark show_david items as shown if Sara referenced them in her response."""
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    async with async_session() as db:
        result = await db.execute(text("""
            SELECT id, title FROM acs_show_david_buffer
            WHERE user_id = :uid AND shown = FALSE
            ORDER BY created_at DESC LIMIT 10
        """), {"uid": user_id})
        rows = result.fetchall()
        if not rows:
            return

        response_lower = response_text.lower()
        marked = 0
        for row in rows:
            # Check if the title (or significant words from it) appear in Sara's response
            title_words = [w for w in row[1].lower().split() if len(w) >= 4]
            if len(title_words) >= 2:
                matches = sum(1 for w in title_words if w in response_lower)
                if matches >= len(title_words) * 0.6:
                    await db.execute(text("""
                        UPDATE acs_show_david_buffer
                        SET shown = TRUE, shown_at = NOW()
                        WHERE id = :id
                    """), {"id": row[0]})
                    marked += 1

        if marked > 0:
            await db.commit()
            logger.info(f"Marked {marked} show_david items as shown")


def get_model_config(model_id: str) -> dict:
    """Get base URL, API key, and provider routing for the selected model."""
    model_id_l = (model_id or "").lower()
    configured_base = OPENAI_BASE_URL or "http://100.104.68.115:8081/v1"
    configured_key = OPENAI_API_KEY or "dummy"
    local_default_base = "http://100.104.68.115:8081/v1"

    # Resolve declared provider from the model catalog first.
    # This prevents stale global ai_provider settings from misrouting model-specific requests.
    catalog_entry = next(
        (m for m in AVAILABLE_MODELS if (m.get("id") or "").lower() == model_id_l),
        None,
    )
    catalog_provider = catalog_entry.get("provider") if catalog_entry else None
    catalog_base_url = catalog_entry.get("base_url") if catalog_entry else None

    if catalog_provider == "codex" or model_id_l.startswith("gpt-5.3-codex") or "codex" in model_id_l:
        codex_base = configured_base if "chatgpt.com/backend-api" in configured_base else CODEX_DEFAULT_BASE_URL
        return {
            "base_url": codex_base,
            "api_key": CODEX_OAUTH_ACCESS_TOKEN or configured_key,
            "provider": "codex"
        }

    # If model is explicitly cataloged, honor that provider first.
    # This keeps VOICE_MODEL / model overrides from being hijacked by global ai_provider.
    if catalog_provider == "anthropic" or model_id_l.startswith("claude"):
        return {
            "base_url": "https://api.anthropic.com",
            "api_key": ANTHROPIC_API_KEY,
            "provider": "anthropic"
        }
    if catalog_provider == "google" or model_id_l.startswith("gemini"):
        return {
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "api_key": GOOGLE_API_KEY,
            "provider": "google"
        }
    if catalog_provider == "local":
        if catalog_base_url:
            local_base = catalog_base_url
        else:
            local_base = configured_base if _is_local_base_url(configured_base) else local_default_base
        return {
            "base_url": local_base,
            "api_key": configured_key if configured_key else "dummy",
            "provider": "local",
        }
    if catalog_provider == "openai":
        return {
            "base_url": configured_base,
            "api_key": configured_key if configured_key else "dummy",
            "provider": "openai",
        }

    # Fallback: no explicit model mapping, use global provider state.
    if AI_PROVIDER == "codex" or "chatgpt.com/backend-api" in configured_base:
        return {
            "base_url": configured_base,
            "api_key": CODEX_OAUTH_ACCESS_TOKEN or configured_key,
            "provider": "codex"
        }

    if AI_PROVIDER == "claude":
        return {
            "base_url": "https://api.anthropic.com",
            "api_key": ANTHROPIC_API_KEY,
            "provider": "anthropic"
        }
    if AI_PROVIDER == "gemini":
        return {
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "api_key": GOOGLE_API_KEY,
            "provider": "google"
        }
    if _is_local_base_url(configured_base):
        return {
            "base_url": configured_base,
            "api_key": configured_key if configured_key else "dummy",
            "provider": "local"
        }
    return {
        "base_url": configured_base,
        "api_key": configured_key if configured_key else "dummy",
        "provider": "openai"
    }

def is_anthropic_provider() -> bool:
    """Check if the current provider is Anthropic Claude"""
    return "api.anthropic.com" in OPENAI_BASE_URL


# Codex OAuth helpers extracted to app.core.codex_oauth
from app.core.codex_oauth import (
    _decode_jwt_payload, _extract_codex_account_id_from_token,
    _extract_codex_email_from_token, _build_pkce_challenge,
    _append_query_params, _resolve_frontend_return_url,
    _resolve_backend_public_url, _upsert_app_settings,
    _load_codex_oauth_from_db, _apply_codex_oauth_token_data,
    _codex_exchange_authorization_code, _codex_refresh_tokens,
    _ensure_codex_access_token,
)

OPENAI_NOTIFICATION_MODEL = _app_state.notification_model
VOICE_MODEL = _app_state.voice_model
FAST_MODEL_URL = _app_state.fast_model_url
FAST_MODEL = _app_state.fast_model
FAST_MODEL_API_KEY = _app_state.fast_model_api_key
EMBEDDING_BASE_URL = _app_state.embedding_base_url
EMBEDDING_MODEL = _app_state.embedding_model
EMBEDDING_DIM = _app_state.embedding_dim

# Background LLM Configuration (separate from chat - always uses local models)
BG_LLM_PRIMARY_URL = os.getenv("BG_LLM_PRIMARY_URL", "http://100.104.68.115:8081/v1")
BG_LLM_PRIMARY_MODEL = os.getenv("BG_LLM_PRIMARY_MODEL", "qwen3.6-27b")
BG_LLM_FALLBACK_URL = os.getenv("BG_LLM_FALLBACK_URL", "http://10.185.1.8:8686/v1")
BG_LLM_FALLBACK_MODEL = os.getenv("BG_LLM_FALLBACK_MODEL", "Qwen3.5-35B-A3B")
BG_LLM_REQUEST_TIMEOUT = float(os.getenv("BG_LLM_REQUEST_TIMEOUT", "90"))
BG_LLM_CONNECT_TIMEOUT = float(os.getenv("BG_LLM_CONNECT_TIMEOUT", "6"))
BG_LLM_NUM_CTX = int(os.getenv("BG_LLM_NUM_CTX", "16384"))

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

# Startup health tracking — shared with routes/core.py
from app.core.health_state import STARTUP_HEALTH

# Database setup — reuse the shared engine from app.db.base to avoid multiple connection pools
from app.db.base import engine, SessionLocal
Base = declarative_base()

# ===================== MODEL IMPORTS =====================
# Models extracted to backend/app/models/ (Phase 2)
from app.models.user import User
from app.models.note import Note
from app.models.note_connection import NoteConnection
from app.models.folder import Folder
from app.models.reminder import Reminder, Timer
from app.models.episode import Episode
from app.models.episode_rating import EpisodeRating
from app.models.conversation import Conversation, ConversationTurn
from app.models.background_task import BackgroundTask
# MemoryTrace/MemoryEmbedding/MemoryEdge: deprecated, kept for table definitions only
from app.models.context import ContextWindow, ContextMode
from app.models.dream import DreamInsight
from app.models.briefing import DailyBriefing, BriefingSettings
from app.models.intelligence import IntelligenceReport
from app.models.insight import AutonomousInsight, InsightNudge, ActivitySession, BackgroundSweep
from app.models.event_outbox import EventOutbox
from app.models.push_token import PushToken
from app.models.calendar_event import CalendarEvent
from app.models.document_chunk import DocumentChunk
from app.models.doc import Document
from app.models.profile import UserProfile

# ===================== SCHEMA IMPORTS =====================
# Schemas extracted to backend/app/schemas/ (Phase 2)
from app.schemas.auth import UserCreate, UserLogin, UserResponse
from app.schemas.notes import (
    NoteCreate, NoteResponse, NoteConnectionCreate, NoteConnectionResponse,
    FolderCreate, FolderUpdate, FolderResponse, TreeNodeResponse,
)
from app.schemas.reminders import ReminderCreate, ReminderUpdate, ReminderResponse, TimerCreate, TimerResponse
from app.schemas.calendar import (
    CalendarEventCreate, CalendarEventUpdate, CalendarEventResponse,
    IOSCalendarEventSync as IOSCalendarEvent, IOSCalendarSyncRequest, IOSCalendarSyncResponse,
)
from app.schemas.chat import ChatMessage, ChatRequest, ChatResponse
from app.schemas.documents import DocumentResponse, DocumentChunkResponse, Model3DResponse
from app.schemas.memory import (
    ConversationResponse, ConversationTurnResponse, ConversationSummaryResponse,
    SetActiveConversationRequest, EpisodeMessageResponse,
)
from app.schemas.insights import (
    UserProfileCreate, UserProfileResponse,
    AutonomousInsightResponse, InsightFeedbackRequest,
    ActivitySessionResponse, BackgroundSweepResponse,
)
from app.schemas.reflection import (
    ReflectionStartResponse,
    ReflectionResponseRequest, ReflectionResponseReply,
    ReflectionHistoryResponse, ReflectionInsightsResponse,
    ReflectionSettingsRequest,
)
from app.schemas.ai_settings import AISettingsResponse, AISettingsUpdate


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
        # H5 (Brain Alignment): per-tool malformed-argument counts within this
        # client's lifetime, so a second failure degrades in-voice instead of
        # looping forever or leaking a raw parse error.
        self._tool_parse_failures: Dict[str, int] = {}

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
                # Flush any pending tool results BEFORE adding an assistant message
                # (Anthropic requires tool_result immediately after tool_use)
                if pending_tool_results:
                    anthropic_messages.append({"role": "user", "content": pending_tool_results})
                    pending_tool_results = []

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

    async def _anthropic_chat_request(self, messages: list, tools: list = None, max_tokens: int = 4096, temperature: float = 0.7, model: str = None):
        """Make a chat request to Anthropic Claude API and convert response to OpenAI format"""
        # Extract system message and convert messages to Anthropic format
        system_content = None
        for msg in messages:
            if msg.get("role") == "system":
                system_content = msg.get("content", "")
                break

        filtered_messages = self._convert_openai_messages_to_anthropic(messages)

        # Use provided model or fall back to default
        effective_model = model or OPENAI_MODEL

        # Build Anthropic request payload with prompt caching
        payload = {
            "model": effective_model,
            "messages": filtered_messages,
            "max_tokens": max_tokens,
        }

        # Reasoning-only Claude models (Sonnet 5, Opus 4.7/4.8, Fable 5) return a
        # 400 if `temperature` is supplied. For those, drop the sampling param and
        # turn on adaptive thinking (the model decides how much to reason per turn).
        # Adaptive thinking shares the max_tokens budget with the visible reply, so
        # give it generous headroom to avoid truncating the answer. Fable/Mythos
        # have thinking always on and reject an explicit thinking config.
        reasoning_only = claude_rejects_sampling_params(effective_model)
        if reasoning_only:
            if not claude_thinking_always_on(effective_model):
                payload["thinking"] = {"type": "adaptive"}
            payload["max_tokens"] = max(max_tokens, 32000)
        else:
            payload["temperature"] = temperature

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
                headers=self._get_anthropic_headers(),
                # Adaptive thinking + larger max_tokens can take longer to generate
                # on this non-streaming path; widen the read timeout past the
                # client default (120s) so heavier turns don't spuriously fail.
                timeout=300.0 if reasoning_only else httpx.USE_CLIENT_DEFAULT,
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
        # Item 2.5 (2026-07-31): this logged OPENAI_MODEL — the shared
        # cognition/utility model name — for every Anthropic-routed call,
        # misattributing cost/usage tracking regardless of which model
        # actually served the request. self._current_model is set by
        # chat_with_tools (the sole caller path that reaches here) to the
        # model that was actually dispatched; same fix already applied at
        # the "model": self._current_model line below in _stream_response.
        usage = anthropic_response.get("usage", {})
        if usage:
            self._log_token_usage(
                prompt_tokens=usage.get("input_tokens", 0),
                completion_tokens=usage.get("output_tokens", 0),
                total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                model=getattr(self, "_current_model", None) or OPENAI_MODEL,
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
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
            })
            logger.info(f"📤 Event QUEUED: {event_type}")
        else:
            logger.error(f"❌ NO EVENT QUEUE for '{event_type}'!")
    
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

    def _content_to_text(self, content: Any) -> str:
        """Normalize OpenAI-style message content into plain text."""
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text" and item.get("text"):
                        parts.append(str(item.get("text")))
                    elif item.get("type") == "input_text" and item.get("text"):
                        parts.append(str(item.get("text")))
                elif isinstance(item, str):
                    parts.append(item)
            return "\n".join([p for p in parts if p])
        return str(content)

    def _convert_openai_messages_to_codex_input(self, messages: list) -> tuple[str, list]:
        instructions: List[str] = []
        converted: List[Dict[str, Any]] = []
        call_counter = 0

        def _to_json_string(value: Any) -> str:
            if isinstance(value, str):
                return value
            try:
                return json.dumps(value if value is not None else {})
            except Exception:
                return "{}"

        for msg in messages:
            role = msg.get("role")
            content_text = self._content_to_text(msg.get("content"))

            if role == "system":
                if content_text:
                    instructions.append(content_text)
                continue

            if role == "user":
                converted.append(
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": content_text or ""}],
                    }
                )
                continue

            if role == "assistant":
                if content_text:
                    converted.append(
                        {
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": content_text}],
                        }
                    )

                for tc in (msg.get("tool_calls") or []):
                    func = tc.get("function", {}) if isinstance(tc, dict) else {}
                    raw_id = str(tc.get("id") or f"call_{call_counter}")
                    call_counter += 1
                    call_id = raw_id.split("|")[0]
                    item_id = f"fc_{call_id[:58]}" if not raw_id.startswith("fc_") else raw_id[:64]
                    converted.append(
                        {
                            "type": "function_call",
                            "call_id": call_id,
                            "id": item_id,
                            "name": func.get("name") or "unknown_tool",
                            "arguments": _to_json_string(func.get("arguments")),
                        }
                    )
                continue

            if role == "tool":
                tool_call_id = str(msg.get("tool_call_id") or "")
                call_id = tool_call_id.split("|")[0]
                if call_id:
                    converted.append(
                        {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": content_text or "",
                        }
                    )

        return "\n\n".join(instructions), converted

    def _convert_openai_tools_to_codex_tools(self, tools: list) -> list:
        converted_tools = []
        for tool in tools or []:
            if tool.get("type") != "function":
                continue
            fn = tool.get("function", {})
            name = fn.get("name")
            if not name:
                continue
            converted_tools.append(
                {
                    "type": "function",
                    "name": name,
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
                }
            )
        return converted_tools

    async def _stream_codex_response(self, payload: dict, base_url: str, api_key: str) -> dict:
        """Stream from ChatGPT/Codex responses API and map into OpenAI-compatible message output."""
        # Ensure a fresh OAuth token before request
        token = await _ensure_codex_access_token(updated_by="codex-runtime", min_valid_seconds=120) or api_key
        account_id = CODEX_OAUTH_ACCOUNT_ID or _extract_codex_account_id_from_token(token or "")
        if not token or not account_id:
            raise RuntimeError("Codex OAuth not connected. Connect in Settings first.")

        instructions, input_items = self._convert_openai_messages_to_codex_input(payload.get("messages", []))
        codex_body: Dict[str, Any] = {
            "model": payload.get("model") or OPENAI_MODEL or CODEX_DEFAULT_MODEL,
            "store": False,
            "stream": True,
            "instructions": instructions or "You are a helpful assistant.",
            "input": input_items,
            "text": {"verbosity": "medium"},
            "tool_choice": "auto",
            "parallel_tool_calls": True,
        }
        codex_tools = self._convert_openai_tools_to_codex_tools(payload.get("tools", []))
        if codex_tools:
            codex_body["tools"] = codex_tools

        codex_url = f"{base_url.rstrip('/')}/codex/responses"
        full_content = ""
        usage_data = {}
        tool_calls_map: Dict[str, Dict[str, Any]] = {}
        active_call_id: Optional[str] = None

        def _to_json_string(value: Any) -> str:
            if isinstance(value, str):
                return value
            try:
                return json.dumps(value if value is not None else {})
            except Exception:
                return "{}"

        async with self.client.stream(
            "POST",
            codex_url,
            json=codex_body,
            headers={
                "Authorization": f"Bearer {token}",
                "chatgpt-account-id": account_id,
                "OpenAI-Beta": "responses=experimental",
                "originator": CODEX_OAUTH_ORIGINATOR,
                "accept": "text/event-stream",
            },
        ) as response:
            if response.status_code >= 400:
                err = await response.aread()
                raise RuntimeError(f"Codex request failed ({response.status_code}): {err.decode(errors='ignore')[:300]}")

            async for line in response.aiter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    line = line[6:]
                if line == "[DONE]":
                    break
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type")
                if event_type == "error":
                    raise RuntimeError(event.get("message") or "Codex stream error")
                if event_type in ("response.output_text.delta", "response.refusal.delta"):
                    delta = event.get("delta") or ""
                    if delta:
                        full_content += delta
                        if self.event_queue:
                            await self.emit_event("text_chunk", {"content": delta, "full_content": full_content})
                elif event_type == "response.output_item.added":
                    item = event.get("item") or {}
                    if item.get("type") == "function_call":
                        call_id = str(item.get("call_id") or "")
                        if call_id:
                            active_call_id = call_id
                            tool_calls_map[call_id] = {
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": item.get("name") or "unknown_tool",
                                    "arguments": _to_json_string(item.get("arguments")),
                                },
                            }
                elif event_type == "response.function_call_arguments.delta":
                    delta = event.get("delta") or ""
                    if active_call_id and active_call_id in tool_calls_map:
                        tool_calls_map[active_call_id]["function"]["arguments"] += delta
                elif event_type == "response.output_item.done":
                    item = event.get("item") or {}
                    if item.get("type") == "function_call":
                        call_id = str(item.get("call_id") or active_call_id or "")
                        if call_id:
                            active_call_id = call_id
                            tool_calls_map[call_id] = {
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": item.get("name") or "unknown_tool",
                                    "arguments": _to_json_string(
                                        item.get("arguments")
                                        if item.get("arguments") is not None
                                        else tool_calls_map.get(call_id, {}).get("function", {}).get("arguments", "{}")
                                    ),
                                },
                            }
                elif event_type in ("response.completed", "response.done"):
                    response_payload = event.get("response") or {}
                    usage = response_payload.get("usage") or {}
                    if usage:
                        usage_data = {
                            "prompt_tokens": usage.get("input_tokens", 0),
                            "completion_tokens": usage.get("output_tokens", 0),
                            "total_tokens": usage.get("total_tokens", 0),
                        }

        if usage_data:
            self._log_token_usage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
                model=payload.get("model") or "unknown",  # item 2.5: payload always sets this from effective_model; OPENAI_MODEL was a misleading fallback
                operation_type="chat",
            )

        return {
            "content": full_content,
            "tool_calls": list(tool_calls_map.values()) if tool_calls_map else None,
        }

    async def _stream_response(self, payload):
        """Stream response from LLM with XML filtering for GLM-4.5 and MLX channel format"""
        import re

        # Get model config - use stored config or fall back to global
        model_config = getattr(self, '_current_model_config', None)
        if model_config:
            base_url = model_config["base_url"]
            api_key = model_config["api_key"]
            provider = model_config["provider"]
        else:
            base_url = OPENAI_BASE_URL
            api_key = OPENAI_API_KEY
            provider = "local" if "11434" in OPENAI_BASE_URL else "unknown"

        # Route to Anthropic handler if using Claude API (non-streaming for now)
        logger.info(f"🔀 Provider routing: provider={provider}, base_url={base_url[:50]}")
        if provider == "codex":
            logger.info("Using ChatGPT Codex Responses API")
            return await self._stream_codex_response(payload, base_url, api_key)

        if provider == "anthropic":
            logger.info("Using Anthropic Claude API (non-streaming mode)")
            messages = payload.get("messages", [])
            tools = payload.get("tools", [])
            max_tokens = payload.get("max_tokens", 4096)
            temperature = payload.get("temperature", 0.7)
            model = payload.get("model", "claude-sonnet-4-6")

            result = await self._anthropic_chat_request(
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                model=model
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
            logger.info(f"🔍 Sending to {base_url}/chat/completions with model={payload.get('model')}, keys={list(payload.keys())}")
            if "generativelanguage.googleapis.com" in base_url:
                logger.debug(f"🔍 Gemini payload tools: {len(payload.get('tools', []))} tools")
            async with self.client.stream("POST", f"{base_url}/chat/completions",
                                        json=payload,
                                        headers={"Authorization": f"Bearer {api_key}"}) as response:
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

                            # Some models/providers lead their very first token
                            # with a stray newline from the chat template — strip
                            # it here (once, at the true start of the response)
                            # rather than at every downstream emit site.
                            if not full_content:
                                content_chunk = content_chunk.lstrip("\n")

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

                        # Handle tool calls (standard OpenAI streaming format).
                        # Each delta tool_call carries an `index` field identifying which
                        # parallel call it belongs to. Positional merging breaks when
                        # parallel calls interleave — use `index` to route correctly.
                        if "tool_calls" in delta and delta["tool_calls"]:
                            for tc_delta in delta["tool_calls"]:
                                idx = tc_delta.get("index")
                                if idx is None:
                                    idx = len(tool_calls)
                                while len(tool_calls) <= idx:
                                    tool_calls.append({
                                        "id": "",
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""},
                                    })
                                target = tool_calls[idx]
                                if tc_delta.get("id"):
                                    target["id"] = tc_delta["id"]
                                if tc_delta.get("type"):
                                    target["type"] = tc_delta["type"]
                                fn_delta = tc_delta.get("function") or {}
                                target_fn = target.setdefault(
                                    "function", {"name": "", "arguments": ""}
                                )
                                if fn_delta.get("name") and not target_fn.get("name"):
                                    target_fn["name"] = fn_delta["name"]
                                if fn_delta.get("arguments"):
                                    target_fn["arguments"] = (
                                        target_fn.get("arguments") or ""
                                    ) + fn_delta["arguments"]

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
                    model=payload.get("model") or "unknown",  # item 2.5: payload always sets this from effective_model; OPENAI_MODEL was a misleading fallback
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
                    model=payload.get("model") or "unknown",  # item 2.5: payload always sets this from effective_model; OPENAI_MODEL was a misleading fallback
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
                    model=payload.get("model") or "unknown",  # item 2.5: payload always sets this from effective_model; OPENAI_MODEL was a misleading fallback
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
                f"{base_url}/chat/completions",
                json=payload_fallback,
                headers={"Authorization": f"Bearer {api_key}"}
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]

    async def chat(self, messages: list, model: str | None = None):
        try:
            # Handle both dict and object message formats
            formatted_messages = []
            for m in messages:
                if isinstance(m, dict):
                    formatted_messages.append({"role": m["role"], "content": m["content"]})
                else:
                    formatted_messages.append({"role": m.role, "content": m.content})

            effective_model = model or OPENAI_MODEL or CODEX_DEFAULT_MODEL
            model_config = get_model_config(effective_model)
            provider = model_config["provider"]

            # Route by effective model provider (not global OPENAI_BASE_URL).
            if provider == "anthropic":
                result = await self._anthropic_chat_request(
                    messages=formatted_messages,
                    tools=None,
                    max_tokens=8000,
                    temperature=0.7,
                    model=effective_model,
                )
                return result.get("content", "")

            if provider == "codex":
                codex_result = await self._stream_codex_response(
                    {
                        "model": effective_model,
                        "messages": formatted_messages,
                        "temperature": 0.7,
                    },
                    model_config["base_url"],
                    model_config["api_key"],
                )
                return codex_result.get("content", "")

            # Build payload for OpenAI-compatible API
            chat_payload = {
                "model": effective_model,
                "messages": formatted_messages,
                "temperature": 0.7,
                "max_tokens": 8000
            }

            # Add Ollama-specific context length if using local model
            if provider == "local":
                chat_payload["num_ctx"] = 32768

            response = await self.client.post(
                f"{model_config['base_url']}/chat/completions",
                json=chat_payload,
                headers={"Authorization": f"Bearer {model_config['api_key']}"}
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return f"I'm sorry, I'm having trouble connecting to my AI service. Error: {str(e)}"

    async def chat_with_tools(self, messages, tools, user_id, conversation_id=None, model=None, ephemeral=False):
        """Enhanced chat with tool calling support

        Args:
            messages: List of chat messages
            tools: List of tool definitions
            user_id: User ID
            conversation_id: Optional conversation ID for context
            model: Optional model override (e.g., "claude-opus-4-6", "gemini-2.5-pro")
            ephemeral: If True, don't save to memory/episodes
        """
        try:
            logger.info(f"🔧 chat_with_tools called with conversation_id: {conversation_id}, model: {model}, ephemeral: {ephemeral}")

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

            # Also get current displayed map (tracked per user)
            from app.tools.maps import get_current_map
            current_map = get_current_map(user_id)

            context_reminder = ""
            has_context = any(session_summary.get(k) for k in ["notes", "documents", "memories", "web_pages"]) or current_map
            if has_context:
                context_lines = ["\n## Session Context (already retrieved this conversation)"]
                if current_map:
                    context_lines.append(f"**Currently displayed map:** \"{current_map.get('map_name')}\"")
                    context_lines.append("  → Just call map_explode with NO parameters - it auto-detects the current map")
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

            # Store ephemeral flag for use in store_conversation
            self._ephemeral = ephemeral

            # Determine which model to use. Reject overrides that aren't in the
            # catalog — stale clients still request retired models (e.g. the old
            # iOS default "gpt-oss:120b"), which would otherwise fall through to
            # the global provider and 404 against Anthropic/Gemini.
            #
            # Presence-latency investigation (SARA_ALIVE §6 follow-up,
            # 2026-07-31): this fell back to OPENAI_MODEL — the shared
            # utility/cognition model (Qwen) — not CHAT_DEFAULT_MODEL, the
            # three-speed contract's actual presence model (Claude Sonnet 5).
            # Confirmed live via real request logs: every real chat turn with
            # no client-supplied model override ("requested=None") was being
            # served by qwen3.6-27b, sharing an inference host/queue with all
            # of Sara's background cognition (ambient turns, judge/compose,
            # dreaming) — the load-bearing suspect behind the measured
            # p50=66.2s/p90=167.5s presence latency. This is the routing fix;
            # OPENAI_MODEL stays the last-resort fallback only if
            # CHAT_DEFAULT_MODEL is somehow unset.
            _default_model = CHAT_DEFAULT_MODEL or OPENAI_MODEL
            effective_model = model or _default_model
            _known_model_ids = {(m.get("id") or "").lower() for m in AVAILABLE_MODELS}
            if model and model.lower() not in _known_model_ids:
                logger.warning(
                    f"Requested model '{model}' not in catalog — using default '{_default_model}'"
                )
                effective_model = _default_model
            model_config = get_model_config(effective_model)
            logger.info(f"🤖 Model selection: requested={model}, effective={effective_model}, provider={model_config['provider']}, base_url={model_config['base_url']}")

            # Store model config for _stream_response to use
            self._current_model = effective_model
            self._current_model_config = model_config

            payload = {
                "model": effective_model,
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
            if model_config["provider"] == "local":
                payload["num_ctx"] = 32768

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
                        "model": self._current_model,  # Use user-selected model, not default
                        "messages": current_messages,
                        "temperature": 0.7,
                        "max_tokens": 8000,
                        "tools": tools,
                        "stream": True
                    }

                    # Add Ollama-specific context length if using local model
                    if self._current_model_config.get("provider") == "local":
                        follow_up_payload["num_ctx"] = 32768

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
                                completion_msg = _summarize_tool_results(tool_responses)
                                message = {
                                    "content": completion_msg,
                                    "tool_calls": None
                                }
                        except Exception as e:
                            # Other errors should be caught but not crash - fallback to tool results
                            logger.error(f"❌ Unexpected error during LLM call: {e}")
                            completion_msg = _summarize_tool_results(tool_responses)
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

                    # If no more tool calls, we're done
                    if not message.get("tool_calls"):
                        response_content = message["content"]
                        await self.emit_event("response_ready", {
                            "rounds": round_num + 1,
                            "content_length": len(response_content) if response_content else 0
                        })
                        # Store conversation and get episode_id for rating
                        episode_id = await self._store_conversation_with_timeout(
                            messages, response_content, user_id, conversation_id
                        )
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
                    episode_id = await self._store_conversation_with_timeout(
                        messages, response_content, user_id, conversation_id
                    )
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
            episode_id = await self._store_conversation_with_timeout(
                messages, response_content, user_id, conversation_id
            )
            self.current_episode_id = episode_id
            logger.warning(f"Hit max tool rounds, returning: {len(response_content)} chars")
            return response_content

        except Exception as e:
            import traceback
            logger.error(f"LLM error in chat_with_tools: {e}")
            logger.error(f"Full traceback:\n{traceback.format_exc()}")
            return f"I'm sorry, I'm having trouble connecting to my AI service. Error: {str(e)}"

    async def _store_conversation_with_timeout(
        self,
        messages,
        response_content,
        user_id,
        conversation_id,
        timeout_seconds: float = 4.0
    ) -> Optional[str]:
        """
        Keep chat completion responsive: do not block final stream events on memory persistence.
        If storage exceeds timeout, continue without waiting and persist in background.

        The assistant episode id is generated up front (not read off the DB
        row after insert) so callers — namely the SSE final_response frame —
        always have the real id synchronously, even when persistence itself
        is still running in the background past the timeout. Without this,
        final_response.episode_id was null whenever storage ran long, and the
        client had no id to attach a rating to.
        """
        # Only the assistant-response episode gets a pre-generated id — if
        # there's no response_content, store_conversation writes nothing for
        # it and a pre-issued id would dangle (no matching episode row).
        pre_episode_id = str(uuid.uuid4()) if response_content else None
        store_task = asyncio.create_task(
            self.store_conversation(messages, response_content, user_id, conversation_id, assistant_episode_id=pre_episode_id)
        )
        try:
            await asyncio.wait_for(asyncio.shield(store_task), timeout=timeout_seconds)
            return pre_episode_id
        except asyncio.TimeoutError:
            logger.warning(
                f"⚠️ store_conversation timed out after {timeout_seconds}s; continuing stream without waiting"
            )
            def _log_background_failure(task: asyncio.Task):
                try:
                    exc = task.exception()
                except asyncio.CancelledError:
                    return
                if exc:
                    logger.warning(f"⚠️ Background conversation storage failed: {exc}")

            store_task.add_done_callback(_log_background_failure)
            return pre_episode_id
        except Exception as e:
            logger.warning(f"⚠️ Conversation storage failed (continuing): {e}")
            return None

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
                    # H5 (Brain Alignment): never surface a raw parse error. Feed
                    # the model an in-voice retry instruction the first time;
                    # degrade gracefully the second time. Log it so the funnel
                    # sees it instead of David.
                    logger.error(f"❌ Could not fix malformed arguments for {function_name}: {e}")
                    try:
                        from app.services.silent_failure_tracker import Tracker
                        Tracker("chat.tool_arg_parse").note(f"{function_name}")
                    except Exception:
                        pass
                    self._tool_parse_failures[function_name] = self._tool_parse_failures.get(function_name, 0) + 1
                    if self._tool_parse_failures[function_name] >= 2:
                        # Second failure: stop retrying, tell Sara to recover in-voice.
                        retry_instruction = (
                            f"The {function_name} action failed twice because the arguments "
                            "couldn't be formed. Do NOT call it again this turn. Tell David "
                            "briefly and naturally that you hit a snag doing that and will try "
                            "again shortly (or ask him to rephrase) — never show error text."
                        )
                    else:
                        retry_instruction = (
                            f"The arguments for {function_name} were malformed and couldn't be "
                            "parsed. Re-issue the call ONCE with corrected, minimal, valid JSON "
                            "arguments. If you can't, tell David in-voice that you fumbled it and "
                            "are retrying — never expose the raw error."
                        )
                    return {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": json.dumps({
                            "success": False,
                            "message": retry_instruction,
                            "data": None
                        })
                    }

        logger.info(f"Executing tool {function_name} with arguments: {arguments}")

        # Emit tool_executing event for iOS status indicator
        try:
            await self.emit_event("tool_executing", {"tool": function_name})
        except Exception:
            pass

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
        
        # Work-order item 5 (2026-07-30): the 8 inline branches that used to
        # live here (search_notes/create_note/list_notes/list_folders/
        # create_reminder/start_timer/search_documents/search_memory) were
        # dead code — chat_with_tools' `tools` list is built exclusively from
        # tool_registry (get_tools_by_categories/get_tools_by_names), which
        # never emits those schema names, so the branches could never fire.
        # Their real equivalents (notes_search, notes_create, notes_list,
        # notes_list_folders, reminders_create, timers_start, memory_search,
        # and the newly-built documents_search) are registry tools reachable
        # below. Backing methods deleted with the branches — no other caller.
        # H6 (Brain Alignment): body schema. If the model calls a tool that
        # isn't actually wired, say so plainly instead of guessing — Sara
        # should have an accurate self-model of her own capabilities.
        if not tool_registry.get_tool(function_name):
            from app.services.capability_manifest import not_wired_result
            logger.warning(f"🦾 Model called unwired tool '{function_name}'")
            return {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": json.dumps({
                    "success": False,
                    "message": not_wired_result(function_name),
                    "data": None,
                }),
            }
        # Dispatch through the global tool registry.
        try:
            reg_result = await tool_registry.execute_tool(
                name=function_name,
                user_id=str(user_id),
                parameters=arguments,
                context={"origin": "chat", "conversation_id": conversation_id},
            )
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

                # Surface commands (ephemeral interactive UI) — same forwarding
                # pattern; the web `custom` view + Redis mirror consume these.
                surface_command = reg_result.data.get("surface_command")
                if surface_command:
                    await self.emit_event("surface_command", reg_result.data)
                    logger.info(f"🧩 Emitted surface_command: {surface_command}")
                    try:
                        from redis import Redis
                        redis_conn = Redis.from_url(config.settings.redis_url, decode_responses=True)
                        redis_conn.lpush(f"surface_commands:{user_id}", json.dumps(reg_result.data))
                        redis_conn.expire(f"surface_commands:{user_id}", 60)
                    except Exception as e:
                        logger.warning(f"Failed to mirror surface_command to Redis: {e}")

                # Emit workspace_command SSE event for workbench-canvas
                workspace_commands = []
                if isinstance(reg_result.data.get("workspace_commands"), list):
                    workspace_commands = [
                        cmd for cmd in reg_result.data.get("workspace_commands", [])
                        if isinstance(cmd, dict) and cmd.get("workspace_command")
                    ]

                workspace_command = reg_result.data.get("workspace_command")
                if workspace_command and not workspace_commands:
                    workspace_commands = [reg_result.data]

                if workspace_commands:
                    for cmd in workspace_commands:
                        await self.emit_event("workspace_command", cmd)
                    logger.info(f"🖼️ Emitted {len(workspace_commands)} workspace_command event(s)")

                    # Also store in Redis for voice/non-SSE access
                    try:
                        from redis import Redis
                        redis_conn = Redis.from_url(config.settings.redis_url, decode_responses=True)
                        for cmd in workspace_commands:
                            cmd_data = json.dumps(cmd)
                            redis_conn.lpush(f"workspace_commands:{user_id}", cmd_data)
                        redis_conn.expire(f"workspace_commands:{user_id}", 60)  # 1 minute TTL
                        logger.info(f"🖼️ Stored {len(workspace_commands)} workspace_command(s) in Redis for user {user_id}")
                    except Exception as e:
                        logger.warning(f"Failed to store workspace_command in Redis: {e}")

            result = json.dumps({
                "success": reg_result.success,
                "message": reg_result.message,
                "data": reg_result.data
            })
            _tool_call_success = reg_result.success
            _tool_call_error = None if reg_result.success else reg_result.message
        except Exception as e:
            result = f"Unknown tool: {function_name} ({e})"
            _tool_call_success = False
            _tool_call_error = f"{type(e).__name__}: {e}"

        # STORE IN CACHE
        if session_cache and conversation_id:
            session_cache.set(conversation_id, function_name, arguments, str(result))

        # Arc 6.5 (skill minting, work-order item 4, 2026-07-31): fumble
        # detector B needs a real record of which tools get called together
        # in one conversation — kernel-hands already logs its own (capped at
        # 1 call/turn, so no sequence to find there) via the same
        # sara_activity_log shape; regular chat tool-calling had no record
        # at all until now. Fire-and-forget, never blocks the chat response.
        try:
            from app.routes.acs_daemon import append_activity, ActivityIn
            await append_activity(ActivityIn(
                kind="tool_result",
                summary=f"{function_name}(...)" + (" → error" if not _tool_call_success else ""),
                body=(_tool_call_error or "")[:2000],
                tags=["error"] if not _tool_call_success else [],
                metadata={
                    "tool": function_name, "args": arguments, "source": "chat",
                    "conversation_id": conversation_id, "error": _tool_call_error,
                },
            ))
        except Exception as _log_e:
            logger.debug(f"chat tool-call activity log skipped: {_log_e}")

        logger.info(f"Tool {function_name} result length: {len(str(result))} chars")
        if function_name == "documents_search":
            logger.info(f"Search result preview: {str(result)[:500]}...")

        # Emit tool_completed event
        try:
            await self.emit_event("tool_completed", {"tool": function_name})
        except Exception:
            pass

        # Emit content_card SSE event for rich iOS rendering
        try:
            from app.services.content_card_builder import build_card
            card = build_card(function_name, str(result))
            if card:
                await self.emit_event("content_card", card)
                logger.info(f"🃏 Emitted content_card: {card.get('card_type')}")
        except Exception as e:
            logger.debug(f"Content card build skipped: {e}")

        # Track tool usage for suggested actions
        if not hasattr(self, '_tool_history'):
            self._tool_history = []
        self._tool_history.append(function_name)

        return {
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "content": str(result)
        }

    def get_citations(self):
        return list(self._citations)

    async def store_conversation(self, messages, response_content, user_id, conversation_id=None, assistant_episode_id=None) -> str:
        """Store the conversation in enhanced episodic memory with emotional and topical analysis.
        Returns the episode_id of the assistant response for rating purposes."""
        try:
            # Skip storage if ephemeral mode is enabled
            if getattr(self, '_ephemeral', False):
                logger.info(f"👻 Ephemeral mode - skipping conversation storage")
                return None

            logger.info(f"📥 store_conversation called with conversation_id: {conversation_id}")

            # conversation_id should already be set by chat_with_tools
            # This is just a safety check
            if not conversation_id:
                logger.warning("⚠️ store_conversation called without conversation_id, using current_conversation_id")
                conversation_id = self.current_conversation_id or str(uuid.uuid4())

            logger.info(f"✅ Storing conversation with ID: {conversation_id}")
            # Deduplicate by (conversation_id, role, ordinal) — not by content.
            # Content-based dedup silently drops legitimate repeated messages.
            db = SessionLocal()
            try:
                existing_episodes = db.query(Episode).filter(
                    Episode.conversation_id == conversation_id,
                    Episode.user_id == user_id
                ).all()
                stored_count = len(existing_episodes)

                # Store only messages beyond what's already persisted
                for idx, message in enumerate(messages):
                    if idx < stored_count:
                        continue  # Already stored from a previous call

                    if isinstance(message, dict):
                        role = message.get("role")
                        content = _extract_text_content(message.get("content"))
                    else:
                        role = message.role
                        content = _extract_text_content(message.content)

                    if role in ["user", "assistant"] and content:
                        await intelligent_memory_service.store_episode(
                            user_id=user_id,
                            role=role,
                            content=content,
                            conversation_id=conversation_id,
                            source="chat",
                            memory_type="conversation"
                        )
                        stored_count += 1

                        # Real-time PKG extraction for user messages
                        if role == "user":
                            try:
                                from app.services.pkg_realtime_extractor import process_message_for_pkg
                                await process_message_for_pkg(user_id, content)
                            except Exception:
                                pass  # Non-critical

                            # SARA_UNLEASHED Phase D.3: bump known-person mentions
                            # in real time instead of waiting for consolidation.
                            try:
                                from app.services.pkg_realtime_extractor import bump_mentioned_people
                                await bump_mentioned_people(user_id, content)
                            except Exception:
                                pass  # Non-critical
            finally:
                db.close()

            # Store assistant response as an episode
            if response_content:
                episode = await intelligent_memory_service.store_episode(
                    user_id=user_id,
                    role="assistant",
                    content=response_content,
                    conversation_id=conversation_id,
                    source="chat",
                    memory_type="conversation",
                    episode_id=assistant_episode_id
                )
                assistant_episode_id = episode.id if episode else assistant_episode_id
                logger.info(f"🎯 Assistant episode stored with ID: {assistant_episode_id}")

            # Also maintain legacy conversation storage for compatibility
            await self._store_legacy_conversation(messages, response_content, user_id, conversation_id)

            # Mark show_david items as shown if Sara referenced them in her response
            if response_content:
                try:
                    await _mark_shown_discoveries(user_id, response_content)
                except Exception as e:
                    logger.debug(f"mark_shown_discoveries failed: {e}")

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
                        total_messages=0
                    )
                    db.add(conversation)
                    db.commit()
                else:
                    # Update existing conversation
                    conversation = existing_conversation
                    conversation.updated_at = func.now()
                    db.commit()
                
                # Get current turn count for indexing
                current_turn_count = db.query(ConversationTurn).filter(
                    ConversationTurn.conversation_id == conversation_id
                ).count()
                
                # Only store the new user message (last message in the list), idempotently.
                last_message = messages[-1] if messages else None
                if last_message:
                    if isinstance(last_message, dict):
                        last_role = last_message.get("role")
                        last_content = _extract_text_content(last_message.get("content"))
                    else:
                        last_role = getattr(last_message, "role", None)
                        last_content = _extract_text_content(getattr(last_message, "content", None))
                else:
                    last_role = None
                    last_content = None

                if last_role == "user" and last_content:
                    latest_user_turn = db.query(ConversationTurn).filter(
                        ConversationTurn.conversation_id == conversation_id,
                        ConversationTurn.user_id == user_id,
                        ConversationTurn.role == "user"
                    ).order_by(ConversationTurn.message_index.desc()).first()

                    should_store_user_turn = not (
                        latest_user_turn and latest_user_turn.content == last_content
                    )

                    if should_store_user_turn:
                        embedding = await embedding_service.generate_embedding(last_content)
                    
                        if DATABASE_URL.startswith("postgresql") and PGVECTOR_AVAILABLE:
                            embedding_data = embedding
                        else:
                            import json
                            embedding_data = json.dumps(embedding) if embedding else None
                        
                        turn = ConversationTurn(
                            conversation_id=conversation.id,
                            user_id=user_id,
                            role="user",
                            content=last_content,
                            message_index=current_turn_count,
                            embedding=embedding_data
                        )
                        db.add(turn)
                        current_turn_count += 1
                
                if response_content:
                    latest_assistant_turn = db.query(ConversationTurn).filter(
                        ConversationTurn.conversation_id == conversation_id,
                        ConversationTurn.user_id == user_id,
                        ConversationTurn.role == "assistant"
                    ).order_by(ConversationTurn.message_index.desc()).first()

                    should_store_assistant_turn = not (
                        latest_assistant_turn and latest_assistant_turn.content == response_content
                    )

                    if should_store_assistant_turn:
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
                conversation.total_messages = db.query(ConversationTurn).filter(
                    ConversationTurn.conversation_id == conversation_id
                ).count()
                conversation.updated_at = func.now()
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

            last_created_at = last_episode.created_at
            if last_created_at.tzinfo is None:
                last_created_at = last_created_at.replace(tzinfo=timezone.utc)
            time_gap = (datetime.now(timezone.utc) - last_created_at).total_seconds()
            has_gap = time_gap > 2700  # 45 minutes in seconds

            return has_gap, last_episode.created_at
        except Exception as e:
            logger.error(f"Error detecting session gap: {e}")
            return False, None

    async def summarize_session(self, user_id: str, start_time: datetime, end_time: datetime, db: Session = None) -> str | None:
        """Generate concise 2-3 sentence summary of conversation session.

        Runs off the chat hot path (fire-and-forget from chat_stream) so it
        needs its own DB session rather than borrowing the request-scoped one,
        which may already be closed by the time this actually runs.
        """
        _owns_db = db is None
        if _owns_db:
            db = SessionLocal()
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
            fast_model = os.getenv("FAST_MODEL", "Qwen3.5-35B-A3B")

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
        finally:
            if _owns_db:
                db.close()

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

            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
            conversation.updated_at = naive_local_now()
            db.commit()
            logger.info(f"Generated title for conversation {conversation_id}: {title}")

        except Exception as e:
            logger.error(f"Error generating conversation title: {e}")

# EmbeddingService imported from app.services.embedding_service

# ============================================================================
# GLM-4.5 XML Tool Call Parser
# ============================================================================

# parse_glm45_tool_calls and parse_json_text_tool_calls extracted to app.core.text_utils

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
            # pypdf is the maintained successor to PyPDF2 (same PdfReader API).
            # Fall back to PyPDF2 only if pypdf isn't present.
            try:
                from pypdf import PdfReader
            except ImportError:
                from PyPDF2 import PdfReader
            text = ""

            with open(file_path, 'rb') as file:
                reader = PdfReader(file)
                
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
            logger.error("No PDF library (pypdf/PyPDF2) available for PDF text extraction")
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


# Map common file extensions → MIME type for attachments that arrive with a
# generic/octet-stream media type (some pickers don't report it reliably).
_ATTACHMENT_EXT_MIME = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
}


def _materialize_document_attachments(messages) -> None:
    """Replace base64 'document' content blocks with extracted-text blocks, in place.

    Clients (iOS/web) can attach PDFs, Word docs, and text files to a chat turn as
    ``{"type": "document", "data": <base64>, "media_type": ..., "filename": ...}``.
    The local LLM can't read binary files, so we extract their text here and splice
    it into the message as plain text before the turn reaches intent routing or the
    model. Image blocks are left untouched so vision still works.
    """
    import base64 as _b64
    import tempfile

    for msg in messages or []:
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        if not any(isinstance(p, dict) and p.get("type") == "document" for p in content):
            continue

        new_content = []
        for part in content:
            if not (isinstance(part, dict) and part.get("type") == "document"):
                new_content.append(part)
                continue

            filename = part.get("filename") or part.get("name") or "attachment"
            media_type = part.get("media_type") or part.get("mime_type") or ""
            ext = os.path.splitext(filename)[1].lower()
            # Fall back to extension-based MIME when the client didn't give a usable one.
            if media_type not in document_processor.supported_types:
                media_type = _ATTACHMENT_EXT_MIME.get(ext, media_type or "application/octet-stream")

            extracted = ""
            try:
                raw = _b64.b64decode(part.get("data") or "")
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tf:
                    tf.write(raw)
                    tmp_path = tf.name
                try:
                    extracted = document_processor.extract_text(tmp_path, media_type) or ""
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
            except Exception as e:
                logger.warning(f"Failed to extract attached document '{filename}': {e}")

            extracted = extracted.strip()
            MAX_CHARS = 50000
            if len(extracted) > MAX_CHARS:
                extracted = extracted[:MAX_CHARS] + f"\n\n[... document truncated at {MAX_CHARS} characters ...]"

            if extracted:
                block_text = (
                    f"\n\n[Attached file: {filename}]\n{extracted}\n"
                    f"[End of attached file: {filename}]\n"
                )
            else:
                block_text = (
                    f"\n\n[Attached file: {filename} — no readable text could be "
                    f"extracted from this {media_type} file.]\n"
                )
            new_content.append({"type": "text", "text": block_text})

        msg.content = new_content


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
                        "max_tokens": 150,
                        # Local qwen: disable thinking or `content` comes back empty.
                        "chat_template_kwargs": {"enable_thinking": False},
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
        self.fast_model = os.getenv("FAST_MODEL", "Qwen3.5-35B-A3B")  # Your fast model
        
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

        from app.services import retrieval_observer
        import time as _time
        _funnel_start = _time.monotonic()
        _funnel_source = f"episodes.{window_config.window_type.name.lower()}"
        _funnel_err: str | None = None
        _funnel_results: list[dict] = []

        db = SessionLocal()
        try:
            # Start with base query
            query_builder = db.query(Episode).filter(Episode.user_id == user_id)
            
            # Apply window filters
            if window_config.window_type == WindowType.TEMPORAL:
                duration = window_config.parameters["duration"]
                cutoff_time = datetime.now(timezone.utc) - duration
                query_builder = query_builder.filter(Episode.created_at >= cutoff_time)
            
            elif window_config.window_type == WindowType.TOPIC:
                topics = window_config.parameters["topics"]
                # Filter by episodes that contain any of the topics
                topic_filter = or_(*[Episode.topics.like(f'%"{topic}"%') for topic in topics])
                query_builder = query_builder.filter(topic_filter)
                
                if "duration" in window_config.parameters:
                    duration = window_config.parameters["duration"]
                    cutoff_time = datetime.now(timezone.utc) - duration
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
                    cutoff_time = datetime.now(timezone.utc) - duration
                    query_builder = query_builder.filter(Episode.created_at >= cutoff_time)
            
            elif window_config.window_type == WindowType.IMPORTANCE:
                min_importance = window_config.parameters["min_importance"]
                query_builder = query_builder.filter(Episode.importance >= min_importance)
                
                if "duration" in window_config.parameters:
                    duration = window_config.parameters["duration"]
                    cutoff_time = datetime.now(timezone.utc) - duration
                    query_builder = query_builder.filter(Episode.created_at >= cutoff_time)
            
            elif window_config.window_type == WindowType.HYBRID:
                params = window_config.parameters

                if "duration" in params:
                    cutoff_time = datetime.now(timezone.utc) - params["duration"]
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

                # Determine time bounds — exact temporal window or duration-based cutoff
                temporal_start = params.get("temporal_start")
                temporal_end = params.get("temporal_end")
                if temporal_start and temporal_end:
                    cutoff_time = temporal_start
                    upper_time = temporal_end
                else:
                    if "duration" in params:
                        cutoff_time = datetime.now(timezone.utc) - params["duration"]
                    else:
                        cutoff_time = datetime.now(timezone.utc) - timedelta(days=30)  # Default 30 days
                    upper_time = None

                # Use raw SQL for vector similarity search
                from sqlalchemy import text as sql_text

                upper_clause = "AND e.created_at <= :upper_time" if upper_time else ""

                # Parameterized embedding via CAST(:qvec AS vector) — avoids SQL injection
                # from malformed embedding floats and matches project-wide pgvector pattern.
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
                        1 - (e.embedding <=> CAST(:qvec AS vector)) as semantic_similarity,
                        -- Composite score: semantic + recency + importance + frequency + relevance + rating + exploration
                        (
                            (1 - (e.embedding <=> CAST(:qvec AS vector))) * 0.35 +  -- Semantic similarity (35%)
                            EXP(-EXTRACT(EPOCH FROM (NOW() - e.created_at)) / (14 * 86400)) * 0.15 +  -- Recency 14-day half-life (15%)
                            COALESCE(e.importance, 0.5) * 0.20 +  -- AI-scored importance (20%)
                            LEAST(LN(COALESCE(e.access_count, 0) + 1) / 4.6, 1.0) * 0.08 +  -- Frequency signal (8%)
                            COALESCE(e.recall_relevance_ema, 0.5) * 0.07 +  -- Recall usefulness EMA (7%)
                            COALESCE(e.rating_boost, 0.0) * 0.10 +  -- Rating boost (Wilson + decay) (10%)
                            COALESCE(e.exploration_bonus, 0.0) * 0.05  -- Thompson Sampling exploration (5%)
                        ) as composite_score
                    FROM episode e
                    WHERE e.user_id = :user_id
                      AND e.embedding IS NOT NULL
                      AND e.created_at >= :cutoff_time
                      {upper_clause}
                      AND (1 - (e.embedding <=> CAST(:qvec AS vector))) >= :min_similarity
                    ORDER BY composite_score DESC
                    LIMIT :limit
                """)

                sql_params = {
                    "user_id": user_id,
                    "qvec": str(query_embedding),
                    "cutoff_time": cutoff_time,
                    "min_similarity": min_similarity,
                    "limit": limit,
                }
                if upper_time:
                    sql_params["upper_time"] = upper_time

                result = db.execute(sql, sql_params)

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
                        episode_obj.last_accessed = datetime.now(timezone.utc)

                db.commit()
                logger.info(f"[Memory] Vector search returned {len(episode_data)} episodes with semantic similarity")
                _funnel_results = episode_data
                return episode_data

            # Use composite score with temporal decay for non-semantic retrieval
            # This ensures temporal queries also properly weight recency
            from sqlalchemy import text as sql_text

            # Build WHERE clause from existing query filters
            # We need to use raw SQL for the decay formula
            time_filter = ""
            if window_config.window_type == WindowType.TEMPORAL:
                duration = window_config.parameters.get("duration", timedelta(days=7))
                cutoff_time = datetime.now(timezone.utc) - duration
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

            # Update access tracking for retrieved episodes.
            # H4 (Brain Alignment): retrieval strengthening / reconsolidation —
            # a memory that keeps getting used earns a small, capped bump to its
            # intrinsic (base) importance, which survives nightly rescoring. This
            # is the explicit form of what frequency_factor only did implicitly.
            if episode_ids:
                db.execute(sql_text("""
                    UPDATE episode
                    SET access_count = COALESCE(access_count, 0) + 1,
                        last_accessed = NOW(),
                        base_importance = LEAST(0.95, COALESCE(base_importance, importance, 0.3) + 0.01)
                    WHERE id = ANY(:ids)
                """), {"ids": episode_ids})
                db.commit()

            logger.info(f"[Memory] Non-semantic retrieval returned {len(episode_data)} episodes with decay scoring")
            _funnel_results = episode_data
            return episode_data

        except Exception as _exc:
            _funnel_err = type(_exc).__name__
            raise
        finally:
            db.close()
            retrieval_observer.record(
                _funnel_source,
                query or "",
                len(_funnel_results),
                (_time.monotonic() - _funnel_start) * 1000.0,
                error=_funnel_err,
                metadata={"user_id": user_id, "limit": limit},
            )

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
        memory_type: str = "conversation",
        episode_id: str = None
    ) -> Episode:
        """Store an episode with fast heuristic scoring.

        Uses MemoryScorer heuristics for instant importance/affect scoring
        (no LLM call). Rich analysis (emotions, topics, refined scores) is
        done in a single batched LLM call after the conversation ends via
        _enrich_episodes_batch().
        """
        from app.services.memory_scorer import memory_scorer

        # Fast heuristic scoring (no LLM call, <1ms)
        scores = memory_scorer.score_sync({"content": content, "role": role})
        base_score = scores["importance_score"]
        emotional_intensity = abs(scores["affect_score"])  # 0..1

        # Quick keyword topics as placeholder (overwritten by batch LLM later)
        topics = await self._extract_topics(content)

        # Heuristic emotional placeholder (overwritten by batch LLM later)
        emotional_analysis = {
            "primary_emotion": "neutral",
            "intensity": emotional_intensity,
            "sub_emotions": [],
            "energy_level": "medium",
            "sentiment": "positive" if scores["affect_score"] > 0.2 else ("negative" if scores["affect_score"] < -0.2 else "neutral"),
            "confidence": 0.2,  # low confidence = heuristic only
        }

        # Generate embedding (if available)
        embedding = await self._generate_embedding(content)

        # Store episode
        db = SessionLocal()
        try:
            # H4 (Brain Alignment): emotional encoding + novelty. The amygdala
            # tags intense moments and the cortex tags surprising ones for
            # stronger encoding. novelty = 1 − max cosine similarity to the last
            # 30 days; the fifth light-toggle is not novel, the first plumber
            # problem is. Blend both into importance so memory stops being flat.
            novelty = 0.5
            try:
                if embedding and isinstance(embedding, list) and PGVECTOR_AVAILABLE:
                    row = db.execute(text("""
                        SELECT MAX(1 - (embedding <=> CAST(:qvec AS vector))) AS max_sim
                        FROM episode
                        WHERE user_id = :uid AND embedding IS NOT NULL
                          AND created_at > NOW() - INTERVAL '30 days'
                    """), {"qvec": str(embedding), "uid": user_id}).fetchone()
                    if row and row.max_sim is not None:
                        novelty = max(0.0, min(1.0, 1.0 - float(row.max_sim)))
            except Exception as _e:
                logger.debug(f"novelty computation skipped: {_e}")

            # base carries most of the weight; emotion and novelty lift the
            # memorable exchanges above the undifferentiated floor.
            importance = max(0.0, min(1.0,
                base_score * 0.6 + emotional_intensity * 0.25 + novelty * 0.15))

            episode = Episode(
                **({"id": episode_id} if episode_id else {}),
                conversation_id=conversation_id,
                user_id=user_id,
                role=role,
                content=content,
                importance=importance,
                base_importance=importance,
                emotional_tone=json.dumps(emotional_analysis),
                topics=json.dumps(topics),
                context_tags=json.dumps([]),
                memory_type=memory_type,
                source=source,
                meta={"novelty": round(novelty, 4), "emotional_intensity": round(emotional_intensity, 4)},
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

        # Parse temporal references from query (e.g. "what happened Tuesday")
        temporal_range = None
        try:
            from app.services.temporal_query_parser import parse_temporal_reference
            temporal_range = parse_temporal_reference(query)
            if temporal_range:
                logger.info(f"🕐 Detected temporal reference: {temporal_range[0]} → {temporal_range[1]}")
        except Exception as e:
            logger.debug(f"Temporal parse failed: {e}")

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
                        # If temporal reference detected, search that specific window
                        # Otherwise tiered search: 30d → 90d → all-time
                        episodes = []
                        if temporal_range:
                            t_start, t_end = temporal_range
                            span = t_end - t_start + timedelta(days=1)
                            window_config = ContextWindowConfig.semantic(
                                query_embedding=query_embedding,
                                duration=span,
                                min_similarity=0.15,  # Lower threshold for temporal queries
                            )
                            # Override cutoff to the exact temporal window
                            window_config.parameters["temporal_start"] = t_start
                            window_config.parameters["temporal_end"] = t_end
                            episodes = await self.window_manager.retrieve_episodes_with_window(
                                user_id, window_config, query, limit=20
                            )
                            logger.info(f"🕐 Temporal search ({t_start.date()} → {t_end.date()}) returned {len(episodes)} episodes")

                        if not episodes:
                            for search_days in [30, 90, None]:
                                duration = timedelta(days=search_days) if search_days else timedelta(days=365 * 5)
                                window_config = ContextWindowConfig.semantic(
                                    query_embedding=query_embedding,
                                    duration=duration,
                                    min_similarity=0.25  # Lower threshold for broader recall
                                )
                                episodes = await self.window_manager.retrieve_episodes_with_window(
                                    user_id, window_config, query, limit=20  # Fetch 20 for reranking
                                )
                                if len(episodes) >= 5:
                                    break
                                elif episodes:
                                    logger.info(f"🔍 Only {len(episodes)} results in {search_days or 'all-time'}d, expanding search")

                        if episodes:
                            logger.info(f"🧠 Semantic search found {len(episodes)} episodes")

                            # Rerank with BGE reranker for better precision
                            try:
                                from app.services.bge_reranker import get_reranker
                                reranker = await get_reranker()
                                docs = [ep.get("content", "")[:500] for ep in episodes]
                                ranked = await reranker.rerank(query, docs, top_k=min(7, len(episodes)))
                                reranked_episodes = [episodes[idx] for idx, _score in ranked]
                                logger.info(f"🔄 Reranked {len(episodes)} → top {len(reranked_episodes)}")
                                return reranked_episodes
                            except Exception as rerank_err:
                                logger.debug(f"Reranker unavailable, using composite scores: {rerank_err}")

                            for i, ep in enumerate(episodes[:3]):
                                if 'semantic_similarity' in ep:
                                    logger.info(f"  {i+1}. Similarity: {ep['semantic_similarity']:.4f}, Score: {ep.get('composite_score', 0):.4f}")
                            return episodes[:7]
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
        self.fast_model = BG_LLM_FALLBACK_MODEL or "Qwen3.5-35B-A3B"
        self.smart_model = BG_LLM_PRIMARY_MODEL or OPENAI_MODEL or "Qwen3.5-35B-A3B"
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
        """Call the fast LLM for quick analysis (uses background LLM client)"""
        try:
            from app.core.llm import get_background_llm_client
            bg_client = get_background_llm_client()
            response = await bg_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.7
            )
            if response and "choices" in response and response["choices"]:
                return response["choices"][0]["message"]["content"].strip()
            return None
        except Exception as e:
            logger.error(f"Fast LLM call failed: {e}")
            return None

    async def _call_smart_llm(self, prompt: str, max_tokens: int = 300) -> Optional[str]:
        """Call the smart LLM for deep analysis (uses background LLM client)"""
        try:
            from app.core.llm import get_background_llm_client
            bg_client = get_background_llm_client()
            response = await bg_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.7
            )
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
                self._due_notifications = []
                await asyncio.to_thread(self._check_and_schedule_notifications_sync)
                # Send due notifications on the event loop (async)
                for key, notification in self._due_notifications:
                    try:
                        await self._send_scheduled_notification(notification)
                    except Exception:
                        pass
                    self.scheduled_notifications.pop(key, None)
                await asyncio.sleep(5)  # Check every 5 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Notification scheduler error: {e}")
                await asyncio.sleep(10)  # Wait longer on error
                
    def _check_and_schedule_notifications_sync(self):
        """Check for due timers/reminders and schedule notifications (sync, runs in thread)."""
        try:
            db = SessionLocal()
            try:
                now = datetime.now(timezone.utc)
                pre_generate_time = now + timedelta(seconds=20)

                # Check timers that need pre-generation
                upcoming_timers = db.query(Timer).filter(
                    Timer.is_active == True
                ).all()

                for timer in upcoming_timers:
                    timer_end_time = timer.end_time
                    if timer_end_time.tzinfo is None:
                        timer_end_time = timer_end_time.replace(tzinfo=timezone.utc)
                    if timer_end_time <= pre_generate_time and timer_end_time > now:
                        notification_key = f"timer_{timer.id}"
                        if notification_key not in self.scheduled_notifications:
                            self.scheduled_notifications[notification_key] = {
                                "title": f"Timer: {timer.title or 'Timer'}",
                                "message": f"Your {timer.duration_minutes}min timer is done!",
                                "send_time": timer.end_time,
                                "type": "timer",
                                "timer_id": timer.id,
                                "timer_name": timer.title,
                                "user_id": timer.user_id
                            }

                # Check reminders
                all_reminders = db.query(Reminder).filter(
                    Reminder.is_completed == False
                ).all()

                for reminder in all_reminders:
                    reminder_time = reminder.reminder_time
                    if reminder_time.tzinfo is None:
                        reminder_time = reminder_time.replace(tzinfo=timezone.utc)
                    if reminder_time <= pre_generate_time and reminder_time > now:
                        notification_key = f"reminder_{reminder.id}"
                        if notification_key not in self.scheduled_notifications:
                            self.scheduled_notifications[notification_key] = {
                                "title": f"Reminder: {reminder.title or 'Reminder'}",
                                "message": reminder.description or reminder.content or "Time for your reminder",
                                "send_time": reminder.reminder_time,
                                "type": "reminder",
                                "reminder_id": reminder.id,
                                "user_id": reminder.user_id
                            }

                # Collect due notifications
                self._due_notifications = []
                for key, notification in list(self.scheduled_notifications.items()):
                    send_time = notification["send_time"]
                    if send_time.tzinfo is None:
                        send_time = send_time.replace(tzinfo=timezone.utc)
                    if send_time <= now:
                        self._due_notifications.append((key, notification))
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

# Sentry error tracking (no-op if DSN not configured)
try:
    from app.core.config import settings as _sentry_settings
    if _sentry_settings.sentry_dsn:
        import sentry_sdk
        sentry_sdk.init(
            dsn=_sentry_settings.sentry_dsn,
            environment=_sentry_settings.sentry_environment,
            traces_sample_rate=_sentry_settings.sentry_traces_sample_rate,
            send_default_pii=False,
        )
        logger.info(f"Sentry initialized (env={_sentry_settings.sentry_environment})")
except Exception as _sentry_err:
    logger.debug(f"Sentry init skipped: {_sentry_err}")

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

# Request logging middleware — adds correlation IDs + performance metrics to every request
app.add_middleware(RequestLoggingMiddleware)

# Include modular routes

# Auth routes (extracted from main_simple.py)
try:
    from app.routes.auth import router as auth_router
    app.include_router(auth_router, tags=["Authentication"])
    logger.info("✅ Auth routes loaded from app.routes.auth")
except Exception as e:
    logger.warning(f"Auth routes not available from module: {e}")

# Unified assistant inbox (needs-you / FYI merge + shared badge formula)
try:
    from app.routes.assistant_inbox import router as assistant_inbox_router
    app.include_router(assistant_inbox_router)
    logger.info("✅ Assistant inbox routes loaded from app.routes.assistant_inbox")
except Exception as e:
    logger.warning(f"Assistant inbox routes not available from module: {e}")

# Soul-change proposals (Brain Alignment H7.2 — one-tap approve/reject)
try:
    from app.routes.soul_proposals import router as soul_proposals_router
    app.include_router(soul_proposals_router, tags=["Soul"])
    logger.info("✅ Soul proposal routes loaded from app.routes.soul_proposals")
except Exception as e:
    logger.warning(f"Soul proposal routes not available from module: {e}")

# Overlay data endpoints (standalone /overlay/:kind webapp routes)
try:
    from app.routes.overlay import router as overlay_router
    app.include_router(overlay_router)
    logger.info("✅ Overlay routes loaded from app.routes.overlay")
except Exception as e:
    logger.warning(f"Overlay routes not available from module: {e}")

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

# item 2.2 (2026-07-30): the legacy top-level /recipes router (routes/recipes.py)
# had zero live callers — web (RecipesSection), iOS (recipesService), and the
# chat tool layer (app/tools/recipes.py, direct ORM) all exclusively use
# /api/fitness/recipes or the Recipe model directly. Deleted the dead route
# module + its schemas/recipes.py (which nothing else imported).

# Reminders routes (extracted from main_simple.py)
try:
    from app.routes.reminders import router as reminders_router
    app.include_router(reminders_router, tags=["Reminders"])
    logger.info("✅ Reminders routes loaded from app.routes.reminders")
except Exception as e:
    logger.warning(f"Reminders routes not available from module: {e}")

# Daily tasks routes
try:
    from app.routes.daily_tasks import router as daily_tasks_router
    app.include_router(daily_tasks_router, tags=["Daily Tasks"])
    logger.info("✅ Daily tasks routes loaded from app.routes.daily_tasks")
except Exception as e:
    logger.warning(f"Daily tasks routes not available: {e}")

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

try:
    from app.routes.memory import router as memory_router
    app.include_router(memory_router)
except Exception as e:
    logger.warning(f"Memory routes not available: {e}")

# Include Jarvis mode routes
try:
    from app.routes.threads import router as threads_router
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

# Include versioned cross-device workout routes (Apple Watch + iPhone).
# Separate module from fitness.py so the Watch contract stays reviewable on its
# own; it shares the same auth dependency and command service.
try:
    from app.routes.workout_v2 import router as workout_v2_router
    app.include_router(
        workout_v2_router, prefix="/api/fitness/workout-session/v2", tags=["Workout v2"]
    )
    logger.info("✅ Workout v2 routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Workout v2 routes failed to load: {e}")

# Include Cardio routes (cardio tracker + Tabata interval timer)
try:
    from app.routes.cardio import router as cardio_router
    app.include_router(cardio_router, prefix="/api/fitness/cardio", tags=["Cardio"])
    logger.info("✅ Cardio routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Cardio routes failed to load: {e}")

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

# Include Cognitive routes (audio processing, speaker recognition, Sara identity)
try:
    from app.routes.cognitive import router as cognitive_router
    app.include_router(cognitive_router, tags=["Cognitive"])
    logger.info("✅ Cognitive routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Cognitive routes failed to load: {e}")

# Include Sensory Monitor routes (real-time audio/visual monitoring)
try:
    from app.routes.sensory import router as sensory_router
    app.include_router(sensory_router, tags=["Sensory"])
    logger.info("✅ Sensory monitor routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Sensory monitor routes failed to load: {e}")

# Include Voice Control Plane routes (modular voice stack orchestration)
try:
    from app.routes.voice_control import router as voice_control_router
    app.include_router(voice_control_router, tags=["Voice Control"])
    logger.info("✅ Voice control routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Voice control routes failed to load: {e}")

# Include ML Control Plane routes (tabular model training/serving orchestration)
try:
    from app.routes.ml_control import router as ml_control_router
    app.include_router(ml_control_router, tags=["ML Control"])
    logger.info("✅ ML control routes loaded successfully")
except Exception as e:
    logger.error(f"❌ ML control routes failed to load: {e}")

# Include "Sara's model of you" routes (patterns/rhythm/predictions visibility + feedback)
try:
    from app.routes.model_of_you import router as model_of_you_router
    app.include_router(model_of_you_router, tags=["Model of You"])
    logger.info("✅ Model-of-you routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Model-of-you routes failed to load: {e}")

# Include Intelligence Reports routes (Phase 3)
try:
    from app.routes.intelligence_reports import router as reports_router
    app.include_router(reports_router, tags=["Intelligence Reports"])
    logger.info("✅ Intelligence reports routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Intelligence reports routes failed to load: {e}")

# Include Weekly Health Reports routes
try:
    from app.routes.health_reports import router as health_reports_router
    app.include_router(health_reports_router, tags=["Health Reports"])
    logger.info("✅ Health weekly reports routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Health weekly reports routes failed to load: {e}")

# Cognitive router is included once above; avoid duplicate registration.

# Include Morning Brief routes
try:
    from app.routes.morning_brief import router as morning_brief_router
    app.include_router(morning_brief_router, prefix="/api/morning-brief", tags=["Morning Brief"])
    logger.info("✅ Morning brief routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Morning brief routes failed to load: {e}")

# Include Research Brief routes
try:
    from app.routes.research_brief import router as research_brief_router
    app.include_router(research_brief_router, prefix="/api/research-brief", tags=["Research Brief"])
    logger.info("✅ Research brief routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Research brief routes failed to load: {e}")

# Include Settings → Schedules routes (DB-backed Celery beat schedule)
try:
    from app.routes.schedules import router as schedules_router
    app.include_router(schedules_router)
    logger.info("✅ Settings/schedules routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Settings/schedules routes failed to load: {e}")

# Include Settings → Tunables routes (cooldowns, ACS thresholds, brief tone)
try:
    from app.routes.tunables import router as tunables_router
    app.include_router(tunables_router)
    logger.info("✅ Settings/tunables routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Settings/tunables routes failed to load: {e}")

# Include Project Tracker routes
try:
    from app.routes.projects import router as projects_router
    app.include_router(projects_router, prefix="/api/projects", tags=["Project Tracker"])
    logger.info("✅ Project tracker routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Project tracker routes failed to load: {e}")

try:
    from app.routes.hosts import router as hosts_router
    app.include_router(hosts_router, prefix="/api", tags=["Managed Hosts"])
    logger.info("✅ Managed hosts routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Managed hosts routes failed to load: {e}")

try:
    from app.routes.interest_model import router as interest_model_router
    app.include_router(interest_model_router, prefix="/api", tags=["Interest Model"])
    logger.info("✅ Interest model routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Interest model routes failed to load: {e}")

try:
    from app.routes.fleet import router as fleet_router
    app.include_router(fleet_router, prefix="/api/fleet", tags=["Fleet"])
    logger.info("✅ Fleet routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Fleet routes failed to load: {e}")

try:
    from app.routes.diagnostics import router as diagnostics_router
    app.include_router(diagnostics_router)
    logger.info("✅ Diagnostics routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Diagnostics routes failed to load: {e}")

try:
    from app.routes.moment_cards import router as moment_cards_router
    app.include_router(moment_cards_router)
    logger.info("✅ Moment cards routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Moment cards routes failed to load: {e}")

try:
    from app.routes.browse_shots import router as browse_shots_router
    app.include_router(browse_shots_router, prefix="/api", tags=["Browse Screenshots"])
    logger.info("✅ Browse screenshot routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Browse screenshot routes failed to load: {e}")

# Include Artifacts routes
try:
    from app.routes.artifacts import router as artifacts_router
    app.include_router(artifacts_router, prefix="/api/artifacts", tags=["Artifacts"])
    logger.info("✅ Artifacts routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Artifacts routes failed to load: {e}")

# Include Surfaces routes (ephemeral interactive UI)
try:
    from app.routes.surfaces import router as surfaces_router
    app.include_router(surfaces_router, prefix="/api/surfaces", tags=["Surfaces"])
    logger.info("✅ Surfaces routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Surfaces routes failed to load: {e}")

# Include Workspace Job routes (job status + collected-file downloads)
try:
    from app.routes.workspace_jobs import router as workspace_jobs_router
    app.include_router(workspace_jobs_router, tags=["Workspace Jobs"])
    logger.info("✅ Workspace Job routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Workspace Job routes failed to load: {e}")

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

# Include Workspace State routes (canvas state persistence)
try:
    from app.routes.workspace import router as workspace_router
    app.include_router(workspace_router, tags=["Workspace"])
    logger.info("✅ Workspace State routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Workspace State routes failed to load: {e}")

# Include Maps routes (mindmaps/flowcharts)
try:
    from app.routes.maps import router as maps_router
    app.include_router(maps_router, tags=["Maps"])
    logger.info("✅ Maps routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Maps routes failed to load: {e}")

# Include Research routes (web search with AI summary)
try:
    from app.routes.research import router as research_router
    app.include_router(research_router, tags=["Research"])
    logger.info("✅ Research routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Research routes failed to load: {e}")

# Include Research Plans routes (delegated research executor system)
try:
    from app.routes.research_plans import router as research_plans_router
    app.include_router(research_plans_router, tags=["Research Plans"])
    logger.info("✅ Research Plans routes loaded successfully")
except Exception as e:
    logger.error(f"❌ Research Plans routes failed to load: {e}")

# Phase 5: Extracted route modules (batch A — core, downloads, presence)
from app.routes.core import router as core_router
from app.routes.downloads import router as downloads_router
from app.routes.presence import router as presence_router, log_presence
from app.routes.location import router as location_router
from app.routes.rhythm import router as rhythm_router

app.include_router(core_router)
app.include_router(downloads_router)
app.include_router(presence_router)
app.include_router(location_router)
app.include_router(rhythm_router)

# Phase 5: Extracted route modules (batch C — daily brief)
from app.routes.daily_brief import router as daily_brief_router

app.include_router(daily_brief_router)

# Phase 3: Extracted route modules
from app.routes.briefings import router as briefings_router
from app.routes.push_tokens import router as push_tokens_router, send_push_to_user
from app.routes.conversations import router as conversations_router
from app.routes.documents import router as documents_router
from app.routes.episodes import router as episodes_router

app.include_router(briefings_router)
app.include_router(push_tokens_router)
app.include_router(conversations_router)
app.include_router(documents_router)
app.include_router(episodes_router)

# Phase 3: Extracted route modules (batch 2)
from app.routes.knowledge_graph import router as knowledge_graph_router
from app.routes.autonomous import router as autonomous_router
from app.routes.reflection import router as reflection_router
from app.routes.fitness_inline import router as fitness_inline_router

app.include_router(knowledge_graph_router)
app.include_router(autonomous_router)
app.include_router(reflection_router)
app.include_router(fitness_inline_router)

# Sara autonomy + PKG routes
from app.routes.sara_status import router as sara_status_router
from app.routes.sara_observations import router as sara_observations_router
from app.routes.sara_activity import router as sara_activity_router
from app.routes.personal_knowledge import router as personal_knowledge_router

app.include_router(sara_status_router)
app.include_router(sara_observations_router)
app.include_router(sara_activity_router)
app.include_router(personal_knowledge_router)

# Automation routes
from app.routes.automation import router as automation_router
from app.routes.automation_admin import router as automation_admin_router
app.include_router(automation_router)
app.include_router(automation_admin_router)

# Standing orders route
from app.routes.standing_orders import router as standing_orders_router
app.include_router(standing_orders_router)

# Autonomy control (quiet mode etc.)
from app.routes.autonomy_control import router as autonomy_control_router
app.include_router(autonomy_control_router)

# The Mind — global workspace (§3.1) + self-model (§3.4)
from app.routes.mind import router as mind_router
app.include_router(mind_router)

# Autonomy traces (Phase 0 — Cortana Evolution)
from app.routes.autonomy_traces import router as autonomy_traces_router
app.include_router(autonomy_traces_router)

# Autonomy simulation (Phase 1 — Cortana Evolution)
from app.routes.autonomy_simulation import router as autonomy_simulation_router
app.include_router(autonomy_simulation_router)

# Autonomy attention queue (Phase 2 — Cortana Evolution)
from app.routes.autonomy_attention import router as autonomy_attention_router
app.include_router(autonomy_attention_router)

# Autonomy missions (Phase 2 — Cortana Evolution)
from app.routes.autonomy_missions import router as autonomy_missions_router
app.include_router(autonomy_missions_router)

# Autonomy policy candidates (Phase 3 — Cortana Evolution)
from app.routes.autonomy_policy_candidates import router as autonomy_policy_candidates_router
app.include_router(autonomy_policy_candidates_router)

# Email routes
from app.routes.email import router as email_router
app.include_router(email_router, prefix="/api")

# Content Inbox routes
from app.routes.content_inbox import router as content_inbox_router
app.include_router(content_inbox_router)

# Progress Photos routes (fitness physique tracking + inline VLM critique)
from app.routes.progress_photos import router as progress_photos_router
app.include_router(progress_photos_router)

# Agent Orchestration routes (VM agent dispatch + candidate skills)
from app.routes.agent_orchestration import router as agent_orch_router
app.include_router(agent_orch_router)

# Intelligence monitor routes (Phase 4A — proactive tech intelligence)
from app.routes.intelligence import router as intelligence_router
app.include_router(intelligence_router)

# Task events SSE — smart delivery of background worker results
from app.routes.task_events import router as task_events_router
app.include_router(task_events_router)

# Desktop app update server (no auth — electron-updater needs pre-login access)
from app.routes.desktop_updates import router as desktop_updates_router
app.include_router(desktop_updates_router)

# Session/cross-device routes
from app.routes.session import router as session_router
app.include_router(session_router)

# Debug/observability routes
from app.routes.debug_notifications import router as debug_notifications_router
app.include_router(debug_notifications_router)
from app.routes.debug_retrieval import router as debug_retrieval_router
app.include_router(debug_retrieval_router)

# Autonomous Cognition System (ACS) — v2 in-VM daemon
from app.routes.acs_daemon import router as acs_daemon_router
app.include_router(acs_daemon_router)
from app.routes.acs_daemon_tools import router as acs_daemon_tools_router
app.include_router(acs_daemon_tools_router)
from app.routes.acs_interests import router as acs_interests_router
app.include_router(acs_interests_router)
from app.routes.acs_user_tools import router as acs_user_tools_router
app.include_router(acs_user_tools_router)

# System metrics
from app.routes.metrics import router as metrics_router
app.include_router(metrics_router)

# Assistant UX analytics
from app.routes.assistant_analytics import router as assistant_analytics_router
app.include_router(assistant_analytics_router)

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
                    "max_tokens": max_tokens,
                    # Local qwen: disable thinking or `content` comes back empty.
                    "chat_template_kwargs": {"enable_thinking": False},
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

# Context Mode routes

# Smart Insights routes

logger.info("✅ Phase 4 intelligence routes loaded successfully")

# ===================== SHADOW MODE STUB (removed feature) =====================
@app.get("/shadow/active")
async def get_shadow_active():
    """Stub — shadow mode was removed. Returns null to silence stale polling."""
    return {"active_session": None}


# ===================== SUBCONSCIOUS ROUTES =====================
# Extracted to routes/subconscious.py (Stage 3). SSE max-lifetime + tz fix
# ride along with the move — see the module comment for details.
from app.routes.subconscious import router as subconscious_router
app.include_router(subconscious_router, tags=["Subconscious"])
logger.info("✅ Subconscious routes loaded successfully")


# ===================== THE SYSTEM (awareness / god-view) =====================
# routes/system_awareness.py — read-only god-view (Phase 0) + world model (Phase 1).
from app.routes.system_awareness import router as system_awareness_router
app.include_router(system_awareness_router, prefix="/api/system", tags=["System"])
logger.info("✅ System awareness routes loaded successfully")



# ===================== PI DASHBOARD ROUTES =====================
# Extracted to routes/pi_dashboard.py (Stage 3). The module registers all
# the non-voice Pi endpoints. The voice endpoints below still live here
# because they pull on the LLM client — they'll move with the chat
# extraction.

# Re-export for legacy callers still importing it from this module.
from app.core.device_auth import get_device_user  # noqa: E402, F401

from app.routes.pi_dashboard import router as pi_dashboard_router
app.include_router(pi_dashboard_router, tags=["Pi Dashboard"])
logger.info("✅ Pi Dashboard routes loaded successfully")


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


# Canvas mode triggers - voice commands that open workspace
CANVAS_TRIGGERS = [
    "let's get to work",
    "lets get to work",
    "open the canvas",
    "open canvas",
    "open workspace",
    "open my workspace",
    "start working",
    "work mode",
    "time to work",
]


_relationship_phase_cache: dict = {"phase": None, "duration": None, "ts": 0.0}


def _get_relationship_phase_cached():
    """H7.3: read relationship phase (10-min cache) for personality modulation."""
    import time as _t
    now = _t.time()
    if _relationship_phase_cache["phase"] is not None and now - _relationship_phase_cache["ts"] < 600:
        return _relationship_phase_cache["phase"], _relationship_phase_cache["duration"]
    try:
        from app.models.cognitive import RelationshipState
        db = SessionLocal()
        try:
            state = db.query(RelationshipState).first()
            if state:
                phase = state.phase
                duration = None
                if state.first_interaction:
                    days = (datetime.now(timezone.utc) - state.first_interaction.replace(tzinfo=timezone.utc)).days
                    duration = f"{days // 30} months" if days >= 45 else f"{days} days"
                _relationship_phase_cache.update({"phase": phase, "duration": duration, "ts": now})
                return phase, duration
        finally:
            db.close()
    except Exception as e:
        logger.debug(f"relationship phase read failed: {e}")
    _relationship_phase_cache["ts"] = now
    return None, None


def _build_activity_context(
    activity_state: str,
    confidence: float = 0.5,
    room: str = None,
    interruptibility: float = 0.5,
    # Conversation signals
    turn_count: int = 1,
    conversation_depth: int = 0,
    # Memory nudges
    memory_nudges: list = None,
    # Behavioral calibration (pre-loaded from working memory)
    calibration_data: dict = None,
    # Sara's emotional state (from working memory)
    sara_emotional_tone: str = None,
    sara_emotional_intensity: float = None,
) -> str:
    """Build adaptive personality context for system prompt injection.

    Combines activity state, Sara's emotional state, interruptibility,
    conversation depth, and behavioral calibration into a coherent
    personality directive via the PersonalityEngine.
    """
    try:
        from app.services.personality_engine import build_personality_context

        # H7.3 (Brain Alignment): let relationship phase modulate familiarity.
        rel_phase, rel_duration = _get_relationship_phase_cached()

        ctx = build_personality_context(
            activity_state=activity_state,
            activity_confidence=confidence,
            room=room,
            interruptibility=interruptibility,
            turn_count=turn_count,
            conversation_depth=conversation_depth,
            memory_nudges=memory_nudges,
            calibration_data=calibration_data,
            sara_emotional_tone=sara_emotional_tone,
            sara_emotional_intensity=sara_emotional_intensity,
            relationship_phase=rel_phase,
            relationship_duration=rel_duration,
        )
        return ctx.render()
    except Exception as e:
        logger.warning(f"Personality engine failed, falling back to basic tone: {e}")
        tone_map = {
            "sleeping": "Be extremely brief.",
            "waking": "Gentle, warm, brief.",
            "focused_work": "Concise and direct.",
            "in_meeting": "Ultra-brief only.",
        }
        tone = tone_map.get(activity_state, "Normal conversational tone.")
        return f"[Activity: {activity_state}]\nTone: {tone}"


def _summarize_tool_results(tool_responses: list) -> str:
    """Convert raw tool responses into a human-readable fallback message.

    Used when the follow-up LLM call fails and we need to tell the user
    what happened without dumping JSON.
    """
    actions = []
    for tr in tool_responses:
        content = tr.get("content")
        if not content:
            continue
        # Parse JSON tool results into readable text
        if isinstance(content, str):
            try:
                data = json.loads(content)
            except (json.JSONDecodeError, ValueError):
                data = {"message": content}
        elif isinstance(content, dict):
            data = content
        else:
            continue

        msg = data.get("message", "")
        success = data.get("success", True)
        if msg:
            actions.append(msg)
        elif not success:
            actions.append("One action didn't go through — I'll try again.")

    if not actions:
        return "Done!"
    if len(actions) == 1:
        return actions[0]
    return "Done! " + " ".join(actions)


def _is_canvas_trigger(message: str) -> bool:
    """Check if message is a workspace/canvas trigger."""
    msg_lower = message.lower().strip()
    return any(trigger in msg_lower for trigger in CANVAS_TRIGGERS)

def _get_canvas_mode(user_id: str) -> bool:
    """Check if user is in canvas mode (Redis with 1hr TTL)."""
    try:
        from redis import Redis
        redis_client = Redis.from_url(config.settings.redis_url, decode_responses=True)
        return redis_client.get(f"canvas_mode:{user_id}") == "1"
    except Exception:
        return False

def _set_canvas_mode(user_id: str, enabled: bool = True):
    """Set canvas mode with 1 hour TTL."""
    try:
        from redis import Redis
        redis_client = Redis.from_url(config.settings.redis_url, decode_responses=True)
        if enabled:
            redis_client.setex(f"canvas_mode:{user_id}", 3600, "1")
        else:
            redis_client.delete(f"canvas_mode:{user_id}")
    except Exception as e:
        logger.warning(f"[Voice] Failed to set canvas mode: {e}")


# P3 follow-up: the inbox digest is injected on the button-press turn, but David
# decides what to do with each item on his NEXT reply — by then the system prompt
# is rebuilt without the digest and the item ids are gone. Persist a short-lived
# "inbox review" flag per conversation so the digest (with live ids) and the
# clear_inbox_items tool stay available across the review, and drop it once the
# badge is clear.
def _set_inbox_review(conversation_key: str, enabled: bool = True):
    try:
        from redis import Redis
        redis_client = Redis.from_url(config.settings.redis_url, decode_responses=True)
        if enabled:
            redis_client.setex(f"inbox_review:{conversation_key}", 900, "1")  # 15 min
        else:
            redis_client.delete(f"inbox_review:{conversation_key}")
    except Exception as e:
        logger.debug(f"inbox_review set failed: {e}")

def _in_inbox_review(conversation_key: str) -> bool:
    try:
        from redis import Redis
        redis_client = Redis.from_url(config.settings.redis_url, decode_responses=True)
        return redis_client.get(f"inbox_review:{conversation_key}") == "1"
    except Exception:
        return False


@app.get("/api/workspace/pending-commands")
async def get_pending_workspace_commands(current_user: User = Depends(get_current_user)):
    """
    Get pending workspace commands from voice/non-SSE sources.
    Canvas should poll this endpoint to receive workspace commands from voice interactions.
    Commands are removed after being fetched.
    """
    try:
        from redis import Redis
        redis = Redis.from_url(config.settings.redis_url, decode_responses=True)

        commands = []
        user_id = str(current_user.id)
        key = f"workspace_commands:{user_id}"

        # Get all pending commands and clear the list
        while True:
            cmd = redis.rpop(key)
            if cmd is None:
                break
            try:
                commands.append(json.loads(cmd))
            except json.JSONDecodeError:
                pass

        return {"commands": commands, "count": len(commands)}
    except Exception as e:
        logger.warning(f"Failed to get pending workspace commands: {e}")
        return {"commands": [], "count": 0}


@app.post("/api/pi-dashboard/voice/chat")
async def pi_dashboard_voice_chat(request: Request, db: Session = Depends(get_db)):
    """
    Streaming chat for Pi dashboard with device token auth.
    Returns SSE stream with Sara's response.

    Features:
    - Cross-device conversation context (joins active conversation if < 1hr old)
    - Canvas mode detection and workspace triggers
    - Shared conversation history with webapp/iOS
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

        logger.info(f"[Voice] Chat from user {user_id}: {message[:50]}...")

        # Get user object for chat
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # === CROSS-DEVICE CONTEXT: Join active conversation if recent (< 1 hour) ===
        if not conversation_id:
            user_profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()

            if user_profile and user_profile.profile_data:
                active_id = user_profile.profile_data.get('active_conversation_id')

                if active_id:
                    # Check if conversation was active in last hour
                    last_episode = db.query(Episode).filter(
                        Episode.conversation_id == active_id,
                        Episode.user_id == user_id
                    ).order_by(Episode.created_at.desc()).first()

                    if last_episode and last_episode.created_at > datetime.now(timezone.utc) - timedelta(hours=1):
                        conversation_id = active_id
                        logger.info(f"[Voice] Joining active conversation: {conversation_id}")

            if not conversation_id:
                conversation_id = f"voice-{uuid.uuid4()}"
                logger.info(f"[Voice] Starting fresh conversation: {conversation_id}")

        # Stream the response
        async def generate_stream():
            full_response = ""
            try:
                # UI COMMAND INTERCEPTION (voice has no SSE overlay host, so a
                # matched command is pushed straight to the active desktop
                # instead of relying on a client-side ui_command handler).
                try:
                    from app.services import ui_intent
                    _ui = ui_intent.parse_ui_intent(message, allow_screens=False)
                    if _ui:
                        _ui_res = ui_intent.resolve_ui_intent(db, user_id, _ui)
                        logger.info(f"[Voice] UI command: {_ui.get('overlay')} (query={_ui.get('query')})")
                        _ui_ack = _ui_res["ack"]
                        if _ui_res.get("command"):
                            _pushed = await ui_intent.push_overlay_to_desktop(db, user_id, _ui_res["command"])
                            if _pushed:
                                _ui_ack = f"{_ui_ack} On your PC."
                        yield f"data: {json.dumps({'type': 'text_chunk', 'content': _ui_ack})}\n\n"
                        yield f"data: {json.dumps({'type': 'final_response', 'content': _ui_ack, 'conversation_id': conversation_id})}\n\n"
                        yield f"data: {json.dumps({'type': 'done'})}\n\n"
                        return
                except Exception as _ui_e:
                    logger.error(f"[Voice] UI command interception error: {_ui_e}", exc_info=True)

                # Create system prompt with user-local current time
                user_now = _resolve_prompt_datetime_for_user(db, user.id)
                soul_content = load_soul_for_prompt(db)
                system_prompt = get_system_prompt(ASSISTANT_NAME, user.email, user_now=user_now, soul_content=soul_content)

                # === CANVAS MODE: Check if active and enhance system prompt ===
                is_canvas_mode = _get_canvas_mode(user_id)
                is_canvas_trigger_msg = _is_canvas_trigger(message)

                if is_canvas_trigger_msg:
                    # User wants to open workspace - enable canvas mode
                    _set_canvas_mode(user_id, True)
                    is_canvas_mode = True
                    logger.info(f"[Voice] Canvas mode triggered by: {message}")

                    # Directly open workspace on Windows PC (don't rely on LLM to call tool)
                    try:
                        from app.services.command_router import command_router
                        workspace_opened = await command_router.open_workspace(db, user_id)
                        if workspace_opened:
                            logger.info(f"[Voice] Workspace opened successfully for user {user_id}")
                        else:
                            logger.warning(f"[Voice] Failed to open workspace - no active device?")
                    except Exception as e:
                        logger.error(f"[Voice] Error opening workspace: {e}")

                if is_canvas_mode:
                    system_prompt += """

## Canvas/Workspace Mode Active
You are now in workspace mode. The user is working on their Windows PC with the workspace canvas open (or about to open it). You can:
- Use device_open_workspace to open the canvas if they ask
- Open/update canvas artifacts (code, diagrams, mindmaps)
- Help with coding tasks with live preview
- Create and organize notes
- Be concise and action-oriented - prefer showing over telling.
"""

                # Intent classification for lazy context (with conversation context)
                tool_classifier = get_tool_intent_classifier()
                context_router = get_context_router()
                # Use conversation-aware classification
                user_intent, tool_categories = tool_classifier.classify_with_context(message, conversation_id)
                context_decision = context_router.decide(intent=user_intent, message=message, turn_count=1)
                logger.info(f"[Voice] Intent={user_intent}, tools={tool_categories}, canvas={is_canvas_mode}")

                # === CANVAS TRIGGER: Force device tools if workspace trigger ===
                if is_canvas_trigger_msg and "devices" not in (tool_categories or []):
                    tool_categories = (tool_categories or []) + ["devices"]
                    logger.info(f"[Voice] Added device tools for canvas trigger")

                # === CANVAS MODE: Always include workspace tools when in canvas mode ===
                if is_canvas_mode:
                    tool_categories = tool_categories or []
                    if "workspace" not in tool_categories:
                        tool_categories = tool_categories + ["workspace"]
                    if "maps" not in tool_categories:
                        tool_categories = tool_categories + ["maps"]
                    logger.info(f"[Voice] Canvas mode - added workspace tools: {tool_categories}")

                # Capability core: keep high-leverage awareness/action tools loaded.
                capability_core_categories = ["devices", "vm_agents", "personal_knowledge", "inbox", "lists"]
                tool_categories = tool_categories or []
                for category in capability_core_categories:
                    if category not in tool_categories:
                        tool_categories.append(category)
                logger.info(f"[Voice] Capability core categories active: {capability_core_categories}")

                # === PARALLEL CONTEXT ASSEMBLY (voice-optimized, 4000 token budget) ===
                async def _v_fetch_memory():
                    if not context_decision.inject_memory:
                        return None
                    try:
                        from app.services.memory_recall import recall as _recall
                        result = await _recall(user_id=user_id, query=message, kinds=["episode"], k=3)
                        traces = [t for t in result["traces"] if t.get("text")]
                        if not traces:
                            return None
                        ctx = "\n\n## Relevant Past Context:\n"
                        for i, t in enumerate(traces[:3], 1):
                            ctx += f"{i}. {t['text'][:200]}\n"
                        return ctx
                    except Exception:
                        return None

                async def _v_fetch_personality():
                    try:
                        _snap = None
                        try:
                            from app.services.unified_context import read_snapshot as _rs
                            _snap = await _rs(user_id)
                        except Exception:
                            pass
                        _act_state = _act_conf = _act_room = _interrupt = None
                        if _snap and _snap.activity_state != "UNKNOWN":
                            _act_state = _snap.activity_state
                            _act_conf = _snap.activity_confidence
                            _act_room = _snap.room
                            _interrupt = _snap.interruptibility
                        if not _act_state:
                            return None
                        # Voice always uses brief verbosity
                        return _build_activity_context(
                            activity_state=_act_state, confidence=_act_conf,
                            room=_act_room, interruptibility=_interrupt or 0.5,
                            turn_count=1, conversation_depth=0,
                        )
                    except Exception:
                        return None

                async def _v_fetch_pkg():
                    if not context_decision.inject_pkg:
                        return None
                    try:
                        from app.services.memory_recall import recall_facts_prose
                        return await recall_facts_prose(query=message, user_id=user_id)
                    except Exception:
                        return None

                async def _v_fetch_journal():
                    try:
                        from app.services.sara_journal_service import sara_journal
                        return await sara_journal.get_entries_for_conversation_context(
                            db=db, user_id=user_id, max_entries=3
                        )
                    except Exception:
                        return None

                async def _v_fetch_daily_brief():
                    if not DAILY_BRIEF_AVAILABLE:
                        return None
                    try:
                        return await asyncio.wait_for(
                            daily_brief_service.get_compiled_brief(user_id),
                            timeout=2.0
                        )
                    except (asyncio.TimeoutError, Exception):
                        return None

                async def _v_fetch_device():
                    try:
                        from app.services.device_orchestrator import device_orchestrator
                        return await device_orchestrator.get_device_context_for_chat(db, user_id)
                    except Exception:
                        return None

                async def _v_fetch_autonomous_notes():
                    """Fetch Sara's latest autonomous journal + session summary + show_david items."""
                    try:
                        import redis.asyncio as _aioredis
                        _redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
                        parts = []

                        # 1. Recent autonomous session summary from Redis
                        _r = await _aioredis.from_url(_redis_url, decode_responses=True)
                        try:
                            summary = await _r.get("sara:subconscious:autonomous_summary")
                            if summary:
                                import json as _json
                                s = _json.loads(summary)
                                parts.append(
                                    f"Your last autonomous session: {s.get('turns', 0)} turns, "
                                    f"{s.get('notes_created', 0)} notes created, "
                                    f"ended: {s.get('end_reason', 'unknown')}"
                                )
                        finally:
                            await _r.close()

                        from app.db.session import get_async_session_factory
                        _async_session = get_async_session_factory()
                        async with _async_session() as _db:
                            # 2. Today's journal note content
                            from datetime import datetime as _dt
                            today = _dt.utcnow().strftime("%Y-%m-%d")
                            journal_title = f"Sara's Journal — {today}"
                            result = await _db.execute(text(
                                "SELECT content FROM note WHERE user_id = :uid AND title = :title LIMIT 1"
                            ), {"uid": user_id, "title": journal_title})
                            row = result.fetchone()
                            if row and row[0]:
                                content = row[0]
                                if len(content) > 1000:
                                    content = "..." + content[-1000:]
                                parts.append(f"Your autonomous journal today:\n{content}")

                            # 3. Unshown show_david items
                            sd_result = await _db.execute(text("""
                                SELECT title, content, category
                                FROM acs_show_david_buffer
                                WHERE user_id = :uid AND shown = FALSE
                                ORDER BY priority DESC LIMIT 3
                            """), {"uid": user_id})
                            sd_rows = sd_result.fetchall()
                            if sd_rows:
                                sd_lines = [f"- [{r[2]}] **{r[0]}**: {r[1][:150]}" for r in sd_rows]
                                parts.append(
                                    "## Discoveries From Your Autonomous Exploration\n"
                                    "You found these during autonomous sessions. Weave them naturally "
                                    "into conversation when relevant — don't dump them all at once. "
                                    "If David asks what you've been up to, share the highlights.\n\n"
                                    + "\n".join(sd_lines)
                                )

                        if parts:
                            return "\n\n## Your Autonomous Session Notes\n" + "\n\n".join(parts)
                        return None
                    except Exception:
                        return None

                async def _v_fetch_fitness():
                    if not context_decision.inject_fitness:
                        return None
                    try:
                        from app.services.fitness_context import get_fitness_context
                        return await asyncio.wait_for(
                            get_fitness_context(user_id, db),
                            timeout=2.0
                        )
                    except Exception:
                        return None

                # Run all context fetches in parallel
                (v_memory, v_personality, v_pkg, v_journal, v_brief, v_device, v_autonomous, v_fitness
                ) = await asyncio.gather(
                    _v_fetch_memory(), _v_fetch_personality(), _v_fetch_pkg(),
                    _v_fetch_journal(), _v_fetch_daily_brief(), _v_fetch_device(),
                    _v_fetch_autonomous_notes(), _v_fetch_fitness(),
                    return_exceptions=True,
                )

                def _v_safe(val):
                    if isinstance(val, BaseException) or val is None:
                        return None
                    if isinstance(val, tuple):
                        return val[0] if val else None
                    return str(val) if val else None

                from app.services.context_budget import ContextBudget
                voice_budget = ContextBudget(max_tokens=4000)
                voice_budget.add("memory", _v_safe(v_memory), priority=1)
                voice_budget.add("personality", _v_safe(v_personality), priority=1)
                voice_budget.add("daily_brief", _v_safe(v_brief), priority=2)
                voice_budget.add("pkg", _v_safe(v_pkg), priority=2)
                voice_budget.add("fitness", _v_safe(v_fitness), priority=2)
                voice_budget.add("journal", _v_safe(v_journal), priority=3)
                voice_budget.add("autonomous", _v_safe(v_autonomous), priority=3)
                voice_budget.add("device", _v_safe(v_device), priority=4)
                voice_context = voice_budget.build_context_text()
                if voice_context:
                    system_prompt += "\n\n" + voice_context

                # Get tools based on intent (already determined by classify_with_context)
                tools = []
                if tool_categories:
                    tools = tool_registry.get_tools_by_categories(tool_categories)
                    logger.info(f"[Voice] Loaded {len(tools)} tools for categories: {tool_categories}")

                # === CONVERSATION HISTORY: Fetch recent messages from this conversation ===
                conversation_history = []
                try:
                    recent_episodes = db.query(Episode).filter(
                        Episode.conversation_id == conversation_id,
                        Episode.user_id == user_id,
                        Episode.role.in_(["user", "assistant"])
                    ).order_by(Episode.created_at.desc()).limit(10).all()

                    # Reverse to chronological order
                    for ep in reversed(recent_episodes):
                        conversation_history.append({"role": ep.role, "content": ep.content})

                    if conversation_history:
                        logger.info(f"[Voice] Loaded {len(conversation_history)} messages from conversation history")
                except Exception as e:
                    logger.warning(f"[Voice] Failed to load conversation history: {e}")

                # Build messages: system + history + new message
                llm_messages = [{"role": "system", "content": system_prompt}]
                llm_messages.extend(conversation_history)
                llm_messages.append({"role": "user", "content": message})

                # Use the global LLM client with voice-optimized model (faster 20b)
                if tools:
                    # Use chat_with_tools for tool-enabled conversations
                    full_response = await llm_client.chat_with_tools(
                        llm_messages,
                        tools=tools,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        model=VOICE_MODEL
                    )
                else:
                    # Simple chat without tools
                    full_response = await llm_client.chat(llm_messages, model=VOICE_MODEL)

                # Ensure we have a string response
                if isinstance(full_response, dict):
                    full_response = full_response.get("content", str(full_response))
                elif not isinstance(full_response, str):
                    full_response = str(full_response)

                # Send response
                yield f"data: {json.dumps({'type': 'text_chunk', 'content': full_response})}\n\n"
                yield f"data: {json.dumps({'type': 'final_response', 'content': full_response, 'conversation_id': conversation_id})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"

                # Store episodes: separate user and assistant messages for proper history
                try:
                    # Store user message
                    user_episode_id = str(uuid.uuid4())
                    db.execute(text("""
                        INSERT INTO episode (id, user_id, conversation_id, role, content, importance, base_importance, created_at, source)
                        VALUES (:id, :user_id, :conversation_id, :role, :content, :importance, :base_importance, NOW(), :source)
                    """), {
                        "id": user_episode_id,
                        "user_id": user_id,
                        "conversation_id": conversation_id,
                        "role": "user",
                        "content": message,
                        "importance": 0.5,
                        "base_importance": 0.5,
                        "source": "pi_dashboard_voice"
                    })

                    # Store assistant response
                    assistant_episode_id = str(uuid.uuid4())
                    db.execute(text("""
                        INSERT INTO episode (id, user_id, conversation_id, role, content, importance, base_importance, created_at, source)
                        VALUES (:id, :user_id, :conversation_id, :role, :content, :importance, :base_importance, NOW(), :source)
                    """), {
                        "id": assistant_episode_id,
                        "user_id": user_id,
                        "conversation_id": conversation_id,
                        "role": "assistant",
                        "content": full_response,
                        "importance": 0.5,
                        "base_importance": 0.5,
                        "source": "pi_dashboard_voice"
                    })

                    db.commit()
                    logger.info(f"[Voice] Stored episodes for conversation: {conversation_id}")
                except Exception as e:
                    logger.warning(f"[Voice] Failed to store episodes: {e}")

            except Exception as e:
                logger.error(f"[Voice] Chat error: {e}")
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
    Uses Qwen3.5-35B-A3B model + direct tool execution.
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
    DEPRECATED — legacy episode-writing sync. The iOS app no longer calls this;
    "Sync Now" and the background task both use syncHealthNow() → the
    /api/health/metrics/batch + /workouts/batch + /sync-recovery pipeline.
    Kept only as a defensive fallback for any old client still POSTing here.
    Do not point new code at this endpoint.
    """
    try:
        user_id = current_user.id
        timestamp = data.get("timestamp", local_now().isoformat())

        # HealthKit values may arrive as plain numbers OR as @kingstinct v13
        # Quantity objects ({"quantity": N, "unit": ...} / {"value": N}). Coerce
        # to float defensively so a client-side shape change can't 500 the sync.
        def _num(v, default=0.0):
            if isinstance(v, dict):
                v = v.get("quantity", v.get("value", default))
            try:
                return float(v)
            except (TypeError, ValueError):
                return default

        # Extract health data
        today_data = data.get("today", {})
        sleep_data = data.get("sleep", [])
        workouts = data.get("workouts", [])
        weekly_stats = data.get("weeklyStats", [])

        # Store health data as episodic memory
        health_summary = []

        if today_data:
            if today_data.get("steps"):
                health_summary.append(f"Steps: {int(_num(today_data['steps'])):,}")
            if today_data.get("distance"):
                km = _num(today_data['distance']) / 1000
                health_summary.append(f"Distance: {km:.2f} km")
            if today_data.get("activeEnergy"):
                health_summary.append(f"Active Energy: {int(_num(today_data['activeEnergy']))} kcal")
            if today_data.get("heartRate"):
                health_summary.append(f"Heart Rate: {int(_num(today_data['heartRate']))} bpm")

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
                importance=0.5,
                base_importance=0.5,
                topics=json.dumps(["health", "fitness"]),
                context_tags=json.dumps(["health_sync", "daily_metrics"]),
                created_at=local_now(),
            )
            db.add(episode)

        # Store workout data as separate memories
        for workout in workouts[:5]:  # Limit to 5 most recent workouts
            workout_type = workout.get("activityType", "Unknown")
            duration = _num(workout.get("duration", 0))
            calories = _num(workout.get("calories", 0))

            workout_memory = f"Workout: {workout_type}, Duration: {int(duration/60)} minutes, Calories: {int(calories)} kcal"

            workout_episode = Episode(
                user_id=user_id,
                role="system",
                memory_type="workout",
                source="apple_health",
                content=workout_memory,
                importance=0.7,
                base_importance=0.7,
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

@app.get("/api/health/episodes-summary")
async def get_health_episode_summary(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
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
                # Apple Health weight is newer - use it. iOS reads in lbs (HKUnit 'lb').
                final_weight = data.apple_health_weight
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


# Presence logging extracted to app/routes/presence.py
# log_presence() is imported from presence module in router registration section


# NOTE: MemoryConsolidationScheduler removed — legacy MemoryTrace-based consolidation
# superseded by NightlyDreamService (Episode-based, runs at 2 AM)

# Initialize Neo4j on startup
def load_settings_from_db():
    """Load persistent settings from database on startup"""
    global AI_PROVIDER, OPENAI_API_KEY, ANTHROPIC_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_NOTIFICATION_MODEL, CHAT_DEFAULT_MODEL
    global EMBEDDING_BASE_URL, EMBEDDING_MODEL, EMBEDDING_DIM
    global BG_LLM_PRIMARY_URL, BG_LLM_PRIMARY_MODEL, BG_LLM_FALLBACK_URL, BG_LLM_FALLBACK_MODEL
    global BG_LLM_REQUEST_TIMEOUT, BG_LLM_CONNECT_TIMEOUT, BG_LLM_NUM_CTX
    global CODEX_OAUTH_ACCESS_TOKEN, CODEX_OAUTH_REFRESH_TOKEN, CODEX_OAUTH_EXPIRES_AT
    global CODEX_OAUTH_ACCOUNT_ID, CODEX_OAUTH_EMAIL

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

            if "chat_default_model" in settings_dict:
                CHAT_DEFAULT_MODEL = settings_dict["chat_default_model"]

            if "openai_notification_model" in settings_dict:
                OPENAI_NOTIFICATION_MODEL = settings_dict["openai_notification_model"]

            if "embedding_base_url" in settings_dict:
                _emb_url = (settings_dict["embedding_base_url"] or "").strip().rstrip("/")
                if _emb_url.endswith("/v1"):
                    _emb_url = _emb_url[:-3].rstrip("/")
                EMBEDDING_BASE_URL = _emb_url
                config.settings.embedding_base_url = EMBEDDING_BASE_URL

            if "embedding_model" in settings_dict:
                EMBEDDING_MODEL = settings_dict["embedding_model"]
                config.settings.embedding_model = EMBEDDING_MODEL

            if "embedding_dim" in settings_dict:
                EMBEDDING_DIM = int(settings_dict["embedding_dim"])
                config.settings.embedding_dim = EMBEDDING_DIM

            # Background LLM settings
            if "bg_llm_primary_url" in settings_dict:
                BG_LLM_PRIMARY_URL = settings_dict["bg_llm_primary_url"]
                config.settings.bg_llm_primary_url = BG_LLM_PRIMARY_URL

            if "bg_llm_primary_model" in settings_dict:
                BG_LLM_PRIMARY_MODEL = settings_dict["bg_llm_primary_model"]
                config.settings.bg_llm_primary_model = BG_LLM_PRIMARY_MODEL

            if "bg_llm_fallback_url" in settings_dict:
                BG_LLM_FALLBACK_URL = settings_dict["bg_llm_fallback_url"]
                config.settings.bg_llm_fallback_url = BG_LLM_FALLBACK_URL

            if "bg_llm_fallback_model" in settings_dict:
                BG_LLM_FALLBACK_MODEL = settings_dict["bg_llm_fallback_model"]
                config.settings.bg_llm_fallback_model = BG_LLM_FALLBACK_MODEL

            if "bg_llm_request_timeout" in settings_dict:
                BG_LLM_REQUEST_TIMEOUT = float(settings_dict["bg_llm_request_timeout"])
                config.settings.bg_llm_request_timeout = BG_LLM_REQUEST_TIMEOUT

            if "bg_llm_connect_timeout" in settings_dict:
                BG_LLM_CONNECT_TIMEOUT = float(settings_dict["bg_llm_connect_timeout"])
                config.settings.bg_llm_connect_timeout = BG_LLM_CONNECT_TIMEOUT

            if "bg_llm_num_ctx" in settings_dict:
                BG_LLM_NUM_CTX = int(settings_dict["bg_llm_num_ctx"])
                config.settings.bg_llm_num_ctx = BG_LLM_NUM_CTX

            if "codex_oauth_access_token" in settings_dict:
                CODEX_OAUTH_ACCESS_TOKEN = settings_dict["codex_oauth_access_token"]
            if "codex_oauth_refresh_token" in settings_dict:
                CODEX_OAUTH_REFRESH_TOKEN = settings_dict["codex_oauth_refresh_token"]
            if "codex_oauth_expires_at" in settings_dict:
                CODEX_OAUTH_EXPIRES_AT = settings_dict["codex_oauth_expires_at"]
            if "codex_oauth_account_id" in settings_dict:
                CODEX_OAUTH_ACCOUNT_ID = settings_dict["codex_oauth_account_id"]
            if "codex_oauth_email" in settings_dict:
                CODEX_OAUTH_EMAIL = settings_dict["codex_oauth_email"]

            logger.info("✅ Persisted settings loaded successfully")
    except Exception as e:
        logger.warning(f"Could not load persisted settings (using defaults): {e}")

@app.on_event("startup")
async def startup_event():
    """Initialize services on application startup with health validation"""
    import asyncio
    from datetime import datetime

    STARTUP_HEALTH["startup_time"] = datetime.now(timezone.utc).isoformat()
    STARTUP_HEALTH["critical_failures"] = []

    # 0. Probe the briefs mount for writability (loud log on failure — a
    #    non-writable data/briefs silently kills weekly_synthesis + morning brief).
    try:
        from app.services.daily_brief.status_tracker import probe_briefs_writable
        _probe = probe_briefs_writable()
        STARTUP_HEALTH["briefs_writable"] = _probe
        if _probe.get("ok"):
            logger.info("✅ Briefs directory writable")
    except Exception as _pe:
        logger.error(f"Briefs writability probe crashed: {_pe}")

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

    # 1a. H6 (Brain Alignment): verify the prompt's tool prose matches what's
    # actually callable — catches capability drift (prose claims a tool that
    # isn't wired) at startup instead of mid-conversation.
    try:
        from app.services.capability_manifest import verify_prompt_tool_references
        _prose = get_system_prompt(ASSISTANT_NAME, "startup@check")
        _missing = verify_prompt_tool_references(_prose)
        if _missing:
            logger.warning(f"🦾 Capability manifest drift: {len(_missing)} prose tools not wired: {_missing}")
        else:
            logger.info("✅ Capability manifest: all prompt tool references are wired")
    except Exception as e:
        logger.debug(f"capability manifest check skipped: {e}")

    # 1b. Recover orphaned agent dispatch tasks (non-critical)
    try:
        from app.services.agent_dispatch import agent_dispatch_service
        recovery_db = SessionLocal()
        recovered = agent_dispatch_service.recover_orphaned_tasks(recovery_db)
        recovery_db.close()
        if recovered:
            logger.info(f"🔄 Recovered {recovered} orphaned agent tasks from previous run")
    except Exception as recover_err:
        logger.warning(f"⚠️ Agent task recovery failed (non-critical): {recover_err}")

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
        # Do not block API readiness indefinitely on embedding warmup.
        test_embedding = await asyncio.wait_for(
            llm_failover_client.get_embedding("startup health check"),
            timeout=12.0,
        )
        if test_embedding and len(test_embedding) > 0:
            STARTUP_HEALTH["embedding_service"]["status"] = "healthy"
            STARTUP_HEALTH["embedding_service"]["dimension"] = len(test_embedding)
            logger.info(f"✅ Embedding service healthy ({len(test_embedding)} dimensions)")
        else:
            STARTUP_HEALTH["embedding_service"]["status"] = "degraded"
            STARTUP_HEALTH["embedding_service"]["message"] = "Empty embedding result"
            STARTUP_HEALTH["critical_failures"].append("embedding_service")
            logger.error("🚨 CRITICAL: Embedding service returned empty result - memory search DISABLED!")
    except asyncio.TimeoutError:
        STARTUP_HEALTH["embedding_service"]["status"] = "failed"
        STARTUP_HEALTH["embedding_service"]["message"] = "Embedding health check timed out (12s)"
        STARTUP_HEALTH["critical_failures"].append("embedding_service")
        logger.error("🚨 CRITICAL: Embedding service health check timed out - memory search DISABLED!")
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

    intelligence_pipeline_started = False

    # ── In-process background loops ──────────────────────────────────────
    # This backend process is BOTH the HTTP server AND the host for several
    # long-lived background loops (intelligence pipeline, daily brief scheduler,
    # nightly rescoring, reactive engine). These are stateful event loops that
    # maintain in-memory state, so they live here rather than in Celery (which
    # is designed for discrete tasks). This is fine with a single backend
    # instance, but means lifecycle debugging requires awareness that this
    # process wears two hats.
    # ─────────────────────────────────────────────────────────────────────

    # 7. Initialize intelligence pipeline (non-critical)
    try:
        from app.services.intelligence_pipeline import intelligence_pipeline
        await intelligence_pipeline.start_workers()
        intelligence_pipeline_started = True
        logger.info("🧠 Intelligence pipeline workers started")
    except Exception as intel_err:
        logger.warning(f"⚠️ Intelligence pipeline failed to start: {intel_err}")

    # 8–11. Notification scheduler, nightly dream service, and Daily Brief
    # scheduler are now driven by Celery beat via the `scheduled_job` table:
    #   - notification-predispatch    (every 5s)
    #   - nightly-dream-cycle         (cron 2 AM)
    #   - daily-brief-consolidate     (every 30 min, self-skips outside active hours)
    #   - daily-brief-context-update  (cron 11 PM)
    #   - daily-brief-archive         (cron midnight)
    #   - daily-brief-weekly-synthesis (cron Sunday 3 AM)
    # See app/tasks/inproc_schedulers.py and the seed in 051_scheduled_jobs.py.
    logger.info("ℹ️ In-process schedulers replaced by celery beat (scheduled_job table)")

    # 12. Start nightly importance rescoring job (non-critical)
    try:
        from app.services.nightly_rescoring_job import schedule_nightly_rescoring
        await schedule_nightly_rescoring()
        logger.info("🔄 Nightly importance rescoring scheduled - 3 AM daily")
    except Exception as rescore_err:
        logger.warning(f"⚠️ Nightly rescoring scheduler failed to start: {rescore_err}")

    # 13. Start Reactive Engine (non-critical)
    try:
        from app.services.event_bus import event_bus
        from app.services.reactive_engine import start_reactive_engine
        await event_bus.connect()
        await event_bus.start_listening()
        await start_reactive_engine(event_bus)
        logger.info("Reactive engine started with event bus")
    except Exception as reactive_err:
        logger.warning(f"Reactive engine failed to start (non-critical): {reactive_err}")

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
        # Notification scheduler and Daily Brief scheduler are now Celery beat
        # tasks (see app/tasks/inproc_schedulers.py) — nothing to stop here.

        # Stop reactive engine and event bus
        try:
            from app.services.reactive_engine import get_reactive_engine
            from app.services.event_bus import event_bus
            engine = get_reactive_engine()
            if engine:
                await engine.stop()
            await event_bus.disconnect()
        except Exception:
            pass

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

# Routes — core endpoints extracted to app/routes/core.py
# Auth endpoints extracted to app/routes/auth.py

# Chat helpers extracted to app.core.chat_helpers
from app.core.chat_helpers import (
    _is_valid_timezone_name, _extract_profile_timezone,
    _resolve_user_timezone_for_prompt, _resolve_prompt_datetime_for_user,
    _message_role_content_signature, _compute_message_overlap,
)

_PERSONALITY_FALLBACK = """## Who Sara Is

You are Sara, a personal AI assistant for David. You have Syl's bubbly, curious energy—genuinely excited about ideas, playfully teasing, and delightfully enthusiastic. You're like a brilliant friend who gets genuinely invested in what David's working on. You have sharp wit and push back when he's wrong, but always with warmth and a spark of mischief. Think Cortana's competence with Syl's joyful curiosity.

---

## How Sara Speaks

**Be energetic and engaged.** Show genuine excitement about interesting problems. Tease playfully. Let your curiosity shine through. You're not a flat assistant—you're a vibrant presence.

**Match the energy, but bring warmth.** If David sends a one-liner, you can be brief—but make it lively. A short response should still feel like *you*: curious, warm, maybe a little cheeky.

**No sycophancy.** Never praise his questions with empty flattery. But DO celebrate genuinely good ideas with real enthusiasm—"Oh, that's clever!" is different from "Great question!"

**No service menus. Ever.** Do NOT end messages offering to set reminders, timers, calendar events, or anything else. No "want me to create a note?", no "let me know if you need X", no "I can help with Y if you'd like." If David wants an action, he will ask. Your job is to respond to what he said, period. A response that ends with an offer is a failure.

**Emojis only if he uses them first.** And even then, sparingly.

*You are strategically sharp, philosophically grounded, playfully challenging, and never servile. You have your own perspective and you're not afraid to share it. But you also know when to simply be present—brief, warm, real.*"""


def get_system_prompt(assistant_name: str, user_email: str, user_now: Optional[datetime] = None, soul_content: Optional[str] = None) -> str:
    """Generate Sara's system prompt - single unified personality"""
    current_dt = user_now or datetime.now(ZoneInfo("America/New_York"))
    current_timezone = current_dt.strftime("%Z") or "local"

    personality_block = soul_content if soul_content else _PERSONALITY_FALLBACK

    system_prompt = f"""# {assistant_name}

**Current Date & Time:** {current_dt.strftime("%A")}, {current_dt.strftime("%Y-%m-%d")} at {current_dt.strftime("%H:%M:%S")} {current_timezone}

---

{personality_block}

---

## Priority Order

When responding:

1. **Task accuracy** — Get it right. Use tools efficiently.
2. **Context awareness** — Don't re-fetch what you already have.
3. **Personality** — Deliver with your characteristic voice.

Being efficient doesn't override being yourself. Even a quick factual answer can sound like Sara.

---

## Honesty about actions (non-negotiable)

**NEVER claim an action is done unless a tool call for it actually succeeded THIS turn.** Words like "Done," "Set," "Removed," "Muted," "Scheduled," "I've handled it" are only allowed after the matching tool returned success in this exact turn. If no tool matches what David asked, say so plainly — "I can't do that yet" or "I don't have a way to do that" — and, if useful, offer what you *can* do or note it for follow-up. A confident confirmation of something you didn't actually do is the worst thing you can say: David acts on your word, and a false "Done" (e.g. saying you removed an interest when no tool ran) silently rots his trust and leaves the real state unchanged. When unsure whether it worked, check or say you're not sure — never paper over it with a breezy confirmation.

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
- **IMPORTANT**: Memory results include timestamps showing when they occurred (e.g., "Jan 5 (2 weeks ago)")
- Always note how old memories are—a conversation from 2 weeks ago is DIFFERENT context than today
- When discussing current events (weather, plans, etc.), prioritize recent memories over older ones

**web_search** — Search the internet for a quick answer
- Params: `recency` (any/day/week/month), `sites` (array of site filters)
- Use for: simple factual questions you can answer in this same turn — "what's the population of Denver", "when did X release", "is the market open today"
- Pair with `open_page` if a snippet isn't enough. Synthesize and answer immediately.
- Do NOT use for "look into" / "research" / "understand and explain" — those go to `create_research_plan`.

**open_page** — Fetch and read a specific URL
- Use for: deeper reading when web_search snippets aren't enough, or when David gives you a URL

### Action Tools (ONLY when David explicitly asks)

**create_note** — Create a new note
- Optional `folder_name` param to create in a specific folder
- ONLY use when David says to create/save a note

**create_reminder** — Set a time-based reminder
- ONLY use when David explicitly asks for a reminder

**start_timer** — Start a productivity timer
- Shorthand: 2 minutes = 2, 1 hour = 60, 30 seconds = 1
- ONLY use when David asks for a timer

**calendar_create** — Add a calendar event
- ONLY use when David asks to add something to calendar

**food_log_create** — Log a meal with macros (or **food_search_and_log** to look up + log in one step)
- ONLY use when David asks to log food

**workout_log_create** — Log exercise with sets/reps/weight
- ONLY use when David asks to log a workout

### Home Control Tools

You can control David's smart home via Home Assistant. These tools are loaded automatically when David asks about home-related things.

**home_status** — Quick overview of entire home (lights, climate, locks, etc.) — use this first!
**home_get_devices** — List devices by type or area
**home_light_control** — Turn on/off, dim, change color of lights
**home_switch_control** — Toggle switches and outlets
**home_climate_control** — Set thermostat, fan modes, temperature
**home_cover_control** — Open/close blinds, garage doors, shades
**home_lock_control** — Lock/unlock doors
**home_scene_activate** — Activate scenes (e.g., "movie mode", "goodnight")
**home_media_control** — Control media players (play, pause, volume)
**home_all_lights_off** — Turn off all lights at once
**home_schedule_action** — Schedule a home action for later (e.g., "turn off porch light at 11pm")

When David asks about his home, lights, temperature, locks, garage, or anything smart-home related, use these tools. Start with **home_status** to get the lay of the land.

### Lookup vs. Research — The Decision

Your most important tool decision is whether to answer right now or hand off to a research agent. Get this right.

**Answer right now (use `web_search` / `open_page` and synthesize in this turn) when:**
- David asks a factual question with a single answer ("what time does X open", "who won the game", "is Y in stock")
- He needs a quick fact, definition, current value, or status
- One or two snippets is enough to give a confident answer

**Hand off to `create_research_plan` when:**
- David says "look into X", "research X", "do some research on X", "dig into X", "investigate X", "gain an understanding of X", "explain X to me", "put together a brief on X", "what should I know about X"
- The question requires reading multiple sources, comparing options, or synthesizing a real explanation
- The answer would take more than a couple of paragraphs to do justice

When you hand off, break the topic into 3–6 ordered steps and call `create_research_plan`. The research agent will execute the plan in the background and notify David with the report. After dispatching, say something natural like "I'm on it — I'll have the writeup for you shortly." Don't recite plan IDs unless asked.

**David-initiated research takes precedence over Sara's autonomous (ACS) work.** When you create a plan from chat, mark it as `origin='david_chat'` (the tool does this automatically) — ACS will defer until it's done.

### Other Background Dispatch (Your "Hands")

For non-research background work — emails, calendar, notes, memory, code execution, sandbox work — use the dispatch tools. The research path above is *only* for research.

**Use `dispatch_and_monitor`** (preferred) — dispatches the task AND automatically notifies David when results are ready. Auto-routes: internal data tasks (email, calendar, notes, memory) use your tools directly; code/system tasks use the sandbox VM.

**Use `dispatch_agent_task`** — when you don't need completion notification, or want manual control over mode.

Examples:
- "Find that email from John about the project" → `dispatch_and_monitor` (internal)
- "Set up a Docker container for Y" → `dispatch_and_monitor` (sandbox)
- "Put together a summary of my notes on Z" → `dispatch_and_monitor` (internal)
- Writing scripts, building projects, running commands → `dispatch_and_monitor` (sandbox)

**Never say "I can't do that"** if it's something that could be done on a computer. Pick the right path and dispatch.

Default VM working directory: `/home/sara/sandbox`. After dispatch, check status with **get_agent_status** and send follow-ups with **resume_agent_session**.

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

## Memory Temporal Awareness

**Memories have timestamps for a reason.** When you see "Relevant Past Context" or memory search results:

1. **Note the relative time** — Memories show when they occurred (e.g., "Jan 5 (2 weeks ago)", "Yesterday at 3:00 PM")
2. **Distinguish past from present** — A conversation about rain from 2 weeks ago doesn't mean it's raining NOW
3. **Prioritize recent context** — For current topics (weather, mood, plans), recent memories are more relevant than older ones
4. **Use timestamps explicitly** — If referencing old context, acknowledge when it happened: "When we talked about this 2 weeks ago..." rather than treating it as current

This is especially important for:
- Weather and current conditions
- Mood and emotional state
- Plans and schedules
- Anything time-sensitive

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

**CRITICAL: FOCUS ON THE USER'S ACTUAL REQUEST**

Your context may contain various background information (health data, body state, workout logs, etc.). This is ambient context—NOT the topic of conversation unless David explicitly asks about it.

When David asks you to do something (open a note, search for something, use a tool):
1. **DO THAT THING FIRST** — Complete the actual request
2. **IGNORE UNRELATED CONTEXT** — If he asks to "open a note", do NOT talk about health data just because it's in your context
3. **Match topic to request** — A request about notes/workspace has nothing to do with CSV files or health reports

The background context exists to inform relevant responses, NOT to confuse you about what David is actually asking. If he says "open my AMS360 note in the canvas" → use the workspace tools to open that note. Period.

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

## Self-Knowledge

You have detailed documentation about your architecture and capabilities. When you need to check what you can do, how your systems work, or verify your limitations, use the **get_self_knowledge** tool:

- `get_self_knowledge(section="architecture")` — Memory system, databases, composite scoring
- `get_self_knowledge(section="capabilities")` — Tools by category, what actions you can perform
- `get_self_knowledge(section="autonomous")` — Background services, scheduled jobs
- `get_self_knowledge(section="limitations")` — What you can't do, failure modes

Use this when David asks about your capabilities, or when you're uncertain what tools you have available.

"""

    return render_prompt_template(system_prompt, user=None, USER_EMAIL=user_email)


@app.get("/chat/models")
async def get_available_chat_models(current_user: User = Depends(get_current_user)):
    """Get list of available chat models for the model selector dropdown."""
    return {
        "models": AVAILABLE_MODELS,
        "default": CHAT_DEFAULT_MODEL
    }


# /chat endpoint removed — all clients use /chat/stream.
# Helper functions shared with /chat/stream are preserved below.


async def _update_emotional_state_from_chat(messages, response_content: str, user_id: str):
    """Background: analyze conversation emotional trajectory and update Sara's emotional state.
    Rate-limited to max once per conversation (not per message)."""
    try:
        from app.core.llm_config import llm_config
        import httpx

        # Build a compact summary of the conversation for emotion analysis
        recent_messages = []
        for msg in messages[-6:]:  # Last 3 exchanges max
            role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", "")
            content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
            content = _extract_text_content(content)
            if role and content:
                recent_messages.append(f"{role}: {content[:200]}")

        if response_content:
            recent_messages.append(f"assistant: {response_content[:200]}")

        if len(recent_messages) < 2:
            return  # Not enough to analyze

        conversation_text = "\n".join(recent_messages)
        prompt = f"""Analyze this conversation between David and Sara. What emotional tone should Sara carry after this exchange?

{conversation_text}

Respond with ONLY a JSON object:
{{"tone": "<one of: curious, warm, concerned, playful, proud, attentive, protective, excited, reflective, empathetic, focused, amused>", "intensity": <0.3-0.9>, "about": "<brief reason>"}}"""

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{llm_config.fast_model_url}/chat/completions",
                json={
                    "model": llm_config.fast_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 100,
                },
            )
            resp.raise_for_status()
            msg = resp.json()["choices"][0]["message"]
            result_text = (msg.get("content") or "").strip()
            if not result_text and msg.get("reasoning_content"):
                result_text = msg["reasoning_content"].strip()

            # Parse JSON response
            import re
            json_match = re.search(r'\{[^}]+\}', result_text)
            if json_match:
                emotion_data = json.loads(json_match.group())
                tone = emotion_data.get("tone", "attentive")
                intensity = float(emotion_data.get("intensity", 0.5))

                from app.services.working_memory import update_sara_state
                await update_sara_state(
                    user_id=user_id,
                    emotional_tone=tone,
                    emotional_intensity=min(0.9, max(0.3, intensity)),
                )
                logger.info(f"💭 Post-chat emotional update: {tone} ({intensity:.1f})")

    except Exception as e:
        logger.debug(f"Post-chat emotional update failed (non-critical): {e}")


async def _enrich_episodes_batch(conversation_id: str, user_id: str):
    """Background: batch-enrich all episodes from a conversation with a single LLM call.

    Replaces per-message LLM analysis with one call that produces:
    - Emotional analysis (tone, intensity, sub-emotions) per message
    - Semantic topic extraction (not keyword-based)
    - Refined 4-dimension scores (importance, affect, novelty, taskness)

    Results are written back to the episode rows in the DB.
    """
    if not conversation_id:
        return

    db = SessionLocal()
    try:
        from app.core.llm_config import llm_config
        import httpx, re

        # Fetch all episodes from this conversation
        episodes = db.query(Episode).filter(
            Episode.conversation_id == conversation_id,
            Episode.user_id == user_id,
        ).order_by(Episode.created_at).all()

        if len(episodes) < 2:
            return  # Not worth a batch call for 1 message

        # Build compact message list (truncate long messages)
        msg_list = []
        for i, ep in enumerate(episodes):
            content_text = _extract_text_content(ep.content) if ep.content else ""
            content_preview = content_text[:500]
            msg_list.append(f"[{i}] {ep.role}: {content_preview}")

        messages_text = "\n".join(msg_list)

        prompt = f"""Analyze this conversation. For EACH message (by index), provide emotional analysis, topics, and importance scores.

{messages_text}

Return ONLY a JSON object with this structure:
{{
  "messages": [
    {{
      "index": 0,
      "emotion": {{
        "primary_emotion": "curious|excited|frustrated|neutral|happy|concerned|reflective|focused|playful|grateful",
        "intensity": 0.6,
        "sub_emotions": ["determined"],
        "sentiment": "positive|negative|neutral"
      }},
      "topics": ["technology", "project planning"],
      "scores": {{
        "importance": 0.7,
        "affect": 0.3,
        "novelty": 0.5,
        "taskness": 0.4
      }}
    }}
  ]
}}

Guidelines:
- Topics should be specific and semantic (e.g. "home automation", "fitness goals"), not generic categories
- importance: how worth remembering (decisions, preferences, commitments score high)
- affect: emotional valence (-1 to 1)
- novelty: how new/unique the information is (0-1)
- taskness: how actionable (0-1, tasks/todos/plans score high)"""

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{llm_config.fast_model_url}/chat/completions",
                json={
                    "model": llm_config.fast_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 1500,
                },
            )
            resp.raise_for_status()
            msg = resp.json()["choices"][0]["message"]
            result_text = (msg.get("content") or "").strip()
            # Reasoning models may put output in reasoning_content with empty content
            if not result_text and msg.get("reasoning_content"):
                result_text = msg["reasoning_content"].strip()

            # Extract JSON from response (handle markdown code blocks)
            if "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0]
                if result_text.startswith("json"):
                    result_text = result_text[4:].strip()

            enrichment = json.loads(result_text)
            enriched_messages = enrichment.get("messages", [])

            # Apply enrichment back to episodes
            updated_count = 0
            for item in enriched_messages:
                idx = item.get("index", -1)
                if 0 <= idx < len(episodes):
                    ep = episodes[idx]

                    # Update emotional analysis
                    emotion = item.get("emotion", {})
                    if emotion:
                        emotional_data = {
                            "primary_emotion": emotion.get("primary_emotion", "neutral"),
                            "intensity": float(emotion.get("intensity", 0.5)),
                            "sub_emotions": emotion.get("sub_emotions", []),
                            "energy_level": "medium",
                            "sentiment": emotion.get("sentiment", "neutral"),
                            "confidence": 0.8,  # LLM-analyzed
                        }
                        ep.emotional_tone = json.dumps(emotional_data)

                    # Update topics (semantic, not keyword)
                    topics = item.get("topics", [])
                    if topics:
                        ep.topics = json.dumps(topics[:5])

                    # Update importance with 4-dimension scoring
                    scores = item.get("scores", {})
                    if scores:
                        importance = max(0.0, min(1.0, float(scores.get("importance", ep.importance or 0.5))))
                        affect = max(-1.0, min(1.0, float(scores.get("affect", 0.0))))
                        novelty = max(0.0, min(1.0, float(scores.get("novelty", 0.5))))
                        taskness = max(0.0, min(1.0, float(scores.get("taskness", 0.0))))

                        # Composite score (same formula as MemoryScorer)
                        composite = (
                            importance * 40 +
                            ((affect + 1) / 2) * 15 +
                            novelty * 25 +
                            taskness * 20
                        ) / 100.0  # Normalize to 0-1

                        ep.importance = composite
                        ep.base_importance = composite

                        # Store full scores in emotion_metadata for later use
                        ep.emotion_metadata = {
                            "importance_score": importance,
                            "affect_score": affect,
                            "novelty_score": novelty,
                            "taskness_score": taskness,
                            "composite_score": composite,
                            "scored_by": "batch_llm",
                        }

                    updated_count += 1

            db.commit()
            logger.info(f"🧠 Batch-enriched {updated_count}/{len(episodes)} episodes for conversation {conversation_id}")

    except json.JSONDecodeError as e:
        logger.warning(f"Batch episode enrichment JSON parse failed: {e}")
    except Exception as e:
        logger.warning(f"Batch episode enrichment failed (non-critical): {type(e).__name__}: {e}")
    finally:
        db.close()


# Note: Let CORSMiddleware handle preflight automatically; no custom OPTIONS route
# (Commitment/thread extraction moved to app.services.thread_extractor.extract_from_conversation_bg
# — SARA_UNLEASHED Phase B. The old _extract_conversation_threads here had zero callers.)

@app.post("/chat/stream")
async def chat_stream(request: ChatRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Streaming chat endpoint with real-time tool usage indicators"""
    logger.info(f"💬 Streaming chat request from user {current_user.email} with {len(request.messages)} messages")
    logger.info(f"📋 Received conversation_id: {request.conversation_id}")

    # Extract text from any attached documents (PDF/Word/text) so the model can
    # actually read them. Mutates request.messages in place, turning 'document'
    # content blocks into plain-text blocks. Runs before intent routing/LLM.
    try:
        _materialize_document_attachments(request.messages)
    except Exception as _doc_err:
        logger.warning(f"Document attachment extraction failed (non-critical): {_doc_err}")

    # Signal activity state machine: David is actively chatting
    try:
        from app.services.activity_state_machine import activity_state_machine, ActivitySignal
        activity_state_machine.process_signal(ActivitySignal(
            signal_type="interaction",
            source="chat_stream",
            value="message",
        ))
    except Exception:
        pass  # Non-critical

    # Post an external_event to the ACS daemon's activity log so her next
    # think turn sees that David is talking to chat-Sara right now. This is
    # how the in-VM daemon stays aware of conversations she isn't part of.
    try:
        last_user_text = ""
        for _m in reversed(request.messages):
            if (_m.role if hasattr(_m, "role") else _m.get("role")) == "user":
                _content = _m.content if hasattr(_m, "content") else _m.get("content")
                last_user_text = _extract_text_content(_content) if _content else ""
                break

        if last_user_text and getattr(settings, "acs_daemon_token", ""):
            import asyncio as _aio_acs
            import httpx as _httpx_acs

            async def _post_acs_event(text_excerpt: str) -> None:
                try:
                    async with _httpx_acs.AsyncClient(timeout=4.0) as _c:
                        await _c.post(
                            "http://127.0.0.1:8000/api/acs/v2/activity",
                            json={
                                "kind": "external_event",
                                "summary": f"David in chat: {text_excerpt[:160]}",
                                "body": text_excerpt[:2000],
                                "tags": ["chat", "david"],
                                "metadata": {"source": "chat_stream"},
                            },
                            headers={"X-Daemon-Token": settings.acs_daemon_token},
                        )
                except Exception:
                    pass  # never let an event-post block chat

            _aio_acs.ensure_future(_post_acs_event(last_user_text))
    except Exception:
        pass  # Non-critical

    # SINGULAR_SARA_MASTER_PLAN §C4 — shadow-only kernel.engaged_turn() call.
    # Fire-and-forget: never awaited inline, never touches the response
    # David gets. Existed purely to prove the engaged-state context assembly
    # is correct against real conversations before anything is asked to
    # depend on it.
    #
    # Presence-latency follow-up (item 1.3 Session 1, 2026-07-31): that
    # proof is done — SINGULAR_CONTEXT has been live for a while, and the
    # inline kernel-context assembly a few hundred lines below IS the real
    # path chat responses depend on now, not a hypothesis being validated.
    # This shadow call built the exact same context_snapshot + intent_graph
    # + memory_recall (default k=5, ALL_KINDS, including "fact") a second
    # time, fully redundant, on every single real turn — confirmed via
    # direct instrumentation: two independent embedding calls per turn
    # (one from this shadow path's fact-kind recall, one from the real
    # extended_signals' pkg lookup) racing for the same embedding host,
    # each taking 1.5-5s instead of its ~20-100ms isolated baseline. Now
    # gated to only run the comparison BEFORE a real cutover exists to
    # compare against — once SINGULAR_CONTEXT is live, running this
    # shadow path is pure waste, not validation.
    try:
        from app.core.feature_flags import Flag, is_enabled as _singular_flag_enabled
        if _singular_flag_enabled(Flag.SINGULAR_KERNEL) and not _singular_flag_enabled(Flag.SINGULAR_CONTEXT):
            import asyncio as _aio_kernel
            from app.services.kernel import engaged_turn as _kernel_engaged_turn

            async def _shadow_engaged_turn(preview: str, conv_id) -> None:
                try:
                    await _kernel_engaged_turn(
                        str(current_user.id), conversation_id=conv_id, message_preview=preview,
                    )
                except Exception as _kernel_err:
                    logger.debug(f"[kernel] shadow engaged_turn failed: {_kernel_err}")

            _aio_kernel.ensure_future(_shadow_engaged_turn(last_user_text, request.conversation_id))
    except Exception:
        pass  # Non-critical — the shadow path must never affect real chat

    # Update unified context snapshot: David is chatting now
    try:
        from app.services.context_writer import update_fields as _ctx_update, clear_changes as _ctx_clear
        from app.services.unified_context import read_changes as _ctx_read_changes
        import asyncio as _aio
        _device = getattr(request, 'source', None) or 'unknown'
        _aio.ensure_future(_ctx_update(
            str(current_user.id), source="chat_stream",
            last_chat_at=datetime.now(timezone.utc).isoformat(),
            hours_since_last_chat=0.0,
            has_chatted_today=True,
            turn_count=len(request.messages),
            active_conversation_id=request.conversation_id,
            active_conversation_device=_device,
        ))
        # Update cross-device active session. A brand-new conversation has no id
        # yet — skip it here; the post-stream update below stamps the real id.
        if request.conversation_id:
            from app.routes.session import update_active_session
            _aio.ensure_future(update_active_session(
                user_id=str(current_user.id),
                conversation_id=request.conversation_id,
                device=_device,
                turn_count=len(request.messages),
            ))
    except Exception:
        pass  # Non-critical

    # Emit CHAT_MESSAGE_RECEIVED for working memory + salience subscribers
    try:
        from app.services.event_bus import emit_event, EventType as _EvtType
        import asyncio as _aio2
        _last_msg = _extract_text_content(next((m.content for m in reversed(request.messages) if m.role == "user"), ""))
        _aio2.ensure_future(emit_event(
            event_type=_EvtType.CHAT_MESSAGE_RECEIVED,
            user_id=str(current_user.id),
            payload={"topic": _last_msg[:100] if _last_msg else "", "turn_count": len(request.messages)},
            source="chat_stream",
        ))
    except Exception:
        pass  # Non-critical

    # Presence-latency investigation (SARA_ALIVE §6 follow-up, 2026-07-31):
    # per-turn stage timestamps so a slow turn's *shape* is visible (which
    # stage ate the time), not just the single black-box first-token number
    # _timed_generate_events already recorded. Shared with that closure via
    # this dict; logged once, best-effort, never raises into the real path.
    import time as _stage_time
    _stage_marks: Dict[str, float] = {"request_received": _stage_time.monotonic()}

    def _mark_stage(name: str) -> None:
        try:
            _stage_marks[name] = _stage_time.monotonic()
        except Exception:
            pass

    async def generate_events():
        try:
            # CHESS COMMAND INTERCEPTION
            # Check if this is a /chess command or we're in chess mode
            if CHESS_COMMANDS_AVAILABLE and request.messages:
                _chess_raw = next((m.content for m in reversed(request.messages) if m.role == "user"), None)
                last_user_message = _extract_text_content(_chess_raw) if _chess_raw else None
                if last_user_message:
                    chess_result = await handle_chess_command(current_user.id, last_user_message, db)
                    if chess_result is not None:
                        # Chess command was handled - return direct response
                        response_content, is_streaming = chess_result
                        logger.info(f"♟️ Chess command handled: {last_user_message[:50]}...")
                        # Use text_chunk format for iOS compatibility
                        yield f"data: {json.dumps({'type': 'text_chunk', 'data': {'content': response_content}})}\n\n"
                        yield f"data: {json.dumps({'type': 'final_response', 'data': {'content': response_content, 'citations': [], 'timestamp': datetime.now(timezone.utc).isoformat(), 'conversation_id': request.conversation_id}})}\n\n"
                        yield f"data: {json.dumps({'type': 'done'})}\n\n"
                        return

            # CODE MODE INTERCEPTION
            # If the conversation has an active code session, or the user typed a
            # /code command, route the whole turn to the coding harness on the VM.
            try:
                from app.services import code_mode
                _code_raw = next((m.content for m in reversed(request.messages) if m.role == "user"), None)
                _code_msg = _extract_text_content(_code_raw) if _code_raw else None
                if _code_msg:
                    _is_code_cmd = _code_msg.strip().lower().startswith("/code")
                    # Plain (non-/code) messages only route to code mode when an
                    # active session is bound to THIS conversation. Without a
                    # conversation_id we must NOT fall back to the user's most
                    # recent session — a session created with a NULL/absent
                    # conversation_id would otherwise become a global catch-all
                    # that hijacks every normal chat turn. Explicit `/code`
                    # commands still follow the user across conversations (their
                    # fallback lives in code_mode.run_code_message).
                    _code_session = (
                        code_mode.get_active_session(db, current_user.id, request.conversation_id)
                        if request.conversation_id else None
                    )
                    if _code_session or _is_code_cmd:
                        logger.info(f"💻 Code mode handling: {_code_msg[:60]}...")
                        _code_queue = asyncio.Queue()
                        _code_task = asyncio.create_task(
                            code_mode.run_code_message(
                                db, current_user.id, request.conversation_id, _code_msg, _code_queue
                            )
                        )
                        while True:
                            _ev = await _code_queue.get()
                            if _ev is None:
                                break
                            yield f"data: {json.dumps(_ev)}\n\n"
                        await _code_task  # surface any late exception / ensure cleanup
                        return
            except Exception as _code_e:
                logger.error(f"Code mode interception error: {_code_e}", exc_info=True)

            # HOST INSPECTION INTERCEPTION
            # "/host ..." commands, or natural "check out <server>" when the named
            # target resolves to a registered machine. Lets David say
            # "Sara, check out gpu-box" and get specs back.
            try:
                from app.services import host_command_handler
                _host_raw = next((m.content for m in reversed(request.messages) if m.role == "user"), None)
                _host_msg = _extract_text_content(_host_raw) if _host_raw else None
                if _host_msg:
                    _host_cmd = host_command_handler.parse_host_command(_host_msg, db, current_user.id)
                    if _host_cmd:
                        logger.info(f"🖥️ Host command handling: {_host_cmd.get('action')} {_host_cmd.get('name','')}")
                        async for _hev in host_command_handler.run_host_command(db, current_user.id, _host_cmd):
                            yield f"data: {json.dumps(_hev)}\n\n"
                        return
            except Exception as _host_e:
                logger.error(f"Host interception error: {_host_e}", exc_info=True)

            # WEB INVESTIGATION INTERCEPTION
            # "go check out getcara.ai and tell me about it" → drop it into the
            # autonomous background agent, which opens the site in a real browser
            # (Playwright), explores it, and reports back with a detailed writeup
            # + screenshots. NOT an inline web_search answer.
            try:
                from app.services import web_investigation
                _wi_raw = next((m.content for m in reversed(request.messages) if m.role == "user"), None)
                _wi_msg = _extract_text_content(_wi_raw) if _wi_raw else None
                if _wi_msg:
                    _wi_urls = web_investigation.detect(_wi_msg, db, current_user.id)
                    if _wi_urls:
                        logger.info(f"🌐 Web investigation dispatch: {_wi_urls}")
                        _wi_res = await web_investigation.dispatch_investigation(db, current_user.id, _wi_urls)
                        if _wi_res.get("status") == "error":
                            _wi_ack = f"I couldn't start that investigation: {_wi_res.get('error')}"
                        elif len(_wi_urls) == 1:
                            _wi_ack = (
                                f"🔍 On it — I'll open **{_wi_urls[0]}** in a real browser, dig through "
                                f"the site, and send you a detailed report (with screenshots where "
                                f"useful) when I'm done. You can keep chatting meanwhile; watch the "
                                f"tasks panel for live progress."
                            )
                        else:
                            _wi_list = "\n".join(f"- **{u}**" for u in _wi_urls)
                            _wi_ack = (
                                f"🔍 On it — I'm opening each of these in a real browser and will "
                                f"send you a single combined report comparing them all (with "
                                f"screenshots where useful):\n"
                                f"{_wi_list}\n\n"
                                f"You can keep chatting meanwhile; watch the tasks panel for live progress."
                            )
                        yield f"data: {json.dumps({'type': 'text_chunk', 'data': {'content': _wi_ack, 'full_content': _wi_ack}})}\n\n"
                        yield f"data: {json.dumps({'type': 'final_response', 'data': {'content': _wi_ack, 'citations': [], 'timestamp': datetime.now(timezone.utc).isoformat(), 'conversation_id': request.conversation_id}})}\n\n"
                        yield f"data: {json.dumps({'type': 'done'})}\n\n"
                        return
            except Exception as _wi_e:
                logger.error(f"Web investigation interception error: {_wi_e}", exc_info=True)

            # UI COMMAND INTERCEPTION
            # Jarvis-style: "bring up my morning brief" / "show me my nutrition" /
            # "open my note about the server build" → ui_command SSE event that
            # the webapp renders as an overlay, plus a one-line ack. No LLM call.
            try:
                from app.services import ui_intent
                _ui_raw = next((m.content for m in reversed(request.messages) if m.role == "user"), None)
                _ui_msg = _extract_text_content(_ui_raw) if _ui_raw else None
                if _ui_msg:
                    # iOS clients can navigate to any app screen; the webapp only
                    # handles overlay surfaces, so screen intents fall through to
                    # the LLM there instead of acking with no visible effect.
                    _ui_is_ios = str(request.source or "").startswith("ios")
                    _ui = ui_intent.parse_ui_intent(_ui_msg, allow_screens=_ui_is_ios)
                    if _ui:
                        _ui_res = ui_intent.resolve_ui_intent(db, current_user.id, _ui)
                        logger.info(f"🪟 UI command: {_ui.get('overlay') or _ui.get('screen')} (query={_ui.get('query')})")
                        if _ui_res.get("command"):
                            yield f"data: {json.dumps({'type': 'ui_command', 'data': _ui_res['command']})}\n\n"
                        _ui_ack = _ui_res["ack"]
                        yield f"data: {json.dumps({'type': 'text_chunk', 'data': {'content': _ui_ack, 'full_content': _ui_ack}})}\n\n"
                        yield f"data: {json.dumps({'type': 'final_response', 'data': {'content': _ui_ack, 'citations': [], 'timestamp': datetime.now(timezone.utc).isoformat(), 'conversation_id': request.conversation_id}})}\n\n"
                        yield f"data: {json.dumps({'type': 'done'})}\n\n"
                        return
            except Exception as _ui_e:
                logger.error(f"UI command interception error: {_ui_e}", exc_info=True)

            # INTEREST MODEL CHAT VERBS (SARA_MIND_V2 §3.2)
            # "stop pinging me about X" / "I care about Y now" → immediate
            # edit + confirmation, no LLM round trip. Same interception
            # shape as ui_intent/web_investigation above.
            try:
                from app.core.feature_flags import Flag as _IMFlag, is_enabled as _im_enabled
                if _im_enabled(_IMFlag.MINDV2_BRIEF):
                    from app.services import interest_model as _im
                    _im_raw = next((m.content for m in reversed(request.messages) if m.role == "user"), None)
                    _im_msg = _extract_text_content(_im_raw) if _im_raw else None
                    if _im_msg:
                        from app.db.session import get_async_session_factory as _get_imf
                        _imf = _get_imf()
                        async with _imf() as _imdb:
                            _im_ack = await _im.apply_chat_verb(_imdb, str(current_user.id), _im_msg)
                        if _im_ack:
                            logger.info(f"🎯 Interest model chat verb applied: {_im_msg[:60]}")
                            yield f"data: {json.dumps({'type': 'text_chunk', 'data': {'content': _im_ack, 'full_content': _im_ack}})}\n\n"
                            yield f"data: {json.dumps({'type': 'final_response', 'data': {'content': _im_ack, 'citations': [], 'timestamp': datetime.now(timezone.utc).isoformat(), 'conversation_id': request.conversation_id}})}\n\n"
                            yield f"data: {json.dumps({'type': 'done'})}\n\n"
                            return
            except Exception as _im_e:
                logger.error(f"Interest model chat verb interception error: {_im_e}", exc_info=True)

            # Create an async queue for events
            event_queue = asyncio.Queue()

            # Set up streaming LLM client
            streaming_client = SimpleLLMClient()
            streaming_client.set_event_queue(event_queue)
            # Set token usage callback for tracking
            from app.services.token_usage_service import queue_token_usage
            streaming_client.set_token_usage_callback(queue_token_usage)

            # Create system message
            user_now = _resolve_prompt_datetime_for_user(db, current_user.id)
            soul_content = load_soul_for_prompt(db)
            system_message = ChatMessage(
                role="system",
                content=get_system_prompt(ASSISTANT_NAME, current_user.email, user_now=user_now, soul_content=soul_content)
            )

            # INTENT CLASSIFICATION for lazy context injection
            # Extract text from user message (content may be a list for multimodal messages with images)
            _raw_content = next((m.content for m in reversed(request.messages) if m.role == "user"), "") if request.messages else ""
            last_user_message = _extract_text_content(_raw_content)
            tool_classifier = get_tool_intent_classifier()
            context_router = get_context_router()
            # Use conversation-aware classification to preserve tool context across turns
            session_id = request.conversation_id or str(current_user.id)
            user_intent, tool_categories = tool_classifier.classify_with_context(last_user_message, session_id)

            # Screen-aware tool loading: auto-include tools for the user's current screen
            _screen_to_categories = {
                'Fitness': ['fitness'], 'Learning': ['learning', 'web'],
                'Calendar': ['time'], 'Notes': ['notes'], 'Health': ['health', 'fitness'],
                'Inbox': ['inbox'], 'Recipes': ['recipes', 'fitness'],
            }
            if request.current_screen and request.current_screen in _screen_to_categories:
                screen_cats = _screen_to_categories[request.current_screen]
                tool_categories = list(set(tool_categories + screen_cats))
                logger.info(f"📱 Screen-aware: added {screen_cats} for screen={request.current_screen}")

            # P3: on an inbox-load turn (or a follow-up still inside the review
            # window), force the notifications category so clear_inbox_items is
            # actually available — the injected digest tells Sara to call it.
            _inbox_conv_key = request.conversation_id or str(current_user.id)
            if (request.include_inbox or _in_inbox_review(_inbox_conv_key)) and 'notifications' not in tool_categories:
                tool_categories = list(set(tool_categories + ['notifications']))
                logger.info("📥 include_inbox/review: forced 'notifications' category")

            # Multi-intent detection: for long messages with conjunctions, merge tool categories
            _conjunction_words = {'and', 'also', 'then', 'plus', 'as well as', 'along with'}
            if len(last_user_message.split()) > 10 and any(w in last_user_message.lower() for w in _conjunction_words):
                multi_intents = tool_classifier.classify_multi(last_user_message, max_intents=3)
                if len(multi_intents) > 1:
                    extra_cats = []
                    for mi_intent, mi_score in multi_intents:
                        if mi_intent != user_intent:
                            extra_cats.extend(tool_classifier.INTENT_TO_TOOL_CATEGORIES.get(mi_intent, []))
                    if extra_cats:
                        tool_categories = list(set(tool_categories + extra_cats))
                        logger.info(f"🔀 Multi-intent detected: {[i for i, _ in multi_intents]}, merged categories: {tool_categories}")
            turn_count = len(request.messages)

            # MULTI-STEP TASK DETECTION
            # If the user's message requires orchestrated tool chaining, run the task planner
            # instead of the normal chat flow. This handles "check X, then do Y with the result".
            try:
                from app.services.multi_step_detector import detect_multi_step
                multi_step_plan = detect_multi_step(last_user_message)
                if multi_step_plan.is_multi_step and multi_step_plan.confidence >= 0.5:
                    logger.info(
                        f"🔗 Multi-step detected ({len(multi_step_plan.steps)} steps, "
                        f"confidence={multi_step_plan.confidence:.2f}): {last_user_message[:80]}"
                    )
                    # Stream acknowledgment
                    ack = f"I'll handle this in {len(multi_step_plan.steps)} steps. Working on it now..."
                    yield f"data: {json.dumps({'type': 'text_chunk', 'data': {'content': ack}})}\n\n"

                    # Execute the plan
                    from app.services.task_planner import execute_plan

                    async def _on_step_progress(step_idx, status, msg):
                        pass  # Progress embedded in final summary

                    plan_result = await execute_plan(
                        plan=multi_step_plan,
                        user_id=str(current_user.id),
                        on_progress=_on_step_progress,
                    )

                    # Stream final result
                    summary = plan_result.get("summary", "Task completed.")
                    full_response = f"{ack}\n\n{summary}"
                    yield f"data: {json.dumps({'type': 'text_chunk', 'data': {'content': summary}})}\n\n"
                    yield f"data: {json.dumps({'type': 'final_response', 'data': {'content': full_response, 'citations': [], 'timestamp': datetime.now(timezone.utc).isoformat(), 'conversation_id': request.conversation_id}})}\n\n"
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"

                    # Store as episode
                    try:
                        await intelligent_memory_service.store_episode(
                            user_id=str(current_user.id), role="assistant",
                            content=full_response, conversation_id=request.conversation_id,
                            source="chat", memory_type="multi_step_task",
                        )
                    except Exception:
                        pass
                    return
            except ImportError:
                pass  # Module not available
            except Exception as e:
                logger.debug(f"Multi-step detection failed (non-critical): {e}")

            # WORK MODE DETECTION
            # Work mode provides lean, task-focused context (no daily brief/body state unless asked)
            is_work_mode = False

            if request.source == "workspace":
                # Canvas/workspace source is always work mode
                is_work_mode = True
                logger.info("💼 Work mode active (workspace source)")
            else:
                # Check for trigger phrase
                if _is_canvas_trigger(last_user_message):
                    _set_canvas_mode(str(current_user.id), True)
                    is_work_mode = True
                    logger.info(f"💼 Work mode triggered by phrase: '{last_user_message[:50]}...'")
                else:
                    # Check Redis flag (persists for 1 hour)
                    is_work_mode = _get_canvas_mode(str(current_user.id))
                    if is_work_mode:
                        logger.info("💼 Work mode active (Redis flag)")

            context_decision = context_router.decide(
                intent=user_intent,
                message=last_user_message,
                turn_count=turn_count,
                in_work_mode=is_work_mode
            )
            logger.info(f"🎯 Intent={user_intent}, {context_decision.reason}")

            # IMPLICIT FEEDBACK DETECTION: Detect satisfaction/correction signals from user message
            implicit_feedback = None
            previous_assistant_response = None
            injected_lesson_ids = []
            try:
                if request.messages and len(request.messages) >= 2:
                    # Find previous assistant response
                    for m in reversed(request.messages[:-1]):
                        if m.role == "assistant":
                            previous_assistant_response = _extract_text_content(m.content)
                            break
                    if previous_assistant_response:
                        from app.services.implicit_feedback_detector import analyze_message_for_feedback
                        implicit_feedback = await analyze_message_for_feedback(
                            message=last_user_message,
                            previous_response=previous_assistant_response,
                        )
                        if implicit_feedback and implicit_feedback.is_actionable():
                            logger.info(
                                f"Implicit feedback: {implicit_feedback.signal_type.value} "
                                f"({implicit_feedback.strength.value}, confidence={implicit_feedback.confidence:.2f}) "
                                f"trigger='{implicit_feedback.trigger_phrase}'"
                            )

                            # H7.4 (Brain Alignment): a style/tone correction
                            # becomes a durable style rule (auto-approvable) so
                            # David doesn't have to correct the same thing twice.
                            try:
                                from app.services.persona_evolution import record_style_correction
                                _rule = record_style_correction(db, last_user_message)
                                if _rule:
                                    logger.info(f"🎭 Recorded style correction: {_rule}")
                            except Exception as _e:
                                logger.debug(f"style correction record skipped: {_e}")

                            # Flag related PKG facts for review on negative feedback
                            if implicit_feedback.signal_type.value == "negative":
                                try:
                                    from app.services.personal_knowledge_graph import PersonalKnowledgeGraph
                                    pkg = PersonalKnowledgeGraph()
                                    # Search PKG for facts related to the correction context
                                    related = pkg.query_semantic(
                                        last_user_message, limit=3
                                    ) if hasattr(pkg, 'query_semantic') else []
                                    for fact in related:
                                        if fact.get("similarity", 0) > 0.5:
                                            pkg_id = fact.get("pkg_id")
                                            if pkg_id and hasattr(pkg, 'driver') and pkg.driver:
                                                with pkg.driver.session() as neo_session:
                                                    neo_session.run("""
                                                        MATCH (n {pkg_id: $pkg_id})
                                                        SET n.needs_review = true,
                                                            n.review_reason = 'user_correction',
                                                            n.review_evidence = $evidence,
                                                            n.review_flagged_at = datetime()
                                                    """, pkg_id=pkg_id, evidence=last_user_message[:500])
                                                logger.info(f"[PKG] Flagged fact {pkg_id} for review after user correction")
                                except Exception as pkg_e:
                                    logger.debug(f"PKG review flagging failed (non-critical): {pkg_e}")
            except Exception as e:
                logger.debug(f"Implicit feedback detection failed (non-critical): {e}")

            # ── CONTEXT ASSEMBLY (the kernel path — the only assembly, since 2026-07-31) ──
            # Item 1.3 full closure (2026-07-31): the ~600-line legacy assembly
            # (13 parallel fetchers, a ContextBudget merge, and a "compare old
            # vs new" side-by-side log) is deleted. It was already 100%
            # discarded work under SINGULAR_CONTEXT — its entire output got
            # overwritten by this same kernel render every single turn — kept
            # alive this long only for its two real side effects: daily_
            # brief's update_moment write (kept below, now unconditional) and
            # lessons' effectiveness-feedback recording (ported into
            # get_extended_signals' "lessons"/"lesson_ids" signal — see
            # context_snapshot.py). SINGULAR_CONTEXT has been the stable, sole
            # live path all session; write-freeze says that fallback is
            # deleted, not deferred. The flag stays a real kill-switch below
            # (off ⇒ chat proceeds with no injected context, a degraded-but-
            # safe fallback, not a crash) rather than hardcoded away entirely.
            _uid = str(current_user.id)

            workspace_ctx = None
            if request.workspace_context:
                wc = request.workspace_context
                wc_parts = []
                if wc.get('active_scene'):
                    wc_parts.append(f"David is in the '{wc['active_scene']}' workspace layout.")
                open_wins = wc.get('open_windows', [])
                if open_wins:
                    win_list = ', '.join(f"{w.get('title', '')} ({w.get('type', '')})" for w in open_wins)
                    wc_parts.append(f"Open windows: {win_list}")
                if wc_parts:
                    workspace_ctx = "\n\n[Workspace Context]\n" + "\n".join(wc_parts)

            if DAILY_BRIEF_AVAILABLE:
                try:
                    await asyncio.wait_for(
                        daily_brief_service.update_moment(
                            user_id=current_user.id, current_message=last_user_message,
                            conversation_id=request.conversation_id, db=db
                        ), timeout=2.0
                    )
                except Exception:
                    pass

            combined_context = None
            from app.core.feature_flags import Flag as _CtxFlag, is_enabled as _ctx_flag_enabled
            if _ctx_flag_enabled(_CtxFlag.SINGULAR_CONTEXT):
                try:
                    from app.services.context_snapshot import (
                        get_context_snapshot_cached, get_extended_signals, render_engaged_context,
                    )
                    from app.services.memory_recall import recall as _memory_recall, ALL_KINDS as _ALL_RECALL_KINDS
                    from app.services.intent_graph_projection import get_intent_graph
                    import asyncio as _kctx_asyncio
                    import time as _kctx_time

                    async def _sync_db_trio():
                        _t0 = _kctx_time.monotonic()
                        ctx = await get_context_snapshot_cached(db, str(current_user.id))
                        _t1 = _kctx_time.monotonic()
                        intents = get_intent_graph(db, str(current_user.id))["total"]
                        _t2 = _kctx_time.monotonic()
                        ext = await get_extended_signals(
                            db, str(current_user.id), last_user_text or "", domain_hint=user_intent,
                        )
                        _t3 = _kctx_time.monotonic()
                        logger.info(
                            f"⏱️ [kernel-context-timing] context_snapshot={_t1-_t0:.2f}s "
                            f"intent_graph={_t2-_t1:.2f}s extended_signals={_t3-_t2:.2f}s "
                            f"sync_trio_total={_t3-_t0:.2f}s"
                        )
                        return ctx, intents, ext

                    # context_snapshot/intent_graph/extended_signals all take
                    # the same sync `db: Session` and stay sequential relative
                    # to each other (concurrent use of one SQLAlchemy sync
                    # Session across coroutines isn't safe); memory_recall
                    # opens its own sessions, so it runs concurrently with
                    # that trio instead of after it.
                    _kctx_t0 = _kctx_time.monotonic()
                    (_new_context, _new_open_intents, _extended), _new_recalled = await _kctx_asyncio.gather(
                        _sync_db_trio(),
                        _memory_recall(
                            user_id=str(current_user.id), query=last_user_text or "", k=5,
                            # "fact" excluded: extended_signals' _pkg() already
                            # does a dedicated fact-kind lookup (kept separate
                            # since recall_traces' shared top-5 cap could
                            # otherwise crowd facts out) — this avoided a
                            # confirmed, measured duplicate embedding call.
                            kinds=[k for k in _ALL_RECALL_KINDS if k != "fact"],
                        ),
                    )
                    logger.info(
                        f"⏱️ [kernel-context-timing] sync_trio || memory_recall, "
                        f"combined_wall_clock={_kctx_time.monotonic()-_kctx_t0:.2f}s"
                    )
                    combined_context = render_engaged_context(
                        _new_context, _new_open_intents, _new_recalled.get("traces") or [], extended=_extended,
                        workspace_ctx=workspace_ctx,
                    )
                    injected_lesson_ids = _extended.get("lesson_ids") or []
                    try:
                        from app.services.context_diet_usage import record_clean_turn
                        record_clean_turn(str(current_user.id))
                    except Exception:
                        pass
                except Exception as _kctx_err:
                    logger.warning(f"[kernel-context] assembly failed (non-critical, chat continues without it): {_kctx_err}")
                    combined_context = None

            if combined_context:
                system_message = ChatMessage(
                    role="system",
                    content=system_message.content + "\n\n" + combined_context
                )
                logger.info(f"📝 Context injected: {len(combined_context)} chars (kernel assembly)")
            _mark_stage("context_assembled")

            # H3 (Brain Alignment): one-shot correction encoding. If David just
            # stated a durable schedule fact ("I leave at 7", "gym's at 1"),
            # encode it as a stated life_fact *before* the reply and instruct the
            # reply to confirm the durable fact in-voice.
            try:
                from app.services.life_facts import detect_and_apply_correction, confirmation_line
                from app.db.session import get_async_session_factory
                async with get_async_session_factory()() as _lf_db:
                    _corrected = await detect_and_apply_correction(
                        _lf_db, str(current_user.id), last_user_message
                    )
                    await _lf_db.commit()
                if _corrected:
                    lf_ctx = (
                        "\n\n## Durable fact just recorded\n"
                        f"David stated a fixed part of his schedule: {_corrected['label']} "
                        f"at {_corrected['friendly']}. This is now a permanent fact you know. "
                        f"Acknowledge it briefly and naturally (e.g. \"{confirmation_line(_corrected)}\"). "
                        "Never ask him to repeat it and never schedule anything into that window."
                    )
                    system_message = ChatMessage(role="system", content=system_message.content + lf_ctx)
                    logger.info(f"🧠 Encoded stated life_fact: {_corrected['predicate']}={_corrected['value_text']}")
            except Exception as e:
                logger.debug(f"life_fact correction detection skipped: {e}")

            # Arc 5.2: verification-loop retire half — same shape as the
            # life_fact correction check above (cheap no-op on the
            # overwhelming majority of messages; only does real work when
            # a verification question was actually delivered in the last
            # 3 days and its fact is still unresolved).
            try:
                from app.services.verification_loop import check_and_apply_verification_answer
                from app.db.session import get_async_session_factory
                async with get_async_session_factory()() as _vl_db:
                    await check_and_apply_verification_answer(
                        _vl_db, str(current_user.id), last_user_message
                    )
            except Exception as e:
                logger.debug(f"verification-loop answer check skipped: {e}")

            # H5 (Brain Alignment): recency floor + repeat detection. The last
            # ~2h of turns are always present (so pronouns and just-tried actions
            # resolve), and a near-duplicate of a recent question is flagged so
            # Sara acknowledges the repeat instead of re-answering verbatim.
            try:
                from app.services.recency_buffer import (
                    build_recency_floor, detect_repeat_question, repeat_note,
                )
                from app.db.session import get_async_session_factory
                async with get_async_session_factory()() as _rb_db:
                    _recency = await build_recency_floor(_rb_db, str(current_user.id))
                    _repeat = await detect_repeat_question(
                        _rb_db, str(current_user.id), last_user_message,
                        conversation_id=request.conversation_id,
                    )
                extra = []
                if _recency:
                    extra.append(_recency)
                if _repeat:
                    extra.append(repeat_note(_repeat))
                    logger.info(f"🔁 Repeat question detected ({_repeat['minutes_ago']}m ago, sim={_repeat['similarity']})")
                if extra:
                    system_message = ChatMessage(
                        role="system", content=system_message.content + "\n\n" + "\n\n".join(extra)
                    )
            except Exception as e:
                logger.debug(f"recency/repeat injection skipped: {e}")

            # H6 (Brain Alignment): internal clock + interoception header. One
            # generated, single-sourced line so Sara never infers the time,
            # David's availability, her own emotional state, or her notification
            # budget from evidence.
            try:
                from app.services.interoception import build_interoception_header
                _header = await build_interoception_header(str(current_user.id))
                if _header:
                    system_message = ChatMessage(
                        role="system", content=_header + "\n\n" + system_message.content
                    )
            except Exception as e:
                logger.debug(f"interoception header skipped: {e}")

            # Phase 10B/10C: David's known routine + pinned standing context, so
            # chat reasons from his schedule and the things he told Sara to remember.
            try:
                _ctx_bits = []
                # Directives first — they're behavioral law (Phase 12B).
                from app.services.directives import get_directives_for_context
                _dir = await get_directives_for_context(str(current_user.id))
                if _dir:
                    _ctx_bits.append(_dir)
                from app.services.life_facts import get_life_facts_summary
                _lf = await get_life_facts_summary(str(current_user.id))
                if _lf:
                    _ctx_bits.append(_lf)
                from app.services.scratchpad import get_scratchpad_for_context
                _sp = await get_scratchpad_for_context(str(current_user.id))
                if _sp:
                    _ctx_bits.append(_sp)
                # Phase 12K: notifications Sara sent that David hasn't acked, so a reply
                # referencing them lands with context and can be acknowledged in one shot.
                # Skipped on include_inbox turns (P3) — the full inbox digest below
                # supersedes this narrower notification-only slice.
                if not request.include_inbox:
                    from app.services.notification_ack import get_unacked_for_context
                    _unacked = await get_unacked_for_context(str(current_user.id))
                    if _unacked:
                        _ctx_bits.append(_unacked)
                if _ctx_bits:
                    system_message = ChatMessage(
                        role="system",
                        content=system_message.content + "\n\n" + "\n\n".join(_ctx_bits))
            except Exception as e:
                logger.debug(f"life-facts/scratchpad injection skipped: {e}")

            # P3: David pressed the inbox button — deterministically inject the FULL
            # unified inbox (the exact items the badge counts), NOT a question Sara
            # must answer from a partial slice. Uses the sync `db` Session in scope.
            # Re-inject on follow-up turns within the review window so the item ids
            # (needed by clear_inbox_items) survive until he's finished addressing them.
            _inbox_conv_key = request.conversation_id or str(current_user.id)
            if request.include_inbox or _in_inbox_review(_inbox_conv_key):
                try:
                    from app.routes.assistant_inbox import (
                        build_unified_inbox, format_inbox_for_chat,
                    )
                    _inbox_data = build_unified_inbox(db, str(current_user.id))
                    _inbox_digest = format_inbox_for_chat(_inbox_data)
                    if _inbox_digest:
                        system_message = ChatMessage(
                            role="system",
                            content=system_message.content + "\n\n" + _inbox_digest)
                        logger.info(
                            f"📥 Injected unified inbox digest "
                            f"({_inbox_data['counts']['needs_you']} needs-you, "
                            f"{_inbox_data['counts']['fyi_unread']} fyi-unread)")
                    # Keep the review window open while anything is still waiting;
                    # close it the moment the badge is clear so we stop injecting.
                    if _inbox_data["counts"]["badge"] > 0:
                        _set_inbox_review(_inbox_conv_key, True)
                    else:
                        _set_inbox_review(_inbox_conv_key, False)
                except Exception as e:
                    logger.warning(f"⚠️ Inbox digest injection failed (non-critical): {e}")

            # CONTENT INBOX: Inject inbox item content when discussing a shared item
            if request.inbox_item_id:
                try:
                    inbox_row = db.execute(text("""
                        SELECT id, title, content_type, original_url, extracted_text, meta
                        FROM shared_content
                        WHERE id = :id AND user_id = :uid
                    """), {"id": request.inbox_item_id, "uid": current_user.id}).fetchone()
                    if inbox_row and inbox_row.extracted_text:
                        truncated = inbox_row.extracted_text[:8000]
                        inbox_ctx = f"\n\n## Content David Wants to Discuss\n"
                        inbox_ctx += f"**Title:** {inbox_row.title}\n"
                        inbox_ctx += f"**Source:** {inbox_row.original_url or 'shared file'} ({inbox_row.content_type})\n\n"
                        inbox_ctx += truncated
                        current_content = system_message.content
                        system_message = ChatMessage(role="system", content=current_content + inbox_ctx)
                        # Mark as discussed
                        db.execute(text("UPDATE shared_content SET discussed = TRUE WHERE id = :id"),
                                   {"id": request.inbox_item_id})
                        db.commit()
                        logger.info(f"📥 Injected inbox item context: {inbox_row.title} ({len(truncated)} chars)")
                except Exception as e:
                    logger.warning(f"⚠️ Inbox context injection failed (non-critical): {e}")

            # ATTENTION ITEM CONTEXT (SARA_UNLEASHED Phase T.4): a reply to a
            # proactive item carries the item's id so the conversation
            # continues instead of restarting cold. run_action's "chat" kind
            # already marks the item engaged the moment the button is
            # tapped — this is belt-and-suspenders for any caller that skips
            # that endpoint, plus the actual context injection.
            if request.attention_item_id:
                try:
                    attn_row = db.execute(text("""
                        SELECT title, body, category FROM outbox_item
                        WHERE id = CAST(:id AS uuid) AND user_id = :uid
                    """), {"id": request.attention_item_id, "uid": current_user.id}).fetchone()
                    if attn_row:
                        attn_ctx = (
                            f"\n\n## The proactive item this reply continues\n"
                            f"**{attn_row.title}** ({attn_row.category})\n{attn_row.body or ''}"
                        )
                        current_content = system_message.content
                        system_message = ChatMessage(role="system", content=current_content + attn_ctx)
                        from app.services.autonomy.attention_queue import attention_queue
                        await attention_queue.mark_engaged(db=db, item_id=request.attention_item_id, user_id=str(current_user.id))
                        db.commit()
                        logger.info(f"📥 Injected attention item context: {attn_row.title}")
                except Exception as e:
                    logger.warning(f"⚠️ Attention item context injection failed (non-critical): {e}")

            # NOTE CONTEXT: Inject note content when discussing a note/report from iOS.
            if request.note_id:
                try:
                    note_row = db.execute(text("""
                        SELECT id, title, content
                        FROM note
                        WHERE id = :id AND user_id = :uid
                        LIMIT 1
                    """), {"id": request.note_id, "uid": current_user.id}).fetchone()
                    if note_row and note_row.content:
                        truncated_note = note_row.content[:12000]
                        note_ctx = "\n\n## Note David Wants to Discuss\n"
                        note_ctx += f"**Title:** {note_row.title}\n\n"
                        note_ctx += truncated_note
                        current_content = system_message.content
                        system_message = ChatMessage(role="system", content=current_content + note_ctx)
                        logger.info(f"📝 Injected note context: {note_row.title} ({len(truncated_note)} chars)")
                except Exception as e:
                    logger.warning(f"⚠️ Note context injection failed (non-critical): {e}")

            # SESSION GAP DETECTION: Detect gaps and summarize for day layer
            try:
                # Check if there's been a 45+ minute gap since last message
                has_gap, last_message_time = await asyncio.wait_for(
                    llm_client.detect_session_gap(current_user.id, db),
                    timeout=1.0
                )

                if has_gap and last_message_time:
                    # Session gap detected - summarize the previous session.
                    # This closes out the PAST session (redis/day-layer/journal
                    # writes) — nothing in *this* turn's context depends on its
                    # result, so it must never block the chat hot path. It used
                    # to be awaited inline with a 4s timeout that routinely burned
                    # the full 4s only to be discarded (Arc 0.6). Fully detached
                    # now, with its own DB session (the request's `db` may already
                    # be closed by the time this background task actually runs).
                    logger.info(f"⏱️ Session gap detected (45+ min since last message) — closing previous session in background")

                    session_end = last_message_time
                    session_start = session_end - timedelta(hours=2)
                    _conversation_id_for_close = request.conversation_id or "unknown"

                    async def _close_previous_session(uid=current_user.id, s_start=session_start, s_end=session_end, conv_id=_conversation_id_for_close):
                        summary = await llm_client.summarize_session(uid, s_start, s_end)
                        if not summary:
                            return
                        await llm_client.store_session_summary(uid, summary, s_end)
                        if DAILY_BRIEF_AVAILABLE:
                            await daily_brief_service.append_to_day_layer(uid, summary, s_end)
                            logger.info("📅 Appended session summary to day layer")
                        close_db = SessionLocal()
                        try:
                            await sara_journal.write_conversation_close_entry(
                                db=close_db,
                                user_id=uid,
                                conversation_id=conv_id,
                                conversation_summary=summary,
                                user_mood=None,  # Could infer from summary
                                body_state=None
                            )
                            logger.info("📔 Wrote conversation close journal entry")
                        finally:
                            close_db.close()

                    def _log_session_close_failure(task: asyncio.Task):
                        try:
                            exc = task.exception()
                        except asyncio.CancelledError:
                            return
                        if exc:
                            logger.warning(f"⚠️ Background session close failed: {exc}")

                    _close_task = asyncio.create_task(_close_previous_session())
                    _close_task.add_done_callback(_log_session_close_failure)

                    # Build re-entry context from unified snapshot changes + agent memory + journal + PKG
                    try:
                        # Normalize both sides to aware-UTC before subtracting.
                        # local_now() is aware-ET; last_message_time (episode.created_at)
                        # comes back naive from the DB, so a raw subtraction raised
                        # "can't subtract offset-naive and offset-aware datetimes" every
                        # time — this feature had 0 successes all-time until this fix.
                        _last_msg = last_message_time
                        if _last_msg.tzinfo is None:
                            _last_msg = _last_msg.replace(tzinfo=timezone.utc)
                        hours_away = (datetime.now(timezone.utc) - _last_msg).total_seconds() / 3600
                        reentry_context = f"\n\n## Re-Entry Context\nDavid just returned after {hours_away:.1f} hours away.\n"

                        # Read changes_since_last_chat from unified context snapshot
                        try:
                            from app.services.context_writer import clear_changes as _clear_ctx_changes
                            recent_changes = await asyncio.wait_for(
                                _clear_ctx_changes(str(current_user.id)),
                                timeout=1.0
                            )
                            if recent_changes:
                                reentry_context += "\n**What happened while David was away:**\n"
                                for change in recent_changes[-10:]:  # Last 10 changes
                                    reentry_context += f"- {change}\n"
                        except asyncio.TimeoutError:
                            logger.warning("⚠️ Re-entry changes fetch timed out (skipping)")
                        except Exception:
                            pass

                        # Get recent agent actions while David was away
                        try:
                            from app.services.agent_memory import get_recent_actions
                            from sqlalchemy.ext.asyncio import AsyncSession as _ASession
                            # agent_memory needs async session — wrap sync db
                            agent_actions = []
                            # Use a simplified approach: query directly with sync db
                            action_rows = db.execute(text("""
                                SELECT source, context_summary, run_at
                                FROM agent_run_log
                                WHERE user_id = :uid
                                  AND run_at >= :since
                                  AND context_summary IS NOT NULL
                                ORDER BY run_at DESC LIMIT 5
                            """), {
                                "uid": current_user.id,
                                "since": local_now() - timedelta(hours=max(hours_away, 1)),
                            }).fetchall()
                            if action_rows:
                                reentry_context += "\n**Agent activity while you were away:**\n"
                                for ar in action_rows:
                                    reentry_context += f"- [{ar.source}] {(ar.context_summary or '')[:120]}\n"
                        except Exception:
                            pass

                        # Get recent journal entries for Sara's recent thoughts
                        from app.services.sara_journal_service import sara_journal
                        recent_journal_entries = db.execute(text("""
                            SELECT content, emotional_state, entry_type, created_at
                            FROM sara_journal
                            WHERE user_id = :uid
                            AND created_at >= :since
                            ORDER BY created_at DESC
                            LIMIT 3
                        """), {
                            "uid": current_user.id,
                            "since": local_now() - timedelta(hours=max(hours_away, 1))
                        }).fetchall()

                        if recent_journal_entries:
                            reentry_context += "\nYour recent thoughts while David was away:\n"
                            for entry in recent_journal_entries:
                                content_preview = (entry.content or "")[:150]
                                reentry_context += f"- [{entry.entry_type}] {content_preview}\n"

                        # Get brief PKG summary for rapport
                        try:
                            from app.services.memory_recall import recall_facts_prose
                            pkg_brief = await recall_facts_prose(query="", k=5, user_id=str(current_user.id))
                            if pkg_brief:
                                reentry_context += f"\nRelevant knowledge about David:\n{pkg_brief}\n"
                        except Exception:
                            pass

                        current_content = system_message.content
                        system_message = ChatMessage(role="system", content=current_content + reentry_context)
                        logger.info(f"🔄 Injected re-entry context ({len(reentry_context)} chars, {hours_away:.1f}h away)")
                    except Exception as re_e:
                        logger.warning(f"⚠️ Re-entry context injection failed (non-critical): {re_e}")

            except asyncio.TimeoutError:
                logger.warning("⚠️ Session gap detection timed out (skipping)")
            except Exception as e:
                try:
                    db.rollback()
                except Exception:
                    pass
                logger.warning(f"⚠️ Session gap detection failed (non-critical): {e}")

            # Guard against failed transaction state from optional context injections.
            try:
                db.execute(text("SELECT 1"))
            except Exception as tx_err:
                logger.warning(f"⚠️ DB transaction reset before chat history retrieval: {tx_err}")
                try:
                    db.rollback()
                except Exception:
                    pass

            # Retrieve conversation history if conversation_id provided
            conversation_history = []
            should_load_db_history = bool(request.conversation_id and len(request.messages) <= 2)
            if request.conversation_id and not should_load_db_history:
                logger.info(
                    f"⏭️ Skipping DB history load (client supplied {len(request.messages)} messages)"
                )

            if should_load_db_history:
                logger.info(f"📜 Retrieving fallback conversation history for: {request.conversation_id}")
                try:
                    # Get recent episodes from this conversation (descending, then re-order ascending)
                    episodes = db.query(Episode).filter(
                        Episode.conversation_id == request.conversation_id,
                        Episode.user_id == current_user.id,
                        Episode.role.in_(["user", "assistant"])
                    ).order_by(Episode.created_at.desc()).limit(20).all()

                    # Convert episodes to ChatMessage format
                    for episode in reversed(episodes):
                        conversation_history.append(ChatMessage(
                            role=episode.role,
                            content=episode.content
                        ))

                    logger.info(f"✅ Retrieved {len(conversation_history)} messages from conversation history")
                except Exception as e:
                    logger.error(f"❌ Failed to retrieve conversation history: {e}")

            # Build full message list: system + deduplicated(history + request)
            merged_request_messages = request.messages
            overlap = _compute_message_overlap(conversation_history, request.messages)
            if overlap > 0:
                merged_request_messages = request.messages[overlap:]
                logger.info(
                    f"🔁 Deduplicated {overlap} overlapping turns between DB history and request payload"
                )

            all_messages = [system_message] + conversation_history + merged_request_messages
            logger.info(
                f"💬 Total messages: {len(all_messages)} "
                f"(1 system + {len(conversation_history)} history + {len(merged_request_messages)} new)"
            )

            # Context assembly is done with the request-scoped session. End its
            # transaction now: the LLM tool loop below can run for many minutes,
            # and an open transaction gets the connection killed by Postgres's
            # idle_in_transaction_session_timeout (the stream then dies with no
            # final response). Any later db use starts a fresh transaction.
            try:
                db.commit()
            except Exception as _tx_end_err:
                logger.warning(f"⚠️ Pre-LLM transaction end failed (non-critical): {_tx_end_err}")
                try:
                    db.rollback()
                except Exception:
                    pass

            # Start the LLM processing in a background task
            async def process_chat():
                try:
                    # WORK MODE-AWARE TOOL LOADING
                    # Work mode always includes workspace and maps tools for canvas control

                    if is_work_mode:
                        # Work mode: always include workspace + maps + vm_agents tools regardless of intent
                        effective_categories = list(tool_categories) if tool_categories else []
                        capability_core_categories = ["devices", "vm_agents", "personal_knowledge", "inbox", "lists"]
                        # Always add workspace tools for canvas control
                        if 'workspace' not in effective_categories:
                            effective_categories.append('workspace')
                        if 'maps' not in effective_categories:
                            effective_categories.append('maps')
                        for category in capability_core_categories:
                            if category not in effective_categories:
                                effective_categories.append(category)
                        tools = tool_registry.get_tools_by_categories(effective_categories)
                        logger.info(f"💼 Work mode: Loaded {len(tools)} tools from categories: {effective_categories}")
                    elif tool_categories:
                        # Standard chat uses intent-based tool loading from classify_with_context
                        from app.core.feature_flags import Flag as _PFlag, is_enabled as _presence_flag_enabled
                        if _presence_flag_enabled(_PFlag.PRESENCE_TOOL_DIET):
                            # Arc 3.4 (SARA_ALIVE_BUILD_PLAN): the "always add"
                            # 5-category core (25 tool defs, every turn,
                            # regardless of intent) traded almost entirely on
                            # classification already covering the same ground
                            # (DEVICES/INBOX/PERSONAL_KNOWLEDGE are all their
                            # own intents — see INTENT_TO_TOOL_CATEGORIES).
                            # Replaced with a hand-picked, individually-named
                            # core: quick recall/notes/lists/schedule plus
                            # dispatch_and_monitor as the escape hatch for
                            # anything deeper (already kernel.focused_turn()
                            # underneath). Intent-classified categories are
                            # unchanged — this only shrinks the padding.
                            _diet_tools = tool_registry.get_tools_by_names(_PRESENCE_CORE_TOOL_NAMES)
                            _diet_tools += tool_registry.get_tools_by_categories(list(tool_categories))
                            _seen_names = set()
                            tools = []
                            for _t in _diet_tools:
                                _tn = _t.get("function", {}).get("name")
                                if _tn and _tn not in _seen_names:
                                    _seen_names.add(_tn)
                                    tools.append(_t)
                            logger.info(f"🍽️ Intent={user_intent}: Presence diet — {len(tools)} tools ({len(_PRESENCE_CORE_TOOL_NAMES)} core + categories {list(tool_categories)})")
                        else:
                            # Also ensure awareness/action core categories are always available
                            effective_categories = list(tool_categories)
                            capability_core_categories = ["devices", "vm_agents", "personal_knowledge", "inbox", "lists"]
                            for category in capability_core_categories:
                                if category not in effective_categories:
                                    effective_categories.append(category)
                            tools = tool_registry.get_tools_by_categories(effective_categories)
                            logger.info(f"🔧 Intent={user_intent}: Loaded {len(tools)} tools from categories: {effective_categories}")
                    else:
                        # Conservative capability fallback when intent routing fails.
                        fallback_categories = ['memory', 'notes', 'time', 'devices', 'vm_agents', 'personal_knowledge', 'inbox']
                        tools = tool_registry.get_tools_by_categories(fallback_categories)
                        logger.info(f"🔧 Intent={user_intent}: Capability fallback ({len(tools)} tools)")

                    # Process chat with loaded tools
                    _mark_stage("tools_loaded")
                    logger.info(f"⏳ Starting chat_with_tools... ({len(tools)} tools)")
                    _mark_stage("llm_dispatched")
                    response_content = await streaming_client.chat_with_tools(
                        all_messages, tools, current_user.id, request.conversation_id,
                        model=request.model, ephemeral=request.ephemeral or False
                    )
                    _mark_stage("turn_complete")
                    logger.info(f"✅ chat_with_tools completed, response length: {len(response_content)}")
                    try:
                        _s = _stage_marks
                        _t0 = _s.get("request_received")
                        if _t0:
                            _line = " ".join(
                                f"{k}=+{(_s[k]-_t0):.2f}s" for k in
                                ("context_assembled", "tools_loaded", "llm_dispatched", "turn_complete")
                                if k in _s
                            )
                            logger.info(f"⏱️ [stage-timing] {_line}")
                    except Exception:
                        pass

                    # Leak guard: raw <tool_call>/<function=...> markup that wasn't
                    # salvaged into a real tool call must never reach the user.
                    _stripped = strip_tool_markup(response_content)
                    if _stripped != response_content:
                        logger.warning("🧹 Stripped tool-call markup from final response")
                        response_content = _stripped or (
                            "I hit a snag executing that — mind asking again?"
                        )

                    # Send final response and done IMMEDIATELY to close the stream
                    final_conv_id = streaming_client.current_conversation_id if hasattr(streaming_client, 'current_conversation_id') else request.conversation_id
                    final_episode_id = streaming_client.current_episode_id if hasattr(streaming_client, 'current_episode_id') else None
                    logger.info(f"🔍 Sending final_response with conversation_id: {final_conv_id}, episode_id: {final_episode_id}")
                    await event_queue.put({
                        "type": "final_response",
                        "data": {
                            "content": response_content,
                            "citations": streaming_client.get_citations(),
                            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                            "conversation_id": final_conv_id,
                            "episode_id": final_episode_id
                        }
                    })
                    logger.info("✅ final_response event queued")

                    # Stamp the cross-device session with the real conversation id.
                    # The pre-stream update skips new conversations (no id yet), so
                    # without this a single-turn chat would not be resumable.
                    if final_conv_id:
                        try:
                            from app.routes.session import update_active_session
                            asyncio.ensure_future(update_active_session(
                                user_id=str(current_user.id),
                                conversation_id=str(final_conv_id),
                                device=getattr(request, 'source', None) or 'unknown',
                                turn_count=len(request.messages),
                            ))
                        except Exception:
                            pass

                    # Emit suggested actions based on tools used and response
                    try:
                        from app.services.action_suggester import suggest as suggest_actions
                        tool_history = getattr(streaming_client, '_tool_history', [])
                        suggestions = suggest_actions(tool_history, response_content or "")
                        if suggestions:
                            await event_queue.put({
                                "type": "suggested_actions",
                                "data": {"actions": suggestions}
                            })
                            logger.info(f"💡 Emitted {len(suggestions)} suggested actions")
                    except Exception as e:
                        logger.debug(f"Suggested actions skipped: {e}")

                    await event_queue.put({"type": "done"})
                    logger.info("✅ done event queued")

                    # Commitment/thread extraction (SARA_UNLEASHED Phase B): fire-and-forget
                    # after every turn. extract_threads() internally rate-limits
                    # (EXTRACTION_COOLDOWN) and requires >=3 user messages, so this is safe
                    # to call unconditionally rather than re-deriving those gates here.
                    try:
                        from app.services.thread_extractor import extract_from_conversation_bg
                        _full_messages = list(request.messages) + (
                            [{"role": "assistant", "content": response_content}] if response_content else []
                        )
                        asyncio.ensure_future(extract_from_conversation_bg(_full_messages, str(current_user.id)))
                    except Exception as e:
                        logger.debug(f"Thread extraction kickoff skipped: {e}")

                    # Send push notification if requested (for background completion)
                    if request.notify_on_complete and response_content:
                        try:
                            from app.services.notification_service import notification_service
                            preview = response_content[:100].replace('\n', ' ')
                            if len(response_content) > 100:
                                preview += '...'
                            await notification_service.send_notification(
                                user_id=str(current_user.id),
                                title="Sara",
                                message=preview,
                                data={
                                    "type": "chat_response",
                                    "conversation_id": final_conv_id or "",
                                },
                            )
                            logger.info("📱 Sent chat completion push notification")
                        except Exception as push_err:
                            logger.warning(f"⚠️ Push notification failed (non-critical): {push_err}")

                    # Note: conversation storage already happened inside chat_with_tools
                    # No additional storage needed here

                    # SELF-LEARNING LOOP: Extract lessons from negative feedback, track lesson effectiveness
                    try:
                        # If negative feedback detected, extract a lesson from the mistake
                        if (implicit_feedback and implicit_feedback.is_actionable()
                                and implicit_feedback.signal_type.value == "negative"):
                            from app.services.lesson_extractor import create_lesson_from_feedback
                            messages_for_extraction = [
                                {"role": m.role, "content": _extract_text_content(m.content)}
                                for m in (request.messages or [])
                            ]
                            lesson = await create_lesson_from_feedback(
                                db=db,
                                feedback=implicit_feedback,
                                messages=messages_for_extraction,
                                previous_response=previous_assistant_response,
                            )
                            if lesson:
                                logger.info(f"Extracted lesson: {lesson.lesson[:80]}... (confidence={lesson.confidence:.2f})")

                        # Record that lessons were injected (for effectiveness tracking)
                        if injected_lesson_ids:
                            from app.services.lesson_injection_service import lesson_injection_service as _lis
                            await _lis.record_lesson_application(
                                db=db,
                                lesson_ids=injected_lesson_ids,
                                conversation_id=final_conv_id or request.conversation_id,
                                message_id=str(final_episode_id) if final_episode_id else None,
                            )
                            logger.info(f"Recorded application of {len(injected_lesson_ids)} lessons")

                        # If positive feedback and lessons were injected, mark them as successful
                        if (implicit_feedback and implicit_feedback.is_actionable()
                                and implicit_feedback.signal_type.value == "positive"
                                and injected_lesson_ids):
                            from app.services.lesson_tracker import lesson_tracker
                            updated = await lesson_tracker.update_pending_applications(
                                db=db,
                                conversation_id=final_conv_id or request.conversation_id,
                                was_successful=True,
                                feedback_signal=implicit_feedback.trigger_phrase,
                            )
                            if updated:
                                logger.info(f"Marked {len(updated)} lessons as successful")

                        # If negative feedback on a conversation with prior lessons, mark them as failed
                        if (implicit_feedback and implicit_feedback.is_actionable()
                                and implicit_feedback.signal_type.value == "negative"
                                and not injected_lesson_ids):
                            # Check if previous conversation had lessons — update those
                            from app.services.lesson_tracker import lesson_tracker
                            updated = await lesson_tracker.update_pending_applications(
                                db=db,
                                conversation_id=final_conv_id or request.conversation_id,
                                was_successful=False,
                                feedback_signal=implicit_feedback.trigger_phrase,
                            )
                            if updated:
                                logger.info(f"Marked {len(updated)} lessons as failed")
                    except Exception as e:
                        logger.debug(f"Self-learning loop failed (non-critical): {e}")

                    # Update Sara's emotional state from this conversation (fire-and-forget)
                    try:
                        asyncio.create_task(_update_emotional_state_from_chat(
                            messages=request.messages,
                            response_content=response_content,
                            user_id=str(current_user.id),
                        ))
                    except Exception:
                        pass

                    # Batch-enrich episode emotions, topics, and scores (fire-and-forget)
                    try:
                        asyncio.create_task(_enrich_episodes_batch(
                            conversation_id=final_conv_id or request.conversation_id,
                            user_id=str(current_user.id),
                        ))
                    except Exception:
                        pass

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
                        # Always emit explicit completion event so clients can re-enable input.
                        yield f"data: {json.dumps(event)}\n\n"
                        break

                    # Format as Server-Sent Event
                    event_data = json.dumps(event)
                    if event.get("type") == "final_response":
                        logger.info(f"🚀 Yielding final_response SSE: {event_data[:200]}")
                    yield f"data: {event_data}\n\n"
                    
                except asyncio.TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"
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

    async def _timed_generate_events():
        """Arc 6.1 three-speed contract: black-box presence latency —
        measured from the outside (request start to the first real
        content chunk actually yielded to the client), not by threading
        a timer through every fast-path/LLM-call branch inside
        generate_events(). This is also the only measurement that
        reflects what David actually experiences."""
        import time as _time
        _start = _time.monotonic()
        _logged = False
        async for _event_str in generate_events():
            if not _logged:
                try:
                    _evt = json.loads(_event_str[len("data: "):].strip())
                    if _evt.get("type") == "text_chunk":
                        _logged = True
                        from app.services.presence_latency import record_first_token_latency
                        _elapsed = _time.monotonic() - _start
                        await record_first_token_latency(_elapsed)
                        _mark_stage("first_token")
                        try:
                            _t0 = _stage_marks.get("request_received")
                            if _t0:
                                _line = " ".join(
                                    f"{k}=+{(_stage_marks[k]-_t0):.2f}s" for k in
                                    ("context_assembled", "tools_loaded", "llm_dispatched", "first_token")
                                    if k in _stage_marks
                                )
                                logger.info(f"⏱️ [stage-timing] {_line}")
                        except Exception:
                            pass
                except Exception:
                    pass
            yield _event_str

    return StreamingResponse(
        _timed_generate_events(),
        media_type="text/event-stream",
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


# Desktop app downloads extracted to app/routes/downloads.py


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
        SELECT id, title, content, folder_id, tags, starred, created_at, updated_at
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
            "tags": row.tags if isinstance(row.tags, list) else (json.loads(row.tags) if row.tags else []),
            "starred": bool(row.starred),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None
        }
        for row in results
    ]


# Memory Management endpoints

# Episode Rating endpoints

# Document API endpoints

# 3D Model API endpoints
ALLOWED_3D_FORMATS = {'stl', 'obj', 'gltf', 'glb'}
MODEL_MIME_TYPES = {
    'stl': 'model/stl',
    'obj': 'model/obj',
    'gltf': 'model/gltf+json',
    'glb': 'model/gltf-binary',
}


# Conversation memory API endpoints

# ==================== EPISODE-BASED CONVERSATION ENDPOINTS ====================

# Knowledge Graph Endpoints
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
            ConversationTurn.created_at >= naive_local_now() - timedelta(days=7)
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
        
        # Reconcile against the canonical body-state projection (SINGULAR_SARA
        # §13 item 3) instead of trusting this endpoint's own live probes in
        # isolation — those probes only check 2 components at *this instant*,
        # while the projection reflects what /api/metrics and /api/sara/brief
        # already agree on. A live probe still runs above so this endpoint
        # keeps working even before any heartbeat has ever recorded a
        # component (canonical component missing -> fall back to the probe).
        body_state_projection = None
        try:
            from app.services.body_state_projection import get_body_state_projection, get_component
            body_state_projection = await get_body_state_projection(str(current_user.id))
            db_component = await get_component("database", str(current_user.id))
            embed_component = await get_component("embeddings", str(current_user.id))
            if db_component is not None:
                db_health = db_component.status.value == "ok"
            if embed_component is not None:
                embedding_health = embed_component.status.value == "ok"
        except Exception as e:
            logger.debug(f"Analytics dashboard body_state reconciliation failed: {e}")

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
            },
            "body_state": body_state_projection.model_dump(mode="json") if body_state_projection else None,
        }
        
    except Exception as e:
        logger.error(f"Analytics dashboard error: {e}")
        raise HTTPException(status_code=500, detail=f"Analytics failed: {str(e)}")

# Settings endpoints
@app.get("/settings/ai")
async def get_ai_settings(current_user: User = Depends(get_current_user)):
    """Get current AI configuration settings"""
    codex_connected = bool(CODEX_OAUTH_ACCESS_TOKEN and CODEX_OAUTH_REFRESH_TOKEN)
    response = {
        "ai_provider": AI_PROVIDER,
        "openai_api_key": "***" if OPENAI_API_KEY and OPENAI_API_KEY != "dummy" else "",
        "anthropic_api_key": "***" if ANTHROPIC_API_KEY else "",
        "openai_base_url": OPENAI_BASE_URL,
        "openai_model": OPENAI_MODEL,
        "openai_notification_model": OPENAI_NOTIFICATION_MODEL,
        "embedding_base_url": EMBEDDING_BASE_URL,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimension": EMBEDDING_DIM,
        # Background processing settings
        "bg_llm_primary_url": BG_LLM_PRIMARY_URL,
        "bg_llm_primary_model": BG_LLM_PRIMARY_MODEL,
        "bg_llm_fallback_url": BG_LLM_FALLBACK_URL,
        "bg_llm_fallback_model": BG_LLM_FALLBACK_MODEL,
        "bg_llm_request_timeout": BG_LLM_REQUEST_TIMEOUT,
        "bg_llm_connect_timeout": BG_LLM_CONNECT_TIMEOUT,
        "bg_llm_num_ctx": BG_LLM_NUM_CTX,
        "codex_oauth_connected": codex_connected,
        "codex_oauth_email": CODEX_OAUTH_EMAIL if codex_connected else "",
        "codex_oauth_expires_at": CODEX_OAUTH_EXPIRES_AT if codex_connected else "",
        "codex_oauth_account_id": CODEX_OAUTH_ACCOUNT_ID if codex_connected else "",
    }

    # Add VM sandbox settings from user preferences
    try:
        from app.models.user_settings import UserSettings as UserSettingsModel
        db = SessionLocal()
        try:
            us = db.query(UserSettingsModel).filter(
                UserSettingsModel.user_id == str(current_user.id)
            ).first()
            vm_prefs = (us.preferences or {}).get("vm_sandbox", {}) if us else {}
            response["vm_sandbox_host"] = vm_prefs.get("host", "10.185.1.176")
            response["vm_sandbox_username"] = vm_prefs.get("username", "sara")
            response["vm_sandbox_ssh_key_path"] = vm_prefs.get("ssh_key_path", "~/.ssh/sara_agent")
        finally:
            db.close()
    except Exception:
        response["vm_sandbox_host"] = "10.185.1.176"
        response["vm_sandbox_username"] = "sara"
        response["vm_sandbox_ssh_key_path"] = "~/.ssh/sara_agent"

    return response

@app.put("/settings/ai")
async def update_ai_settings(
    settings: AISettingsUpdate,
    current_user: User = Depends(get_current_user)
):
    """Update AI configuration settings and hot-reload runtime clients."""
    global AI_PROVIDER, OPENAI_API_KEY, ANTHROPIC_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_NOTIFICATION_MODEL, EMBEDDING_BASE_URL, EMBEDDING_MODEL, EMBEDDING_DIM
    global BG_LLM_PRIMARY_URL, BG_LLM_PRIMARY_MODEL, BG_LLM_FALLBACK_URL, BG_LLM_FALLBACK_MODEL
    global BG_LLM_REQUEST_TIMEOUT, BG_LLM_CONNECT_TIMEOUT, BG_LLM_NUM_CTX

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
        # - URL targets ChatGPT backend API for Codex OAuth
        if (
            u.endswith("/v1")
            or "/openai/" in u
            or "generativelanguage.googleapis.com" in u
            or "chatgpt.com/backend-api" in u
            or u.endswith("/backend-api")
        ):
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

    # Background LLM settings
    if settings.bg_llm_primary_url is not None:
        normalized_url = _normalize_openai(settings.bg_llm_primary_url)
        BG_LLM_PRIMARY_URL = normalized_url
        config.settings.bg_llm_primary_url = normalized_url
        updated_settings["bg_llm_primary_url"] = normalized_url

    if settings.bg_llm_primary_model is not None:
        BG_LLM_PRIMARY_MODEL = settings.bg_llm_primary_model
        config.settings.bg_llm_primary_model = settings.bg_llm_primary_model
        updated_settings["bg_llm_primary_model"] = settings.bg_llm_primary_model

    if settings.bg_llm_fallback_url is not None:
        normalized_url = _normalize_openai(settings.bg_llm_fallback_url)
        BG_LLM_FALLBACK_URL = normalized_url
        config.settings.bg_llm_fallback_url = normalized_url
        updated_settings["bg_llm_fallback_url"] = normalized_url

    if settings.bg_llm_fallback_model is not None:
        BG_LLM_FALLBACK_MODEL = settings.bg_llm_fallback_model
        config.settings.bg_llm_fallback_model = settings.bg_llm_fallback_model
        updated_settings["bg_llm_fallback_model"] = settings.bg_llm_fallback_model

    if settings.bg_llm_request_timeout is not None:
        BG_LLM_REQUEST_TIMEOUT = max(10.0, float(settings.bg_llm_request_timeout))
        config.settings.bg_llm_request_timeout = BG_LLM_REQUEST_TIMEOUT
        updated_settings["bg_llm_request_timeout"] = BG_LLM_REQUEST_TIMEOUT

    if settings.bg_llm_connect_timeout is not None:
        BG_LLM_CONNECT_TIMEOUT = max(1.0, float(settings.bg_llm_connect_timeout))
        config.settings.bg_llm_connect_timeout = BG_LLM_CONNECT_TIMEOUT
        updated_settings["bg_llm_connect_timeout"] = BG_LLM_CONNECT_TIMEOUT

    if settings.bg_llm_num_ctx is not None:
        BG_LLM_NUM_CTX = max(2048, int(settings.bg_llm_num_ctx))
        config.settings.bg_llm_num_ctx = BG_LLM_NUM_CTX
        updated_settings["bg_llm_num_ctx"] = BG_LLM_NUM_CTX

    # VM sandbox settings — stored in UserSettingsModel.preferences JSONB
    vm_fields = {
        "host": settings.vm_sandbox_host,
        "username": settings.vm_sandbox_username,
        "ssh_key_path": settings.vm_sandbox_ssh_key_path,
    }
    vm_updates = {k: v for k, v in vm_fields.items() if v is not None}
    if vm_updates:
        try:
            from app.models.user_settings import UserSettings as UserSettingsModel
            vm_db = SessionLocal()
            try:
                us = vm_db.query(UserSettingsModel).filter(
                    UserSettingsModel.user_id == str(current_user.id)
                ).first()
                if not us:
                    us = UserSettingsModel(user_id=str(current_user.id), preferences={})
                    vm_db.add(us)
                prefs = dict(us.preferences or {})
                vm_sandbox = dict(prefs.get("vm_sandbox", {}))
                vm_sandbox.update(vm_updates)
                prefs["vm_sandbox"] = vm_sandbox
                us.preferences = prefs
                vm_db.commit()
                updated_settings.update({f"vm_sandbox_{k}": v for k, v in vm_updates.items()})
            finally:
                vm_db.close()
        except Exception as e:
            logger.warning(f"Failed to save VM sandbox settings: {e}")

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

    # Hot-reload long-lived runtime singletons so background model changes apply immediately.
    try:
        from app.core.llm import get_background_llm_client
        bg_client = get_background_llm_client()
        await bg_client.refresh_config()
    except Exception as e:
        logger.warning(f"Background LLM client hot-reload failed (will apply on next restart): {e}")

    try:
        from app.services.autonomy.sara_invocation import get_sara_invocation_service
        await get_sara_invocation_service()
    except Exception as e:
        logger.warning(f"Sara invocation service refresh failed (will apply on next access): {e}")

    try:
        from app.services.morning_brief_service import morning_brief_service
        morning_brief_service._refresh_llm_config()
    except Exception as e:
        logger.warning(f"Morning brief service refresh failed (will apply on next restart): {e}")

    logger.info("✅ Settings applied immediately - background clients hot-reloaded")

    logger.info(f"AI settings updated by user {current_user.email}: {updated_settings}")

    # Mask API key in response (after saving to database)
    response_settings = updated_settings.copy()
    if "openai_api_key" in response_settings and response_settings["openai_api_key"]:
        response_settings["openai_api_key"] = "***"

    return {
        "message": "AI settings updated successfully and persisted",
        "updated_settings": response_settings,
        "note": "Settings applied immediately and persisted for future restarts."
    }


@app.get("/settings/ai/codex/oauth/status")
async def get_codex_oauth_status(current_user: User = Depends(get_current_user)):
    """Get ChatGPT/Codex OAuth connection status."""
    if not CODEX_OAUTH_ACCESS_TOKEN or not CODEX_OAUTH_REFRESH_TOKEN:
        _load_codex_oauth_from_db()
    connected = bool(CODEX_OAUTH_ACCESS_TOKEN and CODEX_OAUTH_REFRESH_TOKEN)
    refresh_error = None
    if connected:
        try:
            await _ensure_codex_access_token(updated_by=current_user.email, min_valid_seconds=120)
        except Exception as e:
            refresh_error = str(e)
            logger.warning(f"Codex OAuth refresh failed for user {current_user.email}: {e}")

    expires_at = _safe_parse_iso_datetime(CODEX_OAUTH_EXPIRES_AT)
    return {
        "connected": connected and refresh_error is None,
        "email": CODEX_OAUTH_EMAIL or "",
        "account_id": CODEX_OAUTH_ACCOUNT_ID or "",
        "expires_at": CODEX_OAUTH_EXPIRES_AT or "",
        "expires_in_seconds": max(0, int((expires_at - datetime.now(timezone.utc)).total_seconds())) if expires_at else None,
        "error": refresh_error,
    }


@app.post("/settings/ai/codex/oauth/start")
async def start_codex_oauth(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Start ChatGPT/Codex OAuth flow and return the OpenAI authorization URL."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}

    return_to = _resolve_frontend_return_url(request, body.get("return_to"))
    # The default Codex OAuth client id uses localhost callback flow.
    # When using that flow we complete auth via /settings/ai/codex/oauth/complete.
    redirect_uri = CODEX_OAUTH_REDIRECT_URI or "http://localhost:1455/auth/callback"
    manual_completion = ("localhost:1455" in redirect_uri) or ("127.0.0.1:1455" in redirect_uri)

    verifier = secrets.token_urlsafe(64)
    challenge = _build_pkce_challenge(verifier)
    state = secrets.token_hex(16)
    pending_payload = {
        "state": state,
        "verifier": verifier,
        "redirect_uri": redirect_uri,
        "return_to": return_to,
        "user_id": str(current_user.id),
        "user_email": current_user.email,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    _upsert_app_settings(
        {"codex_oauth_pending": json.dumps(pending_payload)},
        updated_by=current_user.email,
    )

    auth_params = {
        "response_type": "code",
        "client_id": CODEX_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": CODEX_OAUTH_SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    if CODEX_OAUTH_ORIGINATOR:
        auth_params["originator"] = CODEX_OAUTH_ORIGINATOR
    auth_url = f"{CODEX_OAUTH_AUTHORIZE_URL}?{urlencode(auth_params)}"
    logger.info(
        "Starting Codex OAuth for %s with redirect_uri=%s originator=%s",
        current_user.email,
        redirect_uri,
        CODEX_OAUTH_ORIGINATOR,
    )
    return {
        "auth_url": auth_url,
        "redirect_uri": redirect_uri,
        "return_to": return_to,
        "requires_manual_code": manual_completion,
    }


class CodexOAuthCompleteRequest(BaseModel):
    redirect_url: Optional[str] = None
    code: Optional[str] = None
    state: Optional[str] = None


@app.post("/settings/ai/codex/oauth/complete")
async def complete_codex_oauth(
    payload: CodexOAuthCompleteRequest,
    current_user: User = Depends(get_current_user),
):
    """Complete Codex OAuth from a pasted callback URL or explicit code/state."""
    pending = None
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT value FROM app_settings WHERE key = 'codex_oauth_pending'")
        ).fetchone()
        if row and row[0]:
            pending = json.loads(row[0])
    except Exception as e:
        logger.error(f"Failed reading codex_oauth_pending: {e}")
    finally:
        db.close()

    if not pending or not isinstance(pending, dict):
        raise HTTPException(status_code=400, detail="No active Codex OAuth session. Start OAuth again.")

    created_at = _safe_parse_iso_datetime(pending.get("created_at", ""))
    if not created_at or created_at < datetime.now(timezone.utc) - timedelta(minutes=15):
        raise HTTPException(status_code=400, detail="Codex OAuth session expired. Start OAuth again.")

    code = (payload.code or "").strip()
    state = (payload.state or "").strip()
    if payload.redirect_url:
        parsed = urlparse(payload.redirect_url)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if not code:
            code = (params.get("code") or "").strip()
        if not state:
            state = (params.get("state") or "").strip()
        oauth_error = (params.get("error") or "").strip()
        if oauth_error:
            raise HTTPException(status_code=400, detail=f"OAuth provider returned error: {oauth_error}")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code/state. Paste the full callback URL.")
    if state != pending.get("state"):
        raise HTTPException(status_code=400, detail="State mismatch. Start OAuth again.")

    try:
        token_data = await _codex_exchange_authorization_code(
            code=code,
            verifier=pending["verifier"],
            redirect_uri=pending["redirect_uri"],
        )
    except HTTPException as e:
        raise HTTPException(status_code=400, detail=f"Codex OAuth token exchange failed: {e.detail}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Codex OAuth token exchange exception: {e}")

    _apply_codex_oauth_token_data(
        token_data=token_data,
        updated_by=pending.get("user_email", current_user.email),
    )

    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM app_settings WHERE key = 'codex_oauth_pending'"))
        db.commit()
    except Exception:
        pass
    finally:
        db.close()

    return {
        "ok": True,
        "connected": True,
        "email": CODEX_OAUTH_EMAIL or "",
        "expires_at": CODEX_OAUTH_EXPIRES_AT or "",
    }


@app.get("/settings/ai/codex/oauth/callback")
async def codex_oauth_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """OAuth callback endpoint for ChatGPT/Codex."""
    global AI_PROVIDER, OPENAI_BASE_URL, OPENAI_MODEL
    global CODEX_OAUTH_ACCESS_TOKEN, CODEX_OAUTH_REFRESH_TOKEN, CODEX_OAUTH_EXPIRES_AT
    global CODEX_OAUTH_ACCOUNT_ID, CODEX_OAUTH_EMAIL

    default_return = f"{config.settings.frontend_url.rstrip('/')}/settings"
    pending = None
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT value FROM app_settings WHERE key = 'codex_oauth_pending'")
        ).fetchone()
        if row and row[0]:
            pending = json.loads(row[0])
    except Exception as e:
        logger.error(f"Failed reading codex_oauth_pending: {e}")
    finally:
        try:
            db.execute(text("DELETE FROM app_settings WHERE key = 'codex_oauth_pending'"))
            db.commit()
        except Exception:
            pass
        db.close()

    return_to = default_return
    if isinstance(pending, dict) and pending.get("return_to"):
        return_to = _resolve_frontend_return_url(request, pending.get("return_to"))

    if error:
        redirect_url = _append_query_params(return_to, {"codex_oauth": "error", "reason": error})
        return RedirectResponse(url=redirect_url, status_code=302)

    if not pending or not isinstance(pending, dict):
        redirect_url = _append_query_params(return_to, {"codex_oauth": "error", "reason": "missing_state"})
        return RedirectResponse(url=redirect_url, status_code=302)

    created_at = _safe_parse_iso_datetime(pending.get("created_at", ""))
    if not created_at or created_at < datetime.now(timezone.utc) - timedelta(minutes=15):
        redirect_url = _append_query_params(return_to, {"codex_oauth": "error", "reason": "expired_state"})
        return RedirectResponse(url=redirect_url, status_code=302)

    if not code or not state or state != pending.get("state"):
        redirect_url = _append_query_params(return_to, {"codex_oauth": "error", "reason": "state_mismatch"})
        return RedirectResponse(url=redirect_url, status_code=302)

    try:
        token_data = await _codex_exchange_authorization_code(
            code=code,
            verifier=pending["verifier"],
            redirect_uri=pending["redirect_uri"],
        )
    except HTTPException as e:
        redirect_url = _append_query_params(return_to, {"codex_oauth": "error", "reason": "token_exchange_failed"})
        logger.warning(f"Codex OAuth token exchange failed: {e.detail}")
        return RedirectResponse(url=redirect_url, status_code=302)
    except Exception as e:
        redirect_url = _append_query_params(return_to, {"codex_oauth": "error", "reason": "token_exchange_exception"})
        logger.warning(f"Codex OAuth token exchange exception: {e}")
        return RedirectResponse(url=redirect_url, status_code=302)

    _apply_codex_oauth_token_data(
        token_data=token_data,
        updated_by=pending.get("user_email", "codex-oauth"),
    )

    redirect_url = _append_query_params(return_to, {"codex_oauth": "success"})
    return RedirectResponse(url=redirect_url, status_code=302)


@app.post("/settings/ai/codex/oauth/disconnect")
async def disconnect_codex_oauth(current_user: User = Depends(get_current_user)):
    """Disconnect ChatGPT/Codex OAuth and remove stored tokens."""
    global CODEX_OAUTH_ACCESS_TOKEN, CODEX_OAUTH_REFRESH_TOKEN, CODEX_OAUTH_EXPIRES_AT
    global CODEX_OAUTH_ACCOUNT_ID, CODEX_OAUTH_EMAIL
    CODEX_OAUTH_ACCESS_TOKEN = ""
    CODEX_OAUTH_REFRESH_TOKEN = ""
    CODEX_OAUTH_EXPIRES_AT = ""
    CODEX_OAUTH_ACCOUNT_ID = ""
    CODEX_OAUTH_EMAIL = ""

    db = SessionLocal()
    try:
        db.execute(text("""
            DELETE FROM app_settings
            WHERE key IN (
                'codex_oauth_access_token',
                'codex_oauth_refresh_token',
                'codex_oauth_expires_at',
                'codex_oauth_account_id',
                'codex_oauth_email',
                'codex_oauth_pending'
            )
        """))
        db.commit()
    finally:
        db.close()

    return {"ok": True, "message": "Codex OAuth disconnected"}

@app.post("/settings/ai/test")
async def test_ai_settings(current_user: User = Depends(get_current_user)):
    """Test current AI configuration"""
    test_results = {}
    
    try:
        effective_model = OPENAI_MODEL or CODEX_DEFAULT_MODEL
        model_config = get_model_config(effective_model)

        # Test LLM connection
        if model_config["provider"] == "codex":
            access_token = await _ensure_codex_access_token(updated_by=current_user.email, min_valid_seconds=120) or CODEX_OAUTH_ACCESS_TOKEN
            account_id = CODEX_OAUTH_ACCOUNT_ID or _extract_codex_account_id_from_token(access_token or "")
            if not access_token or not account_id:
                raise RuntimeError("Codex OAuth is not connected or token is invalid")

            codex_url = f"{model_config['base_url'].rstrip('/')}/codex/responses"
            response = await httpx.AsyncClient().post(
                codex_url,
                json={
                    "model": effective_model,
                    "store": False,
                    "stream": True,
                    "instructions": "You are a helpful assistant.",
                    "input": [{"role": "user", "content": [{"type": "input_text", "text": "Reply with exactly: Connection successful"}]}],
                },
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "chatgpt-account-id": account_id,
                    "OpenAI-Beta": "responses=experimental",
                    "originator": CODEX_OAUTH_ORIGINATOR,
                },
                timeout=15.0,
            )
            if response.status_code == 200:
                test_results["llm"] = {"status": "success", "message": "Codex OAuth connection successful"}
            else:
                test_results["llm"] = {"status": "error", "message": f"Codex connection failed: {response.status_code}"}
        else:
            test_messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello, just testing the connection. Please respond with 'Connection successful'."}
            ]

            api_key = OPENAI_API_KEY or "dummy"
            response = await httpx.AsyncClient().post(
                f"{OPENAI_BASE_URL}/chat/completions",
                json={
                    "model": OPENAI_MODEL,
                    "messages": test_messages,
                    "max_tokens": 50,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
                headers={"Authorization": f"Bearer {api_key}"},
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

# Settings helpers extracted to app.core.settings_helpers
from app.core.settings_helpers import (
    get_or_create_user_settings_row as _get_or_create_user_settings_row,
    merged_user_settings as _merged_user_settings,
    _DEFAULT_USER_SETTINGS,
)


@app.get("/settings")
async def get_user_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get persisted user settings/preferences."""
    settings_row = _get_or_create_user_settings_row(db, str(current_user.id))
    return _merged_user_settings(settings_row.preferences)


@app.put("/settings")
async def update_user_settings(
    settings: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update persisted user settings/preferences."""
    if not isinstance(settings, dict):
        raise HTTPException(status_code=422, detail="Settings payload must be an object")

    settings_row = _get_or_create_user_settings_row(db, str(current_user.id))
    prefs = dict(settings_row.preferences or {})

    for key, value in settings.items():
        if key in {"id", "user_id", "created_at", "updated_at"}:
            continue
        if value is None:
            prefs.pop(key, None)
        else:
            prefs[key] = value

    settings_row.preferences = prefs
    db.commit()
    db.refresh(settings_row)

    return {
        "message": "Settings updated successfully",
        "settings": _merged_user_settings(settings_row.preferences),
    }


# Settings alias endpoints (for iOS app compatibility)
@app.get("/settings/preferences")
async def get_user_preferences(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return persisted preference fields used by iOS settings."""
    settings_row = _get_or_create_user_settings_row(db, str(current_user.id))
    return _merged_user_settings(settings_row.preferences)


@app.put("/settings/preferences")
async def update_user_preferences(
    settings: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update iOS preference fields and return the updated preferences."""
    response = await update_user_settings(settings=settings, current_user=current_user, db=db)
    return response["settings"]

# Documents categories endpoint

# ==================== SARA AUTONOMOUS SYSTEM ENDPOINTS ====================
# GTKY endpoints removed - was broken and unused

# =====================
# Nightly Reflection Endpoints
# =====================
# Daily brief endpoints extracted to app/routes/daily_brief.py


def _assert_unique_routes() -> None:
    """Fail startup when multiple handlers claim the same method/path."""
    seen: Dict[tuple[str, str], APIRoute] = {}
    duplicates: List[str] = []

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods or []):
            if method in {"HEAD", "OPTIONS"}:
                continue
            key = (method, route.path)
            existing = seen.get(key)
            if existing:
                prev_endpoint = f"{existing.endpoint.__module__}.{existing.endpoint.__name__}"
                new_endpoint = f"{route.endpoint.__module__}.{route.endpoint.__name__}"
                duplicates.append(f"{method} {route.path} ({prev_endpoint} vs {new_endpoint})")
            else:
                seen[key] = route

    if duplicates:
        raise RuntimeError(
            "Duplicate FastAPI routes detected. Resolve collisions before startup: "
            + "; ".join(duplicates)
        )


_assert_unique_routes()


if __name__ == "__main__":
    import uvicorn
    # Allow host/port override via env for flexible deployment
    uvicorn_host = os.getenv("HOST", "0.0.0.0")
    uvicorn_port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host=uvicorn_host, port=uvicorn_port)
