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


def _slice(now, source: str, confidence: float, **data) -> "WorldStateSliceV1":
    from app.schemas.contracts import WorldStateSliceV1
    return WorldStateSliceV1(updated_at=now, source=source, confidence=confidence, data=data)


async def get_world_state(db: Session, user_id: str = DEFAULT_USER_ID) -> WorldStateV1:
    """David's current situation, as six independently-stamped slices (Arc
    2.1) — david, home, calendar_horizon, health_today, work, fleet. Each
    slice is read from an existing source and fails independently: a broken
    fleet query degrades fleet.confidence, not calendar_horizon's."""
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
    calendar_horizon = _slice(
        now, "calendar_event+followup_thread", confidence,
        active_calendar_events=active_calendar_events, open_threads=open_threads,
    )

    # david + home — both already live in unified_context's Redis snapshot;
    # this slice is a read, not a new writer.
    david_slice = home_slice = None
    try:
        from app.services.unified_context import read_snapshot
        snap = await read_snapshot(user_id)
        david_slice = _slice(
            now, "unified_context", 1.0 if snap.activity_state != "UNKNOWN" else 0.3,
            activity_state=snap.activity_state, interruptibility=snap.interruptibility,
            current_place=snap.current_place, mood=snap.mood,
            hours_since_last_chat=snap.hours_since_last_chat,
        )
        home_slice = _slice(
            now, "unified_context", 1.0,
            home_occupied=snap.home_occupied, active_rooms=snap.active_rooms or [],
            temperature_inside=snap.temperature_inside, temperature_outside=snap.temperature_outside,
            weather_condition=snap.weather_condition,
        )
    except Exception as e:
        logger.debug(f"[context_snapshot] unified_context read failed: {e}")

    # health_today — most recent daily recovery snapshot, if any.
    health_slice = None
    try:
        row = db.execute(text("""
            SELECT metric_type, value, recorded_at FROM health_metric
            WHERE user_id = :uid AND recorded_at >= :day_start
            ORDER BY recorded_at DESC LIMIT 20
        """), {"uid": user_id, "day_start": day_start}).fetchall()
        by_metric = {}
        for r in row:
            by_metric.setdefault(r.metric_type, float(r.value))
        health_slice = _slice(now, "health_metric", 1.0 if row else 0.4, **by_metric)
    except Exception as e:
        logger.debug(f"[context_snapshot] health_metric query failed: {e}")

    # work — email needing reply + agent tasks in flight.
    work_slice = None
    try:
        needs_reply = db.execute(text("""
            SELECT COUNT(*) FROM email
            WHERE user_id = :uid AND action_required = TRUE AND is_read = FALSE
        """), {"uid": user_id}).scalar() or 0
        in_flight = db.execute(text("""
            SELECT COUNT(*) FROM background_task
            WHERE user_id = :uid AND status IN ('pending', 'running')
        """), {"uid": user_id}).scalar() or 0
        work_slice = _slice(now, "email+background_task", 1.0,
                             emails_needing_reply=int(needs_reply), tasks_in_flight=int(in_flight))
    except Exception as e:
        logger.debug(f"[context_snapshot] work query failed: {e}")
        work_slice = _slice(now, "email+background_task", 0.3)

    # fleet — managed host reachability.
    fleet_slice = None
    try:
        hosts = db.execute(text("""
            SELECT name, last_status FROM managed_host WHERE user_id = :uid
        """), {"uid": user_id}).fetchall()
        unreachable = [h.name for h in hosts if h.last_status not in ("connected", None)]
        fleet_slice = _slice(now, "managed_host", 1.0 if hosts else 0.5,
                              host_count=len(hosts), unreachable=unreachable)
    except Exception as e:
        logger.debug(f"[context_snapshot] managed_host query failed: {e}")

    return WorldStateV1(
        as_of=now, user_id=user_id, summary=summary,
        active_calendar_events=active_calendar_events, open_threads=open_threads,
        confidence=confidence,
        david=david_slice, home=home_slice, calendar_horizon=calendar_horizon,
        health_today=health_slice, work=work_slice, fleet=fleet_slice,
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
    world = await get_world_state(db, user_id)
    self_ = await get_self_state(user_id)
    relationship = get_relationship_state(db, user_id)

    return {
        "world_state": world.model_dump(mode="json"),
        "self_state": self_.model_dump(mode="json"),
        "relationship_state": relationship.model_dump(mode="json"),
    }
