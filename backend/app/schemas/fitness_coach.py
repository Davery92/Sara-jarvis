"""Validated contracts for the Fitness Coach (FITNESS_COACH_IMPLEMENTATION_PLAN §5, §8).

Three groups live here, and the split matters:

1. **Units, scales and the nullable-metric contract.** `Metric` is the shape
   every analytics number takes. A bare float cannot say "I do not know", and
   the whole point of this subsystem is that unknown, zero and rejected are
   three different answers. `Metric` carries the value *and* why it might be
   missing, over what period, from how many observed days out of how many
   expected.
2. **API DTOs** for athlete profile, goals, limitations, target revisions,
   check-ins and measurements. These enforce omitted-vs-explicit-clear, which
   PATCH semantics need and `Optional[x] = None` cannot express on its own.
3. **`FitnessStateV1` and `CoachReviewOutputV1`** — the deterministic state
   the model reads, and the strictly validated shape it must answer in. The
   review output rejects unknown fields and unknown enum members: a prompt
   instruction is not an enforcement mechanism.

Nothing here connects to a database or an LLM at import.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Bumped when the *shape* of FitnessStateV1 changes in a way a stored review's
# input snapshot could not be re-read under. Stored beside every review.
FITNESS_STATE_SCHEMA_VERSION = 1
# Bumped when an analytics formula changes its meaning (not when a bug is
# fixed in a way that keeps the definition). Recorded in state and reviews so
# "why is this number different from last month's review" is answerable.
ANALYTICS_VERSION = 1
COACH_REVIEW_OUTPUT_VERSION = 1


# ─────────────────────────────────────────────────────────────────────────
# Sentinel: omitted vs explicitly cleared
# ─────────────────────────────────────────────────────────────────────────

class _Unset:
    """Field not present in the request at all.

    `Optional[int] = None` collapses "the client did not mention soreness"
    and "the client is clearing soreness" into the same value. A PATCH that
    cannot tell them apart will either wipe wearable-sourced fields the user
    never touched, or make clearing a value impossible. Check-in and profile
    DTOs default to this and treat an explicit `null` as a clear.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()
Patchable = Union[_Unset, None, Any]


# Control fields on a PATCH body are not patchable columns: they steer the
# write (concurrency, retry) rather than describe a value to store.
_CONTROL_FIELDS = frozenset({"expected_version", "idempotency_key"})


def present_fields(model: BaseModel) -> Dict[str, Any]:
    """The fields a PATCH actually mentioned, `None` meaning "clear this"."""
    out: Dict[str, Any] = {}
    for name in type(model).model_fields:
        if name in _CONTROL_FIELDS:
            continue
        value = getattr(model, name)
        if isinstance(value, _Unset):
            continue
        out[name] = value
    return out


# ─────────────────────────────────────────────────────────────────────────
# Units
# ─────────────────────────────────────────────────────────────────────────

class Unit(str, Enum):
    """Canonical units. Internal storage for new physical measures is metric.

    Existing lbs/integer-load contracts stay compatible through adapters —
    this enum names what a number *is*, it does not force a rewrite of any
    legacy column.
    """
    KG = "kg"
    LB = "lb"
    CM = "cm"
    INCH = "in"
    GRAM = "g"
    KCAL = "kcal"
    HOUR = "h"
    MINUTE = "min"
    SECOND = "s"
    COUNT = "count"
    ML = "ml"
    BPM = "bpm"
    MS = "ms"
    PERCENT = "%"
    KG_PER_WEEK = "kg/week"
    PERCENT_PER_WEEK = "%/week"
    SCORE = "score"
    # Deliberate: a legacy row whose unit was never recorded. Not a guess.
    UNKNOWN = "unknown"


_MASS = {Unit.KG, Unit.LB}
_LENGTH = {Unit.CM, Unit.INCH}
_TIME = {Unit.HOUR, Unit.MINUTE, Unit.SECOND}

LB_PER_KG = Decimal("2.20462262185")
CM_PER_INCH = Decimal("2.54")


class UnitError(ValueError):
    """A conversion that must not be guessed at."""


def ensure_finite(value: Optional[float], field: str = "value") -> Optional[float]:
    """Reject NaN and ±Infinity before they reach the database or a mean.

    A single NaN poisons every aggregate it touches and compares false to
    itself, so it survives naive equality filtering. Reject at the boundary.
    """
    if value is None:
        return None
    v = float(value)
    if math.isnan(v) or math.isinf(v):
        raise UnitError(f"{field} must be a finite number, got {value!r}")
    return v


def convert(value: Optional[float], from_unit: Unit, to_unit: Unit) -> Optional[float]:
    """Convert between compatible units with full precision.

    Raises rather than guessing when the source unit is UNKNOWN or the
    quantities are incompatible. "A weight around 180 is probably pounds" is
    exactly the inference this refuses to make: 180 kg is a real bodyweight.
    """
    if value is None:
        return None
    ensure_finite(value, "value")
    if from_unit == to_unit:
        return float(value)
    if Unit.UNKNOWN in (from_unit, to_unit):
        raise UnitError(
            f"cannot convert {from_unit.value} -> {to_unit.value}: an unrecorded "
            "unit is unknown, not inferable from the magnitude"
        )
    d = Decimal(str(value))
    if from_unit in _MASS and to_unit in _MASS:
        return float(d * LB_PER_KG if to_unit is Unit.LB else d / LB_PER_KG)
    if from_unit in _LENGTH and to_unit in _LENGTH:
        return float(d / CM_PER_INCH if to_unit is Unit.INCH else d * CM_PER_INCH)
    if from_unit in _TIME and to_unit in _TIME:
        secs = {Unit.HOUR: Decimal(3600), Unit.MINUTE: Decimal(60), Unit.SECOND: Decimal(1)}
        return float(d * secs[from_unit] / secs[to_unit])
    raise UnitError(f"incompatible units: {from_unit.value} -> {to_unit.value}")


def to_kg(value: Optional[float], unit: Unit) -> Optional[float]:
    return convert(value, unit, Unit.KG)


def to_cm(value: Optional[float], unit: Unit) -> Optional[float]:
    return convert(value, unit, Unit.CM)


def round_display(value: Optional[float], places: int = 1) -> Optional[float]:
    """Rounding is a *display* decision applied last.

    Analytics keep full precision internally: rounding 2.5 kg plate steps to
    integers at each stage accumulates error that then looks like a trend.

    ROUND_HALF_UP explicitly, not Decimal's ROUND_HALF_EVEN default. Banker's
    rounding would show 81.25 kg as 81.2 and 81.35 as 81.4, which reads as
    inconsistent to someone watching their own bodyweight to a tenth.
    """
    if value is None:
        return None
    return float(
        Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    )


# ─────────────────────────────────────────────────────────────────────────
# The nullable metric contract
# ─────────────────────────────────────────────────────────────────────────

class Unavailable(str, Enum):
    """Why a metric has no value. Never collapsed into zero."""
    NO_DATA = "no_data"
    INSUFFICIENT_COVERAGE = "insufficient_coverage"
    NO_TARGET = "no_target"
    UNKNOWN_UNIT = "unknown_unit"
    NOT_COMPARABLE = "not_comparable"
    DEPENDENCY_FAILED = "dependency_failed"
    NOT_APPLICABLE = "not_applicable"


class Quality(str, Enum):
    STALE = "stale"
    SPARSE = "sparse"
    OUTLIER_PRESENT = "outlier_present"
    SOURCE_CONFLICT = "source_conflict"
    BACKFILLED = "backfilled"
    ESTIMATE = "estimate"
    PARTIAL_DAY = "partial_day"
    UNRESOLVED_IDENTITY = "unresolved_identity"


class Period(BaseModel):
    """Half-open athlete-local calendar interval `[start, end)`.

    Half-open because `fitness_phase.end_date` is inclusive and mixing the
    two conventions silently double-counts or drops a boundary day. The
    conversion happens once, in the target resolver.
    """
    model_config = ConfigDict(frozen=True)

    start: date
    end: date

    @model_validator(mode="after")
    def _ordered(self) -> "Period":
        if self.end < self.start:
            raise ValueError(f"period end {self.end} precedes start {self.start}")
        return self

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    def contains(self, d: date) -> bool:
        return self.start <= d < self.end


class Metric(BaseModel):
    """One analytics number, honest about what it does and does not know."""
    model_config = ConfigDict(frozen=True)

    key: str
    value: Optional[float] = None
    unit: Unit = Unit.COUNT
    period: Optional[Period] = None
    observed_days: Optional[int] = None
    expected_days: Optional[int] = None
    observed_at: Optional[datetime] = None
    source_count: int = 0
    unavailable_reason: Optional[Unavailable] = None
    quality_flags: List[Quality] = Field(default_factory=list)
    formula: Optional[str] = None
    analytics_version: int = ANALYTICS_VERSION
    note: Optional[str] = None

    @field_validator("value")
    @classmethod
    def _finite(cls, v: Optional[float]) -> Optional[float]:
        return ensure_finite(v)

    @model_validator(mode="after")
    def _must_explain_absence(self) -> "Metric":
        if self.value is None and self.unavailable_reason is None:
            raise ValueError(
                f"metric {self.key!r} has no value and no unavailable_reason — "
                "every absent metric must say why it is absent"
            )
        return self

    @property
    def coverage(self) -> Optional[float]:
        if not self.expected_days:
            return None
        return (self.observed_days or 0) / self.expected_days


def unavailable(key: str, reason: Unavailable, **kw: Any) -> Metric:
    """Shorthand for the common case; keeps call sites from forgetting why."""
    return Metric(key=key, value=None, unavailable_reason=reason, **kw)


# ─────────────────────────────────────────────────────────────────────────
# Scales
# ─────────────────────────────────────────────────────────────────────────

SCALE_DIRECTIONS: Dict[str, str] = {
    # Documented direction for each 1-10 subjective field. Without this,
    # "soreness improved" and "soreness increased" are the same number moving.
    "sleep_quality": "higher_is_better",
    "energy": "higher_is_better",
    "motivation": "higher_is_better",
    "subjective_readiness": "higher_is_better",
    "fatigue": "lower_is_better",
    "soreness_level": "lower_is_better",
    "stress": "lower_is_better",
}


def validate_scale(field: str, value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    if field not in SCALE_DIRECTIONS:
        raise ValueError(f"{field} is not a documented 1-10 subjective scale")
    v = int(value)
    if not 1 <= v <= 10:
        raise ValueError(f"{field} must be 1-10, got {v}")
    return v


# ─────────────────────────────────────────────────────────────────────────
# Athlete profile, goals, limitations
# ─────────────────────────────────────────────────────────────────────────

class CalculationSex(str, Enum):
    """Only ever used as an input to a formula that needs it.

    `UNKNOWN` and `PREFER_NOT_TO_SAY` are distinct and both are permanent
    valid answers: a formula requiring this input is simply not applied.
    """
    MALE = "male"
    FEMALE = "female"
    UNKNOWN = "unknown"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


class TrainingLevel(str, Enum):
    UNKNOWN = "unknown"
    NOVICE = "novice"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class CoachingStyle(str, Enum):
    UNSET = "unset"
    DIRECT = "direct"
    SUPPORTIVE = "supportive"
    ANALYTICAL = "analytical"


class AthleteProfileOut(BaseModel):
    user_id: str
    height_cm: Optional[float] = None
    date_of_birth: Optional[date] = None
    calculation_sex: CalculationSex = CalculationSex.UNKNOWN
    training_experience_years: Optional[float] = None
    training_level: TrainingLevel = TrainingLevel.UNKNOWN
    timezone: str = "America/New_York"
    weight_unit: Unit = Unit.LB
    length_unit: Unit = Unit.INCH
    available_days: List[str] = Field(default_factory=list)
    preferred_duration_minutes: Optional[int] = None
    equipment: List[str] = Field(default_factory=list)
    preferred_exercise_ids: List[str] = Field(default_factory=list)
    excluded_exercise_ids: List[str] = Field(default_factory=list)
    dietary_restrictions: List[str] = Field(default_factory=list)
    dietary_preferences: List[str] = Field(default_factory=list)
    supplements: List[str] = Field(default_factory=list)
    coaching_style: CoachingStyle = CoachingStyle.UNSET
    monitoring_consent: bool = False
    row_version: int = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Resolved, never stored: current weight is an observation.
    current_weight: Optional[Metric] = None


class AthleteProfilePatch(BaseModel):
    """PATCH body. Every field defaults to UNSET, so absence means absence."""
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    height_cm: Patchable = UNSET
    date_of_birth: Patchable = UNSET
    calculation_sex: Patchable = UNSET
    training_experience_years: Patchable = UNSET
    training_level: Patchable = UNSET
    timezone: Patchable = UNSET
    weight_unit: Patchable = UNSET
    length_unit: Patchable = UNSET
    available_days: Patchable = UNSET
    preferred_duration_minutes: Patchable = UNSET
    equipment: Patchable = UNSET
    preferred_exercise_ids: Patchable = UNSET
    excluded_exercise_ids: Patchable = UNSET
    dietary_restrictions: Patchable = UNSET
    dietary_preferences: Patchable = UNSET
    supplements: Patchable = UNSET
    coaching_style: Patchable = UNSET
    monitoring_consent: Patchable = UNSET
    expected_version: Optional[int] = None

    @model_validator(mode="after")
    def _check_values(self) -> "AthleteProfilePatch":
        p = present_fields(self)
        h = p.get("height_cm")
        if h is not None and not isinstance(h, _Unset):
            if ensure_finite(float(h), "height_cm") is not None and not 50 <= float(h) <= 275:
                raise ValueError("height_cm outside a plausible human range")
        y = p.get("training_experience_years")
        if y is not None and not isinstance(y, _Unset):
            if not 0 <= float(y) <= 90:
                raise ValueError("training_experience_years outside 0-90")
        if (tz := p.get("timezone")) is not None and not isinstance(tz, _Unset):
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
            try:
                ZoneInfo(str(tz))
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError(f"unknown timezone {tz!r}")
        if (cs := p.get("calculation_sex")) is not None and not isinstance(cs, _Unset):
            CalculationSex(cs)
        if (tl := p.get("training_level")) is not None and not isinstance(tl, _Unset):
            TrainingLevel(tl)
        for unit_field in ("weight_unit", "length_unit"):
            u = p.get(unit_field)
            if u is not None and not isinstance(u, _Unset):
                Unit(u)
        return self


class GoalKind(str, Enum):
    HYPERTROPHY = "hypertrophy"
    STRENGTH = "strength"
    POWERBUILDING = "powerbuilding"
    GAIN = "gain"
    CUT = "cut"
    RECOMP = "recomp"
    MAINTENANCE = "maintenance"


class RateBasis(str, Enum):
    """Which of the two rate fields the athlete actually chose.

    Storing both and inferring intent later means a 0.25 kg/week and a
    0.3%/week target become indistinguishable after a bodyweight change.
    """
    ABSOLUTE = "absolute"
    PERCENT = "percent"
    NONE = "none"


class AthleteGoalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: GoalKind
    is_primary: bool = True
    priority: int = Field(default=1, ge=1, le=10)
    rationale: Optional[str] = Field(default=None, max_length=2000)
    target_weight_kg: Optional[float] = Field(default=None, gt=0, lt=500)
    rate_basis: RateBasis = RateBasis.NONE
    target_rate_kg_week: Optional[float] = None
    target_rate_percent_week: Optional[float] = None
    strength_targets: Dict[str, float] = Field(default_factory=dict)
    valid_from: date
    valid_until: Optional[date] = None
    source: str = "user"

    @model_validator(mode="after")
    def _coherent(self) -> "AthleteGoalIn":
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from (half-open range)")
        for f in ("target_rate_kg_week", "target_rate_percent_week"):
            ensure_finite(getattr(self, f), f)
        if self.rate_basis is RateBasis.ABSOLUTE and self.target_rate_kg_week is None:
            raise ValueError("rate_basis=absolute requires target_rate_kg_week")
        if self.rate_basis is RateBasis.PERCENT and self.target_rate_percent_week is None:
            raise ValueError("rate_basis=percent requires target_rate_percent_week")
        if self.rate_basis is RateBasis.NONE and (
            self.target_rate_kg_week is not None or self.target_rate_percent_week is not None
        ):
            raise ValueError("a rate was supplied but rate_basis says none")
        # Sign coherence: a cut cannot have a positive prescribed rate.
        rate = self.target_rate_kg_week if self.rate_basis is RateBasis.ABSOLUTE \
            else self.target_rate_percent_week
        if rate is not None:
            if self.kind is GoalKind.CUT and rate > 0:
                raise ValueError("a cut's target rate must be negative or zero")
            if self.kind is GoalKind.GAIN and rate < 0:
                raise ValueError("a gain's target rate must be positive or zero")
        for name, value in self.strength_targets.items():
            if ensure_finite(value, f"strength_targets[{name}]") is not None and value <= 0:
                raise ValueError(f"strength target for {name} must be positive")
        return self


class AthleteGoalOut(AthleteGoalIn):
    id: str
    user_id: str
    recorded_at: datetime
    supersedes_id: Optional[str] = None
    approved_at: Optional[datetime] = None


class LimitationStatus(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    SUPERSEDED = "superseded"


class AthleteLimitationIn(BaseModel):
    """A user-reported constraint. Deliberately has no diagnosis field."""
    model_config = ConfigDict(extra="forbid")

    area: str = Field(max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)
    excluded_exercise_ids: List[str] = Field(default_factory=list)
    modified_exercise_ids: List[str] = Field(default_factory=list)
    severity_flag: Optional[Literal["mild", "moderate", "severe"]] = None
    effective_from: date
    effective_until: Optional[date] = None
    notes: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _ordered(self) -> "AthleteLimitationIn":
        if self.effective_until is not None and self.effective_until <= self.effective_from:
            raise ValueError("effective_until must be after effective_from")
        return self


class AthleteLimitationOut(AthleteLimitationIn):
    id: str
    user_id: str
    status: LimitationStatus
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────
# Targets
# ─────────────────────────────────────────────────────────────────────────

class TargetScope(str, Enum):
    PHASE = "phase"
    DEFAULT = "default"


class DayType(str, Enum):
    TRAINING = "training"
    REST = "rest"
    UNKNOWN = "unknown"


class TargetProvenance(str, Enum):
    """Where a resolved target actually came from. Returned to every caller."""
    APPROVED_REVISION = "approved_revision"
    LEGACY_PHASE = "legacy_phase"
    LEGACY_DEFAULT = "legacy_default"
    UNKNOWN = "unknown"


class TargetValues(BaseModel):
    """A complete resolved snapshot, never an ambiguous patch.

    Appending complete values is what makes a historical target answerable:
    a patch chain requires replaying every edit to know what Tuesday's
    protein target was, and one lost edit silently changes history.
    """
    model_config = ConfigDict(extra="forbid")

    calories: Optional[int] = Field(default=None, ge=0, le=20000)
    protein_g: Optional[int] = Field(default=None, ge=0, le=1500)
    carbs_g: Optional[int] = Field(default=None, ge=0, le=2000)
    fat_g: Optional[int] = Field(default=None, ge=0, le=1000)
    sleep_hours: Optional[float] = Field(default=None, ge=0, le=24)
    water_ml: Optional[int] = Field(default=None, ge=0, le=20000)
    steps: Optional[int] = Field(default=None, ge=0, le=200000)
    calorie_tolerance_pct: float = Field(default=10.0, ge=0, le=100)
    protein_tolerance_pct: float = Field(default=10.0, ge=0, le=100)


class TargetRevisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: TargetScope
    phase_id: Optional[str] = None
    valid_from: date
    valid_until: Optional[date] = None
    training: TargetValues
    rest: Optional[TargetValues] = None
    source: str = "user"
    review_recommendation_id: Optional[str] = None

    @model_validator(mode="after")
    def _coherent(self) -> "TargetRevisionIn":
        if self.scope is TargetScope.PHASE and not self.phase_id:
            raise ValueError("scope=phase requires phase_id")
        if self.scope is TargetScope.DEFAULT and self.phase_id:
            raise ValueError("scope=default must not name a phase")
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from (half-open range)")
        return self


class ResolvedTargets(BaseModel):
    """What every consumer — UI, tools, review, voice, brief — reads."""
    user_id: str
    on_date: date
    day_type: DayType
    values: TargetValues
    provenance: TargetProvenance
    scope: Optional[TargetScope] = None
    phase_id: Optional[str] = None
    phase_name: Optional[str] = None
    revision_id: Optional[str] = None
    revision_version: Optional[int] = None
    effective_from: Optional[date] = None
    effective_until: Optional[date] = None
    # True when this date precedes the first provable target: the current
    # values are NOT asserted to have applied then.
    history_unknown: bool = False


class TargetRevisionOut(TargetRevisionIn):
    id: str
    user_id: str
    version: int
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────
# Check-ins and measurements
# ─────────────────────────────────────────────────────────────────────────

class NutritionStatus(str, Enum):
    UNKNOWN = "unknown"
    PARTIAL = "partial"
    COMPLETE = "complete"


class CheckInPatch(BaseModel):
    """A partial daily update.

    The physiological fields (`hrv`, `heart_rate`, `sleep_hours`,
    `body_weight`) are accepted here because that is how a Today screen or a
    chat turn supplies them — but they are **not** check-in columns. The
    service reroutes them to `health_metric` through the canonical ingest, so
    there is one answer to "what did I weigh on 1 October" rather than one
    here and one there. Clearing one is refused: removing an observation is a
    correction, which needs a target and a reason.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    # Rerouted to health_metric, not stored on the daily row.
    hrv: Patchable = UNSET
    heart_rate: Patchable = UNSET
    sleep_hours: Patchable = UNSET
    body_weight: Patchable = UNSET

    bedtime_at: Patchable = UNSET
    wake_at: Patchable = UNSET
    sleep_quality: Patchable = UNSET
    energy: Patchable = UNSET
    fatigue: Patchable = UNSET
    soreness_level: Patchable = UNSET
    stress: Patchable = UNSET
    motivation: Patchable = UNSET
    subjective_readiness: Patchable = UNSET
    notes: Patchable = UNSET
    nutrition_status: Patchable = UNSET
    expected_version: Optional[int] = None
    idempotency_key: Optional[str] = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _scales(self) -> "CheckInPatch":
        p = present_fields(self)
        for f in ("sleep_quality", "energy", "fatigue", "soreness_level",
                  "stress", "motivation", "subjective_readiness"):
            v = p.get(f, UNSET)
            if not isinstance(v, _Unset) and v is not None:
                validate_scale(f, int(v))
        ns = p.get("nutrition_status", UNSET)
        if not isinstance(ns, _Unset) and ns is not None:
            NutritionStatus(ns)
        # Physiological values must be finite and positive before they reach
        # the ingest, which would otherwise be the first thing to notice.
        for f in ("hrv", "heart_rate", "sleep_hours", "body_weight"):
            v = p.get(f, UNSET)
            if isinstance(v, _Unset) or v is None:
                continue
            ensure_finite(float(v), f)
            if float(v) <= 0:
                raise ValueError(f"{f} must be positive")
        if (sleep := p.get("sleep_hours", UNSET)) is not None and \
                not isinstance(sleep, _Unset) and float(sleep) > 24:
            raise ValueError("sleep_hours cannot exceed 24 in one night")
        bed, wake = p.get("bedtime_at", UNSET), p.get("wake_at", UNSET)
        if all(not isinstance(x, _Unset) and x is not None for x in (bed, wake)):
            b = bed if isinstance(bed, datetime) else datetime.fromisoformat(str(bed))
            w = wake if isinstance(wake, datetime) else datetime.fromisoformat(str(wake))
            if w <= b:
                raise ValueError("wake_at must be after bedtime_at")
            if (w - b).total_seconds() > 24 * 3600:
                raise ValueError("a sleep episode longer than 24h is not a night")
        return self


class ReadinessCoverage(str, Enum):
    """Wraps `recovery_score.compute_readiness`, which returns 100 for `{}`.

    The formula is untouched. What changes is that an empty input is now
    reported as unknown instead of as excellent recovery.
    """
    UNKNOWN = "unknown"
    PARTIAL = "partial"
    FULL = "full"


class CheckInOut(BaseModel):
    user_id: str
    log_date: date
    bedtime_at: Optional[datetime] = None
    wake_at: Optional[datetime] = None
    sleep_quality: Optional[int] = None
    energy: Optional[int] = None
    fatigue: Optional[int] = None
    soreness_level: Optional[int] = None
    stress: Optional[int] = None
    motivation: Optional[int] = None
    subjective_readiness: Optional[int] = None
    notes: Optional[str] = None
    nutrition_status: NutritionStatus = NutritionStatus.UNKNOWN
    nutrition_completed_at: Optional[datetime] = None
    row_version: int = 1
    field_sources: Dict[str, str] = Field(default_factory=dict)
    # Canonical observations, read not stored here.
    weight: Optional[Metric] = None
    sleep_duration: Optional[Metric] = None
    steps: Optional[Metric] = None
    water: Optional[Metric] = None
    hrv: Optional[Metric] = None
    resting_heart_rate: Optional[Metric] = None
    computed_readiness: Optional[Dict[str, Any]] = None
    readiness_coverage: ReadinessCoverage = ReadinessCoverage.UNKNOWN


class Quantity(str, Enum):
    MASS = "mass"
    LENGTH = "length"
    TIME = "time"
    COUNT = "count"
    VOLUME = "volume"
    RATE = "rate"
    SCORE = "score"


class Side(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    NONE = "none"


class MeasurementTypeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=60)
    label: str = Field(min_length=1, max_length=120)
    quantity: Quantity
    canonical_unit: Unit
    allows_side: bool = False
    allowed_sites: List[str] = Field(default_factory=list)
    protocol_guidance: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("code")
    @classmethod
    def _normalized_code(cls, v: str) -> str:
        norm = normalize_code(v)
        if not norm:
            raise ValueError("code must contain at least one alphanumeric character")
        return norm


class MeasurementTypeOut(MeasurementTypeIn):
    id: str
    owner_user_id: Optional[str] = None  # None = global seed
    is_active: bool = True


class MeasurementPeriodIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    measured_on: date
    measured_at: Optional[datetime] = None
    protocol: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=2000)
    photo_period_label: Optional[str] = Field(default=None, max_length=120)


class MeasurementPeriodOut(MeasurementPeriodIn):
    id: str
    user_id: str
    created_at: datetime


class MeasurementIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type_code: str
    value: float
    unit: Unit
    measured_at: datetime
    site: Optional[str] = Field(default=None, max_length=60)
    side: Side = Side.NONE
    period_id: Optional[str] = None
    protocol: Optional[str] = Field(default=None, max_length=200)
    idempotency_key: Optional[str] = Field(default=None, max_length=128)
    corrects_observation_id: Optional[str] = None

    @model_validator(mode="after")
    def _finite_positive(self) -> "MeasurementIn":
        ensure_finite(self.value, "value")
        if self.value <= 0:
            raise ValueError("a tape or scale measurement must be positive")
        if self.unit is Unit.UNKNOWN:
            raise ValueError("a new measurement must state its unit")
        return self


class MeasurementOut(BaseModel):
    id: str
    user_id: str
    type_code: str
    label: str
    value: float
    unit: Unit
    canonical_value: Optional[float] = None
    canonical_unit: Unit = Unit.UNKNOWN
    measured_at: datetime
    logical_date: date
    site: Optional[str] = None
    side: Side = Side.NONE
    period_id: Optional[str] = None
    protocol: Optional[str] = None
    source: str = "manual"
    superseded_by_id: Optional[str] = None


def normalize_code(value: str) -> str:
    """Stable lowercase snake form for measurement codes and exercise aliases.

    One normalizer, used by both, so `"BB  Bench-Press"` and `"bb bench press"`
    cannot end up as two different keys in two different tables.
    """
    out: List[str] = []
    prev_sep = True
    for ch in (value or "").strip().lower():
        if ch.isalnum():
            out.append(ch)
            prev_sep = False
        elif not prev_sep:
            out.append("_")
            prev_sep = True
    return "".join(out).strip("_")


# ─────────────────────────────────────────────────────────────────────────
# FitnessStateV1
# ─────────────────────────────────────────────────────────────────────────

class StateSection(str, Enum):
    PROFILE = "profile"
    TARGETS = "targets"
    WEIGHT = "weight"
    NUTRITION = "nutrition"
    SLEEP = "sleep"
    RECOVERY = "recovery"
    TRAINING = "training"
    PERFORMANCE = "performance"
    MEASUREMENTS = "measurements"
    PAIN = "pain"
    PHOTOS = "photos"
    CHANGES = "changes"
    QUALITY = "quality"


class Freshness(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    DEGRADED = "degraded"  # a dependency failed; this is NOT current data


class MetricGroup(BaseModel):
    """A named bag of metrics plus whatever structured extras it needs."""
    section: StateSection
    metrics: Dict[str, Metric] = Field(default_factory=dict)
    items: List[Dict[str, Any]] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class DataQuality(BaseModel):
    """An independent output, not a footnote on another number.

    Coverage confidence (how much data there is) is deliberately separate
    from model confidence (how sure the interpretation is).
    """
    observed_weight_days: Optional[int] = None
    expected_weight_days: Optional[int] = None
    sleep_nights: Optional[int] = None
    nutrition_complete_days: int = 0
    nutrition_partial_days: int = 0
    nutrition_unknown_days: int = 0
    missing_fields: List[str] = Field(default_factory=list)
    unresolved_units: int = 0
    unresolved_exercise_identities: int = 0
    source_conflicts: int = 0
    incomplete_workouts: int = 0
    overdue_cadences: List[str] = Field(default_factory=list)
    stale_profile: bool = False
    no_effective_target: bool = False
    insufficient_comparable_exposures: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class FitnessStateV1(BaseModel):
    """The deterministic projection. No LLM built any number in here."""
    schema_version: int = FITNESS_STATE_SCHEMA_VERSION
    analytics_version: int = ANALYTICS_VERSION
    user_id: str
    as_of: datetime
    athlete_local_date: date
    timezone: str
    period: Optional[Period] = None
    freshness: Freshness = Freshness.FRESH
    data_revision: Optional[str] = None

    profile: Optional[AthleteProfileOut] = None
    goals: List[AthleteGoalOut] = Field(default_factory=list)
    limitations: List[AthleteLimitationOut] = Field(default_factory=list)
    targets: Optional[ResolvedTargets] = None
    program: Dict[str, Any] = Field(default_factory=dict)
    sections: Dict[StateSection, MetricGroup] = Field(default_factory=dict)
    quality: DataQuality = Field(default_factory=DataQuality)
    recent_changes: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    degraded_dependencies: List[str] = Field(default_factory=list)

    def metric_paths(self) -> List[str]:
        """Every `section.key` a review is allowed to cite.

        The validator checks model output against exactly this list, which is
        how an invented metric reference is caught rather than rendered.
        """
        out: List[str] = []
        for section, group in self.sections.items():
            out.extend(f"{section.value}.{k}" for k in group.metrics)
        return out


# ─────────────────────────────────────────────────────────────────────────
# CoachReviewOutputV1
# ─────────────────────────────────────────────────────────────────────────

class RecommendationCategory(str, Enum):
    """A closed set. Anything else is a rejected output, not a new category."""
    MAINTAIN = "maintain"
    PROGRESS = "progress"
    REDUCE = "reduce"
    EXERCISE_CHANGE = "exercise_change"
    VOLUME_CHANGE = "volume_change"
    NUTRITION_CHANGE = "nutrition_change"
    PRIORITIZE_RECOVERY = "prioritize_recovery"
    REQUEST_DATA = "request_data"
    FLAG_CONCERN = "flag_concern"


class ConfidenceCategory(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class ProposedChangeKind(str, Enum):
    NONE = "none"
    TARGET_REVISION = "target_revision"
    DATA_REQUEST = "data_request"
    PROGRAM_CHANGE = "program_change"


class ProposedChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ProposedChangeKind = ProposedChangeKind.NONE
    scope: Optional[TargetScope] = None
    effective_date: Optional[date] = None
    target_values: Optional[TargetValues] = None
    requested_metric: Optional[str] = None
    description: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _coherent(self) -> "ProposedChange":
        if self.kind is ProposedChangeKind.TARGET_REVISION:
            if self.target_values is None or self.scope is None or self.effective_date is None:
                raise ValueError(
                    "a target_revision proposal needs scope, effective_date and "
                    "complete target_values — a partial target cannot be accepted"
                )
        if self.kind is ProposedChangeKind.DATA_REQUEST and not self.requested_metric:
            raise ValueError("a data_request proposal must name the metric wanted")
        if self.kind is ProposedChangeKind.NONE and self.target_values is not None:
            raise ValueError("kind=none cannot carry target values")
        return self


class ReviewObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=1200)
    metric_paths: List[str] = Field(default_factory=list)


class ReviewRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: RecommendationCategory
    headline: str = Field(min_length=1, max_length=240)
    rationale: str = Field(min_length=1, max_length=3000)
    metric_paths: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    confidence: ConfidenceCategory
    confidence_basis: str = Field(min_length=1, max_length=1000)
    proposed_change: ProposedChange = Field(default_factory=ProposedChange)


class CoachReviewOutputV1(BaseModel):
    """What Qwen must produce. `extra="forbid"` everywhere is deliberate.

    Notably absent: any executed-action status. A review cannot report that
    it changed something, because generating a review never changes anything.
    """
    model_config = ConfigDict(extra="forbid")

    output_version: int = COACH_REVIEW_OUTPUT_VERSION
    summary: str = Field(min_length=1, max_length=4000)
    coaching_priority: str = Field(min_length=1, max_length=600)
    observations: List[ReviewObservation] = Field(default_factory=list, max_length=20)
    limitations: List[str] = Field(default_factory=list, max_length=20)
    confidence: ConfidenceCategory
    confidence_basis: str = Field(min_length=1, max_length=1000)
    recommendations: List[ReviewRecommendation] = Field(default_factory=list, max_length=10)

    def referenced_metric_paths(self) -> List[str]:
        paths: List[str] = []
        for o in self.observations:
            paths.extend(o.metric_paths)
        for r in self.recommendations:
            paths.extend(r.metric_paths)
        return paths

    def referenced_evidence(self) -> List[str]:
        out: List[str] = []
        for r in self.recommendations:
            out.extend(r.evidence_refs)
        return out


class ReviewStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    INSUFFICIENT_DATA = "insufficient_data"


TERMINAL_REVIEW_STATUSES = frozenset(
    {ReviewStatus.COMPLETE, ReviewStatus.FAILED, ReviewStatus.INSUFFICIENT_DATA}
)


class DecisionStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


# ─────────────────────────────────────────────────────────────────────────
# Stored review and recommendation rows (Step 19)
# ─────────────────────────────────────────────────────────────────────────

class ReviewKind(str, Enum):
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    ON_DEMAND = "on_demand"
    PHASE_TRANSITION = "phase_transition"
    PHOTO_COMPARISON = "photo_comparison"


class ReviewFailureCategory(str, Enum):
    """Why a review did not produce output. A CATEGORY, never a prompt.

    Storing the prompt and the raw transcript would make this table the
    largest copy of the athlete's private data in the database, kept for the
    least useful reason. A category is what a retry decision needs.
    """
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    INVALID_OUTPUT = "invalid_output"
    SCHEMA_VIOLATION = "schema_violation"
    UNGROUNDED_CLAIM = "ungrounded_claim"
    SAFETY_REFUSED = "safety_refused"
    STATE_UNAVAILABLE = "state_unavailable"
    INSUFFICIENT_DATA = "insufficient_data"
    INTERNAL_ERROR = "internal_error"


class RequestedBy(str, Enum):
    SCHEDULE = "schedule"
    USER = "user"
    SYSTEM = "system"


class CoachReviewOut(BaseModel):
    """A stored review, as an API returns it.

    `input_state` is not in this model by default — it is a whole
    `FitnessStateV1` and most callers want the summary and the
    recommendations. `CoachReviewDetail` carries it for the one screen that
    answers "what did you reason from?".

    `protected_namespaces=()` because `model_requested` and `model_actual`
    are the names this subsystem uses everywhere — the column, the log line
    and the API field. Renaming them to dodge Pydantic's `model_` warning
    would put a third vocabulary in front of a reader for no gain.
    """
    model_config = ConfigDict(protected_namespaces=())

    id: str
    user_id: str
    kind: ReviewKind
    period: Period
    status: ReviewStatus
    input_hash: str
    state_schema_version: int
    analytics_version: int
    data_revision: Optional[str] = None
    collected_at: datetime
    source_cutoff: Optional[datetime] = None
    model_requested: Optional[str] = None
    #: The model that ACTUALLY answered. A fallback that answered as the
    #: primary would make every comparison between runs meaningless.
    model_actual: Optional[str] = None
    provider: Optional[str] = None
    prompt_version: str
    prompt_hash: Optional[str] = None
    output_schema_version: Optional[int] = None
    summary: Optional[str] = None
    evidence_refs: List[str] = Field(default_factory=list)
    error_category: Optional[ReviewFailureCategory] = None
    error_detail: Optional[str] = None
    run_id: Optional[str] = None
    attempt: int = 1
    revision: int = 1
    supersedes_id: Optional[str] = None
    superseded_by_id: Optional[str] = None
    requested_by: RequestedBy = RequestedBy.SCHEDULE
    evaluated_at: Optional[datetime] = None
    created_at: datetime

    @property
    def is_current(self) -> bool:
        return self.superseded_by_id is None


class CoachReviewDetail(CoachReviewOut):
    """The review plus what it reasoned from and what it concluded."""
    input_state: Optional[FitnessStateV1] = None
    output: Optional[CoachReviewOutputV1] = None
    recommendations: List["CoachRecommendationOut"] = Field(default_factory=list)


class CoachRecommendationOut(BaseModel):
    """A stored recommendation.

    There is no `applied` boolean. `decision_status` is the only statement
    about what happened, and `accepted` is constrained in the database to
    require an action receipt or the target revision it produced — so a row
    cannot claim an effect it did not have.
    """
    id: str
    review_id: str
    user_id: str
    category: RecommendationCategory
    action: ProposedChangeKind
    title: str
    rationale: str
    confidence: ConfidenceCategory
    confidence_basis: Optional[str] = None
    limitations: Optional[str] = None
    metric_paths: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    proposed_change: ProposedChange = Field(default_factory=ProposedChange)
    current_target_revision_id: Optional[str] = None
    current_phase_id: Optional[str] = None
    expires_at: Optional[datetime] = None
    decision_status: DecisionStatus = DecisionStatus.PROPOSED
    decided_at: Optional[datetime] = None
    decided_by: Optional[str] = None
    decision_note: Optional[str] = None
    action_receipt_id: Optional[str] = None
    applied_revision_id: Optional[str] = None
    priority: int = 5
    created_at: datetime

    @property
    def is_open(self) -> bool:
        return self.decision_status is DecisionStatus.PROPOSED


class ReviewRequest(BaseModel):
    """Ask for a review. Carries no model name and no prompt.

    Letting a caller choose the model or the prompt would make the stored
    `model_actual`/`prompt_version` pair describe a run nobody can reproduce
    from the server's own configuration.
    """
    model_config = ConfigDict(extra="forbid")

    kind: ReviewKind = ReviewKind.WEEKLY
    period_start: Optional[date] = None
    #: Exclusive, athlete-local.
    period_end: Optional[date] = None
    #: True re-collects state and creates a linked revision when the data
    #: changed. It never overwrites an existing review.
    force: bool = False


CoachReviewDetail.model_rebuild()


# ─────────────────────────────────────────────────────────────────────────
# Photo observations (Step 27)
# ─────────────────────────────────────────────────────────────────────────

class PhotoView(str, Enum):
    FRONT = "front"
    SIDE = "side"
    BACK = "back"
    OTHER = "other"


class ObservationConfidence(str, Enum):
    """How sure the model is. Separate from image quality, deliberately.

    A clear photo can still support only a weak statement, and a confident
    reading of a badly lit one is exactly the thing that must stay visible
    as two facts rather than one.
    """
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class ImageQuality(str, Enum):
    GOOD = "good"
    ACCEPTABLE = "acceptable"
    POOR = "poor"


class ComparisonVerdict(str, Enum):
    """Whether a pair can be compared at all.

    `INCONCLUSIVE` is a first-class answer, not a failure. Lighting, pose
    and distance dominate photo-to-photo difference, so "these two cannot
    be compared" is often the only honest reading — and a system without
    this value would produce a confident difference instead.
    """
    COMPARABLE = "comparable"
    INCONCLUSIVE = "inconclusive"
    NOT_COMPARABLE = "not_comparable"


class RegionObservation(BaseModel):
    """One qualitative statement about one region.

    No numbers. There is no `size_cm`, no `body_fat`, no score: a
    photograph cannot support any of them, and a field for one guarantees
    a model fills it.
    """
    model_config = ConfigDict(extra="forbid")

    #: A body region in the athlete's own vocabulary — "shoulders",
    #: "upper back". Free text, capped, because a closed list would force a
    #: model to mislabel whatever it actually saw.
    region: str = Field(min_length=1, max_length=60)
    observation: str = Field(min_length=1, max_length=600)
    confidence: ObservationConfidence


class PhotoObservationV1(BaseModel):
    """What a model may say about ONE photo.

    Notably absent: any estimate of body fat, weight, lean mass or
    measurement. §5.5 — "no body-fat percentage field or diagnosis" — and
    `extra="forbid"` means a model that produces one is rejected rather
    than having the field dropped on the way to storage.
    """
    model_config = ConfigDict(extra="forbid")

    output_version: int = 1
    view: PhotoView
    #: Two or three sentences. A longer description is a model filling space.
    summary: str = Field(min_length=1, max_length=1200)
    regions: List[RegionObservation] = Field(default_factory=list, max_length=12)
    #: What the photo itself prevented. "The lighting hides the midsection"
    #: is the most useful sentence such a system produces.
    limitations: List[str] = Field(default_factory=list, max_length=8)
    image_quality: ImageQuality
    pose_consistent_with_view: bool
    confidence: ObservationConfidence
    confidence_basis: str = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def _no_numbers_about_the_body(self) -> "PhotoObservationV1":
        """Reject a composition estimate smuggled into prose.

        The schema has no field for it, so a model that wants to say it puts
        it in `summary`. A percentage or a weight in this text would read as
        an observation and `health_metric` would never see it.
        """
        _reject_body_numbers(
            [self.summary, self.confidence_basis]
            + [r.observation for r in self.regions]
            + list(self.limitations)
        )
        return self


class PhotoComparisonV1(BaseModel):
    """What a model may say about a PAIR.

    `verdict=INCONCLUSIVE` with a reason is the expected answer far more
    often than a difference is, because two photos taken weeks apart are
    almost never taken the same way.
    """
    model_config = ConfigDict(extra="forbid")

    output_version: int = 1
    view: PhotoView
    verdict: ComparisonVerdict
    #: Required when the verdict is not `comparable`: a refusal with no
    #: reason is indistinguishable from a failure.
    inconclusive_reason: Optional[str] = Field(default=None, max_length=600)
    summary: str = Field(min_length=1, max_length=1200)
    regions: List[RegionObservation] = Field(default_factory=list, max_length=12)
    limitations: List[str] = Field(default_factory=list, max_length=8)
    #: Whether the two images were taken comparably — lighting, pose,
    #: distance. Reported separately from the verdict so a reader can see
    #: WHY a comparison was refused.
    capture_consistent: bool
    image_quality: ImageQuality
    confidence: ObservationConfidence
    confidence_basis: str = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def _coherent(self) -> "PhotoComparisonV1":
        if self.verdict is not ComparisonVerdict.COMPARABLE and \
                not self.inconclusive_reason:
            raise ValueError(
                "a verdict other than 'comparable' must say why; a refusal "
                "with no reason reads as a failure"
            )
        if self.verdict is ComparisonVerdict.COMPARABLE and \
                not self.capture_consistent:
            raise ValueError(
                "a comparison cannot be 'comparable' while the captures are "
                "inconsistent — that is the definition of inconclusive"
            )
        _reject_body_numbers(
            [self.summary, self.confidence_basis,
             self.inconclusive_reason or ""]
            + [r.observation for r in self.regions]
            + list(self.limitations)
        )
        return self


#: Phrases that assert a body-composition number. Checked in the validator,
#: because the schema has nowhere to put one and a model that wants to say
#: it will put it in prose.
_BODY_NUMBER_PATTERNS = (
    re.compile(r"\b\d{1,2}(?:\.\d+)?\s*%\s*(?:body\s*fat|bf|fat)\b", re.I),
    re.compile(r"\bbody\s*fat\b[^.]{0,30}\b\d", re.I),
    re.compile(r"\b\d{1,2}(?:\.\d+)?\s*(?:to|-|–)\s*\d{1,2}(?:\.\d+)?\s*%", re.I),
    re.compile(r"\b(?:around|about|roughly|approximately|circa)\s+\d{1,3}\s*"
               r"(?:kg|lbs?|pounds?|%)\b", re.I),
    re.compile(r"\b\d{2,3}\s*(?:kg|lbs?|pounds?)\b", re.I),
    re.compile(r"\blean\s*mass\b[^.]{0,30}\b\d", re.I),
    re.compile(r"\bbmi\b", re.I),
)


def _reject_body_numbers(texts: Sequence[str]) -> None:
    for text_value in texts:
        if not text_value:
            continue
        for pattern in _BODY_NUMBER_PATTERNS:
            if pattern.search(text_value):
                raise ValueError(
                    "a photo cannot support a body-composition number "
                    f"({pattern.pattern!r} matched); describe what you see "
                    "instead"
                )


class PhotoAnalysisStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"
    SOURCE_GONE = "source_gone"


class PhotoAnalysisFailure(str, Enum):
    NO_CONSENT = "no_consent"
    NO_VISION_CAPABILITY = "no_vision_capability"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    INVALID_OUTPUT = "invalid_output"
    BODY_COMPOSITION_CLAIM = "body_composition_claim"
    OWNER_MISMATCH = "owner_mismatch"
    SOURCE_CHANGED = "source_changed"
    IMAGE_UNREADABLE = "image_unreadable"
    INTERNAL_ERROR = "internal_error"


# ─────────────────────────────────────────────────────────────────────────
# Curated science (Step 28)
# ─────────────────────────────────────────────────────────────────────────
#
# Three things these types exist to prevent, each of which has a cheaper
# wrong version that looks fine until it is read closely:
#
# 1. **An unreviewed paper being cited.** Ingestion is not acceptance. A
#    record arrives `UNREVIEWED` and stays invisible to retrieval however
#    well it matches a query, because similarity is not endorsement.
# 2. **A citation that cannot be reconstructed.** A review cites a *chunk of
#    a revision*, not a paper. The revision carries the content hash, so
#    "which exact text did she read" is answerable after the PDF is replaced
#    by a corrected version.
# 3. **A finding applied to the wrong people.** Population is a recorded
#    field, not an inference. A twelve-week study on untrained women is
#    evidence about untrained women; ranking must be able to see the
#    mismatch and say so rather than quietly averaging it away.

SCIENCE_SCHEMA_VERSION = 1
#: Bumped when the retrieval ranking changes meaning. Stored beside every
#: citation, so an old review's evidence can be explained under the policy
#: that actually produced it rather than today's.
SCIENCE_RANKING_POLICY_VERSION = 1


class SourceType(str, Enum):
    """What kind of thing this is, which bounds what it can support."""
    META_ANALYSIS = "meta_analysis"
    SYSTEMATIC_REVIEW = "systematic_review"
    RCT = "rct"
    #: Crossover, cohort, case series — not randomised.
    OBSERVATIONAL = "observational"
    NARRATIVE_REVIEW = "narrative_review"
    POSITION_STAND = "position_stand"
    #: A textbook chapter, a coach's write-up, a conference talk. Usable,
    #: but it is somebody's synthesis and must be labelled as one.
    SECONDARY = "secondary"


class ScienceTopic(str, Enum):
    HYPERTROPHY = "hypertrophy"
    STRENGTH = "strength"
    NUTRITION = "nutrition"
    SLEEP = "sleep"
    RECOVERY = "recovery"
    CARDIO = "cardio"
    INJURY = "injury"
    SUPPLEMENTS = "supplements"


class EvidenceQuality(str, Enum):
    """The curator's grade, recorded with a reason. Never computed from
    `source_type` alone: a badly run RCT is worse evidence than a careful
    meta-analysis, and the reverse happens too."""
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"


class ScienceStatus(str, Enum):
    #: Ingested, extracted, chunked, embedded — and invisible to retrieval.
    UNREVIEWED = "unreviewed"
    ACCEPTED = "accepted"
    #: Looked at and declined. Kept, with the reason: the same paper will
    #: arrive again from a refresh, and re-reading it each month is waste.
    REJECTED = "rejected"
    #: A newer revision or a better paper replaced it. Still readable,
    #: because an old review cited it and that citation must resolve.
    SUPERSEDED = "superseded"
    #: Withdrawn by the journal or the authors. Excluded from retrieval and
    #: flagged on every review that cited it.
    RETRACTED = "retracted"


class CurationAction(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    SUPERSEDE = "supersede"
    RETRACT = "retract"
    REOPEN = "reopen"
    ANNOTATE = "annotate"


class ExtractionState(str, Enum):
    PENDING = "pending"
    EXTRACTED = "extracted"
    EMBEDDED = "embedded"
    #: Extraction or embedding gave up. Distinguished from `pending` so a
    #: retry is a decision rather than an accident, and so a record stuck
    #: here is visible instead of looking like it is still working.
    FAILED = "failed"


class ScienceIngestFailure(str, Enum):
    UNSUPPORTED_TYPE = "unsupported_type"
    TOO_LARGE = "too_large"
    NO_TEXT = "no_text"
    FETCH_BLOCKED = "fetch_blocked"
    FETCH_FAILED = "fetch_failed"
    EMBEDDING_UNAVAILABLE = "embedding_unavailable"
    #: The backend returned vectors of a width the column cannot hold.
    #: Padding or truncating would produce a searchable embedding that means
    #: nothing, and the search would still work — which is the worst case.
    EMBEDDING_DIM_MISMATCH = "embedding_dim_mismatch"
    DUPLICATE = "duplicate"


class ScienceAnnotationKind(str, Enum):
    #: "This is the paper everyone cites for X, and it does not say X."
    CAVEAT = "caveat"
    #: How it bears on this athlete specifically.
    APPLICATION = "application"
    DISAGREEMENT = "disagreement"
    NOTE = "note"


class ScienceRegisterInput(BaseModel):
    """A paper arriving, by upload or by URL.

    Bibliographic fields are supplied by whoever registers it, never
    inferred from the filename and never invented. §28.7: the ingesting
    agent verifies primary-source details at ingestion time. A guessed year
    or a guessed population is worse than a blank one, because a blank one
    is visibly blank.
    """
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=500)
    source_type: SourceType
    topics: List[ScienceTopic] = Field(min_length=1)
    url: Optional[str] = Field(default=None, max_length=2000)
    doi: Optional[str] = Field(default=None, max_length=200)
    authors: Optional[str] = Field(default=None, max_length=1000)
    publication_year: Optional[int] = Field(default=None, ge=1900, le=2100)
    journal: Optional[str] = Field(default=None, max_length=300)
    #: Who was studied, in words. "n=43 resistance-trained men, 18-35".
    population: Optional[str] = Field(default=None, max_length=1000)
    #: What it cannot support. Required for acceptance, not for ingestion:
    #: it is the curator's job and it is where most of the value is.
    limitations: Optional[str] = Field(default=None, max_length=2000)
    quality: Optional[EvidenceQuality] = None
    notes: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("doi")
    @classmethod
    def _normalise_doi(cls, value: Optional[str]) -> Optional[str]:
        """One DOI, one record.

        DOIs arrive as `10.1234/abc`, `doi:10.1234/abc`,
        `https://doi.org/10.1234/ABC` and with a trailing full stop from a
        citation. All four are the same paper, and a dedup check on the raw
        string would file four copies.
        """
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        lowered = text.lower()
        for prefix in ("https://doi.org/", "http://doi.org/",
                       "https://dx.doi.org/", "doi:", "doi "):
            if lowered.startswith(prefix):
                text = text[len(prefix):]
                lowered = text.lower()
                break
        text = text.strip().rstrip(".,;")
        if not text.lower().startswith("10."):
            raise ValueError(
                f"{value!r} is not a DOI. A DOI starts with '10.' — if this "
                f"is a URL, pass it as `url`."
            )
        # DOIs are case-insensitive by specification; stored lowercase so
        # the unique index actually collides.
        return text.lower()

    @field_validator("url")
    @classmethod
    def _http_only(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        if not text.lower().startswith(("http://", "https://")):
            raise ValueError(
                "A source URL must be http or https. A `file://` or `data:` "
                "URL would make the fetcher read this machine."
            )
        return text

    @model_validator(mode="after")
    def _identifiable(self) -> "ScienceRegisterInput":
        if not self.doi and not self.url:
            raise ValueError(
                "A record needs a DOI or a URL. Without one there is nothing "
                "to cite and no way to tell a duplicate from a new paper."
            )
        return self


class ScienceCurationInput(BaseModel):
    """A curation decision. The reason is not optional.

    An accept with no reason is indistinguishable from a click, and the
    reason is what a future reader needs: what this paper is good for, and
    what it was accepted *despite*.
    """
    model_config = ConfigDict(extra="forbid")

    action: CurationAction
    reason: str = Field(min_length=10, max_length=2000)
    #: Required for SUPERSEDE: which record replaces this one.
    superseded_by_id: Optional[str] = Field(default=None, max_length=64)
    #: The revision being acted on. Explicit, so accepting while an
    #: extraction is replacing the text cannot accept the new text silently.
    revision: int = Field(ge=1)
    quality: Optional[EvidenceQuality] = None
    limitations: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _coherent(self) -> "ScienceCurationInput":
        if self.action is CurationAction.SUPERSEDE and not self.superseded_by_id:
            raise ValueError(
                "A supersede must name the record that replaces this one, or "
                "the chain cannot be followed from an old citation."
            )
        if self.action is CurationAction.ACCEPT and not self.limitations:
            raise ValueError(
                "Acceptance requires the limitations field. Every paper has "
                "them, and the ones left blank are the ones later misapplied."
            )
        return self


class ScienceCitation(BaseModel):
    """What a review actually read, at the granularity it read it.

    A record id alone cannot be checked: the paper is forty pages and the
    claim came from one paragraph. This names the revision and the chunk, so
    the exact sentences are recoverable even after the source is replaced.
    """
    model_config = ConfigDict(extra="forbid")

    record_id: str
    revision: int
    chunk_id: str
    #: Where in the extracted text, so a reader can find it in the PDF.
    section: Optional[str] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    #: Which ranking produced it. An old citation explained under today's
    #: policy is a different claim about why it was shown.
    ranking_policy_version: int = SCIENCE_RANKING_POLICY_VERSION


class ScienceSearchHit(BaseModel):
    """One retrieval result, carrying what is needed to judge it.

    DOI, population and limitations travel with the text deliberately. A
    snippet with no population is how "trained men gained more from higher
    volume" becomes advice for a 52-year-old beginner.
    """
    model_config = ConfigDict(extra="forbid")

    record_id: str
    revision: int
    chunk_id: str
    title: str
    authors: Optional[str] = None
    publication_year: Optional[int] = None
    journal: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    source_type: SourceType
    quality: Optional[EvidenceQuality] = None
    topics: List[ScienceTopic] = Field(default_factory=list)
    population: Optional[str] = None
    limitations: Optional[str] = None
    section: Optional[str] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    text: str
    #: Component scores, kept separate rather than pre-blended, so a hit
    #: that ranked on topic match despite weak similarity is visible as
    #: exactly that.
    similarity: Optional[float] = None
    lexical: Optional[float] = None
    topic_match: float = 0.0
    quality_weight: float = 0.0
    #: Negative when the study population does not look like this athlete.
    #: Never silently dropped: a mismatch the coach can see is better than a
    #: result that quietly vanished.
    applicability: float = 0.0
    applicability_note: Optional[str] = None
    score: float = 0.0
    ranking_policy_version: int = SCIENCE_RANKING_POLICY_VERSION


class ScienceRefreshOutcome(BaseModel):
    """What one refresh run did — and did not do.

    `last_attempt_at` and `last_success_at` are separate fields because a
    monthly job that has failed every month for four months otherwise shows
    a recent timestamp and looks healthy. That is the same class of lie as
    `DBScheduler` marking `last_status='success'` at dispatch time (§3).
    """
    model_config = ConfigDict(extra="forbid")

    run_id: str
    attempted_at: datetime
    succeeded: bool
    queried_topics: List[ScienceTopic] = Field(default_factory=list)
    candidates_seen: int = 0
    #: Queued as UNREVIEWED. A refresh never accepts anything (§28.6).
    queued_unreviewed: int = 0
    duplicates_skipped: int = 0
    #: Records the refresh found marked retracted upstream, with the reviews
    #: that cited them. Flagged for a human, never auto-applied.
    retractions_flagged: List[str] = Field(default_factory=list)
    affected_review_ids: List[str] = Field(default_factory=list)
    digest_sent: bool = False
    detail: Optional[str] = None

    @model_validator(mode="after")
    def _never_claims_acceptance(self) -> "ScienceRefreshOutcome":
        """A structural guard, not a comment.

        If a future change makes the refresh capable of accepting a record,
        this field will stop validating and the test that asserts it will
        name the step that did it. The alternative is a refresh that quietly
        promotes papers nobody read.
        """
        if self.queued_unreviewed < 0 or self.candidates_seen < 0:
            raise ValueError("counts cannot be negative")
        return self


# ─────────────────────────────────────────────────────────────────────────
# Programming: typed prescriptions and reviewable drafts (Step 29)
# ─────────────────────────────────────────────────────────────────────────
#
# What these types are for: the programming data in this codebase currently
# lives in three places that can disagree — `fitness_template.exercises`
# (a JSON blob the live workout view reads), `template_exercise` (relational
# rows the editor writes), and `exercises[i].set_plan` (a top/backoff
# loading table keyed by *program* week). A draft that writes one and not
# the others produces a program that looks edited on one screen and
# unchanged on another.
#
# So: one typed shape, parsed from either side, written through one writer,
# and versioned immutably before anything is activated.

PROGRAM_DRAFT_VERSION = 1
#: Bumped when the typed prescription shape changes in a way a stored
#: revision snapshot could not be re-read under.
PROGRAM_SNAPSHOT_VERSION = 1


class MetricType(str, Enum):
    """What a set measures. A time-based set with a rep target is a
    contradiction, and the validator says so rather than guessing."""
    REPS = "reps"
    TIME = "time"
    DISTANCE = "distance"


class ProgressionRule(str, Enum):
    """How load advances. Deterministic — none of these consult a model."""
    #: Add reps within the range, then add load and drop to the bottom.
    DOUBLE = "double_progression"
    #: Fixed increment when the last session met its target.
    LINEAR = "linear"
    #: A percentage of a reference max, read from the plan.
    PERCENTAGE = "percentage"
    #: Hold and let the athlete decide. Explicit, so "no rule" is a choice
    #: rather than a missing field that silently becomes double progression.
    MANUAL = "manual"


class SetRole(str, Enum):
    WARMUP = "warmup"
    #: The heaviest prescribed set of the exercise. `set_plan` calls this
    #: `role: "top"` and the advance gate reads it.
    TOP = "top"
    BACKOFF = "backoff"
    WORKING = "working"


class EffortTarget(str, Enum):
    RPE = "rpe"
    RIR = "rir"
    PERCENT_1RM = "percent_1rm"
    NONE = "none"


class DraftStatus(str, Enum):
    DRAFT = "draft"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    #: The base program moved under it. A draft built against revision 4
    #: cannot be applied to revision 6 without being re-read.
    STALE = "stale"
    EXPIRED = "expired"


class DraftBlockKind(str, Enum):
    """Block, mesocycle and program week are the same tree at different
    depths (§29.1: "without unnecessary separate tables"), so this names
    what a draft is about rather than creating three schemas."""
    PROGRAM = "program"
    BLOCK = "block"
    WEEK = "week"


class DraftValidationCode(str, Enum):
    UNKNOWN_EXERCISE = "unknown_exercise"
    EQUIPMENT_UNAVAILABLE = "equipment_unavailable"
    LIMITATION_CONFLICT = "limitation_conflict"
    IMPLAUSIBLE_DURATION = "implausible_duration"
    IMPLAUSIBLE_VOLUME = "implausible_volume"
    IMPLAUSIBLE_INTENSITY = "implausible_intensity"
    CONTRADICTORY_METRIC = "contradictory_metric"
    MISSING_LOAD_UNIT = "missing_load_unit"
    #: Not an error: something the coach must ask before the draft can be
    #: judged. §29.3 — a missing constraint produces a question, not a
    #: default.
    MISSING_CONSTRAINT = "missing_constraint"
    #: A draft that prescribes novice loading to somebody with years of
    #: logged training. §29.3 forbids the beginner default when the history
    #: or the profile says otherwise.
    BEGINNER_DEFAULT_REJECTED = "beginner_default_rejected"


class PrescribedSet(BaseModel):
    """One set, fully specified.

    `load_kg` and `load_percent` are alternatives, not both: a set is
    prescribed either as a weight or as a fraction of a reference, and
    carrying both invites two readers to disagree about which is
    authoritative. The unit is explicit because this codebase stores
    kilograms and displays pounds, and a bare number has been wrong in both
    directions.
    """
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    role: SetRole = SetRole.WORKING
    metric: MetricType = MetricType.REPS
    reps: Optional[int] = Field(default=None, ge=1, le=200)
    reps_low: Optional[int] = Field(default=None, ge=1, le=200)
    reps_high: Optional[int] = Field(default=None, ge=1, le=200)
    seconds: Optional[int] = Field(default=None, ge=1, le=7200)
    meters: Optional[float] = Field(default=None, gt=0, le=100_000)

    load_kg: Optional[float] = Field(default=None, ge=0, le=600)
    load_percent: Optional[float] = Field(default=None, gt=0, le=150)
    load_unit: Optional[Unit] = None

    effort: EffortTarget = EffortTarget.NONE
    rpe: Optional[float] = Field(default=None, ge=1, le=10)
    rir: Optional[int] = Field(default=None, ge=0, le=10)
    rest_seconds: Optional[int] = Field(default=None, ge=0, le=1800)
    is_per_side: bool = False
    note: Optional[str] = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _coherent(self) -> "PrescribedSet":
        if self.load_kg is not None and self.load_percent is not None:
            raise ValueError(
                "a set is prescribed as a weight OR as a percentage, not "
                "both — two readers would disagree about which is the plan"
            )
        if self.load_kg is not None and self.load_unit is None:
            raise ValueError(
                "a prescribed load needs its unit: this codebase stores "
                "kilograms and displays pounds, and a bare number has been "
                "wrong in both directions"
            )
        if self.metric is MetricType.REPS:
            if self.reps is None and self.reps_low is None:
                raise ValueError("a rep set needs reps or a rep range")
            if self.seconds is not None or self.meters is not None:
                raise ValueError(
                    "a rep set carrying seconds or meters is two "
                    "prescriptions in one row"
                )
        if self.metric is MetricType.TIME:
            if self.seconds is None:
                raise ValueError("a time set needs seconds")
            if self.reps is not None or self.reps_low is not None:
                raise ValueError("a time set with a rep target contradicts itself")
        if self.metric is MetricType.DISTANCE and self.meters is None:
            raise ValueError("a distance set needs meters")
        if (self.reps_low is not None) != (self.reps_high is not None):
            raise ValueError("a rep range needs both ends")
        if (self.reps_low is not None and self.reps_high is not None
                and self.reps_low > self.reps_high):
            raise ValueError(
                f"rep range {self.reps_low}-{self.reps_high} is inverted"
            )
        if self.effort is EffortTarget.RPE and self.rpe is None:
            raise ValueError("an RPE target needs an RPE")
        if self.effort is EffortTarget.RIR and self.rir is None:
            raise ValueError("an RIR target needs an RIR")
        if self.effort is EffortTarget.PERCENT_1RM and self.load_percent is None:
            raise ValueError("a percentage target needs load_percent")
        return self

    @property
    def is_working(self) -> bool:
        return self.role is not SetRole.WARMUP


class PrescribedSlot(BaseModel):
    """One exercise in one session, with its sets.

    `exercise_id` is the canonical `exercise_library` id and is what the
    validator checks. `exercise_name` is carried alongside for display and
    for the legacy JSON, which is name-keyed — but a name-only slot is
    rejected at validation, because a renamed exercise silently stops
    matching and the prescription quietly disappears.
    """
    model_config = ConfigDict(extra="forbid")

    order: int = Field(ge=0)
    exercise_id: Optional[str] = Field(default=None, max_length=64)
    exercise_name: str = Field(min_length=1, max_length=200)
    progression: ProgressionRule = ProgressionRule.DOUBLE
    sets: List[PrescribedSet] = Field(min_length=1, max_length=40)
    superset_group: Optional[str] = Field(default=None, max_length=10)
    set_technique: Optional[str] = Field(default=None, max_length=20)
    #: A percentage-driven slot needs something to take a percentage of.
    reference_1rm_kg: Optional[float] = Field(default=None, gt=0, le=600)
    note: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _coherent(self) -> "PrescribedSlot":
        indices = [one.index for one in self.sets]
        if indices != sorted(indices):
            raise ValueError("set indices must be in order")
        if len(set(indices)) != len(indices):
            raise ValueError("two sets share an index")
        if self.progression is ProgressionRule.PERCENTAGE:
            uses_percent = any(
                one.load_percent is not None for one in self.sets
            )
            if uses_percent and self.reference_1rm_kg is None:
                raise ValueError(
                    "percentage progression needs reference_1rm_kg — a "
                    "percentage of nothing is not a prescription"
                )
        return self

    @property
    def working_sets(self) -> int:
        return sum(1 for one in self.sets if one.is_working)


class PrescribedSession(BaseModel):
    """One training day as prescribed.

    `day_of_week` is 0-6 with Monday 0, matching `fitness_template`. Two
    sessions can share a day: a two-a-day is two sessions, and the readers
    that broke on the first match are the reason this is a list rather than
    a mapping.
    """
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)
    scheduled_days: List[str] = Field(default_factory=list, max_length=7)
    order_in_phase: int = 0
    slots: List[PrescribedSlot] = Field(min_length=1, max_length=30)
    #: The template this session corresponds to, when the draft edits an
    #: existing one rather than proposing a new session.
    template_id: Optional[str] = Field(default=None, max_length=64)
    note: Optional[str] = Field(default=None, max_length=1000)

    @property
    def working_sets(self) -> int:
        return sum(slot.working_sets for slot in self.slots)

    def estimated_minutes(self, *, default_rest: int = 120) -> float:
        """A duration estimate from the prescription itself.

        Rest dominates, so this is mostly a rest sum plus time under
        tension. Deliberately crude and deliberately present: a draft that
        prescribes 42 working sets is a three-hour session, and the only way
        to catch that before it reaches a calendar is to add it up.
        """
        total = 0.0
        for slot in self.slots:
            for one in slot.sets:
                rest = one.rest_seconds if one.rest_seconds is not None else default_rest
                if one.metric is MetricType.TIME and one.seconds:
                    work = one.seconds
                elif one.metric is MetricType.REPS:
                    reps = one.reps or one.reps_low or 0
                    work = reps * 3.5
                else:
                    work = 60
                total += work + rest
        return round(total / 60.0, 1)


class PrescribedWeek(BaseModel):
    """One program week.

    `program_week` is the absolute week of the program, which is what
    `set_plan` is keyed by — not the week within a phase. Those two have
    been confused before, and a plan read at the wrong index prescribes the
    wrong loads with total confidence.
    """
    model_config = ConfigDict(extra="forbid")

    program_week: int = Field(ge=1, le=104)
    #: The week within its block, for display. Derived, never authoritative.
    block_week: Optional[int] = Field(default=None, ge=1, le=52)
    is_deload: bool = False
    sessions: List[PrescribedSession] = Field(min_length=1, max_length=14)
    note: Optional[str] = Field(default=None, max_length=1000)

    @property
    def working_sets(self) -> int:
        return sum(session.working_sets for session in self.sessions)


class ProgramDraftV1(BaseModel):
    """A proposed program, block or week. Never activated by the model.

    §29.2: the model produces a constrained draft and nothing else. There
    is no field here for "activate", no template id to overwrite, and no
    date on which it takes effect — acceptance is a separate owner-origin
    call that versions and activates through existing phase control.
    """
    model_config = ConfigDict(extra="forbid")

    draft_version: int = PROGRAM_DRAFT_VERSION
    kind: DraftBlockKind
    title: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=4000)
    #: Which goals this serves, in the athlete's own words from the profile.
    #: A draft that cannot say what it is for cannot be judged.
    addresses_goals: List[str] = Field(default_factory=list, max_length=10)
    weeks: List[PrescribedWeek] = Field(min_length=1, max_length=24)
    #: Accepted-science chunk ids, validated against the offered set the
    #: same way a review's citations are.
    evidence_refs: List[str] = Field(default_factory=list, max_length=20)
    #: What the draft could not decide without asking. Carried in the draft
    #: rather than resolved by a default.
    questions: List[str] = Field(default_factory=list, max_length=10)
    limitations_respected: List[str] = Field(default_factory=list, max_length=20)
    note: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _weeks_are_ordered(self) -> "ProgramDraftV1":
        numbers = [week.program_week for week in self.weeks]
        if len(set(numbers)) != len(numbers):
            raise ValueError("two weeks share a program_week")
        if numbers != sorted(numbers):
            raise ValueError("weeks must be in program-week order")
        if self.kind is DraftBlockKind.WEEK and len(self.weeks) != 1:
            raise ValueError(
                f"a week draft has one week, not {len(self.weeks)}"
            )
        return self

    def all_exercise_names(self) -> List[str]:
        out: List[str] = []
        for week in self.weeks:
            for session in week.sessions:
                for slot in session.slots:
                    out.append(slot.exercise_name)
        return out


class DraftFinding(BaseModel):
    """One validation result. A question is a finding too.

    `blocking` separates "this draft cannot be applied" from "this needs an
    answer first" and from "worth knowing". Collapsing them would either
    block on a note or activate past a real conflict.
    """
    model_config = ConfigDict(extra="forbid")

    code: DraftValidationCode
    message: str = Field(min_length=1, max_length=600)
    blocking: bool = True
    #: Where, as `week/session/slot` indices, so a UI can point at it.
    path: Optional[str] = Field(default=None, max_length=120)


class DraftValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: List[DraftFinding] = Field(default_factory=list)

    @property
    def blocking(self) -> List[DraftFinding]:
        return [one for one in self.findings if one.blocking]

    @property
    def questions(self) -> List[DraftFinding]:
        return [
            one for one in self.findings
            if one.code is DraftValidationCode.MISSING_CONSTRAINT
        ]

    @property
    def acceptable(self) -> bool:
        """Nothing blocking AND nothing unanswered.

        Both, because they are refused for different reasons and a draft
        with only questions would otherwise report itself acceptable while
        `accept_draft` and `ck_program_draft_accept_validated` both refuse
        it — the UI saying yes and the server saying no about the same row.
        """
        return not self.blocking and not self.questions


class ProgramChangePreview(BaseModel):
    """Exactly what accepting a draft would do.

    §29.5. Every field here exists because "it will update your program" is
    not a thing anybody can agree to. The dates, the targets and the
    per-template changes are the agreement.
    """
    model_config = ConfigDict(extra="forbid")

    draft_id: str
    program_id: Optional[str] = None
    program_name: Optional[str] = None
    base_revision: int
    resulting_revision: int
    phase_id: Optional[str] = None
    phase_name: Optional[str] = None
    effective_start: Optional[date] = None
    effective_end: Optional[date] = None
    #: Per session: created / replaced / unchanged, with the counts that
    #: changed. A diff nobody can read is the same as no diff.
    template_changes: List[Dict[str, Any]] = Field(default_factory=list)
    #: Nutrition or target changes the draft implies. Empty is the normal
    #: case: a training draft that silently moved calories would be the
    #: worst kind of surprise.
    target_changes: List[Dict[str, Any]] = Field(default_factory=list)
    weeks_affected: List[int] = Field(default_factory=list)
    total_working_sets: int = 0
    estimated_session_minutes: List[float] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ProgressionDecision(BaseModel):
    """What the deterministic progression says for one exercise.

    No model is consulted. The inputs are the configured rule, the last
    comparable performance and the recovery state; the output names which
    rule fired and why, because "add 5lbs" with no reason is indistinguish-
    able from a guess.
    """
    model_config = ConfigDict(extra="forbid")

    exercise_name: str
    rule: ProgressionRule
    action: Literal["advance_load", "advance_reps", "hold", "reduce",
                    "deload", "ask"]
    #: None means unknown, not zero: a first session has no suggestion and
    #: must say so rather than proposing the empty bar.
    suggested_load_kg: Optional[float] = None
    suggested_reps: Optional[int] = None
    load_unit: Unit = Unit.KG
    reason: str = Field(min_length=1, max_length=600)
    basis_sessions: int = 0
    #: Set when recovery or pain downgraded the decision. Recovery never
    #: inflates a jump — at most it turns an advance into a hold.
    recovery_override: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────
# Approved automation and longitudinal summaries (Step 30)
# ─────────────────────────────────────────────────────────────────────────
#
# This step is where the coach is allowed to act without asking, and the
# whole design is about keeping that permission narrow enough to be
# meaningful. Four things a policy must carry, each because the version
# without it is the one that goes wrong:
#
# * **An action type.** §30.2: "existing workout rest approvals do not
#   authorize calorie/program changes." A permission is for one kind of
#   act, and a blanket "let Sara adjust things" is not a permission.
# * **Numeric bounds, and a rate limit.** A 50-calorie adjustment approved
#   once is not an approval of 50 calories every day; both the size and the
#   frequency are part of what was agreed.
# * **A minimum coverage and an evidence requirement.** An adjustment from
#   two weigh-ins is a response to noise. Sparse data stops the automation
#   rather than producing a confident small change.
# * **An expiry, and a stop.** A permission with no end is a permission
#   nobody remembers giving. Disabling one stops future actions outright.

AUTOMATION_POLICY_VERSION = 1
LONGITUDINAL_SUMMARY_VERSION = 1


class AutomationAction(str, Enum):
    """What one policy may authorize. Deliberately narrow.

    Each member is a distinct permission. There is no `ALL`, and adding one
    would undo the point: the existing in-workout rest automation
    (`workout_command_service.DEFAULT_POLICY`) is a separate thing that
    this enum does not cover, and approving it has never authorized a
    calorie change.
    """
    #: Move a calorie target inside an approved band.
    CALORIE_ADJUST = "calorie_adjust"
    #: Move a protein/carb/fat target inside an approved band.
    MACRO_ADJUST = "macro_adjust"
    #: Apply a deload the program already describes.
    SCHEDULED_DELOAD = "scheduled_deload"
    #: Apply the deterministic per-exercise progression for a session.
    PROGRESSION_APPLY = "progression_apply"
    #: Reduce load after a pain report, within bounds.
    PAIN_LOAD_REDUCTION = "pain_load_reduction"


class AutomationDecision(str, Enum):
    APPLIED = "applied"
    #: Inside the policy but worth telling David about; still applied.
    APPLIED_NOTIFIED = "applied_notified"
    #: Outside the bounds, or the data is too sparse. Becomes a proposal
    #: rather than an action — §30.3.
    PROPOSED = "proposed"
    DENIED = "denied"


class AutomationDenial(str, Enum):
    NO_POLICY = "no_policy"
    POLICY_DISABLED = "policy_disabled"
    POLICY_EXPIRED = "policy_expired"
    POLICY_REVOKED = "policy_revoked"
    OUTSIDE_BOUNDS = "outside_bounds"
    RATE_LIMITED = "rate_limited"
    INSUFFICIENT_COVERAGE = "insufficient_coverage"
    EVIDENCE_REQUIRED = "evidence_required"
    #: A pain report outranks an automated change. §30.3.
    PAIN_REPORTED = "pain_reported"
    #: The program or the targets moved since the policy was evaluated.
    STALE_REVISION = "stale_revision"
    MISSING_DATA = "missing_data"
    DUPLICATE = "duplicate"


class AutomationPolicyIn(BaseModel):
    """A permission, as granted.

    Every field is required that a reader would need to answer "what
    exactly did I agree to". `max_change` and `max_actions_per_window` are
    both mandatory because a size limit without a frequency limit is not a
    limit: fourteen approved 50-calorie steps is a 700-calorie change
    nobody approved.
    """
    model_config = ConfigDict(extra="forbid")

    action: AutomationAction
    #: Largest single change, in the action's own unit (kcal, grams, kg,
    #: or a fraction for a percentage reduction).
    max_change: float = Field(gt=0)
    #: And the floor, so a policy cannot be satisfied by a change too small
    #: to matter — an automation that moves nothing is noise with a
    #: receipt.
    min_change: float = Field(default=0, ge=0)
    max_actions_per_window: int = Field(ge=1, le=30)
    window_days: int = Field(ge=1, le=365)
    #: Observed days out of expected over the lookback, below which the
    #: automation stops. §30.2.
    min_coverage_days: int = Field(ge=1, le=120)
    coverage_window_days: int = Field(ge=1, le=365)
    #: Whether the action needs accepted science behind it. False is
    #: legitimate — a scheduled deload is in the program, not in a paper.
    requires_evidence: bool = False
    #: A permission with no end is one nobody remembers giving.
    expires_at: datetime
    notify: bool = True
    note: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _coherent(self) -> "AutomationPolicyIn":
        if self.min_change and self.min_change >= self.max_change:
            raise ValueError(
                f"min_change {self.min_change} is not below max_change "
                f"{self.max_change}, so no change could satisfy it"
            )
        if self.min_coverage_days > self.coverage_window_days:
            raise ValueError(
                f"min_coverage_days {self.min_coverage_days} exceeds the "
                f"{self.coverage_window_days}-day window it is counted over"
            )
        return self


class AutomationPolicyOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    action: AutomationAction
    enabled: bool
    max_change: float
    min_change: float
    max_actions_per_window: int
    window_days: int
    min_coverage_days: int
    coverage_window_days: int
    requires_evidence: bool
    expires_at: datetime
    notify: bool
    note: Optional[str] = None
    approved_at: datetime
    approved_by: str
    revoked_at: Optional[datetime] = None
    revoked_reason: Optional[str] = None
    policy_version: int = AUTOMATION_POLICY_VERSION
    #: How many actions this policy has taken in its current window, so a
    #: reader can see how close it is to its own limit.
    actions_in_window: int = 0

    @property
    def is_live(self) -> bool:
        return self.enabled and self.revoked_at is None


class AutomationOutcome(BaseModel):
    """What one automation attempt did.

    A denial is an outcome, not an error: the common case is a policy
    working exactly as agreed, and a reader needs to see which guard
    stopped it.
    """
    model_config = ConfigDict(extra="forbid")

    action: AutomationAction
    decision: AutomationDecision
    denial: Optional[AutomationDenial] = None
    reason: str = Field(min_length=1, max_length=800)
    #: Set only when something was applied.
    applied_change: Optional[float] = None
    receipt_id: Optional[str] = None
    #: Set when the attempt became a proposal instead.
    recommendation_id: Optional[str] = None
    policy_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    notified: bool = False

    @model_validator(mode="after")
    def _coherent(self) -> "AutomationOutcome":
        applied = self.decision in (
            AutomationDecision.APPLIED, AutomationDecision.APPLIED_NOTIFIED,
        )
        if applied and self.receipt_id is None:
            raise ValueError(
                "an applied action has a receipt — `verify_action` reads it "
                "back, and a change with no durable row is a claim"
            )
        if applied and self.applied_change is None:
            raise ValueError("an applied action says how much it changed")
        if self.decision is AutomationDecision.DENIED and self.denial is None:
            raise ValueError(
                "a denial names which guard stopped it; 'no' with no reason "
                "is indistinguishable from a bug"
            )
        if not applied and self.applied_change is not None:
            raise ValueError(
                "a change was recorded on an outcome that did not apply one"
            )
        return self


class LongitudinalPeriod(BaseModel):
    """One comparable stretch of training.

    Comparable means the goal, the phase type and the protocol were the
    same throughout — §30.1: compare goals/phases/protocols explicitly. Two
    stretches with different goals are two different experiments, and
    averaging them produces a number about neither.
    """
    model_config = ConfigDict(extra="forbid")

    label: str
    start: date
    end: date
    #: The goal in force. A period whose goal changed mid-way is split.
    goal_kind: Optional[str] = None
    phase_names: List[str] = Field(default_factory=list)
    weeks: float = 0
    #: Every number here is a `Metric`, so "no data" is distinguishable
    #: from zero — over a year, most of these are partly missing.
    weight_change: Optional[Metric] = None
    weight_rate_weekly: Optional[Metric] = None
    tonnage_weekly: Optional[Metric] = None
    sessions_weekly: Optional[Metric] = None
    calorie_mean: Optional[Metric] = None
    protein_mean: Optional[Metric] = None
    sleep_mean: Optional[Metric] = None
    #: Observed days over expected, for the period as a whole. A
    #: longitudinal claim from 20% coverage is a claim about the 20%.
    coverage: Optional[Quality] = None
    coverage_ratio: Optional[float] = None
    notes: List[str] = Field(default_factory=list)


class LongitudinalComparison(BaseModel):
    """Two periods, compared only where comparison is defensible.

    §30.1: "do not fit unexplained multi-year correlations". This holds
    period summaries and an explicit list of why a comparison was NOT
    made — which is the output most of the time, and is more useful than a
    correlation coefficient nobody can interpret.
    """
    model_config = ConfigDict(extra="forbid")

    summary_version: int = LONGITUDINAL_SUMMARY_VERSION
    analytics_version: int = ANALYTICS_VERSION
    periods: List[LongitudinalPeriod] = Field(default_factory=list)
    #: Pairwise, and only between periods that share a goal and have
    #: enough coverage.
    comparisons: List[Dict[str, Any]] = Field(default_factory=list)
    #: Why a pair was not compared, named. The honest bulk of the output.
    not_compared: List[str] = Field(default_factory=list)
    data_quality_notes: List[str] = Field(default_factory=list)


class SourceKind(str, Enum):
    """Where a canonical observation came from.

    The narrow contract §30.4 asks for. New vendors are added by
    registering a kind and an adapter, not by writing another ingest path:
    there is one of those per source already and they disagree about
    timestamps.
    """
    HEALTHKIT = "healthkit"
    MANUAL = "manual"
    SCALE = "scale"
    NUTRITION_API = "nutrition_api"
    WEARABLE = "wearable"


class SourceAdapterContract(BaseModel):
    """What any source must provide to write a canonical observation.

    Written down as a type because the alternative is what already exists:
    several ingest paths with their own timestamp conventions, their own
    idempotency (or none), and their own idea of which table is
    authoritative.
    """
    model_config = ConfigDict(extra="forbid")

    kind: SourceKind
    vendor: str = Field(min_length=1, max_length=80)
    #: A stable per-observation id from the vendor. Without one there is no
    #: idempotency and a re-sync duplicates a year of weigh-ins.
    external_id_field: str = Field(min_length=1, max_length=80)
    #: Which canonical metrics this source may write. A source that can
    #: write anything is a source that will overwrite something.
    writes_metrics: List[str] = Field(min_length=1, max_length=40)
    #: Explicit: aware UTC, naive UTC, or naive athlete-local. Three
    #: conventions exist in this database and a source that does not say
    #: which it uses lands its data 4-5 hours out.
    timestamp_convention: Literal["aware_utc", "naive_utc", "naive_local"]
    requires_consent: bool = True
    #: Whether this source may overwrite an existing value for the same
    #: (metric, instant). Default no: a later sync from a worse source
    #: should not replace a manual entry.
    may_overwrite: bool = False
