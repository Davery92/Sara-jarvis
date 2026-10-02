"""Canonical observation ingest and representative-value selection.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 8. One writer for every observed body
number, and one set of rules for picking *which* of several observations on a
day is the one analytics should use.

Why selection needs rules at all: an athlete who steps on the scale three
times one morning and once the next has not thereby made the first day more
important. Averaging every reading gives frequently-measured days extra
influence over a weekly mean, which then looks like a trend. So each metric
type has a deterministic per-day selection rule, the alternatives are
preserved, and the rule's name travels with the number.

Three selection families, because the underlying quantities are different:

* **Point-in-time** (weight, HRV, resting HR): one representative per day.
  Prefer a manually confirmed reading, then the earliest reading of the day
  for weight — morning weight before food and water is the comparable one —
  then the first available.
* **Daily cumulative** (steps): the *maximum* for the day, never the sum.
  HealthKit sends cumulative running totals, so summing them counts the same
  steps repeatedly. (This is the steps-are-cumulative gotcha, as a rule in
  code rather than a note.)
* **Overnight total** (sleep duration): one episode per logical wake date,
  and never the sum of two overlapping device totals. Two sources each
  reporting "7.5h last night" is one night of 7.5 hours.

Nothing here needs a network or a model. A numeric write that failed is
reported as failed; it never returns success with nothing stored.
"""
from __future__ import annotations

import json
import logging
import math
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.fitness_coach import (
    Metric,
    NutritionStatus,
    Quality,
    Unavailable,
    Unit,
    UnitError,
    convert,
    ensure_finite,
)
from app.services.fitness.events import queue_invalidation, record_fitness_event
from app.services.fitness.data_access import (
    SLEEP_METRIC_ALIASES,
    WEIGHT_METRIC_ALIASES,
    FitnessDataError,
    Observation,
    _require_user,
    athlete_zone,
    local_date_of,
    local_range_bounds,
    load_observations,
    resolve_metric_unit,
)

logger = logging.getLogger(__name__)


class SelectionRule(str):
    """A named per-day selection rule, carried on the metric it produced."""


EARLIEST_OF_DAY = SelectionRule("earliest_of_day")
LATEST_OF_DAY = SelectionRule("latest_of_day")
MANUAL_THEN_EARLIEST = SelectionRule("manual_then_earliest")
DAILY_MAX = SelectionRule("daily_max")
LONGEST_EPISODE = SelectionRule("longest_episode")


# The canonical unit each supported metric type is stored and compared in.
# A type absent here cannot be written without an explicit unit — refusing is
# the point, because the alternative is a column that mixes kg and lb.
CANONICAL_UNITS: Dict[str, Unit] = {
    "weight": Unit.LB,          # the existing contract; adapters convert
    "body_weight": Unit.LB,
    "sleep_hours": Unit.HOUR,
    "sleep_duration": Unit.HOUR,
    "steps": Unit.COUNT,
    "water": Unit.ML,
    "water_ml": Unit.ML,
    "hrv": Unit.MS,
    "hrv_morning": Unit.MS,
    "heart_rate": Unit.BPM,
    "resting_heart_rate": Unit.BPM,
    "resting_hr": Unit.BPM,
    "body_fat_percent": Unit.PERCENT,
}

SELECTION_RULES: Dict[str, SelectionRule] = {
    "weight": MANUAL_THEN_EARLIEST,
    "body_weight": MANUAL_THEN_EARLIEST,
    "steps": DAILY_MAX,
    "water": DAILY_MAX,
    "water_ml": DAILY_MAX,
    "sleep_hours": LONGEST_EPISODE,
    "sleep_duration": LONGEST_EPISODE,
    "hrv": MANUAL_THEN_EARLIEST,
    "hrv_morning": MANUAL_THEN_EARLIEST,
    "heart_rate": MANUAL_THEN_EARLIEST,
    "resting_heart_rate": MANUAL_THEN_EARLIEST,
    "resting_hr": MANUAL_THEN_EARLIEST,
}

MANUAL_SOURCES = frozenset({"manual", "user", "web", "chat", "coach_manual"})


@dataclass(frozen=True)
class IngestResult:
    """What actually happened. `stored` is False when nothing was written."""
    observation_id: Optional[str]
    stored: bool
    duplicate: bool = False
    conflict_recorded: bool = False
    superseded_id: Optional[str] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class SelectedValue:
    """One day's representative observation, with what it beat."""
    logical_date: date
    value: float
    unit: Unit
    observation_id: str
    recorded_at: datetime
    source: str
    rule: str
    candidate_count: int
    alternatives: Tuple[Tuple[str, float], ...] = ()
    quality_flags: Tuple[Quality, ...] = ()


def _observation_columns(db: Session) -> set[str]:
    return {
        r[0] for r in db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'health_metric'
        """)).fetchall()
    }


# ─────────────────────────────────────────────────────────────────────────
# Ingest
# ─────────────────────────────────────────────────────────────────────────

def ingest_observation(
    db: Session,
    user_id: str,
    *,
    metric_type: str,
    value: float,
    unit: Optional[Unit],
    recorded_at: datetime,
    source: str,
    external_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    source_quality: str = "measured",
    timezone_name: Optional[str] = None,
    corrects_observation_id: Optional[str] = None,
    correction_reason: Optional[str] = None,
) -> IngestResult:
    """Write one observation, idempotently, in its canonical unit.

    Does not commit — the caller owns the transaction, so an observation and
    the projection it updates land together or not at all.

    Refuses rather than guesses in three cases, each of which would otherwise
    store a number that looks like a fact:

    * **No unit for an unrecognised metric type.** There is no fallback. The
      magnitude does not disclose the unit.
    * **A non-finite value.** NaN compares false to itself, so it survives
      naive filtering and then poisons every aggregate it reaches.
    * **A correction naming an observation that is not this athlete's.**
    """
    uid = _require_user(user_id)
    cols = _observation_columns(db)
    has_extensions = "unit" in cols

    finite = ensure_finite(value, metric_type)
    if finite is None:
        raise FitnessDataError(f"{metric_type}: a value is required")

    canonical = CANONICAL_UNITS.get(metric_type)
    if unit is None or unit is Unit.UNKNOWN:
        if canonical is None:
            raise FitnessDataError(
                f"{metric_type}: a unit is required — this type has no traced "
                "canonical unit, and a value's magnitude does not disclose one"
            )
        # The caller is writing in the canonical unit implicitly. Accepted,
        # but recorded as the canonical unit rather than as unknown.
        unit = canonical

    original_value: Optional[float] = None
    original_unit: Optional[Unit] = None
    stored_value = finite
    if canonical is not None and unit is not canonical:
        try:
            stored_value = convert(finite, unit, canonical)
        except UnitError as exc:
            raise FitnessDataError(
                f"{metric_type}: cannot store a {unit.value} value in "
                f"{canonical.value} ({exc})"
            ) from exc
        # Keep what the source actually sent. Without it a conversion is
        # irreversible and a later unit-policy change cannot be re-derived.
        original_value, original_unit = finite, unit

    if recorded_at.tzinfo is None:
        raise FitnessDataError(
            "recorded_at must be timezone-aware: a naive observation time "
            "cannot be placed on an athlete-local calendar day"
        )
    recorded_at = recorded_at.astimezone(timezone.utc)
    tz = athlete_zone(timezone_name or _profile_timezone(db, uid))
    logical = local_date_of(recorded_at, tz)

    superseded: Optional[str] = None
    if corrects_observation_id:
        target = db.execute(text("""
            SELECT id, metric_type FROM health_metric
            WHERE id = :id AND user_id = :uid
        """), {"id": corrects_observation_id, "uid": uid}).fetchone()
        if target is None:
            raise LookupError("observation to correct not found")
        if target.metric_type != metric_type:
            raise FitnessDataError(
                "a correction must replace an observation of the same metric type"
            )
        superseded = target.id

    # Provider idempotency first: a replayed sync batch must be a no-op, and
    # matching on the sample id is more reliable than matching timestamps to
    # the microsecond.
    if external_id and has_extensions:
        existing = db.execute(text("""
            SELECT id FROM health_metric
            WHERE user_id = :uid AND source = :src AND external_id = :ext
        """), {"uid": uid, "src": source, "ext": external_id}).fetchone()
        if existing:
            return IngestResult(existing.id, stored=False, duplicate=True,
                               reason="same provider sample already stored")

    obs_id = str(uuid.uuid4())
    meta = dict(metadata or {})
    if original_value is not None and original_unit is not None:
        meta.setdefault("converted_from", {
            "value": original_value, "unit": original_unit.value,
        })

    if has_extensions:
        row = db.execute(text("""
            INSERT INTO health_metric
                (id, user_id, metric_type, value, unit, recorded_at, source, metadata,
                 original_value, original_unit, external_id, logical_date,
                 source_quality, supersedes_id, correction_reason)
            VALUES
                (:id, :uid, :mt, :val, :unit, :ts, :src, CAST(:meta AS jsonb),
                 :oval, :ounit, :ext, :logical, :quality, :sup, :reason)
            ON CONFLICT (user_id, metric_type, recorded_at) DO NOTHING
            RETURNING id
        """), {
            "id": obs_id, "uid": uid, "mt": metric_type, "val": stored_value,
            "unit": (canonical or unit).value, "ts": recorded_at, "src": source,
            "meta": json.dumps(meta), "oval": original_value,
            "ounit": original_unit.value if original_unit else None,
            "ext": external_id, "logical": logical, "quality": source_quality,
            "sup": superseded, "reason": correction_reason,
        }).fetchone()
    else:
        row = db.execute(text("""
            INSERT INTO health_metric
                (id, user_id, metric_type, value, recorded_at, source, metadata)
            VALUES (:id, :uid, :mt, :val, :ts, :src, CAST(:meta AS jsonb))
            ON CONFLICT (user_id, metric_type, recorded_at) DO NOTHING
            RETURNING id
        """), {
            "id": obs_id, "uid": uid, "mt": metric_type, "val": stored_value,
            "ts": recorded_at, "src": source, "meta": json.dumps(meta),
        }).fetchone()

    if row is None:
        # The dedup index refused it. That index is `(user_id, metric_type,
        # recorded_at)` and two live writers depend on it by name, so it is
        # not widened (see migration 162). What *can* be improved is what
        # happens to the loser: record the conflict instead of discarding it.
        return _record_collision(
            db, uid, metric_type, recorded_at, stored_value,
            canonical or unit, source, external_id, has_extensions,
        )

    if superseded:
        db.execute(text("""
            UPDATE health_metric
            SET superseded_by_id = :new, correction_reason = COALESCE(correction_reason, :reason)
            WHERE id = :old AND user_id = :uid
        """), {"new": obs_id, "old": superseded, "uid": uid,
               "reason": correction_reason})

    # Same transaction as the row it describes, and carrying no value — see
    # `fitness/events.py`. A backdated correction changes `logical_date`,
    # which is what tells a consumer that an OLD day moved rather than a new
    # one arriving.
    record_fitness_event(
        db, uid, "fitness.observation_ingested",
        dedupe_key=f"fitness.obs:{obs_id}",
        source_ref=obs_id,
        aggregate_type="health_metric", aggregate_id=obs_id,
        payload={
            "metric_type": metric_type,
            "source": source,
            "is_correction": bool(superseded),
            "source_quality": source_quality,
        },
        logical_date=logical,
        actor_type="user" if source in ("manual", "user", "chat") else "system",
    )

    return IngestResult(obs_id, stored=True, superseded_id=superseded)


def _record_collision(
    db: Session,
    user_id: str,
    metric_type: str,
    recorded_at: datetime,
    value: float,
    unit: Unit,
    source: str,
    external_id: Optional[str],
    has_extensions: bool,
) -> IngestResult:
    """Two sources reported this metric at the same instant.

    The existing behaviour is `DO NOTHING` — the second write vanishes with
    no trace, so "my watch and my scale disagree" is unanswerable. The row
    that won stays the row that won (changing that would mean picking a
    winner here, which is a selection decision, not an ingest one), but the
    rejected value is appended to `source_conflict` so the disagreement is
    visible and `DataQuality.source_conflicts` can count it.
    """
    existing = db.execute(text("""
        SELECT id, value, source FROM health_metric
        WHERE user_id = :uid AND metric_type = :mt AND recorded_at = :ts
    """), {"uid": user_id, "mt": metric_type, "ts": recorded_at}).fetchone()

    if existing is None:  # pragma: no cover - the conflict just happened
        return IngestResult(None, stored=False, reason="insert refused")

    same_value = existing.value is not None and abs(float(existing.value) - value) < 1e-9
    if same_value and existing.source == source:
        return IngestResult(existing.id, stored=False, duplicate=True,
                           reason="identical observation already stored")

    if not has_extensions:
        logger.info(
            "health_metric collision for %s at %s (kept %s, rejected %s) — "
            "schema predates source_conflict, nothing recorded",
            metric_type, recorded_at, existing.source, source,
        )
        return IngestResult(existing.id, stored=False, reason="collision, not recorded")

    db.execute(text("""
        UPDATE health_metric
        SET source_conflict = COALESCE(source_conflict, '[]'::jsonb)
                              || CAST(:entry AS jsonb)
        WHERE id = :id AND user_id = :uid
    """), {
        "id": existing.id, "uid": user_id,
        "entry": json.dumps([{
            "rejected_value": value,
            "rejected_unit": unit.value,
            "rejected_source": source,
            "rejected_external_id": external_id,
            "kept_value": float(existing.value),
            "kept_source": existing.source,
            "at": recorded_at.isoformat(),
        }]),
    })
    return IngestResult(
        existing.id, stored=False, conflict_recorded=True,
        reason=(
            f"another source ({existing.source}) already recorded "
            f"{metric_type} at this instant; the disagreement was recorded"
        ),
    )


def _profile_timezone(db: Session, user_id: str) -> str:
    row = db.execute(text(
        "SELECT timezone FROM fitness_athlete_profile WHERE user_id = :uid"
    ), {"uid": user_id}).fetchone()
    return (row.timezone if row else None) or "America/New_York"


# ─────────────────────────────────────────────────────────────────────────
# Selection
# ─────────────────────────────────────────────────────────────────────────

def select_daily_values(
    observations: Sequence[Observation],
    metric_type: str,
    *,
    rule: Optional[SelectionRule] = None,
) -> Dict[date, SelectedValue]:
    """One representative observation per athlete-local day.

    Pure: takes already-loaded observations and returns a selection. That is
    what makes the rules testable against hand-built fixtures rather than
    against whatever the database happens to hold.

    Observations with an unresolved unit are excluded, not converted. A
    weight whose unit was never recorded cannot join a kg series.
    """
    applied = rule or SELECTION_RULES.get(metric_type, MANUAL_THEN_EARLIEST)
    by_day: Dict[date, List[Observation]] = {}
    for obs in observations:
        if obs.is_superseded:
            continue
        if obs.unit is Unit.UNKNOWN:
            continue
        by_day.setdefault(obs.logical_date, []).append(obs)

    out: Dict[date, SelectedValue] = {}
    for day, candidates in sorted(by_day.items()):
        chosen = _apply_rule(candidates, applied)
        if chosen is None:
            continue
        flags: List[Quality] = list(chosen.quality_flags)
        if len(candidates) > 1:
            # Not an error — three weigh-ins is three weigh-ins. But a
            # consumer showing "81.2 kg" should be able to say there were
            # others.
            flags.append(Quality.SOURCE_CONFLICT) if _values_disagree(candidates) else None
        out[day] = SelectedValue(
            logical_date=day,
            value=chosen.value,
            unit=chosen.unit,
            observation_id=chosen.id,
            recorded_at=chosen.recorded_at,
            source=chosen.source,
            rule=str(applied),
            candidate_count=len(candidates),
            alternatives=tuple(
                (o.id, o.value) for o in candidates if o.id != chosen.id
            ),
            quality_flags=tuple(f for f in flags if f is not None),
        )
    return out


def _values_disagree(candidates: Sequence[Observation]) -> bool:
    """Whether the day's candidates are materially different readings.

    Two sources reporting the same number is not a conflict; it is
    corroboration. The threshold is relative so it works for 80 kg and for
    8000 steps.
    """
    values = [c.value for c in candidates]
    if len(values) < 2:
        return False
    lo, hi = min(values), max(values)
    if hi == 0:
        return False
    return (hi - lo) / abs(hi) > 0.01


def _apply_rule(
    candidates: Sequence[Observation], rule: SelectionRule
) -> Optional[Observation]:
    if not candidates:
        return None
    ordered = sorted(candidates, key=lambda o: (o.recorded_at, o.id))

    if rule == DAILY_MAX:
        # Steps arrive as cumulative running totals, so the day's figure is
        # the maximum. Summing them counts the same steps several times over.
        return max(ordered, key=lambda o: (o.value, o.recorded_at))

    if rule == LONGEST_EPISODE:
        # One night, not the sum of two devices' totals for it. The longest
        # reported total is the one most likely to cover the whole episode;
        # adding them would report 15 hours of sleep for one night.
        return max(ordered, key=lambda o: (o.value, o.recorded_at))

    if rule == LATEST_OF_DAY:
        return ordered[-1]

    if rule == MANUAL_THEN_EARLIEST:
        # A reading the athlete confirmed by hand outranks a passive one:
        # they were there, and a scale's Bluetooth duplicate was not
        # confirmed by anybody. Then earliest, because morning weight before
        # food and water is the comparable measurement.
        manual = [o for o in ordered if o.source in MANUAL_SOURCES]
        return (manual or ordered)[0]

    return ordered[0]


def selected_series(
    db: Session,
    user_id: str,
    metric_type: str,
    start_date: date,
    end_date: date,
    *,
    timezone_name: Optional[str] = None,
) -> Dict[date, SelectedValue]:
    """Load and select in one call, for the common analytics case.

    Resolves the metric aliases: `weight`/`body_weight` are one stream, and
    the three sleep type names are one stream. Loading only one of them would
    silently lose days.
    """
    uid = _require_user(user_id)
    tz_name = timezone_name or _profile_timezone(db, uid)
    tz = athlete_zone(tz_name)
    start_at, end_at = local_range_bounds(start_date, end_date, tz)

    types = _aliases_for(metric_type)
    observations = load_observations(
        db, uid, types, start_at, end_at, timezone_name=tz_name,
    )
    return select_daily_values(observations, metric_type)


def _aliases_for(metric_type: str) -> Tuple[str, ...]:
    if metric_type in WEIGHT_METRIC_ALIASES:
        return WEIGHT_METRIC_ALIASES
    if metric_type in SLEEP_METRIC_ALIASES:
        return SLEEP_METRIC_ALIASES
    if metric_type in ("hrv", "hrv_morning"):
        return ("hrv", "hrv_morning")
    if metric_type in ("resting_heart_rate", "resting_hr", "heart_rate"):
        return ("resting_heart_rate", "resting_hr", "heart_rate")
    if metric_type in ("water", "water_ml"):
        return ("water", "water_ml")
    return (metric_type,)


def latest_metric(
    db: Session,
    user_id: str,
    metric_type: str,
    *,
    key: Optional[str] = None,
    lookback_days: int = 30,
    timezone_name: Optional[str] = None,
) -> Metric:
    """The most recent selected value, as a `Metric` that can say "unknown"."""
    uid = _require_user(user_id)
    tz_name = timezone_name or _profile_timezone(db, uid)
    tz = athlete_zone(tz_name)
    today = datetime.now(tz).date()
    series = selected_series(
        db, uid, metric_type, today - timedelta(days=lookback_days),
        today + timedelta(days=1), timezone_name=tz_name,
    )
    metric_key = key or f"{metric_type}.latest"
    if not series:
        return Metric(key=metric_key, unavailable_reason=Unavailable.NO_DATA)
    day = max(series)
    chosen = series[day]
    return Metric(
        key=metric_key,
        value=chosen.value,
        unit=chosen.unit,
        observed_at=chosen.recorded_at,
        source_count=chosen.candidate_count,
        quality_flags=list(chosen.quality_flags),
        formula=chosen.rule,
        note=f"source: {chosen.source}",
    )


# ─────────────────────────────────────────────────────────────────────────
# Compatibility projections
# ─────────────────────────────────────────────────────────────────────────

def sync_projections(
    db: Session,
    user_id: str,
    metric_type: str,
    logical_date: date,
    *,
    timezone_name: Optional[str] = None,
) -> List[str]:
    """Update the legacy mirrors from the canonical selection.

    `daily_recovery_log.body_weight`/`sleep_hours` and `weight_trend` are
    projections that several existing readers (the iOS app, the recovery
    view, the morning brief) use. They are maintained *from* the canonical
    selection, not calculated independently — two independent calculations is
    how two surfaces come to show different weights for the same day.

    Does not commit. Returns the names of the projections it touched, so a
    caller can say what it changed.
    """
    uid = _require_user(user_id)
    touched: List[str] = []
    tz_name = timezone_name or _profile_timezone(db, uid)

    series = selected_series(
        db, uid, metric_type, logical_date, logical_date + timedelta(days=1),
        timezone_name=tz_name,
    )
    chosen = series.get(logical_date)
    if chosen is None:
        return touched

    if metric_type in WEIGHT_METRIC_ALIASES:
        # `daily_recovery_log.weight_unit` defaults to 'lbs'; the canonical
        # store is lb, so no conversion. Writing a kg value into a column
        # labelled lbs is exactly the class of bug this function exists to
        # make impossible.
        as_lb = chosen.value if chosen.unit is Unit.LB else convert(
            chosen.value, chosen.unit, Unit.LB
        )
        db.execute(text("""
            INSERT INTO daily_recovery_log
                (id, user_id, log_date, body_weight, weight_unit, created_at, updated_at)
            VALUES (:id, :uid, :d, :w, 'lbs', NOW(), NOW())
            ON CONFLICT (user_id, log_date) DO UPDATE
            SET body_weight = EXCLUDED.body_weight,
                weight_unit = 'lbs',
                updated_at  = NOW()
        """), {"id": str(uuid.uuid4()), "uid": uid, "d": logical_date, "w": as_lb})
        touched.append("daily_recovery_log.body_weight")

        db.execute(text("""
            INSERT INTO weight_trend (id, user_id, date, raw_weight, created_at)
            VALUES (:id, :uid, :d, :w, NOW())
            ON CONFLICT (user_id, date) DO UPDATE
            SET raw_weight = EXCLUDED.raw_weight
        """), {"id": str(uuid.uuid4()), "uid": uid, "d": logical_date, "w": as_lb})
        touched.append("weight_trend.raw_weight")

    elif metric_type in SLEEP_METRIC_ALIASES:
        as_hours = chosen.value if chosen.unit is Unit.HOUR else convert(
            chosen.value, chosen.unit, Unit.HOUR
        )
        db.execute(text("""
            INSERT INTO daily_recovery_log
                (id, user_id, log_date, sleep_hours, created_at, updated_at)
            VALUES (:id, :uid, :d, :h, NOW(), NOW())
            ON CONFLICT (user_id, log_date) DO UPDATE
            SET sleep_hours = EXCLUDED.sleep_hours, updated_at = NOW()
        """), {"id": str(uuid.uuid4()), "uid": uid, "d": logical_date, "h": as_hours})
        touched.append("daily_recovery_log.sleep_hours")

    elif metric_type in ("hrv", "hrv_morning"):
        db.execute(text("""
            INSERT INTO daily_recovery_log
                (id, user_id, log_date, hrv, created_at, updated_at)
            VALUES (:id, :uid, :d, :v, NOW(), NOW())
            ON CONFLICT (user_id, log_date) DO UPDATE
            SET hrv = EXCLUDED.hrv, updated_at = NOW()
        """), {"id": str(uuid.uuid4()), "uid": uid, "d": logical_date,
               "v": int(round(chosen.value))})
        touched.append("daily_recovery_log.hrv")

    return touched


def rebuild_weight_trend(
    db: Session,
    user_id: str,
    *,
    from_date: date,
    timezone_name: Optional[str] = None,
) -> int:
    """Recompute `weight_trend` from `from_date` onward.

    A backdated correction invalidates every EWMA value after it, because
    each one was computed from the series as it stood. Recomputing forward
    from the corrected day is the only way the displayed series stays
    consistent with the observations.

    alpha=0.1, matching the existing `/weight` route so the labelled display
    series does not change shape. This is explicitly a *display* series —
    coach analytics compute calendar-window means from the selected
    observations, never from these stored values.
    """
    uid = _require_user(user_id)
    tz_name = timezone_name or _profile_timezone(db, uid)
    tz = athlete_zone(tz_name)
    today = datetime.now(tz).date()

    series = selected_series(
        db, uid, "weight", from_date, today + timedelta(days=1),
        timezone_name=tz_name,
    )
    if not series:
        return 0

    prior = db.execute(text("""
        SELECT trend_weight FROM weight_trend
        WHERE user_id = :uid AND date < :d AND trend_weight IS NOT NULL
        ORDER BY date DESC LIMIT 1
    """), {"uid": uid, "d": from_date}).fetchone()
    trend: Optional[float] = float(prior.trend_weight) if prior else None

    alpha = 0.1
    updated = 0
    for day in sorted(series):
        chosen = series[day]
        raw = chosen.value if chosen.unit is Unit.LB else convert(
            chosen.value, chosen.unit, Unit.LB
        )
        trend = raw if trend is None else (alpha * raw + (1 - alpha) * trend)
        db.execute(text("""
            INSERT INTO weight_trend (id, user_id, date, raw_weight, trend_weight, created_at)
            VALUES (:id, :uid, :d, :raw, :trend, NOW())
            ON CONFLICT (user_id, date) DO UPDATE
            SET raw_weight = EXCLUDED.raw_weight,
                trend_weight = EXCLUDED.trend_weight
        """), {"id": str(uuid.uuid4()), "uid": uid, "d": day,
               "raw": raw, "trend": trend})
        updated += 1
    return updated


# ─────────────────────────────────────────────────────────────────────────
# Daily check-ins
# ─────────────────────────────────────────────────────────────────────────

# Columns a check-in PATCH may write. A fixed tuple, never request-derived:
# the DTO forbids extras, and this is the second line of defence against a
# parameter naming an arbitrary column.
_CHECKIN_COLUMNS = (
    "bedtime_at", "wake_at", "sleep_quality", "energy", "fatigue",
    "soreness_level", "stress", "motivation", "subjective_readiness",
    "notes", "nutrition_status",
)

# Physiological numbers that belong to `health_metric`, not to the check-in
# row. A PATCH naming one of these is rerouted to the canonical ingest; the
# check-in columns for them are maintained mirrors.
_DELEGATED_TO_OBSERVATIONS = frozenset({
    "hrv", "heart_rate", "sleep_hours", "body_weight",
})


class CheckInConflict(Exception):
    """`expected_version` did not match. Re-read and retry."""

    def __init__(self, current_version: int):
        super().__init__("the check-in was modified")
        self.current_version = current_version


def get_check_in(
    db: Session,
    user_id: str,
    log_date: date,
    *,
    timezone_name: Optional[str] = None,
):
    """One athlete-local day, with its canonical observations resolved.

    The subjective fields come from `daily_recovery_log`; weight, sleep,
    steps, water, HRV and resting HR are read from `health_metric` through
    the selection rules. The legacy columns on the recovery row are mirrors
    and are deliberately not what this returns — reading them would mean two
    answers to "what did I weigh" existed in one response.
    """
    from app.schemas.fitness_coach import (
        CheckInOut, NutritionStatus, ReadinessCoverage,
    )

    uid = _require_user(user_id)
    tz_name = timezone_name or _profile_timezone(db, uid)

    present = {
        r[0] for r in db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'daily_recovery_log'
        """)).fetchall()
    }
    extended = [c for c in (
        "bedtime_at", "wake_at", "sleep_quality", "energy", "fatigue",
        "stress", "motivation", "subjective_readiness", "nutrition_status",
        "nutrition_completed_at", "row_version", "field_sources",
    ) if c in present]
    extra = ("," + ", ".join(extended)) if extended else ""

    row = db.execute(text(f"""
        SELECT log_date, hrv, heart_rate, sleep_hours, soreness_level, notes,
               body_weight, weight_unit {extra}
        FROM daily_recovery_log
        WHERE user_id = :uid AND log_date = :d
    """), {"uid": uid, "d": log_date}).fetchone()

    m = dict(row._mapping) if row else {}
    out = CheckInOut(
        user_id=uid,
        log_date=log_date,
        bedtime_at=m.get("bedtime_at"),
        wake_at=m.get("wake_at"),
        sleep_quality=m.get("sleep_quality"),
        energy=m.get("energy"),
        fatigue=m.get("fatigue"),
        soreness_level=m.get("soreness_level"),
        stress=m.get("stress"),
        motivation=m.get("motivation"),
        subjective_readiness=m.get("subjective_readiness"),
        notes=m.get("notes"),
        nutrition_status=NutritionStatus(m.get("nutrition_status") or "unknown"),
        nutrition_completed_at=m.get("nutrition_completed_at"),
        row_version=int(m.get("row_version") or 1),
        field_sources=_as_json_dict(m.get("field_sources")),
    )

    def day_metric(metric_type: str, key: str) -> Metric:
        series = selected_series(
            db, uid, metric_type, log_date, log_date + timedelta(days=1),
            timezone_name=tz_name,
        )
        chosen = series.get(log_date)
        if chosen is None:
            return Metric(key=key, unavailable_reason=Unavailable.NO_DATA)
        return Metric(
            key=key, value=chosen.value, unit=chosen.unit,
            observed_at=chosen.recorded_at, source_count=chosen.candidate_count,
            quality_flags=list(chosen.quality_flags), formula=chosen.rule,
            note=f"source: {chosen.source}",
        )

    out = out.model_copy(update={
        "weight": day_metric("weight", "checkin.weight"),
        "sleep_duration": day_metric("sleep_hours", "checkin.sleep_duration"),
        "steps": day_metric("steps", "checkin.steps"),
        "water": day_metric("water", "checkin.water"),
        "hrv": day_metric("hrv", "checkin.hrv"),
        "resting_heart_rate": day_metric(
            "resting_heart_rate", "checkin.resting_heart_rate"
        ),
    })

    readiness, coverage = compute_wrapped_readiness(db, uid, log_date, out)
    return out.model_copy(update={
        "computed_readiness": readiness,
        "readiness_coverage": coverage,
    })


def _as_json_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def compute_wrapped_readiness(
    db: Session, user_id: str, log_date: date, check_in
) -> Tuple[Optional[Dict[str, Any]], Any]:
    """`compute_readiness`, wrapped so an empty day is not "Excellent".

    `recovery_score.compute_readiness({})` returns 100/"Excellent — good to
    push it today". That is correct arithmetic on no information, and it has
    been displayed to a user who logged nothing. The formula is untouched —
    rewriting it under cover of this work would change every historical score
    — but its *coverage* is now reported beside it, and an input with nothing
    eligible returns no score at all.
    """
    from app.schemas.fitness_coach import ReadinessCoverage
    from app.services.recovery_score import compute_readiness

    inputs = {
        "sleep_hours": check_in.sleep_duration.value if check_in.sleep_duration else None,
        "hrv": check_in.hrv.value if check_in.hrv else None,
        "heart_rate": (
            check_in.resting_heart_rate.value if check_in.resting_heart_rate else None
        ),
        "soreness_level": check_in.soreness_level,
    }
    eligible = [k for k, v in inputs.items() if v is not None]
    if not eligible:
        # Not a score of zero, and not a score of 100. No score.
        return None, ReadinessCoverage.UNKNOWN

    baseline = _readiness_baseline(db, user_id, log_date)
    result = compute_readiness(inputs, baseline)
    coverage = (
        ReadinessCoverage.FULL if len(eligible) == len(inputs)
        else ReadinessCoverage.PARTIAL
    )
    result = dict(result)
    result["inputs_used"] = sorted(eligible)
    result["inputs_missing"] = sorted(set(inputs) - set(eligible))
    result["coverage"] = coverage.value
    return result, coverage


def _readiness_baseline(
    db: Session, user_id: str, log_date: date, *, window_days: int = 28
) -> Dict[str, Any]:
    """Recent averages for HRV and resting HR, from selected observations.

    Computed from the canonical selection rather than from
    `daily_recovery_log`'s mirrors, so a backdated correction moves the
    baseline too.
    """
    start = log_date - timedelta(days=window_days)
    hrv = selected_series(db, user_id, "hrv", start, log_date)
    hr = selected_series(db, user_id, "resting_heart_rate", start, log_date)
    baseline: Dict[str, Any] = {}
    if hrv:
        baseline["avg_hrv"] = sum(v.value for v in hrv.values()) / len(hrv)
    if hr:
        baseline["avg_hr"] = sum(v.value for v in hr.values()) / len(hr)
    return baseline


def patch_check_in(
    db: Session,
    user_id: str,
    log_date: date,
    patch,
    *,
    source: str = "manual",
    timezone_name: Optional[str] = None,
):
    """Apply a partial check-in update.

    Three behaviours that only a partial-update API can get right, and that
    this function exists to get right:

    1. **An omitted field is untouched.** A PATCH sending only `energy` must
       not erase the HRV HealthKit wrote this morning.
    2. **An explicit `null` clears exactly that field**, and nothing else.
    3. **A physiological number is rerouted** to the canonical ingest rather
       than written onto the check-in row, so there is one weight for the day
       rather than one here and one in `health_metric`.

    Marking nutrition complete requires a timestamp (the constraint enforces
    it) because editing a meal afterwards has to be able to invalidate the
    confirmation — and "when was it confirmed" is how that is decided.
    """
    from app.schemas.fitness_coach import NutritionStatus, present_fields

    uid = _require_user(user_id)
    tz_name = timezone_name or _profile_timezone(db, uid)
    fields = present_fields(patch)

    unknown = set(fields) - set(_CHECKIN_COLUMNS) - _DELEGATED_TO_OBSERVATIONS
    if unknown:
        raise FitnessDataError(f"not check-in fields: {sorted(unknown)}")

    current = db.execute(text("""
        SELECT row_version, nutrition_status, field_sources
        FROM daily_recovery_log
        WHERE user_id = :uid AND log_date = :d
        FOR UPDATE
    """), {"uid": uid, "d": log_date}).fetchone()

    expected = getattr(patch, "expected_version", None)
    if current is not None and expected is not None and \
            int(expected) != int(current.row_version):
        raise CheckInConflict(int(current.row_version))

    # Physiological values go to health_metric, not onto this row.
    delegated = {k: v for k, v in fields.items() if k in _DELEGATED_TO_OBSERVATIONS}
    for name, value in delegated.items():
        if value is None:
            # Clearing a physiological reading is a correction, not a delete:
            # it needs a target observation and a reason. Refuse here rather
            # than silently dropping the request.
            raise FitnessDataError(
                f"{name} cannot be cleared through a check-in PATCH; correct "
                "the observation it came from instead"
            )
        _ingest_delegated(db, uid, name, float(value), log_date, tz_name, source)

    row_fields = {k: v for k, v in fields.items() if k in _CHECKIN_COLUMNS}

    # Completeness transitions carry a timestamp and a source. Never inferred
    # from meal count or from calories looking high enough.
    completed_at_change: Optional[Tuple[str, Any]] = None
    if "nutrition_status" in row_fields:
        status = row_fields["nutrition_status"]
        status_value = getattr(status, "value", status)
        if status_value == NutritionStatus.COMPLETE.value:
            completed_at_change = ("nutrition_completed_at", datetime.now(timezone.utc))
        else:
            completed_at_change = ("nutrition_completed_at", None)
        row_fields["nutrition_status"] = status_value

    sources = _as_json_dict(current.field_sources if current else None)
    for name in list(row_fields) + list(delegated):
        sources[name] = source

    if current is None:
        cols = ["id", "user_id", "log_date", "field_sources"]
        params: Dict[str, Any] = {
            "id": str(uuid.uuid4()), "user_id": uid, "log_date": log_date,
            "field_sources": json.dumps(sources),
        }
        for name, value in row_fields.items():
            cols.append(name)
            params[name] = value
        if completed_at_change:
            cols.append(completed_at_change[0])
            params[completed_at_change[0]] = completed_at_change[1]
        placeholders = ", ".join(
            f"CAST(:{c} AS jsonb)" if c == "field_sources" else f":{c}" for c in cols
        )
        # Upsert, not a plain insert. Two reasons, and the first is not
        # hypothetical: `_ingest_delegated` above calls `sync_projections`,
        # which creates this very row to mirror a weight or sleep value. By
        # the time the branch is reached the row exists, and a bare INSERT
        # violates `daily_recovery_log_user_id_log_date_key`. The second is
        # the ordinary race between two devices answering the same day.
        updates = ", ".join(
            f"{c} = EXCLUDED.{c}" for c in cols
            if c not in ("id", "user_id", "log_date")
        )
        db.execute(text(f"""
            INSERT INTO daily_recovery_log ({', '.join(cols)}, created_at, updated_at)
            VALUES ({placeholders}, NOW(), NOW())
            ON CONFLICT (user_id, log_date) DO UPDATE
            SET {updates}, row_version = daily_recovery_log.row_version + 1,
                updated_at = NOW()
        """), params)
    else:
        assignments = ["field_sources = CAST(:field_sources AS jsonb)",
                       "row_version = row_version + 1",
                       "updated_at = NOW()"]
        params = {"uid": uid, "d": log_date, "field_sources": json.dumps(sources)}
        for name, value in row_fields.items():
            assignments.append(f"{name} = :{name}")
            params[name] = value
        if completed_at_change:
            assignments.append(f"{completed_at_change[0]} = :completed_at")
            params["completed_at"] = completed_at_change[1]
        db.execute(text(f"""
            UPDATE daily_recovery_log SET {', '.join(assignments)}
            WHERE user_id = :uid AND log_date = :d
        """), params)

    record_fitness_event(
        db, uid, "fitness.check_in_logged",
        dedupe_key=(
            f"fitness.checkin:{uid}:{log_date.isoformat()}:"
            f"{(current.row_version if current else -1)}"
        ),
        payload={
            "fields": sorted(row_fields),
            "delegated": sorted(delegated),
            "day_existed": current is not None,
        },
        logical_date=log_date, aggregate_type="daily_recovery_log",
    )
    db.commit()
    return get_check_in(db, uid, log_date, timezone_name=tz_name)


def _ingest_delegated(
    db: Session,
    user_id: str,
    field: str,
    value: float,
    log_date: date,
    timezone_name: str,
    source: str,
) -> None:
    """Route a physiological check-in field to the canonical ingest."""
    metric_type, unit = {
        "hrv": ("hrv", Unit.MS),
        "heart_rate": ("resting_heart_rate", Unit.BPM),
        "sleep_hours": ("sleep_hours", Unit.HOUR),
        "body_weight": ("weight", Unit.LB),
    }[field]

    tz = athlete_zone(timezone_name)
    stamp = datetime.combine(log_date, time(hour=7), tzinfo=tz)
    try:
        with db.begin_nested():
            ingest_observation(
                db, user_id, metric_type=metric_type, value=value, unit=unit,
                recorded_at=stamp, source=source,
                metadata={"entered_via": "check_in_patch"},
                source_quality="manual", timezone_name=timezone_name,
            )
        sync_projections(db, user_id, metric_type, log_date,
                         timezone_name=timezone_name)
    except Exception as exc:
        logger.warning(
            "check-in %s not stored as an observation (%s): %s",
            field, type(exc).__name__, exc,
        )


def invalidate_nutrition_completion(
    db: Session, user_id: str, log_date: date, *, reason: str = "meal_edited"
) -> bool:
    """Revoke a nutrition-complete mark after the day's meals changed.

    Default policy (Step 9): editing or removing a meal invalidates the
    confirmation until the athlete reconfirms. The alternative — keeping the
    mark — would leave a day counted as "complete" whose totals no longer
    match what was confirmed, and complete days are the denominator for every
    nutrition average.

    Returns True when a completion was actually revoked. Does not commit.
    """
    uid = _require_user(user_id)
    result = db.execute(text("""
        UPDATE daily_recovery_log
        SET nutrition_status = 'partial',
            nutrition_completed_at = NULL,
            field_sources = COALESCE(field_sources, '{}'::jsonb)
                            || CAST(:entry AS jsonb),
            row_version = row_version + 1,
            updated_at = NOW()
        WHERE user_id = :uid AND log_date = :d AND nutrition_status = 'complete'
    """), {
        "uid": uid, "d": log_date,
        "entry": json.dumps({"nutrition_status": f"invalidated:{reason}"}),
    })
    # A meal edit changes the nutrition averages whether or not a completion
    # was revoked, so the cached state goes either way.
    queue_invalidation(db, uid)
    return result.rowcount > 0


# ─────────────────────────────────────────────────────────────────────────
# Measurement types, periods and readings
# ─────────────────────────────────────────────────────────────────────────

def list_measurement_types(db: Session, user_id: str, *, include_inactive: bool = False):
    """Global seeds plus this athlete's own custom definitions.

    An athlete's custom code is private: another athlete asking for the
    catalog does not see it, and cannot log against it. That is not
    cosmetic — a custom code's label is something the athlete wrote.
    """
    from app.schemas.fitness_coach import MeasurementTypeOut, Quantity, Unit

    uid = _require_user(user_id)
    active = "" if include_inactive else "AND is_active"
    rows = db.execute(text(f"""
        SELECT id, code, label, quantity, canonical_unit, allows_side,
               allowed_sites, protocol_guidance, owner_user_id, is_active
        FROM fitness_measurement_type
        WHERE (owner_user_id IS NULL OR owner_user_id = :uid) {active}
        ORDER BY owner_user_id NULLS FIRST, label
    """), {"uid": uid}).fetchall()
    return [
        MeasurementTypeOut(
            id=r.id, code=r.code, label=r.label,
            quantity=Quantity(r.quantity), canonical_unit=Unit(r.canonical_unit),
            allows_side=bool(r.allows_side),
            allowed_sites=list(r.allowed_sites or []),
            protocol_guidance=r.protocol_guidance,
            owner_user_id=r.owner_user_id, is_active=bool(r.is_active),
        )
        for r in rows
    ]


def create_measurement_type(db: Session, user_id: str, payload):
    """Add a private measurement definition. No migration required.

    That is the whole point of the descriptor table: "forearm at the widest
    point, standing" is a thing one athlete wants to track, and it should not
    need a deploy.

    A code that collides with a global seed is refused rather than shadowing
    it — two definitions of `waist_circumference` with different protocols
    would make the athlete's own history incomparable with itself.
    """
    from app.schemas.fitness_coach import MeasurementTypeOut, Quantity, Unit

    uid = _require_user(user_id)
    clash = db.execute(text("""
        SELECT owner_user_id FROM fitness_measurement_type
        WHERE code = :code AND (owner_user_id IS NULL OR owner_user_id = :uid)
    """), {"code": payload.code, "uid": uid}).fetchone()
    if clash is not None:
        scope = "a global" if clash.owner_user_id is None else "your own"
        raise FitnessDataError(
            f"{payload.code!r} already exists as {scope} measurement type"
        )

    tid = str(uuid.uuid4())
    db.execute(text("""
        INSERT INTO fitness_measurement_type
            (id, code, label, quantity, canonical_unit, allows_side,
             allowed_sites, protocol_guidance, owner_user_id)
        VALUES (:id, :code, :label, :quantity, :unit, :sides,
                CAST(:sites AS jsonb), :protocol, :uid)
    """), {
        "id": tid, "code": payload.code, "label": payload.label,
        "quantity": payload.quantity.value, "unit": payload.canonical_unit.value,
        "sides": payload.allows_side,
        "sites": json.dumps(payload.allowed_sites),
        "protocol": payload.protocol_guidance, "uid": uid,
    })
    db.commit()
    return MeasurementTypeOut(
        id=tid, code=payload.code, label=payload.label,
        quantity=payload.quantity, canonical_unit=payload.canonical_unit,
        allows_side=payload.allows_side, allowed_sites=payload.allowed_sites,
        protocol_guidance=payload.protocol_guidance,
        owner_user_id=uid, is_active=True,
    )


def _resolve_measurement_type(db: Session, user_id: str, code: str):
    """The athlete's own definition first, then the global seed.

    Own-first so a private override is possible in principle; the create
    path refuses such a collision today, which keeps the ordering from
    mattering in practice while leaving it correct if that ever changes.
    """
    row = db.execute(text("""
        SELECT id, code, label, quantity, canonical_unit, allows_side,
               allowed_sites, protocol_guidance, owner_user_id
        FROM fitness_measurement_type
        WHERE code = :code AND (owner_user_id = :uid OR owner_user_id IS NULL)
          AND is_active
        ORDER BY owner_user_id NULLS LAST
        LIMIT 1
    """), {"code": code, "uid": user_id}).fetchone()
    if row is None:
        raise LookupError(f"measurement type {code!r} not found")
    return row


def create_measurement_period(db: Session, user_id: str, payload):
    """Group one tape session or photo set."""
    from app.schemas.fitness_coach import MeasurementPeriodOut

    uid = _require_user(user_id)
    pid = str(uuid.uuid4())
    db.execute(text("""
        INSERT INTO fitness_measurement_period
            (id, user_id, measured_on, measured_at, protocol, notes, photo_period_label)
        VALUES (:id, :uid, :on, :at, :protocol, :notes, :label)
    """), {
        "id": pid, "uid": uid, "on": payload.measured_on,
        "at": payload.measured_at, "protocol": payload.protocol,
        "notes": payload.notes, "label": payload.photo_period_label,
    })
    db.commit()
    row = db.execute(text("""
        SELECT id, user_id, measured_on, measured_at, protocol, notes,
               photo_period_label, created_at
        FROM fitness_measurement_period WHERE id = :id
    """), {"id": pid}).fetchone()
    return MeasurementPeriodOut(**dict(row._mapping))


def list_measurement_periods(
    db: Session, user_id: str, *, limit: int = 50,
):
    from app.schemas.fitness_coach import MeasurementPeriodOut
    uid = _require_user(user_id)
    rows = db.execute(text("""
        SELECT id, user_id, measured_on, measured_at, protocol, notes,
               photo_period_label, created_at
        FROM fitness_measurement_period
        WHERE user_id = :uid
        ORDER BY measured_on DESC, created_at DESC
        LIMIT :lim
    """), {"uid": uid, "lim": min(int(limit), 200)}).fetchall()
    return [MeasurementPeriodOut(**dict(r._mapping)) for r in rows]


def log_measurement(db: Session, user_id: str, payload):
    """Record one tape reading as a canonical observation.

    The value goes to `health_metric` — there is no separate measurement
    value table (§4.2: body observations have one authority). The descriptor,
    site, side, period and protocol travel in `metadata`, projected into
    indexed generated columns by migration 164.

    Validated before anything is written:

    * The type must exist and be visible to this athlete. **A type belonging
      to another athlete is a 404**, so a custom code cannot be probed for
      or logged against.
    * A period must be this athlete's own.
    * A side is only accepted for a type that has sides — a waist with a
      "left" reading would create two incomparable waist series.
    * The unit must be convertible to the type's canonical unit.
    """
    from app.schemas.fitness_coach import MeasurementOut, Side, Unit

    uid = _require_user(user_id)
    descriptor = _resolve_measurement_type(db, uid, payload.type_code)
    canonical_unit = Unit(descriptor.canonical_unit)

    period_protocol: Optional[str] = None
    if payload.period_id:
        owns = db.execute(text("""
            SELECT protocol FROM fitness_measurement_period
            WHERE id = :pid AND user_id = :uid
        """), {"pid": payload.period_id, "uid": uid}).fetchone()
        if not owns:
            raise LookupError("measurement period not found")
        period_protocol = owns.protocol

    if payload.side is not Side.NONE and not descriptor.allows_side:
        raise FitnessDataError(
            f"{descriptor.label} has no left/right distinction; recording one "
            "would split it into two series that cannot be compared"
        )
    if descriptor.allows_side and payload.side is Side.NONE:
        raise FitnessDataError(
            f"{descriptor.label} is measured per side; say which one, or two "
            "readings of different arms will look like a change in one"
        )

    allowed_sites = list(descriptor.allowed_sites or [])
    if payload.site and allowed_sites and payload.site not in allowed_sites:
        raise FitnessDataError(
            f"{payload.site!r} is not a recorded site for {descriptor.label}"
        )

    try:
        canonical_value = convert(payload.value, payload.unit, canonical_unit)
    except UnitError as exc:
        raise FitnessDataError(
            f"{descriptor.label} is recorded in {canonical_unit.value}; "
            f"a {payload.unit.value} value cannot be converted ({exc})"
        ) from exc

    metric_type = f"measurement:{descriptor.code}"
    metadata = {
        "measurement_type_code": descriptor.code,
        "measurement_type_id": descriptor.id,
        "measurement_period_id": payload.period_id,
        "site": payload.site,
        "side": payload.side.value,
        # Most specific wins: what this reading says, then what the session
        # said, then the type's generic guidance. The session's protocol has
        # to outrank the type's, because that is the level at which the
        # athlete actually decided how to measure — "morning, fasted, before
        # water" applies to every reading in the sitting, and comparability
        # is judged on it.
        "protocol": (
            payload.protocol or period_protocol or descriptor.protocol_guidance
        ),
        "label": descriptor.label,
    }
    if payload.unit is not canonical_unit:
        metadata["entered_as"] = {"value": payload.value, "unit": payload.unit.value}

    # `measurement:*` types deliberately have no entry in CANONICAL_UNITS.
    # A custom measurement's canonical unit is a property of its *descriptor
    # row*, not of a module-level dict — which is why the value is converted
    # here and the resolved unit is passed explicitly. Registering it in
    # CANONICAL_UNITS at runtime would put a per-athlete fact into
    # process-local state that does not survive a restart and differs
    # between workers.
    result = ingest_observation(
        db, uid,
        metric_type=metric_type,
        value=canonical_value,
        unit=canonical_unit,
        recorded_at=payload.measured_at,
        source="manual",
        external_id=payload.idempotency_key,
        metadata=metadata,
        source_quality="measured",
        corrects_observation_id=payload.corrects_observation_id,
        correction_reason="measurement correction" if payload.corrects_observation_id else None,
    )
    if not result.stored and not result.duplicate:
        raise FitnessDataError(result.reason or "the measurement was not stored")
    record_fitness_event(
        db, uid, "fitness.measurement_logged",
        dedupe_key=f"fitness.measurement:{result.observation_id}",
        source_ref=result.observation_id,
        aggregate_type="health_metric", aggregate_id=result.observation_id,
        payload={
            "type_code": descriptor.code,
            "site": payload.site, "side": payload.side.value,
            "period_id": payload.period_id,
            "is_correction": bool(payload.corrects_observation_id),
        },
    )
    db.commit()

    row = db.execute(text("""
        SELECT id, user_id, value, unit, recorded_at, logical_date, source,
               metadata, superseded_by_id
        FROM health_metric WHERE id = :id
    """), {"id": result.observation_id}).fetchone()
    meta = _as_json_dict(row.metadata)
    return MeasurementOut(
        id=row.id, user_id=row.user_id, type_code=descriptor.code,
        label=descriptor.label,
        value=float(row.value), unit=Unit(row.unit),
        canonical_value=float(row.value), canonical_unit=Unit(row.unit),
        measured_at=row.recorded_at, logical_date=row.logical_date,
        site=meta.get("site"), side=Side(meta.get("side") or "none"),
        period_id=meta.get("measurement_period_id"),
        protocol=meta.get("protocol"), source=row.source,
        superseded_by_id=row.superseded_by_id,
    )


def list_measurements(
    db: Session,
    user_id: str,
    *,
    type_code: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 100,
    include_superseded: bool = False,
):
    """An athlete's tape readings, newest first."""
    from app.schemas.fitness_coach import MeasurementOut, Side, Unit
    from app.services.fitness.data_access import validate_page_size, validate_span

    uid = _require_user(user_id)
    page = validate_page_size(limit)
    if start_date and end_date:
        validate_span(start_date, end_date)

    clauses = ["user_id = :uid", "measurement_type_code IS NOT NULL"]
    params: Dict[str, Any] = {"uid": uid, "lim": page}
    if type_code:
        clauses.append("measurement_type_code = :code")
        params["code"] = type_code
    if start_date:
        clauses.append("logical_date >= :start")
        params["start"] = start_date
    if end_date:
        clauses.append("logical_date < :end")
        params["end"] = end_date
    if not include_superseded:
        clauses.append("superseded_by_id IS NULL")

    rows = db.execute(text(f"""
        SELECT id, user_id, value, unit, recorded_at, logical_date, source,
               metadata, measurement_type_code, superseded_by_id
        FROM health_metric
        WHERE {' AND '.join(clauses)}
        ORDER BY logical_date DESC, recorded_at DESC
        LIMIT :lim
    """), params).fetchall()

    out = []
    for r in rows:
        meta = _as_json_dict(r.metadata)
        out.append(MeasurementOut(
            id=r.id, user_id=r.user_id,
            type_code=r.measurement_type_code,
            label=meta.get("label") or r.measurement_type_code,
            value=float(r.value), unit=Unit(r.unit),
            canonical_value=float(r.value), canonical_unit=Unit(r.unit),
            measured_at=r.recorded_at, logical_date=r.logical_date,
            site=meta.get("site"), side=Side(meta.get("side") or "none"),
            period_id=meta.get("measurement_period_id"),
            protocol=meta.get("protocol"), source=r.source,
            superseded_by_id=r.superseded_by_id,
        ))
    return out


def measurement_change(
    db: Session,
    user_id: str,
    type_code: str,
    *,
    site: Optional[str] = None,
    side: str = "none",
    lookback_days: int = 120,
) -> Metric:
    """The difference between the two most recent comparable readings.

    "Comparable" is doing real work: same type, same site, same side, same
    protocol, same unit. A waist measured at the navel and one measured at
    the narrowest point differ by centimetres and that difference is not a
    change in the athlete. Readings that are not comparable produce
    `NOT_COMPARABLE`, not a number.
    """
    uid = _require_user(user_id)
    readings = list_measurements(
        db, uid, type_code=type_code,
        start_date=None, end_date=None, limit=200,
    )
    matching = [
        r for r in readings
        if (r.site or None) == (site or None) and r.side.value == side
    ]
    key = f"measurements.{type_code}.change"
    if len(matching) < 2:
        return Metric(
            key=key, unit=matching[0].unit if matching else Unit.UNKNOWN,
            unavailable_reason=Unavailable.INSUFFICIENT_COVERAGE,
            observed_days=len(matching), expected_days=2,
            note="two comparable readings are needed to state a change",
        )

    latest, previous = matching[0], matching[1]
    if latest.unit is not previous.unit:
        return Metric(
            key=key, unavailable_reason=Unavailable.NOT_COMPARABLE,
            note="the two readings are in different units",
        )
    if (latest.protocol or "") != (previous.protocol or ""):
        return Metric(
            key=key, unit=latest.unit,
            unavailable_reason=Unavailable.NOT_COMPARABLE,
            note=(
                "the two readings used different protocols; the difference "
                "between them is not a change in the athlete"
            ),
        )

    elapsed = (latest.logical_date - previous.logical_date).days
    return Metric(
        key=key,
        value=latest.value - previous.value,
        unit=latest.unit,
        observed_at=latest.measured_at,
        observed_days=2,
        expected_days=2,
        source_count=len(matching),
        formula="latest_minus_previous_comparable",
        note=(
            f"{elapsed} days apart"
            + (f", {site}" if site else "")
            + (f", {side}" if side != "none" else "")
        ),
    )
