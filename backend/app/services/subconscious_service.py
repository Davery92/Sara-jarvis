"""
Subconscious Service - Sara's Mental Model Manager

PARTIALLY DEPRECATED: Signal-gathering logic has been extracted to
unified_agent.py (SensingPhase class) which runs as part of the consolidated
4-phase Celery task. The process_user() method is no longer called by the
subconscious worker.

Public API methods are still active (used by routes and other services):
- get_current_state() — reads subconscious_state table
- get_pending_nudges() — reads subconscious_nudge table
- acknowledge_nudge() — updates nudge status
"""

import asyncio
import logging
import uuid
import json
import httpx
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from zoneinfo import ZoneInfo
from dataclasses import dataclass, asdict
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.body_state_service import body_state_service, BodyStateEstimate
from app.services.sara_journal_service import sara_journal
from app.services.ha_control_service import ha_control
from app.core.timezone import USER_TIMEZONE

logger = logging.getLogger(__name__)

# Timezone for schedule (user is in Eastern time)
USER_TZ = USER_TIMEZONE

# Waking hours (6 AM - 10 PM)
WAKING_HOURS_START = 6
WAKING_HOURS_END = 22

# Nudge thresholds
THRESHOLDS = {
    'missed_meal_hours': 5.0,        # More than 5 hours since last meal
    'late_meal_margin_hours': 1.0,   # Past typical meal window by 1+ hour
    'bedtime_hour': 22,              # 10 PM
    'sleep_deficit_hours': 6.0,      # Less than 6 hours sleep
    'long_focus_hours': 3.0,         # Same topic for 3+ hours without break
}

# Severity levels
SEVERITY_INFO = 'info'
SEVERITY_GENTLE = 'gentle'
SEVERITY_URGENT = 'urgent'


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
    mood_context: Optional[str] = None  # LLM notes about current state
    message_velocity: Optional[float] = None
    in_flow_state: bool = False  # High focus, suppress non-urgent nudges

    # Recent conversation digest (actual messages for subconscious awareness)
    recent_conversation_digest: Optional[str] = None

    # Focus
    current_focus_areas: Optional[List[str]] = None
    focus_intensity: Optional[float] = None  # 0-1, how deep in focus

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
    first_activity_today: Optional[datetime] = None  # When user first opened app today
    last_activity_at: Optional[datetime] = None      # Last interaction
    has_chatted_today: bool = False                  # Has user messaged Sara today?
    hours_since_wakeup: Optional[float] = None       # Hours since first activity today
    is_past_bedtime: bool = False                    # Is user active past 10 PM?
    is_waking_hours: bool = True

    # Body state (physiological estimates)
    body_state: Optional[BodyStateEstimate] = None
    body_state_context: Optional[str] = None  # Summary for Sara's prompt

    # Activity state (from ActivityStateMachine)
    activity_state: Optional[str] = None           # ActivityState enum value
    activity_confidence: Optional[float] = None
    activity_reason: Optional[str] = None
    activity_room: Optional[str] = None
    interruptibility_score: Optional[float] = None
    interruptibility_channel: Optional[str] = None  # push, badge, queue

    # Nudge eligibility flags (exposed for heartbeat agent to read)
    nudge_morning_eligible: bool = False
    nudge_bedtime_eligible: bool = False
    nudge_sleep_deficit: float = 0.0

    # Shadow session context (recent activity observation)
    recent_shadow_summary: Optional[str] = None
    shadow_tasks: Optional[List[str]] = None
    shadow_decisions: Optional[List[str]] = None
    shadow_questions: Optional[List[str]] = None
    last_shadow_session_at: Optional[datetime] = None
    shadow_focus_areas: Optional[List[str]] = None  # What David was working on


class SubconsciousService:
    """
    Service for maintaining Sara's mental model and generating nudges.
    """

    def __init__(self, database_url: str):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        self.engine = create_engine(database_url)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.tz = USER_TZ

        # LLM config for inference with failover
        self._refresh_llm_config()

        # Track which backend is currently active
        self._active_llm_url = None
        self._active_model = None

    def _refresh_llm_config(self):
        """Reload background LLM settings so model switches apply live."""
        from app.core.config import settings
        self.llm_primary_url = settings.bg_llm_primary_url.replace('/v1', '')
        self.llm_fallback_url = settings.bg_llm_fallback_url.replace('/v1', '')
        self.primary_model = settings.bg_llm_primary_model
        self.fallback_model = settings.bg_llm_fallback_model

    def _is_waking_hours(self, now: datetime) -> bool:
        """Check if current time is during waking hours"""
        return WAKING_HOURS_START <= now.hour < WAKING_HOURS_END

    async def _get_active_llm(self) -> tuple[str, str]:
        """
        Get the active LLM endpoint and model, with automatic failover.
        Returns (url, model) tuple.
        """
        self._refresh_llm_config()
        # Check primary endpoint
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.llm_primary_url}/v1/models")
                if response.status_code == 200:
                    self._active_llm_url = self.llm_primary_url
                    self._active_model = self.primary_model
                    return self._active_llm_url, self._active_model
        except Exception as e:
            logger.warning(f"Primary LLM unavailable: {e}")

        # Fallback to local endpoint with smaller model
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.llm_fallback_url}/v1/models")
                if response.status_code == 200:
                    logger.info(f"Using fallback LLM at {self.llm_fallback_url} with {self.fallback_model}")
                    self._active_llm_url = self.llm_fallback_url
                    self._active_model = self.fallback_model
                    return self._active_llm_url, self._active_model
        except Exception as e:
            logger.error(f"Fallback LLM also unavailable: {e}")

        # No LLM available
        return None, None

    async def process_user(self, db: Session, user_id: str) -> SubconsciousState:
        """
        Run a full subconscious cycle for a user:
        1. Gather signals from all sources
        2. Compute derived state
        3. Detect threshold crossings
        4. Generate and store nudges
        5. Update state table
        6. Log snapshot
        """
        now = datetime.now(self.tz)
        logger.info(f"Processing subconscious cycle for user {user_id}")

        # Initialize state
        state = SubconsciousState()
        state.is_waking_hours = self._is_waking_hours(now)

        # Gather signals
        await self._gather_presence_signals(db, user_id, state, now)  # Must run first!
        await self._gather_meal_signals(db, user_id, state, now)
        await self._gather_conversation_signals(db, user_id, state, now)
        await self._gather_health_signals(db, user_id, state, now)
        await self._gather_system_health(state)
        await self._gather_shadow_signals(db, user_id, state, now)

        # Estimate body state (physiological awareness)
        try:
            subconscious_dict = {
                'inferred_mood': state.inferred_mood,
                'inferred_energy_level': state.inferred_energy_level,
                'focus_intensity': state.focus_intensity,
                'in_flow_state': state.in_flow_state
            }
            state.body_state = await body_state_service.estimate_body_state(
                db, user_id, subconscious_dict
            )
            state.body_state_context = body_state_service.generate_context_summary(state.body_state)
            logger.info(f"Body state estimated: alertness={state.body_state.alertness:.2f}, "
                       f"blood_sugar={state.body_state.blood_sugar:.2f}")
        except Exception as e:
            import traceback
            logger.error(f"Body state estimation failed: {e}\n{traceback.format_exc()}")
            # Rollback to clear any failed transaction state
            try:
                db.rollback()
            except Exception:
                pass
            state.body_state = None
            state.body_state_context = None

        # Compute activity state and interruptibility
        try:
            from app.services.activity_state_machine import activity_state_machine
            from app.services.interruptibility import compute_interruptibility

            # Gather recent HA activity for the state machine
            ha_activity = []
            try:
                ha_rows = db.execute(text("""
                    SELECT entity_id, to_state, changed_at
                    FROM home_activity_log
                    WHERE changed_at >= NOW() - INTERVAL '30 minutes'
                    ORDER BY changed_at DESC
                    LIMIT 20
                """)).fetchall()
                ha_activity = [
                    {"entity_id": r.entity_id, "to_state": r.to_state, "changed_at": r.changed_at}
                    for r in ha_rows
                ]
            except Exception as e:
                logger.debug(f"Could not fetch HA activity: {e}")
                try:
                    db.rollback()
                except Exception:
                    pass

            # Gather upcoming calendar events for this user only.
            now_local_naive = now.replace(tzinfo=None) if now.tzinfo else now
            later_local_naive = now_local_naive + timedelta(hours=4)
            calendar_events = []
            try:
                cal_rows = db.execute(text("""
                    SELECT title, summary, start_time as start, end_time as end
                    FROM calendar_event
                    WHERE user_id = :user_id
                    AND start_time >= :now
                    AND start_time <= :later
                    ORDER BY start_time ASC
                    LIMIT 5
                """), {"user_id": user_id, "now": now_local_naive, "later": later_local_naive}).fetchall()
                calendar_events = [
                    {"title": r.title or r.summary, "start": r.start, "end": r.end}
                    for r in cal_rows
                ]
            except Exception as e:
                logger.debug(f"Could not fetch calendar: {e}")
                try:
                    db.rollback()
                except Exception:
                    pass

            # Compute activity state from full context
            body_dict = None
            if state.body_state:
                body_dict = {
                    "alertness": state.body_state.alertness,
                    "stress_load": state.body_state.stress_load,
                }

            activity_snapshot = activity_state_machine.compute_from_full_context(
                now=now,
                calendar_events=calendar_events,
                last_interaction_at=state.last_activity_at,
                body_state=body_dict,
                ha_recent_activity=ha_activity,
                first_activity_today=state.first_activity_today,
                has_chatted_today=state.has_chatted_today,
            )

            # Store in subconscious state
            state.activity_state = activity_snapshot.state.value
            state.activity_confidence = activity_snapshot.confidence
            state.activity_reason = activity_snapshot.reason
            state.activity_room = None  # Motion sensors can't identify individuals

            # Compute interruptibility
            hours_since_interaction = None
            if state.last_activity_at:
                hours_since_interaction = (now - state.last_activity_at).total_seconds() / 3600

            # Count recent notifications
            notif_count = 0
            try:
                notif_result = db.execute(text("""
                    SELECT COUNT(*) as cnt FROM notification_log
                    WHERE user_id = :user_id
                      AND sent_at >= NOW() - INTERVAL '1 hour'
                      AND sent = true
                """), {"user_id": user_id}).fetchone()
                notif_count = notif_result.cnt if notif_result else 0
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass

            # Calendar context for interruptibility
            calendar_context = {}
            for evt in calendar_events:
                start = evt.get("start")
                end = evt.get("end")
                if start and end:
                    if isinstance(start, str):
                        start = datetime.fromisoformat(start)
                    if isinstance(end, str):
                        end = datetime.fromisoformat(end)
                    if start.tzinfo is None:
                        start = start.replace(tzinfo=USER_TZ)
                    if end.tzinfo is None:
                        end = end.replace(tzinfo=USER_TZ)
                    title = (evt.get("title") or "").lower()
                    if start <= now <= end and any(kw in title for kw in ["meeting", "call", "sync", "standup"]):
                        calendar_context["in_meeting"] = True
                    minutes_to = (start - now).total_seconds() / 60
                    if 0 < minutes_to < 10:
                        calendar_context["minutes_to_next_event"] = int(minutes_to)

            interruptibility = compute_interruptibility(
                activity=activity_snapshot,
                body_state=body_dict,
                calendar_context=calendar_context if calendar_context else None,
                hours_since_last_interaction=hours_since_interaction,
                notification_count_last_hour=notif_count,
            )

            state.interruptibility_score = interruptibility.score
            state.interruptibility_channel = interruptibility.recommended_channel

            logger.info(
                f"Activity: {state.activity_state} (conf={state.activity_confidence:.2f}), "
                f"Interruptibility: {state.interruptibility_score:.2f} ({state.interruptibility_channel})"
            )

        except Exception as e:
            import traceback
            logger.error(f"Activity state computation failed: {e}\n{traceback.format_exc()}")
            try:
                db.rollback()
            except Exception:
                pass
            state.activity_state = "unknown"
            state.interruptibility_score = 0.5

        # Detect threshold crossings and generate nudges
        nudges = await self._detect_and_generate_nudges(db, user_id, state, now)

        # Update state in database and commit immediately
        await self._update_state(db, user_id, state, now)
        db.commit()

        # Log snapshot for pattern learning (non-critical)
        try:
            await self._log_snapshot(db, user_id, state, nudges, now)
            db.commit()
        except Exception as e:
            logger.warning(f"Snapshot logging failed (non-critical): {e}")
            try:
                db.rollback()
            except Exception:
                pass

        # Write to unified context snapshot (Redis) for cross-system awareness
        try:
            import asyncio
            from app.services.context_writer import update_fields
            ctx_kwargs = {
                "activity_state": state.activity_state or "UNKNOWN",
                "activity_confidence": state.activity_confidence or 0.5,
                "room": state.activity_room,
                "interruptibility": state.interruptibility_score or 0.5,
                "has_chatted_today": state.has_chatted_today,
                "is_past_bedtime": state.is_past_bedtime,
                "mood": state.inferred_mood,
                "energy_level": state.inferred_energy_level,
                "in_flow_state": state.in_flow_state,
            }
            if state.body_state:
                ctx_kwargs.update({
                    "alertness": state.body_state.alertness,
                    "stress_load": state.body_state.stress_load,
                    "blood_sugar": state.body_state.blood_sugar,
                    "circadian_phase": state.body_state.circadian_phase,
                })
            await update_fields(user_id, source="subconscious", **ctx_kwargs)
        except Exception as e:
            logger.debug(f"Unified context snapshot update failed (non-critical): {e}")

        # Refresh open conversation threads in Redis for fast access
        try:
            from app.services.thread_manager import refresh_thread_cache, expire_stale_threads

            class _SyncAsAsyncDB:
                """Minimal wrapper for sync db in async context."""
                def __init__(self, sync_db):
                    self._db = sync_db
                async def execute(self, stmt, params=None):
                    return self._db.execute(stmt, params)
                async def commit(self):
                    self._db.commit()
                async def rollback(self):
                    self._db.rollback()

            db_wrapper = _SyncAsAsyncDB(db)
            await expire_stale_threads(user_id, db_wrapper)
            await refresh_thread_cache(user_id, db_wrapper)
        except Exception as e:
            logger.debug(f"Thread cache refresh failed (non-critical): {e}")

        # Persist body state history for trend analysis (non-critical)
        try:
            db.execute(text("""
                INSERT INTO body_state_history
                (user_id, alertness, stress_load, blood_sugar, circadian_phase,
                 energy_level, mood, in_flow_state, activity_state, recorded_at)
                VALUES
                (:uid, :alertness, :stress, :blood, :circadian,
                 :energy, :mood, :flow, :activity, NOW())
            """), {
                "uid": user_id,
                "alertness": state.body_state.alertness if state.body_state else None,
                "stress": state.body_state.stress_load if state.body_state else None,
                "blood": state.body_state.blood_sugar if state.body_state else None,
                "circadian": state.body_state.circadian_phase if state.body_state else None,
                "energy": state.inferred_energy_level,
                "mood": state.inferred_mood,
                "flow": state.in_flow_state,
                "activity": state.activity_state,
            })
            db.commit()
        except Exception as e:
            logger.debug(f"Body state history insert failed (non-critical): {e}")
            try:
                db.rollback()
            except Exception:
                pass

        # Write Sara's inner monologue journal entry (non-critical)
        try:
            await sara_journal.write_periodic_entry(
                db=db,
                user_id=user_id,
                mood_context=state.mood_context,
                recent_nudges=nudges if nudges else None,
                recent_activity=f"Last presence: {state.hours_since_presence:.1f}h ago" if state.hours_since_presence else None,
                shadow_summary=state.recent_shadow_summary,
                shadow_tasks=state.shadow_tasks,
                conversation_digest=state.recent_conversation_digest,
                activity_state=state.activity_state,
                activity_room=state.activity_room,
            )
            db.commit()
        except Exception as e:
            logger.warning(f"Failed to write journal entry (non-critical): {e}")
            try:
                db.rollback()
            except Exception:
                pass

        # Extract PKG signals from recent conversations (non-critical)
        await self._extract_pkg_signals(db, user_id, state, now)

        # Send push notifications for urgent nudges
        if nudges:
            await self._send_push_notifications(db, user_id, nudges)

        return state

    async def _gather_presence_signals(
        self, db: Session, user_id: str, state: SubconsciousState, now: datetime
    ):
        """
        Gather presence/activity signals from multiple sources:
        - presence_log table (explicit app opens)
        - episode table (chat messages)
        - API activity timestamps

        Determines: when user woke up (first activity), last activity, past bedtime status
        """
        # today_start in local time, then convert to UTC for DB comparisons
        # (DB stores timestamps in UTC)
        today_start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start = today_start_local.astimezone(ZoneInfo('UTC'))

        # Get last activity from presence_log
        presence_result = db.execute(text("""
            SELECT created_at, activity_type
            FROM presence_log
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            LIMIT 1
        """), {"user_id": user_id}).fetchone()

        if presence_result:
            state.last_presence_at = presence_result.created_at
            # presence_log is tz-aware (+00), but handle naive case safely (treat as UTC)
            if presence_result.created_at.tzinfo is None:
                state.last_presence_at = state.last_presence_at.replace(tzinfo=ZoneInfo('UTC')).astimezone(self.tz)
            else:
                state.last_presence_at = state.last_presence_at.astimezone(self.tz)
            state.hours_since_presence = (now - state.last_presence_at).total_seconds() / 3600

        # Get first activity TODAY - determines "wakeup time"
        # Check both presence_log and episode tables
        # Normalize: presence_log is tz-aware, episode is naive (UTC) - convert episode to tz-aware
        first_today_result = db.execute(text("""
            SELECT MIN(activity_time) as first_activity FROM (
                SELECT created_at as activity_time FROM presence_log
                WHERE user_id = :user_id AND created_at >= :today_start
                UNION ALL
                SELECT created_at AT TIME ZONE 'UTC' as activity_time FROM episode
                WHERE user_id = :user_id AND created_at >= :today_start AND role = 'user'
            ) combined
        """), {"user_id": user_id, "today_start": today_start}).fetchone()

        if first_today_result and first_today_result.first_activity:
            state.first_activity_today = first_today_result.first_activity
            # Always convert to user timezone (DB returns UTC)
            if state.first_activity_today.tzinfo is None:
                state.first_activity_today = state.first_activity_today.replace(tzinfo=ZoneInfo('UTC')).astimezone(self.tz)
            else:
                state.first_activity_today = state.first_activity_today.astimezone(self.tz)
            state.hours_since_wakeup = (now - state.first_activity_today).total_seconds() / 3600
            logger.info(f"User woke up at {state.first_activity_today.strftime('%H:%M')}, "
                       f"{state.hours_since_wakeup:.1f} hours ago")

        # Get last activity (most recent interaction)
        # Normalize: presence_log is tz-aware, episode is naive (UTC) - convert episode to tz-aware
        last_activity_result = db.execute(text("""
            SELECT MAX(activity_time) as last_activity FROM (
                SELECT created_at as activity_time FROM presence_log
                WHERE user_id = :user_id
                UNION ALL
                SELECT created_at AT TIME ZONE 'UTC' as activity_time FROM episode
                WHERE user_id = :user_id AND role = 'user'
            ) combined
        """), {"user_id": user_id}).fetchone()

        if last_activity_result and last_activity_result.last_activity:
            state.last_activity_at = last_activity_result.last_activity
            # DB returns tz-aware now, convert to user timezone
            if state.last_activity_at.tzinfo is None:
                state.last_activity_at = state.last_activity_at.replace(tzinfo=ZoneInfo('UTC')).astimezone(self.tz)
            else:
                state.last_activity_at = state.last_activity_at.astimezone(self.tz)

        # Check if user has chatted with Sara today
        chat_result = db.execute(text("""
            SELECT COUNT(*) as chat_count FROM episode
            WHERE user_id = :user_id
              AND created_at >= :today_start
              AND role = 'user'
        """), {"user_id": user_id, "today_start": today_start}).fetchone()

        state.has_chatted_today = chat_result.chat_count > 0 if chat_result else False

        # Check if user is active past bedtime (10 PM)
        if now.hour >= THRESHOLDS['bedtime_hour']:
            # Consider "past bedtime" if there's been activity in the last 30 minutes
            recent_activity = db.execute(text("""
                SELECT COUNT(*) as count FROM (
                    SELECT created_at FROM presence_log
                    WHERE user_id = :user_id AND created_at >= NOW() - INTERVAL '30 minutes'
                    UNION ALL
                    SELECT created_at FROM episode
                    WHERE user_id = :user_id AND created_at >= NOW() - INTERVAL '30 minutes'
                ) combined
            """), {"user_id": user_id}).fetchone()

            state.is_past_bedtime = recent_activity.count > 0 if recent_activity else False

        logger.info(f"Presence: first_today={state.first_activity_today}, "
                   f"has_chatted={state.has_chatted_today}, past_bedtime={state.is_past_bedtime}")

    async def _gather_meal_signals(
        self, db: Session, user_id: str, state: SubconsciousState, now: datetime
    ):
        """Gather meal-related signals"""
        # Get last meal
        result = db.execute(text("""
            SELECT meal_type, logged_at
            FROM food_log
            WHERE user_id = :user_id
            ORDER BY logged_at DESC
            LIMIT 1
        """), {"user_id": user_id}).fetchone()

        if result:
            state.last_meal_type = result.meal_type
            state.last_meal_at = result.logged_at
            if result.logged_at:
                # Make timezone aware - food_log stores naive timestamps in EASTERN time (not UTC!)
                meal_time = result.logged_at
                if meal_time.tzinfo is None:
                    meal_time = meal_time.replace(tzinfo=self.tz)
                else:
                    meal_time = meal_time.astimezone(self.tz)
                delta = now - meal_time
                state.hours_since_meal = delta.total_seconds() / 3600

        # Calculate typical meal windows from last 14 days
        # food_log stores naive timestamps in EASTERN time (not UTC!) - extract hour directly
        meal_windows = {}
        for meal_type in ['breakfast', 'lunch', 'dinner']:
            avg_result = db.execute(text("""
                SELECT
                    AVG(EXTRACT(HOUR FROM logged_at) + EXTRACT(MINUTE FROM logged_at)/60.0) as avg_hour
                FROM food_log
                WHERE user_id = :user_id
                  AND meal_type = :meal_type
                  AND logged_at >= NOW() - INTERVAL '14 days'
            """), {"user_id": user_id, "meal_type": meal_type}).fetchone()

            if avg_result and avg_result.avg_hour:
                avg_hour = float(avg_result.avg_hour)
                # Create a 2-hour window around the average
                start_hour = max(0, avg_hour - 1)
                end_hour = min(24, avg_hour + 1)
                meal_windows[meal_type] = {
                    "avg_hour": round(avg_hour, 1),
                    "window_start": round(start_hour, 1),
                    "window_end": round(end_hour, 1)
                }

        state.typical_meal_windows = meal_windows if meal_windows else None

    async def _gather_conversation_signals(
        self, db: Session, user_id: str, state: SubconsciousState, now: datetime
    ):
        """Gather conversation/chat signals for mood and focus inference using LLM"""
        # Message velocity (messages in last hour for flow detection)
        velocity_result = db.execute(text("""
            SELECT COUNT(*) as msg_count,
                   MIN(created_at) as first_msg,
                   MAX(created_at) as last_msg
            FROM episode
            WHERE user_id = :user_id
              AND created_at >= NOW() - INTERVAL '1 hour'
              AND role = 'user'
        """), {"user_id": user_id}).fetchone()

        if velocity_result and velocity_result.msg_count:
            state.message_velocity = float(velocity_result.msg_count)  # per hour

        # Get recent conversation messages for LLM analysis (user messages only)
        messages_result = db.execute(text("""
            SELECT content, created_at
            FROM episode
            WHERE user_id = :user_id
              AND created_at >= NOW() - INTERVAL '4 hours'
              AND role = 'user'
              AND content IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 25
        """), {"user_id": user_id}).fetchall()

        if messages_result and len(messages_result) >= 2:
            messages = [r.content for r in messages_result if r.content]

            # Use LLM to analyze mood, energy, focus, and flow state
            analysis = await self._llm_analyze_conversation(messages)

            if analysis:
                state.inferred_mood = analysis.get('mood')
                state.inferred_energy_level = analysis.get('energy')
                state.mood_context = analysis.get('context')
                state.current_focus_areas = analysis.get('focus_areas', [])
                state.focus_intensity = analysis.get('focus_intensity')
                state.in_flow_state = analysis.get('in_flow_state', False)

                logger.info(f"LLM analysis: mood={state.inferred_mood}, energy={state.inferred_energy_level}, "
                           f"flow={state.in_flow_state}, focus={state.current_focus_areas}")
                if state.mood_context:
                    logger.info(f"Context: {state.mood_context}")

        # Build conversation digest — both user AND assistant messages
        # so the subconscious knows what was actually discussed
        try:
            digest_result = db.execute(text("""
                SELECT role, content, created_at
                FROM episode
                WHERE user_id = :user_id
                  AND created_at >= NOW() - INTERVAL '4 hours'
                  AND content IS NOT NULL
                  AND role IN ('user', 'assistant')
                ORDER BY created_at ASC
                LIMIT 40
            """), {"user_id": user_id}).fetchall()

            if digest_result and len(digest_result) >= 1:
                lines = []
                for row in digest_result:
                    speaker = "David" if row.role == "user" else "Sara"
                    # Trim very long messages but keep enough for context
                    content = row.content.strip()
                    if len(content) > 500:
                        content = content[:500] + "..."
                    ts = row.created_at.strftime("%I:%M %p") if row.created_at else ""
                    lines.append(f"[{ts}] {speaker}: {content}")
                state.recent_conversation_digest = "\n".join(lines)
                logger.info(f"Built conversation digest: {len(digest_result)} messages")
        except Exception as e:
            logger.debug(f"Failed to build conversation digest: {e}")

    async def _llm_analyze_conversation(self, messages: List[str]) -> Optional[Dict]:
        """
        Use local LLM to analyze recent conversation for mood, energy, and focus.
        Returns structured analysis with context for personalized nudges.
        """
        if not messages:
            return None

        # Format messages for analysis (most recent last)
        conversation = "\n".join(f"- {msg}" for msg in reversed(messages[-20:]))

        prompt = f"""Analyze this user's recent messages to Sara (their AI assistant). Return ONLY valid JSON.

Messages (oldest to newest):
{conversation}

Analyze and return JSON with these fields:
{{
  "mood": "one or two words describing emotional state",
  "energy": 0.0-1.0 (0=exhausted, 0.5=neutral, 1=highly energized),
  "context": "brief note about what's going on (frustration source, excitement reason, etc) - max 50 words",
  "focus_areas": ["list", "of", "topics"] (e.g., coding, fitness, work, planning),
  "focus_intensity": 0.0-1.0 (how deep in a single topic vs scattered),
  "in_flow_state": true/false (sustained focus on one topic with rapid exchanges)
}}

Return ONLY the JSON object, no other text."""

        try:
            # Get active LLM with failover
            llm_url, model = await self._get_active_llm()
            if not llm_url:
                logger.warning("No LLM available for mood analysis")
                return None

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{llm_url}/v1/chat/completions",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3,
                        "max_tokens": 300
                    }
                )

                if response.status_code == 200:
                    result = response.json()
                    content = result['choices'][0]['message']['content'].strip()

                    # Parse JSON from response (handle markdown code blocks)
                    if content.startswith('```'):
                        content = content.split('```')[1]
                        if content.startswith('json'):
                            content = content[4:]
                    content = content.strip()

                    analysis = json.loads(content)

                    # Validate and normalize
                    analysis['energy'] = max(0.0, min(1.0, float(analysis.get('energy', 0.5))))
                    analysis['focus_intensity'] = max(0.0, min(1.0, float(analysis.get('focus_intensity', 0.5))))
                    analysis['in_flow_state'] = bool(analysis.get('in_flow_state', False))
                    analysis['focus_areas'] = analysis.get('focus_areas', [])[:4]

                    return analysis
                else:
                    logger.warning(f"LLM analysis failed: {response.status_code}")
                    return None

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response as JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"LLM analysis error: {e}")
            return None

    async def _gather_health_signals(
        self, db: Session, user_id: str, state: SubconsciousState, now: datetime
    ):
        """Gather health-related signals"""
        # Get last night's sleep
        sleep_result = db.execute(text("""
            SELECT value
            FROM health_metric
            WHERE user_id = :user_id
              AND metric_type = 'sleep_hours'
              AND recorded_at >= NOW() - INTERVAL '24 hours'
            ORDER BY recorded_at DESC
            LIMIT 1
        """), {"user_id": user_id}).fetchone()

        if sleep_result:
            state.last_sleep_hours = float(sleep_result.value)
            if state.last_sleep_hours < 6:
                state.last_sleep_quality = 'poor'
                state.sleep_deficit_hours = 7.0 - state.last_sleep_hours
            elif state.last_sleep_hours < 7:
                state.last_sleep_quality = 'fair'
                state.sleep_deficit_hours = 7.0 - state.last_sleep_hours
            else:
                state.last_sleep_quality = 'good'
                state.sleep_deficit_hours = 0

    async def _gather_system_health(self, state: SubconsciousState):
        """Gather system health signals (LLM backends, docker containers)"""
        # Check LLM backends
        await self._check_llm_backends(state)

        # Check Docker containers (simplified - just check if backend responds)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get("http://10.185.1.180:8000/health")
                state.service_health = {
                    "backend": "healthy" if response.status_code == 200 else "unhealthy"
                }
        except Exception:
            state.service_health = {"backend": "unreachable"}

    async def _check_llm_backends(self, state: SubconsciousState):
        """Check status of LLM backends"""
        async def check_endpoint(url: str) -> str:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    start = datetime.now()
                    response = await client.get(f"{url}/v1/models")
                    elapsed = (datetime.now() - start).total_seconds()

                    if response.status_code == 200:
                        if elapsed > 2.0:
                            return "slow"
                        return "online"
                    return "offline"
            except Exception:
                return "offline"

        # Check primary
        state.llm_primary_status = await check_endpoint(self.llm_primary_url)

        # Check failover
        if self.llm_fallback_url:
            state.llm_failover_status = await check_endpoint(self.llm_fallback_url)
        else:
            state.llm_failover_status = "not_configured"

        # Determine active backend and model
        if state.llm_primary_status == "online":
            state.llm_active_backend = f"{self.llm_primary_url} ({self.primary_model})"
        elif state.llm_failover_status == "online":
            state.llm_active_backend = f"{self.llm_fallback_url} ({self.fallback_model})"
        else:
            state.llm_active_backend = "none_available"

    async def _gather_shadow_signals(
        self, db: Session, user_id: str, state: SubconsciousState, now: datetime
    ):
        """
        Gather signals from recent shadow sessions.
        Pulls summary, tasks, decisions, and questions from wrapped sessions
        within the last 8 hours to inform Sara's context.
        """
        lookback_hours = 8

        # Get recent wrapped shadow sessions with summaries
        sessions_result = db.execute(text("""
            SELECT
                ss.id as session_id,
                ss.context,
                ss.started_at,
                ss.ended_at,
                ssm.full_text,
                ssm.tasks,
                ssm.decisions,
                ssm.questions
            FROM shadow_session ss
            LEFT JOIN shadow_summary ssm ON ssm.session_id = ss.id
            WHERE ss.user_id = :user_id
              AND ss.status = 'wrapped'
              AND ss.ended_at >= NOW() - INTERVAL ':hours hours'
            ORDER BY ss.ended_at DESC
            LIMIT 3
        """.replace(":hours", str(lookback_hours))), {"user_id": user_id}).fetchall()

        if not sessions_result:
            logger.debug("No recent shadow sessions found")
            return

        # Aggregate data from recent sessions
        all_tasks = []
        all_decisions = []
        all_questions = []
        focus_areas = set()
        most_recent_summary = None
        most_recent_session_at = None

        for session in sessions_result:
            # Track most recent session time
            if session.ended_at:
                if most_recent_session_at is None or session.ended_at > most_recent_session_at:
                    most_recent_session_at = session.ended_at
                    most_recent_summary = session.full_text

            # Parse JSON arrays from summary
            if session.tasks:
                try:
                    tasks = json.loads(session.tasks) if isinstance(session.tasks, str) else session.tasks
                    for task in tasks:
                        if isinstance(task, dict):
                            all_tasks.append(task.get('content', str(task)))
                        else:
                            all_tasks.append(str(task))
                except (json.JSONDecodeError, TypeError):
                    pass

            if session.decisions:
                try:
                    decisions = json.loads(session.decisions) if isinstance(session.decisions, str) else session.decisions
                    for decision in decisions:
                        if isinstance(decision, dict):
                            all_decisions.append(decision.get('content', str(decision)))
                        else:
                            all_decisions.append(str(decision))
                except (json.JSONDecodeError, TypeError):
                    pass

            if session.questions:
                try:
                    questions = json.loads(session.questions) if isinstance(session.questions, str) else session.questions
                    for question in questions:
                        if isinstance(question, dict):
                            all_questions.append(question.get('content', str(question)))
                        else:
                            all_questions.append(str(question))
                except (json.JSONDecodeError, TypeError):
                    pass

            # Extract focus areas from context
            if session.context:
                focus_areas.add(session.context)

        # Populate state
        state.recent_shadow_summary = most_recent_summary
        state.last_shadow_session_at = most_recent_session_at
        state.shadow_tasks = all_tasks[:10] if all_tasks else None  # Limit to 10 most recent
        state.shadow_decisions = all_decisions[:10] if all_decisions else None
        state.shadow_questions = all_questions[:10] if all_questions else None
        state.shadow_focus_areas = list(focus_areas)[:5] if focus_areas else None

        if most_recent_session_at:
            hours_ago = (now - most_recent_session_at.replace(tzinfo=self.tz if most_recent_session_at.tzinfo is None else most_recent_session_at.tzinfo)).total_seconds() / 3600
            logger.info(f"Shadow context: {len(all_tasks)} tasks, {len(all_decisions)} decisions, "
                       f"{len(all_questions)} questions from {len(sessions_result)} sessions ({hours_ago:.1f}h ago)")

    async def _detect_and_generate_nudges(
        self, db: Session, user_id: str, state: SubconsciousState, now: datetime
    ) -> List[Dict]:
        """
        Detect threshold crossings and generate nudges.

        Features:
        - Flow state suppression: Non-urgent nudges are held when user is in deep focus
        - Compound conditions: Multiple signals combine for smarter severity
        - Context-aware messages: Uses LLM mood context for personalized nudges
        """
        nudges = []

        # =====================================================
        # MORNING CHECK-IN (15 mins after first activity, if no chat)
        # =====================================================
        morning_eligible = (
            state.first_activity_today and
            state.hours_since_wakeup and
            0.25 <= state.hours_since_wakeup <= 2.0 and
            not state.has_chatted_today
        )
        state.nudge_morning_eligible = bool(morning_eligible)
        if morning_eligible:

            if not await self._nudge_exists_recently(db, user_id, 'morning_checkin', hours=12):
                    hour = now.hour
                    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"

                    nudge = await self._create_nudge(
                        db, user_id,
                        nudge_type='morning_checkin',
                        severity=SEVERITY_GENTLE,
                        title=f"{greeting}! 👋",
                        message="How are you feeling today? I'm here if you want to chat or need help with anything.",
                        action_suggestion="Say hi to Sara",
                        delivery_channel='ios_push',
                        expires_hours=4
                    )
                    nudges.append(nudge)
                    logger.info(f"Generated morning check-in nudge for user {user_id}")

        # =====================================================
        # MEAL NUDGES - DISABLED
        # =====================================================
        # Generic meal notifications are disabled in favor of proactive pattern-based
        # notifications. Sara now learns behavioral patterns during her nightly dream
        # cycle and sends personalized suggestions crafted with LLM awareness.
        #
        # The MorningProactiveService runs at 9 AM and checks detected patterns
        # (e.g., "user runs heat automation when cold") against current conditions,
        # then sends context-aware iOS push notifications.
        #
        # This replaces generic messages like "it's been X hours since you ate" with
        # personalized suggestions like "It's 5°F out - yesterday you had the heat
        # running every 2 hours. Want me to set that up again?"
        # =====================================================

        # =====================================================
        # BEDTIME NUDGE (with context awareness)
        # =====================================================
        state.nudge_bedtime_eligible = bool(state.is_past_bedtime)
        if state.is_past_bedtime:
            if not await self._nudge_exists_recently(db, user_id, 'bedtime', hours=12):
                # Context-aware bedtime message
                if state.mood_context and 'coding' in (state.current_focus_areas or []):
                    message = "It's past 10 PM. I know you're deep in code, but sleep helps with problem-solving. Consider wrapping up."
                elif state.inferred_mood == 'stressed':
                    message = "It's past 10 PM and you seem stressed. Sleep might give you fresh perspective tomorrow."
                else:
                    message = "It's past 10 PM and you're still active. Consider wrapping up for better sleep."

                nudge = await self._create_nudge(
                    db, user_id,
                    nudge_type='bedtime',
                    severity=SEVERITY_GENTLE,
                    title="Time to wind down?",
                    message=message,
                    action_suggestion="Start your bedtime routine",
                    delivery_channel='ios_push',
                    expires_hours=8
                )
                nudges.append(nudge)

        # =====================================================
        # SLEEP DEFICIT (compound with mood)
        # =====================================================
        state.nudge_sleep_deficit = float(state.sleep_deficit_hours) if state.sleep_deficit_hours and state.sleep_deficit_hours > 1.0 else 0.0
        if state.sleep_deficit_hours and state.sleep_deficit_hours > 1.0:
            if not await self._nudge_exists_recently(db, user_id, 'sleep_deficit', hours=24):
                # More urgent if mood is suffering
                if state.inferred_mood in ['tired', 'frustrated', 'stressed'] and state.sleep_deficit_hours > 1.5:
                    message = f"You got {state.last_sleep_hours:.1f} hours last night and seem {state.inferred_mood} today. Prioritize rest tonight."
                    severity = SEVERITY_GENTLE
                else:
                    message = f"You got {state.last_sleep_hours:.1f} hours last night. Try to get extra rest tonight."
                    severity = SEVERITY_INFO

                nudge = await self._create_nudge(
                    db, user_id,
                    nudge_type='sleep_deficit',
                    severity=severity,
                    title="Sleep debt accumulating",
                    message=message,
                    delivery_channel='passive_display',
                    expires_hours=24
                )
                nudges.append(nudge)

        # NOTE: Heartbeat agent checks are now handled by the unified heartbeat
        # (app.services.unified_heartbeat) which runs as a Celery task every 15 min
        # with full run-to-run memory and topic-based notification dedup.

        return nudges

    # NOTE: _run_heartbeat_agent, _evaluate_heartbeat_items, _evaluate_heartbeat_check,
    # and _execute_ha_action methods have been removed. All heartbeat checks are now
    # handled by the unified agent (app.services.unified_agent).

    async def _nudge_exists_recently(
        self, db: Session, user_id: str, nudge_type: str, hours: int
    ) -> bool:
        """Check if a nudge of this type was created recently"""
        result = db.execute(text("""
            SELECT id FROM subconscious_nudge
            WHERE user_id = :user_id
              AND nudge_type = :nudge_type
              AND created_at >= NOW() - INTERVAL ':hours hours'
        """.replace(":hours", str(hours))), {
            "user_id": user_id,
            "nudge_type": nudge_type
        }).fetchone()

        return result is not None

    async def _create_nudge(
        self, db: Session, user_id: str,
        nudge_type: str, severity: str, title: str, message: str,
        delivery_channel: str, expires_hours: int,
        action_suggestion: Optional[str] = None
    ) -> Dict:
        """Create and store a nudge"""
        now = datetime.now(self.tz)
        nudge_id = str(uuid.uuid4())

        db.execute(text("""
            INSERT INTO subconscious_nudge
            (id, user_id, nudge_type, severity, title, message, action_suggestion,
             delivery_channel, expires_at, status, created_at)
            VALUES
            (:id, :user_id, :nudge_type, :severity, :title, :message, :action_suggestion,
             :delivery_channel, :expires_at, 'pending', :created_at)
        """), {
            "id": nudge_id,
            "user_id": user_id,
            "nudge_type": nudge_type,
            "severity": severity,
            "title": title,
            "message": message,
            "action_suggestion": action_suggestion,
            "delivery_channel": delivery_channel,
            "expires_at": now + timedelta(hours=expires_hours),
            "created_at": now
        })

        nudge = {
            "id": nudge_id,
            "nudge_type": nudge_type,
            "severity": severity,
            "title": title,
            "message": message,
            "action_suggestion": action_suggestion,
            "delivery_channel": delivery_channel
        }

        logger.info(f"Created nudge: {nudge_type} ({severity}) for user {user_id}")
        return nudge

    async def _update_state(self, db: Session, user_id: str, state: SubconsciousState, now: datetime):
        """Update or insert state in database"""
        # Check if state exists
        existing = db.execute(text(
            "SELECT id FROM subconscious_state WHERE user_id = :user_id"
        ), {"user_id": user_id}).fetchone()

        # Serialize body state if present
        body_state_json = None
        if state.body_state:
            from dataclasses import asdict as body_asdict
            body_state_json = json.dumps(body_asdict(state.body_state), default=str)

        state_data = {
            "user_id": user_id,
            "last_meal_type": state.last_meal_type,
            "last_meal_at": state.last_meal_at,
            "hours_since_meal": state.hours_since_meal,
            "typical_meal_windows": json.dumps(state.typical_meal_windows) if state.typical_meal_windows else None,
            "inferred_energy_level": state.inferred_energy_level,
            "inferred_mood": state.inferred_mood,
            "mood_context": state.mood_context,
            "message_velocity": state.message_velocity,
            "in_flow_state": state.in_flow_state,
            "current_focus_areas": json.dumps(state.current_focus_areas) if state.current_focus_areas else None,
            "focus_intensity": state.focus_intensity,
            "last_sleep_hours": state.last_sleep_hours,
            "last_sleep_quality": state.last_sleep_quality,
            "sleep_deficit_hours": state.sleep_deficit_hours,
            "docker_health": json.dumps(state.docker_health) if state.docker_health else None,
            "service_health": json.dumps(state.service_health) if state.service_health else None,
            "llm_primary_status": state.llm_primary_status,
            "llm_failover_status": state.llm_failover_status,
            "llm_active_backend": state.llm_active_backend,
            "last_presence_at": state.last_presence_at,
            "hours_since_presence": state.hours_since_presence,
            "first_activity_today": state.first_activity_today,
            "last_activity_at": state.last_activity_at,
            "has_chatted_today": state.has_chatted_today,
            "hours_since_wakeup": state.hours_since_wakeup,
            "is_past_bedtime": state.is_past_bedtime,
            "is_waking_hours": state.is_waking_hours,
            "body_state": body_state_json,
            "body_state_context": state.body_state_context,
            # Activity state & interruptibility
            "activity_state": state.activity_state,
            "activity_confidence": state.activity_confidence,
            "activity_reason": state.activity_reason,
            "activity_room": state.activity_room,
            "interruptibility_score": state.interruptibility_score,
            "interruptibility_channel": state.interruptibility_channel,
            # Nudge eligibility flags
            "nudge_morning_eligible": state.nudge_morning_eligible,
            "nudge_bedtime_eligible": state.nudge_bedtime_eligible,
            "nudge_sleep_deficit": state.nudge_sleep_deficit,
            # Shadow session context
            "recent_shadow_summary": state.recent_shadow_summary,
            "shadow_tasks": json.dumps(state.shadow_tasks) if state.shadow_tasks else None,
            "shadow_decisions": json.dumps(state.shadow_decisions) if state.shadow_decisions else None,
            "shadow_questions": json.dumps(state.shadow_questions) if state.shadow_questions else None,
            "last_shadow_session_at": state.last_shadow_session_at,
            "shadow_focus_areas": json.dumps(state.shadow_focus_areas) if state.shadow_focus_areas else None,
            "updated_at": now
        }

        if existing:
            # Update
            db.execute(text("""
                UPDATE subconscious_state SET
                    last_meal_type = :last_meal_type,
                    last_meal_at = :last_meal_at,
                    hours_since_meal = :hours_since_meal,
                    typical_meal_windows = :typical_meal_windows,
                    inferred_energy_level = :inferred_energy_level,
                    inferred_mood = :inferred_mood,
                    mood_context = :mood_context,
                    message_velocity = :message_velocity,
                    in_flow_state = :in_flow_state,
                    current_focus_areas = :current_focus_areas,
                    focus_intensity = :focus_intensity,
                    last_sleep_hours = :last_sleep_hours,
                    last_sleep_quality = :last_sleep_quality,
                    sleep_deficit_hours = :sleep_deficit_hours,
                    docker_health = :docker_health,
                    service_health = :service_health,
                    llm_primary_status = :llm_primary_status,
                    llm_failover_status = :llm_failover_status,
                    llm_active_backend = :llm_active_backend,
                    last_presence_at = :last_presence_at,
                    hours_since_presence = :hours_since_presence,
                    first_activity_today = :first_activity_today,
                    last_activity_at = :last_activity_at,
                    has_chatted_today = :has_chatted_today,
                    hours_since_wakeup = :hours_since_wakeup,
                    is_past_bedtime = :is_past_bedtime,
                    is_waking_hours = :is_waking_hours,
                    body_state = :body_state,
                    body_state_context = :body_state_context,
                    activity_state = :activity_state,
                    activity_confidence = :activity_confidence,
                    activity_reason = :activity_reason,
                    activity_room = :activity_room,
                    interruptibility_score = :interruptibility_score,
                    interruptibility_channel = :interruptibility_channel,
                    nudge_morning_eligible = :nudge_morning_eligible,
                    nudge_bedtime_eligible = :nudge_bedtime_eligible,
                    nudge_sleep_deficit = :nudge_sleep_deficit,
                    recent_shadow_summary = :recent_shadow_summary,
                    shadow_tasks = :shadow_tasks,
                    shadow_decisions = :shadow_decisions,
                    shadow_questions = :shadow_questions,
                    last_shadow_session_at = :last_shadow_session_at,
                    shadow_focus_areas = :shadow_focus_areas,
                    updated_at = :updated_at
                WHERE user_id = :user_id
            """), state_data)
        else:
            # Insert
            state_data["id"] = str(uuid.uuid4())
            db.execute(text("""
                INSERT INTO subconscious_state
                (id, user_id, last_meal_type, last_meal_at, hours_since_meal, typical_meal_windows,
                 inferred_energy_level, inferred_mood, mood_context, message_velocity, in_flow_state,
                 current_focus_areas, focus_intensity, last_sleep_hours, last_sleep_quality,
                 sleep_deficit_hours, docker_health, service_health, llm_primary_status,
                 llm_failover_status, llm_active_backend, last_presence_at, hours_since_presence,
                 first_activity_today, last_activity_at, has_chatted_today, hours_since_wakeup,
                 is_past_bedtime, is_waking_hours, body_state, body_state_context,
                 activity_state, activity_confidence, activity_reason, activity_room,
                 interruptibility_score, interruptibility_channel,
                 nudge_morning_eligible, nudge_bedtime_eligible, nudge_sleep_deficit,
                 recent_shadow_summary, shadow_tasks, shadow_decisions, shadow_questions,
                 last_shadow_session_at, shadow_focus_areas, updated_at, created_at)
                VALUES
                (:id, :user_id, :last_meal_type, :last_meal_at, :hours_since_meal, :typical_meal_windows,
                 :inferred_energy_level, :inferred_mood, :mood_context, :message_velocity, :in_flow_state,
                 :current_focus_areas, :focus_intensity, :last_sleep_hours, :last_sleep_quality,
                 :sleep_deficit_hours, :docker_health, :service_health, :llm_primary_status,
                 :llm_failover_status, :llm_active_backend, :last_presence_at, :hours_since_presence,
                 :first_activity_today, :last_activity_at, :has_chatted_today, :hours_since_wakeup,
                 :is_past_bedtime, :is_waking_hours, :body_state, :body_state_context,
                 :activity_state, :activity_confidence, :activity_reason, :activity_room,
                 :interruptibility_score, :interruptibility_channel,
                 :nudge_morning_eligible, :nudge_bedtime_eligible, :nudge_sleep_deficit,
                 :recent_shadow_summary, :shadow_tasks, :shadow_decisions, :shadow_questions,
                 :last_shadow_session_at, :shadow_focus_areas, :updated_at, :updated_at)
            """), state_data)

    async def _log_snapshot(
        self, db: Session, user_id: str, state: SubconsciousState,
        nudges: List[Dict], now: datetime
    ):
        """Log state snapshot for pattern learning"""
        snapshot_id = str(uuid.uuid4())

        db.execute(text("""
            INSERT INTO subconscious_log
            (id, user_id, snapshot_at, state_snapshot, nudges_generated, created_at)
            VALUES
            (:id, :user_id, :snapshot_at, :state_snapshot, :nudges_generated, :created_at)
        """), {
            "id": snapshot_id,
            "user_id": user_id,
            "snapshot_at": now,
            "state_snapshot": json.dumps(asdict(state), default=str),
            "nudges_generated": json.dumps(nudges) if nudges else None,
            "created_at": now
        })

    async def _extract_pkg_signals(self, db: Session, user_id: str, state: SubconsciousState, now: datetime):
        """Extract lightweight PKG signals from recent conversations (last 2 hours)"""
        try:
            from app.services.pkg_extractor import pkg_extractor

            # Get recent conversation messages (last 2 hours)
            two_hours_ago = now - timedelta(hours=2)
            result = db.execute(text("""
                SELECT role, content FROM episode
                WHERE user_id = :user_id
                AND created_at >= :since
                AND role IN ('user', 'assistant')
                ORDER BY created_at ASC
                LIMIT 30
            """), {"user_id": user_id, "since": two_hours_ago}).fetchall()

            if not result or len(result) < 2:
                return

            messages = [{"role": row.role, "content": row.content} for row in result]

            extraction = await pkg_extractor.lightweight_extract(messages, user_id)
            total = extraction.get("stats", {}).get("total", 0)
            if total > 0:
                logger.info(f"PKG: Extracted {total} facts from subconscious cycle")

        except Exception as e:
            logger.warning(f"PKG signal extraction failed (non-critical): {e}")
            try:
                db.rollback()
            except Exception:
                pass

    async def _send_push_notifications(self, db: Session, user_id: str, nudges: List[Dict]):
        """Send iOS push notifications for nudges that require it.

        Routes through the unified notification pipeline for topic-based dedup.
        """
        from app.services.unified_notification import send_notification as unified_send

        push_nudges = [n for n in nudges if n.get('delivery_channel') == 'ios_push']

        if not push_nudges:
            return

        for nudge in push_nudges:
            nudge_type = nudge.get('nudge_type', 'general')
            topic = f"subconscious:{nudge_type}"

            try:
                # Route through unified pipeline (uses sync-compatible fallback
                # since subconscious_service uses sync Session, not AsyncSession)
                result = await unified_send(
                    user_id=user_id,
                    title=nudge['title'],
                    message=nudge['message'],
                    priority="normal",
                    topic=topic,
                    category="checkin" if nudge_type in ['morning_checkin', 'bedtime'] else "general",
                    source="subconscious",
                    cooldown_hours=4.0 if nudge_type == 'morning_checkin' else 8.0,
                    db=None,  # Use sync fallback since we have a sync Session
                )

                if result.get("sent"):
                    # Mark nudge as delivered
                    db.execute(text("""
                        UPDATE subconscious_nudge
                        SET delivered_at = NOW(), status = 'delivered'
                        WHERE id = :nudge_id
                    """), {"nudge_id": nudge['id']})
                    logger.info(f"Sent subconscious nudge via unified pipeline: {nudge['title']}")
                else:
                    logger.info(f"Subconscious nudge blocked by dedup: {nudge['title']} reason={result.get('reason')}")

            except Exception as e:
                logger.error(f"Failed to send nudge via unified pipeline: {e}")
                try:
                    db.rollback()
                except Exception:
                    pass

    # Public API methods for external access

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
