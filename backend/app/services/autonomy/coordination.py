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
from enum import Enum
from dataclasses import dataclass

import redis.asyncio as redis

logger = logging.getLogger(__name__)


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
    - Adaptive scheduling based on user state and karma
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
        "karma-alerts": 75,
        "proactive-check": 50,
        "reflection-cycle": 45,
        "morning-anticipation": 40,
        "evening-anticipation": 40,
        "idle-processing": 20,
        "weekly-digest": 10,
    }

    def __init__(self, redis_url: str = "redis://redis:6379/0"):
        self.redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
        self._mode = SystemMode.NORMAL

    async def _get_redis(self) -> redis.Redis:
        """Get Redis connection."""
        if self._redis is None:
            self._redis = redis.from_url(self.redis_url)
        return self._redis

    async def acquire_exclusive(self, worker_name: str, group: str) -> bool:
        """
        Try to acquire exclusive access for a worker group.

        Returns True if lock acquired, False if another worker holds it.
        """
        r = await self._get_redis()
        lock_key = f"worker_lock:{group}"

        # Try to acquire lock with NX (only if not exists)
        acquired = await r.set(lock_key, worker_name, nx=True, ex=3600)

        if acquired:
            logger.debug(f"Worker {worker_name} acquired lock for {group}")
            return True

        current_holder = await r.get(lock_key)
        logger.debug(f"Worker {worker_name} blocked by {current_holder} for {group}")
        return False

    async def release_exclusive(self, group: str) -> None:
        """Release exclusive lock for a group."""
        r = await self._get_redis()
        lock_key = f"worker_lock:{group}"
        await r.delete(lock_key)
        logger.debug(f"Released lock for {group}")

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
        karma_score: Optional[float] = None,
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

        # Adjust for karma (for proactive workers)
        if karma_score is not None and "proactive" in worker_name:
            if karma_score < 30:
                multiplier *= 1.5  # Be more conservative with low karma
            elif karma_score > 70:
                multiplier *= 0.75  # Can be more active with high karma

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
            "timestamp": datetime.utcnow().isoformat(),
        }


# Singleton instance
_coordinator: Optional[WorkerCoordinator] = None


def get_coordinator(redis_url: str = "redis://redis:6379/0") -> WorkerCoordinator:
    """Get or create WorkerCoordinator instance."""
    global _coordinator
    if _coordinator is None:
        _coordinator = WorkerCoordinator(redis_url)
    return _coordinator
