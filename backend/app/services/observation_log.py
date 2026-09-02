"""
Observation Log — salience-scored event observations in Redis.

Interesting events are logged as observations with salience scores.
When accumulated salience crosses a threshold, deliberation is triggered.
Observations are consumed after deliberation processes them.

Redis keys:
    sara:observations:{user_id}         — sorted set (score = salience)
    sara:observation_details:{user_id}  — hash (obs_id → JSON blob)

Usage:
    from app.services.observation_log import log_observation, get_pending_observations

    await log_observation(user_id, "Door opened at 2 AM", salience=0.8, source="security", category="security")
    pending = await get_pending_observations(user_id, min_salience=0.3)
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import List, Optional

from app.core.redis import get_redis as _get_redis

from app.services.silent_failure_tracker import Tracker

logger = logging.getLogger(__name__)

# One tracker for the whole module — reasons differentiate between
# log/get/consume/prune failure modes.
_OBS_LOG_TRACKER = Tracker("observation_log")

OBS_ZSET_KEY = "sara:observations:{user_id}"
OBS_DETAIL_KEY = "sara:observation_details:{user_id}"
OBS_TTL_SECONDS = 24 * 60 * 60  # 24 hours


@dataclass
class Observation:
    id: str
    timestamp: str  # ISO
    source: str  # which subscriber/system logged this
    description: str  # human-readable description
    salience: float  # 0.0-1.0
    category: str  # security, schedule, social, health, home, system
    consumed: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, json_str: str) -> "Observation":
        return cls(**json.loads(json_str))


async def log_observation(
    user_id: str,
    description: str,
    salience: float,
    source: str = "system",
    category: str = "general",
    observation_id: Optional[str] = None,
) -> str:
    """
    Log an observation with a salience score.
    Returns the observation ID.
    """
    obs_id = observation_id or f"obs_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    obs = Observation(
        id=obs_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        source=source,
        description=description,
        salience=min(max(salience, 0.0), 1.0),
        category=category,
    )

    try:
        r = await _get_redis()
        zset_key = OBS_ZSET_KEY.format(user_id=user_id)
        detail_key = OBS_DETAIL_KEY.format(user_id=user_id)

        pipe = r.pipeline()
        pipe.zadd(zset_key, {obs_id: obs.salience})
        pipe.hset(detail_key, obs_id, obs.to_json())
        # Set TTL on both keys (refreshed on each write)
        pipe.expire(zset_key, OBS_TTL_SECONDS)
        pipe.expire(detail_key, OBS_TTL_SECONDS)
        await pipe.execute()

        logger.debug(f"[ObservationLog] Logged {obs_id} salience={obs.salience:.2f} category={category}: {description[:80]}")

        # Update working memory stats
        await _sync_stats(user_id)

        return obs_id
    except Exception as e:
        _OBS_LOG_TRACKER.note(f"log:{type(e).__name__}")
        logger.warning(f"[ObservationLog] Failed to log observation: {e}")
        return obs_id


async def get_pending_observations(
    user_id: str, min_salience: float = 0.0, limit: int = 20
) -> List[Observation]:
    """Get unconsumed observations sorted by salience (highest first)."""
    try:
        r = await _get_redis()
        zset_key = OBS_ZSET_KEY.format(user_id=user_id)
        detail_key = OBS_DETAIL_KEY.format(user_id=user_id)

        # Get observation IDs above min_salience, highest first
        obs_ids = await r.zrevrangebyscore(
            zset_key, "+inf", str(min_salience), start=0, num=limit
        )
        if not obs_ids:
            return []

        # Fetch details
        details = await r.hmget(detail_key, *obs_ids)
        observations = []
        for raw in details:
            if raw:
                obs = Observation.from_json(raw)
                if not obs.consumed:
                    observations.append(obs)
        return observations
    except Exception as e:
        _OBS_LOG_TRACKER.note(f"get_pending:{type(e).__name__}")
        logger.warning(f"[ObservationLog] Failed to get pending observations: {e}")
        return []


async def get_accumulated_salience(user_id: str, top_n: int = 10) -> float:
    """
    Sum of top-N pending observation salience scores.
    Used to decide whether to trigger deliberation.
    """
    try:
        r = await _get_redis()
        zset_key = OBS_ZSET_KEY.format(user_id=user_id)
        # Get top N scores
        top_scores = await r.zrevrange(zset_key, 0, top_n - 1, withscores=True)
        return sum(score for _, score in top_scores) if top_scores else 0.0
    except Exception as e:
        _OBS_LOG_TRACKER.note(f"accumulated_salience:{type(e).__name__}")
        logger.warning(f"[ObservationLog] Failed to get accumulated salience: {e}")
        return 0.0


async def consume_observations(user_id: str, observation_ids: List[str]) -> int:
    """
    Mark observations as consumed after deliberation processes them.
    Removes them from the sorted set and marks consumed in details.
    Returns count of consumed observations.
    """
    if not observation_ids:
        return 0
    try:
        r = await _get_redis()
        zset_key = OBS_ZSET_KEY.format(user_id=user_id)
        detail_key = OBS_DETAIL_KEY.format(user_id=user_id)

        pipe = r.pipeline()
        # Remove from sorted set
        pipe.zrem(zset_key, *observation_ids)
        # Mark as consumed in details (keep for history)
        for obs_id in observation_ids:
            raw = await r.hget(detail_key, obs_id)
            if raw:
                obs = Observation.from_json(raw)
                obs.consumed = True
                pipe.hset(detail_key, obs_id, obs.to_json())
        results = await pipe.execute()

        # Update working memory stats
        await _sync_stats(user_id)

        consumed_count = results[0] if results else 0
        if consumed_count:
            try:
                from app.services.world_state.cognition import resolve_attention_observations
                await resolve_attention_observations(user_id, observation_ids)
            except Exception as e:
                # Recovery is safe: the durable row stays queued and will be
                # mirrored back into Redis on the next attention drain.
                logger.warning("[ObservationLog] durable attention resolution failed: %s", e)
        logger.debug(f"[ObservationLog] Consumed {consumed_count} observations")
        return consumed_count
    except Exception as e:
        _OBS_LOG_TRACKER.note(f"consume:{type(e).__name__}")
        logger.warning(f"[ObservationLog] Failed to consume observations: {e}")
        return 0


async def prune_old(user_id: str, max_age_hours: int = 24) -> int:
    """Remove observations older than max_age_hours. Returns count removed."""
    try:
        r = await _get_redis()
        detail_key = OBS_DETAIL_KEY.format(user_id=user_id)
        zset_key = OBS_ZSET_KEY.format(user_id=user_id)

        # Get all observation details
        all_details = await r.hgetall(detail_key)
        if not all_details:
            return 0

        cutoff = datetime.now(timezone.utc).timestamp() - (max_age_hours * 3600)
        to_remove = []
        for obs_id, raw in all_details.items():
            try:
                obs = Observation.from_json(raw)
                obs_time = datetime.fromisoformat(obs.timestamp).timestamp()
                if obs_time < cutoff:
                    to_remove.append(obs_id)
            except (ValueError, KeyError):
                to_remove.append(obs_id)  # corrupt entry

        if to_remove:
            pipe = r.pipeline()
            pipe.zrem(zset_key, *to_remove)
            pipe.hdel(detail_key, *to_remove)
            await pipe.execute()

        if to_remove:
            await _sync_stats(user_id)
            logger.debug(f"[ObservationLog] Pruned {len(to_remove)} old observations")
        return len(to_remove)
    except Exception as e:
        _OBS_LOG_TRACKER.note(f"prune:{type(e).__name__}")
        logger.warning(f"[ObservationLog] Failed to prune observations: {e}")
        return 0


async def get_observation_count(user_id: str) -> int:
    """Get number of pending (unconsumed) observations."""
    try:
        r = await _get_redis()
        zset_key = OBS_ZSET_KEY.format(user_id=user_id)
        return await r.zcard(zset_key)
    except Exception:
        return 0


async def _sync_stats(user_id: str) -> None:
    """Sync observation stats to working memory."""
    try:
        count = await get_observation_count(user_id)
        r = await _get_redis()
        zset_key = OBS_ZSET_KEY.format(user_id=user_id)
        top = await r.zrevrange(zset_key, 0, 0, withscores=True)
        high_water = top[0][1] if top else 0.0

        from app.services.working_memory import sync_observation_stats
        await sync_observation_stats(user_id, count, high_water)
    except Exception as e:
        logger.debug(f"[ObservationLog] Stats sync failed: {e}")
