"""Per-trigger Redis TTL cooldown.

This is the *fine-grained* cooldown for trigger-instance deduplication
(e.g. "don't re-roast the same stale_pr:oldest_branch combination for 24h").

Broader category-level cooldowns (don't spam user with too many roasts per
day, regardless of which trigger) live in unified_notification.send_notification
and are tuned via tunable_setting rows. That layer enters in PR 4.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import redis.asyncio as redis

logger = logging.getLogger(__name__)


_redis_client: Optional[redis.Redis] = None


def _get_redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://redis:6379/0")


async def _get_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = await redis.from_url(
            _get_redis_url(), encoding="utf-8", decode_responses=True
        )
    return _redis_client


def _cooldown_key(dedup_key: str) -> str:
    return f"narrator:cooldown:{dedup_key}"


async def is_on_cooldown(dedup_key: str) -> bool:
    """True if a trigger with this dedup_key fired recently."""
    try:
        client = await _get_client()
        return bool(await client.exists(_cooldown_key(dedup_key)))
    except Exception as exc:
        # Redis hiccup → fail open. Better to over-fire once than to silently
        # mute the whole narrator. Cooldown is opportunistic, not load-bearing.
        logger.warning("narrator: cooldown check failed (allowing fire): %s", exc)
        return False


async def mark_fired(dedup_key: str, cooldown_seconds: int) -> None:
    """Record a fire so subsequent is_on_cooldown(same key) returns True."""
    try:
        client = await _get_client()
        await client.setex(_cooldown_key(dedup_key), cooldown_seconds, "1")
    except Exception as exc:
        logger.warning("narrator: cooldown mark failed: %s", exc)


async def clear_cooldown(dedup_key: str) -> None:
    """Admin/test helper: drop a single cooldown key."""
    try:
        client = await _get_client()
        await client.delete(_cooldown_key(dedup_key))
    except Exception as exc:
        logger.warning("narrator: cooldown clear failed: %s", exc)
