#!/usr/bin/env python3
"""Report ownership and consistency conflicts in Sara's existing fitness rows.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 4 / migration M0. Read-only by
default and read-only unless `--apply` is given *with* an explicit reviewed
mapping file. It does not reassign anything on its own: the whole reason this
exists is that `routes/fitness.py` spent its life handing out
`os.getenv("SOLO_USER_ID", "default-user")`, so some historical rows may be
owned by a string that is not an `app_user.id`, and nobody can know from the
data alone which human they belong to.

Explicitly refused behaviours, because each is a plausible shortcut that
would destroy information:

* Reassigning orphans to "the first user", "the only user", or anyone named
  David. An id that resolves to nothing is unresolved, not David's.
* Collapsing ambiguous `exercise_library` rows into global seeds. The table
  has no owner column and `exercise_library_seed.py` derived rows from
  whatever names already existed in people's logs, so a "custom" name may be
  private. Private-by-default for anything not provably generic.
* Printing values. The report prints counts, ids and column names — never a
  bodyweight, a measurement, a note or a meal.

Target database must be named explicitly. There is no default `DATABASE_URL`
fallback: the 2026-09-22 incident was a test run inheriting production's.

Usage:
    python backend/scripts/fitness_backfill_audit.py --database-url <url>
    python backend/scripts/fitness_backfill_audit.py --database-url <url> --json
    python backend/scripts/fitness_backfill_audit.py --database-url <url> \
        --apply --mapping reviewed_owners.json --yes
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    from sqlalchemy import create_engine, text
except ImportError:  # pragma: no cover - the container always has it
    print("sqlalchemy is required", file=sys.stderr)
    raise

# Tables with a user_id that should resolve to an app_user row.
OWNED_TABLES = (
    "fitness_program",
    "fitness_phase",
    "fitness_template",
    "fitness_goals",
    "food_log",
    "daily_recovery_log",
    "health_metric",
    "weight_trend",
    "workout_log",
    "workout_session",
    "active_workout_session",
    "exercise_pr",
    "progress_photo",
)

# Known artificial owners from the solo-stub era. Present here so the report
# can distinguish "a value the old stub produced" from "a real id whose user
# row was deleted" — they need different reviews.
STUB_OWNERS = ("default-user", "solo", "")


@dataclass
class Finding:
    check: str
    severity: str  # "block" | "review" | "note"
    count: int
    detail: str
    sample_ids: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity,
            "count": self.count,
            "detail": self.detail,
            "sample_ids": self.sample_ids[:10],
        }


def _table_exists(conn, table: str) -> bool:
    return bool(conn.execute(text(
        "SELECT to_regclass(:t) IS NOT NULL"
    ), {"t": table}).scalar())


def audit_orphan_owners(conn) -> List[Finding]:
    """Rows whose `user_id` does not resolve to an `app_user`."""
    out: List[Finding] = []
    for table in OWNED_TABLES:
        if not _table_exists(conn, table):
            continue
        rows = conn.execute(text(f"""
            SELECT t.user_id, COUNT(*) AS n,
                   (ARRAY_AGG(t.id ORDER BY t.id))[1:10] AS sample
            FROM {table} t
            LEFT JOIN app_user u ON u.id = t.user_id
            WHERE u.id IS NULL
            GROUP BY t.user_id
            ORDER BY n DESC
        """)).fetchall()
        for r in rows:
            owner = r.user_id
            is_stub = (owner or "") in STUB_OWNERS
            out.append(Finding(
                check=f"orphan_owner:{table}",
                severity="review",
                count=int(r.n),
                detail=(
                    f"{table}: {r.n} rows owned by "
                    f"{'the solo-era stub value' if is_stub else 'an id with no app_user row'} "
                    f"{owner!r}. These need a reviewed mapping before they can be "
                    f"claimed by anyone; they do not block new records."
                ),
                sample_ids=[str(x) for x in (r.sample or [])],
            ))
    return out


def audit_duplicate_active_programs(conn) -> List[Finding]:
    """More than one `is_active` program per athlete.

    `get_effective_phase()` resolves the active program with
    `ORDER BY updated_at DESC ... LIMIT 1`, so a second active program is
    silently shadowed — and which one wins changes when either is touched.
    """
    if not _table_exists(conn, "fitness_program"):
        return []
    rows = conn.execute(text("""
        SELECT user_id, COUNT(*) AS n,
               (ARRAY_AGG(id ORDER BY id))[1:10] AS sample
        FROM fitness_program
        WHERE is_active = true
        GROUP BY user_id
        HAVING COUNT(*) > 1
    """)).fetchall()
    return [Finding(
        check="duplicate_active_program",
        severity="review",
        count=int(r.n),
        detail=(
            f"{r.n} simultaneously active programs for one athlete. Phase "
            "resolution picks one by updated_at, so the effective phase can "
            "change without anyone editing a phase."
        ),
        sample_ids=[str(x) for x in (r.sample or [])],
    ) for r in rows]


def audit_overlapping_phases(conn) -> List[Finding]:
    """Two dated phases of one program covering the same day.

    Target revisions attach to a phase, so an overlap makes "which target
    applied on the 14th" ambiguous in a way the resolver cannot fix.
    """
    if not _table_exists(conn, "fitness_phase"):
        return []
    rows = conn.execute(text("""
        SELECT a.user_id, a.program_id, a.id AS a_id, b.id AS b_id
        FROM fitness_phase a
        JOIN fitness_phase b
          ON a.user_id = b.user_id
         AND a.program_id IS NOT DISTINCT FROM b.program_id
         AND a.id < b.id
        WHERE a.start_date IS NOT NULL AND a.end_date IS NOT NULL
          AND b.start_date IS NOT NULL AND b.end_date IS NOT NULL
          AND a.start_date <= b.end_date
          AND b.start_date <= a.end_date
        LIMIT 200
    """)).fetchall()
    if not rows:
        return []
    return [Finding(
        check="overlapping_phases",
        severity="review",
        count=len(rows),
        detail=(
            f"{len(rows)} overlapping dated phase pairs. A date covered by two "
            "phases has no single effective target; the resolver reports the "
            "conflict rather than choosing."
        ),
        sample_ids=[f"{r.a_id}~{r.b_id}" for r in rows[:10]],
    )]


def audit_unit_ambiguity(conn) -> List[Finding]:
    """Observations whose unit was never recorded and cannot be traced.

    Deliberately does NOT infer from magnitude. 180 lb and 180 kg are both
    real bodyweights; guessing would misstate the number by 120%.
    """
    out: List[Finding] = []
    if _table_exists(conn, "health_metric"):
        has_unit = bool(conn.execute(text("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name = 'health_metric' AND column_name = 'unit'
        """)).scalar())
        # Types whose writers were traced (see data_access.LEGACY_METRIC_UNITS).
        traced = (
            "weight", "body_weight", "sleep_hours", "sleep_duration", "sleep",
            "steps", "water", "water_ml", "hrv", "heart_rate",
            "resting_heart_rate", "resting_hr", "vo2_max", "body_fat_percent",
        )
        unit_clause = "AND unit IS NULL" if has_unit else ""
        rows = conn.execute(text(f"""
            SELECT metric_type, COUNT(*) AS n
            FROM health_metric
            WHERE metric_type <> ALL(:traced) {unit_clause}
            GROUP BY metric_type
            ORDER BY n DESC
            LIMIT 50
        """), {"traced": list(traced)}).fetchall()
        for r in rows:
            out.append(Finding(
                check="unresolved_unit",
                severity="note",
                count=int(r.n),
                detail=(
                    f"health_metric type {r.metric_type!r}: {r.n} rows with no "
                    "recorded unit and no traced writer. Flagged unresolved, "
                    "never guessed from the value."
                ),
            ))
    if _table_exists(conn, "daily_recovery_log"):
        n = conn.execute(text("""
            SELECT COUNT(*) FROM daily_recovery_log
            WHERE body_weight IS NOT NULL AND (weight_unit IS NULL OR weight_unit = '')
        """)).scalar()
        if n:
            out.append(Finding(
                check="unresolved_unit",
                severity="note",
                count=int(n),
                detail=(
                    f"{n} daily_recovery_log rows carry a body_weight with no "
                    "weight_unit. The column defaults to 'lbs' for new rows, "
                    "which says nothing about rows written before that default."
                ),
            ))
    return out


def audit_dangling_references(conn) -> List[Finding]:
    """Child rows pointing at parents that no longer exist, or at another owner.

    A cross-owner reference is the serious one: a UUID FK does not enforce
    ownership, so this is the only place it gets checked for history.
    """
    out: List[Finding] = []

    if _table_exists(conn, "workout_log") and _table_exists(conn, "active_workout_session"):
        n = conn.execute(text("""
            SELECT COUNT(*) FROM workout_log w
            WHERE w.active_session_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM active_workout_session s
                              WHERE s.id = w.active_session_id)
        """)).scalar()
        if n:
            out.append(Finding(
                check="dangling_active_session",
                severity="review", count=int(n),
                detail=f"{n} workout_log rows name an active_workout_session that is gone.",
            ))
        cross = conn.execute(text("""
            SELECT COUNT(*) FROM workout_log w
            JOIN active_workout_session s ON s.id = w.active_session_id
            WHERE s.user_id <> w.user_id
        """)).scalar()
        if cross:
            out.append(Finding(
                check="cross_owner_session_reference",
                severity="block", count=int(cross),
                detail=(
                    f"{cross} workout_log rows belong to a different athlete "
                    "than the session they are attached to. This must be "
                    "resolved before any analytics treat sessions as owned."
                ),
            ))

    if _table_exists(conn, "workout_log") and _table_exists(conn, "exercise_library"):
        n = conn.execute(text("""
            SELECT COUNT(*) FROM workout_log w
            WHERE w.exercise_library_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM exercise_library e
                              WHERE e.id = w.exercise_library_id)
        """)).scalar()
        if n:
            out.append(Finding(
                check="dangling_canonical_exercise",
                severity="review", count=int(n),
                detail=f"{n} workout_log rows name a missing exercise_library row.",
            ))
        unresolved = conn.execute(text("""
            SELECT COUNT(*) FROM workout_log
            WHERE exercise_library_id IS NULL AND exercise_id IS NOT NULL
        """)).scalar()
        if unresolved:
            out.append(Finding(
                check="unresolved_exercise_identity",
                severity="note", count=int(unresolved),
                detail=(
                    f"{unresolved} sets carry only legacy text exercise_id with no "
                    "canonical shadow FK. They stay flagged unresolved — a fuzzy "
                    "name match must never silently merge two people's PR history."
                ),
            ))

    if _table_exists(conn, "template_exercise") and _table_exists(conn, "fitness_template"):
        n = conn.execute(text("""
            SELECT COUNT(*) FROM template_exercise te
            WHERE NOT EXISTS (SELECT 1 FROM fitness_template t WHERE t.id = te.template_id)
        """)).scalar()
        if n:
            out.append(Finding(
                check="dangling_template_exercise",
                severity="review", count=int(n),
                detail=f"{n} template_exercise rows name a missing template.",
            ))

    if _table_exists(conn, "workout_session") and _table_exists(conn, "active_workout_session"):
        cross = conn.execute(text("""
            SELECT COUNT(*) FROM workout_session p
            JOIN active_workout_session a ON a.id = p.active_session_id
            WHERE a.user_id <> p.user_id
        """)).scalar()
        if cross:
            out.append(Finding(
                check="cross_owner_session_link",
                severity="block", count=int(cross),
                detail=f"{cross} planned sessions link to another athlete's active session.",
            ))

    return out


def audit_exercise_library_scope(conn) -> List[Finding]:
    """Which `exercise_library` rows can be proven global.

    The table has no owner column. `exercise_library_seed.py` derived rows
    from names that already appeared in logs, so a row's provenance is only
    knowable from who has actually used it. One user → private. Several users
    → shared, which is *not* the same as public and stays restricted until
    reviewed.
    """
    if not (_table_exists(conn, "exercise_library") and _table_exists(conn, "workout_log")):
        return []
    rows = conn.execute(text("""
        WITH usage AS (
            SELECT e.id, COUNT(DISTINCT w.user_id) AS users
            FROM exercise_library e
            LEFT JOIN workout_log w
              ON w.exercise_library_id = e.id
              OR LOWER(TRIM(w.exercise_id)) = LOWER(TRIM(e.name))
            GROUP BY e.id
        )
        SELECT
          COUNT(*) FILTER (WHERE users = 0) AS unused,
          COUNT(*) FILTER (WHERE users = 1) AS single_user,
          COUNT(*) FILTER (WHERE users > 1) AS multi_user
        FROM usage
    """)).fetchone()
    if not rows:
        return []
    return [
        Finding(
            check="exercise_scope:unused",
            severity="note", count=int(rows.unused or 0),
            detail=(
                f"{rows.unused} exercise_library rows nobody has logged. "
                "Unused rows carry no private history, so they are the safe "
                "candidates for a reviewed global seed."
            ),
        ),
        Finding(
            check="exercise_scope:single_user",
            severity="review", count=int(rows.single_user or 0),
            detail=(
                f"{rows.single_user} rows used by exactly one athlete. Treated "
                "as that athlete's private variant: publishing them globally "
                "would expose a user-created exercise name."
            ),
        ),
        Finding(
            check="exercise_scope:multi_user",
            severity="review", count=int(rows.multi_user or 0),
            detail=(
                f"{rows.multi_user} rows used by several athletes — shared, not "
                "proven public. Stays restricted/unresolved pending review."
            ),
        ),
    ]


def audit_target_history(conn) -> List[Finding]:
    """How much target history is provable at all.

    `fitness_goals` columns default to 2000/150/200/70. A row sitting at the
    defaults is not evidence that anyone chose them, and a backfill must not
    assert today's macros applied for all past months.
    """
    out: List[Finding] = []
    if _table_exists(conn, "fitness_goals"):
        n = conn.execute(text("""
            SELECT COUNT(*) FROM fitness_goals
            WHERE calories = 2000 AND protein = 150 AND carbs = 200 AND fats = 70
        """)).scalar()
        if n:
            out.append(Finding(
                check="target_history_unprovable",
                severity="note", count=int(n),
                detail=(
                    f"{n} fitness_goals rows sit exactly on the column defaults. "
                    "Seeded revisions mark dates before the first provable "
                    "target as history_unknown rather than claiming these."
                ),
            ))
    if _table_exists(conn, "fitness_phase"):
        n = conn.execute(text("""
            SELECT COUNT(*) FROM fitness_phase
            WHERE calories_target IS NULL AND calories_training_day IS NULL
              AND calories_rest_day IS NULL
        """)).scalar()
        if n:
            out.append(Finding(
                check="phase_without_targets",
                severity="note", count=int(n),
                detail=f"{n} phases carry no calorie target of any kind; resolves to unknown.",
            ))
    return out


def run_audit(url: str) -> List[Finding]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            findings: List[Finding] = []
            findings += audit_orphan_owners(conn)
            findings += audit_duplicate_active_programs(conn)
            findings += audit_overlapping_phases(conn)
            findings += audit_unit_ambiguity(conn)
            findings += audit_dangling_references(conn)
            findings += audit_exercise_library_scope(conn)
            findings += audit_target_history(conn)
            return findings
    finally:
        engine.dispose()


def apply_mapping(url: str, mapping_path: str, *, dry_run: bool) -> Dict[str, Any]:
    """Reassign owners from an explicit reviewed mapping, and nothing else.

    The mapping file is `{"<old user_id>": "<app_user.id>"}`. Every target
    must already exist as an `app_user`; every source must appear in the
    audit as an orphan. Anything else is refused — this is not a general
    "move rows between users" tool.

    Idempotent: a second run finds nothing left to move, because the source
    ids no longer match. That is what makes it resumable after a failure.
    """
    with open(mapping_path, "r", encoding="utf-8") as fh:
        mapping = json.load(fh)
    if not isinstance(mapping, dict) or not mapping:
        raise SystemExit("mapping must be a non-empty object of old_id -> app_user.id")

    engine = create_engine(url)
    report: Dict[str, Any] = {"dry_run": dry_run, "tables": {}, "mapping": {}}
    try:
        with engine.begin() as conn:
            for old, new in mapping.items():
                if not isinstance(old, str) or not isinstance(new, str) or not new:
                    raise SystemExit("mapping entries must be non-empty strings")
                exists = conn.execute(text(
                    "SELECT 1 FROM app_user WHERE id = :id"), {"id": new}).fetchone()
                if not exists:
                    raise SystemExit(
                        f"refusing: mapping target {new!r} is not an app_user. "
                        "An orphan with no real destination stays quarantined."
                    )
                still_orphan = conn.execute(text(
                    "SELECT 1 FROM app_user WHERE id = :id"), {"id": old}).fetchone()
                if still_orphan:
                    raise SystemExit(
                        f"refusing: source {old!r} IS a real app_user. This tool "
                        "only resolves orphans, it does not move owned rows."
                    )
                report["mapping"][old] = new

            for table in OWNED_TABLES:
                if not _table_exists(conn, table):
                    continue
                moved = 0
                for old, new in mapping.items():
                    n = conn.execute(text(
                        f"SELECT COUNT(*) FROM {table} WHERE user_id = :old"
                    ), {"old": old}).scalar()
                    if not n:
                        continue
                    if not dry_run:
                        conn.execute(text(
                            f"UPDATE {table} SET user_id = :new WHERE user_id = :old"
                        ), {"new": new, "old": old})
                    moved += int(n)
                if moved:
                    report["tables"][table] = moved
            if dry_run:
                conn.rollback()
    finally:
        engine.dispose()
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--database-url", required=True,
                    help="explicit target; there is deliberately no env default")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument("--apply", action="store_true",
                    help="perform a reviewed reassignment (requires --mapping and --yes)")
    ap.add_argument("--mapping", help="reviewed {old_id: app_user.id} JSON file")
    ap.add_argument("--yes", action="store_true", help="confirm a non-dry-run apply")
    args = ap.parse_args()

    if args.apply:
        if not args.mapping:
            print("--apply requires --mapping with a reviewed mapping file", file=sys.stderr)
            return 2
        dry = not args.yes
        report = apply_mapping(args.database_url, args.mapping, dry_run=dry)
        print(json.dumps(report, indent=2))
        if dry:
            print("\nDRY RUN — nothing was written. Re-run with --yes to apply.",
                  file=sys.stderr)
        return 0

    findings = run_audit(args.database_url)
    if args.json:
        print(json.dumps([f.as_dict() for f in findings], indent=2))
    else:
        if not findings:
            print("No fitness ownership or consistency conflicts found.")
        blocking = [f for f in findings if f.severity == "block"]
        for severity, label in (("block", "BLOCKING"), ("review", "NEEDS REVIEW"),
                                ("note", "NOTE")):
            group = [f for f in findings if f.severity == severity]
            if not group:
                continue
            print(f"\n=== {label} ===")
            for f in group:
                print(f"  [{f.check}] {f.detail}")
                if f.sample_ids:
                    print(f"      sample ids: {', '.join(f.sample_ids[:5])}")
        print(
            "\nNothing was changed. Orphans and ambiguous rows stay quarantined; "
            "they do not block new owned records."
        )
        if blocking:
            print(
                f"\n{len(blocking)} BLOCKING finding(s): cross-owner references must "
                "be resolved before analytics treat these rows as owned.",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
