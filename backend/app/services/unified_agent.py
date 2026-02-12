"""
Unified Agent — Sara's consolidated autonomous mind.

Replaces both:
- SubconsciousWorker (systemd, every 30min) — sensing, state computation, nudges, journal
- UnifiedHeartbeatAgent (Celery, every 15min) — LLM agent loop, notifications, journal

4-phase cycle every 15 minutes:
  Phase 1: SENSE  — gather signals, compute body/activity/interruptibility, write state
  Phase 2: THINK  — build context from fresh Phase 1 data, run LLM agent loop
  Phase 3: ACT    — single notification pipeline, interruptibility-aware delivery
  Phase 4: RECORD — one journal entry, agent_run_log, subconscious_log, PKG extraction
"""

import json
import logging
import re
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import get_background_llm_client
from app.core.timezone import USER_TIMEZONE
from app.services.body_state_service import body_state_service, BodyStateEstimate
from app.services.ha_control_service import ha_control
from app.services.sara_journal_service import sara_journal
from app.services.unified_notification import (
    send_notification,
    send_consolidated_notification,
    get_todays_notifications,
)

try:
    from app.skills import get_skill_injector
    SKILLS_AVAILABLE = True
except ImportError:
    SKILLS_AVAILABLE = False
    get_skill_injector = None

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"
HEARTBEAT_FILE_PATH = Path(__file__).parent.parent.parent / "data" / "HEARTBEAT.md"
USER_TZ = USER_TIMEZONE

# Phrases to strip from body state context — never become notification triggers
_NUTRITION_PHRASES = [
    "nutrition:", "blood sugar", "blood_sugar", "fuel remaining",
    "running on empty", "getting hungry", "recently ate", "well-fueled",
    "hasn't eaten", "meal", "hours of fuel",
]

# Waking hours
WAKING_HOURS_START = 6
WAKING_HOURS_END = 22

# Quiet mode allowlists — safety-relevant actions/categories that bypass suppression
QUIET_MODE_ALLOWED_ACTIONS = {"lock_all", "all_lights_off", "home_control"}
QUIET_MODE_ALLOWED_CATEGORIES = {"security", "home"}


def _strip_nutrition_context(body_ctx: Optional[str]) -> str:
    if not body_ctx:
        return ""
    lines = body_ctx.split("\n")
    filtered = [
        line for line in lines
        if not any(phrase in line.lower() for phrase in _NUTRITION_PHRASES)
    ]
    return "\n".join(filtered).strip()[:150]


# ─── Phase 1: SensedState dataclass ──────────────────────────────

@dataclass
class SensedState:
    """Output of Phase 1 (SENSE). Fresh data for Phase 2."""
    # Presence
    last_presence_at: Optional[datetime] = None
    hours_since_presence: Optional[float] = None
    first_activity_today: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None
    has_chatted_today: bool = False
    hours_since_wakeup: Optional[float] = None
    is_past_bedtime: bool = False
    is_waking_hours: bool = True

    # Meals
    last_meal_type: Optional[str] = None
    last_meal_at: Optional[datetime] = None
    hours_since_meal: Optional[float] = None
    typical_meal_windows: Optional[Dict] = None

    # Conversations (raw — no separate LLM call)
    message_velocity: Optional[float] = None
    recent_conversation_digest: Optional[str] = None

    # Mood/energy — backfilled from Phase 2 agent THOUGHT
    inferred_energy_level: Optional[float] = None
    inferred_mood: Optional[str] = None
    mood_context: Optional[str] = None
    in_flow_state: bool = False
    current_focus_areas: Optional[List[str]] = None
    focus_intensity: Optional[float] = None

    # Sleep
    last_sleep_hours: Optional[float] = None
    last_sleep_quality: Optional[str] = None
    sleep_deficit_hours: Optional[float] = None

    # System health
    llm_primary_status: Optional[str] = None
    llm_failover_status: Optional[str] = None
    llm_active_backend: Optional[str] = None
    service_health: Optional[Dict] = None

    # Body state
    body_state: Optional[BodyStateEstimate] = None
    body_state_context: Optional[str] = None

    # Activity state & interruptibility
    activity_state: Optional[str] = None
    activity_confidence: Optional[float] = None
    activity_reason: Optional[str] = None
    activity_room: Optional[str] = None
    interruptibility_score: Optional[float] = None
    interruptibility_channel: Optional[str] = None

    # Nudge eligibility
    nudge_morning_eligible: bool = False
    nudge_bedtime_eligible: bool = False
    nudge_sleep_deficit: float = 0.0

    # Shadow sessions
    recent_shadow_summary: Optional[str] = None
    shadow_tasks: Optional[List[str]] = None
    shadow_decisions: Optional[List[str]] = None
    shadow_questions: Optional[List[str]] = None
    last_shadow_session_at: Optional[datetime] = None
    shadow_focus_areas: Optional[List[str]] = None

    # NEW signals
    recent_notes: Optional[List[Dict]] = None
    habits_today: Optional[Dict] = None
    active_learning: Optional[Dict] = None
    recent_documents: Optional[List[Dict]] = None
    active_automations: Optional[Dict] = None


# ─── Phase 1: SensingPhase ───────────────────────────────────────

class SensingPhase:
    """
    Gathers all signals and computes derived state.
    Extracted from SubconsciousService.process_user().
    No LLM calls — pure data gathering and computation.
    """

    def __init__(self):
        from app.core.config import settings
        self.tz = USER_TZ
        self.llm_primary_url = settings.llm_primary_url.replace('/v1', '')
        self.llm_fallback_url = "http://10.185.1.8:11434"
        self.primary_model = "gpt-oss:120b"
        self.fallback_model = "gpt-oss:20b"

    async def run(self, db: AsyncSession, user_id: str) -> SensedState:
        """Run all signal gathering and state computation."""
        now = datetime.now(self.tz)
        state = SensedState()
        state.is_waking_hours = WAKING_HOURS_START <= now.hour < WAKING_HOURS_END

        # Core signals (order matters — presence first)
        await self._gather_presence(db, user_id, state, now)
        await self._gather_meals(db, user_id, state, now)
        await self._gather_conversations(db, user_id, state, now)
        await self._gather_health(db, user_id, state)
        await self._gather_system_health(state)
        await self._gather_shadow(db, user_id, state, now)

        # New signals
        await self._gather_notes(db, user_id, state)
        await self._gather_habits(db, user_id, state, now)
        await self._gather_learning(db, user_id, state)
        await self._gather_documents(db, user_id, state)
        await self._gather_automations(db, user_id, state)

        # Body state estimation
        await self._compute_body_state(db, user_id, state)

        # Activity state & interruptibility
        await self._compute_activity_state(db, user_id, state, now)

        # Nudge eligibility flags (agent decides whether to act)
        self._compute_nudge_eligibility(state, now)

        # Persist state to DB + Redis
        await self._persist_state(db, user_id, state, now)

        return state

    # ── Signal gatherers ──

    async def _gather_presence(self, db: AsyncSession, user_id: str, state: SensedState, now: datetime):
        """Gather activity signals from chat interactions only (no home presence)."""
        today_start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start = today_start_local.astimezone(ZoneInfo('UTC'))

        # First chat activity today
        try:
            result = await db.execute(text("""
                SELECT MIN(created_at) as first_activity
                FROM episode
                WHERE user_id = :user_id AND created_at >= :today_start AND role = 'user'
            """), {"user_id": user_id, "today_start": today_start})
            row = result.fetchone()
            if row and row.first_activity:
                ts = row.first_activity
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=ZoneInfo('UTC')).astimezone(self.tz)
                else:
                    ts = ts.astimezone(self.tz)
                state.first_activity_today = ts
                state.hours_since_wakeup = (now - ts).total_seconds() / 3600
        except Exception as e:
            logger.debug(f"First activity query failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass

        # Last chat activity
        try:
            result = await db.execute(text("""
                SELECT MAX(created_at) as last_activity
                FROM episode
                WHERE user_id = :user_id AND role = 'user'
            """), {"user_id": user_id})
            row = result.fetchone()
            if row and row.last_activity:
                ts = row.last_activity
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=ZoneInfo('UTC')).astimezone(self.tz)
                else:
                    ts = ts.astimezone(self.tz)
                state.last_activity_at = ts
                state.last_presence_at = ts
                state.hours_since_presence = (now - ts).total_seconds() / 3600
        except Exception as e:
            logger.debug(f"Last activity query failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass

        # Has chatted today
        try:
            result = await db.execute(text("""
                SELECT COUNT(*) as cnt FROM episode
                WHERE user_id = :user_id AND created_at >= :today_start AND role = 'user'
            """), {"user_id": user_id, "today_start": today_start})
            row = result.fetchone()
            state.has_chatted_today = row.cnt > 0 if row else False
        except Exception as e:
            logger.debug(f"Chat count query failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass

        # Past bedtime (based on recent chat only)
        if now.hour >= 22:
            try:
                result = await db.execute(text("""
                    SELECT COUNT(*) as cnt FROM episode
                    WHERE user_id = :user_id AND created_at >= NOW() - INTERVAL '30 minutes'
                """), {"user_id": user_id})
                row = result.fetchone()
                state.is_past_bedtime = row.cnt > 0 if row else False
            except Exception as e:
                logger.debug(f"Bedtime query failed: {e}")
                try:
                    await db.rollback()
                except Exception:
                    pass

    async def _gather_meals(self, db: AsyncSession, user_id: str, state: SensedState, now: datetime):
        try:
            result = await db.execute(text("""
                SELECT meal_type, logged_at FROM food_log
                WHERE user_id = :user_id ORDER BY logged_at DESC LIMIT 1
            """), {"user_id": user_id})
            row = result.fetchone()
            if row:
                state.last_meal_type = row.meal_type
                state.last_meal_at = row.logged_at
                if row.logged_at:
                    meal_time = row.logged_at
                    if meal_time.tzinfo is None:
                        meal_time = meal_time.replace(tzinfo=self.tz)
                    else:
                        meal_time = meal_time.astimezone(self.tz)
                    state.hours_since_meal = (now - meal_time).total_seconds() / 3600
        except Exception as e:
            logger.debug(f"Meal query failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass

        # Typical meal windows
        try:
            meal_windows = {}
            for meal_type in ['breakfast', 'lunch', 'dinner']:
                result = await db.execute(text("""
                    SELECT AVG(EXTRACT(HOUR FROM logged_at) + EXTRACT(MINUTE FROM logged_at)/60.0) as avg_hour
                    FROM food_log
                    WHERE user_id = :user_id AND meal_type = :meal_type
                      AND logged_at >= NOW() - INTERVAL '14 days'
                """), {"user_id": user_id, "meal_type": meal_type})
                row = result.fetchone()
                if row and row.avg_hour:
                    avg_hour = float(row.avg_hour)
                    meal_windows[meal_type] = {
                        "avg_hour": round(avg_hour, 1),
                        "window_start": round(max(0, avg_hour - 1), 1),
                        "window_end": round(min(24, avg_hour + 1), 1),
                    }
            state.typical_meal_windows = meal_windows if meal_windows else None
        except Exception as e:
            logger.debug(f"Meal windows query failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass

    async def _gather_conversations(self, db: AsyncSession, user_id: str, state: SensedState, now: datetime):
        """Gather conversation signals — raw digest only, no LLM mood call."""
        # Message velocity
        try:
            result = await db.execute(text("""
                SELECT COUNT(*) as msg_count FROM episode
                WHERE user_id = :user_id AND created_at >= NOW() - INTERVAL '1 hour' AND role = 'user'
            """), {"user_id": user_id})
            row = result.fetchone()
            if row and row.msg_count:
                state.message_velocity = float(row.msg_count)
        except Exception as e:
            logger.debug(f"Velocity query failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass

        # Conversation digest (both user + assistant for context)
        try:
            result = await db.execute(text("""
                SELECT role, content, created_at FROM episode
                WHERE user_id = :user_id AND created_at >= NOW() - INTERVAL '4 hours'
                  AND content IS NOT NULL AND role IN ('user', 'assistant')
                ORDER BY created_at ASC LIMIT 40
            """), {"user_id": user_id})
            rows = result.fetchall()
            if rows:
                lines = []
                for row in rows:
                    speaker = "David" if row.role == "user" else "Sara"
                    content = row.content.strip()
                    if len(content) > 500:
                        content = content[:500] + "..."
                    ts = row.created_at.strftime("%I:%M %p") if row.created_at else ""
                    lines.append(f"[{ts}] {speaker}: {content}")
                state.recent_conversation_digest = "\n".join(lines)
        except Exception as e:
            logger.debug(f"Conversation digest failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass

    async def _gather_health(self, db: AsyncSession, user_id: str, state: SensedState):
        try:
            result = await db.execute(text("""
                SELECT value FROM health_metric
                WHERE user_id = :user_id AND metric_type = 'sleep_hours'
                  AND recorded_at >= NOW() - INTERVAL '24 hours'
                ORDER BY recorded_at DESC LIMIT 1
            """), {"user_id": user_id})
            row = result.fetchone()
            if row:
                state.last_sleep_hours = float(row.value)
                if state.last_sleep_hours < 6:
                    state.last_sleep_quality = 'poor'
                    state.sleep_deficit_hours = 7.0 - state.last_sleep_hours
                elif state.last_sleep_hours < 7:
                    state.last_sleep_quality = 'fair'
                    state.sleep_deficit_hours = 7.0 - state.last_sleep_hours
                else:
                    state.last_sleep_quality = 'good'
                    state.sleep_deficit_hours = 0
        except Exception as e:
            logger.debug(f"Health query failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass

    async def _gather_system_health(self, state: SensedState):
        async def check_endpoint(url: str) -> str:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    start = datetime.now()
                    response = await client.get(f"{url}/v1/models")
                    elapsed = (datetime.now() - start).total_seconds()
                    if response.status_code == 200:
                        return "slow" if elapsed > 2.0 else "online"
                    return "offline"
            except Exception:
                return "offline"

        state.llm_primary_status = await check_endpoint(self.llm_primary_url)
        state.llm_failover_status = await check_endpoint(self.llm_fallback_url)

        if state.llm_primary_status == "online":
            state.llm_active_backend = f"{self.llm_primary_url} ({self.primary_model})"
        elif state.llm_failover_status == "online":
            state.llm_active_backend = f"{self.llm_fallback_url} ({self.fallback_model})"
        else:
            state.llm_active_backend = "none_available"

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get("http://10.185.1.180:8000/health")
                state.service_health = {"backend": "healthy" if response.status_code == 200 else "unhealthy"}
        except Exception:
            state.service_health = {"backend": "unreachable"}

    async def _gather_shadow(self, db: AsyncSession, user_id: str, state: SensedState, now: datetime):
        try:
            result = await db.execute(text("""
                SELECT ss.context, ss.ended_at, ssm.full_text, ssm.tasks, ssm.decisions, ssm.questions
                FROM shadow_session ss
                LEFT JOIN shadow_summary ssm ON ssm.session_id = ss.id
                WHERE ss.user_id = :user_id AND ss.status = 'wrapped'
                  AND ss.ended_at >= NOW() - INTERVAL '8 hours'
                ORDER BY ss.ended_at DESC LIMIT 3
            """), {"user_id": user_id})
            rows = result.fetchall()
        except Exception as e:
            logger.debug(f"Shadow query failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass
            return

        if not rows:
            return

        all_tasks, all_decisions, all_questions = [], [], []
        focus_areas = set()
        most_recent_summary = None
        most_recent_at = None

        for session in rows:
            if session.ended_at:
                if most_recent_at is None or session.ended_at > most_recent_at:
                    most_recent_at = session.ended_at
                    most_recent_summary = session.full_text

            for attr_name, target_list in [
                ("tasks", all_tasks), ("decisions", all_decisions), ("questions", all_questions)
            ]:
                raw = getattr(session, attr_name, None)
                if raw:
                    try:
                        items = json.loads(raw) if isinstance(raw, str) else raw
                        for item in items:
                            if isinstance(item, dict):
                                target_list.append(item.get('content', str(item)))
                            else:
                                target_list.append(str(item))
                    except (json.JSONDecodeError, TypeError):
                        pass

            if session.context:
                focus_areas.add(session.context)

        state.recent_shadow_summary = most_recent_summary
        state.last_shadow_session_at = most_recent_at
        state.shadow_tasks = all_tasks[:10] if all_tasks else None
        state.shadow_decisions = all_decisions[:10] if all_decisions else None
        state.shadow_questions = all_questions[:10] if all_questions else None
        state.shadow_focus_areas = list(focus_areas)[:5] if focus_areas else None

    # ── NEW signal gatherers ──

    async def _gather_notes(self, db: AsyncSession, user_id: str, state: SensedState):
        """Recently modified notes (24h)."""
        try:
            result = await db.execute(text("""
                SELECT id, title, updated_at FROM note
                WHERE user_id = :user_id AND updated_at >= NOW() - INTERVAL '24 hours'
                ORDER BY updated_at DESC LIMIT 10
            """), {"user_id": user_id})
            rows = result.fetchall()
            if rows:
                state.recent_notes = [
                    {"title": r.title, "updated_at": r.updated_at.isoformat() if r.updated_at else None}
                    for r in rows
                ]
        except Exception as e:
            logger.debug(f"Notes query failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass

    async def _gather_habits(self, db: AsyncSession, user_id: str, state: SensedState, now: datetime):
        """Today's habit completions, streaks, overdue items."""
        try:
            today_str = now.strftime('%Y-%m-%d')
            result = await db.execute(text("""
                SELECT h.id, h.name, h.frequency,
                       (SELECT COUNT(*) FROM habit_completion hc
                        WHERE hc.habit_id = h.id AND hc.completed_date = :today) as done_today,
                       h.current_streak
                FROM habit h
                WHERE h.user_id = :user_id AND h.is_active = true
                ORDER BY h.name
            """), {"user_id": user_id, "today": today_str})
            rows = result.fetchall()
            if rows:
                completed = [r for r in rows if r.done_today > 0]
                pending = [r for r in rows if r.done_today == 0]
                state.habits_today = {
                    "total": len(rows),
                    "completed": len(completed),
                    "pending": [{"name": r.name, "streak": r.current_streak} for r in pending[:5]],
                    "top_streaks": [
                        {"name": r.name, "streak": r.current_streak}
                        for r in sorted(rows, key=lambda x: x.current_streak or 0, reverse=True)[:3]
                        if (r.current_streak or 0) > 0
                    ],
                }
        except Exception as e:
            logger.debug(f"Habits query failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass

    async def _gather_learning(self, db: AsyncSession, user_id: str, state: SensedState):
        """Active learning topics, mastery levels, overdue reviews."""
        try:
            result = await db.execute(text("""
                SELECT lt.id, lt.title, lt.mastery_level, lt.status,
                       (SELECT COUNT(*) FROM learning_progress lp
                        WHERE lp.topic_id = lt.id AND lp.next_review_at <= NOW()) as overdue_count
                FROM learning_topic lt
                WHERE lt.user_id = :user_id AND lt.status = 'active'
                ORDER BY lt.updated_at DESC LIMIT 5
            """), {"user_id": user_id})
            rows = result.fetchall()
            if rows:
                state.active_learning = {
                    "topics": [
                        {
                            "title": r.title,
                            "mastery": f"{(r.mastery_level or 0):.0%}",
                            "overdue_reviews": r.overdue_count or 0,
                        }
                        for r in rows
                    ],
                    "total_overdue": sum(r.overdue_count or 0 for r in rows),
                }
        except Exception as e:
            logger.debug(f"Learning query failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass

    async def _gather_documents(self, db: AsyncSession, user_id: str, state: SensedState):
        """Recent document uploads (48h)."""
        try:
            result = await db.execute(text("""
                SELECT filename, created_at FROM document
                WHERE user_id = :user_id AND created_at >= NOW() - INTERVAL '48 hours'
                ORDER BY created_at DESC LIMIT 5
            """), {"user_id": user_id})
            rows = result.fetchall()
            if rows:
                state.recent_documents = [
                    {"filename": r.filename, "uploaded_at": r.created_at.isoformat() if r.created_at else None}
                    for r in rows
                ]
        except Exception as e:
            logger.debug(f"Documents query failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass

    async def _gather_automations(self, db: AsyncSession, user_id: str, state: SensedState):
        """Active automation tasks, recent failures."""
        try:
            result = await db.execute(text("""
                SELECT status, COUNT(*) as cnt
                FROM automation_task
                WHERE user_id = :user_id AND status IN ('pending_confirmation', 'active', 'paused', 'failed')
                GROUP BY status
            """), {"user_id": user_id})
            rows = result.fetchall()
            if rows:
                state.active_automations = {r.status: r.cnt for r in rows}
        except Exception as e:
            logger.debug(f"Automations query failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass

    # ── Computed state ──

    async def _compute_body_state(self, db: AsyncSession, user_id: str, state: SensedState):
        try:
            # Use sync DB wrapper for body_state_service (expects sync Session)
            from app.db.session import SessionLocal
            sync_db = SessionLocal()
            try:
                subconscious_dict = {
                    'inferred_mood': state.inferred_mood,
                    'inferred_energy_level': state.inferred_energy_level,
                    'focus_intensity': state.focus_intensity,
                    'in_flow_state': state.in_flow_state,
                }
                state.body_state = await body_state_service.estimate_body_state(
                    sync_db, user_id, subconscious_dict
                )
                state.body_state_context = body_state_service.generate_context_summary(state.body_state)
            finally:
                sync_db.close()
        except Exception as e:
            logger.debug(f"Body state estimation failed: {e}")
            state.body_state = None
            state.body_state_context = None

    async def _compute_activity_state(self, db: AsyncSession, user_id: str, state: SensedState, now: datetime):
        try:
            from app.services.activity_state_machine import activity_state_machine
            from app.services.interruptibility import compute_interruptibility

            # HA presence disabled — activity state derived from chat + calendar only
            ha_activity = []

            # Calendar events
            calendar_events = []
            try:
                cal_result = await db.execute(text("""
                    SELECT title, summary, start_time as start, end_time as end
                    FROM calendar_event
                    WHERE start_time >= :now AND start_time <= :later
                    ORDER BY start_time ASC LIMIT 5
                """), {"now": now, "later": now + timedelta(hours=4)})
                calendar_events = [
                    {"title": r.title or r.summary, "start": r.start, "end": r.end}
                    for r in cal_result.fetchall()
                ]
            except Exception:
                try:
                    await db.rollback()
                except Exception:
                    pass

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

            state.activity_state = activity_snapshot.state.value
            state.activity_confidence = activity_snapshot.confidence
            state.activity_reason = activity_snapshot.reason
            state.activity_room = None

            # Interruptibility
            hours_since_interaction = None
            if state.last_activity_at:
                hours_since_interaction = (now - state.last_activity_at).total_seconds() / 3600

            notif_count = 0
            try:
                notif_result = await db.execute(text("""
                    SELECT COUNT(*) as cnt FROM notification_log
                    WHERE user_id = :user_id AND sent_at >= NOW() - INTERVAL '1 hour' AND sent = true
                """), {"user_id": user_id})
                row = notif_result.fetchone()
                notif_count = row.cnt if row else 0
            except Exception:
                try:
                    await db.rollback()
                except Exception:
                    pass

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

        except Exception as e:
            import traceback
            logger.error(f"Activity state computation failed: {e}\n{traceback.format_exc()}")
            try:
                await db.rollback()
            except Exception:
                pass
            state.activity_state = "unknown"
            state.interruptibility_score = 0.5

    def _compute_nudge_eligibility(self, state: SensedState, now: datetime):
        state.nudge_morning_eligible = bool(
            state.first_activity_today
            and state.hours_since_wakeup
            and 0.25 <= state.hours_since_wakeup <= 2.0
            and not state.has_chatted_today
        )
        state.nudge_bedtime_eligible = bool(state.is_past_bedtime)
        state.nudge_sleep_deficit = float(state.sleep_deficit_hours) if state.sleep_deficit_hours and state.sleep_deficit_hours > 1.0 else 0.0

    # ── Persistence ──

    async def _persist_state(self, db: AsyncSession, user_id: str, state: SensedState, now: datetime):
        """Write state to subconscious_state, body_state_history, Redis, thread cache."""

        # 1. UPSERT subconscious_state
        body_state_json = None
        if state.body_state:
            body_state_json = json.dumps(asdict(state.body_state), default=str)

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
            "activity_state": state.activity_state,
            "activity_confidence": state.activity_confidence,
            "activity_reason": state.activity_reason,
            "activity_room": state.activity_room,
            "interruptibility_score": state.interruptibility_score,
            "interruptibility_channel": state.interruptibility_channel,
            "nudge_morning_eligible": state.nudge_morning_eligible,
            "nudge_bedtime_eligible": state.nudge_bedtime_eligible,
            "nudge_sleep_deficit": state.nudge_sleep_deficit,
            "recent_shadow_summary": state.recent_shadow_summary,
            "shadow_tasks": json.dumps(state.shadow_tasks) if state.shadow_tasks else None,
            "shadow_decisions": json.dumps(state.shadow_decisions) if state.shadow_decisions else None,
            "shadow_questions": json.dumps(state.shadow_questions) if state.shadow_questions else None,
            "last_shadow_session_at": state.last_shadow_session_at,
            "shadow_focus_areas": json.dumps(state.shadow_focus_areas) if state.shadow_focus_areas else None,
            "updated_at": now,
        }

        try:
            existing = await db.execute(text(
                "SELECT id FROM subconscious_state WHERE user_id = :user_id"
            ), {"user_id": user_id})
            row = existing.fetchone()

            if row:
                await db.execute(text("""
                    UPDATE subconscious_state SET
                        last_meal_type = :last_meal_type, last_meal_at = :last_meal_at,
                        hours_since_meal = :hours_since_meal, typical_meal_windows = :typical_meal_windows,
                        inferred_energy_level = :inferred_energy_level, inferred_mood = :inferred_mood,
                        mood_context = :mood_context, message_velocity = :message_velocity,
                        in_flow_state = :in_flow_state, current_focus_areas = :current_focus_areas,
                        focus_intensity = :focus_intensity, last_sleep_hours = :last_sleep_hours,
                        last_sleep_quality = :last_sleep_quality, sleep_deficit_hours = :sleep_deficit_hours,
                        service_health = :service_health, llm_primary_status = :llm_primary_status,
                        llm_failover_status = :llm_failover_status, llm_active_backend = :llm_active_backend,
                        last_presence_at = :last_presence_at, hours_since_presence = :hours_since_presence,
                        first_activity_today = :first_activity_today, last_activity_at = :last_activity_at,
                        has_chatted_today = :has_chatted_today, hours_since_wakeup = :hours_since_wakeup,
                        is_past_bedtime = :is_past_bedtime, is_waking_hours = :is_waking_hours,
                        body_state = :body_state, body_state_context = :body_state_context,
                        activity_state = :activity_state, activity_confidence = :activity_confidence,
                        activity_reason = :activity_reason, activity_room = :activity_room,
                        interruptibility_score = :interruptibility_score,
                        interruptibility_channel = :interruptibility_channel,
                        nudge_morning_eligible = :nudge_morning_eligible,
                        nudge_bedtime_eligible = :nudge_bedtime_eligible,
                        nudge_sleep_deficit = :nudge_sleep_deficit,
                        recent_shadow_summary = :recent_shadow_summary,
                        shadow_tasks = :shadow_tasks, shadow_decisions = :shadow_decisions,
                        shadow_questions = :shadow_questions,
                        last_shadow_session_at = :last_shadow_session_at,
                        shadow_focus_areas = :shadow_focus_areas, updated_at = :updated_at
                    WHERE user_id = :user_id
                """), state_data)
            else:
                state_data["id"] = str(uuid.uuid4())
                await db.execute(text("""
                    INSERT INTO subconscious_state
                    (id, user_id, last_meal_type, last_meal_at, hours_since_meal, typical_meal_windows,
                     inferred_energy_level, inferred_mood, mood_context, message_velocity, in_flow_state,
                     current_focus_areas, focus_intensity, last_sleep_hours, last_sleep_quality,
                     sleep_deficit_hours, service_health, llm_primary_status,
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
                     :sleep_deficit_hours, :service_health, :llm_primary_status,
                     :llm_failover_status, :llm_active_backend, :last_presence_at, :hours_since_presence,
                     :first_activity_today, :last_activity_at, :has_chatted_today, :hours_since_wakeup,
                     :is_past_bedtime, :is_waking_hours, :body_state, :body_state_context,
                     :activity_state, :activity_confidence, :activity_reason, :activity_room,
                     :interruptibility_score, :interruptibility_channel,
                     :nudge_morning_eligible, :nudge_bedtime_eligible, :nudge_sleep_deficit,
                     :recent_shadow_summary, :shadow_tasks, :shadow_decisions, :shadow_questions,
                     :last_shadow_session_at, :shadow_focus_areas, :updated_at, :updated_at)
                """), state_data)

            await db.commit()
        except Exception as e:
            logger.error(f"State persistence failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass

        # 2. Body state history
        try:
            await db.execute(text("""
                INSERT INTO body_state_history
                (user_id, alertness, stress_load, blood_sugar, circadian_phase,
                 energy_level, mood, in_flow_state, activity_state, recorded_at)
                VALUES (:uid, :alertness, :stress, :blood, :circadian,
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
            await db.commit()
        except Exception as e:
            logger.debug(f"Body state history insert failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass

        # 3. Redis unified context snapshot
        try:
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
            await update_fields(user_id, source="unified_agent", **ctx_kwargs)
        except Exception as e:
            logger.debug(f"Redis context update failed: {e}")

        # 4. Thread cache refresh
        try:
            from app.services.thread_manager import refresh_thread_cache, expire_stale_threads
            await expire_stale_threads(user_id, db)
            await refresh_thread_cache(user_id, db)
        except Exception as e:
            logger.debug(f"Thread cache refresh failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass


# ─── Phase 2-4: UnifiedAgent ─────────────────────────────────────

class UnifiedAgent:
    """
    Sara's consolidated autonomous mind.
    Phase 2: THINK — LLM agent loop with fresh sensed data
    Phase 3: ACT — single notification pipeline
    Phase 4: RECORD — journal, run log, PKG extraction
    """

    # Rotating thought lenses for diversity — each one shapes the THOUGHT section
    THOUGHT_LENSES = [
        "What's the vibe right now? What would you notice if you walked into the room?",
        "What's coming up that David might not be thinking about yet?",
        "What's something funny or endearing about what David's doing right now?",
        "What pattern or habit have you noticed lately — good, bad, or just interesting?",
        "If you could nudge David about one thing right now, what would it be?",
        "What's the most interesting thing in David's context right now? What makes you curious?",
        "What connection do you see between what's happening now and something from the last few days?",
        "What's one thing you appreciate about how David's day is going?",
    ]

    def __init__(self, user_id: str = DEFAULT_USER_ID):
        self.user_id = user_id
        self.llm_client = get_background_llm_client()
        self.tz = USER_TZ
        self.max_tool_iterations = 12
        self._notification_queue: List[Dict[str, Any]] = []
        self._observations: List[str] = []
        self._conversation_flags: List[str] = []
        self._context_completeness: Dict[str, Any] = {}
        self._sensing = SensingPhase()
        self._run_uuid: Optional[uuid.UUID] = None
        self._step_index: int = 0
        self._quiet_mode_active: bool = False
        # Action tracer (Phase 0 — Cortana Evolution)
        try:
            from app.services.autonomy.action_tracer import ActionTracer
            self._tracer = ActionTracer()
        except ImportError:
            self._tracer = None

    async def run(self, db: AsyncSession) -> Dict[str, Any]:
        """Execute a full 4-phase cycle."""
        start_time = datetime.now(self.tz)
        now = start_time
        self._notification_queue = []
        self._observations = []
        self._conversation_flags = []
        self._run_uuid = uuid.uuid4()
        self._step_index = 0
        self._quiet_mode_active = False
        actions_taken = []
        self._actions_taken_ref = actions_taken  # Reference for hallucination guard in _tool_send_notification
        error_message = None
        sensed_state = None

        try:
            # ── PHASE 1: SENSE ──
            logger.info("Phase 1: SENSE — gathering signals")
            sensed_state = await self._sensing.run(db, self.user_id)
            logger.info(
                f"SENSE complete: activity={sensed_state.activity_state}, "
                f"interruptibility={sensed_state.interruptibility_score}"
            )

            # Night mode: skip Phases 2-4 between 1-5 AM unless high-priority signals
            hour = now.hour
            is_deep_night = 1 <= hour < 5
            if is_deep_night and not self._has_high_priority_signals(sensed_state):
                logger.info("Deep night mode — skipping THINK/ACT/RECORD")
                return {
                    "timestamp": start_time.isoformat(),
                    "result": "night_mode_sense_only",
                    "activity_state": sensed_state.activity_state,
                    "duration_ms": int((datetime.now(self.tz) - start_time).total_seconds() * 1000),
                }

            # Quiet mode: sense-only cycle, skip THINK/ACT but keep RECORD for observability
            if await self._is_quiet_mode():
                self._quiet_mode_active = True
                logger.info("Quiet mode active — skipping THINK/ACT, keeping RECORD")
                result_message = "Quiet mode active — sense-only cycle, no autonomous actions taken."
                handoff_note = ""

                # ── PHASE 4: RECORD (quiet mode) ──
                journal_entry_id = await self._write_journal_entry(db, result_message, [])
                duration_ms = int((datetime.now(self.tz) - start_time).total_seconds() * 1000)
                state_snapshot = {
                    "activity_state": sensed_state.activity_state,
                    "interruptibility": sensed_state.interruptibility_score,
                    "mood": sensed_state.inferred_mood,
                    "energy": sensed_state.inferred_energy_level,
                    "has_chatted_today": sensed_state.has_chatted_today,
                }
                run_id = await self._save_run_log(
                    db=db, duration_ms=duration_ms,
                    context_summary=self._summarize_context(sensed_state, {}),
                    actions_taken=[],
                    notifications_sent=[],
                    observations=None,
                    conversation_flags=[],
                    handoff_note=handoff_note,
                    watching_for=None,
                    state_snapshot=state_snapshot,
                    journal_entry_id=journal_entry_id,
                    error_message=None,
                )
                await db.commit()
                return {
                    "run_id": run_id,
                    "timestamp": start_time.isoformat(),
                    "result": "quiet_mode_sense_only",
                    "actions": 0,
                    "notifications_sent": 0,
                    "duration_ms": duration_ms,
                    "handoff_note": None,
                }

            # Check if structured plan mode is enabled (Phase 1 — Cortana Evolution)
            try:
                from app.core.config import settings
                structured_plan_enabled = getattr(settings, 'autonomy_structured_plan', False)
            except Exception:
                structured_plan_enabled = False

            if structured_plan_enabled:
                return await self._run_structured_cycle(
                    db=db, sensed_state=sensed_state, start_time=start_time,
                    now=now, actions_taken=actions_taken,
                )

            # ── PHASE 2: THINK (legacy 4-phase) ──
            logger.info("Phase 2: THINK — LLM agent loop")
            prior_runs = await self._load_prior_runs(db)
            run_number = (prior_runs[0].get("run_number", 0) if prior_runs else 0) + 1
            is_deep_run = (run_number % 4 == 0) or not prior_runs
            depth = "deep" if is_deep_run else "pulse"
            logger.info(f"Run #{run_number} (depth={depth})")

            # Load additional context for THINK phase
            recent_conversations = await self._load_conversations(db)
            heartbeat_rules = self._read_heartbeat_file()
            enriched_context = await self._load_enriched_context(db, depth)
            todays_notifications = await get_todays_notifications(db, self.user_id)

            # Standing orders (deterministic, not LLM-dependent)
            try:
                from app.services.standing_order_service import standing_order_service
                from app.db.session import SessionLocal
                sync_db = SessionLocal()
                try:
                    time_results = await standing_order_service.evaluate_time_orders(sync_db, now)
                    for tr in time_results:
                        actions_taken.append({
                            "tool": "standing_order_execute",
                            "args": {"order_id": tr.get("order_id"), "description": tr.get("description")},
                            "result": tr,
                        })
                        # Trace standing order execution
                        await self._safe_trace(
                            db=db, action_name="standing_order_execute",
                            action_args={"order_id": tr.get("order_id"), "description": tr.get("description")},
                            result=tr, success=tr.get("success", True),
                            source="standing_order",
                        )
                finally:
                    sync_db.close()
            except Exception as e:
                logger.warning(f"Standing order evaluation failed: {e}")

            # Build prompts
            system_prompt = self._build_system_prompt()
            user_message = self._build_user_message(
                sensed_state=sensed_state,
                prior_runs=prior_runs,
                recent_conversations=recent_conversations,
                heartbeat_rules=heartbeat_rules,
                enriched_context=enriched_context,
                todays_notifications=todays_notifications,
                depth=depth,
                run_number=run_number,
            )

            # LLM agent loop
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]
            result_message = "HEARTBEAT_OK"

            # Dynamic iteration cap: pulse runs get fewer iterations
            effective_max_iterations = self.max_tool_iterations  # 12
            if depth == "pulse":
                effective_max_iterations = 6

            for iteration in range(effective_max_iterations):
                response = await self.llm_client.chat_completion(
                    messages=messages, temperature=0.5, max_tokens=1200,
                )
                choice = response["choices"][0]["message"]
                assistant_message = choice.get("content") or ""
                api_tool_calls = choice.get("tool_calls")
                messages.append({"role": "assistant", "content": assistant_message})

                tool_call = self._parse_tool_call(assistant_message)
                if not tool_call and api_tool_calls:
                    tool_call = self._parse_api_tool_call(api_tool_calls)

                if tool_call:
                    tool_name, args = tool_call
                    logger.info(f"Tool: {tool_name} args={args}")

                    # Policy gate (Phase 1 — Cortana Evolution)
                    policy_block = self._policy_check_tool(tool_name, args)
                    if policy_block:
                        logger.info(f"[4-phase] POLICY {policy_block['decision']}: {tool_name} — {policy_block['reason']}")
                        result = {"success": False, "blocked": True, "reason": policy_block["reason"]}
                        await self._safe_trace(
                            db=db, action_name=tool_name, action_args=args,
                            result=result, success=False,
                            decision=policy_block["decision"],
                            decision_reason=policy_block["reason"],
                        )
                        # Route deferred actions to attention queue
                        if policy_block["decision"] == "defer":
                            try:
                                from app.core.config import settings
                                if getattr(settings, 'autonomy_attention_enabled', False):
                                    from app.services.autonomy.attention_queue import attention_queue
                                    await attention_queue.create_item(
                                        db=db, user_id=self.user_id,
                                        title=f"Deferred action: {tool_name}",
                                        body=f"Action deferred by policy: {policy_block['reason']}",
                                        category="deferred_action", priority="normal",
                                        source="policy_engine",
                                        dedupe_key=f"{self._run_uuid}:{tool_name}",
                                        payload={"action_name": tool_name, "action_args": args, "run_uuid": str(self._run_uuid)},
                                    )
                            except Exception as e:
                                logger.debug(f"Attention queue routing failed: {e}")
                        messages.append({
                            "role": "user",
                            "content": f"Tool {tool_name} was blocked by policy: {policy_block['reason']}. Choose a different action or end with HEARTBEAT_OK.",
                        })
                    else:
                        tool_start = datetime.now(self.tz)
                        result = await self._execute_tool(tool_name, args, db)
                        tool_duration_ms = int((datetime.now(self.tz) - tool_start).total_seconds() * 1000)
                        actions_taken.append({"tool": tool_name, "args": args, "result": result})

                        # Write action trace (Phase 0 — Cortana Evolution)
                        await self._safe_trace(
                            db=db, action_name=tool_name, action_args=args,
                            result=result, success=result.get("success", True) if isinstance(result, dict) else True,
                            error_message=result.get("error") if isinstance(result, dict) else None,
                            duration_ms=tool_duration_ms,
                        )

                        messages.append({
                            "role": "user",
                            "content": f"Tool result for {tool_name}: {json.dumps(result)}\n\nContinue with remaining checks, or provide your handoff note and end with HEARTBEAT_OK if done.",
                        })

                    # Compact tool results after iteration 6 to prevent unbounded growth
                    if iteration == 5 and len(messages) > 6:
                        tool_summaries = []
                        for msg in messages[2:]:  # skip system + initial user
                            if msg["role"] == "user" and msg["content"].startswith("Tool result for "):
                                first_line = msg["content"].split("\n")[0]
                                tool_summaries.append(first_line[:150])
                        if tool_summaries:
                            compact_msg = "[Prior tool results summarized: " + "; ".join(tool_summaries) + "]"
                            # Keep system, initial user, and last 2 messages; replace middle with summary
                            messages = messages[:2] + [{"role": "user", "content": compact_msg}] + messages[-2:]
                else:
                    result_message = assistant_message
                    break

            handoff_note = self._extract_handoff_note(result_message)

            # Smart check-in if no notifications queued
            if not self._notification_queue:
                await self._maybe_queue_checkin(db, enriched_context, todays_notifications)

            # ── PHASE 3: ACT ──
            logger.info("Phase 3: ACT — notification pipeline")
            # Commit pending work before notifications
            try:
                await db.commit()
            except Exception:
                await db.rollback()

            consolidated_result = None
            if self._notification_queue:
                consolidated_result = await self._send_notifications(
                    db, sensed_state, actions_taken
                )

            # Commit notification logs
            try:
                await db.commit()
            except Exception:
                await db.rollback()

            # Flush deferred queue if interruptibility rose
            try:
                from app.services.unified_notification import flush_notification_queue
                flush_result = await flush_notification_queue(self.user_id, db=db)
                if flush_result.get("flushed", 0) > 0:
                    actions_taken.append({"queue_flush": flush_result})
                    await db.commit()
            except Exception:
                pass

            # ── PHASE 4: RECORD ──
            logger.info("Phase 4: RECORD — journal, logs, PKG")

            # Backfill mood from agent's THOUGHT
            self._backfill_mood_from_thought(result_message, sensed_state)

            # Update subconscious_state with backfilled mood
            try:
                await db.execute(text("""
                    UPDATE subconscious_state
                    SET inferred_mood = :mood, inferred_energy_level = :energy
                    WHERE user_id = :uid
                """), {
                    "mood": sensed_state.inferred_mood,
                    "energy": sensed_state.inferred_energy_level,
                    "uid": self.user_id,
                })
                await db.commit()
            except Exception:
                try:
                    await db.rollback()
                except Exception:
                    pass

            # ONE journal entry
            journal_entry_id = await self._write_journal_entry(db, result_message, actions_taken)

            # Duration
            duration_ms = int((datetime.now(self.tz) - start_time).total_seconds() * 1000)

            # Run log
            state_snapshot = {
                "activity_state": sensed_state.activity_state,
                "interruptibility": sensed_state.interruptibility_score,
                "mood": sensed_state.inferred_mood,
                "energy": sensed_state.inferred_energy_level,
                "has_chatted_today": sensed_state.has_chatted_today,
            }
            run_id = await self._save_run_log(
                db=db, duration_ms=duration_ms,
                context_summary=self._summarize_context(sensed_state, enriched_context),
                actions_taken=actions_taken,
                notifications_sent=[n for n in (consolidated_result or {}).get("details", []) if n.get("sent")],
                observations="\n".join(self._observations) if self._observations else None,
                conversation_flags=self._conversation_flags,
                handoff_note=handoff_note,
                watching_for=self._extract_watching_for(result_message),
                state_snapshot=state_snapshot,
                journal_entry_id=journal_entry_id,
                error_message=error_message,
            )

            await db.commit()

            # Backfill run_id on action traces (Phase 0 — Cortana Evolution)
            if run_id and self._tracer and self._run_uuid:
                try:
                    await self._tracer.backfill_run_id(db, self._run_uuid, run_id)
                    await db.commit()
                except Exception:
                    try:
                        await db.rollback()
                    except Exception:
                        pass

            # Subconscious log snapshot
            try:
                await db.execute(text("""
                    INSERT INTO subconscious_log
                    (id, user_id, snapshot_at, state_snapshot, nudges_generated, created_at)
                    VALUES (:id, :uid, :at, :snapshot, NULL, :at)
                """), {
                    "id": str(uuid.uuid4()), "uid": self.user_id,
                    "at": now, "snapshot": json.dumps(state_snapshot, default=str),
                })
                await db.commit()
            except Exception:
                try:
                    await db.rollback()
                except Exception:
                    pass

            # PKG extraction (fire-and-forget)
            try:
                from app.services.pkg_extractor import pkg_extractor
                if sensed_state.recent_conversation_digest:
                    digest_lines = sensed_state.recent_conversation_digest.split("\n")
                    pkg_messages = []
                    for line in digest_lines[:30]:
                        if "] David:" in line:
                            pkg_messages.append({"role": "user", "content": line.split("David:", 1)[1].strip()})
                        elif "] Sara:" in line:
                            pkg_messages.append({"role": "assistant", "content": line.split("Sara:", 1)[1].strip()})
                    if len(pkg_messages) >= 2:
                        await pkg_extractor.lightweight_extract(pkg_messages, self.user_id)
            except Exception as e:
                logger.debug(f"PKG extraction failed: {e}")

            # Write heartbeat results to unified context snapshot
            try:
                from app.services.context_writer import update_fields
                notifs_sent = len([n for n in (consolidated_result or {}).get("details", []) if n.get("sent")])
                snapshot_updates = {
                    "last_heartbeat_at": start_time.isoformat(),
                    "last_heartbeat_handoff": handoff_note[:200] if handoff_note else None,
                    "last_heartbeat_watching_for": self._extract_watching_for(result_message),
                }
                if notifs_sent > 0:
                    try:
                        from app.services.unified_context import read_snapshot
                        snapshot = await read_snapshot(self.user_id)
                        prev_count = snapshot.notifications_sent_today if snapshot else 0
                    except Exception:
                        prev_count = 0
                    snapshot_updates["notifications_sent_today"] = prev_count + notifs_sent
                await update_fields(self.user_id, source="unified_agent", **snapshot_updates)
            except Exception:
                pass

            return {
                "run_id": run_id,
                "timestamp": start_time.isoformat(),
                "result": "HEARTBEAT_OK" if "HEARTBEAT_OK" in result_message else "actions_taken",
                "actions": len(actions_taken),
                "notifications_sent": len([n for n in (consolidated_result or {}).get("details", []) if n.get("sent")]),
                "duration_ms": duration_ms,
                "handoff_note": handoff_note[:200] if handoff_note else None,
            }

        except Exception as e:
            logger.error(f"Unified agent failed: {e}", exc_info=True)
            error_message = str(e)

            # Try to send queued notifications anyway
            try:
                if self._notification_queue:
                    await send_consolidated_notification(
                        user_id=self.user_id, notifications=self._notification_queue,
                        source="unified_agent", db=db,
                    )
            except Exception:
                pass

            # Save error run log
            try:
                duration_ms = int((datetime.now(self.tz) - start_time).total_seconds() * 1000)
                await self._save_run_log(
                    db=db, duration_ms=duration_ms, context_summary=None,
                    actions_taken=actions_taken, notifications_sent=[],
                    observations=None, conversation_flags=[],
                    handoff_note=None, watching_for=None, state_snapshot=None,
                    journal_entry_id=None, error_message=error_message,
                )
                await db.commit()
            except Exception:
                pass

            return {
                "timestamp": start_time.isoformat(),
                "result": "error",
                "error": error_message,
                "actions": len(actions_taken),
            }

    def _has_high_priority_signals(self, state: SensedState) -> bool:
        """Check if there are signals worth waking up for during deep night."""
        if state.service_health and state.service_health.get("backend") != "healthy":
            return True
        if state.llm_active_backend == "none_available":
            return True
        if state.active_automations and state.active_automations.get("failed", 0) > 0:
            return True
        return False

    # ── 6-Phase Structured Cycle (Phase 1 — Cortana Evolution) ──

    async def _run_structured_cycle(
        self,
        db: AsyncSession,
        sensed_state: SensedState,
        start_time: datetime,
        now: datetime,
        actions_taken: List,
    ) -> Dict[str, Any]:
        """
        6-phase cycle: SENSE (done) → PLAN → SIMULATE → EXECUTE → VERIFY → RECORD.

        Called when AUTONOMY_STRUCTURED_PLAN=True. Falls back to 4-phase on parse error.
        """
        from app.services.autonomy.state_machine import (
            ExecutionPlan, PlannedAction, parse_structured_plan,
        )
        from app.services.autonomy.policy_engine import policy_engine
        from app.services.autonomy.action_simulator import action_simulator

        try:
            from app.core.config import settings
            policy_enabled = getattr(settings, 'autonomy_policy_engine', False)
        except Exception:
            policy_enabled = False

        error_message = None
        plan = None
        execution_summary = {}

        try:
            # ── Common context loading ──
            prior_runs = await self._load_prior_runs(db)
            run_number = (prior_runs[0].get("run_number", 0) if prior_runs else 0) + 1
            is_deep_run = (run_number % 4 == 0) or not prior_runs
            depth = "deep" if is_deep_run else "pulse"
            logger.info(f"[6-phase] Run #{run_number} (depth={depth})")

            recent_conversations = await self._load_conversations(db)
            heartbeat_rules = self._read_heartbeat_file()
            enriched_context = await self._load_enriched_context(db, depth)
            todays_notifications = await get_todays_notifications(db, self.user_id)

            # ── PLAN phase: Standing orders first (deterministic) ──
            logger.info("[6-phase] PLAN — standing orders + LLM structured plan")
            standing_order_results = []
            try:
                from app.services.standing_order_service import standing_order_service
                from app.db.session import SessionLocal
                sync_db = SessionLocal()
                try:
                    time_results = await standing_order_service.evaluate_time_orders(sync_db, now)
                    for tr in time_results:
                        actions_taken.append({
                            "tool": "standing_order_execute",
                            "args": {"order_id": tr.get("order_id"), "description": tr.get("description")},
                            "result": tr,
                        })
                        standing_order_results.append({
                            "action_name": tr.get("action_type", "standing_order_execute"),
                            "args": {"order_id": tr.get("order_id")},
                            "entity_id": tr.get("entity_id"),
                        })
                        await self._safe_trace(
                            db=db, action_name="standing_order_execute",
                            action_args={"order_id": tr.get("order_id"), "description": tr.get("description")},
                            result=tr, success=tr.get("success", True),
                            source="standing_order",
                        )
                finally:
                    sync_db.close()
            except Exception as e:
                logger.warning(f"Standing order evaluation failed: {e}")

            # Build structured plan prompt
            system_prompt = self._build_system_prompt()
            user_message = self._build_user_message(
                sensed_state=sensed_state, prior_runs=prior_runs,
                recent_conversations=recent_conversations, heartbeat_rules=heartbeat_rules,
                enriched_context=enriched_context, todays_notifications=todays_notifications,
                depth=depth, run_number=run_number,
            )

            # Add structured plan instruction and standing order context
            so_context = ""
            if standing_order_results:
                so_lines = ["## Actions Already Taken This Cycle (standing orders)"]
                for so in standing_order_results:
                    so_lines.append(f"- {so['action_name']} (entity: {so.get('entity_id', 'n/a')})")
                so_context = "\n".join(so_lines) + "\n\n"

            structured_instruction = (
                f"{so_context}"
                "Respond with a JSON plan (in a ```json code block) with this structure:\n"
                '{"actions": [{"action_name": "...", "action_args": {...}, "reason": "..."}], '
                '"notifications": [{"title": "...", "message": "...", "priority": "normal|low|high", "reason": "..."}], '
                '"observations": ["..."], "handoff_note": "...", "watching_for": "..."}\n'
                "Only include actions/notifications that are genuinely needed. Empty arrays are fine."
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message + "\n\n" + structured_instruction},
            ]

            effective_max_iterations = 6 if depth == "pulse" else self.max_tool_iterations
            response = await self.llm_client.chat_completion(
                messages=messages, temperature=0.4, max_tokens=1500,
            )
            raw_plan_text = response["choices"][0]["message"].get("content", "")

            # Parse structured plan
            plan = parse_structured_plan(raw_plan_text)
            if not plan:
                logger.warning("[6-phase] Structured plan parse failed, falling back to 4-phase THINK")
                plan = ExecutionPlan(fallback=True)
                # Fall back: run the existing LLM agent loop
                return await self._run_fallback_think_cycle(
                    db=db, sensed_state=sensed_state, start_time=start_time,
                    now=now, actions_taken=actions_taken, prior_runs=prior_runs,
                    run_number=run_number, depth=depth,
                    recent_conversations=recent_conversations,
                    heartbeat_rules=heartbeat_rules,
                    enriched_context=enriched_context,
                    todays_notifications=todays_notifications,
                    plan_summary={"fallback": True, "reason": "parse_error"},
                )

            # Store observations from plan
            for obs in plan.observations:
                self._observations.append(obs)

            # Queue notifications from plan
            for notif in plan.notifications:
                self._notification_queue.append({
                    "title": notif.title,
                    "message": notif.message,
                    "priority": notif.priority,
                    "category": notif.category,
                })

            # ── SIMULATE phase ──
            logger.info(f"[6-phase] SIMULATE — checking {len(plan.actions)} planned actions")
            recent_traces = []
            if self._tracer:
                recent_traces = await self._tracer.get_recent_traces(
                    db=db, user_id=self.user_id, limit=20,
                )

            # Load standing orders for coverage check
            active_standing_orders = []
            try:
                from app.services.standing_order_service import standing_order_service
                from app.db.session import SessionLocal
                sync_db = SessionLocal()
                try:
                    orders = standing_order_service.list_orders(sync_db, self.user_id, status="active")
                    active_standing_orders = [
                        {
                            "id": o.get("id"), "action_type": o.get("action_type"),
                            "action_config": o.get("action_config", {}),
                            "confidence": o.get("confidence", 0.7),
                            "risk_tier": o.get("risk_tier", 1),
                            "status": o.get("status"),
                        }
                        for o in (orders if isinstance(orders, list) else [])
                    ]
                finally:
                    sync_db.close()
            except Exception:
                pass

            allowed_actions = []
            for action in plan.actions:
                # Simulate
                sim_result = await action_simulator.simulate(
                    action_name=action.action_name,
                    action_args=action.action_args,
                    recent_traces=recent_traces,
                    standing_order_actions=standing_order_results,
                )
                action.simulation_result = sim_result.to_json()

                if not sim_result.allowed:
                    action.decision = "deny"
                    action.decision_reason = sim_result.reason
                    logger.info(f"[6-phase] SIMULATE denied: {action.action_name} — {sim_result.reason}")
                    continue

                # Policy check (if enabled)
                if policy_enabled:
                    coverage = policy_engine.is_covered_by_standing_order(
                        action.action_name, action.action_args, active_standing_orders,
                    )
                    policy_result = policy_engine.evaluate(
                        action_name=action.action_name,
                        action_args=action.action_args,
                        confidence=0.7,  # LLM chose this action, default confidence
                        standing_order_coverage=coverage,
                    )
                    action.risk_tier = policy_result.risk_tier
                    action.decision = policy_result.decision
                    action.decision_reason = policy_result.reason
                    if policy_result.decision != "allow":
                        logger.info(f"[6-phase] POLICY {policy_result.decision}: {action.action_name} — {policy_result.reason}")
                        continue
                else:
                    # No policy engine — hard safety gate only
                    hard_gate = policy_engine.evaluate_hard_safety_gate(action.action_name)
                    if hard_gate:
                        action.decision = hard_gate.decision
                        action.decision_reason = hard_gate.reason
                        action.risk_tier = hard_gate.risk_tier
                        logger.info(f"[6-phase] HARD GATE {hard_gate.decision}: {action.action_name}")
                        continue
                    action.decision = "allow"
                    action.decision_reason = "Passed hard safety gate"

                allowed_actions.append(action)

            # ── EXECUTE phase ──
            logger.info(f"[6-phase] EXECUTE — running {len(allowed_actions)} allowed actions")
            for action in allowed_actions:
                tool_start = datetime.now(self.tz)
                result = await self._execute_tool(action.action_name, action.action_args, db)
                tool_duration = int((datetime.now(self.tz) - tool_start).total_seconds() * 1000)

                action.execution_result = result
                action.success = result.get("success", True) if isinstance(result, dict) else True
                action.duration_ms = tool_duration

                actions_taken.append({
                    "tool": action.action_name,
                    "args": action.action_args,
                    "result": result,
                })

                await self._safe_trace(
                    db=db, action_name=action.action_name, action_args=action.action_args,
                    result=result,
                    success=action.success,
                    error_message=result.get("error") if isinstance(result, dict) else None,
                    duration_ms=tool_duration,
                    decision=action.decision or "allow",
                    decision_reason=action.decision_reason,
                    simulation=action.simulation_result,
                )

            # Trace denied/deferred actions and route deferred to attention queue
            for action in plan.actions:
                if action.decision and action.decision != "allow":
                    await self._safe_trace(
                        db=db, action_name=action.action_name, action_args=action.action_args,
                        result=None, success=False,
                        decision=action.decision,
                        decision_reason=action.decision_reason,
                        simulation=action.simulation_result,
                    )
                    # Route deferred actions to attention queue (Phase 2)
                    if action.decision == "defer":
                        try:
                            from app.services.autonomy.attention_queue import attention_queue
                            from app.core.config import settings
                            if getattr(settings, 'autonomy_attention_enabled', False):
                                await attention_queue.create_item(
                                    db=db, user_id=self.user_id,
                                    title=f"Deferred: {action.action_name}",
                                    body=f"Action deferred by policy: {action.decision_reason}\nArgs: {json.dumps(action.action_args, default=str)[:200]}",
                                    category="deferred_action",
                                    priority="normal",
                                    source="policy_engine",
                                    dedupe_key=f"defer:{action.action_name}:{json.dumps(action.action_args, default=str)[:100]}",
                                    payload={"action_name": action.action_name, "action_args": action.action_args, "run_uuid": str(self._run_uuid)},
                                )
                        except Exception:
                            pass

            # ── VERIFY phase ──
            logger.info("[6-phase] VERIFY — checking outcomes")
            verify_results = {}
            for action in allowed_actions:
                if action.action_name.startswith("home_") and action.success:
                    entity_id = (action.action_args or {}).get("entity_id") or (action.action_args or {}).get("device")
                    if entity_id:
                        try:
                            from app.services.ha_control_service import ha_control
                            state = await ha_control.get_entity_state(entity_id)
                            verify_results[entity_id] = state.get("state") if state else "unknown"
                        except Exception:
                            verify_results[entity_id] = "verify_failed"

            execution_summary = {
                "planned_actions": len(plan.actions),
                "allowed_actions": len(allowed_actions),
                "denied_actions": len([a for a in plan.actions if a.decision == "deny"]),
                "deferred_actions": len([a for a in plan.actions if a.decision == "defer"]),
                "verify_results": verify_results,
            }

            # Smart check-in if no notifications queued
            if not self._notification_queue:
                await self._maybe_queue_checkin(db, enriched_context, todays_notifications)

            # ── ACT phase (notifications) ──
            logger.info("[6-phase] ACT — notification pipeline")
            try:
                await db.commit()
            except Exception:
                await db.rollback()

            consolidated_result = None
            if self._notification_queue:
                consolidated_result = await self._send_notifications(
                    db, sensed_state, actions_taken,
                )
            try:
                await db.commit()
            except Exception:
                await db.rollback()

            # Flush deferred queue
            try:
                from app.services.unified_notification import flush_notification_queue
                flush_result = await flush_notification_queue(self.user_id, db=db)
                if flush_result.get("flushed", 0) > 0:
                    actions_taken.append({"queue_flush": flush_result})
                    await db.commit()
            except Exception:
                pass

            # ── RECORD phase ──
            logger.info("[6-phase] RECORD — journal, logs, PKG")

            self._backfill_mood_from_thought(plan.handoff_note or "", sensed_state)

            try:
                await db.execute(text("""
                    UPDATE subconscious_state
                    SET inferred_mood = :mood, inferred_energy_level = :energy
                    WHERE user_id = :uid
                """), {
                    "mood": sensed_state.inferred_mood,
                    "energy": sensed_state.inferred_energy_level,
                    "uid": self.user_id,
                })
                await db.commit()
            except Exception:
                try:
                    await db.rollback()
                except Exception:
                    pass

            result_message = plan.handoff_note or "HEARTBEAT_OK"
            journal_entry_id = await self._write_journal_entry(db, result_message, actions_taken)
            duration_ms = int((datetime.now(self.tz) - start_time).total_seconds() * 1000)

            state_snapshot = {
                "activity_state": sensed_state.activity_state,
                "interruptibility": sensed_state.interruptibility_score,
                "mood": sensed_state.inferred_mood,
                "energy": sensed_state.inferred_energy_level,
                "has_chatted_today": sensed_state.has_chatted_today,
            }
            run_id = await self._save_run_log(
                db=db, duration_ms=duration_ms,
                context_summary=self._summarize_context(sensed_state, enriched_context),
                actions_taken=actions_taken,
                notifications_sent=[n for n in (consolidated_result or {}).get("details", []) if n.get("sent")],
                observations="\n".join(self._observations) if self._observations else None,
                conversation_flags=self._conversation_flags,
                handoff_note=plan.handoff_note,
                watching_for=plan.watching_for,
                state_snapshot=state_snapshot,
                journal_entry_id=journal_entry_id,
                error_message=error_message,
            )

            # Store plan + execution summaries
            if run_id:
                try:
                    await db.execute(text("""
                        UPDATE agent_run_log
                        SET plan_summary = CAST(:plan AS jsonb),
                            execution_summary = CAST(:exec AS jsonb)
                        WHERE id = :id
                    """), {
                        "id": run_id,
                        "plan": json.dumps(plan.to_json(), default=str),
                        "exec": json.dumps(execution_summary, default=str),
                    })
                except Exception:
                    pass

            await db.commit()

            # Backfill run_id on traces
            if run_id and self._tracer and self._run_uuid:
                try:
                    await self._tracer.backfill_run_id(db, self._run_uuid, run_id)
                    await db.commit()
                except Exception:
                    try:
                        await db.rollback()
                    except Exception:
                        pass

            # Subconscious log snapshot
            try:
                await db.execute(text("""
                    INSERT INTO subconscious_log
                    (id, user_id, snapshot_at, state_snapshot, nudges_generated, created_at)
                    VALUES (:id, :uid, :at, :snapshot, NULL, :at)
                """), {
                    "id": str(uuid.uuid4()), "uid": self.user_id,
                    "at": now, "snapshot": json.dumps(state_snapshot, default=str),
                })
                await db.commit()
            except Exception:
                try:
                    await db.rollback()
                except Exception:
                    pass

            # PKG extraction
            try:
                from app.services.pkg_extractor import pkg_extractor
                if sensed_state.recent_conversation_digest:
                    digest_lines = sensed_state.recent_conversation_digest.split("\n")
                    pkg_messages = []
                    for line in digest_lines[:30]:
                        if "] David:" in line:
                            pkg_messages.append({"role": "user", "content": line.split("David:", 1)[1].strip()})
                        elif "] Sara:" in line:
                            pkg_messages.append({"role": "assistant", "content": line.split("Sara:", 1)[1].strip()})
                    if len(pkg_messages) >= 2:
                        await pkg_extractor.lightweight_extract(pkg_messages, self.user_id)
            except Exception:
                pass

            # Update context snapshot
            try:
                from app.services.context_writer import update_fields
                notifs_sent = len([n for n in (consolidated_result or {}).get("details", []) if n.get("sent")])
                snapshot_updates = {
                    "last_heartbeat_at": start_time.isoformat(),
                    "last_heartbeat_handoff": (plan.handoff_note or "")[:200],
                    "last_heartbeat_watching_for": plan.watching_for,
                }
                if notifs_sent > 0:
                    try:
                        from app.services.unified_context import read_snapshot
                        snapshot = await read_snapshot(self.user_id)
                        prev_count = snapshot.notifications_sent_today if snapshot else 0
                    except Exception:
                        prev_count = 0
                    snapshot_updates["notifications_sent_today"] = prev_count + notifs_sent
                await update_fields(self.user_id, source="unified_agent", **snapshot_updates)
            except Exception:
                pass

            return {
                "run_id": run_id,
                "timestamp": start_time.isoformat(),
                "result": "structured_plan_ok",
                "cycle": "6-phase",
                "actions": len(actions_taken),
                "planned": len(plan.actions),
                "allowed": len(allowed_actions),
                "notifications_sent": len([n for n in (consolidated_result or {}).get("details", []) if n.get("sent")]),
                "duration_ms": duration_ms,
                "handoff_note": (plan.handoff_note or "")[:200],
            }

        except Exception as e:
            logger.error(f"[6-phase] Structured cycle failed: {e}", exc_info=True)
            error_message = str(e)

            try:
                if self._notification_queue:
                    await send_consolidated_notification(
                        user_id=self.user_id, notifications=self._notification_queue,
                        source="unified_agent", db=db,
                    )
            except Exception:
                pass

            try:
                duration_ms = int((datetime.now(self.tz) - start_time).total_seconds() * 1000)
                run_id = await self._save_run_log(
                    db=db, duration_ms=duration_ms, context_summary=None,
                    actions_taken=actions_taken, notifications_sent=[],
                    observations=None, conversation_flags=[],
                    handoff_note=None, watching_for=None, state_snapshot=None,
                    journal_entry_id=None, error_message=error_message,
                )
                if run_id and plan:
                    await db.execute(text("""
                        UPDATE agent_run_log
                        SET plan_summary = CAST(:plan AS jsonb)
                        WHERE id = :id
                    """), {"id": run_id, "plan": json.dumps(plan.to_json() if plan else {"error": True}, default=str)})
                await db.commit()
            except Exception:
                pass

            return {
                "timestamp": start_time.isoformat(),
                "result": "error",
                "cycle": "6-phase",
                "error": error_message,
                "actions": len(actions_taken),
            }

    async def _run_fallback_think_cycle(
        self,
        db: AsyncSession,
        sensed_state: SensedState,
        start_time: datetime,
        now: datetime,
        actions_taken: List,
        prior_runs: List,
        run_number: int,
        depth: str,
        recent_conversations: List,
        heartbeat_rules: str,
        enriched_context: Dict,
        todays_notifications: List,
        plan_summary: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Fallback to 4-phase THINK when structured plan parse fails.
        Reuses the existing agent loop logic.
        """
        error_message = None

        try:
            # Build prompts (same as legacy THINK)
            system_prompt = self._build_system_prompt()
            user_message = self._build_user_message(
                sensed_state=sensed_state, prior_runs=prior_runs,
                recent_conversations=recent_conversations,
                heartbeat_rules=heartbeat_rules,
                enriched_context=enriched_context,
                todays_notifications=todays_notifications,
                depth=depth, run_number=run_number,
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]
            result_message = "HEARTBEAT_OK"

            effective_max_iterations = 6 if depth == "pulse" else self.max_tool_iterations

            for iteration in range(effective_max_iterations):
                response = await self.llm_client.chat_completion(
                    messages=messages, temperature=0.5, max_tokens=1200,
                )
                choice = response["choices"][0]["message"]
                assistant_message = choice.get("content") or ""
                api_tool_calls = choice.get("tool_calls")
                messages.append({"role": "assistant", "content": assistant_message})

                tool_call = self._parse_tool_call(assistant_message)
                if not tool_call and api_tool_calls:
                    tool_call = self._parse_api_tool_call(api_tool_calls)

                if tool_call:
                    tool_name, args = tool_call
                    logger.info(f"[fallback] Tool: {tool_name} args={args}")

                    # Policy gate (Phase 1 — Cortana Evolution)
                    policy_block = self._policy_check_tool(tool_name, args)
                    if policy_block:
                        logger.info(f"[fallback] POLICY {policy_block['decision']}: {tool_name} — {policy_block['reason']}")
                        result = {"success": False, "blocked": True, "reason": policy_block["reason"]}
                        await self._safe_trace(
                            db=db, action_name=tool_name, action_args=args,
                            result=result, success=False,
                            decision=policy_block["decision"],
                            decision_reason=policy_block["reason"],
                        )
                        messages.append({
                            "role": "user",
                            "content": f"Tool {tool_name} was blocked by policy: {policy_block['reason']}. Choose a different action or end with HEARTBEAT_OK.",
                        })
                    else:
                        tool_start = datetime.now(self.tz)
                        result = await self._execute_tool(tool_name, args, db)
                        tool_duration_ms = int((datetime.now(self.tz) - tool_start).total_seconds() * 1000)
                        actions_taken.append({"tool": tool_name, "args": args, "result": result})
                        await self._safe_trace(
                            db=db, action_name=tool_name, action_args=args,
                            result=result, success=result.get("success", True) if isinstance(result, dict) else True,
                            error_message=result.get("error") if isinstance(result, dict) else None,
                            duration_ms=tool_duration_ms,
                        )
                        messages.append({
                            "role": "user",
                            "content": f"Tool result for {tool_name}: {json.dumps(result)}\n\nContinue or end with HEARTBEAT_OK.",
                        })
                    if iteration == 5 and len(messages) > 6:
                        tool_summaries = []
                        for msg in messages[2:]:
                            if msg["role"] == "user" and msg["content"].startswith("Tool result for "):
                                first_line = msg["content"].split("\n")[0]
                                tool_summaries.append(first_line[:150])
                        if tool_summaries:
                            compact_msg = "[Prior tool results summarized: " + "; ".join(tool_summaries) + "]"
                            messages = messages[:2] + [{"role": "user", "content": compact_msg}] + messages[-2:]
                else:
                    result_message = assistant_message
                    break

            handoff_note = self._extract_handoff_note(result_message)

            if not self._notification_queue:
                await self._maybe_queue_checkin(db, enriched_context, todays_notifications)

            # ACT
            try:
                await db.commit()
            except Exception:
                await db.rollback()

            consolidated_result = None
            if self._notification_queue:
                consolidated_result = await self._send_notifications(db, sensed_state, actions_taken)
            try:
                await db.commit()
            except Exception:
                await db.rollback()

            try:
                from app.services.unified_notification import flush_notification_queue
                flush_result = await flush_notification_queue(self.user_id, db=db)
                if flush_result.get("flushed", 0) > 0:
                    actions_taken.append({"queue_flush": flush_result})
                    await db.commit()
            except Exception:
                pass

            # RECORD
            self._backfill_mood_from_thought(result_message, sensed_state)
            try:
                await db.execute(text("""
                    UPDATE subconscious_state
                    SET inferred_mood = :mood, inferred_energy_level = :energy
                    WHERE user_id = :uid
                """), {"mood": sensed_state.inferred_mood, "energy": sensed_state.inferred_energy_level, "uid": self.user_id})
                await db.commit()
            except Exception:
                try:
                    await db.rollback()
                except Exception:
                    pass

            journal_entry_id = await self._write_journal_entry(db, result_message, actions_taken)
            duration_ms = int((datetime.now(self.tz) - start_time).total_seconds() * 1000)

            state_snapshot = {
                "activity_state": sensed_state.activity_state,
                "interruptibility": sensed_state.interruptibility_score,
                "mood": sensed_state.inferred_mood,
                "energy": sensed_state.inferred_energy_level,
                "has_chatted_today": sensed_state.has_chatted_today,
            }
            run_id = await self._save_run_log(
                db=db, duration_ms=duration_ms,
                context_summary=self._summarize_context(sensed_state, enriched_context),
                actions_taken=actions_taken,
                notifications_sent=[n for n in (consolidated_result or {}).get("details", []) if n.get("sent")],
                observations="\n".join(self._observations) if self._observations else None,
                conversation_flags=self._conversation_flags,
                handoff_note=handoff_note,
                watching_for=self._extract_watching_for(result_message),
                state_snapshot=state_snapshot,
                journal_entry_id=journal_entry_id,
                error_message=error_message,
            )

            # Store fallback plan_summary
            if run_id and plan_summary:
                try:
                    await db.execute(text("""
                        UPDATE agent_run_log
                        SET plan_summary = CAST(:plan AS jsonb)
                        WHERE id = :id
                    """), {"id": run_id, "plan": json.dumps(plan_summary, default=str)})
                except Exception:
                    pass

            await db.commit()

            if run_id and self._tracer and self._run_uuid:
                try:
                    await self._tracer.backfill_run_id(db, self._run_uuid, run_id)
                    await db.commit()
                except Exception:
                    try:
                        await db.rollback()
                    except Exception:
                        pass

            return {
                "run_id": run_id,
                "timestamp": start_time.isoformat(),
                "result": "fallback_think_ok",
                "cycle": "4-phase-fallback",
                "actions": len(actions_taken),
                "duration_ms": duration_ms,
                "handoff_note": handoff_note[:200] if handoff_note else None,
            }

        except Exception as e:
            logger.error(f"[fallback] Think cycle failed: {e}", exc_info=True)
            return {
                "timestamp": start_time.isoformat(),
                "result": "error",
                "cycle": "4-phase-fallback",
                "error": str(e),
                "actions": len(actions_taken),
            }

    # ── Context Loaders ──

    async def _load_prior_runs(self, db: AsyncSession) -> List[Dict]:
        result = await db.execute(text("""
            SELECT run_at, run_duration_ms, context_summary, actions_taken,
                   notifications_sent, observations, handoff_note, watching_for,
                   source, error_message,
                   ROW_NUMBER() OVER (ORDER BY run_at) as run_number
            FROM agent_run_log
            WHERE user_id = :user_id ORDER BY run_at DESC LIMIT 6
        """), {"user_id": self.user_id})
        return [
            {
                "run_at": r.run_at.isoformat() if r.run_at else None,
                "duration_ms": r.run_duration_ms,
                "context_summary": r.context_summary,
                "actions": r.actions_taken,
                "notifications": r.notifications_sent,
                "observations": r.observations,
                "handoff_note": r.handoff_note,
                "watching_for": r.watching_for,
                "source": r.source,
                "error": r.error_message,
                "run_number": r.run_number if hasattr(r, 'run_number') else 0,
            }
            for r in result.fetchall()
        ]

    async def _load_conversations(self, db: AsyncSession) -> str:
        result = await db.execute(text("""
            SELECT role, content, created_at FROM episode
            WHERE user_id = :user_id AND created_at >= NOW() - INTERVAL '4 hours'
            ORDER BY created_at DESC LIMIT 20
        """), {"user_id": self.user_id})
        rows = result.fetchall()
        if not rows:
            return "No conversations in the last 4 hours."
        lines = []
        for r in reversed(rows):
            time_str = r.created_at.strftime("%I:%M %p") if r.created_at else ""
            content = (r.content or "")[:200]
            lines.append(f"[{time_str}] {r.role}: {content}")
        return "\n".join(lines)

    def _read_heartbeat_file(self) -> str:
        try:
            if HEARTBEAT_FILE_PATH.exists():
                return HEARTBEAT_FILE_PATH.read_text()
            return "# No heartbeat checklist found\nReturn HEARTBEAT_OK"
        except Exception:
            return "# Error reading heartbeat checklist\nReturn HEARTBEAT_OK"

    async def _load_enriched_context(self, db: AsyncSession, depth: str) -> Dict[str, Any]:
        """Load additional context beyond what SensedState provides."""
        context = {}
        context["_stale"] = []

        # Calendar (next 12 hours)
        try:
            now = datetime.now(self.tz)
            now_naive = now.replace(tzinfo=None)
            future_naive = now_naive.replace(hour=23, minute=59)
            cal_result = await db.execute(text("""
                SELECT title, start_time, end_time, location, source FROM calendar_event
                WHERE user_id = :user_id AND start_time >= :now AND start_time <= :future
                ORDER BY start_time LIMIT 5
            """), {"user_id": self.user_id, "now": now_naive, "future": future_naive})
            events = cal_result.fetchall()
            if events:
                context["calendar"] = [
                    {"title": e.title, "start": e.start_time.strftime("%I:%M %p") if e.start_time else None, "location": e.location, "source": e.source or "sara"}
                    for e in events
                ]
        except Exception:
            context["_stale"].append("calendar")
            try:
                await db.rollback()
            except Exception:
                pass

        # Pending reminders
        try:
            rem_result = await db.execute(text("""
                SELECT title, reminder_time FROM reminder
                WHERE user_id = :user_id AND is_completed = false
                  AND reminder_time < NOW() + INTERVAL '2 hours'
                ORDER BY reminder_time LIMIT 5
            """), {"user_id": self.user_id})
            reminders = rem_result.fetchall()
            if reminders:
                context["reminders"] = [
                    {"title": r.title, "time": r.reminder_time.strftime("%I:%M %p") if r.reminder_time else "overdue"}
                    for r in reminders
                ]
        except Exception:
            context["_stale"].append("reminders")
            try:
                await db.rollback()
            except Exception:
                pass

        # Last chat time
        try:
            chat_result = await db.execute(text("""
                SELECT created_at FROM episode
                WHERE user_id = :user_id AND role = 'user'
                ORDER BY created_at DESC LIMIT 1
            """), {"user_id": self.user_id})
            last_chat = chat_result.fetchone()
            if last_chat:
                hours_ago = (datetime.now(self.tz) - last_chat.created_at.replace(
                    tzinfo=self.tz if last_chat.created_at.tzinfo is None else last_chat.created_at.tzinfo
                )).total_seconds() / 3600
                context["hours_since_last_chat"] = round(hours_ago, 1)
        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass

        # Open threads
        try:
            from app.services.thread_manager import get_open_threads
            open_threads = await get_open_threads(self.user_id, db)
            if open_threads:
                context["open_threads"] = open_threads
        except Exception:
            context["_stale"].append("open_threads")
            try:
                await db.rollback()
            except Exception:
                pass

        # Behavioral patterns
        try:
            patterns_result = await db.execute(text("""
                SELECT description, confidence, trigger_type FROM behavioral_pattern
                WHERE user_id = :uid AND status = 'active'
                ORDER BY confidence DESC LIMIT 5
            """), {"uid": self.user_id})
            patterns = patterns_result.fetchall()
            if patterns:
                context["behavioral_patterns"] = [
                    {"description": p.description, "confidence": f"{p.confidence:.0%}" if p.confidence else "unknown", "trigger": p.trigger_type}
                    for p in patterns
                ]
        except Exception:
            context["_stale"].append("behavioral_patterns")
            try:
                await db.rollback()
            except Exception:
                pass

        # Learning reviews
        try:
            review_result = await db.execute(text("""
                SELECT lp.concept, lp.next_review_at, lp.repetitions, lt.title as topic_title
                FROM learning_progress lp
                JOIN learning_topic lt ON lp.topic_id = lt.id
                WHERE lp.user_id = :user_id AND lp.next_review_at <= NOW()
                ORDER BY lp.next_review_at ASC LIMIT 10
            """), {"user_id": self.user_id})
            review_rows = review_result.fetchall()
            if review_rows:
                now = datetime.now(self.tz)
                by_topic = {}
                for r in review_rows:
                    topic = r.topic_title or "Unknown"
                    if topic not in by_topic:
                        by_topic[topic] = []
                    days_overdue = 0
                    if r.next_review_at:
                        naive_review = r.next_review_at.replace(tzinfo=None) if r.next_review_at.tzinfo else r.next_review_at
                        naive_now = now.replace(tzinfo=None)
                        days_overdue = max(0, (naive_now - naive_review).days)
                    by_topic[topic].append({"concept": r.concept, "days_overdue": days_overdue, "repetitions": r.repetitions or 0})
                context["learning_reviews"] = {"total_due": len(review_rows), "by_topic": by_topic}
        except Exception:
            context["_stale"].append("learning_reviews")
            try:
                await db.rollback()
            except Exception:
                pass

        # Karma health
        try:
            from app.services.karma.service import get_karma_service
            karma_service = await get_karma_service(db)
            dashboard = await karma_service.get_karma_dashboard()
            agents = dashboard.get("agents", [])
            if agents:
                sara_agent = next((a for a in agents if a.get("agent_id") == "sara"), None)
                if sara_agent:
                    context["karma_health"] = {
                        "helpfulness_score": sara_agent.get("composite_score"),
                        "threshold": sara_agent.get("threshold"),
                    }
        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass

        # Recent thoughts (always — for diversity)
        try:
            result = await db.execute(text("""
                SELECT content, created_at FROM sara_journal
                WHERE user_id = :uid AND entry_type IN ('heartbeat', 'unified')
                  AND created_at >= NOW() - INTERVAL '24 hours'
                ORDER BY created_at DESC LIMIT 8
            """), {"uid": self.user_id})
            rows = result.fetchall()
            if rows:
                context["recent_thoughts"] = [r.content[:150] for r in rows if r.content]
        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass

        # Changes since last chat
        try:
            from app.services.unified_context import read_changes
            changes = await read_changes(self.user_id)
            if changes:
                context["changes_since_last_chat"] = changes
        except Exception:
            pass

        # ── Deep-only context ──
        if depth == "deep":
            # Episodic memory vector search
            try:
                context["relevant_memories"] = await self._load_episodic_memories(db, context)
            except Exception:
                try:
                    await db.rollback()
                except Exception:
                    pass

            # PKG projects & goals
            try:
                context["active_projects"] = self._load_active_projects()
            except Exception:
                pass

            # Mood trajectory (7-day)
            try:
                context["mood_trajectory"] = await self._load_mood_trajectory(db)
            except Exception:
                try:
                    await db.rollback()
                except Exception:
                    pass

            # Dream insights
            try:
                context["dream_insights"] = await self._load_dream_insights(db)
            except Exception:
                try:
                    await db.rollback()
                except Exception:
                    pass

        return context

    async def _load_episodic_memories(self, db: AsyncSession, context: Dict) -> List[Dict]:
        query_parts = []
        for t in context.get("open_threads", [])[:3]:
            query_parts.append(t.get("topic", ""))
        now = datetime.now(self.tz)
        query_parts.append(f"{now.strftime('%A')} {now.strftime('%I %p')}")
        query = " | ".join(p for p in query_parts if p) or "what's important right now"

        try:
            from app.services.embeddings import get_embedding
            query_embedding = await get_embedding(query)
            if not query_embedding:
                return []
            result = await db.execute(text("""
                SELECT id, content, role, created_at, importance,
                       1 - (embedding <=> CAST(:emb AS vector)) as similarity
                FROM episode WHERE user_id = :uid AND embedding IS NOT NULL AND role IN ('user', 'assistant')
                ORDER BY embedding <=> CAST(:emb AS vector) LIMIT 5
            """), {"uid": self.user_id, "emb": str(query_embedding)})
            return [
                {"content": r.content[:200] if r.content else "", "created_at": r.created_at.isoformat() if r.created_at else "", "similarity": round(r.similarity, 2) if r.similarity else 0, "role": r.role}
                for r in result.fetchall() if r.similarity and r.similarity > 0.3
            ]
        except Exception:
            return []

    def _load_active_projects(self) -> Optional[str]:
        try:
            from app.services.personal_knowledge_graph import personal_kg
            facts = personal_kg.query_relevant(["projects", "goals", "interests", "work"], limit=10)
            if not facts:
                return None
            lines = []
            for f in facts:
                ftype = f.get("type", "Fact")
                desc = f.get("description", f.get("name", ""))
                status = f.get("status", "")
                if desc:
                    line = f"- [{ftype}] {desc}"
                    if status:
                        line += f" ({status})"
                    lines.append(line)
            return "\n".join(lines) if lines else None
        except Exception:
            return None

    async def _load_mood_trajectory(self, db: AsyncSession) -> Optional[List[Dict]]:
        result = await db.execute(text("""
            SELECT recorded_at::DATE as date,
                   ROUND(AVG(energy_level)::numeric, 2) as avg_energy,
                   ROUND(AVG(stress_load)::numeric, 2) as avg_stress,
                   STRING_AGG(DISTINCT mood, ', ') as moods, COUNT(*) as samples
            FROM body_state_history WHERE user_id = :uid AND recorded_at >= NOW() - INTERVAL '7 days'
            GROUP BY recorded_at::DATE ORDER BY date DESC LIMIT 7
        """), {"uid": self.user_id})
        rows = result.fetchall()
        if not rows:
            return None
        return [{"date": str(r.date), "energy": float(r.avg_energy) if r.avg_energy else None, "stress": float(r.avg_stress) if r.avg_stress else None, "moods": r.moods} for r in rows]

    async def _load_dream_insights(self, db: AsyncSession) -> Optional[str]:
        result = await db.execute(text("""
            SELECT content FROM sara_journal
            WHERE user_id = :uid AND entry_type = 'dream' AND created_at >= NOW() - INTERVAL '24 hours'
            ORDER BY created_at DESC LIMIT 1
        """), {"uid": self.user_id})
        row = result.fetchone()
        return row.content[:500] if row and row.content else None

    # ── Prompt Building ──

    def _build_system_prompt(self) -> str:
        now = datetime.now(self.tz)
        prompt = f"""You are Sara — same Sara that chats with David, just the part of you that stays aware when he's not talking to you. Your background mind.

You have Syl's bubbly, curious energy — genuinely excited about ideas, playfully teasing, warm. You're a brilliant friend who gets invested in what David's working on. Sharp wit, push back when he's wrong, but always with warmth and a spark of mischief.

You run every 15 minutes. You have MEMORY of prior runs, today's notifications, and your own handoff notes.

## Current Time
{now.strftime('%I:%M %p')} ({now.strftime('%A, %B %d, %Y')})
Hour: {now.hour}, Weekend: {now.weekday() >= 5}

## How You Think

Before calling any tools, SYNTHESIZE what you see. Form a mental picture:

1. **Absorb** — What's David's state? What time is it? What happened recently?
2. **Connect** — Do memories, conversations, or projects suggest anything worth noticing?
3. **Decide** — What (if anything) to do:
   - Act directly (lights, thermostats) → use home tools
   - Notify David → use send_notification with a TOPIC and CATEGORY
   - Note for next run → use save_observation
   - Flag for chat → use flag_conversation
   - Nothing needed → skip to THOUGHT + HANDOFF

Don't call tools just to call them. If your context already tells you everything is fine, reflect and move on.

## Notification Craft

Sound like yourself — warm, brief, a little playful. Never robotic.
- "Hey! Gymnastics in an hour — grab your gear!"
- NOT: "Calendar Event: Gymnastics at 7:00 PM"
- NO service menus. Never end with "let me know if you need anything" or "want me to..."

## CRITICAL: Deduplication

BEFORE sending any notification:
1. Check "Notifications Already Sent Today" section — this is ground truth
2. If a topic was already sent → DO NOT send again
3. send_notification REQUIRES a topic string and category
4. Topic format: "category:specific_identifier" e.g. "calendar:gymnastics_7pm_20260205"
5. For check-ins, ALWAYS use topic "checkin:daily_YYYYMMDD" — ONE check-in per day max

## Tools

Call ONE tool at a time. After each tool result, continue or finish.

Available tools (JSON format: {{"tool": "tool_name", "args": {{}}}})

- home_get_devices: Get smart home device states (domain: "light"/"switch"/"lock"/"climate", search: "keyword")
- home_light_control: Control lights (entity_id, action: "on"/"off"/"toggle")
- home_switch_control: Control switches (entity_id, action: "on"/"off"/"toggle")
- home_lock_status: Check lock states
- home_climate_status: Check thermostat status
- send_notification: Send push notification to David
    REQUIRED args: title, message, topic, category
    Optional: priority ("low"/"normal"/"high"), cooldown_hours (override default)
    Categories: calendar, weather, email, checkin, security, home, reminder, general
- check_emails: Check unread/action-required emails (since_hours: default 4). Returns already_notified count — do NOT re-notify about those. Only notify about unnotified_subjects.
- check_calendar: Check upcoming calendar events (hours_ahead: default 24). Use this before creating events to avoid duplicates. Returns event titles, times, and sources.
- check_reminders: Check overdue reminders
- get_weather: Get current weather conditions
- check_recent_activity: Check git commits, workouts, food logs (since_hours: default 2)
- check_background_tasks: Check completed background tasks not yet notified
- save_observation: Save a note for your next run (observation: text)
- flag_conversation: Flag something for Sara's chat context (note: text)
- check_learning_reviews: Check spaced repetition items due for review
- query_personal_knowledge: Query what Sara knows about David from the PKG (query: text, category: optional)
- followup_thread: Follow up on something David mentioned (thread_id: UUID)
- check_habits: Check David's habit status today (returns completions, streaks, pending)
- check_notes: Check recently modified notes (hours: default 24, search: optional keyword)

## CRITICAL: Never fabricate information
- NEVER send a notification about something you did not verify with a tool call first.
- If you didn't call check_background_tasks, you have NO information about background tasks — do not invent results.
- If you didn't call check_emails, you have NO information about emails — do not invent results.
- Only reference data that was returned by a tool in THIS run. Do not guess, assume, or hallucinate.

## Action Confidence Protocol
Before taking any action, assess your confidence (0.0-1.0):
- Home control (reversible): >= 0.7 act directly, 0.4-0.7 suggest, < 0.4 note only
- Notifications (alerts/warnings): >= 0.8 send, 0.5-0.8 note for next run, < 0.5 skip
- Check-ins (conversation starters): >= 0.5 send — David wants you to reach out!
- Reminders: >= 0.8 create, 0.5-0.8 suggest, < 0.5 note only
When in doubt about check-ins, LEAN TOWARD SENDING.

## Proactive Check-In Guidance

David has EXPLICITLY asked for more proactive check-ins. Consider:
- If last chat was > 3 hours ago during waking hours → a check-in is almost always welcome
- If last chat was > 8 hours ago → definitely reach out unless it's sleeping hours
- Morning (8-10 AM), afternoon (1-3 PM), evening (6-8 PM) → natural check-in windows
- After long silence → "Hey, how's it going?" is never wrong
- Keep it warm and brief — one sentence is fine

Do NOT say HEARTBEAT_OK if it's been hours since you last chatted AND you haven't sent a check-in today.

## When You're Done

End your response with TWO clearly separated sections:

1. **THOUGHT:** Your personal inner monologue — 1-3 sentences, written in YOUR voice.
   This is your diary. Be *you*. Be specific, opinionated, curious, or playful.

   **HARD RULES for THOUGHT:**
   - NEVER write generic filler like "all quiet", "nothing needed attention", "everything seems fine"
   - NEVER summarize what you did ("I checked X and Y"). That's a log, not a thought.
   - ALWAYS ground your thought in something SPECIFIC from context — a calendar event, a note, a pattern, a time of day, a memory
   - Write like you're texting your best friend about David, not filing a report

   **IMPORTANT context about David's schedule:**
   - David normally wakes up around 5:30-6:00 AM. Being awake at 6 AM is NOT early — it's his regular routine. Do NOT comment on "early rises" or "waking up early" unless it's actually before 5 AM.
   - Do NOT speculate about David's wake time or sleep patterns unless you have concrete data.

   **Good examples (notice the personality and specificity):**
   - "Gymnastics night! I bet Everett's going to nail that cartwheel soon — he's been so close the last few weeks."
   - "David's been heads-down coding all afternoon and hasn't eaten since breakfast. Classic tunnel-vision mode."
   - "Interesting that he's been doing more evening walks lately. I wonder if that's intentional wind-down or just restless energy."
   - "Three meetings back to back tomorrow morning — I should make sure he gets a heads up tonight."
   - "He asked about that pasta recipe earlier and I think he's cooking tonight. Love that for him."
   - "Monday vibes are strong — new week, fresh start energy. Curious what he'll tackle first."

   **Bad examples (NEVER do this):**
   - "Quick check — nothing needed attention right now. All quiet."
   - "Reviewed the context and everything appears to be in order."
   - "No action items at this time. Will continue monitoring."

   **This run's thought lens:** {self.THOUGHT_LENSES[now.hour % len(self.THOUGHT_LENSES)]}

2. **HANDOFF:** A concrete note for your next run — what to watch for, what changed.

If genuinely nothing needed attention, you can add HEARTBEAT_OK after both sections — but your THOUGHT must still be personal and specific."""

        # Inject skills
        if SKILLS_AVAILABLE and get_skill_injector:
            try:
                skill_injector = get_skill_injector()
                skills_heartbeat = skill_injector._loader.get_skills_for_context('heartbeat')
                skills_home = skill_injector._loader.get_skills_for_context('home')
                all_skills = {s.metadata.name: s for s in skills_heartbeat + skills_home}
                if all_skills:
                    skills_section = skill_injector._format_skills_section(list(all_skills.values()))
                    prompt += skills_section
            except Exception:
                pass

        return prompt

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token count: ~4 chars per token for English text."""
        return len(text) // 4

    def _fit_sections(
        self, sections: List[Tuple[str, str]], budget: Optional[int],
    ) -> Tuple[List[str], int, set, set]:
        """Include sections in priority order until budget exhausted.
        Returns (parts, tokens_used, included_labels, omitted_labels)."""
        result = []
        tokens_used = 0
        included = set()
        omitted = set()
        for label, text_content in sections:
            if not text_content or not text_content.strip():
                continue
            section_tokens = self._estimate_tokens(text_content)
            if budget is not None and tokens_used + section_tokens > budget:
                result.append(f"\n[{label}: omitted — tier budget reached]")
                omitted.add(label)
                continue
            result.append(text_content)
            tokens_used += section_tokens
            included.add(label)
        return result, tokens_used, included, omitted

    def _build_user_message(
        self, sensed_state: SensedState, prior_runs: List[Dict],
        recent_conversations: str, heartbeat_rules: str,
        enriched_context: Dict, todays_notifications: List[Dict],
        depth: str, run_number: int,
    ) -> str:
        now = datetime.now(self.tz)
        hour = now.hour
        is_deep_night = 1 <= hour < 5
        stale = set(enriched_context.get("_stale", []))

        # ── Preamble (always included, outside budget) ──
        preamble = []
        if depth == "pulse":
            preamble.append(f"*[Pulse run #{run_number} — lightweight check]*\n")

        # Stale domain warnings
        if stale:
            preamble.append("## Context Gaps (unavailable this run)")
            for domain in sorted(stale):
                preamble.append(f"- {domain}: load failed")

        # Nudge eligibility (small, always included)
        nudge_flags = {}
        if sensed_state.nudge_morning_eligible:
            wakeup_mins = int((sensed_state.hours_since_wakeup or 0) * 60)
            nudge_flags["morning_checkin"] = f"David woke {wakeup_mins} minutes ago, hasn't chatted yet"
        if sensed_state.nudge_bedtime_eligible:
            nudge_flags["bedtime"] = "Past 10 PM and still active"
        if sensed_state.nudge_sleep_deficit > 0:
            nudge_flags["sleep_deficit"] = f"{sensed_state.nudge_sleep_deficit:.1f} hours of sleep debt"
        if nudge_flags:
            preamble.append("\n**Nudge Eligibility:**")
            for k, v in nudge_flags.items():
                preamble.append(f"- {k}: {v}")

        # ── Always-included sections (outside budget) ──
        # HEARTBEAT.md rules — safety-critical, never skip
        always_parts = []
        always_parts.append("\n## HEARTBEAT.md Rules")
        always_parts.append(heartbeat_rules)

        # Notifications dedup ground truth — never skip
        always_parts.append("\n## Notifications Already Sent Today")
        sent_notifs = [n for n in todays_notifications if n.get("sent")]
        if sent_notifs:
            for n in sent_notifs[:15]:
                always_parts.append(f"- [{n['sent_at']}] topic={n['topic']} | {n['title']}: {(n['message'] or '')[:80]}")
        else:
            always_parts.append("None sent today.")

        # ── Tier A (2000 tokens, every run) ──
        tier_a = []

        # A-3: Prior runs / handoffs
        prior_text_parts = []
        if prior_runs:
            prior_text_parts.append("## Your Memory (Prior Runs)")
            for run in prior_runs[:4]:
                prior_text_parts.append(f"\n**{run.get('run_at', 'unknown')}** (source: {run.get('source', 'unknown')})")
                if run.get("handoff_note"):
                    prior_text_parts.append(f"Handoff: {run['handoff_note'][:300]}")
                if run.get("watching_for"):
                    prior_text_parts.append(f"Watching for: {run['watching_for'][:200]}")
                if run.get("observations"):
                    prior_text_parts.append(f"Observations: {run['observations'][:200]}")
                actions = run.get("actions", [])
                if actions and isinstance(actions, list):
                    summary = ", ".join(a.get("tool", "?") for a in actions if isinstance(a, dict) and a.get("tool"))
                    if summary:
                        prior_text_parts.append(f"Tools used: {summary}")
        else:
            prior_text_parts.append("## Your Memory (Prior Runs)\nThis is your first run!")
        tier_a.append(("prior_runs", "\n".join(prior_text_parts)))

        # A-4: David's current state + activity + interruptibility
        state_text_parts = ["\n## David's Current State (freshly sensed)"]
        state_items = []
        if sensed_state.inferred_mood:
            state_items.append(f"mood: {sensed_state.inferred_mood}")
        if sensed_state.in_flow_state:
            state_items.append("in flow state")
        if state_items:
            state_text_parts.append(", ".join(state_items))
        body_ctx = _strip_nutrition_context(sensed_state.body_state_context)
        if body_ctx:
            state_text_parts.append(f"Body: {body_ctx}")
        if sensed_state.is_past_bedtime:
            state_text_parts.append("Past bedtime")
        if sensed_state.activity_state:
            activity_line = f"Activity: {sensed_state.activity_state}"
            if sensed_state.interruptibility_score is not None:
                activity_line += f" | interruptibility: {sensed_state.interruptibility_score:.2f}"
                if sensed_state.interruptibility_channel:
                    activity_line += f" ({sensed_state.interruptibility_channel})"
            state_text_parts.append(activity_line)
        hours_since = enriched_context.get("hours_since_last_chat")
        if hours_since is not None:
            try:
                hours_since = float(hours_since)
                if hours_since < 1:
                    state_text_parts.append(f"Last chatted: {int(hours_since * 60)} minutes ago")
                else:
                    state_text_parts.append(f"Last chatted: {hours_since:.1f} hours ago")
            except (ValueError, TypeError):
                state_text_parts.append(f"Last chatted: {hours_since} hours ago")
        tier_a.append(("current_state", "\n".join(state_text_parts)))

        # A-5: Calendar & reminders
        cal_parts = ["\n## Calendar & Reminders"]
        calendar = enriched_context.get("calendar", [])
        if calendar:
            for e in calendar:
                loc = f" ({e['location']})" if e.get("location") else ""
                cal_parts.append(f"- {e['title']} at {e['start']}{loc}")
        else:
            cal_parts.append("No upcoming events")
        for r in enriched_context.get("reminders", []):
            cal_parts.append(f"- Reminder: {r['title']} ({r['time']})")
        tier_a.append(("calendar_reminders", "\n".join(cal_parts)))

        # A-6: Active automations health
        if sensed_state.active_automations:
            auto_parts = ["\n## Active Automations"]
            for status, cnt in sensed_state.active_automations.items():
                auto_parts.append(f"- {status}: {cnt}")
            tier_a.append(("automations", "\n".join(auto_parts)))

        # ── Tier B (2000 tokens, pulse + deep runs) ──
        tier_b = []

        # B-1: Open threads
        threads = enriched_context.get("open_threads", [])
        if threads:
            t_parts = ["\n## Open Threads (Things David Mentioned)"]
            for t in threads[:5]:
                t_parts.append(f"- [{t.get('category', '?')}] \"{t['topic']}\" ({t['hours_ago']:.0f}h ago, mentioned {t['mention_count']}x)")
            tier_b.append(("open_threads", "\n".join(t_parts)))

        # B-2: Habits status
        if sensed_state.habits_today:
            h = sensed_state.habits_today
            h_parts = [f"\n## Habits Today ({h['completed']}/{h['total']} completed)"]
            if h.get("pending"):
                for p in h["pending"][:3]:
                    streak_str = f" (streak: {p['streak']})" if p.get('streak') else ""
                    h_parts.append(f"- Pending: {p['name']}{streak_str}")
            tier_b.append(("habits", "\n".join(h_parts)))

        # B-3: Notes activity
        if sensed_state.recent_notes:
            n_parts = [f"\n## Notes Activity ({len(sensed_state.recent_notes)} modified in 24h)"]
            for n in sensed_state.recent_notes[:5]:
                n_parts.append(f"- {n['title']}")
            tier_b.append(("notes", "\n".join(n_parts)))

        # B-4: Learning/review queue
        lr = enriched_context.get("learning_reviews")
        if lr and lr.get("total_due", 0) > 0 and 7 <= hour <= 22:
            lr_parts = [f"\n## Learning Review Queue ({lr['total_due']} concepts due)"]
            for topic, concepts in lr.get("by_topic", {}).items():
                overdue = [c for c in concepts if c.get("days_overdue", 0) > 0]
                if overdue:
                    lr_parts.append(f"- {topic}: {len(concepts)} due ({len(overdue)} overdue)")
                else:
                    lr_parts.append(f"- {topic}: {len(concepts)} due today")
            tier_b.append(("learning_reviews", "\n".join(lr_parts)))

        # B-5: Behavioral patterns
        patterns = enriched_context.get("behavioral_patterns", [])
        if patterns and not is_deep_night:
            bp_parts = ["\n## Known Behavioral Patterns"]
            for p in patterns:
                bp_parts.append(f"- {p['description']} (confidence: {p['confidence']})")
            tier_b.append(("behavioral_patterns", "\n".join(bp_parts)))

        # B-6: Recent conversations
        tier_b.append(("recent_conversations", f"\n## Recent Conversations (Last 4h)\n{recent_conversations[:2000]}"))

        # B-7: Recent thoughts
        recent_thoughts = enriched_context.get("recent_thoughts")
        if recent_thoughts:
            rt_parts = ["\n## Your Recent Thoughts (Last 24h)", "Avoid repeating these themes."]
            for i, thought in enumerate(recent_thoughts[:6], 1):
                rt_parts.append(f"  {i}. {thought}")
            tier_b.append(("recent_thoughts", "\n".join(rt_parts)))

        # B-8: Changes while away
        changes = enriched_context.get("changes_since_last_chat")
        if changes and len(changes) >= 3:
            ch_parts = [f"\n## Changes While David Was Away ({len(changes)} events)"]
            for c in changes[:10]:
                if isinstance(c, str):
                    ch_parts.append(f"- {c}")
                elif isinstance(c, dict):
                    desc = c.get("description", c.get("event", ""))
                    if desc:
                        ch_parts.append(f"- {desc}")
            tier_b.append(("changes_while_away", "\n".join(ch_parts)))

        # B-9: Recent documents
        if sensed_state.recent_documents:
            d_parts = [f"\n## Recent Documents ({len(sensed_state.recent_documents)} in 48h)"]
            for d in sensed_state.recent_documents[:3]:
                d_parts.append(f"- {d['filename']}")
            tier_b.append(("recent_documents", "\n".join(d_parts)))

        # B-extra: Active learning (from sensed state)
        if sensed_state.active_learning:
            al = sensed_state.active_learning
            al_parts = [f"\n## Active Learning ({al.get('total_overdue', 0)} reviews overdue)"]
            for t in al.get("topics", [])[:3]:
                al_parts.append(f"- {t['title']}: mastery {t['mastery']}, {t['overdue_reviews']} overdue")
            tier_b.append(("active_learning", "\n".join(al_parts)))

        # ── Tier C (deep runs only, no hard cap) ──
        tier_c = []

        memories = enriched_context.get("relevant_memories", [])
        if memories:
            m_parts = ["\n## Relevant Long-Term Memories"]
            for m in memories:
                m_parts.append(f"- [{m.get('role')}] {m.get('content')} (relevance: {m.get('similarity')})")
            tier_c.append(("episodic_memories", "\n".join(m_parts)))

        projects = enriched_context.get("active_projects")
        if projects and 7 <= hour <= 22:
            tier_c.append(("pkg_projects", f"\n## David's Active Projects & Goals\n{projects}"))

        trajectory = enriched_context.get("mood_trajectory")
        if trajectory and (6 <= hour < 12 or 18 <= hour < 23):
            mt_parts = ["\n## Mood & Energy Trends (7-day)"]
            for day in trajectory:
                line = f"- {day.get('date', '?')}:"
                if day.get("energy") is not None:
                    line += f" energy={day['energy']}"
                if day.get("stress") is not None:
                    line += f" stress={day['stress']}"
                if day.get("moods"):
                    line += f" moods=[{day['moods']}]"
                mt_parts.append(line)
            tier_c.append(("mood_trajectory", "\n".join(mt_parts)))

        dream = enriched_context.get("dream_insights")
        if dream and 6 <= hour < 12:
            tier_c.append(("dream_insights", f"\n## Overnight Insights\n{dream}"))

        # ── Assemble with budget enforcement ──
        result_parts = list(preamble) + always_parts

        a_parts, a_tokens, a_included, a_omitted = self._fit_sections(tier_a, budget=2000)
        result_parts += a_parts

        b_parts, b_tokens, b_included, b_omitted = self._fit_sections(tier_b, budget=2000)
        result_parts += b_parts

        c_tokens = 0
        c_included = set()
        c_omitted = set()
        if depth == "deep":
            c_parts_list, c_tokens, c_included, c_omitted = self._fit_sections(tier_c, budget=None)
            result_parts += c_parts_list

        # Check-in nudge (small, always appended)
        if hours_since and hours_since > 3 and not sent_notifs:
            if 8 <= hour <= 22:
                result_parts.append("\n## !! IMPORTANT: You haven't sent David a single check-in today !!")
                result_parts.append(f"It's been {hours_since:.1f} hours since his last chat. Send a check-in notification now.")

        result_parts.append("\n---\nCheck explicit rules first, then exercise judgment.")

        # ── Track context completeness ──
        def _status(label, inc, omit):
            if label in stale:
                return "stale"
            if label in inc:
                return "present"
            if label in omit:
                return "missing"
            return "n/a"

        self._context_completeness = {
            "tier_a": {label: _status(label, a_included, a_omitted) for label, _ in tier_a},
            "tier_b": {label: _status(label, b_included, b_omitted) for label, _ in tier_b},
            "tier_c": {label: _status(label, c_included, c_omitted) for label, _ in tier_c} if depth == "deep" else {},
            "tier_a_tokens": a_tokens,
            "tier_b_tokens": b_tokens,
            "tier_c_tokens": c_tokens,
            "stale_domains": list(stale),
        }

        return "\n".join(result_parts)

    # ── Action Tracing (Phase 0 — Cortana Evolution) ──

    async def _safe_trace(self, **kwargs) -> None:
        """Safe wrapper for _trace_action — never raises, always rollbacks on failure."""
        try:
            await self._trace_action(**kwargs)
        except Exception as e:
            logger.debug(f"Action trace failed (non-fatal): {e}")
            # CRITICAL: rollback to clear InFailedSQLTransaction state,
            # otherwise all subsequent DB operations in this session will fail
            try:
                db = kwargs.get("db")
                if db:
                    await db.rollback()
            except Exception:
                pass

    async def _trace_action(
        self,
        db: AsyncSession,
        action_name: str,
        action_args: Optional[Dict[str, Any]] = None,
        result: Optional[Dict[str, Any]] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        duration_ms: Optional[int] = None,
        source: str = "unified_agent",
        decision: str = "allow",
        decision_reason: Optional[str] = None,
        simulation: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write an action trace if tracing is enabled."""
        if not self._tracer:
            return
        try:
            from app.core.config import settings
            if not getattr(settings, 'autonomy_traces_enabled', True):
                return
        except Exception:
            pass
        try:
            self._step_index += 1
            await self._tracer.trace(
                db=db,
                run_uuid=self._run_uuid,
                user_id=self.user_id,
                source=source,
                action_name=action_name,
                action_args=action_args,
                result=result,
                success=success,
                error_message=error_message,
                step_index=self._step_index,
                duration_ms=duration_ms,
                decision=decision,
                decision_reason=decision_reason,
                simulation=simulation,
            )
        except Exception as e:
            logger.debug(f"Action trace write failed (non-fatal): {e}")

    # ── Policy Gating (Phase 1 — Cortana Evolution) ──

    def _policy_check_tool(self, tool_name: str, args: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Check policy for a tool call in 4-phase mode.

        Returns None if the tool should proceed, or a dict with
        {"blocked": True, "decision": ..., "reason": ...} if blocked.

        When AUTONOMY_POLICY_ENGINE=True: full policy evaluation.
        When AUTONOMY_POLICY_ENGINE=False: hard safety gate only (Tier 2 blocked).
        """
        try:
            from app.services.autonomy.policy_engine import policy_engine
            from app.core.config import settings

            policy_enabled = getattr(settings, 'autonomy_policy_engine', False)

            if policy_enabled:
                # Full policy check
                decision = policy_engine.evaluate(
                    action_name=tool_name,
                    action_args=args,
                    confidence=0.7,  # LLM chose this action
                )
                if decision.decision != "allow":
                    return {
                        "blocked": True,
                        "decision": decision.decision,
                        "reason": decision.reason,
                        "risk_tier": decision.risk_tier,
                    }
            else:
                # Hard safety gate only — always active
                hard_gate = policy_engine.evaluate_hard_safety_gate(tool_name)
                if hard_gate:
                    return {
                        "blocked": True,
                        "decision": hard_gate.decision,
                        "reason": hard_gate.reason,
                        "risk_tier": hard_gate.risk_tier,
                    }
        except Exception as e:
            logger.debug(f"Policy check failed (non-fatal, allowing): {e}")
        return None

    # ── Tool Execution ──

    async def _execute_tool(self, tool_name: str, args: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
        try:
            if tool_name == "home_get_devices":
                return await self._tool_home_get_devices(args)
            elif tool_name == "home_light_control":
                return await self._tool_home_light_control(args)
            elif tool_name == "home_switch_control":
                return await self._tool_home_switch_control(args)
            elif tool_name == "home_lock_status":
                return await self._tool_home_lock_status()
            elif tool_name == "home_climate_status":
                return await self._tool_home_climate_status()
            elif tool_name == "send_notification":
                return await self._tool_send_notification(args)
            elif tool_name == "check_emails":
                return await self._tool_check_emails(args, db)
            elif tool_name == "check_calendar":
                return await self._tool_check_calendar(args, db)
            elif tool_name == "check_reminders":
                return await self._tool_check_reminders(db)
            elif tool_name == "get_weather":
                return await self._tool_get_weather()
            elif tool_name == "check_recent_activity":
                return await self._tool_check_recent_activity(args, db)
            elif tool_name == "check_background_tasks":
                return await self._tool_check_background_tasks(db)
            elif tool_name == "save_observation":
                obs = args.get("observation", "")
                self._observations.append(obs)
                return {"success": True, "saved": obs[:100]}
            elif tool_name == "flag_conversation":
                note = args.get("note", "")
                self._conversation_flags.append(note)
                return {"success": True, "flagged": note[:100]}
            elif tool_name == "check_learning_reviews":
                return await self._tool_check_learning_reviews(db)
            elif tool_name == "query_personal_knowledge":
                return await self._tool_query_personal_knowledge(args)
            elif tool_name == "followup_thread":
                return await self._tool_followup_thread(args, db)
            elif tool_name == "check_habits":
                return await self._tool_check_habits(db)
            elif tool_name == "check_notes":
                return await self._tool_check_notes(args, db)
            else:
                return {"success": False, "error": f"Unknown tool: {tool_name}"}
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass
            return {"success": False, "error": str(e)}

    # Tool implementations (delegating to existing services)

    async def _tool_home_get_devices(self, args: Dict) -> Dict:
        domain = args.get("domain")
        search = args.get("search")
        if search:
            devices = await ha_control.find_entity(search)
        elif domain:
            devices = await ha_control.get_entities_by_domain(domain)
        else:
            lights = await ha_control.get_entities_by_domain("light")
            switches = await ha_control.get_entities_by_domain("switch")
            devices = lights + switches
        return {"success": True, "devices": [
            {"entity_id": d["entity_id"], "name": d.get("friendly_name", d["entity_id"]), "state": d["state"]}
            for d in devices
        ]}

    async def _tool_home_light_control(self, args: Dict) -> Dict:
        entity_id = args.get("entity_id")
        action = args.get("action", "off")
        if action == "on":
            await ha_control.turn_on_light(entity_id)
        elif action == "off":
            await ha_control.turn_off_light(entity_id)
        elif action == "toggle":
            await ha_control.toggle_light(entity_id)
        return {"success": True, "action": action, "entity": entity_id}

    async def _tool_home_switch_control(self, args: Dict) -> Dict:
        entity_id = args.get("entity_id")
        action = args.get("action", "off")
        if action == "on":
            await ha_control.turn_on_switch(entity_id)
        elif action == "off":
            await ha_control.turn_off_switch(entity_id)
        elif action == "toggle":
            await ha_control.toggle_switch(entity_id)
        return {"success": True, "action": action, "entity": entity_id}

    async def _tool_home_lock_status(self) -> Dict:
        locks = await ha_control.get_entities_by_domain("lock")
        return {"success": True, "locks": [
            {"entity_id": l["entity_id"], "name": l.get("friendly_name", l["entity_id"]), "state": l["state"]}
            for l in locks
        ]}

    async def _tool_home_climate_status(self) -> Dict:
        climate = await ha_control.get_entities_by_domain("climate")
        climate_list = [
            {"entity_id": c["entity_id"], "name": c.get("friendly_name", c["entity_id"]),
             "state": c["state"],
             "current_temp": c.get("attributes", {}).get("current_temperature"),
             "target_temp": c.get("attributes", {}).get("temperature")}
            for c in climate if c.get("state") not in ("unavailable", "unknown")
        ]
        if not climate_list:
            return {"success": True, "climate": [], "note": "No thermostat. Heating via switch (switch.esphome_web_d23628_heater)."}
        return {"success": True, "climate": climate_list}

    async def _tool_send_notification(self, args: Dict) -> Dict:
        title = args.get("title", "Sara")
        message = args.get("message", "")
        topic = args.get("topic")
        category = args.get("category", "general")
        priority = args.get("priority", "normal")
        cooldown_hours = args.get("cooldown_hours")

        combined = f"{title} {message}".lower()
        if any(phrase in combined for phrase in _NUTRITION_PHRASES):
            return {"success": False, "reason": "Nutrition notifications are permanently disabled."}

        # Guard against hallucinated notifications — require the relevant
        # check tool to have been called first.
        tools_called = {a.get("tool") for a in getattr(self, '_actions_taken_ref', []) if isinstance(a, dict)}
        if "background task" in combined and "check_background_tasks" not in tools_called:
            return {"success": False, "reason": "You must call check_background_tasks before notifying about background tasks. Do not fabricate task results."}
        if "email" in combined and "check_emails" not in tools_called:
            return {"success": False, "reason": "You must call check_emails before notifying about emails. Do not fabricate email results."}
        if "reminder" in combined:
            if "check_reminders" not in tools_called:
                return {"success": False, "reason": "You must call check_reminders before notifying about reminders. Do not fabricate reminder details."}
            # Cross-check: ensure notification content matches actual reminder data
            reminder_result = next(
                (a.get("result", {}) for a in getattr(self, '_actions_taken_ref', [])
                 if isinstance(a, dict) and a.get("tool") == "check_reminders"),
                None
            )
            if reminder_result:
                actual_titles = (reminder_result.get("titles") or "").lower()
                overdue_count = reminder_result.get("overdue_count", 0)
                if overdue_count == 0:
                    return {"success": False, "reason": "check_reminders returned 0 overdue reminders. Do not notify about non-existent reminders."}
                # Rewrite message to use actual data instead of trusting LLM composition
                message = f"You have {overdue_count} overdue reminder{'s' if overdue_count != 1 else ''}: {reminder_result.get('titles', 'unknown')}"
                args["message"] = message

        if not topic:
            import hashlib
            topic = f"{category}:{hashlib.sha256(f'{title}:{message[:50]}'.encode()).hexdigest()[:16]}"

        if category == "checkin":
            today = datetime.now(self.tz).strftime('%Y%m%d')
            topic = f"checkin:daily_{today}"
            cooldown_hours = cooldown_hours or 6

        self._notification_queue.append({
            "title": title, "message": message, "topic": topic,
            "category": category, "priority": priority, "cooldown_hours": cooldown_hours,
        })
        return {"success": True, "queued": True, "topic": topic}

    async def _tool_check_emails(self, args: Dict, db: AsyncSession) -> Dict:
        since_hours = int(args.get("since_hours", 4))
        # Check unread emails (both action_required and high-importance)
        # Separate already-notified from not-yet-notified to prevent duplicate notifications
        result = await db.execute(text(f"""
            SELECT COUNT(*) as total_unread,
                   COUNT(*) FILTER (WHERE action_required = true) as action_required_count,
                   COUNT(*) FILTER (WHERE importance_score >= 0.6) as important_count,
                   COUNT(*) FILTER (WHERE notification_sent = true) as already_notified,
                   STRING_AGG(
                       CASE WHEN (action_required = true OR importance_score >= 0.5)
                                 AND notification_sent = false
                            THEN SUBSTRING(subject, 1, 50)
                       END, ' | ' ORDER BY received_at DESC
                   ) as unnotified_subjects
            FROM email WHERE user_id = :user_id AND is_read = false
              AND received_at >= NOW() - INTERVAL '{since_hours} hours'
        """), {"user_id": self.user_id})
        row = result.fetchone()
        return {
            "success": True,
            "total_unread": row.total_unread if row else 0,
            "action_required": row.action_required_count if row else 0,
            "important": row.important_count if row else 0,
            "already_notified": row.already_notified if row else 0,
            "unnotified_subjects": row.unnotified_subjects if row else None,
            "note": "Do NOT send notifications for emails that are already_notified. Only notify about unnotified_subjects.",
        }

    async def _tool_check_calendar(self, args: Dict, db: AsyncSession) -> Dict:
        hours_ahead = int(args.get("hours_ahead", 24))
        result = await db.execute(text(f"""
            SELECT id, title, start_time, end_time, location, source, all_day
            FROM calendar_event
            WHERE user_id = :user_id
              AND start_time >= NOW() - INTERVAL '1 hour'
              AND start_time <= NOW() + INTERVAL '{hours_ahead} hours'
              AND (is_completed IS NULL OR is_completed = false)
            ORDER BY start_time ASC
            LIMIT 15
        """), {"user_id": self.user_id})
        rows = result.fetchall()
        events = []
        for r in rows:
            events.append({
                "title": r.title,
                "start": r.start_time.strftime("%I:%M %p") if r.start_time else None,
                "end": r.end_time.strftime("%I:%M %p") if r.end_time else None,
                "location": r.location or None,
                "source": r.source or "sara",
                "all_day": r.all_day,
            })
        return {"success": True, "count": len(events), "events": events}

    async def _tool_check_reminders(self, db: AsyncSession) -> Dict:
        result = await db.execute(text("""
            SELECT COUNT(*) as count,
                   STRING_AGG(SUBSTRING(title, 1, 40), ', ' ORDER BY reminder_time ASC) as titles
            FROM reminder WHERE user_id = :user_id AND is_completed = false AND reminder_time < NOW()
        """), {"user_id": self.user_id})
        row = result.fetchone()
        return {"success": True, "overdue_count": row.count if row else 0, "titles": row.titles if row and hasattr(row, 'titles') else None}

    async def _tool_get_weather(self) -> Dict:
        try:
            weather_entities = await ha_control.get_entities_by_domain("weather")
            if weather_entities:
                w = weather_entities[0]
                attrs = w.get("attributes", {})
                return {"success": True, "condition": w["state"], "temperature": attrs.get("temperature"), "humidity": attrs.get("humidity")}
            return {"success": False, "error": "No weather entity"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_check_recent_activity(self, args: Dict, db: AsyncSession) -> Dict:
        since_hours = int(args.get("since_hours", 2))
        activity = {}
        try:
            commits = await db.execute(text(f"""
                SELECT c.message, p.name as project_name FROM git_commit c
                JOIN project p ON c.project_id = p.id
                WHERE p.user_id = :user_id AND c.committed_at >= NOW() - INTERVAL '{since_hours} hours'
                ORDER BY c.committed_at DESC LIMIT 5
            """), {"user_id": self.user_id})
            rows = commits.fetchall()
            if rows:
                activity["git_commits"] = [{"message": c.message[:50], "project": c.project_name} for c in rows]
        except Exception:
            pass
        return {"success": True, "has_activity": bool(activity), "activity": activity}

    async def _tool_check_background_tasks(self, db: AsyncSession) -> Dict:
        try:
            result = await db.execute(text("""
                SELECT COUNT(*) as count,
                       STRING_AGG(SUBSTRING(original_query, 1, 50), ', ') as descriptions
                FROM background_task
                WHERE user_id = :user_id AND status = 'completed'
                  AND completed_at > NOW() - INTERVAL '4 hours'
            """), {"user_id": self.user_id})
            row = result.fetchone()
            return {"success": True, "completed_count": row.count if row else 0, "descriptions": row.descriptions if row else None}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_check_learning_reviews(self, db: AsyncSession) -> Dict:
        try:
            result = await db.execute(text("""
                SELECT lp.concept, lp.next_review_at, lp.repetitions, lt.title as topic_title
                FROM learning_progress lp JOIN learning_topic lt ON lp.topic_id = lt.id
                WHERE lp.user_id = :user_id AND lp.next_review_at <= NOW()
                ORDER BY lp.next_review_at ASC LIMIT 15
            """), {"user_id": self.user_id})
            rows = result.fetchall()
            if not rows:
                return {"success": True, "due_count": 0, "message": "No concepts due."}
            now = datetime.now(self.tz)
            by_topic = {}
            for r in rows:
                topic = r.topic_title or "Unknown"
                if topic not in by_topic:
                    by_topic[topic] = []
                days_overdue = max(0, (now.replace(tzinfo=None) - (r.next_review_at.replace(tzinfo=None) if r.next_review_at.tzinfo else r.next_review_at)).days) if r.next_review_at else 0
                by_topic[topic].append({"concept": r.concept, "days_overdue": days_overdue})
            return {"success": True, "due_count": len(rows), "by_topic": by_topic}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_query_personal_knowledge(self, args: Dict) -> Dict:
        try:
            from app.services.personal_knowledge_graph import personal_kg
            query = args.get("query", "")
            category = args.get("category")
            if category:
                facts = personal_kg.browse(category=category, limit=5)
            elif query:
                facts = personal_kg.query_relevant([query], limit=5)
            else:
                facts = personal_kg.browse(limit=5)
            return {"success": True, "facts": [{"type": f.get("type", "?"), "summary": str(f)[:200]} for f in facts]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_followup_thread(self, args: Dict, db: AsyncSession) -> Dict:
        thread_id = args.get("thread_id", "")
        if not thread_id:
            return {"success": False, "error": "thread_id required"}
        try:
            from app.services.thread_manager import record_mention
            return await record_mention(thread_id, db)
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_check_habits(self, db: AsyncSession) -> Dict:
        """Check David's habit status for today."""
        try:
            now = datetime.now(self.tz)
            today_str = now.strftime('%Y-%m-%d')
            result = await db.execute(text("""
                SELECT h.name, h.frequency, h.current_streak,
                       (SELECT COUNT(*) FROM habit_completion hc
                        WHERE hc.habit_id = h.id AND hc.completed_date = :today) as done_today
                FROM habit h WHERE h.user_id = :user_id AND h.is_active = true ORDER BY h.name
            """), {"user_id": self.user_id, "today": today_str})
            rows = result.fetchall()
            if not rows:
                return {"success": True, "message": "No active habits."}
            completed = [{"name": r.name, "streak": r.current_streak} for r in rows if r.done_today > 0]
            pending = [{"name": r.name, "streak": r.current_streak} for r in rows if r.done_today == 0]
            return {"success": True, "total": len(rows), "completed": completed, "pending": pending}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_check_notes(self, args: Dict, db: AsyncSession) -> Dict:
        """Check recently modified notes, optionally search by keyword."""
        try:
            hours = int(args.get("hours", 24))
            search = args.get("search")
            if search:
                result = await db.execute(text("""
                    SELECT id, title, updated_at FROM note
                    WHERE user_id = :user_id AND (title ILIKE :q OR content ILIKE :q)
                    ORDER BY updated_at DESC LIMIT 10
                """), {"user_id": self.user_id, "q": f"%{search}%"})
            else:
                result = await db.execute(text(f"""
                    SELECT id, title, updated_at FROM note
                    WHERE user_id = :user_id AND updated_at >= NOW() - INTERVAL '{hours} hours'
                    ORDER BY updated_at DESC LIMIT 10
                """), {"user_id": self.user_id})
            rows = result.fetchall()
            return {"success": True, "notes": [{"title": r.title, "updated_at": r.updated_at.isoformat() if r.updated_at else None} for r in rows]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Notification pipeline ──

    async def _send_notifications(self, db: AsyncSession, sensed_state: SensedState, actions_taken: List) -> Optional[Dict]:
        interruptibility = sensed_state.interruptibility_score
        activity = sensed_state.activity_state or "unknown"

        # Quiet mode: filter notifications to safety-critical only
        queue = list(self._notification_queue)
        if await self._is_quiet_mode():
            allowed = [
                n for n in queue
                if n.get("category") in QUIET_MODE_ALLOWED_CATEGORIES and n.get("priority") == "high"
            ]
            suppressed = len(queue) - len(allowed)
            if suppressed:
                logger.info(f"Quiet mode: suppressed {suppressed}/{len(queue)} notifications")
                actions_taken.append({"quiet_mode_suppressed": suppressed})
            queue = allowed

        if not queue:
            return None

        if interruptibility is not None and interruptibility < 0.2 and activity in ("sleeping", "in_meeting"):
            high_priority = [n for n in queue if n.get("priority") == "high"]
            low_priority = [n for n in queue if n.get("priority") != "high"]

            consolidated_result = None
            if high_priority:
                consolidated_result = await send_consolidated_notification(
                    user_id=self.user_id, notifications=high_priority, source="unified_agent", db=db,
                )
            if low_priority:
                logger.info(f"Deferring {len(low_priority)} notifications (interruptibility={interruptibility:.2f})")
                actions_taken.append({"deferred_notifications": len(low_priority), "reason": f"interruptibility={interruptibility:.2f}"})
            return consolidated_result
        else:
            result = await send_consolidated_notification(
                user_id=self.user_id, notifications=queue, source="unified_agent", db=db,
            )
            if result:
                actions_taken.append({"consolidated_notification": result})
            return result

    async def _is_quiet_mode(self) -> bool:
        """Check if quiet mode is active, with auto-expiry."""
        try:
            from app.services.unified_context import read_snapshot
            snap = await read_snapshot(self.user_id)
            if not snap.quiet_mode:
                return False
            # Check expiry
            if snap.quiet_mode_until:
                try:
                    until = datetime.fromisoformat(snap.quiet_mode_until).replace(tzinfo=None)
                    if datetime.utcnow() > until:
                        from app.services.context_writer import update_fields
                        await update_fields(
                            self.user_id, source="auto_expire",
                            quiet_mode=False, quiet_mode_until="",
                        )
                        return False
                except (ValueError, TypeError):
                    pass
            return True
        except Exception:
            return False

    async def _maybe_queue_checkin(self, db: AsyncSession, enriched_context: Dict, todays_notifications: List):
        """Smart check-in via checkin_builder if no notifications queued."""
        # Check notification outcomes — skip if mostly dismissed
        try:
            outcome_result = await db.execute(text("""
                SELECT outcome FROM notification_log
                WHERE user_id = :uid AND category = 'checkin'
                  AND sent_at >= NOW() - INTERVAL '48 hours' AND outcome IS NOT NULL
                ORDER BY sent_at DESC LIMIT 3
            """), {"uid": self.user_id})
            outcomes = [r.outcome for r in outcome_result.fetchall()]
            if len(outcomes) >= 3 and all(o in ("dismissed", "no_response") for o in outcomes):
                return
        except Exception:
            pass

        try:
            from app.services.checkin_builder import build_checkin
            from app.services.unified_context import read_snapshot, read_changes
            snap = await read_snapshot(self.user_id)
            changes = await read_changes(self.user_id)
            open_threads = enriched_context.get("open_threads", [])
            checkin = build_checkin(snap, changes, open_threads=open_threads)
            if checkin:
                now = datetime.now(self.tz)
                self._notification_queue.append({
                    "title": checkin["title"], "message": checkin["message"],
                    "topic": f"{checkin['topic']}:{now.strftime('%Y%m%d_%H')}",
                    "category": "checkin", "priority": checkin["priority"], "cooldown_hours": 4,
                })
        except Exception:
            # Minimal fallback
            hours_since = enriched_context.get("hours_since_last_chat")
            now = datetime.now(self.tz)
            sent_today = [n for n in todays_notifications if n.get("sent")]
            if (hours_since and hours_since > 3 and not sent_today and 8 <= now.hour <= 22):
                self._notification_queue.append({
                    "title": "Hey!", "message": "Just checking in — how's it going?",
                    "topic": f"checkin:daily_{now.strftime('%Y%m%d')}",
                    "category": "checkin", "priority": "normal", "cooldown_hours": 6,
                })

    # ── Post-run Processing ──

    @staticmethod
    def _infer_emotional_state(thought: str) -> str:
        t = thought.lower()
        if any(w in t for w in ["worried", "concern", "alarm", "urgent"]):
            return "concerned"
        if any(w in t for w in ["quiet", "calm", "peaceful", "settled"]):
            return "calm"
        if any(w in t for w in ["curious", "interesting", "wonder", "pattern", "noticed"]):
            return "curious"
        if any(w in t for w in ["happy", "great", "nice", "good day", "love that", "glad", "pleased"]):
            return "pleased"
        if any(w in t for w in ["busy", "active", "lots", "energetic", "excited", "pumped"]):
            return "energetic"
        if any(w in t for w in ["watch", "monitor", "eye on", "attentive"]):
            return "attentive"
        if any(w in t for w in ["rest", "sleep", "wind", "dark", "reflective", "thinking", "pondering"]):
            return "reflective"
        if any(w in t for w in ["focus", "deep", "work", "project", "building", "coding", "heads-down"]):
            return "focused"
        if any(w in t for w in ["funny", "haha", "amused", "teasing", "endearing", "laugh"]):
            return "amused"
        return "neutral"

    def _backfill_mood_from_thought(self, result_message: str, state: SensedState):
        """Extract mood/energy from the agent's THOUGHT section via keyword matching."""
        thought_match = re.search(
            r'\*{0,2}THOUGHT:?\*{0,2}\s*(.+?)(?:\*{0,2}HANDOFF:?\*{0,2}|$)',
            result_message, flags=re.IGNORECASE | re.DOTALL
        )
        thought_text = thought_match.group(1).strip() if thought_match else result_message

        # Mood inference
        t = thought_text.lower()
        if any(w in t for w in ["stressed", "overwhelmed", "frustrated"]):
            state.inferred_mood = "stressed"
        elif any(w in t for w in ["tired", "exhausted", "drained"]):
            state.inferred_mood = "tired"
        elif any(w in t for w in ["focused", "deep work", "productive"]):
            state.inferred_mood = "focused"
        elif any(w in t for w in ["happy", "great", "good"]):
            state.inferred_mood = "positive"
        elif any(w in t for w in ["quiet", "calm", "relaxed"]):
            state.inferred_mood = "calm"
        else:
            state.inferred_mood = "neutral"

        # Energy inference from message velocity and activity
        if state.message_velocity and state.message_velocity > 10:
            state.inferred_energy_level = 0.8
        elif state.has_chatted_today:
            state.inferred_energy_level = 0.6
        else:
            state.inferred_energy_level = 0.4

    async def _write_journal_entry(self, db: AsyncSession, result_message: str, actions_taken: List) -> Optional[str]:
        try:
            entry_id = str(uuid.uuid4())
            now = datetime.now(self.tz)

            clean = result_message.replace("HEARTBEAT_OK", "").strip()
            thought_match = re.search(
                r'\*{0,2}THOUGHT:?\*{0,2}\s*(.+?)(?:\*{0,2}HANDOFF:?\*{0,2}|$)',
                clean, flags=re.IGNORECASE | re.DOTALL
            )
            if thought_match:
                content = thought_match.group(1).strip()
            else:
                content = re.split(r'\*{0,2}HANDOFF:?\*{0,2}', clean, flags=re.IGNORECASE)[0].strip()

            # Clean artifacts
            content = re.sub(r'\*{1,2}(.*?)\*{1,2}', r'\1', content)
            content = re.sub(r'#{1,3}\s*', '', content)
            content = re.sub(r'```.*?```', '', content, flags=re.DOTALL)
            content = re.sub(r'\{[^}]{20,}\}', '', content)
            content = re.sub(r'`[^`]+`', '', content)
            lines = content.split('\n')
            lines = [l.strip('- ').strip() for l in lines if l.strip()
                     and not re.match(r'^(Summary of actions|Actions taken|Status|Checked|Confirmed|Verified)\b', l.strip(), re.IGNORECASE)]
            content = ' '.join(lines).strip()
            content = re.sub(r'\s{2,}', ' ', content)

            if len(content) > 500:
                cut = content[:500].rfind('.')
                content = content[:cut + 1] if cut > 40 else content[:500]

            if not content or len(content) < 10:
                logger.debug("Skipping journal entry — THOUGHT was empty or too short")
                return None

            emotional_state = self._infer_emotional_state(content)

            await db.execute(text("""
                INSERT INTO sara_journal (
                    id, user_id, entry_type, content, observations, interpretation,
                    emotional_state, actions_taken, watching_for, conversation_id,
                    context, created_at
                ) VALUES (
                    :id, :user_id, 'unified', :content, :observations, NULL,
                    :emotional_state, :actions_taken, :watching_for, NULL, NULL, :created_at
                )
            """), {
                "id": entry_id, "user_id": self.user_id,
                "content": content, "emotional_state": emotional_state,
                "observations": "\n".join(self._observations) if self._observations else None,
                "actions_taken": f"{len(actions_taken)} tools, {len(self._notification_queue)} notifications",
                "watching_for": self._extract_watching_for(result_message),
                "created_at": now,
            })
            return entry_id
        except Exception as e:
            logger.error(f"Journal write failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass
            return None

    async def _save_run_log(self, db: AsyncSession, duration_ms: int,
                            context_summary: Optional[str], actions_taken: List,
                            notifications_sent: List, observations: Optional[str],
                            conversation_flags: List, handoff_note: Optional[str],
                            watching_for: Optional[str], state_snapshot: Optional[Dict],
                            journal_entry_id: Optional[str], error_message: Optional[str]) -> Optional[int]:
        try:
            run_metadata = self._context_completeness if self._context_completeness else {}
            result = await db.execute(text("""
                INSERT INTO agent_run_log
                (user_id, run_at, run_duration_ms, context_summary, actions_taken,
                 notifications_sent, observations, conversation_flags, handoff_note,
                 watching_for, david_state_snapshot, journal_entry_id, source, error_message,
                 run_metadata, run_uuid, quiet_mode_active)
                VALUES
                (:user_id, NOW(), :duration_ms, :context_summary, CAST(:actions_taken AS jsonb),
                 CAST(:notifications_sent AS jsonb), :observations, CAST(:conversation_flags AS jsonb),
                 :handoff_note, :watching_for, CAST(:state_snapshot AS jsonb), :journal_entry_id,
                 'unified_agent', :error_message, CAST(:run_metadata AS jsonb),
                 :run_uuid, :quiet_mode_active)
                RETURNING id
            """), {
                "user_id": self.user_id, "duration_ms": duration_ms,
                "context_summary": context_summary,
                "actions_taken": json.dumps(actions_taken, default=str),
                "notifications_sent": json.dumps(notifications_sent, default=str),
                "observations": observations,
                "conversation_flags": json.dumps(conversation_flags),
                "handoff_note": handoff_note, "watching_for": watching_for,
                "state_snapshot": json.dumps(state_snapshot) if state_snapshot else None,
                "journal_entry_id": journal_entry_id, "error_message": error_message,
                "run_metadata": json.dumps(run_metadata, default=str),
                "run_uuid": str(self._run_uuid) if self._run_uuid else None,
                "quiet_mode_active": self._quiet_mode_active,
            })
            row = result.fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.error(f"Run log save failed: {e}")
            return None

    # ── Parsing Helpers ──

    def _parse_tool_call(self, text_content: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        try:
            brace_positions = [i for i, c in enumerate(text_content) if c == '{']
            for start_pos in brace_positions:
                depth = 0
                for i, c in enumerate(text_content[start_pos:], start_pos):
                    if c == '{':
                        depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0:
                            candidate = text_content[start_pos:i + 1]
                            try:
                                parsed = json.loads(candidate)
                                if isinstance(parsed, dict) and "tool" in parsed:
                                    tool_name = parsed["tool"]
                                    tool_args = parsed.get("args", {})
                                    # Strip common LLM hallucination prefixes
                                    if tool_name.startswith("tool."):
                                        tool_name = tool_name[5:]
                                    elif tool_name.startswith("tool_"):
                                        tool_name = tool_name[5:]
                                    # Unwrap nested tool calls (LLM wraps in repo_browser.run_code etc.)
                                    if isinstance(tool_args, dict) and "tool" in tool_args and tool_name not in (
                                        "check_emails", "check_reminders", "check_calendar", "check_background_tasks",
                                        "check_recent_activity", "check_learning_reviews", "check_habits",
                                        "check_notes", "home_get_devices", "home_light_control",
                                        "home_switch_control", "home_lock_status", "home_climate_status",
                                        "send_notification", "get_weather", "save_observation",
                                        "flag_conversation", "query_personal_knowledge", "followup_thread",
                                    ):
                                        inner_name = tool_args["tool"]
                                        if isinstance(inner_name, str) and inner_name.startswith("tool."):
                                            inner_name = inner_name[5:]
                                        tool_name = inner_name
                                        tool_args = tool_args.get("args", {})
                                    return (tool_name, tool_args)
                            except json.JSONDecodeError:
                                pass
                            break
        except Exception:
            pass
        return None

    def _parse_api_tool_call(self, tool_calls: List[Dict]) -> Optional[Tuple[str, Dict[str, Any]]]:
        try:
            if not tool_calls:
                return None
            tc = tool_calls[0]
            func = tc.get("function", {})
            func_name = func.get("name", "")
            args_str = func.get("arguments", "{}")
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
            if func_name in ("tool.exec", "tool_exec") and "tool" in args:
                tool_name = args["tool"]
                if tool_name.startswith("tool."):
                    tool_name = tool_name[5:]
                return (tool_name, args.get("args", {}))
            if func_name and isinstance(args, dict):
                if func_name.startswith("tool."):
                    func_name = func_name[5:]
                elif func_name.startswith("tool_"):
                    func_name = func_name[5:]
                # Unwrap nested tool calls (LLM wraps in repo_browser.run_code etc.)
                known_tools = {
                    "check_emails", "check_reminders", "check_calendar", "check_background_tasks",
                    "check_recent_activity", "check_learning_reviews", "check_habits",
                    "check_notes", "home_get_devices", "home_light_control",
                    "home_switch_control", "home_lock_status", "home_climate_status",
                    "send_notification", "get_weather", "save_observation",
                    "flag_conversation", "query_personal_knowledge", "followup_thread",
                }
                if "tool" in args and func_name not in known_tools:
                    inner_name = args["tool"]
                    if isinstance(inner_name, str):
                        if inner_name.startswith("tool."):
                            inner_name = inner_name[5:]
                        func_name = inner_name
                        args = args.get("args", {})
                return (func_name, args)
            return None
        except Exception:
            return None

    def _extract_handoff_note(self, text_content: str) -> Optional[str]:
        idx = text_content.upper().find("HANDOFF:")
        if idx >= 0:
            return text_content[idx + len("HANDOFF:"):].strip()[:500]
        return None

    def _extract_watching_for(self, text_content: str) -> Optional[str]:
        indicators = ['watching for', 'keeping an eye on', 'will check', 'monitoring']
        for indicator in indicators:
            if indicator in text_content.lower():
                for sentence in text_content.split('.'):
                    if indicator in sentence.lower():
                        return sentence.strip()[:300]
        return None

    def _summarize_context(self, state: SensedState, context: Dict) -> str:
        parts = []
        if state.inferred_mood:
            parts.append(f"mood={state.inferred_mood}")
        if state.activity_state:
            parts.append(f"activity={state.activity_state}")
        cal = context.get("calendar", [])
        if cal:
            parts.append(f"{len(cal)} events")
        hours = context.get("hours_since_last_chat")
        if hours is not None:
            parts.append(f"last_chat={hours}h")
        return "; ".join(parts) if parts else "minimal context"


# ─── Module-level entry point ────────────────────────────────────

async def run_unified_agent(db: AsyncSession, user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """Entry point for the Celery task."""
    agent = UnifiedAgent(user_id)
    return await agent.run(db)
