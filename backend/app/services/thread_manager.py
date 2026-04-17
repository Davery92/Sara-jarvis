"""
Thread Manager — CRUD + lifecycle for conversation threads.

Tracks things David mentioned that Sara could naturally follow up on.
Each thread has a follow-up window, anti-harping limits, and response tracking.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
THREAD_CACHE_KEY = "sara:open_threads:{user_id}"
THREAD_CACHE_TTL = 300  # 5 minutes


async def _get_redis() -> aioredis.Redis:
    """Get shared Redis connection."""
    from app.services.unified_context import _get_redis as uc_get_redis
    return await uc_get_redis()


async def get_open_threads(user_id: str, db: AsyncSession) -> List[Dict]:
    """Get open threads that are ripe for follow-up.

    Returns threads where:
    - status = 'open'
    - follow_up_after <= NOW() (enough time has passed)
    - mention_count < max_mentions (not harped on)
    - david_response NOT IN ('negative', 'ignored')
    """
    result = await db.execute(text("""
        SELECT id, topic, topic_category, opened_at, follow_up_after,
               follow_up_before, last_mentioned_at, mention_count, max_mentions,
               david_response, suggested_followup, priority, source
        FROM followup_thread
        WHERE user_id = :user_id
          AND status = 'open'
          AND (follow_up_after IS NULL OR follow_up_after <= NOW())
          AND mention_count < max_mentions
          AND (david_response IS NULL OR david_response NOT IN ('negative', 'ignored'))
          AND (follow_up_before IS NULL OR follow_up_before > NOW())
        ORDER BY priority DESC, opened_at DESC
        LIMIT 10
    """), {"user_id": user_id})

    rows = result.fetchall()
    threads = []
    for r in rows:
        hours_ago = 0
        if r.opened_at:
            delta = datetime.now(timezone.utc) - r.opened_at.replace(tzinfo=None)
            hours_ago = round(delta.total_seconds() / 3600, 1)

        threads.append({
            "id": str(r.id),
            "topic": r.topic,
            "category": r.topic_category,
            "hours_ago": hours_ago,
            "mention_count": r.mention_count or 0,
            "max_mentions": r.max_mentions or 3,
            "suggested_followup": r.suggested_followup,
            "priority": r.priority or 0.5,
            "source": r.source,
        })

    return threads


async def get_all_open_threads(user_id: str, db: AsyncSession) -> List[Dict]:
    """Get ALL open threads (including not-yet-ripe), for dedup during extraction."""
    result = await db.execute(text("""
        SELECT id, topic, topic_category, status, opened_at
        FROM followup_thread
        WHERE user_id = :user_id
          AND status IN ('open', 'followed_up')
          AND (follow_up_before IS NULL OR follow_up_before > NOW())
        ORDER BY opened_at DESC
        LIMIT 20
    """), {"user_id": user_id})

    return [
        {
            "id": str(r.id),
            "topic": r.topic,
            "category": r.topic_category,
            "status": r.status,
        }
        for r in result.fetchall()
    ]


async def get_open_threads_summary(user_id: str) -> List[Dict]:
    """Get open threads from Redis cache (fast path for reactive engine)."""
    try:
        r = await _get_redis()
        cached = await r.get(THREAD_CACHE_KEY.format(user_id=user_id))
        if cached:
            return json.loads(cached)
    except Exception as e:
        logger.debug(f"Thread cache read failed: {e}")
    return []


async def refresh_thread_cache(user_id: str, db: AsyncSession) -> None:
    """Refresh the Redis cache of open threads."""
    try:
        threads = await get_open_threads(user_id, db)
        r = await _get_redis()
        key = THREAD_CACHE_KEY.format(user_id=user_id)
        await r.set(key, json.dumps(threads), ex=THREAD_CACHE_TTL)
    except Exception as e:
        logger.debug(f"Thread cache refresh failed: {e}")


async def record_mention(thread_id: str, db: AsyncSession) -> Dict:
    """Record that Sara mentioned this thread. Auto-drops if >= max_mentions."""
    result = await db.execute(text("""
        UPDATE followup_thread
        SET mention_count = mention_count + 1,
            last_mentioned_at = NOW(),
            updated_at = NOW(),
            status = CASE
                WHEN mention_count + 1 >= max_mentions THEN 'dropped'
                ELSE status
            END
        WHERE id = :tid
        RETURNING mention_count, max_mentions, status
    """), {"tid": thread_id})

    row = result.fetchone()
    if row:
        return {
            "success": True,
            "mention_count": row.mention_count,
            "max_mentions": row.max_mentions,
            "status": row.status,
            "auto_dropped": row.status == "dropped",
        }
    return {"success": False, "error": "Thread not found"}


async def resolve_thread(thread_id: str, db: AsyncSession) -> bool:
    """Mark a thread as resolved (David completed or addressed the thing)."""
    result = await db.execute(text("""
        UPDATE followup_thread
        SET status = 'resolved', resolved_at = NOW(), updated_at = NOW()
        WHERE id = :tid AND status = 'open'
    """), {"tid": thread_id})
    return result.rowcount > 0


async def record_david_response(
    thread_id: str, response_quality: str, db: AsyncSession
) -> bool:
    """Record how David responded to a follow-up.

    response_quality: 'positive', 'neutral', 'negative', 'ignored'
    If negative or ignored, thread is dropped immediately.
    """
    new_status = "open"
    if response_quality in ("negative", "ignored"):
        new_status = "dropped"
    elif response_quality == "positive":
        new_status = "followed_up"

    result = await db.execute(text("""
        UPDATE followup_thread
        SET david_response = :response,
            status = :new_status,
            updated_at = NOW()
        WHERE id = :tid
    """), {"tid": thread_id, "response": response_quality, "new_status": new_status})
    return result.rowcount > 0


async def expire_stale_threads(user_id: str, db: AsyncSession) -> int:
    """Mark threads past their follow_up_before as expired."""
    result = await db.execute(text("""
        UPDATE followup_thread
        SET status = 'expired', updated_at = NOW()
        WHERE user_id = :user_id
          AND status = 'open'
          AND follow_up_before IS NOT NULL
          AND follow_up_before < NOW()
    """), {"user_id": user_id})
    count = result.rowcount
    if count > 0:
        logger.info(f"Expired {count} stale conversation threads")
    return count


async def create_thread(
    user_id: str,
    topic: str,
    category: str,
    follow_up_after: datetime,
    follow_up_before: datetime,
    max_mentions: int,
    original_context: str,
    suggested_followup: str,
    priority: float,
    db: AsyncSession,
    source: str = "chat",
) -> str:
    """Create a new conversation thread. Returns the thread ID."""
    result = await db.execute(text("""
        INSERT INTO followup_thread
            (user_id, topic, topic_category, follow_up_after, follow_up_before,
             max_mentions, original_context, suggested_followup, priority, source)
        VALUES
            (:user_id, :topic, :category, :follow_up_after, :follow_up_before,
             :max_mentions, :original_context, :suggested_followup, :priority, :source)
        RETURNING id
    """), {
        "user_id": user_id,
        "topic": topic,
        "category": category,
        "follow_up_after": follow_up_after,
        "follow_up_before": follow_up_before,
        "max_mentions": max_mentions,
        "original_context": original_context,
        "suggested_followup": suggested_followup,
        "priority": priority,
        "source": source,
    })
    row = result.fetchone()
    return str(row[0]) if row else ""
