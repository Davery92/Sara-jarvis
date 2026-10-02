"""`FitnessStateV1`: the one deterministic projection every consumer reads.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 17. This is the layer that turns owned
rows into the typed state the UI, the chat tools, the world brief and the
coach review all consume. Before it, each of those computed its own numbers
and could disagree.

Three properties it has to keep:

1. **No LLM, ever.** Every number here is arithmetic over records. The model
   interprets this state; it never produces any of it.
2. **A dependency failure is `DEGRADED`, not a smaller state.** Returning
   fewer metrics because a query failed would be indistinguishable from the
   athlete having less data, and a review would then reason about an absence
   that is really an outage. `degraded_dependencies` names what failed.
3. **Correctness survives Redis.** The cache is keyed on a data-revision
   fingerprint, so a backdated correction changes the key. A missed
   invalidation bounds staleness to the TTL rather than being unbounded, and
   `fresh=True` bypasses the cache entirely — which is what a review input
   uses, because an immutable audit must never come from a cache.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.fitness_coach import (
    ANALYTICS_VERSION,
    FITNESS_STATE_SCHEMA_VERSION,
    FitnessStateV1,
    Freshness,
    MetricGroup,
    Period,
    StateSection,
    Unit,
)
from app.services.fitness import analytics
from app.services.fitness.data_access import (
    _require_user,
    athlete_zone,
    data_revision,
    load_food_days,
    load_sets,
    load_training_sessions,
)

logger = logging.getLogger(__name__)

#: Short, because a backdated correction that missed its invalidation stays
#: wrong for exactly this long. Long enough that a dashboard's several reads
#: in one sitting hit the cache.
CACHE_TTL_SECONDS = 120

#: Cache key version. Bumped when the state's *shape* changes, so a
#: deployment cannot serve a previous shape to a reader expecting this one.
CACHE_KEY_VERSION = 1

ALL_SECTIONS = frozenset(StateSection)


def build_fitness_state(
    db: Session,
    user_id: str,
    as_of: Optional[datetime] = None,
    *,
    period_end: Optional[date] = None,
    sections: Optional[Sequence[StateSection]] = None,
    span: int = 7,
    fresh: bool = False,
    redis_client: Any = None,
) -> FitnessStateV1:
    """The athlete's deterministic state.

    `period_end` is **exclusive** and athlete-local. A completed review
    passes the athlete's today, so the current incomplete day is never
    averaged in.

    `sections` narrows the work — a chat capsule needs goal, targets and
    today, not a 28-day training breakdown. Narrowing changes which sections
    are present, never what a present section says.

    `fresh=True` skips the cache. Review inputs use it: a stored audit has to
    be reproducible from records, and one assembled from a cache could not be.
    """
    uid = _require_user(user_id)
    wanted: Set[StateSection] = set(sections) if sections else set(ALL_SECTIONS)

    timezone_name, profile = _profile(db, uid)
    tz = athlete_zone(timezone_name)
    moment = as_of or datetime.now(timezone.utc)
    local_today = moment.astimezone(tz).date()
    end = period_end or local_today

    revision = _safe(db, uid, "data_revision", lambda: data_revision(db, uid), "")
    cache_key = _cache_key(uid, end, timezone_name, span, wanted, revision)

    if not fresh and redis_client is not None:
        cached = _read_cache(redis_client, cache_key)
        if cached is not None:
            return cached

    degraded: List[str] = []
    groups: Dict[StateSection, MetricGroup] = {}

    goals = _safe(db, uid, "goals", lambda: _goals(db, uid, end), [], degraded)
    limitations = _safe(
        db, uid, "limitations", lambda: _limitations(db, uid, end), [], degraded,
    )
    targets = _safe(db, uid, "targets", lambda: _targets(db, uid, end), None, degraded)
    program = _safe(db, uid, "program", lambda: _program(db, uid, end), {}, degraded)

    if StateSection.WEIGHT in wanted:
        groups[StateSection.WEIGHT] = _safe(
            db, uid, "weight",
            lambda: _weight_group(db, uid, end, timezone_name, goals, span),
            MetricGroup(section=StateSection.WEIGHT), degraded,
        )
    if StateSection.NUTRITION in wanted:
        groups[StateSection.NUTRITION] = _safe(
            db, uid, "nutrition",
            lambda: _nutrition_group(db, uid, end, timezone_name, span),
            MetricGroup(section=StateSection.NUTRITION), degraded,
        )
    if StateSection.SLEEP in wanted:
        groups[StateSection.SLEEP] = _safe(
            db, uid, "sleep",
            lambda: _sleep_group(db, uid, end, timezone_name, targets, span),
            MetricGroup(section=StateSection.SLEEP), degraded,
        )
    if StateSection.RECOVERY in wanted:
        groups[StateSection.RECOVERY] = _safe(
            db, uid, "recovery",
            lambda: _recovery_group(db, uid, end, span),
            MetricGroup(section=StateSection.RECOVERY), degraded,
        )
    if StateSection.TRAINING in wanted:
        groups[StateSection.TRAINING] = _safe(
            db, uid, "training",
            lambda: _training_group(db, uid, end, timezone_name, span),
            MetricGroup(section=StateSection.TRAINING), degraded,
        )
    if StateSection.PAIN in wanted:
        groups[StateSection.PAIN] = _safe(
            db, uid, "pain", lambda: _pain_group(db, uid, end, span),
            MetricGroup(section=StateSection.PAIN), degraded,
        )
    if StateSection.MEASUREMENTS in wanted:
        groups[StateSection.MEASUREMENTS] = _safe(
            db, uid, "measurements", lambda: _measurement_group(db, uid, end),
            MetricGroup(section=StateSection.MEASUREMENTS), degraded,
        )

    quality = analytics.data_quality(
        weight_group=groups.get(StateSection.WEIGHT),
        nutrition_group=groups.get(StateSection.NUTRITION),
        sleep_group=groups.get(StateSection.SLEEP),
        training_group=groups.get(StateSection.TRAINING),
        no_effective_target=(targets is None or targets.provenance.value == "unknown"),
        stale_profile=profile is None,
        unresolved_units=_safe(
            db, uid, "unresolved_units", lambda: _unresolved_units(db, uid), 0,
        ),
        unresolved_exercise_identities=_safe(
            db, uid, "unresolved_exercises",
            lambda: _unresolved_exercises(db, uid, end, span), 0,
        ),
        source_conflicts=_safe(
            db, uid, "source_conflicts",
            lambda: _source_conflicts(db, uid, end, span), 0,
        ),
    )

    state = FitnessStateV1(
        schema_version=FITNESS_STATE_SCHEMA_VERSION,
        analytics_version=ANALYTICS_VERSION,
        user_id=uid,
        as_of=moment,
        athlete_local_date=local_today,
        timezone=timezone_name,
        period=Period(start=end - timedelta(days=span), end=end),
        # DEGRADED, not a smaller state: fewer metrics because a query failed
        # is indistinguishable from the athlete having less data, and a
        # review would then reason about an absence that is really an outage.
        freshness=Freshness.DEGRADED if degraded else Freshness.FRESH,
        data_revision=revision or None,
        profile=profile,
        goals=goals,
        limitations=limitations,
        targets=targets,
        program=program,
        sections=groups,
        quality=quality,
        degraded_dependencies=degraded,
    )

    if redis_client is not None and not degraded:
        # Never cache a degraded state: it would be served as current for the
        # whole TTL, which is exactly the "stale output labelled current"
        # failure the freshness field exists to prevent.
        _write_cache(redis_client, cache_key, state)
    return state


# ── Section builders ──────────────────────────────────────────────────────

def _profile(db: Session, user_id: str):
    from app.services.fitness.profile import get_athlete_profile, profile_timezone

    try:
        timezone_name = profile_timezone(db, user_id)
    except Exception:
        timezone_name = "America/New_York"
    try:
        has_row = db.execute(text(
            "SELECT 1 FROM fitness_athlete_profile WHERE user_id = :uid"
        ), {"uid": user_id}).fetchone()
        profile = get_athlete_profile(db, user_id) if has_row else None
    except Exception as exc:
        logger.warning("fitness state: profile unavailable (%s)", type(exc).__name__)
        profile = None
    return timezone_name, profile


def _goals(db: Session, user_id: str, end: date):
    from app.services.fitness.profile import get_goals
    # `end` is exclusive, so the goals in force on the last COMPLETE day.
    return get_goals(db, user_id, end - timedelta(days=1))


def _limitations(db: Session, user_id: str, end: date):
    from app.services.fitness.profile import get_limitations
    return get_limitations(db, user_id, end - timedelta(days=1))


def _targets(db: Session, user_id: str, end: date):
    from app.services.fitness.targets import resolve_targets
    return resolve_targets(db, user_id, end - timedelta(days=1))


def _program(db: Session, user_id: str, end: date) -> Dict[str, Any]:
    from app.services.fitness.targets import resolve_day_type

    try:
        from app.services.phase_resolution import get_active_program, get_effective_phase
        program = get_active_program(db, user_id)
        phase = get_effective_phase(db, user_id, on_date=end - timedelta(days=1))
    except Exception as exc:
        logger.warning("fitness state: program unavailable (%s)", type(exc).__name__)
        return {}

    out: Dict[str, Any] = {}
    if program:
        out["program"] = {
            "id": program.get("id"), "name": program.get("name"),
            "goal": program.get("goal"),
            "start_date": program.get("start_date"),
            "end_date": program.get("end_date"),
        }
    if phase:
        out["phase"] = {
            "id": phase.get("id"), "name": phase.get("name"),
            "goal": phase.get("goal"),
            "start_date": phase.get("start_date"),
            # Reported as the INCLUSIVE date it is on the row. The resolver
            # converts to half-open; exposing the converted value here would
            # make two surfaces show different block end dates.
            "end_date_inclusive": phase.get("end_date"),
            "deload_week": phase.get("deload_week"),
        }
    out["day_type"] = resolve_day_type(db, user_id, end - timedelta(days=1)).value
    return out


def _weight_group(
    db: Session, user_id: str, end: date, timezone_name: str, goals, span: int,
) -> MetricGroup:
    from app.services.fitness.observations import selected_series

    lookback = max(span, 28) + 1
    series = selected_series(
        db, user_id, "weight", end - timedelta(days=lookback), end,
        timezone_name=timezone_name,
    )
    values = [
        analytics.DailyValue(
            day=day, value=chosen.value, unit=chosen.unit,
            source_count=chosen.candidate_count,
            quality_flags=chosen.quality_flags,
        )
        for day, chosen in series.items()
    ]

    primary = next((g for g in goals if g.is_primary), None)
    rate, rate_unit = None, None
    if primary is not None:
        if primary.rate_basis.value == "absolute":
            rate, rate_unit = primary.target_rate_kg_week, Unit.KG_PER_WEEK
        elif primary.rate_basis.value == "percent":
            rate, rate_unit = primary.target_rate_percent_week, Unit.PERCENT_PER_WEEK

    return analytics.weight_metrics(
        values, end,
        goal_rate_per_week=rate, goal_rate_unit=rate_unit,
        goal_changed_on=primary.valid_from if primary else None,
    )


def _nutrition_group(
    db: Session, user_id: str, end: date, timezone_name: str, span: int,
) -> MetricGroup:
    from app.services.fitness.data_access import load_check_ins

    start = end - timedelta(days=span)
    food = load_food_days(db, user_id, start, end, timezone_name=timezone_name)
    check_ins = load_check_ins(db, user_id, start, end)

    days: List[analytics.NutritionDay] = []
    for offset in range(span):
        day = start + timedelta(days=offset)
        meals = food.get(day)
        status = (check_ins.get(day) or {}).get("nutrition_status") or "unknown"
        days.append(analytics.NutritionDay(
            day=day,
            calories=meals.calories if meals else None,
            protein_g=meals.protein_g if meals else None,
            carbs_g=meals.carbs_g if meals else None,
            fat_g=meals.fat_g if meals else None,
            status=status,
            meal_count=meals.meal_count if meals else 0,
            known_fields=dict(meals.known_fields) if meals else {},
            has_estimated_items=bool(meals.has_estimated_items) if meals else False,
        ))

    targets_by_day = _targets_by_day(db, user_id, start, end)
    return analytics.nutrition_metrics(
        days, end, targets_by_day=targets_by_day, span=span,
    )


def _targets_by_day(db: Session, user_id: str, start: date, end: date):
    """One resolved target per day in the window.

    Resolved per day rather than once: the target may have changed mid-window
    and the day type certainly does. Comparing every day against one target
    is the error the revision history exists to prevent.
    """
    from app.services.fitness.targets import resolve_targets

    out = {}
    day = start
    while day < end:
        try:
            out[day] = resolve_targets(db, user_id, day)
        except Exception as exc:
            logger.debug("target resolution failed for %s: %s", day, exc)
            # One error poisons the whole PostgreSQL transaction, so without
            # this the remaining days would all fail too and the window
            # would look as though it had no targets at all.
            try:
                db.rollback()
            except Exception:
                pass
        day += timedelta(days=1)
    return out


def _sleep_group(
    db: Session, user_id: str, end: date, timezone_name: str, targets, span: int,
) -> MetricGroup:
    from app.services.fitness.data_access import load_check_ins
    from app.services.fitness.observations import selected_series

    start = end - timedelta(days=span * 2)
    series = selected_series(
        db, user_id, "sleep_hours", start, end, timezone_name=timezone_name,
    )
    check_ins = load_check_ins(db, user_id, start, end)

    nights: List[analytics.SleepNight] = []
    for day in sorted(set(series) | set(check_ins)):
        chosen = series.get(day)
        row = check_ins.get(day) or {}
        # The canonical observation first, then the legacy check-in column.
        #
        # `daily_recovery_log.sleep_hours` is what the iOS app and the
        # recovery log have always written, and §5.2 keeps it as a
        # compatibility mirror. Reading only the observation stream made a
        # night logged through the older path invisible — so a week with
        # seven recorded sleeps reported zero nights, and the coach asked
        # "how did you sleep?" about a night already in the log.
        hours = chosen.value if chosen else None
        if hours is None and row.get("sleep_hours") is not None:
            try:
                hours = float(row["sleep_hours"])
            except (TypeError, ValueError):
                hours = None
        nights.append(analytics.SleepNight(
            day=day,
            hours=hours,
            bedtime_minutes=_clock_minutes(row.get("bedtime_at"), timezone_name),
            wake_minutes=_clock_minutes(row.get("wake_at"), timezone_name),
            quality=row.get("sleep_quality"),
        ))

    target_hours = targets.values.sleep_hours if targets else None
    return analytics.sleep_metrics(
        nights, end, target_hours=target_hours, span=span,
    )


def _clock_minutes(moment, timezone_name: str) -> Optional[int]:
    """Minutes past midnight in the ATHLETE's timezone.

    Converting is the point: a bedtime stored as UTC and read as
    minutes-past-UTC-midnight would put an 11pm ET bedtime at 03:00, and the
    consistency figure would then measure the UTC offset rather than the
    athlete's habit.
    """
    if moment is None:
        return None
    if getattr(moment, "tzinfo", None) is None:
        return None
    local = moment.astimezone(athlete_zone(timezone_name))
    return local.hour * 60 + local.minute


def _recovery_group(db: Session, user_id: str, end: date, span: int) -> MetricGroup:
    from app.schemas.fitness_coach import SCALE_DIRECTIONS
    from app.services.fitness.data_access import load_check_ins

    start = end - timedelta(days=span * 2)
    rows = load_check_ins(db, user_id, start, end)

    by_field: Dict[str, List[analytics.DailyValue]] = {}
    for day, row in rows.items():
        for field_name in SCALE_DIRECTIONS:
            value = row.get(field_name)
            if value is None:
                continue
            by_field.setdefault(field_name, []).append(
                analytics.DailyValue(day=day, value=float(value), unit=Unit.SCORE)
            )
    return analytics.subjective_metrics(by_field, end, span=span)


def _training_group(
    db: Session, user_id: str, end: date, timezone_name: str, span: int,
) -> MetricGroup:
    from app.services.fitness.exercises import effective_load_for, get_exercise

    start = end - timedelta(days=span)
    sessions = load_training_sessions(db, user_id, start, end)
    sets = load_sets(db, user_id, start, end, timezone_name=timezone_name)

    session_records = [
        analytics.SessionRecord(
            key=s.key, day=s.session_date, status=s.status,
            was_planned=s.was_planned, completed_sets=s.total_sets_completed,
        )
        for s in sessions
    ]

    # The prescribed count comes from each session's own stored snapshot, not
    # from today's templates — a template edit must not change last week's
    # adherence.
    planned = 0
    for s in sessions:
        exercises = (s.snapshot or {}).get("exercises") or []
        if exercises:
            planned += 1
        elif s.was_planned:
            planned += 1
    planned_from_snapshot = planned or None

    exercise_cache: Dict[str, Any] = {}
    records: List[analytics.SetRecord] = []
    for row in sets:
        ref = None
        if row.exercise_library_id:
            if row.exercise_library_id not in exercise_cache:
                exercise_cache[row.exercise_library_id] = get_exercise(
                    db, user_id, row.exercise_library_id
                )
            ref = exercise_cache[row.exercise_library_id]

        effective, _reason = effective_load_for(ref, row.load)
        records.append(analytics.SetRecord(
            set_id=row.id, day=row.session_date or (
                row.logged_at.date() if row.logged_at else start
            ),
            exercise_id=row.exercise_library_id,
            exercise_name=row.exercise_id or "unknown",
            occurrence_id=row.exercise_performance_id,
            session_key=row.active_session_id or row.session_id,
            reps=row.reps,
            load=effective if effective is not None else row.load,
            load_unit=row.load_unit,
            set_kind=row.set_kind, set_role=row.set_role,
            counts_toward_target=row.counts_toward_target,
            voided=row.voided_at is not None, skipped=row.skipped,
            effort=row.rir if row.rir is not None else row.rpe,
            effort_scale="rir" if row.rir is not None else (
                "rpe" if row.rpe is not None else None
            ),
            # An exercise with no recorded convention is NOT comparable. That
            # is the honest default: "40" might be per hand or total.
            load_comparable=bool(ref and ref.load_is_comparable),
            primary_muscles=ref.primary_muscles if ref else (),
            secondary_muscles=ref.secondary_muscles if ref else (),
        ))

    group = analytics.training_metrics(
        session_records, records, end,
        planned_from_snapshot=planned_from_snapshot, span=span,
    )
    group.metrics.update(analytics.exercise_frequency(records, end, span=max(span, 28)))
    return group


def _pain_group(db: Session, user_id: str, end: date, span: int) -> MetricGroup:
    from app.services.fitness.performance import pain_patterns

    group = MetricGroup(section=StateSection.PAIN)
    start = end - timedelta(days=max(span, 28))
    try:
        patterns = pain_patterns(db, user_id, start, end)
    except Exception as exc:
        logger.warning("fitness state: pain patterns failed (%s)", type(exc).__name__)
        return group

    for pattern in patterns:
        group.items.append({
            "exercise": pattern.exercise_name,
            "exercise_library_id": pattern.exercise_library_id,
            "sessions_with_pain": pattern.sessions_with_pain,
            "sessions_with_report": pattern.sessions_with_report,
            "sessions_total": pattern.sessions_total,
            "reporting_coverage": pattern.reporting_coverage,
            "max_severity": pattern.max_severity,
            "locations": list(pattern.locations),
            "sides": list(pattern.sides),
        })
    if patterns:
        group.limitations.append(
            "Pain is what the athlete reported, not a diagnosis. A session "
            "with no report is unknown, not pain-free — the "
            "sessions_with_report count is the denominator."
        )
    return group


def _measurement_group(db: Session, user_id: str, end: date) -> MetricGroup:
    from app.services.fitness.observations import (
        list_measurement_types, measurement_change,
    )

    group = MetricGroup(section=StateSection.MEASUREMENTS)
    try:
        types = list_measurement_types(db, user_id)
    except Exception as exc:
        logger.warning("fitness state: measurement types failed (%s)",
                       type(exc).__name__)
        return group

    for descriptor in types:
        sides = ("left", "right") if descriptor.allows_side else ("none",)
        for side in sides:
            metric = measurement_change(db, user_id, descriptor.code, side=side)
            if metric.value is None and metric.observed_days in (None, 0):
                # Nothing recorded for this type at all. Listing every
                # unmeasured circumference would bury the ones that matter.
                continue
            suffix = "" if side == "none" else f"_{side}"
            group.metrics[f"{descriptor.code}{suffix}_change"] = metric
    return group


# ── Quality inputs ────────────────────────────────────────────────────────

def _unresolved_units(db: Session, user_id: str) -> int:
    present = {
        r[0] for r in db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'health_metric'
        """)).fetchall()
    }
    if "unit" not in present:
        return 0
    from app.services.fitness.data_access import LEGACY_METRIC_UNITS
    return int(db.execute(text("""
        SELECT COUNT(*) FROM health_metric
        WHERE user_id = :uid AND unit IS NULL AND metric_type <> ALL(:traced)
    """), {"uid": user_id, "traced": list(LEGACY_METRIC_UNITS)}).scalar() or 0)


def _unresolved_exercises(db: Session, user_id: str, end: date, span: int) -> int:
    return int(db.execute(text("""
        SELECT COUNT(DISTINCT exercise_id) FROM workout_log
        WHERE user_id = :uid
          AND exercise_library_id IS NULL
          AND exercise_id IS NOT NULL
          AND session_date >= :start AND session_date < :end
    """), {
        "uid": user_id, "start": end - timedelta(days=max(span, 28)), "end": end,
    }).scalar() or 0)


def _source_conflicts(db: Session, user_id: str, end: date, span: int) -> int:
    present = {
        r[0] for r in db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'health_metric'
        """)).fetchall()
    }
    if "source_conflict" not in present:
        return 0
    return int(db.execute(text("""
        SELECT COUNT(*) FROM health_metric
        WHERE user_id = :uid AND source_conflict IS NOT NULL
          AND logical_date >= :start AND logical_date < :end
    """), {
        "uid": user_id, "start": end - timedelta(days=max(span, 28)), "end": end,
    }).scalar() or 0)


# ── Failure isolation ─────────────────────────────────────────────────────

def _safe(
    db: Session, user_id: str, name: str, build, default,
    degraded: Optional[List[str]] = None,
):
    """Run one section's builder, recording a failure rather than raising.

    A single failing section must not take the whole state with it: the
    athlete's weight history is still useful when the pain query is broken.
    But the failure is *named* in `degraded_dependencies` rather than
    swallowed, because a silently smaller state reads as less data.

    The session is rolled back to a savepoint-free clean state on failure —
    in PostgreSQL one error poisons the transaction, so without this every
    later section would fail too and the state would look entirely empty.
    """
    try:
        return build()
    except Exception as exc:
        logger.warning(
            "fitness state: %s unavailable (%s): %s", name, type(exc).__name__, exc,
        )
        if degraded is not None:
            degraded.append(name)
        try:
            db.rollback()
        except Exception:
            pass
        return default


# ── Cache ─────────────────────────────────────────────────────────────────

def _cache_key(
    user_id: str, end: date, timezone_name: str, span: int,
    sections: Set[StateSection], revision: str,
) -> str:
    """Key on everything that changes the answer.

    `revision` is the crucial one: it is a fingerprint of the athlete's
    latest write times, so a backdated correction produces a different key
    and the stale entry becomes unreachable rather than needing to be
    explicitly deleted. An invalidation that never fires therefore costs the
    TTL at worst, not forever.
    """
    payload = json.dumps({
        "v": CACHE_KEY_VERSION,
        "schema": FITNESS_STATE_SCHEMA_VERSION,
        "analytics": ANALYTICS_VERSION,
        "user": user_id,
        "end": end.isoformat(),
        "tz": timezone_name,
        "span": span,
        "sections": sorted(s.value for s in sections),
        "revision": revision,
    }, sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"fitness:state:{user_id}:{digest}"


def _read_cache(redis_client: Any, key: str) -> Optional[FitnessStateV1]:
    try:
        raw = redis_client.get(key)
    except Exception as exc:
        # Redis is expendable (§4.8). A cache read failure costs a recompute.
        logger.debug("fitness state cache read failed (%s)", type(exc).__name__)
        return None
    if not raw:
        return None
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return FitnessStateV1.model_validate_json(raw)
    except Exception as exc:
        # A cached payload from a previous shape. Recompute rather than
        # guess at it; the key version makes this rare, not impossible.
        logger.info("discarding unreadable cached fitness state (%s)",
                    type(exc).__name__)
        return None


def _write_cache(redis_client: Any, key: str, state: FitnessStateV1) -> None:
    try:
        redis_client.setex(key, CACHE_TTL_SECONDS, state.model_dump_json())
    except Exception as exc:
        logger.debug("fitness state cache write failed (%s)", type(exc).__name__)


def invalidate_fitness_state(redis_client: Any, user_id: str) -> int:
    """Drop this athlete's cached states.

    Best effort by design. The revision fingerprint in the key means a missed
    invalidation bounds staleness to the TTL, so this is an optimisation
    rather than a correctness requirement — which is what lets it be called
    after a commit without a transaction around it.

    Note the `redis<5.0.0` pin: the async client has `.close()`, not
    `.aclose()`, and calling the latter raises AttributeError at runtime.
    This function takes a sync client and closes nothing.
    """
    if redis_client is None:
        return 0
    try:
        keys = list(redis_client.scan_iter(match=f"fitness:state:{user_id}:*"))
        if not keys:
            return 0
        return int(redis_client.delete(*keys) or 0)
    except Exception as exc:
        logger.debug("fitness state invalidation failed (%s)", type(exc).__name__)
        return 0


# ── Rendering ─────────────────────────────────────────────────────────────

def render_fitness_capsule(state: FitnessStateV1, char_budget: int = 1500) -> str:
    """A compact chat capsule, within a character budget.

    Priority order is deliberate and is what gets kept when the budget bites:
    goal and phase, today's targets, **active limitations**, then freshness.
    Limitations rank above trends because a shoulder that hurts changes what
    Sara should suggest, and a trend does not.

    Every number carries its coverage. "81.2 kg" with no "3 of 7 days" reads
    as a settled fact, and that is how a thin figure becomes a decision.
    """
    lines: List[str] = []

    if state.freshness is Freshness.DEGRADED:
        lines.append(
            f"[Some fitness data could not be read: "
            f"{', '.join(state.degraded_dependencies)}. Treat the rest as "
            f"incomplete rather than as all there is.]"
        )

    primary = next((g for g in state.goals if g.is_primary), None)
    if primary:
        rate = ""
        if primary.rate_basis.value == "absolute" and primary.target_rate_kg_week is not None:
            rate = f" at {primary.target_rate_kg_week} kg/week"
        elif primary.rate_basis.value == "percent" and primary.target_rate_percent_week is not None:
            rate = f" at {primary.target_rate_percent_week}%/week"
        lines.append(f"Goal: {primary.kind.value}{rate} (since {primary.valid_from}).")
    else:
        lines.append("Goal: none recorded.")

    phase = (state.program or {}).get("phase")
    if phase:
        lines.append(
            f"Block: {phase.get('name')}"
            + (f", {phase.get('goal')}" if phase.get("goal") else "")
            + f". Today is a {state.program.get('day_type', 'unknown')} day."
        )

    if state.targets:
        values = state.targets.values
        if values.calories is not None:
            parts = [f"{values.calories} kcal"]
            if values.protein_g is not None:
                parts.append(f"{values.protein_g}g protein")
            provenance = ""
            if state.targets.provenance.value.startswith("legacy"):
                provenance = " (no recorded history behind these)"
            lines.append(f"Targets today: {', '.join(parts)}{provenance}.")
        else:
            lines.append("Targets today: not recorded.")

    # Above trends, deliberately.
    if state.limitations:
        described = "; ".join(
            f"{limitation.area}"
            + (f" ({limitation.severity_flag})" if limitation.severity_flag else "")
            for limitation in state.limitations[:3]
        )
        lines.append(f"Working around: {described}.")

    weight = state.sections.get(StateSection.WEIGHT)
    if weight:
        latest = weight.metrics.get("latest")
        if latest and latest.value is not None:
            lines.append(f"Weight: {latest.value} {latest.unit.value} ({latest.note}).")
        velocity = weight.metrics.get("velocity_weekly")
        if velocity and velocity.value is not None:
            lines.append(
                f"Weekly change: {velocity.value:+.2f} {velocity.unit.value} "
                f"({velocity.observed_days}/{velocity.expected_days} days observed)."
            )
        elif velocity is not None:
            lines.append(
                "Weekly change: not enough weigh-ins to say — "
                "not the same as no change."
            )

    nutrition = state.sections.get(StateSection.NUTRITION)
    if nutrition:
        complete = nutrition.metrics.get("complete_days")
        calories = nutrition.metrics.get("calories_mean")
        if calories and calories.value is not None:
            lines.append(
                f"Intake: {calories.value:.0f} kcal/day over "
                f"{calories.observed_days} fully logged days."
            )
        elif complete and complete.value is not None:
            lines.append(
                f"Intake: {int(complete.value)} fully logged days this week — "
                "too few to average."
            )

    training = state.sections.get(StateSection.TRAINING)
    if training:
        done = training.metrics.get("sessions_completed")
        sets = training.metrics.get("working_sets")
        if done and done.value is not None:
            fragment = f"Training: {int(done.value)} sessions"
            if sets and sets.value is not None:
                fragment += f", {int(sets.value)} working sets"
            lines.append(fragment + " this week.")

    pain = state.sections.get(StateSection.PAIN)
    if pain and pain.items:
        worst = pain.items[0]
        lines.append(
            f"Pain: {worst['exercise']} in "
            f"{worst['sessions_with_pain']} of {worst['sessions_with_report']} "
            f"sessions that were asked about. Reported, not diagnosed."
        )

    missing = state.quality.missing_fields
    if missing:
        lines.append(f"Unavailable: {len(missing)} metrics — see data quality.")

    capsule = "\n".join(lines)
    if len(capsule) <= char_budget:
        return capsule

    # Truncate by dropping whole lines from the END, so the priority order
    # above is what survives. Cutting mid-sentence would leave a number with
    # its coverage caveat removed, which is worse than omitting the number.
    kept: List[str] = []
    used = 0
    for line in lines:
        if used + len(line) + 1 > char_budget:
            break
        kept.append(line)
        used += len(line) + 1
    return "\n".join(kept)
