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
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.contracts import RelationshipStateV1, SelfStateV1, WorldStateV1
from app.core.config import get_owner_id
from app.core.timezone import render_when

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = get_owner_id()
_TZ = ZoneInfo("America/New_York")


def _today_bounds_naive(now_utc: datetime) -> tuple:
    """Naive ET midnight bounds — for the legacy `timestamp without time zone`
    columns that store ET wall-clock (calendar_event.start_time). NOT valid for
    a timestamptz column; use `_today_bounds_aware` there."""
    from app.core.timezone import naive_local_day_bounds
    return naive_local_day_bounds(now_utc.astimezone(_TZ).date())


def _today_bounds_aware(now_utc: datetime) -> tuple:
    """Aware ET midnight bounds — for `timestamptz` columns (health_metric)."""
    from app.core.timezone import local_day_bounds
    return local_day_bounds(now_utc.astimezone(_TZ).date())


# The metrics `health_today` is expected to carry. A metric missing from
# health_metric is reported as "unavailable", never omitted: an omitted metric
# reads to the model as "nothing worth mentioning", while the truth is "we do
# not know" — and a model handed a gap where a number should be will fill it
# (2026-08-31: seven days of invented HRV). Absence has to be as visible as
# presence.
EXPECTED_HEALTH_METRICS = ("hrv", "resting_hr", "sleep_hours", "steps")


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
        # `world_thread`, not `followup_thread`. These were two separate thread
        # tables and this count read the empty one: on 2026-09-02 the chat context
        # said "open_threads=0" in the same prompt that listed eight active
        # threads, three of them the Laura Weippert ones. world_thread is the one
        # with closers and expiries (ground-truth Phase 2), so it is the one that
        # can be counted honestly.
        open_threads = db.execute(text("""
            SELECT COUNT(*) FROM world_thread
             WHERE user_id = :uid
               AND status IN ('proposed', 'open', 'waiting', 'blocked', 'overdue')
        """), {"uid": user_id}).scalar() or 0
    except Exception as e:
        logger.debug(f"[context_snapshot] world_thread query failed: {e}")
        confidence = min(confidence, 0.5)

    # Titled upcoming events, ALL-DAY INCLUDED. Before 2026-09-01 chat context
    # carried only the count above — no titles, no horizon — so Sara invented
    # upcoming plans from episodic memory (moved the Sept 30 Redstone dinner to
    # "Labor Day weekend", knew nothing of a vacation starting in 2 days: the
    # Salem block is all-day, which the world_brief calendar sweep also skips).
    # start_time/end_time are naive ET wall-clock — compare against naive ET,
    # never NOW() (session TZ is UTC).
    upcoming_events: list = []
    later_events: list = []
    try:
        from app.core.timezone import naive_local_now
        _win_start = naive_local_now()
        _near_end = _win_start + timedelta(days=14)
        _rows = db.execute(text("""
            SELECT title, start_time, end_time, COALESCE(all_day, FALSE) AS all_day
            FROM calendar_event
            WHERE user_id = :uid
              AND COALESCE(end_time, start_time) >= :win_start
              AND start_time < :win_far
            ORDER BY start_time ASC LIMIT 40
        """), {"uid": user_id, "win_start": _win_start,
               "win_far": _win_start + timedelta(days=90)}).fetchall()
        for r in _rows:
            # calendar_event.start_time/end_time are NAIVE ET wall clock — say so
            # rather than letting the renderer guess (invariant 4, one clock).
            if r.all_day:
                if r.end_time is not None and r.end_time.date() != r.start_time.date():
                    _when = (f"{render_when(r.start_time.date())}–"
                             f"{render_when(r.end_time.date())}")
                else:
                    _when = render_when(r.start_time.date())
            else:
                _when = render_when(r.start_time, source_convention="et")
            _entry = f"{_when}: {(r.title or '').strip()}"
            if r.start_time < _near_end:
                if len(upcoming_events) < 12:
                    upcoming_events.append(_entry)
            elif len(later_events) < 5:
                later_events.append(_entry)
    except Exception as e:
        logger.debug(f"[context_snapshot] upcoming calendar query failed: {e}")
        confidence = min(confidence, 0.5)

    summary = f"{active_calendar_events} calendar event(s) today, {open_threads} open thread(s)."
    calendar_horizon = _slice(
        now, "calendar_event+world_thread", confidence,
        active_calendar_events=active_calendar_events, open_threads=open_threads,
        upcoming=upcoming_events, later=later_events,
    )

    # david + home — both already live in unified_context's Redis snapshot;
    # this slice is a read, not a new writer. updated_at comes from the
    # snapshot's OWN last-write time, not our read time — that's what makes
    # staleness (Arc 2.4) detectable at all; if we stamped "now" here, a
    # snapshot that stopped being written 3 days ago would still look fresh
    # forever (the exact meal-state-frozen-since-February failure mode).
    david_slice = home_slice = None
    try:
        from app.services.unified_context import read_snapshot
        snap = await read_snapshot(user_id)
        snap_at = now
        if snap.updated_at:
            try:
                snap_at = datetime.fromisoformat(snap.updated_at)
                if snap_at.tzinfo is None:
                    snap_at = snap_at.replace(tzinfo=timezone.utc)
            except Exception:
                snap_at = now
        david_slice = _slice(
            snap_at, "unified_context", 1.0 if snap.activity_state != "UNKNOWN" else 0.3,
            activity_state=snap.activity_state, interruptibility=snap.interruptibility,
            current_place=snap.current_place, mood=snap.mood,
            hours_since_last_chat=snap.hours_since_last_chat,
        )
        home_slice = _slice(
            snap_at, "unified_context", 1.0,
            home_occupied=snap.home_occupied, active_rooms=snap.active_rooms or [],
            temperature_inside=snap.temperature_inside, temperature_outside=snap.temperature_outside,
            weather_condition=snap.weather_condition,
        )
    except Exception as e:
        logger.debug(f"[context_snapshot] unified_context read failed: {e}")

    # health_today — today's readings, each stamped with when it was taken.
    # updated_at is the newest reading's own recorded_at (source truth), not
    # read time. Every metric in EXPECTED_HEALTH_METRICS appears, present or
    # not: a present one renders as "54 (as of 06:12)", a missing one as
    # "unavailable". Confidence is per-metric coverage, not "a row exists" —
    # a slice with sleep but no HRV is half-known, and must not claim 1.0.
    health_slice = None
    try:
        # Ground-truth plan, Phase 5 §7: the LATEST reading in the last 36 hours,
        # not "today's". HealthKit syncs when the phone feels like it — on
        # 2026-09-02 the night's sleep and HRV existed but landed at 07:22 ET,
        # stamped 06:00, so the 6 AM brief and every chat turn before the sync
        # reported "unavailable" for readings that were about to arrive. A 36-hour
        # window with an explicit measured-at and synced-at is honest about both
        # what was measured and when Sara learned it.
        rows = db.execute(text("""
            SELECT metric_type, value, recorded_at, created_at FROM health_metric
            WHERE user_id = :uid AND recorded_at >= :since
            ORDER BY recorded_at DESC LIMIT 100
        """), {"uid": user_id, "since": now - timedelta(hours=36)}).fetchall()

        by_metric: Dict[str, Any] = {}
        newest = None
        for r in rows:
            if r.metric_type in by_metric:
                continue
            stamp = ""
            if r.recorded_at:
                measured = render_when(r.recorded_at, source_convention="utc")
                stamp = f" (measured {measured}"
                # When the two differ by more than an hour, say so — that gap is
                # the difference between "no reading" and "no sync yet".
                #
                # Guarded on its own: the sync annotation is a nicety, and losing
                # the whole health slice to a malformed created_at would hide
                # every reading behind an empty section. Absence has to be
                # visible (see EXPECTED_HEALTH_METRICS), which means the slice
                # itself must survive anything one column can do to it.
                try:
                    synced_at = getattr(r, "created_at", None)
                    if synced_at and (synced_at - r.recorded_at) > timedelta(hours=1):
                        stamp += f", synced {render_when(synced_at, source_convention='utc')}"
                except TypeError:
                    pass
                stamp += ")"
            by_metric[r.metric_type] = f"{float(r.value):g}{stamp}"
            if r.recorded_at and (newest is None or r.recorded_at > newest):
                newest = r.recorded_at

        # Resolve logical metrics onto whichever stream carries them today —
        # today's HRV arrives as `hrv_morning`, and without this the slice
        # reports "hrv unavailable" while the reading sits one key away.
        from app.services.health_insight_service import METRIC_ALIASES
        for canonical, chain in METRIC_ALIASES.items():
            if canonical in by_metric:
                continue
            for alt in chain:
                if alt in by_metric:
                    by_metric[canonical] = by_metric[alt]
                    break

        present = sum(1 for m in EXPECTED_HEALTH_METRICS if m in by_metric)
        for metric in EXPECTED_HEALTH_METRICS:
            by_metric.setdefault(metric, "unavailable (nothing recorded in the last 36h)")

        health_slice = _slice(
            newest or now, "health_metric",
            round(present / len(EXPECTED_HEALTH_METRICS), 2),
            **by_metric,
        )
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

    # fleet — managed host reachability. updated_at = the OLDEST last_seen_at
    # across hosts (the least-fresh host sets the slice's real freshness —
    # conservative on purpose, so one silently-unpolled host can't hide
    # behind five freshly-polled ones). A host with last_seen_at = NULL has
    # NEVER reported in — that's not "fresh" (found live: all 6 of David's
    # registered hosts have last_status/last_seen_at NULL, and a naive
    # `fresh if no data` fallback would have silently called that healthy —
    # the exact "never observed a heartbeat" gap body_state_projection.py's
    # own comment already warns about). Never-reported hosts count as
    # unreachable AND pin the slice to epoch (maximally stale) rather than now.
    fleet_slice = None
    try:
        hosts = db.execute(text("""
            SELECT name, last_status, last_seen_at FROM managed_host WHERE user_id = :uid
        """), {"uid": user_id}).fetchall()
        never_reported = [h.name for h in hosts if h.last_seen_at is None]
        unreachable = sorted(set(
            [h.name for h in hosts if h.last_status not in ("connected", None)] + never_reported
        ))
        seen_ats = [h.last_seen_at for h in hosts if h.last_seen_at]
        if never_reported and hosts:
            fleet_at = datetime.fromtimestamp(0, tz=timezone.utc)
            fleet_confidence = 0.0
        elif seen_ats:
            fleet_at = min(seen_ats)
            fleet_confidence = 1.0
        else:
            fleet_at, fleet_confidence = now, 0.5  # no hosts registered at all
        fleet_slice = _slice(fleet_at, "managed_host", fleet_confidence,
                              host_count=len(hosts), unreachable=unreachable,
                              never_reported=never_reported)
    except Exception as e:
        logger.debug(f"[context_snapshot] managed_host query failed: {e}")

    # expectations (Arc 4.1) — today's expected shape, from daily_rhythm +
    # training_day + calendar_event. A prediction, not an observation: this
    # is what "ambient wakes evaluate error-against-expectation" reads.
    # updated_at is now (recomputed live each call, cheap DB reads only) —
    # confidence reflects how much of the day is actually predictable yet,
    # not staleness (daily_rhythm itself decays its own confidence).
    expectations_slice = None
    try:
        from app.services.daily_rhythm import (
            build_rhythm_summary, get_upcoming_rhythm_window, stated_rhythm_keys,
        )
        from app.services.training_day import is_training_day

        # Follow-up plan §2: a learned median is not printed next to a stated
        # fact that answers the same question. On 2026-09-02 this slice rendered
        # "leave ~6:24" one line below "leaves for work 7am".
        rhythm_summary = build_rhythm_summary(
            db, user_id, exclude_keys=await stated_rhythm_keys(user_id))
        upcoming = get_upcoming_rhythm_window(db, user_id, within_minutes=180)
        training = is_training_day(db, user_id, now.astimezone(_TZ).date())

        # Follow-up plan §5: an all-day event has no start time. Its
        # `start_time` is midnight because a date has to be stored in a
        # timestamp column, and reading that as a clock time is how the
        # expectations slice announced "next_meeting_at=Thu Sep 3, 12:00 AM ET"
        # for a whole-day trip to Salem. All-day rows are excluded from
        # `next_meeting` entirely and reported separately, without a time.
        upcoming_rows = db.execute(text("""
            SELECT title, start_time, COALESCE(all_day, FALSE) AS all_day
            FROM calendar_event
            WHERE user_id = :uid AND start_time > :now_naive
            ORDER BY start_time ASC LIMIT 10
        """), {"uid": user_id, "now_naive": now.astimezone(_TZ).replace(tzinfo=None)}).fetchall()

        next_meeting_row = next((r for r in upcoming_rows if not r.all_day), None)
        next_all_day_row = next((r for r in upcoming_rows if r.all_day), None)

        exp_data = {}
        if rhythm_summary:
            exp_data["rhythm_summary"] = rhythm_summary
        if upcoming:
            exp_data["next_rhythm_window"] = upcoming["label"]
            exp_data["next_rhythm_minutes_away"] = upcoming["minutes_until"]
            exp_data["next_rhythm_confidence"] = upcoming["confidence"]
        exp_data["is_training_day"] = bool(training.get("is_training_day"))
        if next_meeting_row:
            exp_data["next_meeting"] = next_meeting_row.title
            exp_data["next_meeting_at"] = render_when(
                next_meeting_row.start_time, source_convention="et")
        if next_all_day_row:
            exp_data["next_event"] = (
                f"{(next_all_day_row.title or '').strip()} — "
                f"{render_when(next_all_day_row.start_time, source_convention='et', all_day=True)}"
            )

        # Confidence: 0 with nothing predictable yet (cold start — no learned
        # rhythm, no training-day signal, no calendar), scaling up with how
        # many of the expected-day components actually resolved.
        signal_count = sum([
            bool(rhythm_summary), bool(upcoming), training.get("is_training_day") is not None,
            bool(next_meeting_row or next_all_day_row),
        ])
        exp_confidence = min(1.0, signal_count / 3.0) if signal_count else 0.0

        expectations_slice = _slice(
            now, "daily_rhythm+training_day+calendar_event", exp_confidence, **exp_data,
        )
    except Exception as e:
        logger.debug(f"[context_snapshot] expectations slice failed: {e}")

    world = WorldStateV1(
        as_of=now, user_id=user_id, summary=summary,
        active_calendar_events=active_calendar_events, open_threads=open_threads,
        confidence=confidence,
        david=david_slice, home=home_slice, calendar_horizon=calendar_horizon,
        health_today=health_slice, work=work_slice, fleet=fleet_slice,
        expectations=expectations_slice,
    )
    try:
        await check_staleness(world)
    except Exception as e:
        logger.debug(f"[context_snapshot] staleness check failed: {e}")
    return world


# Arc 2.4 — a slice whose updated_at exceeds its freshness budget is a
# prediction error ("I expected this to be current, it isn't"), not silent
# staleness. calendar_horizon and work are live queries every call, so they
# have no meaningful staleness budget — they're either right now or errored.
_FRESHNESS_BUDGET = {
    "david": timedelta(hours=2),
    "home": timedelta(hours=2),
    "health_today": timedelta(hours=24),
    "fleet": timedelta(hours=24),
}


async def check_staleness(world: WorldStateV1) -> list:
    """Emit a PREDICTION_VIOLATED event for every slice past its freshness
    budget. Returns the list of stale slice names (for callers/tests that
    want the result without going through the event bus)."""
    from app.services.event_bus import emit_event, EventType

    now = datetime.now(timezone.utc)
    stale = []
    for slice_name, budget in _FRESHNESS_BUDGET.items():
        s = getattr(world, slice_name, None)
        if s is None:
            continue
        age = now - s.updated_at
        if age > budget:
            stale.append(slice_name)
            try:
                await emit_event(
                    EventType.PREDICTION_VIOLATED,
                    user_id=world.user_id,
                    payload={
                        "kind": "world_state_slice_stale",
                        "slice": slice_name,
                        "source": s.source,
                        "age_hours": round(age.total_seconds() / 3600, 1),
                        "budget_hours": budget.total_seconds() / 3600,
                    },
                    source="context_snapshot.check_staleness",
                )
            except Exception as e:
                logger.debug(f"[context_snapshot] staleness event emit failed for {slice_name}: {e}")
    return stale


async def get_self_state(user_id: str = DEFAULT_USER_ID, db: Optional[Session] = None) -> SelfStateV1:
    """Sara's own state: current kernel mode/wake-reason (the real published
    state, not a guess) plus open concerns derived from the canonical
    body-state projection's degraded components.

    `db` (Arc 4.2, optional so existing callers that only want kernel/body
    state keep working unchanged) reads the rolling self-story —
    sara_journal_service uses a sync Session, so this must be the same kind
    of Session get_context_snapshot's caller already has, not a new
    connection opened here."""
    from app.services.body_state_projection import get_body_state_projection
    from app.services.kernel import get_state as kernel_get_state

    # Presence-latency follow-up (item 1.3 Session 1, 2026-07-31): unlike
    # world/self/relationship above, these two take only `user_id` — neither
    # touches the shared sync `db`, so gathering them has none of that risk.
    import asyncio
    import time as _t
    now = datetime.now(timezone.utc)
    _t0 = _t.monotonic()
    kernel_state, body_state = await asyncio.gather(kernel_get_state(user_id), get_body_state_projection(user_id))
    _t1 = _t.monotonic()
    logger.info(f"⏱️ [self-state-timing] kernel_state+body_state_projection(parallel)={_t1-_t0:.2f}s")

    open_concerns = [c.impact for c in body_state.components if c.status.value == "degraded" and c.impact]

    self_story = None
    if db is not None:
        try:
            from app.services.sara_journal_service import sara_journal
            self_story = await sara_journal.get_self_story(db, user_id)
        except Exception as e:
            logger.debug(f"[context_snapshot] self_story read failed: {e}")

    return SelfStateV1(
        as_of=now,
        kernel_state=kernel_state.get("state") or "ambient",
        wake_reason=kernel_state.get("wake_reason"),
        focus=None,  # no focus-tracking source exists yet (C7 territory)
        open_concerns=open_concerns,
        confidence=body_state.confidence if body_state.components else 0.5,
        self_story=self_story,
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

    # Arc 4.5: read the latest theory-of-david row directly rather than
    # through sara_journal_service.get_theory_of_david — that method is
    # `async def` (matching write_theory_of_david's shape) but this
    # function is sync, and db here is the same sync Session that method
    # expects, so the tiny query is inlined instead of introducing an
    # async/sync collision into this function's signature.
    theory_of_david: Optional[str] = None
    try:
        row = db.execute(text("""
            SELECT content FROM sara_journal
            WHERE user_id = :uid AND entry_type = 'theory_of_david'
            ORDER BY created_at DESC LIMIT 1
        """), {"uid": user_id}).fetchone()
        if row:
            theory_of_david = row.content
    except Exception as e:
        logger.debug(f"[context_snapshot] theory_of_david query failed: {e}")

    return RelationshipStateV1(
        as_of=now, user_id=user_id, active_conversation_id=active_conversation_id,
        tone=None, recent_promises=[], confidence=confidence,
        theory_of_david=theory_of_david,
    )


async def get_context_snapshot(db: Session, user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """One assembled snapshot — world + self + relationship — for inspection.
    Body state and the intent graph already have their own endpoints; this
    ties the remaining three together the same way.

    Presence-latency follow-up (item 1.3 Session 1, 2026-07-31): considered
    gathering world_state/self_state/relationship_state in parallel, but all
    three take the same sync `db: Session` — concurrent use of one
    SQLAlchemy sync Session across coroutines is not something the library
    supports safely, and measured (see below) the sequential cost here is
    already small (~0.1-0.3s combined) next to memory_recall's ~2.25s.
    Not worth the correctness risk for that little upside — parallelized
    memory_recall against this sequence instead, at the call site in
    main_simple.py, since memory_recall opens its own sessions."""
    import time as _t
    _t0 = _t.monotonic()
    world = await get_world_state(db, user_id)
    _t1 = _t.monotonic()
    self_ = await get_self_state(user_id, db=db)
    _t2 = _t.monotonic()
    relationship = get_relationship_state(db, user_id)
    _t3 = _t.monotonic()
    logger.info(
        f"⏱️ [context-snapshot-timing] world_state={_t1-_t0:.2f}s "
        f"self_state={_t2-_t1:.2f}s relationship_state={_t3-_t2:.2f}s"
    )

    return {
        "world_state": world.model_dump(mode="json"),
        "self_state": self_.model_dump(mode="json"),
        "relationship_state": relationship.model_dump(mode="json"),
    }


_SNAPSHOT_CACHE_TTL_SEC = 20


def _snapshot_cache_key(user_id: str) -> str:
    return f"sara:context_snapshot:{user_id}"


async def get_context_snapshot_cached(db: Session, user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """Presence-latency follow-up (item 1.3 Session 1, 2026-07-31): the
    architectural direction (a chat turn's assembly cost should collapse to
    recall + thread + a read, not a from-scratch build every turn) applied
    to the one piece of get_context_snapshot's output that's genuinely
    message-independent — world/self/relationship state changes on its own
    clock (calendar, health, kernel mode, body health), never on what David
    just typed. `memory_recall`/`extended_signals`' `pkg` sub-fetch stay
    live per-turn on purpose; they're query-dependent.

    Short TTL (20s), not event-driven invalidation — same pragmatic
    precedent as world_brief.get_rendered_brief's 2-minute cache. A chat
    reply reflecting world-state up to 20s stale is a fully reasonable
    trade for skipping a rebuild on every single turn of a fast back-and-
    forth conversation; a real kernel-maintained warm artifact updated on
    genuine world-state-change events would be more precise but is a
    larger, separate piece of work than this pass's scope."""
    try:
        from app.services.unified_context import _get_redis
        r = await _get_redis()
        cached = await r.get(_snapshot_cache_key(user_id))
        if cached:
            import json as _json
            return _json.loads(cached if isinstance(cached, str) else cached.decode("utf-8"))
    except Exception as e:
        logger.debug(f"[context_snapshot] cache read skipped: {e}")

    snapshot = await get_context_snapshot(db, user_id)

    try:
        from app.services.unified_context import _get_redis
        import json as _json
        r = await _get_redis()
        await r.set(_snapshot_cache_key(user_id), _json.dumps(snapshot), ex=_SNAPSHOT_CACHE_TTL_SEC)
    except Exception as e:
        logger.debug(f"[context_snapshot] cache write skipped: {e}")

    return snapshot


async def get_extended_signals(
    db: Session, user_id: str = DEFAULT_USER_ID, message: str = "",
    domain_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """Arc 2.3 gap-closing (2026-07-29): the categories the side-by-side
    comparison log measured present in the old ~19-source assembly and
    missing from the 4-source shadow — pkg, daily_brief, journal, patterns,
    device, and Sara's own emotional tone. Calls the exact same underlying
    services the old assembly's fetchers call (not a re-implementation), so
    there's one source of truth per category, just two callers of it during
    the overlap window. Best-effort per category — one failing must never
    block the others or the turn.

    Item 1.3 ruling 2 (2026-07-31): added `lessons` — the one legacy
    fetcher (`_fetch_lessons` in main_simple.py) with a real side effect
    (recording which lessons were shown, feeding the effectiveness/recall-
    testing loop) and no home in the new path until now. Ported here
    rather than left to run twice: same lesson_injection_service call the
    legacy fetcher made, same self-contained side-effect-free computation
    (the actual `record_lesson_application` write still happens in
    main_simple.py's post-response processing, unchanged — this only
    supplies the lesson_ids that call needs). Returns `lesson_ids`
    alongside the text fields so the caller can wire up that recording.
    """
    import asyncio

    async def _pkg() -> Optional[str]:
        try:
            from app.services.memory_recall import recall_facts_prose
            # Presence-latency follow-up, ruling 1 (2026-07-31): this is
            # the one recall_facts_prose caller inside a real, live chat
            # turn — explicit "embedding" (the fast GPU host) rather than
            # the default "embedding_cognition", so it never queues behind
            # background cognition's own embedding traffic.
            return await recall_facts_prose(query=message, user_id=user_id, embedding_capability="embedding")
        except Exception as e:
            logger.debug(f"[extended_signals] pkg failed: {e}")
            return None

    async def _daily_brief() -> Optional[str]:
        try:
            from app.services.daily_brief import daily_brief_service
            return await daily_brief_service.get_compiled_brief(user_id)
        except Exception as e:
            logger.debug(f"[extended_signals] daily_brief failed: {e}")
            return None

    async def _journal() -> Optional[str]:
        try:
            from app.services.sara_journal_service import sara_journal
            return await sara_journal.get_entries_for_conversation_context(
                db=db, user_id=user_id, max_entries=3
            )
        except Exception as e:
            logger.debug(f"[extended_signals] journal failed: {e}")
            return None

    async def _patterns() -> Optional[str]:
        try:
            rows = db.execute(text("""
                SELECT description, confidence FROM behavioral_pattern
                WHERE user_id = :uid AND status = 'active'
                ORDER BY confidence DESC LIMIT 5
            """), {"uid": user_id}).fetchall()
            if not rows:
                return None
            return "; ".join(f"{r.description} ({r.confidence:.0%})" for r in rows)
        except Exception as e:
            logger.debug(f"[extended_signals] patterns failed: {e}")
            return None

    async def _device() -> Optional[str]:
        try:
            from app.services.device_orchestrator import device_orchestrator
            return await device_orchestrator.get_device_context_for_chat(db, user_id)
        except Exception as e:
            logger.debug(f"[extended_signals] device failed: {e}")
            return None

    async def _emotional_tone() -> Optional[str]:
        try:
            from app.services.working_memory import read_memory
            wm = await read_memory(user_id)
            if wm and wm.sara_emotional_tone:
                intensity = getattr(wm, "sara_emotional_intensity", None) or 0.5
                return f"{wm.sara_emotional_tone} ({intensity:.2f})"
        except Exception as e:
            logger.debug(f"[extended_signals] emotional_tone failed: {e}")
        return None

    async def _lessons() -> tuple:
        try:
            from app.core.health_state import STARTUP_HEALTH
            es = (STARTUP_HEALTH.get("embedding_service") or {}).get("status")
            if es != "healthy":
                return None, []
        except Exception:
            pass  # health snapshot not available in every context this runs from
        try:
            from app.services.lesson_injection_service import lesson_injection_service
            return await asyncio.wait_for(
                lesson_injection_service.get_lessons_for_injection(
                    db=db, query=message, domain_hint=domain_hint, limit=3,
                    embedding_capability="embedding",
                ), timeout=2.5
            )
        except Exception as e:
            logger.debug(f"[extended_signals] lessons failed: {e}")
            return None, []

    # Presence-latency follow-up (item 1.3 Session 1, 2026-07-31): these
    # already run in parallel, so total time = the slowest one, not the
    # sum — timed individually to find which one that is (measured 0.45s-
    # 8s total across real turns, wide enough variance to suspect a shared
    # external dependency, not a fixed cost).
    import time as _t

    async def _timed(name, coro):
        t0 = _t.monotonic()
        result = await coro
        logger.info(f"⏱️ [extended-signals-timing] {name}={_t.monotonic()-t0:.2f}s")
        return result

    pkg, brief, journal, patterns, device, tone, lessons_result = await asyncio.gather(
        _timed("pkg", _pkg()), _timed("daily_brief", _daily_brief()),
        _timed("journal", _journal()), _timed("patterns", _patterns()),
        _timed("device", _device()), _timed("emotional_tone", _emotional_tone()),
        _timed("lessons", _lessons()),
    )
    lessons_text, lesson_ids = lessons_result if isinstance(lessons_result, tuple) else (None, [])

    def _s(v: Any) -> Optional[str]:
        return v if isinstance(v, str) and v.strip() else None

    return {
        "pkg": _s(pkg), "daily_brief": _s(brief), "journal": _s(journal),
        "patterns": _s(patterns), "device": _s(device), "emotional_tone": _s(tone),
        "lessons": _s(lessons_text), "lesson_ids": lesson_ids or [],
    }


_PKG_HEALTH_LINE_RE = re.compile(r"^\s*-\s*David's ([^:]+):", re.IGNORECASE)


def suppress_pkg_health_conflicts(pkg_text: str, health_data: Dict[str, Any]) -> str:
    """Drop PKG health lines about a metric `health_metric` already answered
    for today. Raw wins, always — a graph fact is at best a paraphrase of a
    measurement and at worst (pre-Phase-0) a number Sara invented, and two
    numbers for the same metric side by side is how the model ends up choosing
    the wrong one. Only genuinely conflicting lines go; everything else stays.
    """
    if not pkg_text or not health_data:
        return pkg_text

    from app.services.personal_knowledge_graph import _normalize_metric

    # Metric names we have a real reading for today (not "unavailable").
    answered = {
        _normalize_metric(k) for k, v in health_data.items()
        if not (isinstance(v, str) and v.startswith("unavailable"))
    }
    # health_metric's own naming vs. what the extractor tends to write.
    aliases = {
        "hrv": {"hrv", "heart rate variability"},
        "resting hr": {"resting hr", "resting heart rate", "rhr"},
        "sleep hours": {"sleep hours", "sleep duration", "sleep quality", "sleep"},
        "steps": {"steps", "step count", "daily steps"},
        "weight": {"weight", "body weight", "bodyweight"},
        "heart rate": {"heart rate", "hr", "pulse"},
    }
    blocked = set()
    for metric in answered:
        blocked |= aliases.get(metric, {metric})

    kept = []
    for line in pkg_text.split("\n"):
        m = _PKG_HEALTH_LINE_RE.match(line)
        if m and _normalize_metric(m.group(1)) in blocked:
            logger.debug(f"[context_snapshot] suppressed PKG health line (raw wins): {line.strip()[:80]}")
            continue
        kept.append(line)
    return "\n".join(kept)


def _clip_to_paragraph(text_: str, limit: int) -> str:
    """Cut at a paragraph boundary, never mid-word.

    `[:1500]` on the stable layer sliced a sentence in half; a model reading a
    truncated clause completes it, and what it completes with is invention.
    """
    text_ = (text_ or "").strip()
    if len(text_) <= limit:
        return text_
    head = text_[:limit]
    for boundary in ("\n\n", "\n", ". "):
        cut = head.rfind(boundary)
        if cut > limit // 2:
            return head[:cut].rstrip() + ("." if boundary == ". " else "")
    return head.rsplit(" ", 1)[0] + "…"


def _slice_is_dead(slice_name: str, data: Dict[str, Any]) -> bool:
    """True when a slice has nothing worth a line in the prompt."""
    if slice_name == "fleet":
        # A host that has NEVER reported in is not an unreachable host; it is a
        # registry row. When every registered host is in that state — which was
        # true of all six for weeks — the slice is describing the registry, not
        # the world, and saying "6 hosts unreachable" every turn is a lie of
        # emphasis. Only report the fleet when something has actually reported.
        host_count = int(data.get("host_count") or 0)
        never_reported = data.get("never_reported") or []
        return host_count == 0 or len(never_reported) >= host_count
    return False


_NOISE_PATTERN_RE = re.compile(r"(lock|light|door)[\w_]*\s*(cycle|routine)?", re.IGNORECASE)


def _patterns_are_noise(patterns: str) -> bool:
    """True when every learned pattern is a lock/light cycle at ~100%.

    Those are the house behaving normally. Reported as "patterns", they read as
    insight into David and crowd out the ones that are.
    """
    text_ = (patterns or "").strip()
    if not text_:
        return True
    entries = [e.strip() for e in re.split(r"[;\n]", text_) if e.strip()]
    if not entries:
        return True
    return all(
        _NOISE_PATTERN_RE.search(e) and re.search(r"\b(9\d|100)\s*%", e)
        for e in entries
    )



# Which budget allotment each rendered block draws from. The renderer emits a
# flat list of lines; this maps a line's leading header back to its section so
# the budget can charge it correctly.
_SECTION_HEADERS = (
    ("### Calendar", "calendar"),
    ("### Relevant memory", "memory"),
    ("## Today's Brief", "brief"),
    ("## Knowledge Graph", "brief"),
    ("## Recent Journal", "brief"),
    ("### What you understand about David", "brief"),
    ("## Lessons", "lessons"),
    ("## Workspace", "device"),
)


def _split_sections(lines: List[str]) -> List[tuple]:
    """Group rendered lines into (budget_section, text) blocks, in order."""
    blocks: List[tuple] = []
    current_name = "brief"
    current: List[str] = []
    for line in lines:
        stripped = line.strip()
        matched = next((n for h, n in _SECTION_HEADERS if stripped.startswith(h)), None)
        if matched:
            if current:
                blocks.append((current_name, "\n".join(current)))
            current_name, current = matched, [line]
        else:
            current.append(line)
    if current:
        blocks.append((current_name, "\n".join(current)))
    return blocks


def render_engaged_context(
    context: Dict[str, Any], open_intents: int, recall_traces: list,
    extended: Optional[Dict[str, Any]] = None,
    workspace_ctx: Optional[str] = None,
) -> str:
    """Render kernel.engaged_turn()'s assembled context (world/self/
    relationship + recall) into the markdown block chat's system prompt
    would inject — Arc 2.3's actual 4-source replacement for the ~19-source
    budget assembly, made comparable to it instead of just a shadow dict.

    Deliberately dense but plain: one block per slice, only non-null data,
    no editorializing — matches how the other injected context blocks in
    main_simple.py read (## headers + short lines).

    `extended` (get_extended_signals) folds in the categories the Arc 2.3
    comparison log measured present in the old assembly and missing here —
    pkg/daily_brief/journal/patterns/device/emotional_tone/lessons —
    closing the measured gap before the flag flips, not after.

    `workspace_ctx` (item 1.3 ruling 2, 2026-07-31): the Desktop Jarvis
    workspace-scene string main_simple.py builds straight from the
    request (active scene, open windows) — cheap, synchronous, request-
    scoped, so it's passed in rather than re-fetched here."""
    lines = ["## Current Situation (world_state + self_state + relationship_state)"]

    world = context.get("world_state") or {}
    for slice_name in ("david", "home", "calendar_horizon", "health_today", "work", "fleet", "expectations"):
        s = world.get(slice_name)
        if not s or not s.get("data"):
            continue
        if _slice_is_dead(slice_name, s["data"]):
            # Ground-truth plan, Phase 5 §8. A slice with nothing to say is worse
            # than absent: the fleet line reported "6 hosts unreachable" on every
            # turn for weeks when no agents were ever enrolled, and Sara never
            # mentioned it because it was noise — it just cost tokens and made
            # everything around it look equally ignorable.
            continue
        data_str = ", ".join(
            f"{k}={v}" for k, v in s["data"].items()
            if v not in (None, [], "") and k not in ("upcoming", "later")
        )
        if data_str:
            lines.append(f"- **{slice_name}** ({s.get('source', '?')}, confidence={s.get('confidence', '?')}): {data_str}")

    # Verified calendar block (2026-09-01): the ONLY authoritative source for
    # upcoming plans in a chat turn. Rendered as explicit dated lines so the
    # model quotes instead of reconstructing from memory.
    _cal = (world.get("calendar_horizon") or {}).get("data") or {}
    lines.append("### Calendar — verified upcoming (next 14 days)")
    if _cal.get("upcoming"):
        for _e in _cal["upcoming"]:
            lines.append(f"  - {_e}")
    else:
        lines.append("  - nothing on the calendar in the next 14 days")
    if _cal.get("later"):
        lines.append("  further out: " + "; ".join(_cal["later"]))

    self_state = context.get("self_state") or {}
    if self_state.get("kernel_state"):
        lines.append(f"- **self**: kernel_state={self_state['kernel_state']}")
    for concern in (self_state.get("open_concerns") or [])[:5]:
        lines.append(f"  - concern: {concern}")
    # The self-story is deliberately NOT injected (ground-truth plan, Phase 5 §5).
    # `reflection/agent.py` regenerated it every four hours from the deliberation
    # journal — ~130 "staying quiet" lines a day — and it drifted into things like
    # "cowardice wearing a mask… I am terrified…" on a day nothing had happened.
    # Sara then read that back as fact about herself on every single chat turn.
    # The row is still written for the UI; it is no longer prompt input.

    relationship = context.get("relationship_state") or {}
    if relationship.get("active_conversation_id"):
        lines.append(f"- **relationship**: active_conversation={relationship['active_conversation_id']}")
    if relationship.get("theory_of_david"):
        # Arc 4.5: same "every context in every state" treatment as
        # self-story — its own prose block, not a bullet.
        lines.append(f"\n### What you understand about David\n{relationship['theory_of_david']}")

    lines.append(f"- **open_intents**: {open_intents}")

    if recall_traces:
        lines.append("\n### Relevant memory (memory.recall)")
        for t in recall_traces[:5]:
            lines.append(f"- [{t.get('kind')}, {t.get('confidence')}] {(t.get('text') or '')[:150]}")

    if extended:
        if extended.get("emotional_tone"):
            lines.append(f"- **sara_feels**: {extended['emotional_tone']}")
        if extended.get("patterns") and not _patterns_are_noise(extended["patterns"]):
            lines.append(f"- **patterns**: {extended['patterns']}")
        if extended.get("device"):
            lines.append(f"\n{extended['device']}")
        if extended.get("daily_brief"):
            lines.append(f"\n## Today's Brief\n{_clip_to_paragraph(extended['daily_brief'], 1500)}")
        if extended.get("pkg"):
            pkg_text = suppress_pkg_health_conflicts(
                extended["pkg"], (world.get("health_today") or {}).get("data") or {}
            )
            if pkg_text.strip():
                lines.append(f"\n## Knowledge Graph\n{pkg_text[:1000]}")
        if extended.get("journal"):
            lines.append(f"\n## Recent Journal\n{_clip_to_paragraph(extended['journal'], 1000)}")
        if extended.get("lessons"):
            lines.append(f"\n{extended['lessons']}")

    if workspace_ctx:
        lines.append(workspace_ctx)

    # Ground-truth plan, Phase 5 §4: one hard cap, with a stated share per
    # section. Before this the block was assembled and injected whole — 7-8k
    # uncacheable tokens a turn, growing with every new slice anyone added.
    from app.services.context_budget import SectionBudget

    budget = SectionBudget()
    for name, block in _split_sections(lines):
        budget.add(name, block)
    return budget.render()
