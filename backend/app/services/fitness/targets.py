"""The one target resolver, and the one target writer.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 6 / §4.3. Every consumer — the
dashboard, voice, the world brief, the weekly health collector, the coach
review, the chat tools — resolves nutrition targets through
`resolve_targets()`. Before this there were three answers available
(`fitness_phase` macros, `fitness_goals` macros, and whatever
`fitness_context.py` happened to read), and they could disagree.

Resolution order, in full:

1. The effective phase for the athlete-local date, via the existing
   `phase_resolution.get_effective_phase()` — that function stays
   authoritative for *which* phase applies. It is called with an explicit
   `on_date`, never allowed to default, because its default is process-ET.
2. The approved `fitness_target_revision` covering that date for that phase.
3. Failing that, the phase row's own legacy macro columns, labelled
   `provenance=legacy_phase`.
4. With no effective phase: the approved default-scope revision, then
   `fitness_goals`, labelled `legacy_default`.
5. Nothing at all → `provenance=unknown` with null values. Not zero, and not
   today's values retroactively applied.

`history_unknown` is set when the requested date precedes the earliest
revision for the resolved scope. That matters because `fitness_goals`
defaults to 2000/150/200/70: a row on those defaults is not evidence anybody
chose them, so asserting them as February's target would invent adherence
data.

The **half-open conversion** happens here and only here.
`fitness_phase.end_date` is inclusive; revisions are `[valid_from,
valid_until)`. Everything downstream sees half-open.

The writer (`create_target_revision`) appends a revision *and* updates the
legacy projection in one transaction, so a reader that has not been migrated
yet never sees a value the revision history disagrees with.
"""
from __future__ import annotations

import logging
import uuid
import zlib
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.fitness_coach import (
    DayType,
    ResolvedTargets,
    TargetProvenance,
    TargetRevisionIn,
    TargetRevisionOut,
    TargetScope,
    TargetValues,
)
from app.services.fitness.events import record_fitness_event
from app.services.fitness.data_access import FitnessDataError, _require_user

logger = logging.getLogger(__name__)

_ADVISORY_NAMESPACE = 2


class TargetConflict(Exception):
    """An overlapping approved revision, or a stale `expected_revision`."""

    def __init__(self, message: str, current_revision_id: Optional[str] = None):
        super().__init__(message)
        self.current_revision_id = current_revision_id


def _advisory_key(user_id: str) -> int:
    return (_ADVISORY_NAMESPACE << 32) | zlib.crc32(user_id.encode("utf-8"))


_REVISION_COLUMNS = """
    id, user_id, scope, phase_id, version, valid_from, valid_until,
    calories, protein_g, carbs_g, fat_g,
    rest_calories, rest_protein_g, rest_carbs_g, rest_fat_g, rest_steps,
    sleep_hours, water_ml, steps,
    calorie_tolerance_pct, protein_tolerance_pct,
    source, review_recommendation_id, approved_at, approved_by, created_at
"""


# ─────────────────────────────────────────────────────────────────────────
# Day type
# ─────────────────────────────────────────────────────────────────────────

def resolve_day_type(db: Session, user_id: str, on_date: date) -> DayType:
    """Training or rest, from the existing resolver.

    Delegates to `training_day.is_training_day()`, which already unified the
    schedule-vs-session question (see the fitness-schedule gotcha). A failure
    returns UNKNOWN rather than guessing rest: a rest-day calorie target
    applied to a training day is a real misstatement.
    """
    try:
        from app.services.training_day import is_training_day
        verdict = is_training_day(db, user_id, on_date)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("day-type resolution failed for %s: %s", on_date, exc)
        return DayType.UNKNOWN
    if verdict is None:
        return DayType.UNKNOWN
    return DayType.TRAINING if verdict.get("is_training_day") else DayType.REST


# ─────────────────────────────────────────────────────────────────────────
# Resolution
# ─────────────────────────────────────────────────────────────────────────

def resolve_targets(
    db: Session,
    user_id: str,
    on_date: date,
    day_type: Optional[DayType] = None,
) -> ResolvedTargets:
    """What the athlete's targets were (or are) on `on_date`.

    `on_date` is required and athlete-local. There is no default: the
    existing phase/training-day resolvers default to process ET, and letting
    that choose would silently answer for the wrong calendar day for a
    travelling or non-ET athlete.
    """
    uid = _require_user(user_id)
    resolved_day_type = day_type or resolve_day_type(db, uid, on_date)

    phase = _effective_phase(db, uid, on_date)

    if phase:
        revision = _approved_revision(
            db, uid, TargetScope.PHASE, on_date, phase_id=phase["id"]
        )
        if revision:
            return _from_revision(
                uid, on_date, resolved_day_type, revision,
                phase_name=phase.get("name"),
                history_unknown=_precedes_history(
                    db, uid, TargetScope.PHASE, on_date, phase["id"]
                ),
            )

        # No revision covers this date. Falling back to the phase's own
        # columns is only honest when the phase has NO revision history at
        # all — because those columns are mutable and are kept in step with
        # the *current* target. Once a revision exists, the legacy columns
        # hold today's numbers, and returning them for a date before the
        # first revision would assert that today's target applied then.
        #
        # That is the exact failure this subsystem exists to prevent: a
        # September adherence figure computed against an October calorie
        # target that was set in October.
        if _has_revisions(db, uid, TargetScope.PHASE, phase["id"]):
            return ResolvedTargets(
                user_id=uid, on_date=on_date, day_type=resolved_day_type,
                values=TargetValues(), provenance=TargetProvenance.UNKNOWN,
                scope=TargetScope.PHASE, phase_id=phase["id"],
                phase_name=phase.get("name"),
                history_unknown=True,
            )

        legacy = _phase_legacy_values(phase, resolved_day_type)
        if legacy is not None:
            return ResolvedTargets(
                user_id=uid, on_date=on_date, day_type=resolved_day_type,
                values=legacy, provenance=TargetProvenance.LEGACY_PHASE,
                scope=TargetScope.PHASE, phase_id=phase["id"],
                phase_name=phase.get("name"),
                effective_from=phase.get("start_date"),
                # Inclusive end_date → half-open. The one conversion point.
                effective_until=(
                    phase["end_date"] + timedelta(days=1)
                    if phase.get("end_date") else None
                ),
                history_unknown=True,
            )

    revision = _approved_revision(db, uid, TargetScope.DEFAULT, on_date)
    if revision:
        return _from_revision(
            uid, on_date, resolved_day_type, revision,
            phase_name=(phase or {}).get("name"),
            history_unknown=_precedes_history(db, uid, TargetScope.DEFAULT, on_date, None),
        )

    # Same rule for the default scope: `fitness_goals` is one mutable row
    # kept in step with the current revision, so it cannot answer for a date
    # that revision does not cover.
    if _has_revisions(db, uid, TargetScope.DEFAULT, None):
        return ResolvedTargets(
            user_id=uid, on_date=on_date, day_type=resolved_day_type,
            values=TargetValues(), provenance=TargetProvenance.UNKNOWN,
            scope=TargetScope.DEFAULT,
            phase_id=(phase or {}).get("id"),
            phase_name=(phase or {}).get("name"),
            history_unknown=True,
        )

    legacy_default = _default_legacy_values(db, uid)
    if legacy_default is not None:
        return ResolvedTargets(
            user_id=uid, on_date=on_date, day_type=resolved_day_type,
            values=legacy_default, provenance=TargetProvenance.LEGACY_DEFAULT,
            scope=TargetScope.DEFAULT,
            phase_id=(phase or {}).get("id"),
            phase_name=(phase or {}).get("name"),
            # No effective dates: `fitness_goals` is a mutable current row
            # with no history at all, so claiming a start date would be a
            # fabrication.
            history_unknown=True,
        )

    return ResolvedTargets(
        user_id=uid, on_date=on_date, day_type=resolved_day_type,
        values=TargetValues(), provenance=TargetProvenance.UNKNOWN,
        phase_id=(phase or {}).get("id"),
        phase_name=(phase or {}).get("name"),
        history_unknown=True,
    )


def _effective_phase(db: Session, user_id: str, on_date: date) -> Optional[Dict[str, Any]]:
    """The existing resolver, called with an explicit date."""
    try:
        from app.services.phase_resolution import get_effective_phase
        return get_effective_phase(db, user_id, on_date=on_date)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("phase resolution failed for %s on %s: %s", user_id, on_date, exc)
        return None


def _approved_revision(
    db: Session,
    user_id: str,
    scope: TargetScope,
    on_date: date,
    *,
    phase_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """The approved revision covering `on_date`, newest version wins.

    `approved_at IS NOT NULL` is the filter that keeps a draft revision from
    silently becoming the athlete's target before anyone accepted it.
    """
    rows = db.execute(text(f"""
        SELECT {_REVISION_COLUMNS}
        FROM fitness_target_revision
        WHERE user_id = :uid
          AND scope = :scope
          AND COALESCE(phase_id, '') = COALESCE(:pid, '')
          AND approved_at IS NOT NULL
          AND valid_from <= :d
          AND (valid_until IS NULL OR valid_until > :d)
        ORDER BY version DESC
        LIMIT 1
    """), {"uid": user_id, "scope": scope.value, "pid": phase_id, "d": on_date}).fetchone()
    return dict(rows._mapping) if rows else None


def _has_revisions(
    db: Session, user_id: str, scope: TargetScope, phase_id: Optional[str]
) -> bool:
    """Whether any approved revision exists for this scope at all.

    The dividing line between "this athlete's targets have never been
    recorded, so the legacy column is the best available answer" and "this
    athlete's targets ARE recorded, so a gap in them is a genuine unknown".
    """
    return bool(db.execute(text("""
        SELECT 1 FROM fitness_target_revision
        WHERE user_id = :uid AND scope = :scope
          AND COALESCE(phase_id, '') = COALESCE(:pid, '')
          AND approved_at IS NOT NULL
        LIMIT 1
    """), {"uid": user_id, "scope": scope.value, "pid": phase_id}).fetchone())


def _precedes_history(
    db: Session, user_id: str, scope: TargetScope, on_date: date,
    phase_id: Optional[str],
) -> bool:
    """True when `on_date` is before the first revision for this scope.

    The caller is asking about a period where the targets genuinely are not
    recorded. Returning the current values for it would invent adherence.
    """
    earliest = db.execute(text("""
        SELECT MIN(valid_from) FROM fitness_target_revision
        WHERE user_id = :uid AND scope = :scope
          AND COALESCE(phase_id, '') = COALESCE(:pid, '')
          AND approved_at IS NOT NULL
    """), {"uid": user_id, "scope": scope.value, "pid": phase_id}).scalar()
    return earliest is None or on_date < earliest


def _from_revision(
    user_id: str,
    on_date: date,
    day_type: DayType,
    revision: Dict[str, Any],
    *,
    phase_name: Optional[str],
    history_unknown: bool,
) -> ResolvedTargets:
    values = _revision_values(revision, day_type)
    return ResolvedTargets(
        user_id=user_id,
        on_date=on_date,
        day_type=day_type,
        values=values,
        provenance=TargetProvenance.APPROVED_REVISION,
        scope=TargetScope(revision["scope"]),
        phase_id=revision.get("phase_id"),
        phase_name=phase_name,
        revision_id=revision["id"],
        revision_version=int(revision["version"]),
        effective_from=revision["valid_from"],
        effective_until=revision["valid_until"],
        history_unknown=history_unknown,
    )


def _revision_values(revision: Dict[str, Any], day_type: DayType) -> TargetValues:
    """Pick the training or rest variant.

    A revision with null rest values does not distinguish day types, so both
    read the training values. That is different from a rest-day target of 0,
    which is why the fallback is `if x is None` and not `or`.
    """
    def pick(train_key: str, rest_key: str) -> Optional[int]:
        if day_type is DayType.REST:
            rest = revision.get(rest_key)
            if rest is not None:
                return int(rest)
        value = revision.get(train_key)
        return int(value) if value is not None else None

    sleep = revision.get("sleep_hours")
    return TargetValues(
        calories=pick("calories", "rest_calories"),
        protein_g=pick("protein_g", "rest_protein_g"),
        carbs_g=pick("carbs_g", "rest_carbs_g"),
        fat_g=pick("fat_g", "rest_fat_g"),
        # Sleep and water are not day-typed; steps is.
        sleep_hours=float(sleep) if sleep is not None else None,
        water_ml=revision.get("water_ml"),
        steps=pick("steps", "rest_steps"),
        calorie_tolerance_pct=float(revision.get("calorie_tolerance_pct") or 10),
        protein_tolerance_pct=float(revision.get("protein_tolerance_pct") or 10),
    )


def _phase_legacy_values(
    phase: Dict[str, Any], day_type: DayType
) -> Optional[TargetValues]:
    """A phase's own macro columns, read the way the existing UI reads them.

    Returns None when the phase carries no calorie or protein target at all —
    an empty phase resolves to unknown, not to zeros.
    """
    def pick(train_key: str, rest_key: str, base_key: Optional[str]) -> Optional[int]:
        if day_type is DayType.REST and phase.get(rest_key) is not None:
            return int(phase[rest_key])
        if phase.get(train_key) is not None:
            return int(phase[train_key])
        if base_key and phase.get(base_key) is not None:
            return int(phase[base_key])
        return None

    calories = pick("calories_training_day", "calories_rest_day", "calories_target")
    protein = int(phase["protein_target"]) if phase.get("protein_target") is not None else None
    carbs = pick("carbs_training_day", "carbs_rest_day", "carbs_target")
    fat = pick("fat_training_day", "fat_rest_day", "fat_target")
    steps = phase.get("daily_steps_target")

    if all(v is None for v in (calories, protein, carbs, fat, steps)):
        return None
    return TargetValues(
        calories=calories, protein_g=protein, carbs_g=carbs, fat_g=fat,
        steps=int(steps) if steps is not None else None,
    )


def _default_legacy_values(db: Session, user_id: str) -> Optional[TargetValues]:
    row = db.execute(text("""
        SELECT calories, protein, carbs, fats FROM fitness_goals
        WHERE user_id = :uid
        ORDER BY updated_at DESC NULLS LAST
        LIMIT 1
    """), {"uid": user_id}).fetchone()
    if row is None:
        return None
    return TargetValues(
        calories=row.calories, protein_g=row.protein,
        carbs_g=row.carbs, fat_g=row.fats,
    )


# ─────────────────────────────────────────────────────────────────────────
# Writing
# ─────────────────────────────────────────────────────────────────────────

def create_target_revision(
    db: Session,
    user_id: str,
    payload: TargetRevisionIn,
    *,
    expected_revision: Optional[str] = None,
    approved_by: Optional[str] = None,
    sync_legacy: bool = True,
) -> TargetRevisionOut:
    """Append an approved revision and close the previous one, atomically.

    Two things happen in one transaction and must not be separable:

    1. The open revision covering `valid_from` gets `valid_until =
       valid_from` — closed, not overwritten. Its values stay queryable, so a
       review that cited them stays verifiable.
    2. The legacy projection (`fitness_phase` macros, or `fitness_goals`)
       is updated **only when this revision is the current one**. Writing a
       backdated revision must not change what the dashboard shows today.

    `expected_revision` is the optimistic-concurrency check used when
    accepting a coach recommendation: the proposal was computed against a
    specific current revision, and if that has moved the acceptance is stale.
    """
    uid = _require_user(user_id)
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _advisory_key(uid)})

    if payload.scope is TargetScope.PHASE:
        owned = db.execute(text(
            "SELECT id, name, start_date, end_date FROM fitness_phase "
            "WHERE id = :pid AND user_id = :uid"
        ), {"pid": payload.phase_id, "uid": uid}).fetchone()
        if owned is None:
            # 404-shaped: a foreign phase must not confirm its own existence.
            raise LookupError("phase not found")

    current = _approved_revision(
        db, uid, payload.scope, payload.valid_from, phase_id=payload.phase_id
    )
    if expected_revision is not None:
        current_id = (current or {}).get("id")
        if current_id != expected_revision:
            raise TargetConflict(
                "the targets changed since this proposal was computed; "
                "recompute before accepting",
                current_revision_id=current_id,
            )

    # Anything approved that *starts after* this revision and would overlap
    # it is a genuine conflict — a revision cannot be inserted underneath
    # existing history.
    later_conflict = db.execute(text("""
        SELECT id FROM fitness_target_revision
        WHERE user_id = :uid AND scope = :scope
          AND COALESCE(phase_id, '') = COALESCE(:pid, '')
          AND approved_at IS NOT NULL
          AND valid_from > :vf
          AND valid_from < COALESCE(:vu, 'infinity'::date)
        LIMIT 1
    """), {
        "uid": uid, "scope": payload.scope.value, "pid": payload.phase_id,
        "vf": payload.valid_from, "vu": payload.valid_until,
    }).fetchone()
    if later_conflict:
        raise TargetConflict(
            f"an approved revision already starts inside "
            f"[{payload.valid_from}, {payload.valid_until or 'open'}); "
            "correct that revision instead of inserting under it",
            current_revision_id=later_conflict.id,
        )

    if current:
        if current["valid_from"] == payload.valid_from:
            # Same start date: this replaces it rather than closing it, since
            # a zero-length interval is not a valid revision.
            db.execute(text("""
                UPDATE fitness_target_revision
                SET approved_at = NULL WHERE id = :id
            """), {"id": current["id"]})
        else:
            db.execute(text("""
                UPDATE fitness_target_revision
                SET valid_until = :vf WHERE id = :id
            """), {"vf": payload.valid_from, "id": current["id"]})

    next_version = int(db.execute(text("""
        SELECT COALESCE(MAX(version), 0) + 1 FROM fitness_target_revision
        WHERE user_id = :uid AND scope = :scope
          AND COALESCE(phase_id, '') = COALESCE(:pid, '')
    """), {"uid": uid, "scope": payload.scope.value, "pid": payload.phase_id}).scalar())

    rid = str(uuid.uuid4())
    t, r = payload.training, payload.rest
    db.execute(text("""
        INSERT INTO fitness_target_revision
            (id, user_id, scope, phase_id, version, valid_from, valid_until,
             calories, protein_g, carbs_g, fat_g,
             rest_calories, rest_protein_g, rest_carbs_g, rest_fat_g, rest_steps,
             sleep_hours, water_ml, steps,
             calorie_tolerance_pct, protein_tolerance_pct,
             source, review_recommendation_id, approved_at, approved_by)
        VALUES
            (:id, :uid, :scope, :pid, :version, :vf, :vu,
             :cal, :pro, :carb, :fat,
             :rcal, :rpro, :rcarb, :rfat, :rsteps,
             :sleep, :water, :steps,
             :ctol, :ptol,
             :src, :rec, NOW(), :by)
    """), {
        "id": rid, "uid": uid, "scope": payload.scope.value,
        "pid": payload.phase_id, "version": next_version,
        "vf": payload.valid_from, "vu": payload.valid_until,
        "cal": t.calories, "pro": t.protein_g, "carb": t.carbs_g, "fat": t.fat_g,
        "rcal": (r.calories if r else None),
        "rpro": (r.protein_g if r else None),
        "rcarb": (r.carbs_g if r else None),
        "rfat": (r.fat_g if r else None),
        "rsteps": (r.steps if r else None),
        "sleep": t.sleep_hours, "water": t.water_ml, "steps": t.steps,
        "ctol": t.calorie_tolerance_pct, "ptol": t.protein_tolerance_pct,
        "src": payload.source, "rec": payload.review_recommendation_id,
        "by": approved_by or uid,
    })

    if sync_legacy and (payload.valid_until is None or payload.valid_until > date.today()):
        _sync_legacy_projection(db, uid, payload)

    # Macro numbers are a prescription the athlete or a review set, not an
    # observation of their body, so they may appear in a world fact. The
    # version is included because that is what tells a consumer whether it
    # has already seen this change.
    record_fitness_event(
        db, uid, "fitness.target_changed",
        dedupe_key=f"fitness.target:{rid}",
        source_ref=rid, aggregate_type="fitness_target_revision",
        aggregate_id=rid,
        payload={
            "scope": payload.scope.value, "phase_id": payload.phase_id,
            "valid_from": payload.valid_from.isoformat(),
            "valid_until": payload.valid_until.isoformat() if payload.valid_until else None,
            "source": payload.source,
            "from_recommendation": bool(payload.review_recommendation_id),
            "has_rest_variant": payload.rest is not None,
        },
        logical_date=payload.valid_from,
        actor_type="user" if payload.source == "user" else "system",
    )
    db.commit()
    return get_revision(db, uid, rid)


def _sync_legacy_projection(db: Session, user_id: str, payload: TargetRevisionIn) -> None:
    """Keep the existing readers correct.

    `fitness_phase`'s macro columns and `fitness_goals`' macros are what
    `fitness_context.py`, `world_brief.py`, the dashboard and the iOS app
    read today. Updating them in the same transaction as the revision is
    what makes "old macro endpoints and new APIs agree" true rather than
    aspirational.

    Only called for a revision that is current, so a backdated correction
    does not change what today's dashboard shows.
    """
    t, r = payload.training, payload.rest
    if payload.scope is TargetScope.PHASE:
        db.execute(text("""
            UPDATE fitness_phase SET
                calories_target       = COALESCE(:cal, calories_target),
                protein_target        = COALESCE(:pro, protein_target),
                carbs_target          = COALESCE(:carb, carbs_target),
                fat_target            = COALESCE(:fat, fat_target),
                calories_training_day = COALESCE(:cal, calories_training_day),
                carbs_training_day    = COALESCE(:carb, carbs_training_day),
                fat_training_day      = COALESCE(:fat, fat_training_day),
                calories_rest_day     = COALESCE(:rcal, calories_rest_day),
                carbs_rest_day        = COALESCE(:rcarb, carbs_rest_day),
                fat_rest_day          = COALESCE(:rfat, fat_rest_day),
                daily_steps_target    = COALESCE(:steps, daily_steps_target),
                updated_at            = CURRENT_TIMESTAMP
            WHERE id = :pid AND user_id = :uid
        """), {
            "cal": t.calories, "pro": t.protein_g, "carb": t.carbs_g, "fat": t.fat_g,
            "rcal": (r.calories if r else None),
            "rcarb": (r.carbs_g if r else None),
            "rfat": (r.fat_g if r else None),
            "steps": t.steps, "pid": payload.phase_id, "uid": user_id,
        })
    else:
        existing = db.execute(text(
            "SELECT id FROM fitness_goals WHERE user_id = :uid LIMIT 1"
        ), {"uid": user_id}).fetchone()
        if existing:
            db.execute(text("""
                UPDATE fitness_goals SET
                    calories = COALESCE(:cal, calories),
                    protein  = COALESCE(:pro, protein),
                    carbs    = COALESCE(:carb, carbs),
                    fats     = COALESCE(:fat, fats),
                    updated_at = NOW()
                WHERE user_id = :uid
            """), {"cal": t.calories, "pro": t.protein_g, "carb": t.carbs_g,
                   "fat": t.fat_g, "uid": user_id})
        else:
            db.execute(text("""
                INSERT INTO fitness_goals (id, user_id, calories, protein, carbs, fats)
                VALUES (:id, :uid, :cal, :pro, :carb, :fat)
            """), {"id": str(uuid.uuid4()), "uid": user_id,
                   "cal": t.calories, "pro": t.protein_g,
                   "carb": t.carbs_g, "fat": t.fat_g})


def get_revision(db: Session, user_id: str, revision_id: str) -> TargetRevisionOut:
    uid = _require_user(user_id)
    row = db.execute(text(
        f"SELECT {_REVISION_COLUMNS} FROM fitness_target_revision "
        "WHERE id = :id AND user_id = :uid"
    ), {"id": revision_id, "uid": uid}).fetchone()
    if row is None:
        raise LookupError("target revision not found")
    return _revision_out(row)


def list_revisions(
    db: Session,
    user_id: str,
    *,
    scope: Optional[TargetScope] = None,
    phase_id: Optional[str] = None,
    limit: int = 100,
) -> List[TargetRevisionOut]:
    """The athlete's target history, newest first."""
    uid = _require_user(user_id)
    clauses = ["user_id = :uid"]
    params: Dict[str, Any] = {"uid": uid, "lim": min(int(limit), 500)}
    if scope is not None:
        clauses.append("scope = :scope")
        params["scope"] = scope.value
    if phase_id is not None:
        clauses.append("phase_id = :pid")
        params["pid"] = phase_id
    rows = db.execute(text(f"""
        SELECT {_REVISION_COLUMNS} FROM fitness_target_revision
        WHERE {' AND '.join(clauses)}
        ORDER BY valid_from DESC, version DESC
        LIMIT :lim
    """), params).fetchall()
    return [_revision_out(r) for r in rows]


def _revision_out(row: Any) -> TargetRevisionOut:
    m = dict(row._mapping)
    sleep = m.get("sleep_hours")
    training = TargetValues(
        calories=m["calories"], protein_g=m["protein_g"],
        carbs_g=m["carbs_g"], fat_g=m["fat_g"],
        sleep_hours=float(sleep) if sleep is not None else None,
        water_ml=m["water_ml"], steps=m["steps"],
        calorie_tolerance_pct=float(m["calorie_tolerance_pct"]),
        protein_tolerance_pct=float(m["protein_tolerance_pct"]),
    )
    has_rest = any(
        m.get(k) is not None
        for k in ("rest_calories", "rest_protein_g", "rest_carbs_g",
                  "rest_fat_g", "rest_steps")
    )
    rest = TargetValues(
        calories=m["rest_calories"], protein_g=m["rest_protein_g"],
        carbs_g=m["rest_carbs_g"], fat_g=m["rest_fat_g"],
        sleep_hours=float(sleep) if sleep is not None else None,
        water_ml=m["water_ml"],
        steps=m["rest_steps"] if m["rest_steps"] is not None else m["steps"],
        calorie_tolerance_pct=float(m["calorie_tolerance_pct"]),
        protein_tolerance_pct=float(m["protein_tolerance_pct"]),
    ) if has_rest else None

    return TargetRevisionOut(
        id=m["id"], user_id=m["user_id"], scope=TargetScope(m["scope"]),
        phase_id=m["phase_id"], version=int(m["version"]),
        valid_from=m["valid_from"], valid_until=m["valid_until"],
        training=training, rest=rest,
        source=m["source"],
        review_recommendation_id=m["review_recommendation_id"],
        approved_at=m["approved_at"], approved_by=m["approved_by"],
        created_at=m["created_at"],
    )


def seed_phase_revision(
    db: Session,
    user_id: str,
    phase_id: str,
    nutrition: Dict[str, Any],
    *,
    start_date: date,
    end_date: Optional[date] = None,
    source: str = "phase_created",
) -> Optional[str]:
    """Record the initial revision for a phase being *created*.

    Distinct from `record_phase_edit` in one way that matters: a newly
    created phase's targets provably applied from its own `start_date`, so
    the revision is dated there rather than today. `plan_adjust.py` (which
    splits and copies blocks) and `plan_importer.py` (which creates a whole
    program from a document) both call this.

    `end_date` is **inclusive** here, matching `fitness_phase`, and is
    converted to the half-open `valid_until` exactly once — in this
    function. A caller passing a half-open end would shift every target by
    a day.

    Does not commit: the caller owns the transaction that created the phase,
    and a revision that outlived a rolled-back phase would reference nothing.
    Returns the new revision's id, or None when there is nothing to record.
    """
    if not nutrition:
        return None
    values = TargetValues(
        calories=nutrition.get("calories_training_day") or nutrition.get("calories_target"),
        protein_g=nutrition.get("protein_target"),
        carbs_g=nutrition.get("carbs_training_day") or nutrition.get("carbs_target"),
        fat_g=nutrition.get("fat_training_day") or nutrition.get("fat_target"),
        steps=nutrition.get("daily_steps_target"),
    )
    if all(v is None for v in (values.calories, values.protein_g,
                               values.carbs_g, values.fat_g, values.steps)):
        return None

    rest = None
    if any(nutrition.get(k) is not None for k in
           ("calories_rest_day", "carbs_rest_day", "fat_rest_day")):
        rest = TargetValues(
            calories=nutrition.get("calories_rest_day"),
            protein_g=nutrition.get("protein_target"),
            carbs_g=nutrition.get("carbs_rest_day"),
            fat_g=nutrition.get("fat_rest_day"),
            steps=nutrition.get("daily_steps_target"),
        )

    rid = str(uuid.uuid4())
    db.execute(text("""
        INSERT INTO fitness_target_revision
            (id, user_id, scope, phase_id, version, valid_from, valid_until,
             calories, protein_g, carbs_g, fat_g,
             rest_calories, rest_protein_g, rest_carbs_g, rest_fat_g, rest_steps,
             steps, source, approved_at, approved_by)
        VALUES
            (:id, :uid, 'phase', :pid, 1, :vf, :vu,
             :cal, :pro, :carb, :fat,
             :rcal, :rpro, :rcarb, :rfat, :rsteps,
             :steps, :src, NOW(), :uid)
        ON CONFLICT DO NOTHING
    """), {
        "id": rid, "uid": user_id, "pid": phase_id,
        "vf": start_date,
        # fitness_phase.end_date is INCLUSIVE; revisions are half-open.
        "vu": (end_date + timedelta(days=1)) if end_date else None,
        "cal": values.calories, "pro": values.protein_g,
        "carb": values.carbs_g, "fat": values.fat_g,
        "rcal": (rest.calories if rest else None),
        "rpro": (rest.protein_g if rest else None),
        "rcarb": (rest.carbs_g if rest else None),
        "rfat": (rest.fat_g if rest else None),
        "rsteps": (rest.steps if rest else None),
        "steps": values.steps, "src": source,
    })
    return rid


def record_phase_edit(
    db: Session,
    user_id: str,
    phase_id: str,
    values: TargetValues,
    *,
    rest: Optional[TargetValues] = None,
    effective_from: Optional[date] = None,
    source: str = "phase_edit",
) -> Optional[TargetRevisionOut]:
    """Entry point for the *existing* phase-macro writers.

    `routes/fitness.py`'s phase editor, `plan_adjust.py` and
    `plan_importer.py` all set phase macros directly. Each now calls this so
    the edit enters the revision history instead of silently replacing a
    historical target. Step 6's "no known target writer bypasses revision
    recording".

    Returns None — not an error — when the phase has no macros worth
    recording, so a caller editing only a phase's name does not create an
    empty revision.
    """
    if all(v is None for v in (values.calories, values.protein_g,
                               values.carbs_g, values.fat_g, values.steps)):
        return None
    uid = _require_user(user_id)
    start = effective_from
    if start is None:
        row = db.execute(text(
            "SELECT start_date FROM fitness_phase WHERE id = :pid AND user_id = :uid"
        ), {"pid": phase_id, "uid": uid}).fetchone()
        if row is None:
            raise LookupError("phase not found")
        from app.services.fitness.profile import athlete_today
        # The edit takes effect today, not at the phase's start: retroactively
        # applying new macros to weeks already lived would rewrite adherence.
        start = max(row.start_date or athlete_today(db, uid), athlete_today(db, uid)) \
            if row.start_date else athlete_today(db, uid)

    try:
        return create_target_revision(
            db, uid,
            TargetRevisionIn(
                scope=TargetScope.PHASE, phase_id=phase_id,
                valid_from=start, training=values, rest=rest, source=source,
            ),
            # The legacy columns were already written by the caller; writing
            # them again would be harmless but pointless.
            sync_legacy=False,
        )
    except TargetConflict as exc:
        # A phase edit must not fail because its history is tangled; log and
        # let the caller's own write stand, with the conflict visible.
        logger.warning(
            "phase %s macro edit could not be recorded as a revision: %s",
            phase_id, exc
        )
        return None
