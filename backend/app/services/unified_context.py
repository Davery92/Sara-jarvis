"""
Unified Context Snapshot — single source of truth for David's current state.

Every agent, every chat turn, every notification reads from this one Redis-backed
snapshot instead of making scattered DB queries. The snapshot is written to
incrementally by each system (subconscious, HA bridge, heartbeat, chat, etc.)
and can be fully rebuilt from DB on cold start.
"""

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, get_args, get_origin, Union
from app.core.timezone import now as local_now

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
SNAPSHOT_KEY = "sara:unified_context:{user_id}"
CHANGES_KEY = "sara:context_changes:{user_id}"


@dataclass
class UnifiedContextSnapshot:
    """Single object containing everything about David right now."""

    # ── Activity / Presence ──
    activity_state: str = "UNKNOWN"
    activity_confidence: float = 0.5
    room: Optional[str] = None
    interruptibility: float = 0.5
    hours_since_last_chat: float = 0.0
    last_chat_at: Optional[str] = None  # ISO string
    last_chat_topic: Optional[str] = None
    has_chatted_today: bool = False
    is_past_bedtime: bool = False

    # ── Body State ──
    alertness: float = 0.5
    stress_load: float = 0.3
    blood_sugar: float = 0.5
    circadian_phase: str = "normal"
    energy_level: Optional[float] = None
    mood: Optional[str] = None
    in_flow_state: bool = False

    # ── Environment ──
    home_occupied: bool = True
    active_rooms: Optional[List[str]] = None
    temperature_inside: Optional[float] = None
    temperature_outside: Optional[float] = None
    weather_condition: Optional[str] = None

    # ── Schedule ──
    next_event_title: Optional[str] = None
    next_event_minutes_away: Optional[int] = None
    events_today_count: int = 0

    # ── Agent Memory ──
    last_heartbeat_at: Optional[str] = None
    last_heartbeat_handoff: Optional[str] = None
    last_heartbeat_watching_for: Optional[str] = None
    last_handoff_set_at: Optional[str] = None
    last_anticipation_note: Optional[str] = None
    notifications_sent_today: int = 0

    # ── Active Work ──
    active_projects: Optional[List[str]] = None
    learning_reviews_due: int = 0
    active_learning_topics: Optional[List[str]] = None

    # ── Conversation Threads ──
    open_thread_count: int = 0
    ripe_thread_topics: Optional[List[str]] = None

    # ── Conversation ──
    active_conversation_id: Optional[str] = None
    active_conversation_device: Optional[str] = None
    turn_count: int = 0

    # ── Quiet Mode ──
    quiet_mode: bool = False
    quiet_mode_until: Optional[str] = None  # ISO timestamp

    # ── Sara Internal State ──
    sara_focus: Optional[str] = None  # what Sara is paying attention to
    sara_emotional_tone: Optional[str] = None  # curious/concerned/playful/proud/etc
    sara_emotional_intensity: float = 0.3  # 0.0-1.0, how strongly Sara feels the current tone
    sara_curiosities: Optional[List[str]] = None  # things Sara wants to explore (max 5)
    sara_last_deliberation_at: Optional[str] = None  # ISO timestamp
    sara_deliberation_count_today: int = 0
    observation_count: int = 0  # pending observations awaiting deliberation
    salience_high_water: float = 0.0  # highest unprocessed salience score

    # ── Derived State (event-driven) ──
    hours_since_last_meal: float = 0.0
    last_meal_type: Optional[str] = None
    today_habit_status: Optional[str] = None  # "3/7 done, pending: meditation, reading"
    recent_notes_summary: Optional[str] = None  # "3 notes edited: Memory Architecture, ..."
    active_project_summary: Optional[str] = None

    # ── Notification Calibration ──
    notification_engagement_stats: Optional[str] = None  # JSON: {category: {sent, engaged, dismissed, ignored, rate}}
    behavioral_calibration: Optional[str] = None  # JSON: {category_scores, best_hours, worst_hours, insights}

    # ── Jetson / Sensory ──
    desk_presence: bool = False
    voice_conversation_active: bool = False
    jetson_online: bool = False

    # ── PKG Growth ──
    pkg_validation_report: Optional[str] = None  # JSON: {confirmed, contradictions_count, stale, ...}
    pkg_knowledge_gaps: Optional[str] = None  # JSON: [{"topic": ..., "mentions": N, "suggested_type": ...}]

    # ── ACS (Autonomous Cognition System) ──
    acs_state: Optional[str] = None  # autonomous|pausing|conversational|cooldown
    acs_active_session_id: Optional[str] = None
    acs_model_id: Optional[str] = None

    # ── Meta ──
    version: int = 0
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict:
        """Serialize to flat dict for Redis hash storage."""
        d = {}
        for k, v in asdict(self).items():
            if v is None:
                d[k] = ""
            elif isinstance(v, (list, dict)):
                d[k] = json.dumps(v)
            elif isinstance(v, bool):
                d[k] = "1" if v else "0"
            else:
                d[k] = str(v)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, str]) -> "UnifiedContextSnapshot":
        """Deserialize from Redis hash."""
        if not d:
            return cls()
        kwargs = {}
        field_types = {f.name: f.type for f in cls.__dataclass_fields__.values()}

        def _unwrap_optional(ftype):
            origin = get_origin(ftype)
            if origin is Union:
                args = [a for a in get_args(ftype) if a is not type(None)]
                if len(args) == 1:
                    return args[0], True
            return ftype, False

        for k, raw in d.items():
            if k not in field_types:
                continue
            ftype = field_types[k]
            try:
                inner_type, is_optional = _unwrap_optional(ftype)
                origin = get_origin(inner_type)
                if origin in (list, dict):
                    kwargs[k] = json.loads(raw) if raw else (None if is_optional else inner_type())
                elif inner_type is bool:
                    kwargs[k] = raw in ("1", "True", "true") if raw else (None if is_optional else False)
                elif inner_type is int:
                    kwargs[k] = int(float(raw)) if raw else (None if is_optional else 0)
                elif inner_type is float:
                    kwargs[k] = float(raw) if raw else (None if is_optional else 0.0)
                elif inner_type is str:
                    kwargs[k] = raw if raw else None
                else:
                    kwargs[k] = raw
            except (ValueError, json.JSONDecodeError):
                pass  # keep default
        return cls(**kwargs)


# ── Redis Connection Pool (per-event-loop singleton) ──

_redis_pool: Optional[aioredis.Redis] = None
_redis_loop_id: Optional[int] = None  # track which event loop owns the pool


async def _get_redis() -> aioredis.Redis:
    """Lazy-init shared Redis connection, recreated when event loop changes."""
    global _redis_pool, _redis_loop_id
    import asyncio
    cur_loop = id(asyncio.get_running_loop())
    if _redis_pool is None or cur_loop != _redis_loop_id:
        # Close stale pool (best-effort)
        if _redis_pool is not None:
            try:
                await _redis_pool.aclose()
            except Exception:
                pass
        _redis_pool = await aioredis.from_url(
            REDIS_URL, decode_responses=True, max_connections=10
        )
        _redis_loop_id = cur_loop
    return _redis_pool


async def read_snapshot(user_id: str) -> UnifiedContextSnapshot:
    """Read the full snapshot from Redis. Returns empty snapshot if not found."""
    try:
        r = await _get_redis()
        key = SNAPSHOT_KEY.format(user_id=user_id)
        data = await r.hgetall(key)
        if data:
            return UnifiedContextSnapshot.from_dict(data)
        return UnifiedContextSnapshot()
    except Exception as e:
        logger.warning(f"Failed to read snapshot from Redis: {e}")
        return UnifiedContextSnapshot()


async def write_snapshot(user_id: str, snapshot: UnifiedContextSnapshot) -> None:
    """Write the full snapshot to Redis hash."""
    try:
        r = await _get_redis()
        key = SNAPSHOT_KEY.format(user_id=user_id)
        snapshot.version += 1
        snapshot.updated_at = local_now().isoformat()
        await r.hset(key, mapping=snapshot.to_dict())
    except Exception as e:
        logger.warning(f"Failed to write snapshot to Redis: {e}")


async def read_changes(user_id: str) -> List[str]:
    """Read the list of changes since David's last chat."""
    try:
        r = await _get_redis()
        key = CHANGES_KEY.format(user_id=user_id)
        changes = await r.lrange(key, 0, -1)
        return changes or []
    except Exception as e:
        logger.warning(f"Failed to read changes from Redis: {e}")
        return []
