#!/usr/bin/env python3
"""
Post-import edits for the Two-A-Day Powerbuilding Recomp program
(HRV_PIPELINE_AND_TWO_A_DAY_PROGRAM_2026_09_14 §B3).

`apply_imported_plan` copies the same templates into every phase, which is right
for the three build-style phases and wrong for the deload. This differentiates
them after the fact:

  1. Deload (Week 4) — PM templates drop to ~50% of their sets and back off to
     3-4 RIR; AM exercises take the deload row of their own loading table.
  2. Rep PR (Week 8) — AM exercise notes lead with that week's rep-PR target.
  3. cardio_settings — the spec's 10-15 min post-AM-lift cardio, 2-4 mornings a
     week, replaces The Forge's 90-120 min/wk.

Idempotent: every edit is marked and re-running skips what is already done.
It operates on the active program, so it cannot touch archived history.

  docker compose exec -T backend python scripts/plans/postprocess_two_a_day_2026_09_14.py [--dry-run]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import text  # noqa: E402

USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"
DELOAD_PHASE = "Deload (Week 4)"
REP_PR_PHASE = "Rep PR (Week 8)"

DELOAD_MARK = "DELOAD WEEK: "
REP_PR_MARK = "REP PR WEEK — "

# The deload row of each AM lift's own loading table (spec §6, Weeks 1-8 and
# Backoff Loads). "210 × 5 × 2" reads load × reps × sets.
DELOAD_AM = {
    "Newtech Flat":       {"sets": 3, "reps": "4-5", "top": "230x4", "backoff": "210x5 x2 sets"},
    "Deadlift":           {"sets": 3, "reps": "2-3", "top": "285x2", "backoff": "250x3 x1-2 sets"},
    "Smith Machine Press": {"sets": 3, "reps": "4-5", "top": "125x4", "backoff": "115x5 x2 sets"},
    "Back Squat":         {"sets": 3, "reps": "3-5", "top": "205x3", "backoff": "180x5 x2 sets"},
}

# Rep-PR targets (spec §6, Week 8 row). Backoffs from the Backoff Loads table.
REP_PR_AM = {
    "Newtech Flat":       "270x5 target, backoffs 235x4-6 x3",
    "Deadlift":           "325x3 target, backoffs 280x3-5 x2",
    "Smith Machine Press": "155x4+ target, backoffs 140x4-6 x3",
    "Back Squat":         "230x4+ target, backoffs 205x4-6 x3",
}

# RPE under a deload: 3-4 RIR. The build-phase 8 (compounds, 1-2 RIR) and 9
# (isolation, 0-2 RIR) map to 6 and 7 — both inside the 6-7 band, and the
# relative ordering of compound vs isolation effort is preserved.
DELOAD_RPE = {8: 6.0, 9: 7.0}

CARDIO_MENU_ITEM = {
    "key": "stairs",
    "label": "StairMaster / incline walk — after AM lift",
    "typical_minutes": 12,
    "worth_minutes": 12,
    "note": "2–4 mornings/wk, easy-moderate. Never before the lift; no hard intervals around Tue/Thu.",
}


def _load(raw):
    return json.loads(raw) if isinstance(raw, str) else (raw or [])


def deload_templates(db, phase_id, dry):
    rows = db.execute(text("""
        SELECT id, name, exercises FROM fitness_template
        WHERE phase_id = :pid ORDER BY order_in_phase
    """), {"pid": phase_id}).fetchall()

    changed = 0
    for r in rows:
        exercises = _load(r.exercises)
        if not exercises:
            continue
        is_am = " AM — " in r.name
        touched = False

        for ex in exercises:
            notes = ex.get("notes") or ""
            if notes.startswith(DELOAD_MARK):
                continue  # already processed

            if is_am:
                spec = DELOAD_AM.get(ex.get("name"))
                if not spec:
                    print(f"  !! no deload row for AM exercise {ex.get('name')!r} — left alone")
                    continue
                ex["sets"] = spec["sets"]
                ex["reps"] = spec["reps"]
                ex["notes"] = (f"{DELOAD_MARK}top set {spec['top']}, backoff {spec['backoff']}. "
                               f"Stay well under RPE 8 — this week exists to recover.\n{notes}")
            else:
                ex["sets"] = max(1, int(ex.get("sets") or 1) // 2)
                rpe = ex.get("rpe_target")
                ex["rpe_target"] = DELOAD_RPE.get(int(rpe), 6.0) if rpe else 6.0
                ex["notes"] = f"{DELOAD_MARK}~50% of the usual sets, 3-4 RIR.\n{notes}"
            touched = True

        if touched:
            changed += 1
            print(f"  {r.name}: {'AM deload loads' if is_am else 'sets halved, 3-4 RIR'}")
            if not dry:
                db.execute(text(
                    "UPDATE fitness_template SET exercises = :ex, updated_at = now() WHERE id = :id"),
                    {"ex": json.dumps(exercises), "id": r.id})
    return changed


def rep_pr_templates(db, phase_id, dry):
    rows = db.execute(text("""
        SELECT id, name, exercises FROM fitness_template
        WHERE phase_id = :pid AND name LIKE '%% AM —%%' ORDER BY order_in_phase
    """), {"pid": phase_id}).fetchall()

    changed = 0
    for r in rows:
        exercises = _load(r.exercises)
        touched = False
        for ex in exercises:
            notes = ex.get("notes") or ""
            if notes.startswith(REP_PR_MARK):
                continue
            target = REP_PR_AM.get(ex.get("name"))
            if not target:
                print(f"  !! no rep-PR target for {ex.get('name')!r} — left alone")
                continue
            ex["notes"] = (f"{REP_PR_MARK}targets: {target}. Controlled rep PR at a familiar "
                           f"load — no true max testing.\n{notes}")
            touched = True
        if touched:
            changed += 1
            print(f"  {r.name}: rep-PR targets prepended")
            if not dry:
                db.execute(text(
                    "UPDATE fitness_template SET exercises = :ex, updated_at = now() WHERE id = :id"),
                    {"ex": json.dumps(exercises), "id": r.id})
    return changed


def cardio_settings(db, dry):
    row = db.execute(text("""
        SELECT weekly_min_minutes, weekly_max_minutes, steps_floor, menu
        FROM cardio_settings WHERE user_id = :uid
    """), {"uid": USER_ID}).fetchone()
    if not row:
        print("  !! no cardio_settings row — skipped")
        return 0

    # Copy: a `json` column comes back already parsed, so `_load` would hand
    # back the row's own list and appending would mutate it under us.
    menu = list(_load(row.menu))
    before = len(menu)
    if not any(m.get("key") == CARDIO_MENU_ITEM["key"] for m in menu):
        menu.append(CARDIO_MENU_ITEM)

    print(f"  {row.weekly_min_minutes}-{row.weekly_max_minutes} min/wk → 30-60; "
          f"steps_floor {row.steps_floor} kept; menu items {before} → {len(menu)} "
          f"({', '.join(m.get('key', '?') for m in menu)})")
    if not dry:
        db.execute(text("""
            UPDATE cardio_settings
            SET weekly_min_minutes = 30, weekly_max_minutes = 60, menu = CAST(:menu AS json),
                updated_at = now()
            WHERE user_id = :uid
        """), {"uid": USER_ID, "menu": json.dumps(menu)})
    return 1


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

        phases = {r.name: r.id for r in db.execute(text(
            "SELECT id, name FROM fitness_phase WHERE program_id = :pid"), {"pid": program_id})}
        for needed in (DELOAD_PHASE, REP_PR_PHASE):
            if needed not in phases:
                print(f"FAILED: phase {needed!r} not found", file=sys.stderr)
                return 1

        print(f"1. {DELOAD_PHASE}")
        n1 = deload_templates(db, phases[DELOAD_PHASE], args.dry_run)
        print(f"\n2. {REP_PR_PHASE}")
        n2 = rep_pr_templates(db, phases[REP_PR_PHASE], args.dry_run)
        print("\n3. cardio_settings")
        n3 = cardio_settings(db, args.dry_run)

        if args.dry_run:
            db.rollback()
            print(f"\n--dry-run: nothing written ({n1} deload, {n2} rep-PR templates, {n3} cardio).")
        else:
            db.commit()
            print(f"\nCommitted: {n1} deload templates, {n2} rep-PR templates, {n3} cardio settings.")
        return 0
    except Exception as e:
        db.rollback()
        print(f"FAILED ({type(e).__name__}): {e}", file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
