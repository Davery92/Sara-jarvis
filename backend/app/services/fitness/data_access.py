"""Owner-scoped bounded reads and legacy row/time/unit adapters.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 3. This is deliberately *not* a
generic repository framework. It is the one place that knows the awkward
truths about the existing fitness tables, so that analytics, state, reviews
and the routes do not each learn them separately and disagree:

* **`food_log.logged_at` is naive ET wall-clock**, while its `created_at` is
  naive UTC. Aggregating meals by `created_at` moves a 9pm dinner into the
  next day. `health_metric.recorded_at` and the workout tables are aware
  timestamptz. Three conventions, one converter.
* **Athlete-local calendar days** come from the athlete's own timezone, not
  the process default. A traveling athlete's "yesterday" is not the server's.
* **`workout_log.weight` is an INTEGER.** It cannot hold a 2.5 kg jump. The
  effective-load adapter here is the only thing that decides what a set
  actually lifted, and it is shared with recalc and progression so a
  correction cannot leave two different answers.
* **Unknown units stay unknown.** No helper here guesses lbs from magnitude.

Transaction rule: nothing in this module commits. Readers read; the mutation
services own the unit of work and return only after their own commit. That
keeps network/model work outside any open transaction.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.timezone import USER_TIMEZONE, UTC
from app.schemas.fitness_coach import (
    Quality,
    Unit,
    UnitError,
    ensure_finite,
    to_kg,
)

logger = logging.getLogger(__name__)

# Bounds. Every collection read is capped so a date-span parameter cannot turn
# into a full-table scan of someone's multi-year history.
MAX_DAY_SPAN = 400
MAX_ROWS = 5000
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500


class FitnessDataError(ValueError):
    """A bad request shape, caught before it reaches SQL."""


# ─────────────────────────────────────────────────────────────────────────
# Timezone and period handling
# ─────────────────────────────────────────────────────────────────────────

def athlete_zone(timezone_name: Optional[str]) -> ZoneInfo:
    """The athlete's timezone, defaulting to Sara's existing ET.

    An unknown name falls back rather than raising: a corrupt profile field
    must not make a read of someone's weight history impossible. It is logged,
    and the profile validator rejects bad names on write.
    """
    if not timezone_name:
        return USER_TIMEZONE
    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("unknown athlete timezone %r — falling back to ET", timezone_name)
        return USER_TIMEZONE


def local_day_bounds(day: date, tz: ZoneInfo) -> Tuple[datetime, datetime]:
    """Aware UTC `[start, end)` for one athlete-local calendar day.

    A DST day is 23 or 25 hours long. Computing this as `start + 24h` is the
    bug that puts a 1am Sunday reading in Saturday twice a year.
    """
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def local_range_bounds(start: date, end: date, tz: ZoneInfo) -> Tuple[datetime, datetime]:
    """Aware UTC bounds for a half-open athlete-local date range."""
    validate_span(start, end)
    start_at, _ = local_day_bounds(start, tz)
    # `end` is exclusive, so the range stops at the start of that local day.
    end_at = datetime.combine(end, time.min, tzinfo=tz).astimezone(UTC)
    return start_at, end_at


def validate_span(start: date, end: date, *, max_days: int = MAX_DAY_SPAN) -> None:
    if end < start:
        raise FitnessDataError(f"range end {end} precedes start {start}")
    if (end - start).days > max_days:
        raise FitnessDataError(
            f"range of {(end - start).days} days exceeds the {max_days}-day cap"
        )


def validate_page_size(limit: Optional[int]) -> int:
    if limit is None:
        return DEFAULT_PAGE_SIZE
    n = int(limit)
    if n < 1:
        raise FitnessDataError("limit must be at least 1")
    return min(n, MAX_PAGE_SIZE)


def local_date_of(moment: Optional[datetime], tz: ZoneInfo) -> Optional[date]:
    """The athlete-local calendar date an aware instant falls on."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        # Aware-vs-naive is a per-column fact; a caller that reaches here with
        # a naive value has skipped the right adapter. Assume UTC and flag it
        # rather than silently shifting by the local offset.
        logger.debug("local_date_of received a naive datetime; assuming UTC")
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(tz).date()


def naive_et_to_utc(moment: Optional[datetime]) -> Optional[datetime]:
    """`food_log.logged_at` → aware UTC.

    That column is `timestamp without time zone` holding ET wall-clock. It is
    the only fitness column with this convention and the reason this function
    exists separately from the UTC one.
    """
    if moment is None:
        return None
    if moment.tzinfo is not None:
        return moment.astimezone(UTC)
    return moment.replace(tzinfo=USER_TIMEZONE).astimezone(UTC)


def naive_utc_to_utc(moment: Optional[datetime]) -> Optional[datetime]:
    """A naive-UTC legacy column (`created_at` on several tables) → aware UTC."""
    if moment is None:
        return None
    if moment.tzinfo is not None:
        return moment.astimezone(UTC)
    return moment.replace(tzinfo=UTC)


def as_aware_utc(moment: Optional[datetime]) -> Optional[datetime]:
    """An already-aware timestamptz column → UTC, unchanged in meaning."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        raise FitnessDataError(
            "expected an aware timestamp; use naive_et_to_utc or naive_utc_to_utc "
            "for the legacy naive columns instead of guessing here"
        )
    return moment.astimezone(UTC)


# ─────────────────────────────────────────────────────────────────────────
# Unit adapters for legacy rows
# ─────────────────────────────────────────────────────────────────────────

# `health_metric` had no unit column before migration 162. These are the units
# the existing writers actually used, traced from the ingest paths — not a
# guess from value magnitude. A type absent here resolves to UNKNOWN.
LEGACY_METRIC_UNITS: Dict[str, Unit] = {
    "weight": Unit.LB,
    "body_weight": Unit.LB,
    "sleep_hours": Unit.HOUR,
    "sleep_duration": Unit.HOUR,
    "sleep": Unit.HOUR,
    "steps": Unit.COUNT,
    "water": Unit.ML,
    "water_ml": Unit.ML,
    "hrv": Unit.MS,
    "heart_rate": Unit.BPM,
    "resting_heart_rate": Unit.BPM,
    "resting_hr": Unit.BPM,
    "vo2_max": Unit.COUNT,
    "body_fat_percent": Unit.PERCENT,
}

# Sleep has been written under several type names over time. Analytics must
# treat them as one stream, and must NOT sum two of them for the same night.
SLEEP_METRIC_ALIASES = ("sleep_hours", "sleep_duration", "sleep")
WEIGHT_METRIC_ALIASES = ("weight", "body_weight")


def resolve_metric_unit(metric_type: str, stored_unit: Optional[str]) -> Unit:
    """The unit of one observation: stored first, traced legacy second.

    An unrecognised stored unit is UNKNOWN, not the legacy default — a writer
    that recorded something unexpected is a conflict to surface, not to
    paper over.
    """
    if stored_unit:
        try:
            return Unit(stored_unit)
        except ValueError:
            logger.warning("unrecognised stored unit %r on %s", stored_unit, metric_type)
            return Unit.UNKNOWN
    return LEGACY_METRIC_UNITS.get(metric_type, Unit.UNKNOWN)


# ─────────────────────────────────────────────────────────────────────────
# Row adapters
# ─────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Observation:
    """One canonical physical observation, unit-explicit."""
    id: str
    user_id: str
    metric_type: str
    value: float
    unit: Unit
    recorded_at: datetime          # aware UTC
    logical_date: date             # athlete-local
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    external_id: Optional[str] = None
    original_value: Optional[float] = None
    original_unit: Optional[Unit] = None
    superseded_by_id: Optional[str] = None
    quality_flags: Tuple[Quality, ...] = ()

    @property
    def value_kg(self) -> Optional[float]:
        """Mass in kg, or None when the unit is not a mass or is unknown."""
        try:
            return to_kg(self.value, self.unit)
        except UnitError:
            return None

    @property
    def is_superseded(self) -> bool:
        return self.superseded_by_id is not None


@dataclass(frozen=True)
class FoodDay:
    """One athlete-local day of meals. Unknown macros stay unknown."""
    logical_date: date
    calories: Optional[float]
    protein_g: Optional[float]
    carbs_g: Optional[float]
    fat_g: Optional[float]
    meal_count: int
    # Per-field counts, because a day can know calories and not know fat.
    known_fields: Dict[str, int] = field(default_factory=dict)
    has_estimated_items: bool = False
    last_logged_at: Optional[datetime] = None


@dataclass(frozen=True)
class SetRow:
    """One performed set, with the effective load resolved exactly once."""
    id: str
    user_id: str
    exercise_id: Optional[str]
    exercise_library_id: Optional[str]
    set_index: Optional[int]
    reps: Optional[int]
    legacy_weight: Optional[int]
    load: Optional[float]
    load_unit: Unit
    rir: Optional[float]
    rpe: Optional[float]
    set_kind: str
    set_role: Optional[str]
    counts_toward_target: bool
    voided_at: Optional[datetime]
    skipped: bool
    is_failure: bool
    parent_set_id: Optional[str]
    set_group_id: Optional[str]
    group_sequence: int
    active_session_id: Optional[str]
    session_id: Optional[str]
    exercise_performance_id: Optional[str]
    logged_at: Optional[datetime]
    session_date: Optional[date]

    @property
    def is_live(self) -> bool:
        """Counts as performed: not voided, not skipped."""
        return self.voided_at is None and not self.skipped

    @property
    def is_working(self) -> bool:
        return self.set_kind == "working"

    @property
    def load_kg(self) -> Optional[float]:
        try:
            return to_kg(self.load, self.load_unit)
        except UnitError:
            return None


@dataclass(frozen=True)
class TrainingSessionRow:
    """One de-duplicated session.

    `workout_session` (planned), `active_workout_session` (performed) and the
    legacy `workout` aggregate can all describe the same training bout. This
    is the single projection; counting all three is how "three sessions
    today" happens.
    """
    key: str
    user_id: str
    session_date: Optional[date]
    planned_session_id: Optional[str]
    active_session_id: Optional[str]
    template_id: Optional[str]
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    was_planned: bool
    total_sets_completed: int = 0
    snapshot: Dict[str, Any] = field(default_factory=dict)


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return ensure_finite(float(value))


def _as_json(value: Any) -> Dict[str, Any]:
    """JSON/JSONB/TEXT columns all parse the same way here.

    `fitness_template.exercises` is TEXT holding JSON while
    `active_workout_session.workout_snapshot` is real JSONB. Both reach
    readers through this, so a string and an object behave identically.
    """
    if value is None:
        return {}
    if isinstance(value, (dict, list)):
        return value  # type: ignore[return-value]
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", "replace")
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return {}
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            logger.warning("unparseable JSON column (%d chars)", len(stripped))
            return {}
    return {}


def parse_json_column(value: Any) -> Any:
    """Public alias — template readers need the list form too."""
    return _as_json(value)


def effective_load(row: Any) -> Tuple[Optional[float], Unit]:
    """The one answer to "what did this set actually lift".

    Precedence is deliberate: the fractional `load_value`/`load_unit` pair
    added by migration 166 wins when present, because the legacy integer
    `weight` column is a *projection* of it that has already lost the
    fraction. Reading the integer first would turn a 102.5 lb set into 102 lb
    for every analytics consumer, and the rounding would look like a plateau.

    Shared with `workout_recalc` and `progressive_overload` so a correction
    cannot leave two surfaces disagreeing about the same set.
    """
    mapping = row._mapping if hasattr(row, "_mapping") else row
    fractional = mapping.get("load_value") if hasattr(mapping, "get") else None
    if fractional is not None:
        unit = mapping.get("load_unit")
        resolved = Unit(unit) if unit else Unit.LB
        return _as_float(fractional), resolved
    legacy = mapping.get("weight") if hasattr(mapping, "get") else None
    if legacy is None:
        return None, Unit.UNKNOWN
    # The legacy contract is pounds: that is what every existing client sends
    # and what `exercise_pr.weight` compares against.
    return _as_float(legacy), Unit.LB


def adapt_set_row(row: Any, *, tz: ZoneInfo) -> SetRow:
    m = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    load, load_unit = effective_load(m)
    logged = m.get("session_time") or m.get("logged_at") or m.get("created_at")
    logged_at = as_aware_utc(logged) if logged is not None and logged.tzinfo else naive_utc_to_utc(logged)
    return SetRow(
        id=m["id"],
        user_id=m.get("user_id", ""),
        exercise_id=m.get("exercise_id"),
        exercise_library_id=m.get("exercise_library_id"),
        set_index=m.get("set_index"),
        reps=m.get("reps"),
        legacy_weight=m.get("weight"),
        load=load,
        load_unit=load_unit,
        rir=_as_float(m.get("rir")),
        rpe=_as_float(m.get("rpe_decimal") if m.get("rpe_decimal") is not None else m.get("rpe")),
        set_kind=m.get("set_kind") or "working",
        set_role=m.get("set_role"),
        counts_toward_target=bool(m.get("counts_toward_target", True)),
        voided_at=m.get("voided_at"),
        skipped=bool(m.get("skipped") or False),
        is_failure=bool(m.get("is_failure") or False),
        parent_set_id=m.get("parent_set_id"),
        set_group_id=m.get("set_group_id"),
        group_sequence=int(m.get("group_sequence") or 0),
        active_session_id=m.get("active_session_id"),
        session_id=m.get("session_id"),
        exercise_performance_id=m.get("exercise_performance_id"),
        logged_at=logged_at,
        session_date=m.get("session_date"),
    )


# ─────────────────────────────────────────────────────────────────────────
# Owner-scoped queries
# ─────────────────────────────────────────────────────────────────────────

def _require_user(user_id: Optional[str]) -> str:
    """No helper in this module has a default user.

    The entire reason Step 2 existed is that one did. A missing user_id is a
    programming error, raised loudly, never resolved to an owner.
    """
    if not user_id or not str(user_id).strip():
        raise FitnessDataError(
            "user_id is required: fitness data access has no default owner"
        )
    return str(user_id)


def _observation_columns(db: Session) -> Dict[str, bool]:
    """Which of migration 162's additive columns this database actually has.

    The same code must read a pre-162 schema (the pinned production
    generation) and a post-162 one. Probing beats a feature flag because it
    cannot drift from reality.
    """
    rows = db.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'health_metric'
    """)).fetchall()
    present = {r[0] for r in rows}
    return {
        "unit": "unit" in present,
        "external_id": "external_id" in present,
        "original_value": "original_value" in present,
        "logical_date": "logical_date" in present,
        "superseded_by_id": "superseded_by_id" in present,
        "source_quality": "source_quality" in present,
    }


def load_observations(
    db: Session,
    user_id: str,
    metric_types: Sequence[str],
    start_at: datetime,
    end_at: datetime,
    *,
    timezone_name: Optional[str] = None,
    include_superseded: bool = False,
    limit: int = MAX_ROWS,
) -> List[Observation]:
    """Canonical physical observations in `[start_at, end_at)`, owner-scoped.

    Half-open on purpose: a closed upper bound double-counts a reading taken
    exactly at local midnight when two adjacent windows are compared.
    """
    uid = _require_user(user_id)
    if not metric_types:
        return []
    if end_at < start_at:
        raise FitnessDataError("end_at precedes start_at")
    tz = athlete_zone(timezone_name)
    cols = _observation_columns(db)

    select_extra = ", ".join(
        filter(None, [
            "unit" if cols["unit"] else "NULL AS unit",
            "external_id" if cols["external_id"] else "NULL AS external_id",
            "original_value" if cols["original_value"] else "NULL AS original_value",
            "original_unit" if cols["original_value"] else "NULL AS original_unit",
            "logical_date" if cols["logical_date"] else "NULL AS logical_date",
            "superseded_by_id" if cols["superseded_by_id"] else "NULL AS superseded_by_id",
            "source_quality" if cols["source_quality"] else "NULL AS source_quality",
        ])
    )
    superseded_filter = ""
    if not include_superseded and cols["superseded_by_id"]:
        superseded_filter = "AND superseded_by_id IS NULL"

    rows = db.execute(text(f"""
        SELECT id, user_id, metric_type, value, recorded_at, source, metadata,
               {select_extra}
        FROM health_metric
        WHERE user_id = :uid
          AND metric_type = ANY(:types)
          AND recorded_at >= :start_at
          AND recorded_at <  :end_at
          {superseded_filter}
        ORDER BY recorded_at ASC, id ASC
        LIMIT :lim
    """), {
        "uid": uid,
        "types": list(metric_types),
        "start_at": start_at,
        "end_at": end_at,
        "lim": min(int(limit), MAX_ROWS),
    }).fetchall()

    out: List[Observation] = []
    for r in rows:
        m = dict(r._mapping)
        unit = resolve_metric_unit(m["metric_type"], m.get("unit"))
        flags: List[Quality] = []
        if unit is Unit.UNKNOWN:
            flags.append(Quality.UNRESOLVED_IDENTITY)
        meta = _as_json(m.get("metadata"))
        if isinstance(meta, dict) and meta.get("backfilled"):
            flags.append(Quality.BACKFILLED)
        recorded_at = as_aware_utc(m["recorded_at"])
        logical = m.get("logical_date") or local_date_of(recorded_at, tz)
        original_unit = None
        if m.get("original_unit"):
            try:
                original_unit = Unit(m["original_unit"])
            except ValueError:
                original_unit = Unit.UNKNOWN
        out.append(Observation(
            id=m["id"],
            user_id=m["user_id"],
            metric_type=m["metric_type"],
            value=_as_float(m["value"]),
            unit=unit,
            recorded_at=recorded_at,
            logical_date=logical,
            source=m.get("source") or "unknown",
            metadata=meta if isinstance(meta, dict) else {},
            external_id=m.get("external_id"),
            original_value=_as_float(m.get("original_value")),
            original_unit=original_unit,
            superseded_by_id=m.get("superseded_by_id"),
            quality_flags=tuple(flags),
        ))
    return out


def load_food_days(
    db: Session,
    user_id: str,
    start_date: date,
    end_date: date,
    *,
    timezone_name: Optional[str] = None,
) -> Dict[date, FoodDay]:
    """Meals aggregated by athlete-local day in `[start_date, end_date)`.

    Grouped on `logged_at` — the time the food was eaten — never
    `created_at`, which is when the row was inserted. A meal logged the next
    morning belongs to the night before.

    Per-field denominators are tracked because a day can have a known calorie
    total and an unknown fat total; averaging the latter as zero understates
    it, and averaging over the same denominator as calories misreports
    coverage.
    """
    uid = _require_user(user_id)
    validate_span(start_date, end_date)
    tz = athlete_zone(timezone_name)

    # logged_at is naive ET wall-clock, so the bounds are naive ET too: a
    # timestamptz bound would be silently cast and shift by the UTC offset.
    rows = db.execute(text("""
        SELECT id, calories, protein, carbs, fats, logged_at, detailed_items
        FROM food_log
        WHERE user_id = :uid
          AND logged_at >= :start_at
          AND logged_at <  :end_at
        ORDER BY logged_at ASC
        LIMIT :lim
    """), {
        "uid": uid,
        "start_at": datetime.combine(start_date, time.min),
        "end_at": datetime.combine(end_date, time.min),
        "lim": MAX_ROWS,
    }).fetchall()

    acc: Dict[date, Dict[str, Any]] = {}
    for r in rows:
        m = dict(r._mapping)
        logged_naive_et: datetime = m["logged_at"]
        day = logged_naive_et.date()
        if tz is not USER_TIMEZONE:
            # Reinterpret the stored ET wall-clock in the athlete's zone so a
            # relocated athlete's day boundaries follow them.
            day = local_date_of(naive_et_to_utc(logged_naive_et), tz)
        bucket = acc.setdefault(day, {
            "calories": None, "protein": None, "carbs": None, "fats": None,
            "meals": 0, "known": {}, "estimated": False, "last": None,
        })
        bucket["meals"] += 1
        bucket["last"] = max(
            filter(None, [bucket["last"], naive_et_to_utc(logged_naive_et)])
        )
        for src, dst in (("calories", "calories"), ("protein", "protein"),
                         ("carbs", "carbs"), ("fats", "fats")):
            v = _as_float(m.get(src))
            if v is None:
                continue
            bucket[dst] = (bucket[dst] or 0.0) + v
            bucket["known"][dst] = bucket["known"].get(dst, 0) + 1
        items = _as_json(m.get("detailed_items"))
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("nutrition_basis") == "estimated":
                    bucket["estimated"] = True
                    break

    return {
        day: FoodDay(
            logical_date=day,
            calories=b["calories"],
            protein_g=b["protein"],
            carbs_g=b["carbs"],
            fat_g=b["fats"],
            meal_count=b["meals"],
            known_fields=dict(b["known"]),
            has_estimated_items=b["estimated"],
            last_logged_at=b["last"],
        )
        for day, b in sorted(acc.items())
    }


def load_check_ins(
    db: Session,
    user_id: str,
    start_date: date,
    end_date: date,
) -> Dict[date, Dict[str, Any]]:
    """`daily_recovery_log` rows in `[start_date, end_date)`, keyed by date."""
    uid = _require_user(user_id)
    validate_span(start_date, end_date)
    present = {
        r[0] for r in db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'daily_recovery_log'
        """)).fetchall()
    }
    extended = [
        c for c in (
            "bedtime_at", "wake_at", "sleep_quality", "energy", "fatigue",
            "stress", "motivation", "subjective_readiness",
            "nutrition_status", "nutrition_completed_at", "row_version",
            "field_sources",
        ) if c in present
    ]
    extra = ("," + ", ".join(extended)) if extended else ""
    rows = db.execute(text(f"""
        SELECT id, user_id, log_date, hrv, heart_rate, sleep_hours,
               soreness_level, notes, body_weight, weight_unit,
               created_at, updated_at {extra}
        FROM daily_recovery_log
        WHERE user_id = :uid AND log_date >= :start AND log_date < :end
        ORDER BY log_date ASC
        LIMIT :lim
    """), {"uid": uid, "start": start_date, "end": end_date, "lim": MAX_ROWS}).fetchall()
    out: Dict[date, Dict[str, Any]] = {}
    for r in rows:
        m = dict(r._mapping)
        if "field_sources" in m:
            m["field_sources"] = _as_json(m.get("field_sources")) or {}
        out[m["log_date"]] = m
    return out


def load_training_sessions(
    db: Session,
    user_id: str,
    start_date: date,
    end_date: date,
) -> List[TrainingSessionRow]:
    """One row per real training bout in `[start_date, end_date)`.

    The de-duplication: a planned `workout_session` that links to an
    `active_workout_session` via `active_session_id` is ONE session. An
    active session with no planned parent is an unplanned session. Two
    sessions on the same date stay two sessions — a two-a-day is not a
    duplicate, which is why the key is the session id and not the date.
    """
    uid = _require_user(user_id)
    validate_span(start_date, end_date)

    planned = db.execute(text("""
        SELECT id, user_id, template_id, session_date, status,
               started_at, completed_at, active_session_id
        FROM workout_session
        WHERE user_id = :uid AND session_date >= :start AND session_date < :end
        ORDER BY session_date ASC, created_at ASC
        LIMIT :lim
    """), {"uid": uid, "start": start_date, "end": end_date, "lim": MAX_ROWS}).fetchall()

    active = db.execute(text("""
        SELECT id, user_id, template_id, status, started_at, completed_at,
               total_sets_completed, workout_snapshot
        FROM active_workout_session
        WHERE user_id = :uid
          AND started_at >= :start_at AND started_at < :end_at
        ORDER BY started_at ASC
        LIMIT :lim
    """), {
        "uid": uid,
        "start_at": datetime.combine(start_date, time.min, tzinfo=UTC) - timedelta(days=1),
        "end_at": datetime.combine(end_date, time.min, tzinfo=UTC) + timedelta(days=1),
        "lim": MAX_ROWS,
    }).fetchall()

    active_by_id = {r._mapping["id"]: dict(r._mapping) for r in active}
    claimed: set[str] = set()
    out: List[TrainingSessionRow] = []

    for r in planned:
        m = dict(r._mapping)
        a = active_by_id.get(m.get("active_session_id")) if m.get("active_session_id") else None
        if a:
            claimed.add(a["id"])
        out.append(TrainingSessionRow(
            key=m["id"],
            user_id=uid,
            session_date=m["session_date"],
            planned_session_id=m["id"],
            active_session_id=(a or {}).get("id"),
            template_id=m.get("template_id") or (a or {}).get("template_id"),
            status=m["status"],
            started_at=(a or {}).get("started_at") or m.get("started_at"),
            completed_at=(a or {}).get("completed_at") or m.get("completed_at"),
            was_planned=True,
            total_sets_completed=int((a or {}).get("total_sets_completed") or 0),
            snapshot=_as_json((a or {}).get("workout_snapshot")) or {},
        ))

    for sid, a in active_by_id.items():
        if sid in claimed:
            continue
        started = a.get("started_at")
        sess_date = started.date() if started else None
        if sess_date is None or not (start_date <= sess_date < end_date):
            continue
        out.append(TrainingSessionRow(
            key=sid,
            user_id=uid,
            session_date=sess_date,
            planned_session_id=None,
            active_session_id=sid,
            template_id=a.get("template_id"),
            status=a.get("status") or "unknown",
            started_at=started,
            completed_at=a.get("completed_at"),
            was_planned=False,
            total_sets_completed=int(a.get("total_sets_completed") or 0),
            snapshot=_as_json(a.get("workout_snapshot")) or {},
        ))

    out.sort(key=lambda s: (s.session_date or date.min, s.started_at or datetime.min.replace(tzinfo=UTC)))
    return out


def load_sets(
    db: Session,
    user_id: str,
    start_date: date,
    end_date: date,
    *,
    timezone_name: Optional[str] = None,
    exercise_library_id: Optional[str] = None,
    include_voided: bool = False,
) -> List[SetRow]:
    """Performed sets in `[start_date, end_date)`, owner-scoped.

    `session_date` is the primary filter with a `session_time`/`created_at`
    fallback, because older rows predate `session_date` being populated.
    """
    uid = _require_user(user_id)
    validate_span(start_date, end_date)
    tz = athlete_zone(timezone_name)

    present = {
        r[0] for r in db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'workout_log'
        """)).fetchall()
    }
    optional = [c for c in ("load_value", "load_unit", "rir", "rpe_decimal",
                            "set_role", "is_failure", "actual_rest_seconds",
                            "tempo", "exercise_performance_id") if c in present]
    extra = ("," + ", ".join(optional)) if optional else ""

    clauses = ["user_id = :uid"]
    params: Dict[str, Any] = {
        "uid": uid, "start": start_date, "end": end_date,
        "start_at": datetime.combine(start_date, time.min, tzinfo=UTC),
        "end_at": datetime.combine(end_date, time.min, tzinfo=UTC),
        "lim": MAX_ROWS,
    }
    clauses.append("""(
        (session_date IS NOT NULL AND session_date >= :start AND session_date < :end)
        OR (session_date IS NULL
            AND COALESCE(session_time, created_at) >= :start_at
            AND COALESCE(session_time, created_at) <  :end_at)
    )""")
    if not include_voided:
        clauses.append("voided_at IS NULL")
    if exercise_library_id:
        clauses.append("exercise_library_id = :elid")
        params["elid"] = exercise_library_id

    rows = db.execute(text(f"""
        SELECT id, user_id, exercise_id, exercise_library_id, set_index, reps,
               weight, rpe, set_kind, parent_set_id, set_group_id,
               group_sequence, counts_toward_target, voided_at, skipped,
               active_session_id, session_id, session_date, session_time,
               created_at, is_pr {extra}
        FROM workout_log
        WHERE {' AND '.join(clauses)}
        ORDER BY COALESCE(session_time, created_at) ASC, group_sequence ASC, id ASC
        LIMIT :lim
    """), params).fetchall()
    return [adapt_set_row(r, tz=tz) for r in rows]


def load_template_snapshot(
    db: Session, user_id: str, template_id: str
) -> Optional[Dict[str, Any]]:
    """One owned template with its JSON and normalized children reconciled.

    `fitness_template.exercises` (TEXT JSON) and `template_exercise` rows are
    both live. This returns both, labelled, so a caller never has to guess
    which one a given field came from.
    """
    uid = _require_user(user_id)
    row = db.execute(text("""
        SELECT id, user_id, phase_id, name, scheduled_days, exercises,
               order_in_phase, notes, starting_weights, day_of_week, rotation_order
        FROM fitness_template
        WHERE id = :tid AND user_id = :uid
    """), {"tid": template_id, "uid": uid}).fetchone()
    if not row:
        return None
    m = dict(row._mapping)
    m["exercises_json"] = _as_json(m.pop("exercises")) or []
    m["starting_weights"] = _as_json(m.get("starting_weights")) or {}
    children = db.execute(text("""
        SELECT te.id, te.exercise_name, te.order_index, te.target_sets,
               te.rep_range_low, te.rep_range_high, te.target_rpe,
               te.rest_seconds, te.progression_rule, te.notes,
               te.metric_type, te.is_per_side, te.superset_group, te.set_technique
        FROM template_exercise te
        WHERE te.template_id = :tid
          AND EXISTS (SELECT 1 FROM fitness_template t
                      WHERE t.id = te.template_id AND t.user_id = :uid)
        ORDER BY te.order_index ASC, te.created_at ASC
    """), {"tid": template_id, "uid": uid}).fetchall()
    m["exercise_rows"] = [dict(c._mapping) for c in children]
    return m


def assert_owned(
    db: Session, user_id: str, table: str, row_id: Optional[str],
    *, owner_column: str = "user_id",
) -> None:
    """Validate a caller-supplied parent id before using it.

    The table name is matched against an allowlist, never interpolated from a
    request: a measurement or tool parameter must not be able to name an
    arbitrary table or column.
    """
    if row_id is None:
        return
    uid = _require_user(user_id)
    if table not in _OWNED_TABLES:
        raise FitnessDataError(f"{table!r} is not an owner-checkable fitness table")
    if owner_column != "user_id":
        raise FitnessDataError("owner_column is fixed; it is not a request parameter")
    found = db.execute(text(
        f"SELECT 1 FROM {table} WHERE id = :rid AND user_id = :uid"
    ), {"rid": row_id, "uid": uid}).fetchone()
    if not found:
        # 404-shaped on purpose: the route layer turns this into a 404 so a
        # foreign id does not confirm its own existence.
        raise LookupError(f"{table} {row_id} not found for this user")


_OWNED_TABLES = frozenset({
    "fitness_program",
    "fitness_phase",
    "fitness_template",
    "fitness_athlete_goal",
    "fitness_athlete_limitation",
    "fitness_target_revision",
    "fitness_measurement_period",
    "fitness_measurement_type",
    "fitness_exercise_performance",
    "fitness_pain_report",
    "fitness_coach_review",
    "fitness_coach_recommendation",
    "fitness_photo_analysis",
    "fitness_science_record",
    "active_workout_session",
    "workout_session",
    "workout_log",
    "progress_photo",
    "food_log",
    "daily_recovery_log",
})


def data_revision(db: Session, user_id: str) -> str:
    """A cheap fingerprint of "has anything the athlete owns changed".

    Used as a cache key component so a stale Fitness State cannot be served
    as current after a backdated correction. Deliberately coarse: it only has
    to change when something relevant changes, not identify what.
    """
    uid = _require_user(user_id)
    row = db.execute(text("""
        SELECT
          (SELECT COALESCE(MAX(created_at)::text, '') FROM health_metric WHERE user_id = :uid)
          || '|' ||
          (SELECT COALESCE(MAX(updated_at)::text, '') FROM food_log WHERE user_id = :uid)
          || '|' ||
          (SELECT COALESCE(MAX(updated_at)::text, '') FROM daily_recovery_log WHERE user_id = :uid)
          || '|' ||
          (SELECT COALESCE(MAX(created_at)::text, '') FROM workout_log WHERE user_id = :uid)
          || '|' ||
          (SELECT COALESCE(MAX(updated_at)::text, '') FROM active_workout_session WHERE user_id = :uid)
          AS fingerprint
    """), {"uid": uid}).fetchone()
    raw = (row.fingerprint if row else "") or ""
    import hashlib
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
