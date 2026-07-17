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

from app.core.deps import get_current_user
from app.db.session import get_db

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
