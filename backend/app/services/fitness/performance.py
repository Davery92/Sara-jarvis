"""Exercise occurrences, precise load/effort metadata, and pain reports.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 13.

These functions are called *from inside* `workout_command_service`'s
transaction, not instead of it. That service remains the single mutation
authority — it holds the session lock, enforces `expected_version`, replays
commands idempotently and owns void/correction. Writing a set from here
would bypass all of it, so nothing here writes a `workout_log` row.

What it does own:

* **`ensure_occurrence`** — the stable identity of one appearance of one
  exercise within one session. "Bench, something else, bench again" is two
  occurrences, and without it "how did the second block compare to the
  first" has no subject.
* **`attach_precise_load`** — the fractional load/unit pair and the effort,
  role and rest fields. The integer `workout_log.weight` stays as the
  compatibility projection; this never truncates in either direction.
* **`record_pain`** — what the athlete said, with no diagnosis anywhere, and
  summaries that count distinct *sessions* rather than sets.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.fitness_coach import (
    Metric,
    Unavailable,
    Unit,
    UnitError,
    convert,
    ensure_finite,
)
from app.services.fitness.data_access import (
    FitnessDataError,
    _require_user,
    athlete_zone,
    local_date_of,
)

logger = logging.getLogger(__name__)

# Roles of a WORKING set. Deliberately not values of `set_kind`, which stays
# working/warmup/drop — revision 125's counting rules and `workout_recalc`
# depend on those three, and a top set that stopped counting toward the
# target would be a real bug.
VALID_SET_ROLES = frozenset({
    "top", "backoff", "amrap", "myo", "cluster", "straight",
})

VALID_LOAD_UNITS = frozenset({Unit.KG, Unit.LB})


@dataclass(frozen=True)
class Occurrence:
    id: str
    user_id: str
    active_session_id: str
    occurrence: int
    captured_name: str
    captured_variant: Optional[str]
    exercise_library_id: Optional[str]
    order_index: int
    pain_reported: bool
    max_pain_severity: Optional[int]


@dataclass(frozen=True)
class PainPattern:
    """Pain for one canonical exercise, counted by session.

    `sessions_with_pain` and `sessions_with_report` are both present because
    the ratio is the only honest statement: "four of six documented barbell
    curl sessions" means something; "four reports" does not, since four
    reports could all be from one session.
    """
    exercise_library_id: Optional[str]
    exercise_name: str
    sessions_with_pain: int
    sessions_with_report: int
    sessions_total: int
    max_severity: Optional[int]
    latest_severity: Optional[int]
    latest_at: Optional[datetime]
    locations: Tuple[str, ...] = ()
    sides: Tuple[str, ...] = ()

    @property
    def reporting_coverage(self) -> Optional[float]:
        """What fraction of sessions were asked about.

        None when there were no sessions. A pattern drawn from two reports
        out of twenty sessions is a different claim from two out of two, and
        the denominator is what says which.
        """
        if not self.sessions_total:
            return None
        return self.sessions_with_report / self.sessions_total


# ─────────────────────────────────────────────────────────────────────────
# Occurrences
# ─────────────────────────────────────────────────────────────────────────

def ensure_occurrence(
    db: Session,
    user_id: str,
    active_session_id: str,
    *,
    captured_name: str,
    captured_variant: Optional[str] = None,
    template_slot_id: Optional[str] = None,
    exercise_library_id: Optional[str] = None,
    load_convention: Optional[str] = None,
    order_index: int = 0,
    new_block: bool = False,
) -> Occurrence:
    """The occurrence a set belongs to, creating it if needed.

    Idempotent for the ordinary case: successive sets of the same exercise
    reuse the open occurrence, which is what makes "sets in this block"
    countable. `new_block=True` forces a fresh occurrence — that is how the
    second bench block becomes a second occurrence rather than more sets on
    the first.

    Matching is on the *captured* name and variant, not on the canonical id.
    A variant change mid-session ("switched to close grip") is a different
    block of work, and the canonical id may be identical for both.

    Does not commit: the caller's transaction owns the set and the occurrence
    together, so a rolled-back set leaves no orphan occurrence.
    """
    uid = _require_user(user_id)
    name = (captured_name or "").strip()
    if not name:
        raise FitnessDataError("an occurrence needs the exercise name it was logged under")
    variant = (captured_variant or "").strip() or None

    owns = db.execute(text("""
        SELECT 1 FROM active_workout_session WHERE id = :sid AND user_id = :uid
    """), {"sid": active_session_id, "uid": uid}).fetchone()
    if not owns:
        raise LookupError("session not found")

    if not new_block:
        existing = db.execute(text("""
            SELECT id, user_id, active_session_id, occurrence, captured_name,
                   captured_variant, exercise_library_id, order_index,
                   pain_reported, max_pain_severity
            FROM fitness_exercise_performance
            WHERE active_session_id = :sid
              AND user_id = :uid
              AND captured_name = :name
              AND COALESCE(captured_variant, '') = COALESCE(:variant, '')
            ORDER BY occurrence DESC
            LIMIT 1
        """), {"sid": active_session_id, "uid": uid, "name": name,
               "variant": variant}).fetchone()
        if existing:
            return Occurrence(**dict(existing._mapping))

    # `occurrence` is per session, not per exercise: it is the order the
    # blocks happened in, which is what makes a session's shape readable.
    next_occurrence = int(db.execute(text("""
        SELECT COALESCE(MAX(occurrence), 0) + 1
        FROM fitness_exercise_performance
        WHERE active_session_id = :sid
    """), {"sid": active_session_id}).scalar())

    perf_id = str(uuid.uuid4())
    db.execute(text("""
        INSERT INTO fitness_exercise_performance
            (id, user_id, active_session_id, occurrence, template_slot_id,
             exercise_library_id, captured_name, captured_variant,
             captured_load_convention, order_index)
        VALUES (:id, :uid, :sid, :occ, :slot, :canon, :name, :variant,
                :convention, :order_index)
    """), {
        "id": perf_id, "uid": uid, "sid": active_session_id,
        "occ": next_occurrence, "slot": template_slot_id,
        "canon": exercise_library_id, "name": name, "variant": variant,
        "convention": load_convention, "order_index": order_index,
    })
    row = db.execute(text("""
        SELECT id, user_id, active_session_id, occurrence, captured_name,
               captured_variant, exercise_library_id, order_index,
               pain_reported, max_pain_severity
        FROM fitness_exercise_performance WHERE id = :id
    """), {"id": perf_id}).fetchone()
    return Occurrence(**dict(row._mapping))


def list_occurrences(
    db: Session, user_id: str, active_session_id: str
) -> List[Occurrence]:
    uid = _require_user(user_id)
    rows = db.execute(text("""
        SELECT id, user_id, active_session_id, occurrence, captured_name,
               captured_variant, exercise_library_id, order_index,
               pain_reported, max_pain_severity
        FROM fitness_exercise_performance
        WHERE active_session_id = :sid AND user_id = :uid
        ORDER BY occurrence
    """), {"sid": active_session_id, "uid": uid}).fetchall()
    return [Occurrence(**dict(r._mapping)) for r in rows]


# ─────────────────────────────────────────────────────────────────────────
# Precise load and effort
# ─────────────────────────────────────────────────────────────────────────

def attach_precise_load(
    db: Session,
    user_id: str,
    set_id: str,
    *,
    load_value: Optional[float] = None,
    load_unit: Optional[Unit] = None,
    rir: Optional[float] = None,
    rpe_decimal: Optional[float] = None,
    set_role: Optional[str] = None,
    is_failure: Optional[bool] = None,
    actual_rest_seconds: Optional[int] = None,
    tempo: Optional[str] = None,
    exercise_performance_id: Optional[str] = None,
) -> None:
    """Add the fields the legacy columns cannot hold.

    The integer `workout_log.weight` is left as it is — it is the
    compatibility projection every shipped client reads, and overwriting it
    with a rounded fraction would change what those clients show.
    `data_access.effective_load` prefers `load_value` precisely so analytics
    see 227.5 while an old client still sees 227.

    Does not commit. Called inside the command service's transaction, so the
    set and its precision land together.
    """
    uid = _require_user(user_id)

    owns = db.execute(text("""
        SELECT 1 FROM workout_log WHERE id = :sid AND user_id = :uid
    """), {"sid": set_id, "uid": uid}).fetchone()
    if not owns:
        raise LookupError("set not found")

    assignments: List[str] = []
    params: Dict[str, Any] = {"sid": set_id, "uid": uid}

    if load_value is not None:
        ensure_finite(load_value, "load_value")
        if load_value < 0:
            raise FitnessDataError("a load cannot be negative")
        if load_unit is None:
            raise FitnessDataError(
                "a load needs its unit: a bare number cannot be compared "
                "against anything"
            )
        if load_unit not in VALID_LOAD_UNITS:
            raise FitnessDataError(
                f"{load_unit.value!r} is not a load unit (kg or lb)"
            )
        assignments += ["load_value = :load_value", "load_unit = :load_unit"]
        params["load_value"] = load_value
        params["load_unit"] = load_unit.value

    if rir is not None:
        ensure_finite(rir, "rir")
        if not 0 <= rir <= 10:
            raise FitnessDataError("reps in reserve must be 0-10")
        assignments.append("rir = :rir")
        params["rir"] = rir

    if rpe_decimal is not None:
        ensure_finite(rpe_decimal, "rpe_decimal")
        if not 1 <= rpe_decimal <= 10:
            raise FitnessDataError("RPE must be 1-10")
        assignments.append("rpe_decimal = :rpe_decimal")
        params["rpe_decimal"] = rpe_decimal

    if set_role is not None:
        if set_role not in VALID_SET_ROLES:
            raise FitnessDataError(
                f"{set_role!r} is not a set role "
                f"({', '.join(sorted(VALID_SET_ROLES))}). Note these are roles "
                "of a working set, not values of set_kind."
            )
        assignments.append("set_role = :set_role")
        params["set_role"] = set_role

    if is_failure is not None:
        assignments.append("is_failure = :is_failure")
        params["is_failure"] = bool(is_failure)

    if actual_rest_seconds is not None:
        if not 0 <= int(actual_rest_seconds) <= 86400:
            raise FitnessDataError("a rest period must be 0-86400 seconds")
        assignments.append("actual_rest_seconds = :rest")
        params["rest"] = int(actual_rest_seconds)

    if tempo is not None:
        assignments.append("tempo = :tempo")
        params["tempo"] = tempo[:16]

    if exercise_performance_id is not None:
        owns_perf = db.execute(text("""
            SELECT 1 FROM fitness_exercise_performance
            WHERE id = :pid AND user_id = :uid
        """), {"pid": exercise_performance_id, "uid": uid}).fetchone()
        if not owns_perf:
            raise LookupError("exercise performance not found")
        assignments.append("exercise_performance_id = :perf")
        params["perf"] = exercise_performance_id

    if not assignments:
        return

    db.execute(text(f"""
        UPDATE workout_log SET {', '.join(assignments)}
        WHERE id = :sid AND user_id = :uid
    """), params)


def set_effort(row: Any) -> Tuple[Optional[float], Optional[str]]:
    """The effort of a set, and which scale it is on.

    RIR and RPE are different scales and are not converted into each other:
    the conversion depends on the rep range, and doing it here would bake
    that assumption into every comparison. Returns the value and the scale
    name so a caller can refuse to compare across them.
    """
    m = row._mapping if hasattr(row, "_mapping") else row
    rir = m.get("rir")
    if rir is not None:
        return float(rir), "rir"
    decimal = m.get("rpe_decimal")
    if decimal is not None:
        return float(decimal), "rpe"
    legacy = m.get("rpe")
    if legacy is not None:
        return float(legacy), "rpe"
    return None, None


# ─────────────────────────────────────────────────────────────────────────
# Pain
# ─────────────────────────────────────────────────────────────────────────

def record_pain(
    db: Session,
    user_id: str,
    *,
    pain_present: bool,
    occurred_at: datetime,
    severity: Optional[int] = None,
    location: Optional[str] = None,
    side: Optional[str] = None,
    onset: Optional[str] = None,
    context: Optional[str] = None,
    notes: Optional[str] = None,
    exercise_performance_id: Optional[str] = None,
    active_session_id: Optional[str] = None,
    workout_set_id: Optional[str] = None,
    exercise_library_id: Optional[str] = None,
    corrects_report_id: Optional[str] = None,
    timezone_name: Optional[str] = None,
    source: str = "manual",
    commit: bool = True,
) -> str:
    """Record what the athlete said about pain.

    `pain_present` is required and has no default. A session with no report
    is unknown, not pain-free, and the only way to keep that true is to
    refuse to write a row that does not state it.

    `severity=0` with `pain_present=False` is the meaningful "asked, nothing
    hurt" answer, which is different from no row at all. Severity above zero
    with `pain_present=False` is refused by the constraint: such a row would
    count as pain in one query and as no-pain in another.

    A correction supersedes rather than overwrites — "I said 7 but it was
    more like 3" is a second statement, and both are things the athlete said.
    """
    uid = _require_user(user_id)

    if severity is not None:
        if not 0 <= int(severity) <= 10:
            raise FitnessDataError("pain severity is 0-10")
        if not pain_present and int(severity) > 0:
            raise FitnessDataError(
                "a severity above zero with pain_present=false is incoherent: "
                "the row would count as pain in one query and not in another"
            )
    if side is not None and side not in ("left", "right", "both", "none"):
        raise FitnessDataError(f"{side!r} is not a side")
    if onset is not None and onset not in ("sudden", "gradual", "pre_existing", "unknown"):
        raise FitnessDataError(f"{onset!r} is not a recognised onset")
    if occurred_at.tzinfo is None:
        raise FitnessDataError(
            "occurred_at must be timezone-aware so it lands on the right "
            "athlete-local day"
        )

    for table, value, label in (
        ("fitness_exercise_performance", exercise_performance_id, "exercise performance"),
        ("active_workout_session", active_session_id, "session"),
        ("workout_log", workout_set_id, "set"),
    ):
        if value is None:
            continue
        owns = db.execute(text(
            f"SELECT 1 FROM {table} WHERE id = :rid AND user_id = :uid"
        ), {"rid": value, "uid": uid}).fetchone()
        if not owns:
            raise LookupError(f"{label} not found")

    superseded: Optional[str] = None
    if corrects_report_id:
        prior = db.execute(text("""
            SELECT id FROM fitness_pain_report WHERE id = :rid AND user_id = :uid
        """), {"rid": corrects_report_id, "uid": uid}).fetchone()
        if not prior:
            raise LookupError("pain report not found")
        superseded = prior.id

    tz = athlete_zone(timezone_name or _profile_timezone(db, uid))
    logical = local_date_of(occurred_at.astimezone(timezone.utc), tz)

    report_id = str(uuid.uuid4())
    db.execute(text("""
        INSERT INTO fitness_pain_report
            (id, user_id, exercise_performance_id, active_session_id,
             workout_set_id, exercise_library_id, occurred_at, logical_date,
             pain_present, severity, location, side, onset, context, notes, source)
        VALUES (:id, :uid, :perf, :sid, :set_id, :canon, :at, :logical,
                :present, :severity, :location, :side, :onset, :context,
                :notes, :source)
    """), {
        "id": report_id, "uid": uid, "perf": exercise_performance_id,
        "sid": active_session_id, "set_id": workout_set_id,
        "canon": exercise_library_id,
        "at": occurred_at.astimezone(timezone.utc), "logical": logical,
        "present": bool(pain_present), "severity": severity,
        "location": location, "side": side, "onset": onset,
        "context": context, "notes": notes, "source": source,
    })

    if superseded:
        db.execute(text("""
            UPDATE fitness_pain_report SET superseded_by_id = :new
            WHERE id = :old AND user_id = :uid
        """), {"new": report_id, "old": superseded, "uid": uid})

    # Keep the occurrence's denormalized summary in step. The reports stay
    # the authority — this is a cheap read for the session projection, and it
    # is recomputed from the live reports rather than incremented, so a
    # correction cannot leave it stale.
    if exercise_performance_id:
        db.execute(text("""
            UPDATE fitness_exercise_performance p
            SET pain_reported = COALESCE(agg.any_pain, FALSE),
                max_pain_severity = agg.max_severity,
                updated_at = NOW()
            FROM (
                SELECT BOOL_OR(pain_present) AS any_pain,
                       MAX(severity) FILTER (WHERE pain_present) AS max_severity
                FROM fitness_pain_report
                WHERE exercise_performance_id = :pid AND superseded_by_id IS NULL
            ) agg
            WHERE p.id = :pid AND p.user_id = :uid
        """), {"pid": exercise_performance_id, "uid": uid})

    if commit:
        db.commit()
    return report_id


def _profile_timezone(db: Session, user_id: str) -> str:
    row = db.execute(text(
        "SELECT timezone FROM fitness_athlete_profile WHERE user_id = :uid"
    ), {"uid": user_id}).fetchone()
    return (row.timezone if row else None) or "America/New_York"


def pain_patterns(
    db: Session,
    user_id: str,
    start_date: date,
    end_date: date,
    *,
    min_sessions: int = 1,
) -> List[PainPattern]:
    """Pain per canonical exercise in `[start_date, end_date)`, by session.

    **Sessions, not sets.** Four reports across four sets of one session is
    one session with pain; counting reports would make a single bad session
    look like a pattern, which is exactly the kind of claim that would get
    an exercise dropped from a program for no reason.

    `sessions_total` is the denominator: "four of six documented barbell curl
    sessions" is a statement, "four reports" is not.
    """
    uid = _require_user(user_id)
    rows = db.execute(text("""
        WITH sessions AS (
            SELECT p.exercise_library_id,
                   -- The captured name is the fallback identity for sets
                   -- whose canonical id was never resolved; grouping on the
                   -- canonical id alone would silently merge them.
                   MIN(p.captured_name) AS exercise_name,
                   p.active_session_id,
                   BOOL_OR(r.id IS NOT NULL) AS had_report,
                   BOOL_OR(COALESCE(r.pain_present, FALSE)) AS had_pain,
                   MAX(r.severity) FILTER (WHERE r.pain_present) AS max_severity,
                   MAX(r.occurred_at) FILTER (WHERE r.pain_present) AS latest_at
            FROM fitness_exercise_performance p
            JOIN active_workout_session s ON s.id = p.active_session_id
            LEFT JOIN fitness_pain_report r
              ON r.exercise_performance_id = p.id
             AND r.superseded_by_id IS NULL
            WHERE p.user_id = :uid
              AND s.started_at >= :start_at
              AND s.started_at <  :end_at
            GROUP BY p.exercise_library_id, p.active_session_id
        )
        SELECT exercise_library_id,
               MIN(exercise_name) AS exercise_name,
               COUNT(*) AS sessions_total,
               COUNT(*) FILTER (WHERE had_report) AS sessions_with_report,
               COUNT(*) FILTER (WHERE had_pain) AS sessions_with_pain,
               MAX(max_severity) AS max_severity,
               MAX(latest_at) AS latest_at
        FROM sessions
        GROUP BY exercise_library_id
        HAVING COUNT(*) FILTER (WHERE had_pain) >= :min_sessions
        ORDER BY COUNT(*) FILTER (WHERE had_pain) DESC
    """), {
        "uid": uid,
        "start_at": datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc),
        "end_at": datetime.combine(end_date, datetime.min.time(), tzinfo=timezone.utc),
        "min_sessions": min_sessions,
    }).fetchall()

    out: List[PainPattern] = []
    for row in rows:
        detail = db.execute(text("""
            SELECT DISTINCT r.location, r.side, r.severity, r.occurred_at
            FROM fitness_pain_report r
            JOIN fitness_exercise_performance p ON p.id = r.exercise_performance_id
            WHERE r.user_id = :uid
              AND r.superseded_by_id IS NULL
              AND r.pain_present
              AND COALESCE(p.exercise_library_id, '') = COALESCE(:canon, '')
            ORDER BY r.occurred_at DESC
        """), {"uid": uid, "canon": row.exercise_library_id}).fetchall()

        out.append(PainPattern(
            exercise_library_id=row.exercise_library_id,
            exercise_name=row.exercise_name or "unknown exercise",
            sessions_with_pain=int(row.sessions_with_pain),
            sessions_with_report=int(row.sessions_with_report),
            sessions_total=int(row.sessions_total),
            max_severity=int(row.max_severity) if row.max_severity is not None else None,
            latest_severity=(
                int(detail[0].severity)
                if detail and detail[0].severity is not None else None
            ),
            latest_at=row.latest_at,
            locations=tuple(
                sorted({d.location for d in detail if d.location})
            ),
            sides=tuple(sorted({d.side for d in detail if d.side})),
        ))
    return out


def session_pain_status(
    db: Session, user_id: str, active_session_id: str
) -> Metric:
    """Whether this session had pain, as a metric that can say "unknown".

    A session with no report resolves to `NO_DATA`, not to zero. "Nobody
    asked" and "nothing hurt" support completely different coaching, and the
    whole point of an explicit `pain_present` column is that a missing row
    cannot be read as the second one.
    """
    uid = _require_user(user_id)
    row = db.execute(text("""
        SELECT COUNT(*) AS reports,
               BOOL_OR(pain_present) AS any_pain,
               MAX(severity) FILTER (WHERE pain_present) AS max_severity
        FROM fitness_pain_report
        WHERE user_id = :uid AND active_session_id = :sid
          AND superseded_by_id IS NULL
    """), {"uid": uid, "sid": active_session_id}).fetchone()

    if row is None or int(row.reports or 0) == 0:
        return Metric(
            key="pain.session",
            unit=Unit.SCORE,
            unavailable_reason=Unavailable.NO_DATA,
            note="nobody was asked about pain in this session — not the same as pain-free",
        )
    if not row.any_pain:
        return Metric(
            key="pain.session",
            value=0.0,
            unit=Unit.SCORE,
            source_count=int(row.reports),
            note="asked, and no pain reported",
        )
    return Metric(
        key="pain.session",
        value=float(row.max_severity) if row.max_severity is not None else 0.0,
        unit=Unit.SCORE,
        source_count=int(row.reports),
        note="highest reported severity in this session",
    )
