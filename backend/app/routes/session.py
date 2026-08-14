"""
Session routes — active session tracking for cross-device continuity.

Sara is one assistant across desktop and iOS. This endpoint lets clients
check if there's an active conversation to resume.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional
from app.core.timezone import now as local_now

from app.core.redis import get_redis
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.deps import get_current_user
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/session", tags=["session"])

SESSION_KEY = "sara:active_session:{user_id}"
SESSION_TTL = 3600  # 1 hour


class ActiveSession(BaseModel):
    conversation_id: Optional[str] = None
    started_at: Optional[str] = None
    last_activity_at: Optional[str] = None
    last_device: Optional[str] = None
    turn_count: int = 0
    topic_summary: Optional[str] = None


class SessionResponse(BaseModel):
    active: bool
    session: Optional[ActiveSession] = None


async def _get_redis():
    return await get_redis()


@router.get("/active", response_model=SessionResponse)
async def get_active_session(current_user=Depends(get_current_user)):
    """
    Returns the current active session if one exists and is < 1hr old.
    All clients (desktop, iOS) call this on mount to decide whether to resume or start fresh.
    """
    try:
        r = await _get_redis()
        key = SESSION_KEY.format(user_id=str(current_user.id))
        data = await r.get(key)
        if not data:
            return SessionResponse(active=False)

        session_data = json.loads(data)
        last_activity = session_data.get("last_activity_at")
        if last_activity:
            last_dt = datetime.fromisoformat(last_activity)
            if (local_now() - last_dt) > timedelta(hours=1):
                return SessionResponse(active=False)

        return SessionResponse(
            active=True,
            session=ActiveSession(**session_data)
        )
    except Exception as e:
        logger.warning(f"Failed to get active session: {e}")
        return SessionResponse(active=False)


async def update_active_session(
    user_id: str,
    conversation_id: str,
    device: str = "unknown",
    turn_count: int = 0,
    topic_summary: Optional[str] = None,
) -> None:
    """Update the active session in Redis. Called from chat_stream on each turn."""
    # Never store a placeholder id — clients resume whatever id is in here,
    # and a bogus value blocks their fallback to /api/conversations/active.
    if not conversation_id or conversation_id == "unknown":
        return
    try:
        r = await _get_redis()
        key = SESSION_KEY.format(user_id=user_id)

        # Read existing session
        existing = await r.get(key)
        if existing:
            session_data = json.loads(existing)
        else:
            session_data = {
                "conversation_id": conversation_id,
                "started_at": local_now().isoformat(),
            }

        # Update fields
        session_data["conversation_id"] = conversation_id
        session_data["last_activity_at"] = local_now().isoformat()
        session_data["last_device"] = device
        session_data["turn_count"] = turn_count
        if topic_summary:
            session_data["topic_summary"] = topic_summary

        await r.setex(key, SESSION_TTL, json.dumps(session_data))
    except Exception as e:
        logger.debug(f"Failed to update active session: {e}")


class NotificationAck(BaseModel):
    outcome: str  # "opened_chat", "dismissed", "no_response"


@router.post("/notifications/{notification_id}/ack")
async def ack_notification(
    notification_id: int,
    ack: NotificationAck,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Acknowledge a notification — called by iOS/desktop when tapped or dismissed.
    Writes outcome to notification_log for adaptive check-in frequency.
    """
    from sqlalchemy import text
    try:
        now = local_now()
        # Get the notification to compute response time
        row = db.execute(text("""
            SELECT sent_at FROM notification_log
            WHERE id = :id AND user_id = :uid
        """), {"id": notification_id, "uid": str(current_user.id)}).fetchone()

        response_seconds = None
        if row and row.sent_at:
            response_seconds = int((now - row.sent_at).total_seconds())

        db.execute(text("""
            UPDATE notification_log
            SET seen_at = :seen, outcome = :outcome, response_time_seconds = :rts
            WHERE id = :id AND user_id = :uid
        """), {
            "seen": now,
            "outcome": ack.outcome,
            "rts": response_seconds,
            "id": notification_id,
            "uid": str(current_user.id),
        })
        db.commit()

        return {"ok": True, "response_time_seconds": response_seconds}
    except Exception as e:
        logger.warning(f"Notification ack failed: {e}")
        return {"ok": False, "error": str(e)}
