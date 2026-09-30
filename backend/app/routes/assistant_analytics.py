"""Assistant experience analytics routes."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_current_user_sync
from app.db.session import get_db
from app.core.config import settings
from app.models.user import User
from sqlalchemy import text

logger = logging.getLogger(__name__)

router = APIRouter(tags=["assistant-analytics"])

event_log_table = Table(
    "event_log",
    MetaData(),
    Column("id", Integer, primary_key=True),
    Column("event_id", String, nullable=False),
    Column("event_type", String, nullable=False),
    Column("user_id", String, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("source", String, nullable=False),
    Column("metadata", JSON, nullable=False),
    Column("timestamp", DateTime(timezone=True), nullable=False),
)

ALLOWED_EVENT_TYPES = {
    "assistant.chat_opened",
    "assistant.inbox_opened",
    "assistant.inbox_item_opened",
    "assistant.message_sent",
    "assistant.proactive_context_opened",
    "assistant.proactive_context_prompt_used",
    "assistant.suggested_action_tapped",
    "assistant.voice_hands_free_toggled",
    "assistant.voice_hold_to_talk_started",
}


class AssistantAnalyticsEventRequest(BaseModel):
    event_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    source: str = "ios_app"


def _current_user_id(current_user: Any) -> str:
    if hasattr(current_user, "id"):
        return str(current_user.id)
    if isinstance(current_user, dict) and current_user.get("id") is not None:
        return str(current_user["id"])
    raise HTTPException(status_code=500, detail="Unable to resolve current user id")


def _safe_payload(raw_value: Any) -> Dict[str, Any]:
    return raw_value if isinstance(raw_value, dict) else {}


def _ensure_event_log_table(db: Session) -> None:
    event_log_table.create(bind=db.get_bind(), checkfirst=True)


def _empty_summary(days: int, *, available: bool, note: str | None = None) -> Dict[str, Any]:
    return {
        "window_days": days,
        "available": available,
        "note": note,
        "metrics": {
            "daily_assistant_usage_days": 0,
            "chat_opens": 0,
            "inbox_opens": 0,
            "notification_to_chat_opens": 0,
            "suggested_action_completions": 0,
            "voice_usage": {
                "hold_to_talk_starts": 0,
                "hands_free_enabled": 0,
                "voice_message_sends": 0,
            },
        },
        "event_counts": {},
    }


@router.post("/api/assistant-analytics/events")
async def create_assistant_analytics_event(
    request: AssistantAnalyticsEventRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Persist assistant experience analytics events from trusted app clients."""
    if request.event_type not in ALLOWED_EVENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported event_type '{request.event_type}'")

    event_id = str(uuid4())
    timestamp = datetime.now(timezone.utc)

    try:
        _ensure_event_log_table(db)
        db.execute(
            event_log_table.insert().values(
                event_id=event_id,
                event_type=request.event_type,
                user_id=_current_user_id(current_user),
                payload=request.payload,
                source=request.source or "ios_app",
                metadata=request.metadata,
                timestamp=timestamp,
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Failed to write assistant analytics event %s: %s", request.event_type, exc)
        raise HTTPException(status_code=500, detail="Failed to record analytics event")

    return {"success": True, "event_id": event_id, "timestamp": timestamp.isoformat()}


@router.get("/api/assistant-analytics/summary")
async def get_assistant_analytics_summary(
    days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return a compact assistant UX metrics summary for the requested window."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    user_id = _current_user_id(current_user)
    try:
        _ensure_event_log_table(db)
        rows = db.execute(
            select(
                event_log_table.c.event_type,
                event_log_table.c.payload,
                event_log_table.c.timestamp,
            )
            .where(event_log_table.c.user_id == user_id)
            .where(event_log_table.c.event_type.like("assistant.%"))
            .where(event_log_table.c.timestamp >= since)
        ).mappings().all()
    except Exception as exc:
        logger.error("Failed to load assistant analytics summary: %s", exc)
        return _empty_summary(
            days,
            available=False,
            note="Analytics storage is not available yet. Showing empty summary.",
        )

    event_counts: Dict[str, int] = {}
    message_days = set()
    notification_context_opens = 0
    suggested_action_message_sends = 0
    voice_message_sends = 0
    hands_free_enabled = 0

    for row in rows:
        event_type = str(row.get("event_type") or "")
        payload = _safe_payload(row.get("payload"))
        timestamp = row.get("timestamp")

        event_counts[event_type] = event_counts.get(event_type, 0) + 1

        if event_type == "assistant.message_sent" and timestamp:
            message_days.add(timestamp.date().isoformat())
            if payload.get("entry_point") == "suggested_action":
                suggested_action_message_sends += 1
            if str(payload.get("input_mode", "")).startswith("voice_"):
                voice_message_sends += 1

        if event_type == "assistant.proactive_context_opened" and payload.get("source") == "notification":
            notification_context_opens += 1

        if event_type == "assistant.voice_hands_free_toggled" and payload.get("enabled") is True:
            hands_free_enabled += 1

    return {
        "window_days": days,
        "available": True,
        "note": None,
        "metrics": {
            "daily_assistant_usage_days": len(message_days),
            "chat_opens": event_counts.get("assistant.chat_opened", 0),
            "inbox_opens": event_counts.get("assistant.inbox_opened", 0),
            "notification_to_chat_opens": notification_context_opens,
            "suggested_action_completions": suggested_action_message_sends,
            "voice_usage": {
                "hold_to_talk_starts": event_counts.get("assistant.voice_hold_to_talk_started", 0),
                "hands_free_enabled": hands_free_enabled,
                "voice_message_sends": voice_message_sends,
            },
        },
        "event_counts": event_counts,
    }


# Moved out of main_simple.py 2026-09-30 (cleanup plan 4.7). Path unchanged.
#
# Two substitutions, both behavior-preserving:
#  * get_current_user_sync, not this module's async get_current_user — in the
#    monolith this resolved to the sync dependency, with no device-token
#    fallback. Keeping it sync preserves the auth this endpoint had.
#  * the monolith global EMBEDDING_DIM becomes settings.embedding_dim. Both
#    places that mutate that global (the app_settings loader and
#    PUT /settings/ai) assign config.settings.embedding_dim in the same
#    breath, so the value observed here is identical, hot reloads included.
@router.get("/analytics/dashboard")
async def get_analytics_dashboard(current_user: User = Depends(get_current_user_sync), db: Session = Depends(get_db)):
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
            embedding_health = len(embedding_test) == settings.embedding_dim
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
