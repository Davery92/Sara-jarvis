"""
Working Memory — Sara's persistent, incrementally-updated awareness.

Extends the UnifiedContextSnapshot with read/update/rebuild operations.
Working memory is always fresh because event subscribers update it continuously,
rather than rebuilding from scratch every 15 minutes.

Usage:
    from app.services.working_memory import read_memory, update_memory, rebuild_memory

    memory = await read_memory(user_id)
    await update_memory(user_id, source="chat_stream", hours_since_last_chat=0.0)
    await rebuild_memory(user_id, db)  # cold-start only
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.services.unified_context import (
    UnifiedContextSnapshot,
    read_snapshot,
)
from app.services.context_writer import update_fields, rebuild_snapshot

logger = logging.getLogger(__name__)


async def read_memory(user_id: str) -> UnifiedContextSnapshot:
    """
    Read the full working memory from Redis.
    This is the single source of truth for Sara's current awareness.
    Returns an empty snapshot if Redis is cold.
    """
    return await read_snapshot(user_id)


async def update_memory(user_id: str, source: str = "unknown", **fields) -> None:
    """
    Incrementally update working memory fields.
    Delegates to context_writer.update_fields which handles:
    - Atomic Redis hash updates
    - Version bumping
    - Notable field change tracking
    """
    if not fields:
        return
    await update_fields(user_id, source=source, **fields)


async def rebuild_memory(user_id: str, db: Session) -> UnifiedContextSnapshot:
    """
    Full cold-start rebuild from DB.
    Used on Redis restart, first boot, or if snapshot is missing/stale.
    """
    return await rebuild_snapshot(user_id, db)


async def update_sara_state(
    user_id: str,
    focus: Optional[str] = None,
    emotional_tone: Optional[str] = None,
    emotional_intensity: Optional[float] = None,
    curiosities: Optional[list] = None,
    deliberation_happened: bool = False,
) -> None:
    """
    Update Sara's internal state fields in working memory.
    Called after deliberation to persist Sara's evolving awareness.

    Emotional tone updates go through the momentum system: the new tone
    blends with the current tone rather than replacing it instantly.
    """
    fields = {}
    if focus is not None:
        fields["sara_focus"] = focus

    if emotional_tone is not None:
        # Apply emotional momentum — don't flip instantly
        from app.services.emotional_state import update_emotional_state, BASELINE_TONE, BASELINE_INTENSITY
        try:
            current = await read_memory(user_id)
            current_tone = current.sara_emotional_tone or BASELINE_TONE
            current_intensity = current.sara_emotional_intensity if current.sara_emotional_intensity else BASELINE_INTENSITY
        except Exception:
            current_tone = BASELINE_TONE
            current_intensity = BASELINE_INTENSITY

        new_state = update_emotional_state(
            current_tone=current_tone,
            current_intensity=current_intensity,
            new_tone=emotional_tone,
            new_intensity=emotional_intensity or 0.6,
        )
        fields["sara_emotional_tone"] = new_state.tone
        fields["sara_emotional_intensity"] = new_state.intensity

    if curiosities is not None:
        fields["sara_curiosities"] = curiosities[:5]  # cap at 5
    if deliberation_happened:
        fields["sara_last_deliberation_at"] = datetime.now(timezone.utc).isoformat()
    if fields:
        await update_fields(user_id, source="deliberation", **fields)


async def increment_deliberation_count(user_id: str) -> None:
    """Bump the daily deliberation counter. Reset handled by DerivedSignalRefresher at midnight."""
    try:
        from app.services.unified_context import _get_redis, SNAPSHOT_KEY
        r = await _get_redis()
        key = SNAPSHOT_KEY.format(user_id=user_id)
        await r.hincrby(key, "sara_deliberation_count_today", 1)
    except Exception as e:
        logger.warning(f"Failed to increment deliberation count: {e}")


async def inject_acs_signals(user_id: str) -> None:
    """
    Inject signals from the latest ACS session into working memory.
    Called after ACS session finalization to bridge autonomous activity into
    the salience/deliberation pipeline.
    """
    try:
        from app.db.session import get_async_session_factory
        from sqlalchemy import text

        async_session = get_async_session_factory()
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT mode, avg_engagement, notes_written, nodes_created, summary
                FROM acs_session_log
                WHERE user_id = :uid
                ORDER BY started_at DESC
                LIMIT 1
            """), {"uid": user_id})
            row = result.fetchone()
            if not row:
                return

            mode, avg_eng, notes, nodes, summary = row

            # Only inject if session was productive
            if (avg_eng or 0) < 0.4 and (notes or 0) == 0 and (nodes or 0) == 0:
                return

            # Build a curiosity list from high-engagement session topics
            curiosities = []
            if summary:
                curiosities = [summary[:100]]

            fields = {}
            if curiosities:
                fields["sara_curiosities"] = curiosities
            if summary:
                fields["sara_focus"] = f"ACS {mode}: {summary[:80]}" if summary else None

            if fields:
                await update_fields(user_id, source="acs_session", **fields)
                logger.info(f"Injected ACS signals into working memory: mode={mode}, engagement={avg_eng:.2f}")

    except Exception as e:
        logger.warning(f"ACS signal injection failed: {e}")


async def sync_observation_stats(user_id: str, count: int, high_water: float) -> None:
    """
    Update observation stats in working memory.
    Called by observation_log after logging/consuming observations.
    """
    await update_fields(
        user_id,
        source="observation_log",
        observation_count=count,
        salience_high_water=high_water,
    )
