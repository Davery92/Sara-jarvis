"""
Working Memory Service for Sara's cognitive architecture.

Working memory is Sara's conscious scratchpad - what she's actively aware of.
This includes:
- Current consolidated context (from consolidation agent)
- Active conversation threads
- Pending actions she's tracking
- Inferred user state
- System state

Working memory is ephemeral - it resets/decays and is size-limited to force
prioritization.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional

from app.core.timezone import now as local_now
from dataclasses import dataclass, field, asdict
from enum import Enum

import redis

logger = logging.getLogger(__name__)


class UserAvailability(str, Enum):
    """User availability states."""
    ACTIVE = "active"
    AVAILABLE = "available"
    BUSY = "busy"
    DND = "dnd"
    AWAY = "away"
    SLEEPING = "sleeping"
    UNKNOWN = "unknown"


class ActionType(str, Enum):
    """Types of pending actions."""
    NOTIFY = "notify"
    REMIND = "remind"
    EXECUTE = "execute"
    ASK = "ask"
    OBSERVE = "observe"


class ThreadStatus(str, Enum):
    """Conversation thread status."""
    ACTIVE = "active"
    WAITING = "waiting"
    RESOLVED = "resolved"


@dataclass
class ContextSegment:
    """A segment of consolidated context."""
    type: str
    timestamp: str
    content: Any
    relevance_score: float
    source_raw_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActiveThread:
    """An active conversation thread."""
    thread_id: str
    topic: str
    participants: List[str]
    last_updated: str
    status: ThreadStatus
    summary: str


@dataclass
class PendingAction:
    """An action Sara is considering or tracking."""
    action_id: str
    type: ActionType
    priority: float
    context: str
    created_at: str
    deadline: Optional[str] = None


@dataclass
class UserState:
    """Inferred state about the user."""
    inferred_activity: str
    availability: UserAvailability
    location: str
    last_interaction: Optional[str]
    mood_signals: List[str] = field(default_factory=list)
    confidence: float = 0.5
    inferred_at: str = ""


@dataclass
class SystemState:
    """Current system state."""
    last_consolidation: Optional[str]
    buffer_health: str
    overall_health: str
    active_workers: List[str] = field(default_factory=list)
    updated_at: str = ""


@dataclass
class WorkingMemorySnapshot:
    """Complete snapshot of working memory."""
    current_context: List[ContextSegment]
    active_threads: List[ActiveThread]
    pending_actions: List[PendingAction]
    user_state: UserState
    system_state: SystemState
    snapshot_at: str


class WorkingMemoryService:
    """
    Service for managing Sara's working memory.

    Working memory provides Sara with:
    - Awareness of recent context (last 60 seconds of consolidated data)
    - Tracking of active conversations
    - List of pending actions she's considering
    - Understanding of user's current state
    - Awareness of system health

    All data is stored in Redis with TTLs to ensure automatic cleanup.
    """

    # Redis key prefixes
    PREFIX = "working_memory:"

    # Capacity limits
    LIMITS = {
        "context_segments": 50,
        "active_threads": 10,
        "pending_actions": 20,
    }

    # TTLs in seconds
    TTLS = {
        "context": 3600,       # 1 hour
        "threads": 86400,      # 24 hours
        "actions": 86400,      # 24 hours
        "user_state": 3600,    # 1 hour
        "system_state": 600,   # 10 minutes
    }

    def __init__(self, redis_url: Optional[str] = None):
        """Initialize working memory service."""
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://redis:6379/0")
        self._redis: Optional[redis.Redis] = None

    @property
    def redis(self) -> redis.Redis:
        """Lazy initialization of Redis client."""
        if self._redis is None:
            from app.core.redis import get_redis_sync_bytes
            self._redis = get_redis_sync_bytes()
        return self._redis

    def _key(self, user_id: str, component: str) -> str:
        """Generate Redis key for a working memory component."""
        return f"{self.PREFIX}{user_id}:{component}"

    # ============================================
    # Context Management
    # ============================================

    async def get_current_context(self, user_id: str) -> List[ContextSegment]:
        """Get the current consolidated context segments."""
        key = self._key(user_id, "context")

        try:
            data = self.redis.get(key)
            if not data:
                return []

            context = json.loads(data)
            segments = context.get("segments", [])

            return [
                ContextSegment(**seg) for seg in segments
            ]

        except Exception as e:
            logger.error(f"Error getting context for {user_id}: {e}")
            return []

    async def update_context(
        self,
        user_id: str,
        segments: List[ContextSegment]
    ) -> bool:
        """
        Update the current context with new segments.

        New segments are merged with existing, applying capacity limits.
        """
        key = self._key(user_id, "context")

        try:
            # Get existing context
            existing = await self.get_current_context(user_id)

            # Merge with new segments
            all_segments = existing + segments

            # Sort by relevance and apply limit
            sorted_segments = sorted(
                all_segments,
                key=lambda s: s.relevance_score,
                reverse=True
            )[:self.LIMITS["context_segments"]]

            # Store
            context_data = {
                "segments": [asdict(s) for s in sorted_segments],
                "updated_at": local_now().isoformat()
            }

            self.redis.setex(
                key,
                self.TTLS["context"],
                json.dumps(context_data)
            )

            return True

        except Exception as e:
            logger.error(f"Error updating context for {user_id}: {e}")
            return False

    async def clear_context(self, user_id: str) -> bool:
        """Clear all context segments."""
        key = self._key(user_id, "context")
        try:
            self.redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Error clearing context for {user_id}: {e}")
            return False

    # ============================================
    # Thread Management
    # ============================================

    async def get_active_threads(self, user_id: str) -> List[ActiveThread]:
        """Get all active conversation threads."""
        key = self._key(user_id, "threads")

        try:
            # Threads stored as sorted set (score = last_updated timestamp)
            thread_ids = self.redis.zrevrange(key, 0, -1)

            threads = []
            for thread_id in thread_ids:
                tid = thread_id.decode() if isinstance(thread_id, bytes) else thread_id
                thread_data = self.redis.hgetall(f"{key}:{tid}")

                if thread_data:
                    decoded = {
                        k.decode() if isinstance(k, bytes) else k:
                        v.decode() if isinstance(v, bytes) else v
                        for k, v in thread_data.items()
                    }

                    # Parse participants
                    participants = json.loads(decoded.get("participants", "[]"))

                    threads.append(ActiveThread(
                        thread_id=tid,
                        topic=decoded.get("topic", ""),
                        participants=participants,
                        last_updated=decoded.get("last_updated", ""),
                        status=ThreadStatus(decoded.get("status", "active")),
                        summary=decoded.get("summary", "")
                    ))

            return threads

        except Exception as e:
            logger.error(f"Error getting threads for {user_id}: {e}")
            return []

    async def add_thread(
        self,
        user_id: str,
        thread: ActiveThread
    ) -> bool:
        """Add or update an active thread."""
        key = self._key(user_id, "threads")

        try:
            # Check capacity
            count = self.redis.zcard(key)
            if count >= self.LIMITS["active_threads"]:
                # Remove oldest thread
                self.redis.zpopmin(key, 1)

            # Add to sorted set
            score = datetime.fromisoformat(thread.last_updated).timestamp()
            self.redis.zadd(key, {thread.thread_id: score})

            # Store thread data
            thread_key = f"{key}:{thread.thread_id}"
            self.redis.hset(thread_key, mapping={
                "topic": thread.topic,
                "participants": json.dumps(thread.participants),
                "last_updated": thread.last_updated,
                "status": thread.status.value,
                "summary": thread.summary
            })

            # Set TTL
            self.redis.expire(key, self.TTLS["threads"])
            self.redis.expire(thread_key, self.TTLS["threads"])

            return True

        except Exception as e:
            logger.error(f"Error adding thread for {user_id}: {e}")
            return False

    async def update_thread_status(
        self,
        user_id: str,
        thread_id: str,
        status: ThreadStatus
    ) -> bool:
        """Update the status of a thread."""
        key = f"{self._key(user_id, 'threads')}:{thread_id}"

        try:
            self.redis.hset(key, "status", status.value)
            self.redis.hset(key, "last_updated", local_now().isoformat())
            return True
        except Exception as e:
            logger.error(f"Error updating thread status: {e}")
            return False

    # ============================================
    # Pending Actions Management
    # ============================================

    async def get_pending_actions(self, user_id: str) -> List[PendingAction]:
        """Get all pending actions."""
        key = self._key(user_id, "actions")

        try:
            # Actions stored as sorted set (score = priority)
            action_ids = self.redis.zrevrange(key, 0, -1)

            actions = []
            for action_id in action_ids:
                aid = action_id.decode() if isinstance(action_id, bytes) else action_id
                action_data = self.redis.hgetall(f"{key}:{aid}")

                if action_data:
                    decoded = {
                        k.decode() if isinstance(k, bytes) else k:
                        v.decode() if isinstance(v, bytes) else v
                        for k, v in action_data.items()
                    }

                    actions.append(PendingAction(
                        action_id=aid,
                        type=ActionType(decoded.get("type", "observe")),
                        priority=float(decoded.get("priority", 0.5)),
                        context=decoded.get("context", ""),
                        created_at=decoded.get("created_at", ""),
                        deadline=decoded.get("deadline")
                    ))

            return actions

        except Exception as e:
            logger.error(f"Error getting actions for {user_id}: {e}")
            return []

    async def add_pending_action(
        self,
        user_id: str,
        action: PendingAction
    ) -> bool:
        """Add a pending action."""
        key = self._key(user_id, "actions")

        try:
            # Check capacity
            count = self.redis.zcard(key)
            if count >= self.LIMITS["pending_actions"]:
                # Remove lowest priority action
                self.redis.zpopmin(key, 1)

            # Add to sorted set (score = priority)
            self.redis.zadd(key, {action.action_id: action.priority})

            # Store action data
            action_key = f"{key}:{action.action_id}"
            mapping = {
                "type": action.type.value,
                "priority": str(action.priority),
                "context": action.context,
                "created_at": action.created_at,
            }
            if action.deadline:
                mapping["deadline"] = action.deadline

            self.redis.hset(action_key, mapping=mapping)

            # Set TTL
            self.redis.expire(key, self.TTLS["actions"])
            self.redis.expire(action_key, self.TTLS["actions"])

            return True

        except Exception as e:
            logger.error(f"Error adding action for {user_id}: {e}")
            return False

    async def remove_pending_action(
        self,
        user_id: str,
        action_id: str
    ) -> bool:
        """Remove a pending action."""
        key = self._key(user_id, "actions")

        try:
            self.redis.zrem(key, action_id)
            self.redis.delete(f"{key}:{action_id}")
            return True
        except Exception as e:
            logger.error(f"Error removing action: {e}")
            return False

    # ============================================
    # User State Management
    # ============================================

    async def get_user_state(self, user_id: str) -> UserState:
        """Get the inferred user state."""
        key = self._key(user_id, "user_state")

        try:
            data = self.redis.get(key)
            if not data:
                return UserState(
                    inferred_activity="unknown",
                    availability=UserAvailability.UNKNOWN,
                    location="unknown",
                    last_interaction=None,
                    inferred_at=datetime.now(ZoneInfo("America/New_York")).isoformat()
                )

            state_data = json.loads(data)
            return UserState(
                inferred_activity=state_data.get("inferred_activity", "unknown"),
                availability=UserAvailability(state_data.get("availability", "unknown")),
                location=state_data.get("location", "unknown"),
                last_interaction=state_data.get("last_interaction"),
                mood_signals=state_data.get("mood_signals", []),
                confidence=state_data.get("confidence", 0.5),
                inferred_at=state_data.get("inferred_at", "")
            )

        except Exception as e:
            logger.error(f"Error getting user state for {user_id}: {e}")
            return UserState(
                inferred_activity="unknown",
                availability=UserAvailability.UNKNOWN,
                location="unknown",
                last_interaction=None,
                inferred_at=local_now().isoformat()
            )

    async def update_user_state(
        self,
        user_id: str,
        state: UserState
    ) -> bool:
        """Update the inferred user state."""
        key = self._key(user_id, "user_state")

        try:
            state_dict = asdict(state)
            state_dict["availability"] = state.availability.value

            self.redis.setex(
                key,
                self.TTLS["user_state"],
                json.dumps(state_dict)
            )
            return True

        except Exception as e:
            logger.error(f"Error updating user state for {user_id}: {e}")
            return False

    async def record_interaction(self, user_id: str) -> bool:
        """Record that an interaction occurred (updates last_interaction)."""
        key = f"user:{user_id}:last_interaction"

        try:
            self.redis.set(key, local_now().isoformat())
            return True
        except Exception as e:
            logger.error(f"Error recording interaction: {e}")
            return False

    # ============================================
    # System State Management
    # ============================================

    async def get_system_state(self, user_id: str) -> SystemState:
        """Get the current system state."""
        key = self._key(user_id, "system_state")

        try:
            data = self.redis.get(key)
            if not data:
                return SystemState(
                    last_consolidation=None,
                    buffer_health="unknown",
                    overall_health="unknown",
                    updated_at=local_now().isoformat()
                )

            state_data = json.loads(data)
            return SystemState(
                last_consolidation=state_data.get("last_consolidation"),
                buffer_health=state_data.get("buffer_health", "unknown"),
                overall_health=state_data.get("overall_health", "unknown"),
                active_workers=state_data.get("active_workers", []),
                updated_at=state_data.get("updated_at", "")
            )

        except Exception as e:
            logger.error(f"Error getting system state: {e}")
            return SystemState(
                last_consolidation=None,
                buffer_health="unknown",
                overall_health="unknown",
                updated_at=local_now().isoformat()
            )

    async def update_system_state(
        self,
        user_id: str,
        state: SystemState
    ) -> bool:
        """Update the system state."""
        key = self._key(user_id, "system_state")

        try:
            self.redis.setex(
                key,
                self.TTLS["system_state"],
                json.dumps(asdict(state))
            )
            return True

        except Exception as e:
            logger.error(f"Error updating system state: {e}")
            return False

    # ============================================
    # Snapshot (Complete Working Memory)
    # ============================================

    async def get_snapshot(self, user_id: str) -> WorkingMemorySnapshot:
        """
        Get a complete snapshot of working memory.

        This is what gets injected into Sara's context.
        """
        context = await self.get_current_context(user_id)
        threads = await self.get_active_threads(user_id)
        actions = await self.get_pending_actions(user_id)
        user_state = await self.get_user_state(user_id)
        system_state = await self.get_system_state(user_id)

        return WorkingMemorySnapshot(
            current_context=context,
            active_threads=threads,
            pending_actions=actions,
            user_state=user_state,
            system_state=system_state,
            snapshot_at=local_now().isoformat()
        )

    def format_for_prompt(self, snapshot: WorkingMemorySnapshot) -> str:
        """
        Format working memory snapshot for injection into Sara's prompt.

        Returns XML-formatted string for prompt injection.
        """
        lines = ["<working_memory>"]

        # Current context
        if snapshot.current_context:
            lines.append("  <current_context>")
            for seg in snapshot.current_context[:10]:  # Limit for prompt size
                lines.append(f"    <segment type=\"{seg.type}\" relevance=\"{seg.relevance_score:.2f}\">")
                content_str = str(seg.content)[:200]  # Truncate long content
                lines.append(f"      {content_str}")
                lines.append("    </segment>")
            lines.append("  </current_context>")

        # Active threads
        if snapshot.active_threads:
            lines.append("  <active_threads>")
            for thread in snapshot.active_threads:
                lines.append(f"    <thread id=\"{thread.thread_id}\" status=\"{thread.status.value}\">")
                lines.append(f"      <topic>{thread.topic}</topic>")
                lines.append(f"      <summary>{thread.summary}</summary>")
                lines.append("    </thread>")
            lines.append("  </active_threads>")

        # Pending actions
        if snapshot.pending_actions:
            lines.append("  <pending_actions>")
            for action in snapshot.pending_actions:
                lines.append(f"    <action id=\"{action.action_id}\" type=\"{action.type.value}\" priority=\"{action.priority:.2f}\">")
                lines.append(f"      {action.context}")
                lines.append("    </action>")
            lines.append("  </pending_actions>")

        # User state
        lines.append("  <user_state>")
        lines.append(f"    <activity>{snapshot.user_state.inferred_activity}</activity>")
        lines.append(f"    <availability>{snapshot.user_state.availability.value}</availability>")
        lines.append(f"    <location>{snapshot.user_state.location}</location>")
        if snapshot.user_state.last_interaction:
            lines.append(f"    <last_interaction>{snapshot.user_state.last_interaction}</last_interaction>")
        lines.append("  </user_state>")

        # System state (brief)
        lines.append("  <system_state>")
        lines.append(f"    <health>{snapshot.system_state.overall_health}</health>")
        lines.append(f"    <buffer_health>{snapshot.system_state.buffer_health}</buffer_health>")
        lines.append("  </system_state>")

        lines.append("</working_memory>")

        return "\n".join(lines)


# Singleton instance
_working_memory_service: Optional[WorkingMemoryService] = None


def get_working_memory_service() -> WorkingMemoryService:
    """Get the singleton WorkingMemoryService instance."""
    global _working_memory_service
    if _working_memory_service is None:
        _working_memory_service = WorkingMemoryService()
    return _working_memory_service
