"""
Subconscious Service - Sara's Mental Model State Reader

DEPRECATED: Signal-gathering and processing logic has been replaced by the
event-driven deliberation system (salience subscriber, working memory,
periodic deliberation fallback). The old process_user() cycle has been removed.

Remaining public API (used by routes and other services):
- get_current_state() — reads subconscious_state table
- get_pending_nudges() — reads subconscious_nudge table
- acknowledge_nudge() — updates nudge status
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from zoneinfo import ZoneInfo
from dataclasses import dataclass
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.body_state_service import BodyStateEstimate
from app.core.timezone import USER_TIMEZONE

logger = logging.getLogger(__name__)

USER_TZ = USER_TIMEZONE


@dataclass
class SubconsciousState:
    """Current mental model state"""
    # Meal tracking
    last_meal_type: Optional[str] = None
    last_meal_at: Optional[datetime] = None
    hours_since_meal: Optional[float] = None
    typical_meal_windows: Optional[Dict] = None

    # Energy/mood (LLM-inferred)
    inferred_energy_level: Optional[float] = None
    inferred_mood: Optional[str] = None
    mood_context: Optional[str] = None
    message_velocity: Optional[float] = None
    in_flow_state: bool = False

    # Recent conversation digest
    recent_conversation_digest: Optional[str] = None

    # Focus
    current_focus_areas: Optional[List[str]] = None
    focus_intensity: Optional[float] = None

    # Sleep
    last_sleep_hours: Optional[float] = None
    last_sleep_quality: Optional[str] = None
    sleep_deficit_hours: Optional[float] = None

    # System health
    docker_health: Optional[Dict] = None
    service_health: Optional[Dict] = None
    llm_primary_status: Optional[str] = None
    llm_failover_status: Optional[str] = None
    llm_active_backend: Optional[str] = None

    # Presence & Activity
    last_presence_at: Optional[datetime] = None
    hours_since_presence: Optional[float] = None
    first_activity_today: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None
    has_chatted_today: bool = False
    hours_since_wakeup: Optional[float] = None
    is_past_bedtime: bool = False
    is_waking_hours: bool = True

    # Body state
    body_state: Optional[BodyStateEstimate] = None
    body_state_context: Optional[str] = None

    # Activity state (from ActivityStateMachine)
    activity_state: Optional[str] = None
    activity_confidence: Optional[float] = None
    activity_reason: Optional[str] = None
    activity_room: Optional[str] = None
    interruptibility_score: Optional[float] = None
    interruptibility_channel: Optional[str] = None

    # Nudge eligibility flags
    nudge_morning_eligible: bool = False
    nudge_bedtime_eligible: bool = False
    nudge_sleep_deficit: float = 0.0

    # Shadow session context
    recent_shadow_summary: Optional[str] = None
    shadow_tasks: Optional[List[str]] = None
    shadow_decisions: Optional[List[str]] = None
    shadow_questions: Optional[List[str]] = None
    last_shadow_session_at: Optional[datetime] = None
    shadow_focus_areas: Optional[List[str]] = None


class SubconsciousService:
    """
    Read-only service for querying Sara's mental model state.
    Processing is now handled by the event-driven deliberation system.
    """

    def __init__(self, database_url: str):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        self.engine = create_engine(database_url)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.tz = USER_TZ

    async def get_current_state(self, db: Session, user_id: str) -> Optional[Dict]:
        """Get current subconscious state for a user"""
        result = db.execute(text("""
            SELECT * FROM subconscious_state WHERE user_id = :user_id
        """), {"user_id": user_id}).fetchone()

        if result:
            return dict(result._mapping)
        return None

    async def get_pending_nudges(self, db: Session, user_id: str) -> List[Dict]:
        """Get pending nudges for a user"""
        result = db.execute(text("""
            SELECT id, nudge_type, severity, title, message, action_suggestion,
                   delivery_channel, created_at, expires_at
            FROM subconscious_nudge
            WHERE user_id = :user_id
              AND status = 'pending'
              AND expires_at > NOW()
            ORDER BY
                CASE severity
                    WHEN 'urgent' THEN 1
                    WHEN 'gentle' THEN 2
                    ELSE 3
                END,
                created_at DESC
        """), {"user_id": user_id}).fetchall()

        return [dict(r._mapping) for r in result]

    async def acknowledge_nudge(self, db: Session, nudge_id: str) -> bool:
        """Acknowledge a nudge"""
        result = db.execute(text("""
            UPDATE subconscious_nudge
            SET acknowledged_at = NOW(), status = 'acknowledged'
            WHERE id = :nudge_id AND status IN ('pending', 'delivered')
        """), {"nudge_id": nudge_id})

        return result.rowcount > 0
