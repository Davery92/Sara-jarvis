#!/usr/bin/env python3
"""
Add per-set `set_plan` (top/backoff loading table) to the 4 AM lifts of the
Two-A-Day Powerbuilding Recomp program (TWO_A_DAY_AM_SETS_AND_FOOD_REPEAT_PLAN
Part A1).

The importer only ever wrote `sets` / `reps` / `notes` on each AM exercise,
with the 8-week loading table as a text blob in `notes`. This adds a
structured `set_plan` key (additive — no other key is touched) so the workout
engine can resolve real per-set targets instead of one flat suggested_weight.

Numbers are hand-typed from the source of truth, not LLM-derived:
  - `backend/scripts/plans/two_a_day_2026_09_14.json` (weeks 1-3, 5-7 build
    rows + warm-ups, already-applied exercise notes)
  - `backend/scripts/plans/postprocess_two_a_day_2026_09_14.py` (DELOAD_AM,
    REP_PR_AM — the week 4 and week 8 rows)

Idempotent: skips any exercise that already carries a `set_plan` key. Touches
every phase's copy of each AM exercise (apply_imported_plan copies the same
weekly templates into every phase), so a full 1-8 week table lands on all 16
rows (4 lifts x 4 phases) regardless of which phase's copy resolves a given
program week at runtime.

  docker compose exec -T backend python scripts/plans/add_set_plan_two_a_day.py [--dry-run]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import text  # noqa: E402

USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

# One entry per AM lift. `top`/`backoff` weeks are program weeks (1-8),
# matching workout_prescription.program_week(). `sets` on backoff is the
# number of backoff sets for that week (1 top set is always separate).
SET_PLANS = {
    "Newtech Flat": {
        "kind": "top_backoff",
        "warmup": [{"weight": 90, "reps": 10}, {"weight": 180, "reps": 5}, {"weight": 230, "reps": 2}],
        "weeks": {
            "1": {"top": {"weight": 270, "reps": "2", "rpe_cap": 8},
                  "backoff": {"weight": 230, "reps": "4-6", "sets": 3, "rir": "1-2"}},
            "2": {"top": {"weight": 270, "reps": "3", "rpe_cap": 8},
                  "backoff": {"weight": 230, "reps": "4-6", "sets": 3, "rir": "1-2"}},
            "3": {"top": {"weight": 270, "reps": "4", "rpe_cap": 8},
                  "backoff": {"weight": 240, "reps": "4-6", "sets": 3, "rir": "1-2"}},
            "4": {"label": "DELOAD",
                  "top": {"weight": 230, "reps": "4"},
                  "backoff": {"weight": 210, "reps": "5", "sets": 2}},
            "5": {"top": {"weight": 280, "reps": "2", "rpe_cap": 8},
                  "backoff": {"weight": 240, "reps": "4-6", "sets": 3, "rir": "1-2"}},
            "6": {"top": {"weight": 280, "reps": "3", "rpe_cap": 8},
                  "backoff": {"weight": 250, "reps": "4-6", "sets": 3, "rir": "1-2"}},
            "7": {"top": {"weight": 280, "reps": "4", "rpe_cap": 8},
                  "backoff": {"weight": 250, "reps": "4-6", "sets": 3, "rir": "1-2"}},
            "8": {"label": "REP PR",
                  "top": {"weight": 270, "reps": "5"},
                  "backoff": {"weight": 235, "reps": "4-6", "sets": 3, "rir": "1-2"}},
        },
        "advance_rule": "clean_top_set_rpe_le_8",
    },
    "Deadlift": {
        "kind": "top_backoff",
        "warmup": [{"weight": 135, "reps": 5}, {"weight": 185, "reps": 3},
                   {"weight": 225, "reps": 2}, {"weight": 275, "reps": 1}],
        "weeks": {
            "1": {"top": {"weight": 315, "reps": "1-3", "rpe_cap": 8},
                  "backoff": {"weight": 275, "reps": "3-5", "sets": 2}},
            "2": {"top": {"weight": 320, "reps": "1-3", "rpe_cap": 8},
                  "backoff": {"weight": 280, "reps": "3-5", "sets": 2}},
            "3": {"top": {"weight": 325, "reps": "1-3", "rpe_cap": 8},
                  "backoff": {"weight": 285, "reps": "3-5", "sets": 2}},
            "4": {"label": "DELOAD",
                  "top": {"weight": 285, "reps": "2"},
                  "backoff": {"weight": 250, "reps": "3", "sets": 2}},
            "5": {"top": {"weight": 330, "reps": "1-3", "rpe_cap": 8},
                  "backoff": {"weight": 290, "reps": "3-5", "sets": 2}},
            "6": {"top": {"weight": 335, "reps": "1-3", "rpe_cap": 8},
                  "backoff": {"weight": 295, "reps": "3-5", "sets": 2}},
            "7": {"top": {"weight": 340, "reps": "1-2", "rpe_cap": 8},
                  "backoff": {"weight": 300, "reps": "3-5", "sets": 2}},
            "8": {"label": "REP PR",
                  "top": {"weight": 325, "reps": "3"},
                  "backoff": {"weight": 280, "reps": "3-5", "sets": 2}},
        },
        "advance_rule": "clean_top_set_rpe_le_8",
    },
    "Smith Machine Press": {
        "kind": "top_backoff",
        "warmup": [{"weight": 65, "reps": 8}, {"weight": 95, "reps": 5},
                   {"weight": 115, "reps": 3}, {"weight": 135, "reps": 1}],
        "weeks": {
            "1": {"top": {"weight": 145, "reps": "2-4", "rpe_cap": 8},
                  "backoff": {"weight": 130, "reps": "4-6", "sets": 3, "rir": "1-2"}},
            "2": {"top": {"weight": 150, "reps": "2-4", "rpe_cap": 8},
                  "backoff": {"weight": 135, "reps": "4-6", "sets": 3, "rir": "1-2"}},
            "3": {"top": {"weight": 155, "reps": "2-4", "rpe_cap": 8},
                  "backoff": {"weight": 140, "reps": "4-6", "sets": 3, "rir": "1-2"}},
            "4": {"label": "DELOAD",
                  "top": {"weight": 125, "reps": "4"},
                  "backoff": {"weight": 115, "reps": "5", "sets": 2}},
            "5": {"top": {"weight": 155, "reps": "2-4", "rpe_cap": 8},
                  "backoff": {"weight": 140, "reps": "4-6", "sets": 3, "rir": "1-2"}},
            "6": {"top": {"weight": 160, "reps": "2-4", "rpe_cap": 8},
                  "backoff": {"weight": 145, "reps": "4-6", "sets": 3, "rir": "1-2"}},
            "7": {"top": {"weight": 165, "reps": "1-3", "rpe_cap": 8},
                  "backoff": {"weight": 150, "reps": "4-6", "sets": 3, "rir": "1-2"}},
            "8": {"label": "REP PR",
                  "top": {"weight": 155, "reps": "4+"},
                  "backoff": {"weight": 140, "reps": "4-6", "sets": 3, "rir": "1-2"}},
        },
        "advance_rule": "clean_top_set_rpe_le_8",
    },
    "Back Squat": {
        "kind": "top_backoff",
        "warmup": [{"weight": 45, "reps": 8}, {"weight": 135, "reps": 5},
                   {"weight": 185, "reps": 3}, {"weight": 205, "reps": 1}],
        "weeks": {
            "1": {"top": {"weight": 225, "reps": "2-4", "rpe_cap": 8},
                  "backoff": {"weight": 200, "reps": "4-6", "sets": 3, "rir": "1-2"}},
            "2": {"top": {"weight": 230, "reps": "2-4", "rpe_cap": 8},
                  "backoff": {"weight": 205, "reps": "4-6", "sets": 3, "rir": "1-2"}},
            "3": {"top": {"weight": 235, "reps": "2-4", "rpe_cap": 8},
                  "backoff": {"weight": 210, "reps": "4-6", "sets": 3, "rir": "1-2"}},
            "4": {"label": "DELOAD",
                  "top": {"weight": 205, "reps": "3"},
                  "backoff": {"weight": 180, "reps": "5", "sets": 2}},
            "5": {"top": {"weight": 235, "reps": "2-4", "rpe_cap": 8},
                  "backoff": {"weight": 210, "reps": "4-6", "sets": 3, "rir": "1-2"}},
            "6": {"top": {"weight": 240, "reps": "2-4", "rpe_cap": 8},
                  "backoff": {"weight": 215, "reps": "4-6", "sets": 3, "rir": "1-2"}},
            "7": {"top": {"weight": 245, "reps": "1-3", "rpe_cap": 8},
                  "backoff": {"weight": 220, "reps": "4-6", "sets": 3, "rir": "1-2"}},
            "8": {"label": "REP PR",
                  "top": {"weight": 230, "reps": "4+"},
                  "backoff": {"weight": 205, "reps": "4-6", "sets": 3, "rir": "1-2"}},
        },
        "advance_rule": "clean_top_set_rpe_le_8",
    },
}


def _load(raw):
    return json.loads(raw) if isinstance(raw, str) else (raw or [])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        program = db.execute(text("""
            SELECT id, name FROM fitness_program WHERE user_id = :uid AND is_active = true
        """), {"uid": USER_ID}).fetchall()
        if len(program) != 1:
            print(f"FAILED: expected exactly 1 active program, found {len(program)}", file=sys.stderr)
            return 1
        program_id, program_name = program[0].id, program[0].name
        print(f"Active program: {program_name}\n")

        phase_ids = [r.id for r in db.execute(text(
            "SELECT id FROM fitness_phase WHERE program_id = :pid"), {"pid": program_id})]

        rows = db.execute(text("""
            SELECT id, name, exercises FROM fitness_template
            WHERE phase_id = ANY(:pids)
        """), {"pids": phase_ids}).fetchall()

        changed = 0
        touched_names = set()
        for r in rows:
            exercises = _load(r.exercises)
            if not exercises:
                continue
            row_touched = False
            for ex in exercises:
                name = ex.get("name")
                plan = SET_PLANS.get(name)
                if not plan:
                    continue
                if ex.get("set_plan"):
                    continue  # idempotent — already has one
                ex["set_plan"] = plan
                row_touched = True
                touched_names.add(name)
            if row_touched:
                changed += 1
                print(f"  {r.name}: set_plan added")
                if not args.dry_run:
                    db.execute(text(
                        "UPDATE fitness_template SET exercises = :ex, updated_at = now() WHERE id = :id"),
                        {"ex": json.dumps(exercises), "id": r.id})

        if args.dry_run:
            db.rollback()
            print(f"\n--dry-run: nothing written ({changed} template rows would change).")
            return 0

        db.commit()
        print(f"\nCommitted: {changed} template rows updated. Lifts touched: {sorted(touched_names)}")

        # Verify: every AM template exercise in every phase has a full 1-8 week table.
        verify_rows = db.execute(text("""
            SELECT ft.name AS template_name, fp.name AS phase_name, ft.exercises
            FROM fitness_template ft
            JOIN fitness_phase fp ON fp.id = ft.phase_id
            WHERE ft.phase_id = ANY(:pids) AND ft.name LIKE '%% AM —%%'
        """), {"pids": phase_ids}).fetchall()
        missing = []
        for r in verify_rows:
            for ex in _load(r.exercises):
                if ex.get("name") not in SET_PLANS:
                    continue
                weeks = ((ex.get("set_plan") or {}).get("weeks") or {})
                have = set(weeks.keys())
                want = {str(i) for i in range(1, 9)}
                if have != want:
                    missing.append((r.phase_name, r.template_name, ex.get("name"), sorted(want - have)))
        if missing:
            print(f"\nVERIFY FAILED — {len(missing)} exercise(s) missing week entries:")
            for phase_name, template_name, ex_name, weeks in missing:
                print(f"  {phase_name} / {template_name} / {ex_name}: missing weeks {weeks}")
            return 2
        print(f"\nVerify OK: all {len(verify_rows)} AM template rows carry set_plan.weeks[\"1\".\"8\"] for their plan-driven lift.")
        return 0
    except Exception as e:
        db.rollback()
        print(f"FAILED ({type(e).__name__}): {e}", file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
