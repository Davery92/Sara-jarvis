"""
Event-envelope adapter (SINGULAR_SARA_MASTER_PLAN §C1).

"Implement adapters from current event bus, observations, ACS activity, task
progress, and integration callbacks" into the canonical `EventEnvelopeV1`
contract (§4.1), and "persist event causality and idempotency."

This is the event-bus adapter specifically: every event published through
`app.services.event_bus.event_bus` already carries almost everything the
canonical envelope needs (`event_id`, `user_id`, `payload`, `source`,
`timestamp`) — the gaps are `kind` (derived from `event_type`), a stable
`dedupe_key`, and `correlation_id`/`causation_id`. This module fills those
gaps and persists the result, without changing what `EventBus.publish()`
actually does for its existing subscribers (see the hook in `event_bus.py`,
which calls this best-effort, after the real publish work).

`dedupe_key` defaults to a deterministic hash of (kind, user_id, payload) so
publishing "the same fact" twice yields the same key — the property the C1
exit gate calls "replaying an event produces the same dedupe... outcome."

`correlation_id` defaults to the currently-bound kernel turn (if any) — see
`app.core.correlation` — so an event published from inside a kernel turn is
traceably "caused by" that turn without every publish call site needing to
thread the ID through by hand.

Storage is Redis-only for now (matching the existing 7-day `event_log`
TTL this replaces nothing of) — durable, longer-lived persistence is a
follow-up once something actually needs to query across that window; that's
a schema migration on shared state and should be a deliberate, confirmed
step, not a side effect of this adapter.
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.schemas.contracts import EventEnvelopeV1

logger = logging.getLogger(__name__)

_ENVELOPE_TTL_SECONDS = 7 * 24 * 60 * 60  # match the legacy event_log retention
_INDEX_MAX_SIZE = 500


def _stable_dedupe_key(kind: str, user_id: str, payload: Dict[str, Any]) -> str:
    """Deterministic — same (kind, user_id, payload) always yields the same
    key, regardless of dict key order, so identical re-publishes dedupe."""
    canonical = json.dumps(payload, sort_keys=True, default=str)
    digest = hashlib.sha256(f"{kind}:{user_id}:{canonical}".encode()).hexdigest()[:24]
    return f"{kind}:{user_id}:{digest}"


def build_envelope(event) -> EventEnvelopeV1:
    """Pure mapping — no I/O — from the event-bus `Event` model to the
    canonical `EventEnvelopeV1`. Kept separate from persistence so it's
    trivially unit-testable."""
    from app.core.correlation import get_current_correlation

    metadata = event.metadata or {}
    kind = event.event_type.value
    now = datetime.now(timezone.utc)

    bound = get_current_correlation()
    correlation_id = metadata.get("correlation_id") or bound.kernel_turn_id

    return EventEnvelopeV1(
        event_id=event.event_id,
        occurred_at=event.timestamp,
        observed_at=now,
        user_id=event.user_id,
        source=event.source,
        kind=kind,
        payload=event.payload or {},
        provenance=metadata.get("provenance") or event.source,
        confidence=metadata.get("confidence", 1.0),
        sensitivity=metadata.get("sensitivity", "normal"),
        retention_class=metadata.get("retention_class", "standard"),
        correlation_id=correlation_id,
        causation_id=metadata.get("causation_id"),
        dedupe_key=metadata.get("dedupe_key") or _stable_dedupe_key(kind, event.user_id, event.payload or {}),
        source_ref=metadata.get("source_ref"),
    )


async def _get_redis():
    import redis.asyncio as aioredis
    return aioredis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)


async def record_envelope(envelope: EventEnvelopeV1) -> None:
    """Persist the canonical envelope and index it under its user for
    recent-event lookups (diagnostics, future replay)."""
    r = await _get_redis()
    try:
        key = f"sara:event_envelope:{envelope.event_id}"
        await r.setex(key, _ENVELOPE_TTL_SECONDS, envelope.model_dump_json())

        index_key = f"sara:event_envelope:index:{envelope.user_id}"
        score = envelope.occurred_at.timestamp()
        await r.zadd(index_key, {envelope.event_id: score})
        await r.zremrangebyrank(index_key, 0, -(_INDEX_MAX_SIZE + 1))
        await r.expire(index_key, _ENVELOPE_TTL_SECONDS)
    finally:
        try:
            await r.close()
        except Exception:
            pass


async def record_from_event(event) -> EventEnvelopeV1:
    """Build + persist in one call — what `EventBus.publish()` calls."""
    envelope = build_envelope(event)
    await record_envelope(envelope)
    return envelope


async def get_envelope(event_id: str) -> Optional[EventEnvelopeV1]:
    r = await _get_redis()
    try:
        raw = await r.get(f"sara:event_envelope:{event_id}")
        return EventEnvelopeV1.model_validate_json(raw) if raw else None
    finally:
        try:
            await r.close()
        except Exception:
            pass


async def get_recent_envelopes(user_id: str, limit: int = 20) -> List[EventEnvelopeV1]:
    """Most recent canonical envelopes for a user, newest first. Entries
    whose TTL has already expired are silently skipped rather than raising —
    the index and the envelope keys can legitimately fall out of step near
    the retention boundary."""
    r = await _get_redis()
    try:
        index_key = f"sara:event_envelope:index:{user_id}"
        event_ids = await r.zrevrange(index_key, 0, max(limit, 1) - 1)
        envelopes: List[EventEnvelopeV1] = []
        for event_id in event_ids:
            raw = await r.get(f"sara:event_envelope:{event_id}")
            if raw:
                envelopes.append(EventEnvelopeV1.model_validate_json(raw))
        return envelopes
    finally:
        try:
            await r.close()
        except Exception:
            pass
