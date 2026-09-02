"""
Single-flight lock for the research LLM lane.

`--concurrency=1` on the david_priority worker is the primary serialization,
but `run_research_plan`'s default queue is `cognitive` (concurrency 4) and the
autonomous path uses it, so a misrouted or second worker could still put two
research agents on the lane at once — which is exactly what OOM'd the Mac
Studio into 507s on 2026-09-01. This is the belt to that pair of braces.

The lock is per-user and heartbeated: a research run legitimately spans hours,
so a fixed TTL would either expire mid-run (defeating the lock) or outlive a
crashed worker by hours (wedging the lane). A short TTL refreshed by a
background task gives both — a killed worker's lock ages out in ~5 minutes.
"""

import asyncio
import logging
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

LANE_LOCK_TTL = 300          # seconds; a dead worker's lock clears in ~5 min
LANE_LOCK_HEARTBEAT = 60     # refresh interval, comfortably under the TTL


def lane_lock_key(user_id: str) -> str:
    return f"research_executor_lock:{user_id}"


class LaneLock:
    """Best-effort exclusive claim on a user's research lane.

    Redis being unavailable must never stop research — in that case `acquire`
    reports success and the worker concurrency setting is the only guard, which
    is where we were before this existed.
    """

    def __init__(self, user_id: str, plan_id: str):
        self.user_id = user_id
        self.plan_id = plan_id
        self.token = f"{plan_id}:{uuid.uuid4().hex[:8]}"
        self._redis = None
        self._heartbeat: Optional[asyncio.Task] = None
        self.held = False

    async def acquire(self) -> bool:
        """True if we own the lane (or Redis is down and we're proceeding blind)."""
        try:
            from app.core.redis import get_redis
            self._redis = await get_redis()
            got = await self._redis.set(
                lane_lock_key(self.user_id), self.token, nx=True, ex=LANE_LOCK_TTL
            )
        except Exception as e:
            logger.warning("Research lane lock unavailable (%s) — proceeding without it", e)
            self._redis = None
            self.held = False
            return True

        if not got:
            try:
                holder = await self._redis.get(lane_lock_key(self.user_id))
            except Exception:
                holder = None
            logger.info(
                "Research lane already held by %s — plan %s will wait",
                holder, self.plan_id,
            )
            return False

        self.held = True
        self._heartbeat = asyncio.create_task(self._beat())
        return True

    async def _beat(self):
        while True:
            try:
                await asyncio.sleep(LANE_LOCK_HEARTBEAT)
                if self._redis is None:
                    return
                # Only extend a lock we still own — never resurrect one that
                # expired and was taken by another plan.
                current = await self._redis.get(lane_lock_key(self.user_id))
                if current != self.token:
                    logger.warning(
                        "Research lane lock for %s lost (held by %s)", self.user_id, current
                    )
                    self.held = False
                    return
                await self._redis.expire(lane_lock_key(self.user_id), LANE_LOCK_TTL)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("Research lane heartbeat failed: %s", e)

    async def release(self):
        if self._heartbeat:
            self._heartbeat.cancel()
            try:
                await self._heartbeat
            except (asyncio.CancelledError, Exception):
                pass
            self._heartbeat = None
        if self._redis is None or not self.held:
            return
        try:
            current = await self._redis.get(lane_lock_key(self.user_id))
            if current == self.token:
                await self._redis.delete(lane_lock_key(self.user_id))
        except Exception as e:
            logger.warning("Could not release research lane lock: %s", e)
        finally:
            self.held = False
