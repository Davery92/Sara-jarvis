"""Athlete profile, dated goals and limitations.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 6. One service truth for the athlete's
own stable facts, their goal history and their reported constraints.

Transaction rule (Step 3): nothing here commits except the mutation
functions, each of which owns exactly one unit of work and returns only
after its commit. No network or model call happens inside a transaction —
there are none in this module at all, which is why Settings works with every
LLM endpoint down.
"""
from __future__ import annotations

import logging
import uuid
import zlib
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.fitness_coach import (
    AthleteGoalIn,
    AthleteGoalOut,
    AthleteLimitationIn,
    AthleteLimitationOut,
    AthleteProfileOut,
    AthleteProfilePatch,
    CalculationSex,
    CoachingStyle,
    LimitationStatus,
    Metric,
    RateBasis,
    TrainingLevel,
    Unavailable,
    Unit,
    present_fields,
)
from app.services.fitness.events import queue_invalidation, record_fitness_event
from app.services.fitness.data_access import (
    FitnessDataError,
    _require_user,
    athlete_zone,
)

logger = logging.getLogger(__name__)


class ConcurrencyConflict(Exception):
    """`expected_version` did not match. The caller must re-read and retry.

    A separate exception type rather than a bare 409: the route turns it into
    a 409 *with the current version*, so a client can reconcile instead of
    guessing.
    """

    def __init__(self, current_version: int, message: str = "profile was modified"):
        super().__init__(message)
        self.current_version = current_version


class GoalOverlap(Exception):
    """Two primary goals would be in force on the same day."""


# Fields whose change a historical review could have depended on. Everything
# else is edited silently — the audit is deliberately sparse (§5.1), since a
# review already snapshots the constraints it reasoned under.
_AUDITED_FIELDS = frozenset({
    "height_cm", "date_of_birth", "calculation_sex", "timezone",
    "training_level", "training_experience_years", "available_days",
    "equipment", "excluded_exercise_ids", "preferred_duration_minutes",
    "monitoring_consent",
})

_PROFILE_COLUMNS = (
    "height_cm", "date_of_birth", "calculation_sex", "training_experience_years",
    "training_level", "timezone", "weight_unit", "length_unit", "available_days",
    "preferred_duration_minutes", "equipment", "preferred_exercise_ids",
    "excluded_exercise_ids", "dietary_restrictions", "dietary_preferences",
    "supplements", "coaching_style", "monitoring_consent",
)

_JSON_COLUMNS = frozenset({
    "available_days", "equipment", "preferred_exercise_ids",
    "excluded_exercise_ids", "dietary_restrictions", "dietary_preferences",
    "supplements",
})


def _advisory_key(user_id: str, namespace: int) -> int:
    """A stable 63-bit advisory-lock key for one athlete and one concern.

    Advisory locks rather than row locks because the invariant being
    protected ("no two overlapping primary goals") is about rows that may not
    exist yet, so there is nothing to `SELECT ... FOR UPDATE`.
    """
    digest = zlib.crc32(f"{namespace}:{user_id}".encode("utf-8"))
    return (namespace << 32) | digest


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# Profile
# ─────────────────────────────────────────────────────────────────────────

def get_athlete_profile(
    db: Session, user_id: str, *, include_weight: bool = True
) -> AthleteProfileOut:
    """The athlete's profile, creating nothing.

    An athlete who has never opened Settings has no row, and that is a valid
    state — this returns an all-unknown profile rather than inserting
    defaults, because an inserted row would make "never configured" and
    "configured to the defaults" indistinguishable.

    `current_weight` is resolved from `health_metric`, never stored. It comes
    back as a `Metric`, so "I have no weight observations" is expressible.
    """
    uid = _require_user(user_id)
    row = db.execute(text(f"""
        SELECT user_id, {', '.join(_PROFILE_COLUMNS)}, row_version,
               created_at, updated_at
        FROM fitness_athlete_profile WHERE user_id = :uid
    """), {"uid": uid}).fetchone()

    if row is None:
        profile = AthleteProfileOut(user_id=uid)
    else:
        m = dict(row._mapping)
        profile = AthleteProfileOut(
            user_id=uid,
            height_cm=float(m["height_cm"]) if m["height_cm"] is not None else None,
            date_of_birth=m["date_of_birth"],
            calculation_sex=CalculationSex(m["calculation_sex"]),
            training_experience_years=(
                float(m["training_experience_years"])
                if m["training_experience_years"] is not None else None
            ),
            training_level=TrainingLevel(m["training_level"]),
            timezone=m["timezone"],
            weight_unit=Unit(m["weight_unit"]),
            length_unit=Unit(m["length_unit"]),
            available_days=m["available_days"] or [],
            preferred_duration_minutes=m["preferred_duration_minutes"],
            equipment=m["equipment"] or [],
            preferred_exercise_ids=m["preferred_exercise_ids"] or [],
            excluded_exercise_ids=m["excluded_exercise_ids"] or [],
            dietary_restrictions=m["dietary_restrictions"] or [],
            dietary_preferences=m["dietary_preferences"] or [],
            supplements=m["supplements"] or [],
            coaching_style=CoachingStyle(m["coaching_style"]),
            monitoring_consent=bool(m["monitoring_consent"]),
            row_version=int(m["row_version"]),
            created_at=m["created_at"],
            updated_at=m["updated_at"],
        )

    if include_weight:
        profile = profile.model_copy(
            update={"current_weight": _latest_weight(db, uid, profile.timezone)}
        )
    return profile


def _latest_weight(db: Session, user_id: str, timezone_name: str) -> Metric:
    """The most recent non-superseded bodyweight observation, with its time.

    Deliberately not a "current weight" field on the profile: a backdated
    correction has to change this answer, and a stored copy would not.
    """
    present = {
        r[0] for r in db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'health_metric'
        """)).fetchall()
    }
    unit_col = "unit" if "unit" in present else "NULL AS unit"
    superseded = "AND superseded_by_id IS NULL" if "superseded_by_id" in present else ""
    row = db.execute(text(f"""
        SELECT value, recorded_at, source, {unit_col}
        FROM health_metric
        WHERE user_id = :uid AND metric_type = ANY(:types) {superseded}
        ORDER BY recorded_at DESC
        LIMIT 1
    """), {"uid": user_id, "types": ["weight", "body_weight"]}).fetchone()

    if row is None:
        return Metric(
            key="profile.current_weight",
            unavailable_reason=Unavailable.NO_DATA,
            note="no bodyweight observation recorded",
        )

    from app.services.fitness.data_access import resolve_metric_unit
    unit = resolve_metric_unit("weight", row.unit)
    if unit is Unit.UNKNOWN:
        return Metric(
            key="profile.current_weight",
            unavailable_reason=Unavailable.UNKNOWN_UNIT,
            observed_at=row.recorded_at,
            source_count=1,
            note=(
                "the most recent weight observation has no recorded unit; "
                "it is not inferable from the value"
            ),
        )
    return Metric(
        key="profile.current_weight",
        value=float(row.value),
        unit=unit,
        observed_at=row.recorded_at,
        source_count=1,
        note=f"source: {row.source}",
    )


def patch_athlete_profile(
    db: Session, user_id: str, patch: AthleteProfilePatch
) -> AthleteProfileOut:
    """Apply only the fields the request mentioned.

    `UNSET` vs explicit `null` is load-bearing: without the distinction, a
    PATCH that sends `{"height_cm": 181}` would either wipe every other field
    or make clearing one impossible. `present_fields` returns exactly what
    was mentioned, with `None` meaning "clear this".

    Upserts rather than requiring a prior GET, so the first edit works; the
    `expected_version` check is skipped only when no row exists yet, because
    there is nothing to conflict with.
    """
    uid = _require_user(user_id)
    fields = present_fields(patch)
    if not fields:
        return get_athlete_profile(db, uid)

    unknown = set(fields) - set(_PROFILE_COLUMNS)
    if unknown:
        # Defence in depth: the DTO already forbids extras, and the column
        # names here are a fixed tuple, never request-supplied.
        raise FitnessDataError(f"not profile columns: {sorted(unknown)}")

    current = db.execute(text("""
        SELECT row_version FROM fitness_athlete_profile
        WHERE user_id = :uid FOR UPDATE
    """), {"uid": uid}).fetchone()

    if current is None:
        new_version = 1
        cols = ["id", "user_id", "row_version"]
        params: Dict[str, Any] = {
            "id": str(uuid.uuid4()), "user_id": uid, "row_version": new_version,
        }
        for name, value in fields.items():
            cols.append(name)
            params[name] = _bind_value(name, value)
        placeholders = ", ".join(
            f"CAST(:{c} AS jsonb)" if c in _JSON_COLUMNS else f":{c}" for c in cols
        )
        db.execute(text(f"""
            INSERT INTO fitness_athlete_profile ({', '.join(cols)})
            VALUES ({placeholders})
        """), params)
    else:
        if patch.expected_version is not None and \
                int(patch.expected_version) != int(current.row_version):
            raise ConcurrencyConflict(int(current.row_version))

        before = db.execute(text(f"""
            SELECT {', '.join(sorted(_AUDITED_FIELDS & set(fields)))}
            FROM fitness_athlete_profile WHERE user_id = :uid
        """), {"uid": uid}).fetchone() if (_AUDITED_FIELDS & set(fields)) else None

        new_version = int(current.row_version) + 1
        assignments, params = [], {"uid": uid, "row_version": new_version}
        for name, value in fields.items():
            assignments.append(
                f"{name} = CAST(:{name} AS jsonb)" if name in _JSON_COLUMNS
                else f"{name} = :{name}"
            )
            params[name] = _bind_value(name, value)
        db.execute(text(f"""
            UPDATE fitness_athlete_profile
            SET {', '.join(assignments)}, row_version = :row_version, updated_at = NOW()
            WHERE user_id = :uid
        """), params)

        if before is not None:
            _record_changes(db, uid, dict(before._mapping), fields,
                            int(current.row_version), new_version)

    # No event: a profile edit is not news. But it CAN change the timezone
    # the athlete's days are cut on, which moves every logical date — so the
    # cached state has to go.
    queue_invalidation(db, uid)
    db.commit()
    return get_athlete_profile(db, uid)


def _bind_value(name: str, value: Any) -> Any:
    if value is None:
        return None
    if name in _JSON_COLUMNS:
        import json
        return json.dumps(value)
    if name in ("calculation_sex", "training_level", "coaching_style",
                "weight_unit", "length_unit"):
        return getattr(value, "value", value)
    if name == "monitoring_consent":
        return bool(value)
    return value


def _record_changes(
    db: Session, user_id: str, before: Dict[str, Any],
    fields: Dict[str, Any], from_version: int, to_version: int,
) -> None:
    import json
    for name, new_value in fields.items():
        if name not in _AUDITED_FIELDS:
            continue
        old_value = before.get(name)
        if old_value == new_value:
            continue
        db.execute(text("""
            INSERT INTO fitness_athlete_profile_change
                (id, user_id, field, old_value, new_value, from_version, to_version)
            VALUES (:id, :uid, :f, CAST(:ov AS jsonb), CAST(:nv AS jsonb), :fv, :tv)
        """), {
            "id": str(uuid.uuid4()), "uid": user_id, "f": name,
            "ov": json.dumps(old_value, default=str),
            "nv": json.dumps(new_value, default=str),
            "fv": from_version, "tv": to_version,
        })


def profile_timezone(db: Session, user_id: str) -> str:
    """Just the timezone, for callers that need the athlete-local date.

    Separate from `get_athlete_profile` because resolving a date should not
    cost a weight lookup, and because every analytics window needs this.
    """
    uid = _require_user(user_id)
    row = db.execute(text(
        "SELECT timezone FROM fitness_athlete_profile WHERE user_id = :uid"
    ), {"uid": uid}).fetchone()
    return (row.timezone if row else None) or "America/New_York"


def athlete_today(db: Session, user_id: str) -> date:
    """The athlete's own calendar date, not the server's.

    Every `on_date` default in this subsystem comes through here. The
    existing `phase_resolution`/`training_day` resolvers default to ET via
    `app.core.timezone`, which is correct for Sara's owner and wrong for a
    travelling or non-ET athlete — so callers pass an explicit date rather
    than letting those defaults choose.
    """
    tz = athlete_zone(profile_timezone(db, user_id))
    return datetime.now(tz).date()


# ─────────────────────────────────────────────────────────────────────────
# Goals
# ─────────────────────────────────────────────────────────────────────────

_GOAL_COLUMNS = """
    id, user_id, kind, is_primary, priority, rationale, target_weight_kg,
    rate_basis, target_rate_kg_week, target_rate_percent_week,
    strength_targets, valid_from, valid_until, recorded_at, supersedes_id,
    source, approved_at
"""


def _goal_out(row: Any) -> AthleteGoalOut:
    m = dict(row._mapping)
    return AthleteGoalOut(
        id=m["id"],
        user_id=m["user_id"],
        kind=m["kind"],
        is_primary=bool(m["is_primary"]),
        priority=int(m["priority"]),
        rationale=m["rationale"],
        target_weight_kg=(
            float(m["target_weight_kg"]) if m["target_weight_kg"] is not None else None
        ),
        rate_basis=RateBasis(m["rate_basis"]),
        target_rate_kg_week=(
            float(m["target_rate_kg_week"])
            if m["target_rate_kg_week"] is not None else None
        ),
        target_rate_percent_week=(
            float(m["target_rate_percent_week"])
            if m["target_rate_percent_week"] is not None else None
        ),
        strength_targets=m["strength_targets"] or {},
        valid_from=m["valid_from"],
        valid_until=m["valid_until"],
        recorded_at=m["recorded_at"],
        supersedes_id=m["supersedes_id"],
        source=m["source"],
        approved_at=m["approved_at"],
    )


def get_goals(
    db: Session,
    user_id: str,
    on_date: Optional[date] = None,
    *,
    include_history: bool = False,
) -> List[AthleteGoalOut]:
    """Goals in force on `on_date`, or the whole history.

    As-of resolution is half-open: `valid_from <= d < valid_until`. The
    primary goal comes first, then secondary priorities in order — callers
    that want "the goal" take `[0]` and get a deterministic answer.
    """
    uid = _require_user(user_id)
    if include_history:
        rows = db.execute(text(f"""
            SELECT {_GOAL_COLUMNS} FROM fitness_athlete_goal
            WHERE user_id = :uid
            ORDER BY valid_from DESC, is_primary DESC, priority ASC
        """), {"uid": uid}).fetchall()
    else:
        d = on_date or athlete_today(db, uid)
        rows = db.execute(text(f"""
            SELECT {_GOAL_COLUMNS} FROM fitness_athlete_goal
            WHERE user_id = :uid
              AND valid_from <= :d
              AND (valid_until IS NULL OR valid_until > :d)
            ORDER BY is_primary DESC, priority ASC, valid_from DESC
        """), {"uid": uid, "d": d}).fetchall()
    return [_goal_out(r) for r in rows]


def get_primary_goal(
    db: Session, user_id: str, on_date: Optional[date] = None
) -> Optional[AthleteGoalOut]:
    for goal in get_goals(db, user_id, on_date):
        if goal.is_primary:
            return goal
    return None


def create_goal(db: Session, user_id: str, payload: AthleteGoalIn) -> AthleteGoalOut:
    """Record a goal, closing any primary goal it supersedes.

    The advisory lock serialises two devices creating a goal at once. The
    exclusion constraint in migration 160 is the backstop, but the lock is
    what lets this *close* the previous interval rather than just failing:
    "I'm cutting now" should end the bulk, not be rejected because the bulk
    has no end date.

    A non-primary goal takes neither path — several may coexist.
    """
    uid = _require_user(user_id)
    gid = str(uuid.uuid4())
    supersedes: Optional[str] = None

    if payload.is_primary:
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"),
                   {"k": _advisory_key(uid, 1)})

        # Anything still open that this goal starts inside gets closed at the
        # new goal's start. A goal that would overlap a *closed* interval is
        # a genuine conflict — that is history being contradicted, not
        # superseded.
        open_overlap = db.execute(text("""
            SELECT id, valid_from, valid_until FROM fitness_athlete_goal
            WHERE user_id = :uid AND is_primary
              AND valid_until IS NULL
              AND valid_from <= :vf
            ORDER BY valid_from DESC
            LIMIT 1
        """), {"uid": uid, "vf": payload.valid_from}).fetchone()

        closed_conflict = db.execute(text("""
            SELECT id FROM fitness_athlete_goal
            WHERE user_id = :uid AND is_primary
              AND valid_until IS NOT NULL
              AND valid_from < COALESCE(:vu, 'infinity'::date)
              AND valid_until > :vf
            LIMIT 1
        """), {"uid": uid, "vf": payload.valid_from, "vu": payload.valid_until}).fetchone()
        if closed_conflict:
            raise GoalOverlap(
                f"a primary goal already covers {payload.valid_from}; close or "
                "correct it rather than adding a second one"
            )

        if open_overlap:
            if open_overlap.valid_from == payload.valid_from:
                raise GoalOverlap(
                    "a primary goal already starts on that date; edit it instead "
                    "of creating a zero-length interval"
                )
            db.execute(text("""
                UPDATE fitness_athlete_goal SET valid_until = :vf WHERE id = :id
            """), {"vf": payload.valid_from, "id": open_overlap.id})
            supersedes = open_overlap.id

    db.execute(text("""
        INSERT INTO fitness_athlete_goal
            (id, user_id, kind, is_primary, priority, rationale, target_weight_kg,
             rate_basis, target_rate_kg_week, target_rate_percent_week,
             strength_targets, valid_from, valid_until, recorded_at,
             supersedes_id, source, approved_at)
        VALUES
            (:id, :uid, :kind, :primary, :priority, :rationale, :tw,
             :rb, :kg, :pct, CAST(:st AS jsonb), :vf, :vu, NOW(),
             :sup, :src, NOW())
    """), {
        "id": gid, "uid": uid, "kind": payload.kind.value,
        "primary": payload.is_primary, "priority": payload.priority,
        "rationale": payload.rationale, "tw": payload.target_weight_kg,
        "rb": payload.rate_basis.value,
        "kg": payload.target_rate_kg_week,
        "pct": payload.target_rate_percent_week,
        "st": __import__("json").dumps(payload.strength_targets),
        "vf": payload.valid_from, "vu": payload.valid_until,
        "sup": supersedes, "src": payload.source,
    })
    # A goal change carries real attention: every adherence number after it
    # is measured against something different, and a silent change makes
    # those numbers mean something new with nothing saying so. The rate
    # itself is a prescription, not a body measurement, so it may travel.
    record_fitness_event(
        db, uid, "fitness.goal_changed",
        dedupe_key=f"fitness.goal:{gid}",
        source_ref=gid, aggregate_type="fitness_athlete_goal", aggregate_id=gid,
        payload={
            "action": "created", "kind": payload.kind.value,
            "is_primary": payload.is_primary,
            "rate_basis": payload.rate_basis.value,
            "supersedes_id": supersedes,
            "valid_from": payload.valid_from.isoformat(),
        },
        logical_date=payload.valid_from,
    )
    db.commit()

    row = db.execute(text(f"SELECT {_GOAL_COLUMNS} FROM fitness_athlete_goal WHERE id = :id"),
                     {"id": gid}).fetchone()
    return _goal_out(row)


def close_goal(
    db: Session, user_id: str, goal_id: str, valid_until: date
) -> AthleteGoalOut:
    """End a goal's interval. Never deletes it.

    "What was I training for in March" has to stay answerable, including for
    a review from March whose rationale cites it.
    """
    uid = _require_user(user_id)
    row = db.execute(text("""
        SELECT valid_from, valid_until FROM fitness_athlete_goal
        WHERE id = :id AND user_id = :uid FOR UPDATE
    """), {"id": goal_id, "uid": uid}).fetchone()
    if row is None:
        raise LookupError("goal not found")
    if valid_until <= row.valid_from:
        raise FitnessDataError("valid_until must be after the goal's start")

    db.execute(text("""
        UPDATE fitness_athlete_goal SET valid_until = :vu WHERE id = :id AND user_id = :uid
    """), {"vu": valid_until, "id": goal_id, "uid": uid})
    record_fitness_event(
        db, uid, "fitness.goal_changed",
        dedupe_key=f"fitness.goal:{goal_id}:closed:{valid_until.isoformat()}",
        source_ref=goal_id, aggregate_type="fitness_athlete_goal",
        aggregate_id=goal_id,
        payload={"action": "closed", "valid_until": valid_until.isoformat()},
        logical_date=valid_until,
    )
    db.commit()
    return _goal_out(db.execute(text(
        f"SELECT {_GOAL_COLUMNS} FROM fitness_athlete_goal WHERE id = :id"
    ), {"id": goal_id}).fetchone())


# ─────────────────────────────────────────────────────────────────────────
# Limitations
# ─────────────────────────────────────────────────────────────────────────

_LIMITATION_COLUMNS = """
    id, user_id, area, description, excluded_exercise_ids, modified_exercise_ids,
    severity_flag, effective_from, effective_until, status, notes, created_at
"""


def _limitation_out(row: Any) -> AthleteLimitationOut:
    m = dict(row._mapping)
    return AthleteLimitationOut(
        id=m["id"], user_id=m["user_id"], area=m["area"],
        description=m["description"],
        excluded_exercise_ids=m["excluded_exercise_ids"] or [],
        modified_exercise_ids=m["modified_exercise_ids"] or [],
        severity_flag=m["severity_flag"],
        effective_from=m["effective_from"],
        effective_until=m["effective_until"],
        status=LimitationStatus(m["status"]),
        notes=m["notes"], created_at=m["created_at"],
    )


def get_limitations(
    db: Session,
    user_id: str,
    on_date: Optional[date] = None,
    *,
    include_history: bool = False,
) -> List[AthleteLimitationOut]:
    """Limitations in force on `on_date`, or all of them.

    As-of rather than status-only, because a review from six weeks ago
    reasoned under the constraints that were active *then*. Reading only
    `status = 'active'` would make its recommendations look arbitrary.
    """
    uid = _require_user(user_id)
    if include_history:
        rows = db.execute(text(f"""
            SELECT {_LIMITATION_COLUMNS} FROM fitness_athlete_limitation
            WHERE user_id = :uid ORDER BY effective_from DESC
        """), {"uid": uid}).fetchall()
    else:
        d = on_date or athlete_today(db, uid)
        rows = db.execute(text(f"""
            SELECT {_LIMITATION_COLUMNS} FROM fitness_athlete_limitation
            WHERE user_id = :uid
              AND status <> 'superseded'
              AND effective_from <= :d
              AND (effective_until IS NULL OR effective_until > :d)
            ORDER BY effective_from DESC
        """), {"uid": uid, "d": d}).fetchall()
    return [_limitation_out(r) for r in rows]


def create_limitation(
    db: Session, user_id: str, payload: AthleteLimitationIn
) -> AthleteLimitationOut:
    uid = _require_user(user_id)
    lid = str(uuid.uuid4())
    import json
    db.execute(text("""
        INSERT INTO fitness_athlete_limitation
            (id, user_id, area, description, excluded_exercise_ids,
             modified_exercise_ids, severity_flag, effective_from,
             effective_until, status, notes)
        VALUES (:id, :uid, :area, :descr, CAST(:ex AS jsonb), CAST(:mod AS jsonb),
                :sev, :ef, :eu, 'active', :notes)
    """), {
        "id": lid, "uid": uid, "area": payload.area,
        "descr": payload.description,
        "ex": json.dumps(payload.excluded_exercise_ids),
        "mod": json.dumps(payload.modified_exercise_ids),
        "sev": payload.severity_flag,
        "ef": payload.effective_from, "eu": payload.effective_until,
        "notes": payload.notes,
    })
    # The area, not the description. "left shoulder" is what a consumer needs
    # to route around; the athlete's own words about it stay in the owned row.
    record_fitness_event(
        db, uid, "fitness.limitation_changed",
        dedupe_key=f"fitness.limitation:{lid}",
        source_ref=lid, aggregate_type="fitness_athlete_limitation",
        aggregate_id=lid,
        payload={
            "action": "created", "area": payload.area,
            "severity_flag": payload.severity_flag,
            "excluded_count": len(payload.excluded_exercise_ids),
            "modified_count": len(payload.modified_exercise_ids),
        },
        logical_date=payload.effective_from,
    )
    db.commit()
    return _limitation_out(db.execute(text(
        f"SELECT {_LIMITATION_COLUMNS} FROM fitness_athlete_limitation WHERE id = :id"
    ), {"id": lid}).fetchone())


def resolve_limitation(
    db: Session, user_id: str, limitation_id: str,
    *, effective_until: Optional[date] = None,
) -> AthleteLimitationOut:
    """Mark a limitation resolved. Retained, not deleted."""
    uid = _require_user(user_id)
    row = db.execute(text("""
        SELECT effective_from FROM fitness_athlete_limitation
        WHERE id = :id AND user_id = :uid FOR UPDATE
    """), {"id": limitation_id, "uid": uid}).fetchone()
    if row is None:
        raise LookupError("limitation not found")
    end = effective_until or athlete_today(db, uid)
    if end <= row.effective_from:
        end = row.effective_from  # keep the interval non-negative
        db.execute(text("""
            UPDATE fitness_athlete_limitation
            SET status = 'resolved', effective_until = NULL, updated_at = NOW()
            WHERE id = :id AND user_id = :uid
        """), {"id": limitation_id, "uid": uid})
    else:
        db.execute(text("""
            UPDATE fitness_athlete_limitation
            SET status = 'resolved', effective_until = :eu, updated_at = NOW()
            WHERE id = :id AND user_id = :uid
        """), {"eu": end, "id": limitation_id, "uid": uid})
    record_fitness_event(
        db, uid, "fitness.limitation_changed",
        dedupe_key=f"fitness.limitation:{limitation_id}:resolved",
        source_ref=limitation_id,
        aggregate_type="fitness_athlete_limitation", aggregate_id=limitation_id,
        payload={"action": "resolved"},
        logical_date=end,
    )
    db.commit()
    return _limitation_out(db.execute(text(
        f"SELECT {_LIMITATION_COLUMNS} FROM fitness_athlete_limitation WHERE id = :id"
    ), {"id": limitation_id}).fetchone())


def active_exclusions(
    db: Session, user_id: str, on_date: Optional[date] = None
) -> List[str]:
    """Canonical exercise ids the athlete should not be prescribed.

    The union of the profile's standing exclusions and every limitation in
    force on the date. Program generation reads this; it is the one place
    that knows both sources exist.
    """
    uid = _require_user(user_id)
    out: set[str] = set()
    profile = db.execute(text("""
        SELECT excluded_exercise_ids FROM fitness_athlete_profile WHERE user_id = :uid
    """), {"uid": uid}).fetchone()
    if profile and profile.excluded_exercise_ids:
        out.update(str(x) for x in profile.excluded_exercise_ids)
    for lim in get_limitations(db, uid, on_date):
        out.update(lim.excluded_exercise_ids)
    return sorted(out)
