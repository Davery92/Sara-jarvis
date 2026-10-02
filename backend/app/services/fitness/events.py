"""Thin durable fitness events, plus cache invalidation after the commit.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 17.4. Two jobs, and the split between
them is the point:

* **The event row is written inside the caller's transaction.** It commits
  with the record it describes, or not at all. An event about a weigh-in
  that was rolled back would make a consumer reason about a reading that
  does not exist.
* **The cache invalidation runs after the commit.** Dropping a cache entry
  before the new row is visible would let a concurrent reader repopulate it
  from the old data — the invalidation would have fired and still left a
  stale entry behind.

Two rules about content:

**No values travel in the payload.** `fitness.observation_ingested` says
*that* a weight was recorded, with its metric type, day and row id — never
the number. A world fact is a wider surface than an owned fitness row, and
copying a body measurement into it would put it somewhere the health
authority rules do not reach. A consumer that needs the number reads the
state, under the athlete's own auth.

**A failure here never loses the source record.** Pub/sub and Redis are both
best effort; the athlete's set, meal or weigh-in is already committed.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, Optional

from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_INVALIDATE_INFO_KEY = "fitness_state_invalidate_after_commit"
_HOOK_INSTALLED = False

#: Payload keys that may never appear. Checked rather than trusted, because
#: the cost of a mistake is a body measurement in a lower-sensitivity store,
#: and that is not something a code review reliably catches every time.
FORBIDDEN_PAYLOAD_KEYS = frozenset({
    "value", "values", "weight", "body_weight", "weight_kg", "calories",
    "protein_g", "carbs_g", "fat_g", "hrv", "heart_rate", "sleep_hours",
    "measurement", "notes", "description", "rationale", "original_value",
})


def _dispatch_invalidations(session: Session) -> None:
    user_ids = set(session.info.pop(_INVALIDATE_INFO_KEY, ()) or ())
    if not user_ids:
        return
    try:
        from app.core.redis import get_redis_sync
        from app.services.fitness.state import invalidate_fitness_state
        client = get_redis_sync()
    except Exception as exc:
        logger.debug("fitness invalidation unavailable (%s)", type(exc).__name__)
        return
    for user_id in user_ids:
        try:
            invalidate_fitness_state(client, user_id)
        except Exception as exc:
            # The cache key carries a data-revision fingerprint, so a missed
            # invalidation costs the TTL rather than being unbounded. That is
            # exactly why this is allowed to fail quietly.
            logger.debug("fitness invalidation failed (%s)", type(exc).__name__)


def _clear_invalidations(session: Session) -> None:
    session.info.pop(_INVALIDATE_INFO_KEY, None)


def _clear_soft(session: Session, previous_transaction) -> None:
    _clear_invalidations(session)


def install_hooks() -> None:
    global _HOOK_INSTALLED
    if _HOOK_INSTALLED:
        return
    sa_event.listen(Session, "after_commit", _dispatch_invalidations)
    # BOTH rollback events. `after_rollback` only fires when a DBAPI
    # transaction was actually open, so a rollback on a session that has
    # only queued an invalidation would leave the queue in place and drop
    # the cache for a write that never happened. `after_soft_rollback`
    # always fires.
    sa_event.listen(Session, "after_rollback", _clear_invalidations)
    sa_event.listen(Session, "after_soft_rollback", _clear_soft)
    _HOOK_INSTALLED = True


install_hooks()


def queue_invalidation(db: Session, user_id: str) -> None:
    """Mark this athlete's cached state for dropping once the commit lands.

    Safe to call repeatedly in one transaction: the set collapses, so a
    bulk ingest of thirty observations drops the cache once rather than
    thirty times.
    """
    if not user_id:
        return
    try:
        db.info.setdefault(_INVALIDATE_INFO_KEY, set()).add(str(user_id))
    except Exception as exc:
        logger.debug("could not queue fitness invalidation (%s)", type(exc).__name__)


def record_fitness_event(
    db: Session,
    user_id: str,
    kind: str,
    *,
    dedupe_key: str,
    payload: Optional[Dict[str, Any]] = None,
    source: str = "fitness_coach",
    source_ref: Optional[str] = None,
    logical_date: Optional[date] = None,
    aggregate_type: Optional[str] = None,
    aggregate_id: Optional[str] = None,
    actor_type: str = "user",
    actor_id: Optional[str] = None,
) -> Optional[str]:
    """Append one thin event in the CALLER's transaction, and queue invalidation.

    Returns the event id, or None when world events are disabled or the
    append failed. Never raises: the record this describes is the thing that
    matters, and a bookkeeping row must not be able to roll it back.
    """
    body: Dict[str, Any] = dict(payload or {})
    leaked = FORBIDDEN_PAYLOAD_KEYS & set(body)
    if leaked:
        # Drop them rather than refuse: refusing would fail the athlete's
        # write for a bookkeeping reason, and the event is still useful
        # without the values. Logged loudly because it is a code defect.
        logger.error(
            "fitness event %s carried private values %s — dropped. Events "
            "reference records; consumers read them under the owner's auth.",
            kind, sorted(leaked),
        )
        body = {k: v for k, v in body.items() if k not in leaked}
    if logical_date is not None:
        body["logical_date"] = logical_date.isoformat()

    queue_invalidation(db, user_id)

    try:
        from app.services.world_state.writer import append_world_event
        # A SAVEPOINT, not a bare try: the append flushes, and in PostgreSQL a
        # failed statement poisons the whole transaction. Without this, an
        # event-row failure would take the athlete's weigh-in down with it at
        # commit time — the exact inversion this function exists to avoid.
        with db.begin_nested():
            row = append_world_event(
                db, user_id=str(user_id), kind=kind, source=source,
                source_ref=source_ref, dedupe_key=dedupe_key, payload=body,
                aggregate_type=aggregate_type, aggregate_id=aggregate_id,
                actor_type=actor_type, actor_id=actor_id or str(user_id),
            )
        return getattr(row, "event_id", None) if row is not None else None
    except Exception as exc:
        logger.warning(
            "fitness event %s not appended (%s): %s", kind, type(exc).__name__, exc,
        )
        return None
