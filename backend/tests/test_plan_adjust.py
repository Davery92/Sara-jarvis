"""plan_adjust tests (docs/plans/FITNESS_PLAN_CONTROL_2026_08_17.md, Phase 2).

Same rules as test_workout_flexible_sets.py: real PostgreSQL, because the
properties under test — date-range collisions, FK-cascaded programs/phases,
and phase_resolution's ORDER BY tie-breaking — are ones SQLite would fake.

    docker compose -f docker-compose.dev.yml exec -T backend \\
        pytest tests/test_plan_adjust.py
"""

import os
import uuid
from datetime import date

import pytest
from sqlalchemy import text
from tests.conftest import WORLD_MODEL_CLEANUP_STATEMENTS

pytestmark = pytest.mark.integration


def _pg_available() -> bool:
    return os.getenv("DATABASE_URL", "").startswith("postgresql")


requires_pg = pytest.mark.skipif(
    not _pg_available(), reason="needs the PostgreSQL dev database (run inside the backend container)"
)


@pytest.fixture
def pg():
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def user_id(pg):
    uid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO app_user (id, email, password_hash) VALUES (:id, :email, 'x')
    """), {"id": uid, "email": f"planadjust-{uid}@example.invalid"})
    pg.commit()
    yield uid
    for stmt in (
        "DELETE FROM fitness_template WHERE user_id = :uid",
        "DELETE FROM fitness_phase WHERE user_id = :uid",
        "DELETE FROM fitness_program WHERE user_id = :uid",
        # Every world event this fixture's services emitted is keyed by the
        # throwaway user; without this the dev DB accumulates orphans.
        *WORLD_MODEL_CLEANUP_STATEMENTS,
        "DELETE FROM app_user WHERE id = :uid",
    ):
        try:
            pg.execute(text(stmt), {"uid": uid})
            pg.commit()
        except Exception:
            pg.rollback()


def _program(pg, user_id, *, start="2026-01-01", end="2026-04-30"):
    pid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_program (id, user_id, name, goal, start_date, end_date, is_active)
        VALUES (:id, :uid, 'Test Program', 'recomp', :start, :end, true)
    """), {"id": pid, "uid": user_id, "start": start, "end": end})
    pg.commit()
    return pid


def _phase(pg, user_id, program_id, *, name, start, end, order_index=0,
           calories_target=2400, status="planned"):
    phid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_phase (id, user_id, program_id, name, goal, order_index,
            start_date, end_date, status, calories_target)
        VALUES (:id, :uid, :pid, :name, 'hypertrophy', :oi, :start, :end, :status, :cal)
    """), {"id": phid, "uid": user_id, "pid": program_id, "name": name, "oi": order_index,
           "start": start, "end": end, "status": status, "cal": calories_target})
    pg.commit()
    return phid


def _template(pg, user_id, phase_id, *, name="Upper A"):
    tid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_template (id, user_id, phase_id, name, scheduled_days, exercises)
        VALUES (:id, :uid, :pid, :name, '["monday"]', '[{"name": "Bench Press", "sets": 3, "reps": "8"}]')
    """), {"id": tid, "uid": user_id, "pid": phase_id, "name": name})
    pg.commit()
    return tid


def _fetch_phase(pg, phase_id):
    row = pg.execute(text("""
        SELECT id, name, status, start_date, end_date, calories_target,
               calories_training_day, calories_rest_day
        FROM fitness_phase WHERE id = :id
    """), {"id": phase_id}).fetchone()
    return dict(row._mapping) if row else None


# ──────────────────────────────────────────────────────────────────────────

@requires_pg
def test_insert_phase_block_requires_active_program(pg, user_id):
    from app.services.plan_adjust import insert_phase_block

    with pytest.raises(ValueError, match="No active program"):
        insert_phase_block(
            pg, user_id, name="Cut", goal="cut",
            start_date=date(2026, 1, 15), duration_weeks=2,
        )


@requires_pg
def test_overlay_block_inside_one_phase_splits_it(pg, user_id):
    from app.services.plan_adjust import insert_phase_block

    program_id = _program(pg, user_id)
    phase_id = _phase(pg, user_id, program_id, name="Hypertrophy Block",
                       start="2026-01-01", end="2026-02-28", calories_target=2800)
    _template(pg, user_id, phase_id)

    summary = insert_phase_block(
        pg, user_id, name="Cut", goal="cut",
        start_date=date(2026, 1, 15), end_date=date(2026, 1, 21),
        nutrition={"calories_training_day": 2300, "calories_rest_day": 1900},
    )
    pg.commit()

    assert summary["mode"] == "overlay"
    assert summary["start_date"] == "2026-01-15"
    assert summary["end_date"] == "2026-01-21"
    assert summary["split_phase_id"] is not None
    # the block's own templates were copied from the phase effective the day before
    assert summary["templates_copied"] == 1

    original = _fetch_phase(pg, phase_id)
    assert original["end_date"].isoformat() == "2026-01-14"

    post = _fetch_phase(pg, summary["split_phase_id"])
    assert post["start_date"].isoformat() == "2026-01-22"
    assert post["end_date"].isoformat() == "2026-02-28"
    assert post["calories_target"] == 2800  # cloned from the original phase

    block = _fetch_phase(pg, summary["block_phase_id"])
    assert block["calories_training_day"] == 2300
    assert block["calories_rest_day"] == 1900
    assert "Cut" in block["name"] and "Jan 15" in block["name"]

    # the post-split continuation got its own copy of the original's template
    post_templates = pg.execute(text(
        "SELECT COUNT(*) FROM fitness_template WHERE phase_id = :pid"
    ), {"pid": summary["split_phase_id"]}).scalar()
    assert post_templates == 1


@requires_pg
def test_overlay_straddles_two_phases_trims_both(pg, user_id):
    from app.services.plan_adjust import insert_phase_block

    program_id = _program(pg, user_id)
    phase_a = _phase(pg, user_id, program_id, name="Phase A", order_index=0,
                      start="2026-01-01", end="2026-01-14")
    phase_b = _phase(pg, user_id, program_id, name="Phase B", order_index=1,
                      start="2026-01-15", end="2026-01-28")

    summary = insert_phase_block(
        pg, user_id, name="Cut", goal="cut",
        start_date=date(2026, 1, 10), end_date=date(2026, 1, 20),
    )
    pg.commit()

    assert len(summary["trimmed_phases"]) == 2
    a = _fetch_phase(pg, phase_a)
    b = _fetch_phase(pg, phase_b)
    assert a["end_date"].isoformat() == "2026-01-09"
    assert b["start_date"].isoformat() == "2026-01-21"


@requires_pg
def test_push_mode_shifts_later_phases(pg, user_id):
    from app.services.plan_adjust import insert_phase_block

    program_id = _program(pg, user_id, end="2026-01-28")
    phase_a = _phase(pg, user_id, program_id, name="Phase A", order_index=0,
                      start="2026-01-01", end="2026-01-14")
    phase_b = _phase(pg, user_id, program_id, name="Phase B", order_index=1,
                      start="2026-01-15", end="2026-01-28")

    summary = insert_phase_block(
        pg, user_id, name="Cut", goal="cut", mode="push",
        start_date=date(2026, 1, 8), duration_weeks=1,
    )
    pg.commit()

    assert summary["mode"] == "push"
    a = _fetch_phase(pg, phase_a)
    assert a["end_date"].isoformat() == "2026-01-07"  # trimmed, not shifted

    b = _fetch_phase(pg, phase_b)
    assert b["start_date"].isoformat() == "2026-01-22"  # shifted by 7 days
    assert b["end_date"].isoformat() == "2026-02-04"

    prog = pg.execute(text(
        "SELECT end_date FROM fitness_program WHERE id = :id"
    ), {"id": program_id}).fetchone()
    assert prog.end_date.isoformat() == "2026-02-04"


@requires_pg
def test_effective_phase_resolves_block_then_falls_back_after(pg, user_id):
    from app.services.plan_adjust import insert_phase_block
    from app.services.phase_resolution import get_effective_phase

    program_id = _program(pg, user_id)
    phase_id = _phase(pg, user_id, program_id, name="Hypertrophy Block",
                       start="2026-01-01", end="2026-02-28", calories_target=2800)

    summary = insert_phase_block(
        pg, user_id, name="Cut", goal="cut",
        start_date=date(2026, 1, 15), end_date=date(2026, 1, 21),
        nutrition={"calories_training_day": 2300, "calories_rest_day": 1900},
    )
    pg.commit()

    inside = get_effective_phase(pg, user_id, date(2026, 1, 18))
    assert inside["id"] == summary["block_phase_id"]
    assert inside["calories_training_day"] == 2300

    after = get_effective_phase(pg, user_id, date(2026, 2, 1))
    assert after["id"] == summary["split_phase_id"]
    assert after["calories_target"] == 2800

    before = get_effective_phase(pg, user_id, date(2026, 1, 5))
    assert before["id"] == phase_id


@requires_pg
def test_end_phase_block_early_restores_neighbor_start(pg, user_id):
    from app.services.plan_adjust import insert_phase_block, end_phase_block_early

    program_id = _program(pg, user_id)
    _phase(pg, user_id, program_id, name="Phase A", order_index=0,
           start="2026-01-01", end="2026-01-14")
    phase_b = _phase(pg, user_id, program_id, name="Phase B", order_index=1,
                      start="2026-01-15", end="2026-01-28")

    summary = insert_phase_block(
        pg, user_id, name="Cut", goal="cut",
        start_date=date(2026, 1, 10), end_date=date(2026, 1, 20),
    )
    pg.commit()
    assert _fetch_phase(pg, phase_b)["start_date"].isoformat() == "2026-01-21"

    result = end_phase_block_early(pg, user_id, summary["block_phase_id"], date(2026, 1, 16))
    pg.commit()

    assert result["end_date"] == "2026-01-16"
    assert result["restored_neighbor"]["id"] == phase_b
    assert result["restored_neighbor"]["start_date"] == "2026-01-17"

    b = _fetch_phase(pg, phase_b)
    assert b["start_date"].isoformat() == "2026-01-17"


@requires_pg
def test_overlay_shelves_phase_fully_inside_block(pg, user_id):
    from app.services.plan_adjust import insert_phase_block
    from app.services.phase_resolution import get_effective_phase

    program_id = _program(pg, user_id)
    _phase(pg, user_id, program_id, name="Base Block", order_index=0,
           start="2026-01-01", end="2026-02-28", calories_target=2800)
    deload_id = _phase(pg, user_id, program_id, name="Deload Week", order_index=1,
                        start="2026-01-17", end="2026-01-19", calories_target=2600)

    summary = insert_phase_block(
        pg, user_id, name="Cut", goal="cut",
        start_date=date(2026, 1, 15), end_date=date(2026, 1, 21),
    )
    pg.commit()

    assert len(summary["shelved_phases"]) == 1
    assert summary["shelved_phases"][0]["id"] == deload_id

    deload = _fetch_phase(pg, deload_id)
    assert deload["status"] == "completed"
    assert deload["start_date"] is None and deload["end_date"] is None

    # a date that used to belong only to the shelved phase now resolves to the block,
    # not the shelved row — the resolver ignores status, so this is the only way to
    # avoid it winning a stale ORDER BY tie-break against the newer block.
    resolved = get_effective_phase(pg, user_id, date(2026, 1, 20))
    assert resolved["id"] == summary["block_phase_id"]


@requires_pg
def test_nutrition_guide_regenerated_on_insert(pg, user_id):
    from app.services.plan_adjust import insert_phase_block
    import json

    program_id = _program(pg, user_id)
    _phase(pg, user_id, program_id, name="Hypertrophy Block",
           start="2026-01-01", end="2026-02-28")

    insert_phase_block(
        pg, user_id, name="Cut", goal="cut",
        start_date=date(2026, 1, 15), end_date=date(2026, 1, 21),
        nutrition={"calories_training_day": 2300, "calories_rest_day": 1900,
                   "protein_target": 200},
    )
    pg.commit()

    row = pg.execute(text(
        "SELECT nutrition_guide FROM fitness_program WHERE id = :id"
    ), {"id": program_id}).fetchone()
    guide = json.loads(row[0])
    cal_row = next(m for m in guide["macros"] if m["label"] == "Calories")
    assert cal_row["training"] == "~2,300"
    assert cal_row["rest"] == "~1,900"
    assert "Cut" in guide["how_it_works"]


@requires_pg
def test_update_nutrition_guide_size_cap(pg, user_id):
    from app.services.plan_adjust import update_nutrition_guide, MAX_GUIDE_BYTES

    _program(pg, user_id)
    huge = {"how_it_works": "x" * (MAX_GUIDE_BYTES + 1)}
    with pytest.raises(ValueError, match="size cap"):
        update_nutrition_guide(pg, user_id, huge)
