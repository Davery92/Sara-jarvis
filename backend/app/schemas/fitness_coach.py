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
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

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
