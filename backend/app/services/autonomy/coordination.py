"""
WorkerCoordinator - Coordinates workers to prevent conflicts.

Manages:
- Exclusive access groups (prevent simultaneous conflicting tasks)
- Resource budgets (limit LLM calls, memory usage)
- Adaptive scheduling based on context
- Graceful degradation under load
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from app.core.timezone import now as local_now
from enum import Enum
from dataclasses import dataclass

import redis.asyncio as redis

logger = logging.getLogger(__name__)

_RELEASE_IF_OWNER = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class HealthStatus(str, Enum):
    """System health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    ERROR = "error"


class SystemMode(str, Enum):
    """System operating modes."""
    NORMAL = "normal"
    DEGRADED = "degraded"
    MAINTENANCE = "maintenance"


@dataclass
class ResourceUsage:
    """Current resource usage."""
    llm_calls_minute: int
    concurrent_heavy_tasks: int
    memory_mb: int


class WorkerCoordinator:
    """
    Coordinates background workers to prevent conflicts and manage resources.

    Features:
    - Exclusive locks for conflicting task groups
    - Resource budget enforcement
    - Adaptive scheduling based on user state
    - Graceful degradation under constraints
    """

    # Workers that shouldn't run simultaneously
    EXCLUSIVE_GROUPS = {
        "reflection": ["reflection-cycle", "nightly-consolidation"],
        "heavy_llm": ["proactive-check", "morning-anticipation", "evening-anticipation", "weekly-digest"],
    }

    # Resource limits
    RESOURCE_LIMITS = {
        "llm_calls_per_minute": 10,
        "concurrent_heavy_tasks": 2,
        "memory_usage_mb": 2048,
    }

    # Base schedules (seconds between runs)
    BASE_SCHEDULES = {
        "proactive-check": 900,      # 15 minutes
        "consolidation-sweep": 60,   # 1 minute
        "context-refresh": 60,       # 1 minute
        "buffer-cleanup": 300,       # 5 minutes
    }

    # Worker priorities (higher = more essential)
    WORKER_PRIORITIES = {
        "system-heartbeat": 100,
        "context-refresh": 90,
        "consolidation-sweep": 85,
        "buffer-cleanup": 80,
        "proactive-check": 50,
        "reflection-cycle": 45,
        "morning-anticipation": 40,
        "evening-anticipation": 40,
        "idle-processing": 20,
        "weekly-digest": 10,
    }

    # Keep lock TTL short enough to self-heal after worker restarts/crashes.
    # The unified agent typically finishes within a couple of minutes.
    EXCLUSIVE_LOCK_TTL_SECONDS = 900

    def __init__(self, redis_url: str = "redis://redis:6379/0"):
        self.redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
        self._redis_loop_id: Optional[int] = None
        self._mode = SystemMode.NORMAL

    async def _get_redis(self) -> redis.Redis:
        """Get Redis connection, recreated when event loop changes."""
        import asyncio
        cur_loop = id(asyncio.get_running_loop())
        if self._redis is None or cur_loop != self._redis_loop_id:
            if self._redis is not None:
                try:
                    await self._redis.close()
                except Exception:
                    pass
            self._redis = redis.from_url(self.redis_url)
            self._redis_loop_id = cur_loop
        return self._redis

    async def acquire_exclusive(self, worker_name: str, group: str) -> bool:
        """
        Try to acquire exclusive access for a worker group.

        Returns True if lock acquired, False if another worker holds it.
        """
        r = await self._get_redis()
        lock_key = f"worker_lock:{group}"

        # Try to acquire lock with NX (only if not exists)
        acquired = await r.set(
            lock_key,
            worker_name,
            nx=True,
            ex=self.EXCLUSIVE_LOCK_TTL_SECONDS,
        )

        if acquired:
            logger.debug(f"Worker {worker_name} acquired lock for {group}")
            return True

        current_holder = await r.get(lock_key)
        logger.debug(f"Worker {worker_name} blocked by {current_holder} for {group}")
        return False

    async def release_exclusive(self, group: str, worker_name: Optional[str] = None) -> None:
        """Release exclusive lock for a group.

        If worker_name is provided, only release when that worker currently
        holds the lock.
        """
        r = await self._get_redis()
        lock_key = f"worker_lock:{group}"

        if worker_name:
            deleted = 0
            eval_error = None
            try:
                deleted = await r.eval(_RELEASE_IF_OWNER, 1, lock_key, worker_name)
            except Exception as e:
                # Compatibility fallback for Redis implementations without EVAL (e.g., some fakeredis builds).
                eval_error = e
                current_holder = await r.get(lock_key)
                if isinstance(current_holder, bytes):
                    current_holder = current_holder.decode()
                if str(current_holder) == worker_name:
                    deleted = await r.delete(lock_key)

            if eval_error is not None:
                logger.warning(
                    f"Lock release CAS fallback used for {group}; Redis EVAL unavailable: {eval_error}"
                )

            if deleted:
                logger.debug(f"Released lock for {group} (owner={worker_name})")
            else:
                current_holder = await r.get(lock_key)
                if isinstance(current_holder, bytes):
                    current_holder = current_holder.decode()
                logger.debug(
                    f"Skip releasing lock for {group}; holder={current_holder}, requested={worker_name}"
                )
            return

        logger.warning(f"Releasing lock for {group} without owner verification")
        await r.delete(lock_key)
        logger.debug(f"Released lock for {group}")

    async def refresh_exclusive(self, worker_name: str, group: str) -> bool:
        """
        Refresh lock TTL for a group if held by worker_name.

        Returns True if refreshed, False if lock is missing or owned by another worker.
        """
        r = await self._get_redis()
        lock_key = f"worker_lock:{group}"
        current_holder = await r.get(lock_key)
        if current_holder is None:
            return False
        if isinstance(current_holder, bytes):
            current_holder = current_holder.decode()
        if str(current_holder) != worker_name:
            return False

        await r.expire(lock_key, self.EXCLUSIVE_LOCK_TTL_SECONDS)
        return True

    async def get_lock_holder(self, group: str) -> Optional[str]:
        """Get the current holder of an exclusive lock group."""
        r = await self._get_redis()
        lock_key = f"worker_lock:{group}"
        holder = await r.get(lock_key)
        if holder is None:
            return None
        if isinstance(holder, bytes):
            return holder.decode()
        return str(holder)

    async def check_resource_budget(self, resource: str, amount: int) -> bool:
        """Check if resource budget allows this operation."""
        r = await self._get_redis()
        key = f"resource_usage:{resource}"

        current = await r.get(key)
        current_val = int(current) if current else 0

        limit = self.RESOURCE_LIMITS.get(resource, float('inf'))
        return current_val + amount <= limit

    async def consume_resource(self, resource: str, amount: int) -> None:
        """Record resource consumption."""
        r = await self._get_redis()
        key = f"resource_usage:{resource}"

        await r.incrby(key, amount)
        await r.expire(key, 60)  # Reset every minute

    async def get_adaptive_schedule(
        self,
        worker_name: str,
        user_availability: Optional[str] = None,
    ) -> int:
        """
        Get adaptive schedule for a worker based on context.

        Returns recommended seconds between runs.
        """
        base = self.BASE_SCHEDULES.get(worker_name, 300)

        multiplier = 1.0

        # Adjust for user availability
        if user_availability == "sleeping":
            multiplier *= 3.0  # Much less frequent when sleeping
        elif user_availability == "dnd":
            if "proactive" in worker_name:
                multiplier *= 2.0  # Less proactive during DND

        # Adjust for system load
        load = await self._get_system_load()
        if load > 0.8:
            multiplier *= 1.5

        return int(base * multiplier)

    async def _get_system_load(self) -> float:
        """Get current system load estimate (0-1)."""
        r = await self._get_redis()

        # Check LLM call rate
        llm_calls = await r.get("resource_usage:llm_calls_per_minute")
        llm_load = int(llm_calls or 0) / self.RESOURCE_LIMITS["llm_calls_per_minute"]

        # Check concurrent tasks
        heavy_tasks = await r.get("resource_usage:concurrent_heavy_tasks")
        task_load = int(heavy_tasks or 0) / self.RESOURCE_LIMITS["concurrent_heavy_tasks"]

        return max(llm_load, task_load)

    async def should_run_worker(self, worker_name: str) -> bool:
        """
        Determine if a worker should run given current constraints.

        Implements graceful degradation based on system health.
        """
        priority = self.WORKER_PRIORITIES.get(worker_name, 50)

        # Check system mode
        if self._mode == SystemMode.MAINTENANCE:
            return priority >= 100  # Only heartbeat

        if self._mode == SystemMode.DEGRADED:
            return priority >= 70  # Skip low-priority workers

        # Check resource availability
        load = await self._get_system_load()

        if load > 0.9:
            return priority >= 80  # Only essential workers
        elif load > 0.7:
            return priority >= 50  # Skip low-priority

        return True

    async def enter_degraded_mode(self, reason: str) -> None:
        """Enter degraded mode - reduce non-essential operations."""
        self._mode = SystemMode.DEGRADED
        logger.warning(f"Entering degraded mode: {reason}")

        r = await self._get_redis()
        await r.set("system_mode", "degraded", ex=3600)
        await r.set("degraded_reason", reason, ex=3600)

    async def exit_degraded_mode(self) -> None:
        """Return to normal operation."""
        self._mode = SystemMode.NORMAL
        logger.info("Exiting degraded mode")

        r = await self._get_redis()
        await r.set("system_mode", "normal")
        await r.delete("degraded_reason")

    async def get_system_status(self) -> Dict[str, Any]:
        """Get current system status for monitoring."""
        r = await self._get_redis()

        mode = await r.get("system_mode")
        degraded_reason = await r.get("degraded_reason")

        llm_usage = await r.get("resource_usage:llm_calls_per_minute")
        heavy_tasks = await r.get("resource_usage:concurrent_heavy_tasks")

        # Get active locks
        lock_keys = await r.keys("worker_lock:*")
        active_locks = {}
        for key in lock_keys:
            holder = await r.get(key)
            group = key.decode().replace("worker_lock:", "")
            active_locks[group] = holder.decode() if holder else None

        return {
            "mode": mode.decode() if mode else "normal",
            "degraded_reason": degraded_reason.decode() if degraded_reason else None,
            "resource_usage": {
                "llm_calls_per_minute": int(llm_usage or 0),
                "concurrent_heavy_tasks": int(heavy_tasks or 0),
            },
            "active_locks": active_locks,
            "timestamp": local_now().isoformat(),
        }


# Singleton instance
_coordinator: Optional[WorkerCoordinator] = None


def get_coordinator(redis_url: str = "redis://redis:6379/0") -> WorkerCoordinator:
    """Get or create WorkerCoordinator instance."""
    global _coordinator
    if _coordinator is None:
        _coordinator = WorkerCoordinator(redis_url)
    return _coordinator
