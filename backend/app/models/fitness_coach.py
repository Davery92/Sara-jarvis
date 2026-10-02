"""ORM models for the Fitness Coach's new owned tables.

FITNESS_COACH_IMPLEMENTATION_PLAN §5. Mapped on `app.db.base.Base`, the
modular base that `app/models/*` uses — **not** the second
`declarative_base()` that `main_simple.py:602` also creates. There are two
bases in this process and `alembic/env.py` targets the monolith's, which is
why none of these tables is created by autogenerate: every one of them has a
hand-written revision (159-173), and these classes exist for typed reads and
relationship traversal rather than as the schema's definition.

Consequences of that split, worth stating because getting them wrong is
quiet rather than loud:

* `extend_existing=True` is **not** used here. Nothing in this module maps a
  table that is already registered on either metadata — these are all new
  tables. The existing-table extensions (`health_metric`,
  `daily_recovery_log`, `workout_log`, `exercise_pr`, `progress_photo`,
  `exercise_library`) are reached through SQL in
  `app/services/fitness/data_access.py`, not remapped here, precisely so
  this module cannot collide with the 50 modules that do need
  `extend_existing`.
* Every child carries its own `user_id` with an FK to `app_user`, *and*
  services still validate that the parent belongs to the same user. An FK to
  a UUID proves the parent row exists; it never proves it belongs to the
  requester. Both checks, always.
* Nothing here has a `current_weight` column. Bodyweight is an observation
  in `health_metric`, resolved on read. A copied "current" field would start
  disagreeing with the observations the moment a backdated correction landed.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    """Aware UTC.

    Not `datetime.now()`: in this container a naive local now lands 4-5h
    early (`app/core/timezone.py`, gotcha 7). Not `utcnow()` either, which is
    naive. New fitness timestamps are aware UTC in `timestamptz` columns, and
    the athlete-local calendar date is stored separately where it matters.
    """
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# Athlete profile
# ─────────────────────────────────────────────────────────────────────────

class AthleteProfile(Base):
    """Stable, editable athlete facts. One row per athlete.

    Everything optional on purpose. An athlete who declines to give a date of
    birth or a calculation sex is a supported, permanent state — a formula
    that needs those inputs simply is not applied, rather than being fed a
    default that silently becomes a fabricated number.
    """
    __tablename__ = "fitness_athlete_profile"

    id = Column(String(36), primary_key=True, default=_uuid)
    # Unbounded String, matching `app_user.id`, which is `character varying`
    # with no length in the inspected schema and holds ids longer than 36
    # characters. A String(36) FK would truncate exactly those athletes' ids.
    user_id = Column(
        String, ForeignKey("app_user.id", ondelete="CASCADE"),
        unique=True, nullable=False,
    )

    height_cm = Column(Numeric(6, 2))
    date_of_birth = Column(Date)
    # 'male' | 'female' | 'unknown' | 'prefer_not_to_say'. The last two are
    # distinct: one is "we never asked", the other is a deliberate refusal.
    calculation_sex = Column(String(24), nullable=False, default="unknown")

    training_experience_years = Column(Numeric(5, 2))
    training_level = Column(String(20), nullable=False, default="unknown")

    timezone = Column(String(64), nullable=False, default="America/New_York")
    # Display preference only. Canonical storage for new physical measures is
    # metric; this decides what the athlete is shown and what an un-united
    # manual entry form submits.
    weight_unit = Column(String(8), nullable=False, default="lb")
    length_unit = Column(String(8), nullable=False, default="in")

    available_days = Column(JSONB, nullable=False, default=list)
    preferred_duration_minutes = Column(Integer)
    equipment = Column(JSONB, nullable=False, default=list)
    # Canonical exercise_library ids, not names: a name-keyed exclusion stops
    # working the moment the athlete renames the exercise.
    preferred_exercise_ids = Column(JSONB, nullable=False, default=list)
    excluded_exercise_ids = Column(JSONB, nullable=False, default=list)

    dietary_restrictions = Column(JSONB, nullable=False, default=list)
    dietary_preferences = Column(JSONB, nullable=False, default=list)
    supplements = Column(JSONB, nullable=False, default=list)

    coaching_style = Column(String(20), nullable=False, default="unset")
    monitoring_consent = Column(Boolean, nullable=False, default=False)

    # Optimistic concurrency for PATCH. Two devices editing the profile is
    # ordinary (phone and web), and last-write-wins silently discards one.
    row_version = Column(Integer, nullable=False, default=1)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        CheckConstraint(
            "calculation_sex IN ('male','female','unknown','prefer_not_to_say')",
            name="ck_athlete_profile_sex",
        ),
        CheckConstraint(
            "training_level IN ('unknown','novice','intermediate','advanced')",
            name="ck_athlete_profile_level",
        ),
        CheckConstraint(
            "height_cm IS NULL OR (height_cm > 50 AND height_cm < 275)",
            name="ck_athlete_profile_height",
        ),
        CheckConstraint(
            "training_experience_years IS NULL OR "
            "(training_experience_years >= 0 AND training_experience_years <= 90)",
            name="ck_athlete_profile_experience",
        ),
        CheckConstraint("row_version >= 1", name="ck_athlete_profile_version"),
    )


class AthleteProfileChange(Base):
    """A sparse audit of material profile edits.

    Sparse deliberately: not every keystroke, only the fields a historical
    review might have depended on (height, timezone, equipment, exclusions).
    A review already snapshots the constraints it reasoned under, so this is
    for answering "when did the available-days change" rather than for
    reconstructing state.
    """
    __tablename__ = "fitness_athlete_profile_change"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(
        String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    field = Column(String(64), nullable=False)
    old_value = Column(JSONB)
    new_value = Column(JSONB)
    from_version = Column(Integer, nullable=False)
    to_version = Column(Integer, nullable=False)
    changed_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    source = Column(String(32), nullable=False, default="user")

    __table_args__ = (
        Index("ix_athlete_profile_change_user_time", "user_id", "changed_at"),
    )


# ─────────────────────────────────────────────────────────────────────────
# Goals
# ─────────────────────────────────────────────────────────────────────────

class AthleteGoal(Base):
    """A dated athlete goal. Half-open `[valid_from, valid_until)`.

    Half-open, unlike `fitness_phase`'s inclusive `end_date`. Mixing the two
    conventions is how a boundary day ends up counted twice or not at all;
    the conversion happens exactly once, in the target resolver.

    `is_primary` has a partial-unique guard in the migration rather than a
    constraint here: PostgreSQL cannot express "no two primary goals with
    overlapping intervals" declaratively without an exclusion constraint over
    a daterange, so the writer takes an advisory lock and checks overlap.
    Several non-primary goals may coexist — "gain strength" and "keep the
    waist under 34 inches" are not in conflict.

    Superseded rows are never deleted: "what was I training for in March" is
    a question the review audit has to be able to answer.
    """
    __tablename__ = "fitness_athlete_goal"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(
        String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )

    kind = Column(String(24), nullable=False)
    is_primary = Column(Boolean, nullable=False, default=True)
    priority = Column(Integer, nullable=False, default=1)
    rationale = Column(Text)

    target_weight_kg = Column(Numeric(6, 2))
    # Which rate field the athlete actually chose. Storing both and inferring
    # later makes 0.25 kg/week and 0.3%/week indistinguishable after any
    # bodyweight change.
    rate_basis = Column(String(12), nullable=False, default="none")
    target_rate_kg_week = Column(Numeric(6, 3))
    target_rate_percent_week = Column(Numeric(6, 3))
    strength_targets = Column(JSONB, nullable=False, default=dict)

    valid_from = Column(Date, nullable=False)
    valid_until = Column(Date)
    recorded_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    supersedes_id = Column(
        String(36), ForeignKey("fitness_athlete_goal.id", ondelete="SET NULL")
    )  # our own table's id: always a UUID
    source = Column(String(32), nullable=False, default="user")
    approved_at = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "kind IN ('hypertrophy','strength','powerbuilding','gain','cut',"
            "'recomp','maintenance')",
            name="ck_athlete_goal_kind",
        ),
        CheckConstraint(
            "rate_basis IN ('absolute','percent','none')",
            name="ck_athlete_goal_rate_basis",
        ),
        CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name="ck_athlete_goal_interval",
        ),
        CheckConstraint("priority BETWEEN 1 AND 10", name="ck_athlete_goal_priority"),
        CheckConstraint(
            "target_weight_kg IS NULL OR (target_weight_kg > 0 AND target_weight_kg < 500)",
            name="ck_athlete_goal_target_weight",
        ),
        # The rate the athlete chose must actually be present, and the one
        # they did not choose must be absent.
        CheckConstraint(
            "(rate_basis = 'absolute' AND target_rate_kg_week IS NOT NULL "
            "   AND target_rate_percent_week IS NULL)"
            " OR (rate_basis = 'percent' AND target_rate_percent_week IS NOT NULL "
            "   AND target_rate_kg_week IS NULL)"
            " OR (rate_basis = 'none' AND target_rate_kg_week IS NULL "
            "   AND target_rate_percent_week IS NULL)",
            name="ck_athlete_goal_rate_coherent",
        ),
        # A cut cannot prescribe gaining, and vice versa.
        CheckConstraint(
            "NOT (kind = 'cut' AND COALESCE(target_rate_kg_week, "
            "     target_rate_percent_week, 0) > 0)",
            name="ck_athlete_goal_cut_sign",
        ),
        CheckConstraint(
            "NOT (kind = 'gain' AND COALESCE(target_rate_kg_week, "
            "     target_rate_percent_week, 0) < 0)",
            name="ck_athlete_goal_gain_sign",
        ),
        Index("ix_athlete_goal_user_from", "user_id", "valid_from"),
        Index("ix_athlete_goal_user_primary", "user_id", "is_primary", "valid_from"),
    )


# ─────────────────────────────────────────────────────────────────────────
# Limitations
# ─────────────────────────────────────────────────────────────────────────

class AthleteLimitation(Base):
    """A user-reported constraint on what they can train.

    There is deliberately **no diagnosis column**. Pain and injury here are
    reports, not findings: "right shoulder hurts on overhead press" is data,
    "rotator cuff impingement" is a clinical conclusion this system does not
    make. The severity flag is coarse and self-reported for the same reason.

    Resolved limitations are retained. A review from six weeks ago reasoned
    under the constraints that were active then, and deleting them would make
    its recommendations look arbitrary.
    """
    __tablename__ = "fitness_athlete_limitation"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(
        String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )

    area = Column(String(120), nullable=False)
    description = Column(Text)
    excluded_exercise_ids = Column(JSONB, nullable=False, default=list)
    modified_exercise_ids = Column(JSONB, nullable=False, default=list)
    severity_flag = Column(String(12))

    effective_from = Column(Date, nullable=False)
    effective_until = Column(Date)
    status = Column(String(16), nullable=False, default="active")
    notes = Column(Text)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        CheckConstraint(
            "status IN ('active','resolved','superseded')",
            name="ck_athlete_limitation_status",
        ),
        CheckConstraint(
            "severity_flag IS NULL OR severity_flag IN ('mild','moderate','severe')",
            name="ck_athlete_limitation_severity",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from",
            name="ck_athlete_limitation_interval",
        ),
        Index("ix_athlete_limitation_user_status", "user_id", "status"),
        Index("ix_athlete_limitation_user_dates", "user_id", "effective_from",
              "effective_until"),
    )


# ─────────────────────────────────────────────────────────────────────────
# Target revisions
# ─────────────────────────────────────────────────────────────────────────

class TargetRevision(Base):
    """An append-only, complete snapshot of nutrition/habit targets.

    Complete, not a patch. A patch chain means answering "what was Tuesday's
    protein target" requires replaying every edit, and one lost edit silently
    rewrites history. Each row states every value that applied.

    `scope='phase'` revisions version the macros that live directly on
    `fitness_phase`; `scope='default'` revisions version `fitness_goals`.
    Those legacy columns stay as the *current* projection so every existing
    reader keeps working — they are maintained atomically by the writer in
    `app/services/fitness/targets.py`, which is the only thing allowed to
    touch both.

    `history_unknown` is not a column: it is derived. A date before the
    earliest revision resolves to unknown provenance rather than to the
    current values, because `fitness_goals` defaults to 2000/150/200/70 and a
    row sitting on those defaults is not evidence anyone chose them.
    """
    __tablename__ = "fitness_target_revision"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(
        String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    scope = Column(String(12), nullable=False)
    phase_id = Column(String, ForeignKey("fitness_phase.id", ondelete="CASCADE"))
    version = Column(Integer, nullable=False, default=1)

    valid_from = Column(Date, nullable=False)
    valid_until = Column(Date)

    # Training-day values. Always populated — a revision with no training
    # values would resolve to nothing on a training day.
    calories = Column(Integer)
    protein_g = Column(Integer)
    carbs_g = Column(Integer)
    fat_g = Column(Integer)
    # Rest-day values, nullable: a phase that does not distinguish day types
    # leaves these null and both day types read the training values.
    rest_calories = Column(Integer)
    rest_protein_g = Column(Integer)
    rest_carbs_g = Column(Integer)
    rest_fat_g = Column(Integer)
    # A rest-day step goal is routinely higher than a training-day one, so
    # steps gets the same split the macros have. Sleep and water do not:
    # nobody sets a different water target for a rest day.
    rest_steps = Column(Integer)

    sleep_hours = Column(Numeric(4, 2))
    water_ml = Column(Integer)
    steps = Column(Integer)
    calorie_tolerance_pct = Column(Numeric(5, 2), nullable=False, default=10)
    protein_tolerance_pct = Column(Numeric(5, 2), nullable=False, default=10)

    source = Column(String(32), nullable=False, default="user")
    # Set when this revision came from accepting a coach recommendation. The
    # FK is added in revision 168, once the recommendation table exists.
    review_recommendation_id = Column(String(36))
    approved_at = Column(DateTime(timezone=True))
    approved_by = Column(String(36))
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        CheckConstraint("scope IN ('phase','default')", name="ck_target_revision_scope"),
        CheckConstraint(
            "(scope = 'phase' AND phase_id IS NOT NULL)"
            " OR (scope = 'default' AND phase_id IS NULL)",
            name="ck_target_revision_scope_phase",
        ),
        CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name="ck_target_revision_interval",
        ),
        CheckConstraint("version >= 1", name="ck_target_revision_version"),
        CheckConstraint(
            "calories IS NULL OR (calories >= 0 AND calories <= 20000)",
            name="ck_target_revision_calories",
        ),
        CheckConstraint(
            "protein_g IS NULL OR (protein_g >= 0 AND protein_g <= 1500)",
            name="ck_target_revision_protein",
        ),
        CheckConstraint(
            "calorie_tolerance_pct >= 0 AND calorie_tolerance_pct <= 100"
            " AND protein_tolerance_pct >= 0 AND protein_tolerance_pct <= 100",
            name="ck_target_revision_tolerance",
        ),
        UniqueConstraint("user_id", "scope", "phase_id", "version",
                         name="uq_target_revision_version"),
        Index("ix_target_revision_resolve", "user_id", "scope", "valid_from"),
        Index("ix_target_revision_phase", "phase_id", "valid_from"),
    )
