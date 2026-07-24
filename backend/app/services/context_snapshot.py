"""
Canonical context snapshot — world/self/relationship state (SINGULAR_SARA_
MASTER_PLAN §13/§4.2/§C2).

§4.2 wants one context assembler producing versioned world/body/relationship/
self projections, each field carrying `as_of`, source, and confidence, read
identically by chat, ambient, and focused states. Body state already has its
canonical projection (`body_state_projection.py`); this module is the
read-only equivalent for the other three — computed from sources that
already exist (kernel's published state, the intent-graph projection,
`calendar_event`, `conversation`), not a new truth store.

Deliberately honest about gaps rather than fabricating data: there is no
commitment-extractor yet (that's C3), so `relationship_state.recent_promises`
stays empty rather than guessing at "promises" from data that doesn't
represent them. `self_state.open_concerns` is real, though — it's every
degraded body component's impact string, which is exactly what the plan
means by "open concerns."

Nothing reads from this module yet; it's the same kind of silhouette as
`intent_graph_projection.py` — proof that one coherent snapshot CAN be built
from what already exists, ahead of anything actually being routed through it
(that routing is the rest of C2, and is a real behavior change deserving its
own careful rollout, not a side effect of this module existing).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.contracts import RelationshipStateV1, SelfStateV1, WorldStateV1

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"
_TZ = ZoneInfo("America/New_York")


def _today_bounds_naive(now_utc: datetime) -> tuple:
    local_now = now_utc.astimezone(_TZ)
    start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.replace(tzinfo=None), (start + timedelta(days=1)).replace(tzinfo=None)


def get_world_state(db: Session, user_id: str = DEFAULT_USER_ID) -> WorldStateV1:
    """David's current situation: today's calendar load + open threads.
    Confidence reflects how much of this is actually queried vs assumed."""
    now = datetime.now(timezone.utc)
    day_start, day_end = _today_bounds_naive(now)

    active_calendar_events = 0
    open_threads = 0
    confidence = 1.0

    try:
        active_calendar_events = db.execute(text("""
            SELECT COUNT(*) FROM calendar_event
            WHERE user_id = :uid AND start_time < :day_end AND end_time >= :day_start
        """), {"uid": user_id, "day_start": day_start, "day_end": day_end}).scalar() or 0
    except Exception as e:
        logger.debug(f"[context_snapshot] calendar query failed: {e}")
        confidence = min(confidence, 0.5)

    try:
        open_threads = db.execute(text("""
            SELECT COUNT(*) FROM followup_thread WHERE user_id = :uid AND status = 'open'
        """), {"uid": user_id}).scalar() or 0
    except Exception as e:
        logger.debug(f"[context_snapshot] followup_thread query failed: {e}")
        confidence = min(confidence, 0.5)

    summary = f"{active_calendar_events} calendar event(s) today, {open_threads} open thread(s)."

    return WorldStateV1(
        as_of=now, user_id=user_id, summary=summary,
        active_calendar_events=active_calendar_events, open_threads=open_threads,
        confidence=confidence,
    )


async def get_self_state(user_id: str = DEFAULT_USER_ID) -> SelfStateV1:
    """Sara's own state: current kernel mode/wake-reason (the real published
    state, not a guess) plus open concerns derived from the canonical
    body-state projection's degraded components."""
    from app.services.body_state_projection import get_body_state_projection
    from app.services.kernel import get_state as kernel_get_state

    now = datetime.now(timezone.utc)
    kernel_state = await kernel_get_state(user_id)
    body_state = await get_body_state_projection(user_id)

    open_concerns = [c.impact for c in body_state.components if c.status.value == "degraded" and c.impact]

    return SelfStateV1(
        as_of=now,
        kernel_state=kernel_state.get("state") or "ambient",
        wake_reason=kernel_state.get("wake_reason"),
        focus=None,  # no focus-tracking source exists yet (C7 territory)
        open_concerns=open_concerns,
        confidence=body_state.confidence if body_state.components else 0.5,
    )


def get_relationship_state(db: Session, user_id: str = DEFAULT_USER_ID) -> RelationshipStateV1:
    """Active conversation only, today. `recent_promises` stays empty — there
    is no commitment extractor yet (C3) to source it from honestly, and
    guessing would violate the plan's own 'no unsupported factual assertion'
    quality bar (§9.2)."""
    now = datetime.now(timezone.utc)
    active_conversation_id: Optional[str] = None
    confidence = 0.6  # thin projection — mostly a placeholder until C3/C4 land

    try:
        row = db.execute(text("""
            SELECT id FROM conversation WHERE user_id = :uid ORDER BY updated_at DESC LIMIT 1
        """), {"uid": user_id}).fetchone()
        if row:
            active_conversation_id = str(row[0])
    except Exception as e:
        logger.debug(f"[context_snapshot] conversation query failed: {e}")
        confidence = 0.3

    return RelationshipStateV1(
        as_of=now, user_id=user_id, active_conversation_id=active_conversation_id,
        tone=None, recent_promises=[], confidence=confidence,
    )


async def get_context_snapshot(db: Session, user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """One assembled snapshot — world + self + relationship — for inspection.
    Body state and the intent graph already have their own endpoints; this
    ties the remaining three together the same way."""
    world = get_world_state(db, user_id)
    self_ = await get_self_state(user_id)
    relationship = get_relationship_state(db, user_id)

    return {
        "world_state": world.model_dump(mode="json"),
        "self_state": self_.model_dump(mode="json"),
        "relationship_state": relationship.model_dump(mode="json"),
    }
