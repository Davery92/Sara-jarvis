"""Generator-side habituation for proactive stimuli.

Repeated unengaged stimuli should stop being generated at the source instead
of relying on downstream dedup to silence them. This service keeps one row per
(generator, stimulus_key), decays ignored items, and lets engagement recover
strength over time.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)

MIN_STRENGTH_TO_GENERATE = 0.1
IGNORED_DECAY_FACTOR = 0.5
ENGAGED_RECOVERY_FACTOR = 2.0
SPONTANEOUS_RECOVERY_PER_DAY = 0.05
ENGAGEMENT_WINDOW_HOURS = 24


async def should_generate(
    db: AsyncSession,
    generator: str,
    stimulus_key: str,
) -> bool:
    """Return whether the generator should build this candidate.

    Also applies any pending ignored-delivery decay and spontaneous recovery.
    """
    generator = (generator or "unknown")[:80]
    stimulus_key = (stimulus_key or "unknown")[:255]
    await _ensure_row(db, generator, stimulus_key)
    await _apply_pending_decay(db, generator, stimulus_key)

    row = (await db.execute(text("""
        SELECT strength FROM stimulus_habituation
        WHERE generator = :generator AND stimulus_key = :stimulus_key
    """), {"generator": generator, "stimulus_key": stimulus_key})).fetchone()
    strength = float(row.strength if row else 1.0)
    return strength >= MIN_STRENGTH_TO_GENERATE


async def note_delivery(
    db: AsyncSession,
    generator: str,
    stimulus_key: str,
) -> None:
    """Record that a stimulus actually left the generator."""
    generator = (generator or "unknown")[:80]
    stimulus_key = (stimulus_key or "unknown")[:255]
    await _ensure_row(db, generator, stimulus_key)
    await db.execute(text("""
        UPDATE stimulus_habituation
        SET last_fired_at = NOW(), updated_at = NOW()
        WHERE generator = :generator AND stimulus_key = :stimulus_key
    """), {"generator": generator, "stimulus_key": stimulus_key})


async def note_engagement(
    db: AsyncSession,
    generator: str,
    stimulus_key: str,
    engaged_at: Optional[object] = None,
) -> None:
    """Boost a stimulus when David engages with it."""
    generator = (generator or "unknown")[:80]
    stimulus_key = (stimulus_key or "unknown")[:255]
    await _ensure_row(db, generator, stimulus_key)
    await db.execute(text("""
        UPDATE stimulus_habituation
        SET strength = LEAST(1.0, GREATEST(0.0, strength) * :factor),
            last_engaged_at = COALESCE(:engaged_at, NOW()),
            last_decay_checked_at = NOW(),
            updated_at = NOW()
        WHERE generator = :generator AND stimulus_key = :stimulus_key
    """), {
        "generator": generator,
        "stimulus_key": stimulus_key,
        "factor": ENGAGED_RECOVERY_FACTOR,
        "engaged_at": engaged_at,
    })


async def _ensure_row(db: AsyncSession, generator: str, stimulus_key: str) -> None:
    await db.execute(text("""
        INSERT INTO stimulus_habituation (generator, stimulus_key, strength, last_decay_checked_at)
        VALUES (:generator, :stimulus_key, 1.0, NOW())
        ON CONFLICT (generator, stimulus_key) DO NOTHING
    """), {"generator": generator, "stimulus_key": stimulus_key})


async def _apply_pending_decay(db: AsyncSession, generator: str, stimulus_key: str) -> None:
    """Decay ignored deliveries once, then recover slowly toward 1.0."""
    row = (await db.execute(text("""
        SELECT strength, last_fired_at, last_engaged_at, last_decay_checked_at
        FROM stimulus_habituation
        WHERE generator = :generator AND stimulus_key = :stimulus_key
    """), {"generator": generator, "stimulus_key": stimulus_key})).fetchone()
    if not row:
        return

    now = local_now()
    strength = float(row.strength or 1.0)
    last_checked = row.last_decay_checked_at or row.last_fired_at or now

    days = max(0.0, (now - last_checked).total_seconds() / 86400.0)
    if days:
        strength = min(1.0, strength + (days * SPONTANEOUS_RECOVERY_PER_DAY))

    last_fired = row.last_fired_at
    last_engaged = row.last_engaged_at
    ignored_window_elapsed = (
        last_fired is not None
        and now - last_fired >= timedelta(hours=ENGAGEMENT_WINDOW_HOURS)
        and (last_engaged is None or last_engaged < last_fired)
        and (row.last_decay_checked_at is None or row.last_decay_checked_at < last_fired)
    )
    if ignored_window_elapsed:
        strength *= IGNORED_DECAY_FACTOR

    await db.execute(text("""
        UPDATE stimulus_habituation
        SET strength = :strength,
            last_decay_checked_at = NOW(),
            updated_at = NOW()
        WHERE generator = :generator AND stimulus_key = :stimulus_key
    """), {
        "generator": generator,
        "stimulus_key": stimulus_key,
        "strength": max(0.0, min(1.0, strength)),
    })
