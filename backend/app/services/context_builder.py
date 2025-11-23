"""
Context Packet Standardization
Unified context building for LLM requests
"""
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
import json
import logging

logger = logging.getLogger(__name__)


class UserState(BaseModel):
    """User's current state"""
    active_goals: List[Dict[str, Any]] = []
    current_mode: Optional[str] = None  # work, fitness, personal, learning
    preferences: Dict[str, Any] = {}
    timezone: str = "America/New_York"
    focus_mode: bool = False


class MemoryContext(BaseModel):
    """Relevant memory context"""
    episodes: List[Dict[str, Any]] = []
    notes: List[Dict[str, Any]] = []
    documents: List[Dict[str, Any]] = []
    total_retrieved: int = 0
    relevance_threshold: float = 0.7


class RecentAction(BaseModel):
    """Recent user action"""
    action_type: str  # workout_logged, food_logged, note_created, etc.
    timestamp: datetime
    summary: str
    data: Dict[str, Any] = {}


class EphemeralContext(BaseModel):
    """Temporary, real-time context"""
    active_timers: List[Dict[str, Any]] = []
    upcoming_reminders: List[Dict[str, Any]] = []
    todays_schedule: List[Dict[str, Any]] = []
    current_weather: Optional[Dict[str, Any]] = None
    time_of_day: str  # morning, afternoon, evening, night


class ContextPacket(BaseModel):
    """Standardized context packet for LLM"""
    user_id: str
    user_state: UserState
    memory_context: MemoryContext
    recent_actions: List[RecentAction]
    ephemeral_context: EphemeralContext
    tools_available: List[str] = []
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    cache_key: Optional[str] = None

    def to_llm_context(self) -> str:
        """Convert to natural language context for LLM"""
        parts = []

        # User state
        if self.user_state.current_mode:
            parts.append(f"Current mode: {self.user_state.current_mode}")

        if self.user_state.active_goals:
            parts.append(f"Active goals: {len(self.user_state.active_goals)}")
            for goal in self.user_state.active_goals[:3]:  # Top 3
                parts.append(f"  - {goal.get('title')} ({goal.get('progress', 0)}% complete)")

        # Ephemeral context
        parts.append(f"\nTime of day: {self.ephemeral_context.time_of_day}")

        if self.ephemeral_context.active_timers:
            parts.append(f"Active timers: {len(self.ephemeral_context.active_timers)}")
            for timer in self.ephemeral_context.active_timers:
                parts.append(f"  - {timer.get('title')}: {timer.get('remaining')} remaining")

        if self.ephemeral_context.upcoming_reminders:
            parts.append(f"Upcoming reminders: {len(self.ephemeral_context.upcoming_reminders)}")
            for reminder in self.ephemeral_context.upcoming_reminders[:3]:
                parts.append(f"  - {reminder.get('content')} at {reminder.get('due_at')}")

        if self.ephemeral_context.todays_schedule:
            parts.append(f"Today's schedule: {len(self.ephemeral_context.todays_schedule)} events")

        # Recent actions
        if self.recent_actions:
            parts.append(f"\nRecent activity (last 10 actions):")
            for action in self.recent_actions[:10]:
                parts.append(f"  - {action.summary}")

        # Memory context
        if self.memory_context.episodes:
            parts.append(f"\nRelevant memories: {len(self.memory_context.episodes)}")

        if self.memory_context.notes:
            parts.append(f"Relevant notes: {len(self.memory_context.notes)}")

        return "\n".join(parts)


class ContextBuilder:
    """Builds standardized context packets"""

    def __init__(self, db: Session, redis_client=None):
        self.db = db
        self.redis_client = redis_client
        self.cache_ttl = 300  # 5 minutes

    async def build_context(
        self,
        user_id: str,
        query: Optional[str] = None,
        include_memory: bool = True,
        include_recent_actions: bool = True,
        include_ephemeral: bool = True
    ) -> ContextPacket:
        """
        Build a complete context packet

        Args:
            user_id: User ID
            query: Optional query for memory retrieval
            include_memory: Include memory context
            include_recent_actions: Include recent actions
            include_ephemeral: Include ephemeral context

        Returns:
            ContextPacket
        """
        # Check cache first
        cache_key = f"context:{user_id}:{include_memory}:{include_recent_actions}:{include_ephemeral}"

        if self.redis_client:
            try:
                cached = await self.redis_client.get(cache_key)
                if cached:
                    logger.debug(f"✅ Context cache hit for user {user_id}")
                    return ContextPacket.parse_raw(cached)
            except Exception as e:
                logger.warning(f"Cache retrieval failed: {e}")

        # Build context components
        user_state = await self._build_user_state(user_id)
        memory_context = await self._build_memory_context(user_id, query) if include_memory else MemoryContext()
        recent_actions = await self._get_recent_actions(user_id) if include_recent_actions else []
        ephemeral_context = await self._build_ephemeral_context(user_id) if include_ephemeral else EphemeralContext()
        tools_available = await self._get_available_tools(user_id)

        # Create packet
        packet = ContextPacket(
            user_id=user_id,
            user_state=user_state,
            memory_context=memory_context,
            recent_actions=recent_actions,
            ephemeral_context=ephemeral_context,
            tools_available=tools_available,
            cache_key=cache_key
        )

        # Cache it
        if self.redis_client:
            try:
                await self.redis_client.setex(
                    cache_key,
                    self.cache_ttl,
                    packet.json()
                )
                logger.debug(f"📦 Cached context for user {user_id}")
            except Exception as e:
                logger.warning(f"Cache storage failed: {e}")

        return packet

    async def _build_user_state(self, user_id: str) -> UserState:
        """Build user state from user_life_context table"""
        try:
            # Query user_life_context (will be created in task 1.4)
            # For now, return default state
            return UserState(
                active_goals=[],
                current_mode="personal",
                preferences={},
                timezone="America/New_York",
                focus_mode=False
            )
        except Exception as e:
            logger.error(f"Error building user state: {e}")
            return UserState()

    async def _build_memory_context(self, user_id: str, query: Optional[str] = None) -> MemoryContext:
        """Build memory context with relevant episodes and notes"""
        try:
            episodes = []
            notes = []

            # Query episodes (simplified - will be enhanced with HYDRA in Phase 2)
            if query:
                # Get relevant episodes
                episode_query = text("""
                    SELECT id, content, importance, created_at
                    FROM episodes
                    WHERE user_id = :user_id
                    ORDER BY importance DESC, created_at DESC
                    LIMIT 5
                """)
                result = self.db.execute(episode_query, {"user_id": user_id})
                episodes = [
                    {
                        "id": row.id,
                        "content": row.content[:200],  # Truncate
                        "importance": row.importance,
                        "created_at": row.created_at.isoformat() if row.created_at else None
                    }
                    for row in result.fetchall()
                ]

                # Get relevant notes
                note_query = text("""
                    SELECT id, title, content, created_at
                    FROM notes
                    WHERE user_id = :user_id
                    ORDER BY created_at DESC
                    LIMIT 5
                """)
                result = self.db.execute(note_query, {"user_id": user_id})
                notes = [
                    {
                        "id": row.id,
                        "title": row.title,
                        "content": row.content[:200],  # Truncate
                        "created_at": row.created_at.isoformat() if row.created_at else None
                    }
                    for row in result.fetchall()
                ]

            return MemoryContext(
                episodes=episodes,
                notes=notes,
                documents=[],
                total_retrieved=len(episodes) + len(notes),
                relevance_threshold=0.7
            )

        except Exception as e:
            logger.error(f"Error building memory context: {e}")
            return MemoryContext()

    async def _get_recent_actions(self, user_id: str, limit: int = 10) -> List[RecentAction]:
        """Get recent user actions from event log"""
        try:
            # Query event_log (created in task 1.2)
            query = text("""
                SELECT event_type, payload, timestamp
                FROM event_log
                WHERE user_id = :user_id
                ORDER BY timestamp DESC
                LIMIT :limit
            """)

            result = self.db.execute(query, {"user_id": user_id, "limit": limit})

            actions = []
            for row in result.fetchall():
                # Generate human-readable summary
                summary = self._action_to_summary(row.event_type, row.payload)

                actions.append(RecentAction(
                    action_type=row.event_type,
                    timestamp=row.timestamp,
                    summary=summary,
                    data=row.payload
                ))

            return actions

        except Exception as e:
            logger.error(f"Error getting recent actions: {e}")
            return []

    def _action_to_summary(self, event_type: str, payload: Dict[str, Any]) -> str:
        """Convert action to human-readable summary"""
        summaries = {
            "workout.logged": f"Logged workout: {payload.get('exercise', 'exercise')}",
            "food.logged": f"Logged meal: {payload.get('food_description', 'meal')}",
            "note.created": f"Created note: {payload.get('title', 'untitled')}",
            "timer.started": f"Started timer: {payload.get('title', 'timer')}",
            "reminder.created": f"Created reminder: {payload.get('content', 'reminder')}",
            "goal.created": f"Created goal: {payload.get('title', 'goal')}",
        }

        return summaries.get(event_type, f"Action: {event_type}")

    async def _build_ephemeral_context(self, user_id: str) -> EphemeralContext:
        """Build ephemeral (real-time) context"""
        try:
            # Get active timers
            active_timers = await self._get_active_timers(user_id)

            # Get upcoming reminders (next 24 hours)
            upcoming_reminders = await self._get_upcoming_reminders(user_id)

            # Get today's schedule
            todays_schedule = await self._get_todays_schedule(user_id)

            # Determine time of day
            time_of_day = self._get_time_of_day()

            return EphemeralContext(
                active_timers=active_timers,
                upcoming_reminders=upcoming_reminders,
                todays_schedule=todays_schedule,
                time_of_day=time_of_day
            )

        except Exception as e:
            logger.error(f"Error building ephemeral context: {e}")
            return EphemeralContext(time_of_day="unknown")

    async def _get_active_timers(self, user_id: str) -> List[Dict[str, Any]]:
        """Get active timers"""
        try:
            query = text("""
                SELECT id, title, duration, started_at
                FROM timers
                WHERE user_id = :user_id
                AND completed = FALSE
                ORDER BY started_at DESC
                LIMIT 5
            """)

            result = self.db.execute(query, {"user_id": user_id})

            timers = []
            for row in result.fetchall():
                # Calculate remaining time
                elapsed = (datetime.utcnow() - row.started_at).total_seconds()
                remaining = max(0, row.duration - elapsed)

                timers.append({
                    "id": row.id,
                    "title": row.title,
                    "duration": row.duration,
                    "remaining": f"{int(remaining // 60)}min"
                })

            return timers

        except Exception as e:
            logger.error(f"Error getting timers: {e}")
            return []

    async def _get_upcoming_reminders(self, user_id: str) -> List[Dict[str, Any]]:
        """Get upcoming reminders (next 24 hours)"""
        try:
            now = datetime.utcnow()
            tomorrow = now + timedelta(days=1)

            query = text("""
                SELECT id, content, due_at
                FROM reminders
                WHERE user_id = :user_id
                AND completed = FALSE
                AND due_at > :now
                AND due_at < :tomorrow
                ORDER BY due_at
                LIMIT 5
            """)

            result = self.db.execute(query, {
                "user_id": user_id,
                "now": now,
                "tomorrow": tomorrow
            })

            reminders = []
            for row in result.fetchall():
                reminders.append({
                    "id": row.id,
                    "content": row.content,
                    "due_at": row.due_at.isoformat() if row.due_at else None
                })

            return reminders

        except Exception as e:
            logger.error(f"Error getting reminders: {e}")
            return []

    async def _get_todays_schedule(self, user_id: str) -> List[Dict[str, Any]]:
        """Get today's calendar events"""
        try:
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)

            query = text("""
                SELECT id, title, starts_at, ends_at
                FROM calendar_events
                WHERE user_id = :user_id
                AND starts_at >= :today_start
                AND starts_at < :today_end
                ORDER BY starts_at
                LIMIT 10
            """)

            result = self.db.execute(query, {
                "user_id": user_id,
                "today_start": today_start,
                "today_end": today_end
            })

            events = []
            for row in result.fetchall():
                events.append({
                    "id": row.id,
                    "title": row.title,
                    "starts_at": row.starts_at.isoformat() if row.starts_at else None,
                    "ends_at": row.ends_at.isoformat() if row.ends_at else None
                })

            return events

        except Exception as e:
            logger.error(f"Error getting schedule: {e}")
            return []

    def _get_time_of_day(self) -> str:
        """Determine time of day"""
        hour = datetime.now().hour

        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 21:
            return "evening"
        else:
            return "night"

    async def _get_available_tools(self, user_id: str) -> List[str]:
        """Get list of available tool names"""
        # For now, return all tools
        # In the future, this could be filtered based on user permissions
        from app.tools.registry_v2 import registry_v2

        return list(registry_v2.tools.keys())

    async def invalidate_cache(self, user_id: str):
        """Invalidate cached context for a user"""
        if self.redis_client:
            try:
                # Delete all context cache keys for this user
                pattern = f"context:{user_id}:*"
                keys = await self.redis_client.keys(pattern)
                if keys:
                    await self.redis_client.delete(*keys)
                    logger.debug(f"🗑️  Invalidated context cache for user {user_id}")
            except Exception as e:
                logger.warning(f"Cache invalidation failed: {e}")


# Helper function to get context builder
def get_context_builder(db: Session, redis_client=None) -> ContextBuilder:
    """Get a context builder instance"""
    return ContextBuilder(db, redis_client)
