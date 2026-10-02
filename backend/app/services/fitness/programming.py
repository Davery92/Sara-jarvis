"""Program versioning, typed prescriptions, and reviewable drafts.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 29.

The thing this module is actually for: programming data in this codebase
lives in three places that can disagree.

* `fitness_template.exercises` — a JSON blob the live workout view reads.
* `template_exercise` — relational rows the template editor writes.
* `exercises[i].set_plan` — a top/backoff loading table keyed by *program*
  week, which neither of the above knows about.

A writer that touches one and not the others produces a program that looks
edited on one screen and unchanged on another, and a logged session whose
snapshot no longer matches the template it was performed from. So this
module defines one typed shape (`PrescribedSession`), parses it from either
side, and writes both through `write_session` — the single writer §29.1
asks for.

Three other rules, each with a constraint behind it rather than a comment:

* **The model drafts; a person activates.** `generate_draft` produces a
  validated `ProgramDraftV1` and writes a `fitness_program_draft` row. It
  cannot write a template, and `ck_program_draft_decided_by` refuses a
  decision attributed to a model. §29.2.
* **Progression is deterministic.** `progression_for` consults the
  configured rule, the last comparable performance and the recovery state.
  No model. Recovery can downgrade an advance to a hold; it never inflates
  a jump, which is `progressive_overload`'s existing rule and is kept.
* **The past does not move.** Activating a revision writes new rows. A
  completed session's snapshot and a stored review's input state are never
  rewritten, and a backdated revision has to say `effect_scope =
  'retroactive'` explicitly. §29.6.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.fitness_coach import (
    DraftBlockKind,
    DraftFinding,
    DraftStatus,
    DraftValidation,
    DraftValidationCode,
    EffortTarget,
    MetricType,
    PROGRAM_SNAPSHOT_VERSION,
    PrescribedSession,
    PrescribedSet,
    PrescribedSlot,
    PrescribedWeek,
    ProgramChangePreview,
    ProgramDraftV1,
    ProgressionDecision,
    ProgressionRule,
    SetRole,
    Unit,
)
from app.services.fitness import safety
from app.services.fitness.data_access import FitnessDataError, _require_user

logger = logging.getLogger(__name__)

UTC = timezone.utc

#: Plausibility bounds. Not opinions about good programming — bounds past
#: which a draft is a parsing accident. A 42-working-set session is three
#: hours and nobody asked for that; a 310-minute one is a typo.
MAX_WORKING_SETS_PER_SESSION = 40
MAX_SESSION_MINUTES = 180
MIN_SESSION_MINUTES = 8
#: Weekly working sets per muscle above which the draft is flagged rather
#: than refused: there are real programs up here and the athlete decides.
HIGH_WEEKLY_SETS = 30
MAX_WEEKLY_SETS = 90

#: An athlete with this much logged history is not a beginner, whatever a
#: draft assumes. §29.3.
EXPERIENCED_SESSION_COUNT = 40
EXPERIENCED_YEARS = 2.0

LB_PER_KG = 2.2046226218


class ProgrammingError(FitnessDataError):
    """A refusal a caller can show."""


class TruncatedDraft(ProgrammingError):
    """The model ran out of output budget mid-draft.

    Distinct from a parse failure because the remedy is different: a smaller
    ask or a bigger budget, not a better prompt. `generate_draft` does NOT
    spend its repair turn on one — a repair prompt makes the output longer,
    which is the opposite of what a truncated draft needs.
    """


class RevisionConflict(FitnessDataError):
    """The program moved under the draft.

    Carries the revisions so a client can reconcile rather than retry
    blindly — a blind retry against a changed program is how a reviewed
    draft gets applied to something nobody reviewed.
    """

    def __init__(self, message: str, *, base: Optional[int], current: Optional[int]):
        super().__init__(message)
        self.base = base
        self.current = current


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def _as_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return None
    return value


# ─────────────────────────────────────────────────────────────────────────
# The typed parser: JSON and relational, into one shape
# ─────────────────────────────────────────────────────────────────────────

def parse_reps(value: Any) -> Tuple[Optional[int], Optional[int]]:
    """A rep target into (low, high).

    The strings in this data are "8-10", "4+", "3", "AMRAP", 12 and None.
    "4+" is a floor with no ceiling, which is NOT the same as 4 — a reader
    that collapsed it would prescribe a hard four where the plan wanted at
    least four.
    """
    if value is None or value == "":
        return None, None
    if isinstance(value, (int, float)):
        count = int(value)
        return (count, count) if count > 0 else (None, None)
    token = str(value).strip().lower()
    if not token or token in ("amrap", "max", "to failure"):
        return None, None
    if token.endswith("+"):
        try:
            return int(float(token[:-1])), None
        except ValueError:
            return None, None
    for separator in ("-", "–", "to"):
        if separator in token:
            left, _, right = token.partition(separator)
            try:
                return int(float(left.strip())), int(float(right.strip()))
            except ValueError:
                continue
    try:
        count = int(float(token))
    except ValueError:
        return None, None
    return (count, count) if count > 0 else (None, None)


def _set_from_plan_entry(
    index: int, entry: Dict[str, Any], *, default_rest: Optional[int],
) -> Optional[PrescribedSet]:
    """One `set_plan` row into a typed set.

    `set_plan` entries look like
    `{"role": "top", "reps": "2-4", "rpe": 8, "pct": 0.85, "sets": 3}`.
    A `sets` count is expanded by the caller; this handles one.
    """
    role_token = str(entry.get("role") or "working").lower()
    role = {
        "top": SetRole.TOP, "backoff": SetRole.BACKOFF,
        "warmup": SetRole.WARMUP, "working": SetRole.WORKING,
    }.get(role_token, SetRole.WORKING)

    low, high = parse_reps(entry.get("reps"))
    percent = entry.get("pct") if entry.get("pct") is not None else entry.get("percent")
    if percent is not None:
        try:
            percent = float(percent)
        except (TypeError, ValueError):
            percent = None
        # A `set_plan` percentage is a fraction (0.85) in this data; a
        # typed one is a percentage (85). Treating 0.85 as 0.85% would
        # prescribe an empty bar.
        if percent is not None and percent <= 1.5:
            percent *= 100.0

    rpe = entry.get("rpe")
    try:
        rpe = float(rpe) if rpe is not None else None
    except (TypeError, ValueError):
        rpe = None

    effort = EffortTarget.NONE
    if rpe is not None:
        effort = EffortTarget.RPE
    elif percent is not None:
        effort = EffortTarget.PERCENT_1RM

    if low is None and high is None and percent is None:
        # Nothing prescribed. Dropping it is right: a set with no target is
        # not a set, and inventing one would be inventing the plan.
        return None

    rest = entry.get("rest_seconds")
    try:
        rest = int(rest) if rest is not None else default_rest
    except (TypeError, ValueError):
        rest = default_rest

    return PrescribedSet(
        index=index, role=role, metric=MetricType.REPS,
        reps=low if (low is not None and high == low) else None,
        reps_low=low if (high is not None and high != low) else (
            low if high is None and low is not None else None
        ),
        reps_high=high if (high is not None and high != low) else None,
        load_percent=percent, effort=effort, rpe=rpe,
        rest_seconds=rest,
    )


def parse_slot(spec: Dict[str, Any], *, week: Optional[int] = None) -> PrescribedSlot:
    """One template exercise into a typed slot.

    Reads `set_plan` when the exercise has one for `week` — that is the
    authoritative prescription for a plan-driven lift — and falls back to
    the flat `sets`/`reps`/`rpe_target` fields otherwise. Both paths exist
    in live data, and a parser that handled one would silently flatten the
    other's top/backoff structure into three identical sets.
    """
    name = str(spec.get("name") or spec.get("exercise_name") or "").strip()
    if not name:
        raise ProgrammingError("a template exercise with no name cannot be typed")

    rule_token = str(spec.get("progression_rule") or "").strip().lower()
    progression = {
        "double_progression": ProgressionRule.DOUBLE,
        "double": ProgressionRule.DOUBLE,
        "linear": ProgressionRule.LINEAR,
        "percentage": ProgressionRule.PERCENTAGE,
        "percent": ProgressionRule.PERCENTAGE,
        "manual": ProgressionRule.MANUAL,
        "none": ProgressionRule.MANUAL,
    }.get(rule_token, ProgressionRule.DOUBLE)

    default_rest = spec.get("rest_seconds")
    try:
        default_rest = int(default_rest) if default_rest is not None else 120
    except (TypeError, ValueError):
        default_rest = 120

    metric_token = str(spec.get("metric_type") or "reps").lower()
    metric = {
        "reps": MetricType.REPS, "time": MetricType.TIME,
        "distance": MetricType.DISTANCE,
    }.get(metric_token, MetricType.REPS)
    per_side = bool(spec.get("is_per_side"))

    sets: List[PrescribedSet] = []
    plan = spec.get("set_plan") or {}
    week_plan = None
    if plan.get("kind") == "top_backoff" and week is not None:
        week_plan = (plan.get("weeks") or {}).get(str(week))

    if week_plan:
        # Warmups first, in the plan's own order, then the working rows.
        for entry in (plan.get("warmup") or []):
            built = _set_from_plan_entry(
                len(sets), {**entry, "role": "warmup"}, default_rest=60,
            )
            if built:
                sets.append(built)
        for entry in (week_plan.get("sets") or week_plan.get("rows") or []):
            count = entry.get("sets") or 1
            try:
                count = max(1, int(count))
            except (TypeError, ValueError):
                count = 1
            for _ in range(count):
                built = _set_from_plan_entry(
                    len(sets), entry, default_rest=default_rest,
                )
                if built:
                    sets.append(built)

    if not sets:
        count = spec.get("sets") or spec.get("target_sets") or 3
        try:
            count = max(1, min(int(count), 40))
        except (TypeError, ValueError):
            count = 3
        low, high = parse_reps(
            spec.get("reps")
            if spec.get("reps") is not None
            else spec.get("rep_range_low")
        )
        if low is None and spec.get("rep_range_low") is not None:
            low = int(spec["rep_range_low"])
            high = (
                int(spec["rep_range_high"])
                if spec.get("rep_range_high") is not None else low
            )
        rpe = spec.get("rpe_target")
        if rpe is None:
            rpe = spec.get("target_rpe")
        try:
            rpe = float(rpe) if rpe is not None else None
        except (TypeError, ValueError):
            rpe = None

        seconds = None
        if metric is MetricType.TIME:
            seconds = low or 30
            low = high = None

        for index in range(count):
            sets.append(PrescribedSet(
                index=index, role=SetRole.WORKING, metric=metric,
                reps=low if (low is not None and high == low) else None,
                reps_low=low if (high is not None and high != low) else None,
                reps_high=high if (high is not None and high != low) else None,
                seconds=seconds,
                meters=None,
                effort=EffortTarget.RPE if rpe is not None else EffortTarget.NONE,
                rpe=rpe, rest_seconds=default_rest, is_per_side=per_side,
            ))

    reference = spec.get("reference_1rm_kg") or spec.get("training_max_kg")
    try:
        reference = float(reference) if reference is not None else None
    except (TypeError, ValueError):
        reference = None
    if reference is None and any(one.load_percent for one in sets):
        # A percentage with no reference is unusable, and MANUAL is the
        # honest rule for it: the typed shape refuses PERCENTAGE without a
        # reference, and silently inventing one would invent the loads.
        progression = (
            ProgressionRule.MANUAL
            if progression is ProgressionRule.PERCENTAGE else progression
        )

    return PrescribedSlot(
        order=int(spec.get("order_index") or spec.get("order") or 0),
        exercise_id=spec.get("exercise_id") or spec.get("exercise_library_id"),
        exercise_name=name,
        progression=progression,
        sets=sets,
        superset_group=spec.get("superset_group"),
        set_technique=spec.get("set_technique"),
        reference_1rm_kg=reference,
        note=(spec.get("notes") or None),
    )


def parse_session(
    template: Dict[str, Any], *, week: Optional[int] = None,
) -> PrescribedSession:
    """One `fitness_template` row into a typed session."""
    exercises = _as_json(template.get("exercises")) or []
    if not isinstance(exercises, list):
        raise ProgrammingError(
            f"template {template.get('id')} has a non-list exercises column"
        )
    slots: List[PrescribedSlot] = []
    for position, spec in enumerate(exercises):
        if not isinstance(spec, dict):
            continue
        spec = {**spec}
        spec.setdefault("order", position)
        try:
            slots.append(parse_slot(spec, week=week))
        except Exception as exc:
            # One unparseable exercise does not cost the session: the rest
            # of the prescription is still the plan, and a hard failure here
            # would make the whole template unreadable because of one bad
            # row written years ago.
            logger.info(
                "[programming] skipped exercise %r in template %s: %s",
                spec.get("name"), template.get("id"), exc,
            )
    if not slots:
        raise ProgrammingError(
            f"template {template.get('id')} produced no usable exercises"
        )

    scheduled = _as_json(template.get("scheduled_days")) or []
    if isinstance(scheduled, str):
        scheduled = [scheduled]

    return PrescribedSession(
        name=str(template.get("name") or "Session"),
        day_of_week=template.get("day_of_week"),
        scheduled_days=[str(day) for day in scheduled][:7],
        order_in_phase=int(template.get("order_in_phase") or 0),
        slots=sorted(slots, key=lambda slot: slot.order),
        template_id=template.get("id"),
        note=(template.get("notes") or None),
    )


def read_session(
    db: Session, user_id: str, template_id: str, *, week: Optional[int] = None,
) -> PrescribedSession:
    """The typed session for one template, owner-scoped."""
    owner = _require_user(user_id)
    row = db.execute(text("""
        SELECT id, name, scheduled_days, exercises, order_in_phase, notes,
               day_of_week, phase_id, current_revision
        FROM fitness_template
        WHERE id = :id AND user_id = :u
    """), {"id": template_id, "u": owner}).fetchone()
    if row is None:
        raise LookupError(f"template {template_id} not found")
    return parse_session(dict(row._mapping), week=week)


# ─────────────────────────────────────────────────────────────────────────
# The one writer
# ─────────────────────────────────────────────────────────────────────────

def _slot_to_json(slot: PrescribedSlot) -> Dict[str, Any]:
    """A typed slot rendered into the legacy JSON exercise shape.

    The live workout view reads this, so the keys are its keys. A rep range
    becomes "8-10" because that is what it parses; a single target becomes
    "8". `set_plan` is carried through untouched when present, since it is
    richer than this projection and re-deriving it would lose the warmups.
    """
    first_working = next(
        (one for one in slot.sets if one.is_working), slot.sets[0],
    )
    low = first_working.reps_low or first_working.reps
    high = first_working.reps_high or first_working.reps
    if low is not None and high is not None and low != high:
        reps = f"{low}-{high}"
    elif low is not None:
        reps = str(low)
    else:
        reps = "8-10"

    return {
        "name": slot.exercise_name,
        "exercise_id": slot.exercise_id,
        "sets": slot.working_sets,
        "reps": reps,
        "rep_range_low": low,
        "rep_range_high": high,
        "rpe_target": first_working.rpe,
        "rest_seconds": first_working.rest_seconds or 120,
        "progression_rule": slot.progression.value.upper(),
        "notes": slot.note or "",
        "metric_type": first_working.metric.value,
        "is_per_side": first_working.is_per_side,
        "superset_group": slot.superset_group,
        "set_technique": slot.set_technique,
    }


def _slot_to_row(slot: PrescribedSlot) -> Dict[str, Any]:
    """A typed slot rendered into `template_exercise` columns."""
    first_working = next(
        (one for one in slot.sets if one.is_working), slot.sets[0],
    )
    low = first_working.reps_low or first_working.reps
    high = first_working.reps_high or first_working.reps
    return {
        "exercise_name": slot.exercise_name,
        "order_index": slot.order,
        "target_sets": slot.working_sets,
        "rep_range_low": low,
        "rep_range_high": high,
        "target_rpe": first_working.rpe,
        "rest_seconds": first_working.rest_seconds,
        "progression_rule": slot.progression.value.upper(),
        "notes": slot.note,
        "metric_type": first_working.metric.value,
        "is_per_side": first_working.is_per_side,
        "superset_group": slot.superset_group,
        "set_technique": slot.set_technique,
    }


def write_session(
    db: Session,
    user_id: str,
    template_id: str,
    session: PrescribedSession,
    *,
    program_revision_id: Optional[str] = None,
    activate: bool = True,
    commit: bool = True,
) -> int:
    """Write one typed session to BOTH projections and version it.

    This is the single writer §29.1 asks for. Both `template_exercise` and
    `fitness_template.exercises` are rebuilt from the same typed source in
    one transaction, so the three-way disagreement that motivated this
    module cannot reappear through this path.

    `set_plan` on an existing exercise is carried forward by name. The
    typed shape can express a top/backoff week, but the projection into the
    flat JSON cannot hold one — so dropping the original would silently
    strip the loading table off every plan-driven lift the first time its
    template was written through here. That is exactly the bug
    `_sync_template_exercises_json` already guards against, and this keeps
    the guard.

    Returns the new template revision number.
    """
    owner = _require_user(user_id)
    existing = db.execute(text("""
        SELECT exercises, current_revision FROM fitness_template
        WHERE id = :id AND user_id = :u
        FOR UPDATE
    """), {"id": template_id, "u": owner}).fetchone()
    if existing is None:
        raise LookupError(f"template {template_id} not found")

    previous = _as_json(existing.exercises) or []
    carried_plans = {
        spec.get("name"): spec.get("set_plan")
        for spec in previous
        if isinstance(spec, dict) and spec.get("set_plan")
    }

    exercises_json: List[Dict[str, Any]] = []
    for slot in sorted(session.slots, key=lambda one: one.order):
        rendered = _slot_to_json(slot)
        carried = carried_plans.get(slot.exercise_name)
        if carried:
            rendered["set_plan"] = carried
        exercises_json.append(rendered)

    db.execute(text("""
        DELETE FROM template_exercise WHERE template_id = :id
          AND EXISTS (SELECT 1 FROM fitness_template t
                      WHERE t.id = :id AND t.user_id = :u)
    """), {"id": template_id, "u": owner})
    for slot in sorted(session.slots, key=lambda one: one.order):
        params = _slot_to_row(slot)
        params.update({"id": str(uuid.uuid4()), "template_id": template_id})
        db.execute(text("""
            INSERT INTO template_exercise (
                id, template_id, exercise_name, order_index, target_sets,
                rep_range_low, rep_range_high, target_rpe, rest_seconds,
                progression_rule, notes, metric_type, is_per_side,
                superset_group, set_technique, created_at, updated_at
            ) VALUES (
                :id, :template_id, :exercise_name, :order_index,
                :target_sets, :rep_range_low, :rep_range_high, :target_rpe,
                :rest_seconds, :progression_rule, :notes, :metric_type,
                :is_per_side, :superset_group, :set_technique, NOW(), NOW()
            )
        """), params)

    revision = int(existing.current_revision or 0) + 1
    snapshot = session.model_dump(mode="json")
    db.execute(text("""
        INSERT INTO fitness_template_revision (
            id, user_id, template_id, revision, program_revision_id,
            snapshot, snapshot_version, content_hash, working_sets,
            estimated_minutes, activated_at, created_at
        ) VALUES (
            :id, :u, :template, :revision, :program_revision,
            CAST(:snapshot AS JSONB), :snapshot_version, :hash,
            :working_sets, :minutes,
            CASE WHEN :activate THEN NOW() ELSE NULL END, NOW()
        )
    """), {
        "id": str(uuid.uuid4()), "u": owner, "template": template_id,
        "revision": revision, "program_revision": program_revision_id,
        "snapshot": json.dumps(snapshot),
        "snapshot_version": PROGRAM_SNAPSHOT_VERSION,
        "hash": _hash(snapshot), "working_sets": session.working_sets,
        "minutes": session.estimated_minutes(), "activate": activate,
    })

    db.execute(text("""
        UPDATE fitness_template SET
            name = :name,
            scheduled_days = :scheduled,
            exercises = :exercises,
            order_in_phase = :order_in_phase,
            notes = COALESCE(:notes, notes),
            day_of_week = :day_of_week,
            current_revision = :revision,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = :id AND user_id = :u
    """), {
        "name": session.name,
        "scheduled": json.dumps(session.scheduled_days),
        "exercises": json.dumps(exercises_json),
        "order_in_phase": session.order_in_phase,
        "notes": session.note, "day_of_week": session.day_of_week,
        "revision": revision, "id": template_id, "u": owner,
    })

    if commit:
        db.commit()
    return revision


def sync_projections(db: Session, user_id: str, template_id: str) -> int:
    """Re-derive the JSON projection from the relational rows.

    The compatibility entry point for `routes/fitness.py`, which edits
    `template_exercise` directly. It reads the rows, types them, and writes
    both sides through `write_session` — so an edit made through the old
    route produces a revision like any other, and the two projections stay
    equal whichever door was used.
    """
    owner = _require_user(user_id)
    template = db.execute(text("""
        SELECT id, name, scheduled_days, exercises, order_in_phase, notes,
               day_of_week
        FROM fitness_template WHERE id = :id AND user_id = :u
    """), {"id": template_id, "u": owner}).fetchone()
    if template is None:
        raise LookupError(f"template {template_id} not found")

    rows = db.execute(text("""
        SELECT exercise_name, order_index, target_sets, rep_range_low,
               rep_range_high, target_rpe, rest_seconds, progression_rule,
               notes, metric_type, is_per_side, superset_group,
               set_technique
        FROM template_exercise
        WHERE template_id = :id
        ORDER BY order_index ASC, created_at ASC
    """), {"id": template_id}).fetchall()
    if not rows:
        raise ProgrammingError(
            f"template {template_id} has no exercises to synchronise"
        )

    slots = [
        parse_slot({**dict(row._mapping), "order": index})
        for index, row in enumerate(rows)
    ]
    scheduled = _as_json(template.scheduled_days) or []
    if isinstance(scheduled, str):
        scheduled = [scheduled]
    session = PrescribedSession(
        name=str(template.name or "Session"),
        day_of_week=template.day_of_week,
        scheduled_days=[str(day) for day in scheduled][:7],
        order_in_phase=int(template.order_in_phase or 0),
        slots=slots, template_id=template_id,
        note=(template.notes or None),
    )
    return write_session(
        db, owner, template_id, session, activate=True, commit=False,
    )


# ─────────────────────────────────────────────────────────────────────────
# Validation (§29.3)
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class AthleteConstraints:
    """What the draft has to fit inside.

    Read from the owned profile, goals and limitations — never inferred
    from the draft. A validator that took its constraints from the thing
    being validated would approve anything.
    """
    equipment: Set[str] = field(default_factory=set)
    available_days: Set[str] = field(default_factory=set)
    preferred_minutes: Optional[int] = None
    training_level: Optional[str] = None
    experience_years: Optional[float] = None
    logged_sessions: int = 0
    #: Lowercased limitation text plus the exercises it excludes.
    limitations: List[Dict[str, Any]] = field(default_factory=list)
    excluded_exercise_ids: Set[str] = field(default_factory=set)
    goals: List[str] = field(default_factory=list)
    weight_unit: Unit = Unit.LB

    @property
    def is_experienced(self) -> bool:
        """§29.3: no beginner default if experienced history or profile.

        Either signal is enough. A lifter with four years of training and
        no logged sessions here is still not a novice, and somebody with
        two hundred logged sessions and a blank profile is not either.
        """
        if self.training_level in ("intermediate", "advanced"):
            return True
        if (self.experience_years or 0) >= EXPERIENCED_YEARS:
            return True
        return self.logged_sessions >= EXPERIENCED_SESSION_COUNT


def load_constraints(db: Session, user_id: str) -> AthleteConstraints:
    """The athlete's own constraints, from owned rows only."""
    owner = _require_user(user_id)
    constraints = AthleteConstraints()

    profile = db.execute(text("""
        SELECT equipment, available_days, preferred_duration_minutes,
               training_level, training_experience_years,
               excluded_exercise_ids, weight_unit
        FROM fitness_athlete_profile WHERE user_id = :u
    """), {"u": owner}).fetchone()
    if profile is not None:
        constraints.equipment = {
            str(item).strip().lower()
            for item in (_as_json(profile.equipment) or [])
        }
        constraints.available_days = {
            str(item).strip().lower()
            for item in (_as_json(profile.available_days) or [])
        }
        constraints.preferred_minutes = profile.preferred_duration_minutes
        constraints.training_level = profile.training_level
        constraints.experience_years = (
            float(profile.training_experience_years)
            if profile.training_experience_years is not None else None
        )
        constraints.excluded_exercise_ids = {
            str(item) for item in (_as_json(profile.excluded_exercise_ids) or [])
        }
        try:
            constraints.weight_unit = Unit(profile.weight_unit)
        except (ValueError, TypeError):
            constraints.weight_unit = Unit.LB

    # `area` and `excluded_exercise_ids`, not `body_region`/`avoid_movements`:
    # the limitation row records WHICH exercises to avoid, by id, rather
    # than a movement vocabulary. That is the stronger contract — an id
    # survives a rename — and it is also why the description is kept as
    # free text and never parsed for a diagnosis.
    limitation_rows = db.execute(text("""
        SELECT area, description, excluded_exercise_ids,
               modified_exercise_ids, severity_flag
        FROM fitness_athlete_limitation
        WHERE user_id = :u
          AND status = 'active'
          AND (effective_until IS NULL OR effective_until >= CURRENT_DATE)
    """), {"u": owner}).fetchall()
    for row in limitation_rows:
        excluded = {
            str(item) for item in (_as_json(row.excluded_exercise_ids) or [])
        }
        constraints.limitations.append({
            "area": (row.area or "").lower(),
            "description": (row.description or ""),
            "excluded_ids": excluded,
            "modified_ids": {
                str(item)
                for item in (_as_json(row.modified_exercise_ids) or [])
            },
            "severity": row.severity_flag,
        })
        # A limitation's exclusions are exclusions, whatever the profile
        # separately lists.
        constraints.excluded_exercise_ids |= excluded

    # `rationale`, not `description`, and currency is a date window plus
    # `approved_at` rather than a status column.
    goal_rows = db.execute(text("""
        SELECT kind, rationale, is_primary, priority
        FROM fitness_athlete_goal
        WHERE user_id = :u
          AND valid_from <= CURRENT_DATE
          AND (valid_until IS NULL OR valid_until >= CURRENT_DATE)
        ORDER BY is_primary DESC, priority ASC NULLS LAST
    """), {"u": owner}).fetchall()
    constraints.goals = [
        (row.rationale or row.kind or "").strip()
        for row in goal_rows
        if (row.rationale or row.kind)
    ]

    constraints.logged_sessions = db.execute(text("""
        SELECT COUNT(DISTINCT session_date) FROM workout_log
        WHERE user_id = :u
    """), {"u": owner}).scalar() or 0

    return constraints


def _known_exercises(
    db: Session, user_id: str, names: Sequence[str],
) -> Dict[str, Dict[str, Any]]:
    """Library rows for these names, owner-visible.

    Matched on `normalized_name` as well as `name`: the library holds
    "Barbell Bench Press" and a draft will say "barbell bench press", and
    rejecting that as unknown would make the validator useless.
    """
    if not names:
        return {}
    wanted = [name.strip().lower() for name in names if name and name.strip()]
    rows = db.execute(text("""
        SELECT id, name, normalized_name, equipment_required,
               injury_contraindications, load_convention
        FROM exercise_library
        WHERE (owner_user_id = :u OR owner_user_id IS NULL
               OR visibility = 'public')
          AND archived_at IS NULL
          AND (LOWER(name) = ANY(:names)
               OR LOWER(COALESCE(normalized_name, '')) = ANY(:names))
    """), {"u": user_id, "names": wanted}).fetchall()
    found: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        payload = dict(row._mapping)
        for key in ("name", "normalized_name"):
            value = payload.get(key)
            if value:
                found.setdefault(str(value).strip().lower(), payload)
    return found


def prose_findings(draft: ProgramDraftV1) -> List[Any]:
    """Every language finding over a draft's prose, severity intact.

    One traversal with two readers: `validate_draft` turns these into
    `DraftFinding`s, and `generate_draft` filters to the rejecting ones to
    decide whether the draft may be stored at all. Two traversals would
    eventually disagree about which fields count.
    """
    out: List[Any] = []
    for where, prose in _draft_text(draft):
        out.extend(safety.check_text(where, prose))
    return out


def _draft_text(draft: ProgramDraftV1) -> List[Tuple[str, str]]:
    """Every free-text field in a draft, with where it came from.

    The schema has no field for a diagnosis, so prose is the only place one
    can appear — which makes this list the whole surface the language gate
    has to cover.
    """
    parts: List[Tuple[str, str]] = [
        ("title", draft.title),
        ("rationale", draft.rationale),
    ]
    if draft.note:
        parts.append(("note", draft.note))
    parts.extend(
        (f"questions[{index}]", one)
        for index, one in enumerate(draft.questions)
    )
    parts.extend(
        (f"limitations_respected[{index}]", one)
        for index, one in enumerate(draft.limitations_respected)
    )
    for week_index, week in enumerate(draft.weeks):
        if week.note:
            parts.append((f"weeks[{week_index}].note", week.note))
        for session_index, session in enumerate(week.sessions):
            where = f"weeks[{week_index}].sessions[{session_index}]"
            if session.note:
                parts.append((f"{where}.note", session.note))
            for slot_index, slot in enumerate(session.slots):
                if slot.note:
                    parts.append(
                        (f"{where}.slots[{slot_index}].note", slot.note)
                    )
                for one in slot.sets:
                    if one.note:
                        parts.append((
                            f"{where}.slots[{slot_index}].sets[{one.index}]"
                            f".note",
                            one.note,
                        ))
    return parts


def validate_draft(
    db: Session,
    user_id: str,
    draft: ProgramDraftV1,
    constraints: Optional[AthleteConstraints] = None,
) -> DraftValidation:
    """Check a draft against the athlete's own constraints.

    Every finding is either blocking or a question. Nothing is silently
    corrected: a validator that repaired a draft would be writing the
    program, and the person reviewing it would be approving something
    nobody wrote.
    """
    owner = _require_user(user_id)
    constraints = constraints or load_constraints(db, owner)
    findings: List[DraftFinding] = []

    library = _known_exercises(db, owner, draft.all_exercise_names())

    for week_index, week in enumerate(draft.weeks):
        weekly_sets = week.working_sets
        if weekly_sets > MAX_WEEKLY_SETS:
            findings.append(DraftFinding(
                code=DraftValidationCode.IMPLAUSIBLE_VOLUME,
                message=(
                    f"Week {week.program_week} prescribes {weekly_sets} "
                    f"working sets. That is past anything this validator "
                    f"will pass as a parse rather than a plan."
                ),
                path=f"{week_index}",
            ))
        elif weekly_sets > HIGH_WEEKLY_SETS * 3:
            findings.append(DraftFinding(
                code=DraftValidationCode.IMPLAUSIBLE_VOLUME,
                message=(
                    f"Week {week.program_week} prescribes {weekly_sets} "
                    f"working sets across the week — high enough to be worth "
                    f"a second look before it reaches a calendar."
                ),
                blocking=False, path=f"{week_index}",
            ))

        for session_index, session in enumerate(week.sessions):
            path = f"{week_index}/{session_index}"
            minutes = session.estimated_minutes()

            if session.working_sets > MAX_WORKING_SETS_PER_SESSION:
                findings.append(DraftFinding(
                    code=DraftValidationCode.IMPLAUSIBLE_VOLUME,
                    message=(
                        f"{session.name} prescribes {session.working_sets} "
                        f"working sets in one session."
                    ),
                    path=path,
                ))
            if minutes > MAX_SESSION_MINUTES:
                findings.append(DraftFinding(
                    code=DraftValidationCode.IMPLAUSIBLE_DURATION,
                    message=(
                        f"{session.name} works out to about {minutes:.0f} "
                        f"minutes from its own sets and rests. Anything past "
                        f"{MAX_SESSION_MINUTES} is a typo or a different "
                        f"sport."
                    ),
                    path=path,
                ))
            elif minutes < MIN_SESSION_MINUTES:
                findings.append(DraftFinding(
                    code=DraftValidationCode.IMPLAUSIBLE_DURATION,
                    message=(
                        f"{session.name} works out to {minutes:.0f} minutes, "
                        f"which is not a session."
                    ),
                    path=path,
                ))
            elif (constraints.preferred_minutes
                    and minutes > constraints.preferred_minutes * 1.4):
                findings.append(DraftFinding(
                    code=DraftValidationCode.IMPLAUSIBLE_DURATION,
                    message=(
                        f"{session.name} is about {minutes:.0f} minutes "
                        f"against a stated preference of "
                        f"{constraints.preferred_minutes}."
                    ),
                    blocking=False, path=path,
                ))

            if (session.scheduled_days and constraints.available_days
                    and not any(
                        day.strip().lower() in constraints.available_days
                        for day in session.scheduled_days
                    )):
                # A question, not a block: the answer may be "yes, the
                # week changed", and refusing the draft outright would
                # make a schedule change require a re-draft rather than a
                # sentence. `accept_draft` still refuses while it is
                # unanswered, which is the distinction `DraftFinding`
                # exists to carry.
                findings.append(DraftFinding(
                    code=DraftValidationCode.MISSING_CONSTRAINT,
                    message=(
                        f"{session.name} is scheduled on "
                        f"{', '.join(session.scheduled_days)}, which is not "
                        f"among the available days on file "
                        f"({', '.join(sorted(constraints.available_days))}). "
                        f"Has the week changed?"
                    ),
                    blocking=False, path=path,
                ))

            for slot_index, slot in enumerate(session.slots):
                slot_path = f"{path}/{slot_index}"
                findings.extend(_validate_slot(
                    slot, slot_path, library, constraints,
                ))

    # §29.3: respect the limitation without interpreting it. The prompt
    # says so and, until the 2026-10-02 live run, nothing checked it — the
    # draft path never called `safety` at all. Reusing `safety.check_text`
    # rather than carrying a second list: that module already learned the
    # distinction between "rotator cuff tear" (a condition) and "rotator
    # cuff health" (ordinary gym language), and a second list would have to
    # learn it again.
    for finding in prose_findings(draft):
        findings.append(DraftFinding(
            code=DraftValidationCode.DIAGNOSTIC_LANGUAGE,
            message=finding.message,
            # An overclaim is downgrade-severity in the review path and the
            # same here: worth saying, not worth refusing a block over.
            blocking=finding.severity == "reject",
            path=finding.path,
        ))

    if not constraints.equipment:
        findings.append(DraftFinding(
            code=DraftValidationCode.MISSING_CONSTRAINT,
            message=(
                "No equipment is recorded on the profile, so nothing here "
                "can be checked against what is actually available. What "
                "do you have?"
            ),
            blocking=False,
        ))
    if not constraints.goals and not draft.addresses_goals:
        findings.append(DraftFinding(
            code=DraftValidationCode.MISSING_CONSTRAINT,
            message=(
                "No active goal is recorded and the draft does not say what "
                "it is for, so there is nothing to judge it against."
            ),
            blocking=False,
        ))

    # §29.3: no beginner default when the history or the profile says
    # otherwise. Checked on the draft's own loading, not on its prose: a
    # plan whose every set sits at RPE 6 with no top set is a novice plan
    # whatever it calls itself.
    if constraints.is_experienced:
        beginner = _looks_like_a_beginner_plan(draft)
        if beginner:
            findings.append(DraftFinding(
                code=DraftValidationCode.BEGINNER_DEFAULT_REJECTED,
                message=(
                    f"This prescribes novice loading ({beginner}) to "
                    f"somebody with "
                    f"{constraints.logged_sessions} logged sessions and "
                    f"a stated level of "
                    f"{constraints.training_level or 'unrecorded'}. Draft it "
                    f"for the lifter on file."
                ),
            ))

    return DraftValidation(findings=findings)


def _validate_slot(
    slot: PrescribedSlot,
    path: str,
    library: Dict[str, Dict[str, Any]],
    constraints: AthleteConstraints,
) -> List[DraftFinding]:
    findings: List[DraftFinding] = []
    key = slot.exercise_name.strip().lower()
    row = library.get(key)

    if row is None:
        findings.append(DraftFinding(
            code=DraftValidationCode.UNKNOWN_EXERCISE,
            message=(
                f"{slot.exercise_name!r} is not in the exercise library. A "
                f"name that resolves to nothing has no history to progress "
                f"from and no contraindications to check."
            ),
            path=path,
        ))
    else:
        if slot.exercise_id and str(row["id"]) != str(slot.exercise_id):
            findings.append(DraftFinding(
                code=DraftValidationCode.UNKNOWN_EXERCISE,
                message=(
                    f"{slot.exercise_name!r} names library id "
                    f"{slot.exercise_id}, which is a different exercise "
                    f"({row['id']})."
                ),
                path=path,
            ))
        if str(row["id"]) in constraints.excluded_exercise_ids:
            findings.append(DraftFinding(
                code=DraftValidationCode.LIMITATION_CONFLICT,
                message=(
                    f"{slot.exercise_name} is on the athlete's excluded "
                    f"list."
                ),
                path=path,
            ))

        required = {
            str(item).strip().lower()
            for item in (_as_json(row.get("equipment_required")) or [])
        }
        missing = required - constraints.equipment
        if required and constraints.equipment and missing:
            findings.append(DraftFinding(
                code=DraftValidationCode.EQUIPMENT_UNAVAILABLE,
                message=(
                    f"{slot.exercise_name} needs "
                    f"{', '.join(sorted(missing))}, which is not on the "
                    f"equipment list."
                ),
                path=path,
            ))

        contraindications = {
            str(item).strip().lower()
            for item in (_as_json(row.get("injury_contraindications")) or [])
        }
        for limitation in constraints.limitations:
            area = limitation["area"]
            # Matched on the recorded area against the library's own
            # contraindication list, and on the limitation's explicit
            # exclusions. Never on a guess about what the injury IS: §29.3
            # says respect the limitation without diagnosing it. "Avoid
            # these exercises for the left shoulder" is an instruction, and
            # what is wrong with the shoulder is not this module's business.
            if area and area in contraindications:
                findings.append(DraftFinding(
                    code=DraftValidationCode.LIMITATION_CONFLICT,
                    message=(
                        f"{slot.exercise_name} is contraindicated for the "
                        f"recorded {area} limitation."
                    ),
                    path=path,
                ))
            if str(row["id"]) in limitation["modified_ids"]:
                findings.append(DraftFinding(
                    code=DraftValidationCode.LIMITATION_CONFLICT,
                    message=(
                        f"{slot.exercise_name} is marked as needing "
                        f"modification for the recorded {area or 'logged'} "
                        f"limitation, and the draft prescribes it as "
                        f"written."
                    ),
                    blocking=False, path=path,
                ))

    for one in slot.sets:
        if one.load_kg is not None and one.load_unit is None:
            findings.append(DraftFinding(
                code=DraftValidationCode.MISSING_LOAD_UNIT,
                message=(
                    f"{slot.exercise_name} set {one.index} prescribes a load "
                    f"with no unit."
                ),
                path=path,
            ))
        if one.load_percent is not None and one.load_percent > 105:
            findings.append(DraftFinding(
                code=DraftValidationCode.IMPLAUSIBLE_INTENSITY,
                message=(
                    f"{slot.exercise_name} set {one.index} prescribes "
                    f"{one.load_percent:.0f}% of a max."
                ),
                path=path,
            ))
        if one.rpe is not None and one.reps and one.reps > 20 and one.rpe >= 9.5:
            findings.append(DraftFinding(
                code=DraftValidationCode.IMPLAUSIBLE_INTENSITY,
                message=(
                    f"{slot.exercise_name} set {one.index} asks for "
                    f"{one.reps} reps at RPE {one.rpe}."
                ),
                blocking=False, path=path,
            ))
        if (one.metric is MetricType.REPS and one.reps_high
                and one.reps_low and one.reps_high - one.reps_low > 12):
            findings.append(DraftFinding(
                code=DraftValidationCode.IMPLAUSIBLE_INTENSITY,
                message=(
                    f"{slot.exercise_name} set {one.index} spans "
                    f"{one.reps_low}-{one.reps_high} reps, which is not a "
                    f"target."
                ),
                blocking=False, path=path,
            ))

    if (slot.progression is ProgressionRule.PERCENTAGE
            and slot.reference_1rm_kg is None):
        findings.append(DraftFinding(
            code=DraftValidationCode.MISSING_CONSTRAINT,
            message=(
                f"{slot.exercise_name} is prescribed as percentages but no "
                f"reference max is on file. What should it be a percentage "
                f"of?"
            ),
            blocking=False, path=path,
        ))
    return findings


def _looks_like_a_beginner_plan(draft: ProgramDraftV1) -> Optional[str]:
    """Why this reads as a novice plan, or None.

    Two signals, both about the loading rather than the language: no set
    anywhere above RPE 8, and no exercise carrying more than three working
    sets. Either alone is a legitimate choice; together, across a whole
    draft, it is the template a model reaches for when it has not read the
    history.
    """
    efforts = [
        one.rpe for week in draft.weeks for session in week.sessions
        for slot in session.slots for one in slot.sets
        if one.rpe is not None
    ]
    max_sets = max(
        (slot.working_sets for week in draft.weeks
         for session in week.sessions for slot in session.slots),
        default=0,
    )
    if efforts and max(efforts) <= 8.0 and max_sets <= 3:
        return (
            f"nothing above RPE {max(efforts):.1f} and at most "
            f"{max_sets} working sets per exercise"
        )
    return None


# ─────────────────────────────────────────────────────────────────────────
# Drafts: store, preview, accept (§29.2, §29.5)
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class StoredDraft:
    id: str
    kind: DraftBlockKind
    status: DraftStatus
    draft: ProgramDraftV1
    validation: DraftValidation
    program_id: Optional[str]
    phase_id: Optional[str]
    base_revision: Optional[int]
    model_actual: Optional[str]
    created_at: Optional[datetime]
    resulting_revision_id: Optional[str] = None
    decision_reason: Optional[str] = None


def current_revision(
    db: Session, user_id: str, program_id: Optional[str],
) -> int:
    """The program's current revision, 0 when it has none yet."""
    if not program_id:
        return 0
    return db.execute(text("""
        SELECT COALESCE(MAX(revision), 0) FROM fitness_program_revision
        WHERE user_id = :u AND program_id = :p
    """), {"u": _require_user(user_id), "p": program_id}).scalar() or 0


def store_draft(
    db: Session,
    user_id: str,
    draft: ProgramDraftV1,
    *,
    program_id: Optional[str] = None,
    phase_id: Optional[str] = None,
    model_actual: Optional[str] = None,
    prompt_version: Optional[str] = None,
    science_citations: Optional[Sequence[Dict[str, Any]]] = None,
    requested_by: str = "user",
    ttl_days: int = 14,
    constraints: Optional[AthleteConstraints] = None,
) -> StoredDraft:
    """Validate and store a draft. Never activates anything.

    The validation is stored with the draft rather than recomputed on read:
    the constraints can change, and what the reviewer needs to see is what
    was true when the draft was made. Recomputing would quietly turn a
    blocked draft into an acceptable one because a limitation expired.
    """
    owner = _require_user(user_id)
    validation = validate_draft(db, owner, draft, constraints)

    # Supersede any open draft of the same kind for this program: the
    # unique partial index allows one, and two proposals for the same weeks
    # accepted in either order produce a different program.
    db.execute(text("""
        UPDATE fitness_program_draft
        SET status = 'stale', updated_at = NOW()
        WHERE user_id = :u AND status = 'draft' AND kind = :kind
          AND COALESCE(program_id, '') = COALESCE(:program, '')
    """), {"u": owner, "kind": draft.kind.value, "program": program_id})

    draft_id = str(uuid.uuid4())
    base = current_revision(db, owner, program_id)
    questions = [
        finding.message for finding in validation.questions
    ]
    db.execute(text("""
        INSERT INTO fitness_program_draft (
            id, user_id, kind, status, program_id, phase_id, base_revision,
            payload, payload_version, validation, open_questions,
            model_actual, prompt_version, prompt_hash, science_citations,
            requested_by, valid_until, created_at, updated_at
        ) VALUES (
            :id, :u, :kind, 'draft', :program, :phase, :base,
            CAST(:payload AS JSONB), :payload_version,
            CAST(:validation AS JSONB), CAST(:questions AS JSONB),
            :model, :prompt_version, :prompt_hash,
            CAST(:citations AS JSONB), :requested_by, :valid_until,
            NOW(), NOW()
        )
    """), {
        "id": draft_id, "u": owner, "kind": draft.kind.value,
        "program": program_id, "phase": phase_id, "base": base,
        "payload": draft.model_dump_json(),
        "payload_version": draft.draft_version,
        "validation": validation.model_dump_json(),
        "questions": json.dumps(questions),
        "model": model_actual, "prompt_version": prompt_version,
        "prompt_hash": _hash(prompt_version or ""),
        "citations": json.dumps(list(science_citations or [])),
        "requested_by": requested_by,
        "valid_until": _now() + timedelta(days=ttl_days),
    })
    db.commit()
    logger.info(
        "[programming] stored draft %s (%s, %d blocking, %d questions)",
        draft_id, draft.kind.value, len(validation.blocking), len(questions),
    )
    return StoredDraft(
        id=draft_id, kind=draft.kind, status=DraftStatus.DRAFT, draft=draft,
        validation=validation, program_id=program_id, phase_id=phase_id,
        base_revision=base, model_actual=model_actual, created_at=_now(),
    )


def get_draft(db: Session, user_id: str, draft_id: str) -> StoredDraft:
    owner = _require_user(user_id)
    row = db.execute(text("""
        SELECT id, kind, status, program_id, phase_id, base_revision,
               payload, validation, model_actual, created_at,
               resulting_revision_id, decision_reason
        FROM fitness_program_draft
        WHERE id = :id AND user_id = :u
    """), {"id": draft_id, "u": owner}).fetchone()
    if row is None:
        raise LookupError(f"draft {draft_id} not found")
    payload = _as_json(row.payload) or {}
    validation = _as_json(row.validation) or {"findings": []}
    return StoredDraft(
        id=row.id, kind=DraftBlockKind(row.kind),
        status=DraftStatus(row.status),
        draft=ProgramDraftV1.model_validate(payload),
        validation=DraftValidation.model_validate(validation),
        program_id=row.program_id, phase_id=row.phase_id,
        base_revision=row.base_revision, model_actual=row.model_actual,
        created_at=row.created_at,
        resulting_revision_id=row.resulting_revision_id,
        decision_reason=row.decision_reason,
    )


def list_drafts(
    db: Session, user_id: str, *, status: Optional[DraftStatus] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    owner = _require_user(user_id)
    rows = db.execute(text("""
        SELECT id, kind, status, program_id, phase_id, base_revision,
               open_questions, model_actual, created_at, decided_at,
               decision_reason, resulting_revision_id,
               jsonb_array_length(COALESCE(validation -> 'findings', '[]'::jsonb))
                   AS finding_count
        FROM fitness_program_draft
        WHERE user_id = :u
          AND (CAST(:status AS VARCHAR) IS NULL
               OR status = CAST(:status AS VARCHAR))
        ORDER BY created_at DESC
        LIMIT :limit
    """), {
        "u": owner, "status": status.value if status else None,
        "limit": max(1, min(limit, 100)),
    }).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row._mapping)
        for key in ("created_at", "decided_at"):
            if item.get(key):
                item[key] = item[key].isoformat()
        item["open_questions"] = _as_json(item.get("open_questions")) or []
        out.append(item)
    return out


def preview_draft(
    db: Session, user_id: str, draft_id: str,
) -> ProgramChangePreview:
    """Exactly what accepting this draft would do.

    §29.5. Every field exists because "it will update your program" is not
    something anybody can agree to: the dates, the per-session changes and
    the resulting revision are the agreement.
    """
    owner = _require_user(user_id)
    stored = get_draft(db, owner, draft_id)
    base = current_revision(db, owner, stored.program_id)

    program_name = None
    if stored.program_id:
        program_name = db.execute(text("""
            SELECT name FROM fitness_program
            WHERE id = :p AND user_id = :u
        """), {"p": stored.program_id, "u": owner}).scalar()

    phase_name = effective_start = effective_end = None
    if stored.phase_id:
        phase = db.execute(text("""
            SELECT name, start_date, end_date FROM fitness_phase
            WHERE id = :id AND user_id = :u
        """), {"id": stored.phase_id, "u": owner}).fetchone()
        if phase is not None:
            phase_name = phase.name
            effective_start = phase.start_date
            effective_end = phase.end_date

    existing_templates = {}
    if stored.phase_id:
        for row in db.execute(text("""
            SELECT id, name, current_revision FROM fitness_template
            WHERE phase_id = :phase AND user_id = :u
        """), {"phase": stored.phase_id, "u": owner}).fetchall():
            existing_templates[str(row.name).strip().lower()] = dict(row._mapping)

    changes: List[Dict[str, Any]] = []
    minutes: List[float] = []
    total_sets = 0
    for week in stored.draft.weeks:
        for session in week.sessions:
            total_sets += session.working_sets
            minutes.append(session.estimated_minutes())
            match = (
                existing_templates.get(session.name.strip().lower())
                if session.template_id is None
                else {"id": session.template_id, "name": session.name,
                      "current_revision": None}
            )
            changes.append({
                "session": session.name,
                "program_week": week.program_week,
                "action": "replace" if match else "create",
                "template_id": (match or {}).get("id"),
                "from_revision": (match or {}).get("current_revision"),
                "working_sets": session.working_sets,
                "estimated_minutes": session.estimated_minutes(),
                "exercises": [slot.exercise_name for slot in session.slots],
                "scheduled_days": session.scheduled_days,
            })

    warnings = [finding.message for finding in stored.validation.findings]
    if stored.base_revision is not None and stored.base_revision != base:
        warnings.insert(0, (
            f"This draft was built against revision {stored.base_revision} "
            f"and the program is now at {base}. Accepting it would apply a "
            f"plan written for a different program."
        ))

    return ProgramChangePreview(
        draft_id=draft_id, program_id=stored.program_id,
        program_name=program_name, base_revision=base,
        resulting_revision=base + 1, phase_id=stored.phase_id,
        phase_name=phase_name, effective_start=effective_start,
        effective_end=effective_end, template_changes=changes,
        # Empty, always, from a training draft. A plan that silently moved
        # calories would be the worst kind of surprise, so target changes
        # go through `recommendations`/`targets` where they are decided one
        # at a time.
        target_changes=[],
        weeks_affected=[week.program_week for week in stored.draft.weeks],
        total_working_sets=total_sets, estimated_session_minutes=minutes,
        warnings=warnings,
    )


def accept_draft(
    db: Session,
    user_id: str,
    draft_id: str,
    *,
    decided_by: str,
    reason: str,
    effect_scope: str = "forward",
    effective_from: Optional[date] = None,
) -> Dict[str, Any]:
    """Version and activate a draft, atomically.

    Everything here is one transaction: the program revision, every
    template revision, both projections of every session, and the draft's
    own decision. A partial activation would leave the athlete with three
    of five sessions changed and no way to tell which.

    Refuses when:

    * the draft is not `draft` — a decided draft is the audit trail for the
      revision it produced;
    * validation has anything blocking — §29 completion: no unreviewed
      model plan is activated;
    * a question is unanswered;
    * the program moved under it (`RevisionConflict`).

    `decided_by` is recorded and may not be a model. The database agrees:
    `ck_program_draft_decided_by` and
    `ck_program_revision_activated_by` both refuse one.
    """
    owner = _require_user(user_id)
    if not decided_by or not decided_by.strip():
        raise ProgrammingError(
            "acceptance records who accepted it; there is no default"
        )
    if decided_by.strip().lower() in ("model", "llm", "autonomous", "system"):
        raise ProgrammingError(
            f"{decided_by!r} cannot accept a program draft. §29.2: the model "
            f"drafts and a person activates."
        )
    if len(reason.strip()) < 5:
        raise ProgrammingError(
            "acceptance needs a reason — it is the audit for every session "
            "this rewrites"
        )
    if effect_scope not in ("forward", "retroactive"):
        raise ProgrammingError(f"unknown effect scope {effect_scope!r}")

    row = db.execute(text("""
        SELECT id, status, program_id, phase_id, base_revision, payload,
               validation, open_questions
        FROM fitness_program_draft
        WHERE id = :id AND user_id = :u
        FOR UPDATE
    """), {"id": draft_id, "u": owner}).fetchone()
    if row is None:
        raise LookupError(f"draft {draft_id} not found")
    if row.status != DraftStatus.DRAFT.value:
        raise ProgrammingError(
            f"draft {draft_id} is {row.status}; its decision is already "
            f"recorded and is the audit trail for whatever it produced"
        )

    validation = DraftValidation.model_validate(
        _as_json(row.validation) or {"findings": []}
    )
    if validation.blocking:
        raise ProgrammingError(
            "this draft has "
            f"{len(validation.blocking)} blocking finding(s) and cannot be "
            f"activated: "
            + "; ".join(one.message for one in validation.blocking[:3])
        )
    questions = _as_json(row.open_questions) or []
    if questions:
        raise ProgrammingError(
            f"{len(questions)} question(s) are unanswered: "
            + "; ".join(str(one) for one in questions[:3])
        )

    base = current_revision(db, owner, row.program_id)
    if row.base_revision is not None and row.base_revision != base:
        raise RevisionConflict(
            f"the draft was built against revision {row.base_revision} and "
            f"the program is now at {base}. Re-read it: applying it would "
            f"activate a plan written for a different program.",
            base=row.base_revision, current=base,
        )

    draft = ProgramDraftV1.model_validate(_as_json(row.payload) or {})

    revision_id = str(uuid.uuid4())
    snapshot = draft.model_dump(mode="json")
    db.execute(text("""
        INSERT INTO fitness_program_revision (
            id, user_id, program_id, revision, label, snapshot,
            snapshot_version, content_hash, source, draft_id,
            effective_from, effect_scope, activated_at, activated_by,
            notes, created_at
        ) VALUES (
            :id, :u, :program, :revision, :label, CAST(:snapshot AS JSONB),
            :snapshot_version, :hash, 'draft', :draft,
            :effective_from, :scope, NOW(), :by, :notes, NOW()
        )
    """), {
        "id": revision_id, "u": owner,
        # A draft can target a program that does not exist yet (a first
        # plan). The draft id stands in, so the revision chain still has a
        # stable key rather than a NULL that collides with every other.
        "program": row.program_id or f"draft:{draft_id}",
        "revision": base + 1, "label": draft.title,
        "snapshot": json.dumps(snapshot),
        "snapshot_version": PROGRAM_SNAPSHOT_VERSION,
        "hash": _hash(snapshot), "draft": draft_id,
        "effective_from": effective_from, "scope": effect_scope,
        "by": decided_by.strip(), "notes": reason.strip(),
    })

    activated: List[Dict[str, Any]] = []
    for week in draft.weeks:
        for session in week.sessions:
            template_id = session.template_id or _find_template(
                db, owner, row.phase_id, session.name,
            )
            if template_id is None:
                template_id = _create_template(
                    db, owner, row.phase_id, session,
                )
                action = "created"
            else:
                action = "replaced"
            template_revision = write_session(
                db, owner, template_id, session,
                program_revision_id=revision_id, activate=True, commit=False,
            )
            activated.append({
                "template_id": template_id, "session": session.name,
                "action": action, "revision": template_revision,
                "program_week": week.program_week,
            })

    db.execute(text("""
        UPDATE fitness_program_draft SET
            status = 'accepted', decided_at = NOW(), decided_by = :by,
            decision_reason = :reason, resulting_revision_id = :revision,
            updated_at = NOW()
        WHERE id = :id AND user_id = :u
    """), {
        "by": decided_by.strip(), "reason": reason.strip(),
        "revision": revision_id, "id": draft_id, "u": owner,
    })

    if row.phase_id:
        db.execute(text("""
            UPDATE fitness_phase SET program_revision = :revision,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :id AND user_id = :u
        """), {"revision": base + 1, "id": row.phase_id, "u": owner})

    db.commit()
    logger.info(
        "[programming] draft %s accepted by %s -> revision %d (%d sessions)",
        draft_id, decided_by, base + 1, len(activated),
    )
    return {
        "draft_id": draft_id,
        "program_revision_id": revision_id,
        "revision": base + 1,
        "effect_scope": effect_scope,
        "templates": activated,
    }


def reject_draft(
    db: Session, user_id: str, draft_id: str, *, decided_by: str, reason: str,
) -> Dict[str, Any]:
    """Decline a draft, with the reason kept.

    The draft and its payload stay: the same proposal will be generated
    again, and "we looked at this and said no, because X" is the only thing
    that stops it being re-proposed forever.
    """
    owner = _require_user(user_id)
    if len(reason.strip()) < 5:
        raise ProgrammingError(
            "a rejection needs a reason, or the same draft comes back next "
            "week"
        )
    updated = db.execute(text("""
        UPDATE fitness_program_draft SET
            status = 'rejected', decided_at = NOW(), decided_by = :by,
            decision_reason = :reason, updated_at = NOW()
        WHERE id = :id AND user_id = :u AND status = 'draft'
        RETURNING id
    """), {
        "by": decided_by.strip(), "reason": reason.strip(),
        "id": draft_id, "u": owner,
    }).fetchone()
    if updated is None:
        raise ProgrammingError(
            f"draft {draft_id} is not open for a decision"
        )
    db.commit()
    return {"draft_id": draft_id, "status": "rejected"}


def _find_template(
    db: Session, user_id: str, phase_id: Optional[str], name: str,
) -> Optional[str]:
    if not phase_id:
        return None
    return db.execute(text("""
        SELECT id FROM fitness_template
        WHERE user_id = :u AND phase_id = :phase
          AND LOWER(name) = LOWER(:name)
        ORDER BY created_at ASC
        LIMIT 1
    """), {"u": user_id, "phase": phase_id, "name": name}).scalar()


def _create_template(
    db: Session, user_id: str, phase_id: Optional[str],
    session: PrescribedSession,
) -> str:
    """An empty template row for a session the draft introduces.

    Created empty and immediately written through `write_session`, so there
    is never a template whose JSON and relational rows were populated by
    two different writers.
    """
    template_id = str(uuid.uuid4())
    db.execute(text("""
        INSERT INTO fitness_template (
            id, phase_id, user_id, name, scheduled_days, exercises,
            order_in_phase, day_of_week, current_revision,
            created_at, updated_at
        ) VALUES (
            :id, :phase, :u, :name, '[]', '[]', :order, :day, 0,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
    """), {
        "id": template_id, "phase": phase_id, "u": user_id,
        "name": session.name, "order": session.order_in_phase,
        "day": session.day_of_week,
    })
    return template_id


# ─────────────────────────────────────────────────────────────────────────
# Deterministic progression (§29.4)
# ─────────────────────────────────────────────────────────────────────────
#
# No model is consulted anywhere below. The inputs are the configured rule,
# the last comparable performance and the recovery state; the output names
# which rule fired. "Add 5lbs" with no reason is indistinguishable from a
# guess, and a guess is what a model would produce here.
#
# `progressive_overload.py` remains THE progression brain for the in-session
# suggestion (flat-increment, RPE-gated, recovery-aware) and is reused for
# recovery gating. This adds the rule-typed variants the plan asks for —
# double, linear, percentage — and routes to the existing implementation's
# recovery semantics rather than inventing a second set.

#: Upper-body and lower-body increments, in kilograms. The existing brain
#: works in pounds (5 and 10); these are the same jumps expressed in the
#: canonical storage unit, so the two cannot drift by rounding.
LINEAR_INCREMENT_KG = {"upper": 2.5, "lower": 5.0}
_LOWER_BODY_MARKERS = (
    "squat", "deadlift", "leg", "lunge", "hip", "calf", "glute",
)


def _is_lower_body(exercise_name: str) -> bool:
    lowered = exercise_name.lower()
    return any(marker in lowered for marker in _LOWER_BODY_MARKERS)


def _round_plate_kg(weight: float) -> float:
    """To the nearest 1.25kg — the smallest pair of plates most gyms have.

    Rounding to 2.5 would make every upper-body increment either doubled or
    dropped, which is how a linear progression becomes a plateau.
    """
    return round(weight / 1.25) * 1.25


def _comparable_sets(
    db: Session, user_id: str, exercise_name: str, *, limit: int = 3,
) -> List[Dict[str, Any]]:
    """Recent sessions for this lift, newest first.

    "Comparable" is doing real work here: sets are matched on the exercise
    and on the same load convention, so an assisted pull-up's 30kg of
    *help* is never read as 30kg lifted, and a dumbbell press logged per
    hand is not compared against a barbell. `effective_load` is the one
    implementation of that, and this reuses it.
    """
    from app.services.fitness.data_access import adapt_set_row, athlete_zone

    owner = _require_user(user_id)
    tz = athlete_zone(db.execute(text("""
        SELECT timezone FROM fitness_athlete_profile WHERE user_id = :u
    """), {"u": owner}).scalar())

    rows = db.execute(text("""
        SELECT wl.id, wl.session_date, wl.reps, wl.load_value, wl.load_unit,
               wl.rpe, wl.flags, wl.set_index, wl.skipped,
               wl.exercise_id, el.name AS exercise_name,
               el.load_convention, el.is_unilateral
        FROM workout_log wl
        LEFT JOIN exercise_library el ON el.id = wl.exercise_id
        WHERE wl.user_id = :u
          AND COALESCE(wl.skipped, FALSE) = FALSE
          AND LOWER(COALESCE(el.name, '')) = LOWER(:name)
        ORDER BY wl.session_date DESC, wl.set_index ASC
        LIMIT 200
    """), {"u": owner, "name": exercise_name}).fetchall()

    from app.services.fitness.exercises import COMPARABLE_LOAD_CONVENTIONS

    by_date: Dict[Any, List[Any]] = {}
    for row in rows:
        # "Comparable" is `exercises.COMPARABLE_LOAD_CONVENTIONS`, the one
        # definition: total and per-hand. An assisted pull-up's 30kg is 30kg
        # of HELP and a machine stack's "12" is a pin position, so neither
        # can enter a progression figure — and an unrecorded convention is
        # not an assumption of `total`.
        if (row.load_convention or "") not in COMPARABLE_LOAD_CONVENTIONS:
            continue
        by_date.setdefault(row.session_date, []).append(row)

    sessions: List[Dict[str, Any]] = []
    for session_date in sorted(by_date, reverse=True)[:limit]:
        loads: List[float] = []
        reps: List[int] = []
        efforts: List[float] = []
        unit = Unit.KG
        for row in by_date[session_date]:
            adapted = adapt_set_row(row, tz=tz)
            # `load_kg` is the canonical figure: `load` is whatever unit the
            # client sent, and comparing a pound set against a kilogram one
            # is how a progression suggests a 2.2x jump.
            canonical = adapted.load_kg
            if canonical is None or not adapted.reps:
                # A set whose effective load is unknown is left out rather
                # than counted at its recorded number.
                continue
            loads.append(float(canonical))
            reps.append(int(adapted.reps))
            if adapted.rpe is not None:
                efforts.append(float(adapted.rpe))
        if not loads:
            continue
        sessions.append({
            "date": session_date,
            "top_load": max(loads),
            "mean_load": sum(loads) / len(loads),
            "min_reps": min(reps),
            "max_reps": max(reps),
            "sets": len(loads),
            "mean_rpe": (sum(efforts) / len(efforts)) if efforts else None,
            "unit": unit,
        })
    return sessions


@dataclass
class RecoveryGate:
    """What recovery and pain permit today.

    `action` is one of advance / hold / reduce / deload. Built on
    `progressive_overload`'s existing recovery semantics rather than a
    second set: that module is THE progression brain and its rule —
    recovery never inflates a jump, at most it downgrades an advance to a
    hold — is the one being preserved here.
    """
    action: str
    reason: str
    factor: float = 1.0


#: Pain at or above this, on the check-in's 0-10 scale, reduces load rather
#: than holding it. Below it, pain holds. Zero pain is not the same as no
#: pain recorded, and neither is treated as permission.
PAIN_REDUCE_THRESHOLD = 6
PAIN_HOLD_THRESHOLD = 3


#: How far back a pain report still gates load. Seven days: a report from
#: three weeks ago that was never followed up should not hold a lift
#: forever — that is the self-reinforcing nag shape this codebase has been
#: through — and a report from yesterday obviously should.
PAIN_LOOKBACK_DAYS = 7


def _recent_pain(
    db: Session, user_id: str, on_date: date,
) -> Optional[int]:
    """The worst pain severity reported in the last week, or None.

    None means "nothing reported", which is NOT the same as zero. A zero
    would read as "checked and fine"; this returns None so the gate falls
    through to the recovery factor instead of treating silence as consent.
    """
    try:
        severity = db.execute(text("""
            SELECT MAX(r.severity)
            FROM fitness_pain_report r
            WHERE r.user_id = :u
              AND r.superseded_by_id IS NULL
              AND COALESCE(r.pain_present, FALSE) = TRUE
              AND r.occurred_at >= :since
        """), {
            "u": user_id,
            "since": datetime.combine(
                on_date - timedelta(days=PAIN_LOOKBACK_DAYS),
                datetime.min.time(), tzinfo=UTC,
            ),
        }).scalar()
    except Exception as exc:
        logger.info("[programming] pain reports unreadable: %s", exc)
        return None
    return int(severity) if severity is not None else None


def recovery_gate(
    db: Session,
    user_id: str,
    on_date: date,
    *,
    recovery: Optional[Dict[str, Any]] = None,
) -> RecoveryGate:
    """Whether today permits adding load.

    A scheduled deload wins outright: the phase says this week is a
    deload, and a good night's sleep does not override the plan. Then pain,
    then the recovery factor.
    """
    from app.services import progressive_overload

    owner = _require_user(user_id)

    try:
        deload = progressive_overload.get_deload_state(db, owner, on_date)
    except Exception as exc:
        logger.info("[programming] deload state unreadable: %s", exc)
        deload = {"is_deload": False}
    if deload.get("is_deload"):
        return RecoveryGate(
            action="deload",
            reason=(
                f"week {deload.get('week_of_phase')} of "
                f"{deload.get('phase_name') or 'this phase'} is the "
                f"scheduled deload"
            ),
        )

    if recovery is None:
        try:
            recovery = progressive_overload.get_morning_recovery(
                db, owner, on_date,
            )
        except Exception as exc:
            logger.info("[programming] recovery unreadable: %s", exc)
            recovery = None

    # Pain is read here rather than taken from the recovery snapshot:
    # `get_morning_recovery` carries HRV, sleep, heart rate and soreness,
    # and pain is a different thing recorded in a different place
    # (`fitness_pain_report`, per exercise performance). Treating soreness
    # as pain would make a hard leg day a reason to reduce load, and
    # ignoring pain would make a reported injury invisible to progression.
    pain = _recent_pain(db, owner, on_date)
    if pain is not None and pain >= PAIN_REDUCE_THRESHOLD:
        return RecoveryGate(
            action="reduce",
            reason=f"pain reported at {pain}/10 within the last week",
        )
    if pain is not None and pain >= PAIN_HOLD_THRESHOLD:
        return RecoveryGate(
            action="hold",
            reason=f"pain reported at {pain}/10 within the last week",
        )

    factor, reason = progressive_overload.get_recovery_factor(recovery)
    if factor < 0.95:
        return RecoveryGate(action="hold", reason=reason, factor=factor)
    return RecoveryGate(action="advance", reason=reason, factor=factor)


def progression_for(
    db: Session,
    user_id: str,
    slot: PrescribedSlot,
    *,
    on_date: Optional[date] = None,
    recovery: Optional[Dict[str, Any]] = None,
) -> ProgressionDecision:
    """What to do with this exercise's load, deterministically.

    Four rules, and which one applies is configured on the slot rather than
    chosen here. Recovery and pain can downgrade an advance to a hold,
    reduce, or deload; they never inflate a jump — that is
    `progressive_overload`'s existing rule and breaking it here would make
    a good night's sleep a reason to add weight.
    """
    owner = _require_user(user_id)
    on_date = on_date or date.today()
    history = _comparable_sets(db, owner, slot.exercise_name)

    if not history:
        return ProgressionDecision(
            exercise_name=slot.exercise_name, rule=slot.progression,
            action="ask",
            reason=(
                "No comparable logged sets for this lift, so there is no "
                "load to progress from. A suggestion here would be a guess "
                "dressed as a plan."
            ),
            basis_sessions=0,
        )

    last = history[0]
    unit = last["unit"]
    target = next((one for one in slot.sets if one.is_working), slot.sets[0])
    target_low = target.reps_low or target.reps
    target_high = target.reps_high or target.reps

    gate = recovery_gate(db, owner, on_date, recovery=recovery)
    if gate.action == "deload":
        return ProgressionDecision(
            exercise_name=slot.exercise_name, rule=slot.progression,
            action="deload",
            suggested_load_kg=_round_plate_kg(last["mean_load"] * 0.6),
            load_unit=unit,
            reason=(
                f"Deload: {gate.reason}. 60% of the last working load, and "
                f"the rep targets stand."
            ),
            basis_sessions=len(history), recovery_override=gate.reason,
        )
    if gate.action == "reduce":
        return ProgressionDecision(
            exercise_name=slot.exercise_name, rule=slot.progression,
            action="reduce",
            suggested_load_kg=_round_plate_kg(last["mean_load"] * 0.9),
            load_unit=unit,
            reason=f"Reducing 10%: {gate.reason}.",
            basis_sessions=len(history), recovery_override=gate.reason,
        )

    holding = gate.action == "hold"

    if slot.progression is ProgressionRule.MANUAL:
        return ProgressionDecision(
            exercise_name=slot.exercise_name, rule=slot.progression,
            action="hold", suggested_load_kg=last["mean_load"],
            load_unit=unit,
            reason=(
                "Manual progression: holding the last load and leaving the "
                "call to you."
            ),
            basis_sessions=len(history),
            recovery_override=gate.reason if holding else None,
        )

    if slot.progression is ProgressionRule.PERCENTAGE:
        if slot.reference_1rm_kg is None or target.load_percent is None:
            return ProgressionDecision(
                exercise_name=slot.exercise_name, rule=slot.progression,
                action="ask",
                reason=(
                    "Percentage progression with no reference max on file. "
                    "A percentage of nothing is not a prescription."
                ),
                basis_sessions=len(history),
            )
        prescribed = _round_plate_kg(
            slot.reference_1rm_kg * target.load_percent / 100.0
        )
        return ProgressionDecision(
            exercise_name=slot.exercise_name, rule=slot.progression,
            action="hold" if holding else "advance_load",
            suggested_load_kg=prescribed, load_unit=unit,
            reason=(
                f"{target.load_percent:.0f}% of a "
                f"{slot.reference_1rm_kg:.1f}kg reference, from the plan "
                f"rather than from last week"
                + (f"; holding there because {gate.reason}" if holding else "")
            ),
            basis_sessions=len(history),
            recovery_override=gate.reason if holding else None,
        )

    met_top = (
        target_high is not None and last["min_reps"] >= target_high
    )
    met_floor = (
        target_low is not None and last["min_reps"] >= target_low
    )
    felt_easy = last["mean_rpe"] is None or last["mean_rpe"] < 8.5

    if slot.progression is ProgressionRule.LINEAR:
        increment = LINEAR_INCREMENT_KG[
            "lower" if _is_lower_body(slot.exercise_name) else "upper"
        ]
        if met_floor and felt_easy and not holding:
            return ProgressionDecision(
                exercise_name=slot.exercise_name, rule=slot.progression,
                action="advance_load",
                suggested_load_kg=_round_plate_kg(
                    last["mean_load"] + increment
                ),
                suggested_reps=target_low, load_unit=unit,
                reason=(
                    f"Linear: hit {last['min_reps']} reps at "
                    f"{last['mean_load']:.1f} last time"
                    + (
                        f" at RPE {last['mean_rpe']:.1f}"
                        if last["mean_rpe"] is not None else ""
                    )
                    + f", so +{increment}kg."
                ),
                basis_sessions=len(history),
            )
        return ProgressionDecision(
            exercise_name=slot.exercise_name, rule=slot.progression,
            action="hold", suggested_load_kg=last["mean_load"],
            suggested_reps=target_low, load_unit=unit,
            reason=(
                f"Holding {last['mean_load']:.1f}: "
                + (
                    gate.reason if holding
                    else (
                        f"last session was {last['min_reps']} reps"
                        + (
                            f" at RPE {last['mean_rpe']:.1f}"
                            if last["mean_rpe"] is not None else ""
                        )
                        + f" against a {target_low}-rep floor"
                    )
                )
                + "."
            ),
            basis_sessions=len(history),
            recovery_override=gate.reason if holding else None,
        )

    # Double progression: add reps inside the range, then load and drop to
    # the bottom of it.
    increment = LINEAR_INCREMENT_KG[
        "lower" if _is_lower_body(slot.exercise_name) else "upper"
    ]
    if met_top and felt_easy and not holding:
        return ProgressionDecision(
            exercise_name=slot.exercise_name, rule=slot.progression,
            action="advance_load",
            suggested_load_kg=_round_plate_kg(last["mean_load"] + increment),
            suggested_reps=target_low, load_unit=unit,
            reason=(
                f"Double progression: {last['min_reps']} reps at the top of "
                f"the {target_low}-{target_high} range, so +{increment}kg "
                f"and back to {target_low}."
            ),
            basis_sessions=len(history),
        )
    if holding:
        return ProgressionDecision(
            exercise_name=slot.exercise_name, rule=slot.progression,
            action="hold", suggested_load_kg=last["mean_load"],
            suggested_reps=min(
                last["min_reps"] + 1, target_high or last["min_reps"] + 1,
            ),
            load_unit=unit,
            reason=f"Holding at {last['mean_load']:.1f}: {gate.reason}.",
            basis_sessions=len(history), recovery_override=gate.reason,
        )
    next_reps = (
        min(last["min_reps"] + 1, target_high)
        if target_high is not None else last["min_reps"] + 1
    )
    return ProgressionDecision(
        exercise_name=slot.exercise_name, rule=slot.progression,
        action="advance_reps", suggested_load_kg=last["mean_load"],
        suggested_reps=next_reps, load_unit=unit,
        reason=(
            f"Double progression: {last['min_reps']} reps at "
            f"{last['mean_load']:.1f}, so same load and "
            f"{next_reps} reps before adding weight."
        ),
        basis_sessions=len(history),
    )


# ─────────────────────────────────────────────────────────────────────────
# Draft generation (§29.2)
# ─────────────────────────────────────────────────────────────────────────
#
# The model's entire job is to produce a `ProgramDraftV1`. It is given the
# allowed exercise names, the athlete's constraints, deterministic
# performance data and accepted evidence, and its output goes through the
# same validator a hand-written draft would. It cannot write a template:
# nothing below this line touches `fitness_template`.

MAX_ALLOWED_EXERCISES = 80
#: Measured, not guessed. `scripts/fitness_draft_smoke.py` against the
#: deployed 27B on 2026-10-02: ONE week (3 sessions, 13 slots, 34 working
#: sets) took 196.7s and ~3,970 output tokens at ~20 tok/s decode. The
#: first value here was 180.0, copied from `reviews.REVIEW_TIMEOUT_SECONDS`
#: where it works — a review is a summary and a handful of
#: recommendations, while a draft writes out every set because the prompt
#: forbids "3x8". So every live draft timed out before producing anything.
#:
#: 540 leaves room for a denser week at the output cap below (~350s of
#: decode) and still sits under `settings.bg_llm_request_timeout` (600.0).
#: A `wait_for` tighter than the client's own budget means the client's
#: timeout can never apply, which is what 180 did.
DRAFT_TIMEOUT_SECONDS = 540.0


def allowed_exercises(
    db: Session, user_id: str, constraints: AthleteConstraints,
    *, limit: int = MAX_ALLOWED_EXERCISES,
) -> List[str]:
    """Exercise names this athlete can actually be prescribed.

    Filtered by equipment and by the limitation exclusions before the model
    sees them, which is the cheap half of §29.3: a name that was never
    offered cannot be prescribed, and the validator then only has to catch
    the model ignoring the list.
    """
    owner = _require_user(user_id)
    rows = db.execute(text("""
        SELECT id, name, equipment_required, injury_contraindications,
               movement_pattern
        FROM exercise_library
        WHERE (owner_user_id = :u OR owner_user_id IS NULL
               OR visibility = 'public')
          AND archived_at IS NULL
          AND name IS NOT NULL
        ORDER BY
            -- The athlete's own entries first: they are the ones with
            -- history to progress from.
            CASE WHEN owner_user_id = :u THEN 0 ELSE 1 END,
            name ASC
    """), {"u": owner}).fetchall()

    # Areas with an active limitation. An exercise contraindicated for one
    # is withheld, for the same reason unavailable equipment is: the live
    # run on 2026-10-02 offered an Overhead Press to an athlete with a
    # recorded shoulder limitation, the model dutifully used it, and
    # `validate_draft` then blocked the whole draft for using what it had
    # been handed. The offered list and the validator must not disagree —
    # the validator is the backstop for a name the model INVENTED, or for a
    # limitation recorded after the draft, not the first line of defence.
    limited_areas = {
        one["area"] for one in constraints.limitations if one.get("area")
    }

    out: List[str] = []
    for row in rows:
        if str(row.id) in constraints.excluded_exercise_ids:
            continue
        required = {
            str(item).strip().lower()
            for item in (_as_json(row.equipment_required) or [])
        }
        if required and constraints.equipment and (required - constraints.equipment):
            continue
        contraindications = {
            str(item).strip().lower()
            for item in (_as_json(row.injury_contraindications) or [])
        }
        if contraindications & limited_areas:
            continue
        out.append(str(row.name))
        if len(out) >= limit:
            break
    return out


def performance_summary(
    db: Session, user_id: str, names: Sequence[str], *, per_lift: int = 2,
) -> Dict[str, Any]:
    """Recent comparable performance per lift, computed.

    §29.2: deterministic performance data. The model is given numbers, not
    a workout log to interpret — a model asked to read its own inputs reads
    them wrong, and the error is invisible because the output is prose.
    """
    owner = _require_user(user_id)
    summary: Dict[str, Any] = {}
    for name in list(dict.fromkeys(names))[:30]:
        history = _comparable_sets(db, owner, name, limit=per_lift)
        if not history:
            continue
        summary[name] = [
            {
                "date": str(entry["date"]),
                "top_load": round(entry["top_load"], 2),
                "mean_load": round(entry["mean_load"], 2),
                "unit": entry["unit"].value,
                "min_reps": entry["min_reps"],
                "sets": entry["sets"],
                "mean_rpe": (
                    round(entry["mean_rpe"], 1)
                    if entry["mean_rpe"] is not None else None
                ),
            }
            for entry in history
        ]
    return summary


def constraints_payload(constraints: AthleteConstraints) -> Dict[str, Any]:
    """The constraints as the model sees them.

    No owner id, and no limitation description beyond what is needed to
    avoid an exercise: the model is told WHICH exercises to avoid, not what
    is wrong with the athlete. §29.3 — respect the limitation without
    diagnosing it, and a model that never receives the diagnosis cannot
    repeat one.
    """
    return {
        "equipment": sorted(constraints.equipment),
        "available_days": sorted(constraints.available_days),
        "preferred_session_minutes": constraints.preferred_minutes,
        "training_level": constraints.training_level,
        "training_experience_years": constraints.experience_years,
        "logged_sessions": constraints.logged_sessions,
        "is_experienced": constraints.is_experienced,
        "goals": constraints.goals,
        "limitations": [
            {
                "area": one["area"],
                # The athlete's own words, passed through unaltered. Not
                # interpreted here and not to be interpreted there.
                "note": one["description"][:200],
                "severity": one["severity"],
            }
            for one in constraints.limitations
        ],
        "weight_unit": constraints.weight_unit.value,
    }


async def generate_draft(
    db: Session,
    user_id: str,
    *,
    request: Optional[str] = None,
    kind: DraftBlockKind = DraftBlockKind.BLOCK,
    program_id: Optional[str] = None,
    phase_id: Optional[str] = None,
    evidence: Optional[Sequence[Any]] = None,
) -> StoredDraft:
    """Ask the local model for a draft, validate it, store it.

    One call plus at most one repair, like the review path: a model that
    cannot produce the schema twice will not produce it on the fifth
    attempt, and each attempt costs a wait and a GPU slot.

    No transaction is held across the model call.
    """
    from app.prompts import fitness_program_draft as prompt_module

    owner = _require_user(user_id)
    constraints = load_constraints(db, owner)
    names = allowed_exercises(db, owner, constraints)
    if not names:
        raise ProgrammingError(
            "No exercises are available for this athlete under the recorded "
            "equipment and exclusions, so there is nothing to draft from. "
            "That is a profile gap, not a programming decision."
        )

    existing_names: List[str] = []
    if phase_id:
        for row in db.execute(text("""
            SELECT exercises FROM fitness_template
            WHERE user_id = :u AND phase_id = :phase
        """), {"u": owner, "phase": phase_id}).fetchall():
            for spec in (_as_json(row.exercises) or []):
                if isinstance(spec, dict) and spec.get("name"):
                    existing_names.append(str(spec["name"]))

    # Scoped to the OFFERED list. The live run noticed the gap and said so
    # out loud — "Overhead Press (not in allowed list but noted in recent
    # performance)" — which is the same landmine as offering an exercise
    # it may not use, one wrapper over: history for a lift it cannot
    # prescribe is an invitation to prescribe it.
    offerable = set(names)
    performance = performance_summary(
        db, owner,
        [one for one in (existing_names or names[:20]) if one in offerable],
    )
    payload = constraints_payload(constraints)
    passages = [
        hit.model_dump(mode="json") if hasattr(hit, "model_dump") else dict(hit)
        for hit in (evidence or [])
    ]

    user_prompt = prompt_module.build_user_prompt(
        payload, names, performance=performance,
        evidence=passages or None, request=request,
    )

    # Reads are done; nothing is held while the model thinks.
    db.rollback()

    # A truncated draft propagates rather than being repaired: a repair
    # prompt is longer than the original, so retrying a draft that already
    # ran out of budget spends another three minutes to fail the same way.
    content, model_actual = await _chat(
        prompt_module.SYSTEM_PROMPT, user_prompt,
    )
    draft, errors = _parse_draft(content, kind)
    if draft is None:
        repaired, repair_model = await _chat(
            prompt_module.SYSTEM_PROMPT,
            user_prompt + "\n\n" + prompt_module.build_repair_prompt(errors),
        )
        draft, repair_errors = _parse_draft(repaired, kind)
        model_actual = repair_model or model_actual
        if draft is None:
            raise ProgrammingError(
                "The model did not produce a usable draft: "
                + "; ".join((errors + repair_errors)[:4])
            )

    # §29.3, and the review path's rule applied verbatim: a draft whose
    # prose names a condition is NOT stored. "A sentence containing a
    # diagnosis cannot be repaired by deleting a word — the whole reasoning
    # behind it assumed the diagnosis, and shipping the rest would leave
    # advice built on a clinical claim with the claim edited out."
    #
    # The 2026-10-02 live run is why this exists. With the contraindicated
    # exercises withheld, the model had to explain WHY it was avoiding
    # something and invented one: the athlete's note says "left shoulder
    # complains on heavy flat pressing" and the draft said "to avoid
    # aggravating shoulder impingement". Storing it would have put an
    # invented diagnosis in the database and on a screen, with a warning
    # beside it — and a warning beside a diagnosis is still a diagnosis.
    #
    # One repair turn, like the photo-analysis path, then refused.
    leaks = [
        one for one in prose_findings(draft) if one.severity == "reject"
    ]
    if leaks:
        logger.info(
            "[programming] draft leaked clinical language, repairing: %s",
            "; ".join(one.message for one in leaks[:2]),
        )
        repaired_content, repair_model = await _chat(
            prompt_module.SYSTEM_PROMPT,
            user_prompt + "\n\n" + prompt_module.build_repair_prompt(
                [one.message for one in leaks]
            ),
        )
        model_actual = repair_model or model_actual
        candidate, _ = _parse_draft(repaired_content, kind)
        still_leaking = (
            [one for one in prose_findings(candidate) if one.severity == "reject"]
            if candidate is not None else leaks
        )
        if candidate is None or still_leaking:
            raise ProgrammingError(
                "The draft named a clinical condition and said so again "
                "after being told not to, so nothing was stored: "
                + "; ".join(
                    one.message for one in (still_leaking or leaks)[:2]
                )
            )
        draft = candidate

    return store_draft(
        db, owner, draft, program_id=program_id, phase_id=phase_id,
        model_actual=model_actual,
        prompt_version=prompt_module.PROMPT_VERSION,
        science_citations=[
            {"chunk_id": one.get("chunk_id"), "record_id": one.get("record_id")}
            for one in passages
            if one.get("chunk_id") in set(draft.evidence_refs)
        ],
        constraints=constraints,
    )


async def _chat(
    system: str,
    user: str,
    *,
    timeout: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Tuple[str, Optional[str]]:
    """One bounded call to the local background model.

    `enable_thinking: False` nested in `chat_template_kwargs` — without it
    Qwen returns an empty `content` for structured output (§9). `max_tokens`
    is always set: `llama-server` keeps generating after a non-streaming
    client disconnects.

    `timeout` and `max_tokens` are overridable so the smoke script can
    MEASURE what a draft actually costs rather than guessing at the
    constants. The defaults are what production uses.
    """
    import asyncio

    from app.core.llm import get_background_llm_client
    from app.prompts import fitness_program_draft as prompt_module

    client = get_background_llm_client()
    response = await asyncio.wait_for(
        client.chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens or prompt_module.MAX_OUTPUT_TOKENS,
            temperature=prompt_module.TEMPERATURE,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        ),
        timeout=timeout or DRAFT_TIMEOUT_SECONDS,
    )
    choices = (response or {}).get("choices") or [{}]
    message = choices[0].get("message") or {}
    answer = (message.get("content") or "").strip()

    # A draft cut off at the cap is not malformed JSON, and reporting it as
    # "the output was not JSON" sends the next reader to the prompt instead
    # of to the budget. A four-week block is roughly four times the measured
    # one-week output — about 16,000 tokens — so this is the failure a large
    # ask produces, and it has to name itself.
    if choices[0].get("finish_reason") == "length":
        raise TruncatedDraft(
            f"the model hit the {max_tokens or prompt_module.MAX_OUTPUT_TOKENS}"
            f"-token output cap with {len(answer)} characters written. Every "
            f"set is enumerated, so a multi-week block does not fit in one "
            f"call: ask for fewer weeks, or raise MAX_OUTPUT_TOKENS and "
            f"DRAFT_TIMEOUT_SECONDS together."
        )

    return answer, (response or {}).get("model")


def _parse_draft(
    content: str, kind: DraftBlockKind,
) -> Tuple[Optional[ProgramDraftV1], List[str]]:
    """Strict parse. An unknown field is a rejection, not a warning."""
    if not content:
        return None, ["the model returned nothing"]
    body = _extract_json(content)
    if body is None:
        return None, ["the output was not JSON"]
    body.setdefault("kind", kind.value)
    try:
        return ProgramDraftV1.model_validate(body), []
    except Exception as exc:
        return None, [_short_error(exc)]


def _extract_json(content: str) -> Optional[Dict[str, Any]]:
    text_body = content.strip()
    if text_body.startswith("```"):
        text_body = text_body.split("```")[1]
        if text_body.lstrip().lower().startswith("json"):
            text_body = text_body.lstrip()[4:]
    start = text_body.find("{")
    end = text_body.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text_body[start:end + 1])
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _short_error(exc: Exception) -> str:
    """A validation error the repair turn can act on.

    The full pydantic error is hundreds of lines for a draft this size, and
    a repair prompt that is mostly error text crowds out the draft it is
    supposed to fix.
    """
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return str(exc)[:300]
    parts: List[str] = []
    for one in errors()[:6]:
        location = ".".join(str(piece) for piece in one.get("loc", ()))
        parts.append(f"{location}: {one.get('msg')}")
    return "; ".join(parts)[:600] or str(exc)[:300]
