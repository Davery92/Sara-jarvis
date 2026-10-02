"""Step 4 of FITNESS_COACH_IMPLEMENTATION_PLAN: the M0 ownership migration is
safe on pre-existing records, and the audit reports conflicts instead of
guessing an owner.

The thing actually at risk here is history. The obvious "correct" migration —
`ALTER TABLE food_log ADD FOREIGN KEY (user_id) REFERENCES app_user(id)` —
fails on any row left over from the `SOLO_USER_ID`/`default-user` era, and
the only ways to make it succeed are to delete those rows or to reassign
them to a guessed owner. These tests pin the behaviour that neither happens.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_ownership_migration_pg.py
"""
import importlib.util
import json
import os
import pathlib
import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

requires_pg = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="needs a disposable PostgreSQL",
)

_AUDIT_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "fitness_backfill_audit.py"


def _load_audit():
    """Import the audit by path — `scripts/` is not an importable package.

    The `sys.modules` registration is required, not cosmetic: `@dataclass`
    resolves its field annotations through `sys.modules[cls.__module__]`, so
    executing the module before registering it raises inside dataclasses.
    """
    import sys
    if "fitness_backfill_audit" in sys.modules:
        return sys.modules["fitness_backfill_audit"]
    spec = importlib.util.spec_from_file_location("fitness_backfill_audit", _AUDIT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fitness_backfill_audit"] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_workout(pg, user_id: str) -> str:
    """`workout_log.workout_id` references `workout` — the legacy aggregate.

    A set cannot exist without one, which is itself part of why the plan
    keeps three session-ish tables (`workout`, `workout_session`,
    `active_workout_session`) rather than replacing them.
    """
    wid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO workout (id, user_id, title, status, created_at, updated_at)
        VALUES (:id, :u, 'M0 audit fixture', 'completed', NOW(), NOW())
    """), {"id": wid, "u": user_id})
    return wid


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
def athletes(pg):
    """Two real athletes plus one deliberately orphaned owner string."""
    unusable_hash = "$2b$12$" + "x" * 53
    alice = f"m0a-{uuid.uuid4().hex[:18]}"
    bob = f"m0b-{uuid.uuid4().hex[:18]}"
    for uid in (alice, bob):
        pg.execute(text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
        """), {"id": uid, "e": f"{uid}@m0.invalid", "p": unusable_hash})
    pg.commit()
    yield alice, bob, "default-user"
    pg.rollback()
    for t in ("workout_log", "workout", "food_log", "daily_recovery_log", "health_metric",
              "exercise_pr", "workout_session", "active_workout_session",
              "fitness_template", "fitness_phase", "fitness_program",
              "fitness_goals", "weight_trend", "progress_photo"):
        pg.execute(text(f"DELETE FROM {t} WHERE user_id = ANY(:ids)"),
                   {"ids": [alice, bob, "default-user"]})
    pg.execute(text("DELETE FROM fitness_ownership_quarantine WHERE observed_owner = 'default-user'"))
    pg.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"), {"ids": [alice, bob]})
    pg.commit()


# ─────────────────────────────────────────────────────────────────────────
# Schema shape
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_migration_is_at_head_with_the_m0_objects(pg):
    version = pg.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version is not None, "the disposable database must declare its revision"

    assert pg.execute(text(
        "SELECT to_regclass('fitness_ownership_quarantine')")).scalar() is not None

    cols = {r[0] for r in pg.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'exercise_library'
    """)).fetchall()}
    assert {"owner_user_id", "visibility", "archived_at", "scope_reviewed_at"} <= cols


@requires_pg
def test_owner_date_indexes_exist_for_every_analytics_window(pg):
    """A 28-day review must not sequentially scan a multi-year history."""
    expected = {
        "ix_health_metric_user_type_time",
        "ix_daily_recovery_log_user_date",
        "ix_workout_log_user_session_date",
        "ix_workout_log_user_logged_fallback",
        "ix_workout_log_user_canonical_exercise",
        "ix_workout_session_user_date",
        "ix_active_workout_session_user_started",
        "ix_weight_trend_user_date",
        "ix_exercise_pr_user_name",
        "ix_fitness_phase_user_dates",
        "ix_fitness_template_user_phase",
        "ix_progress_photo_user_taken",
    }
    present = {r[0] for r in pg.execute(text("""
        SELECT indexname FROM pg_indexes WHERE schemaname = 'public'
    """)).fetchall()}
    assert expected <= present, f"missing: {sorted(expected - present)}"


@requires_pg
def test_no_foreign_key_was_added_to_the_unconstrained_owner_columns(pg):
    """The deliberate omission.

    Constraint coverage is already uneven in the inspected schema — earlier
    migrations put `REFERENCES app_user(id)` on `workout_log`,
    `active_workout_session`, `exercise_pr`, `fitness_program`,
    `progress_photo` and `weight_trend`, but not on `food_log`,
    `health_metric`, `daily_recovery_log`, `fitness_template`,
    `fitness_phase`, `fitness_goals` or `workout_session`.

    M0 does not close that gap. Adding the FK to the uncovered tables would
    fail the upgrade on any row left from the `SOLO_USER_ID`/`default-user`
    era, and the only ways to make it succeed are to delete that history or
    reassign it to a guessed owner. Ownership is enforced in the service
    layer — which is where it has to be anyway, since an FK proves a parent
    exists and never that it belongs to the requester.
    """
    unconstrained = {"food_log", "health_metric", "daily_recovery_log",
                     "fitness_template", "fitness_phase", "fitness_goals",
                     "workout_session"}
    fks = {r[0] for r in pg.execute(text("""
        SELECT tc.table_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON kcu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND kcu.column_name = 'user_id'
    """)).fetchall()}
    assert fks & unconstrained == set(), (
        "M0 must not constrain the legacy owner columns yet; found FKs on "
        f"{sorted(fks & unconstrained)}"
    )


@requires_pg
def test_visibility_defaults_to_unscoped_not_global(pg, athletes):
    """No existing exercise is declared public by a migration.

    `exercise_library_seed.py` derived rows from names that already appeared
    in people's logs, so "global by default" would publish user-created
    exercise names.
    """
    eid = f"m0-ex-{uuid.uuid4().hex[:12]}"
    pg.execute(text("""
        INSERT INTO exercise_library (id, name, movement_pattern, created_at, updated_at)
        VALUES (:id, 'Zercher Good Morning', 'hinge', NOW(), NOW())
    """), {"id": eid})
    pg.commit()
    try:
        row = pg.execute(text(
            "SELECT visibility, owner_user_id FROM exercise_library WHERE id = :id"
        ), {"id": eid}).fetchone()
        assert row.visibility == "unscoped"
        assert row.owner_user_id is None
    finally:
        pg.rollback()
        pg.execute(text("DELETE FROM exercise_library WHERE id = :id"), {"id": eid})
        pg.commit()


@requires_pg
def test_scope_constraint_rejects_an_ownerless_private_exercise(pg):
    """A private row with no owner would be invisible to everyone."""
    eid = f"m0-ex-{uuid.uuid4().hex[:12]}"
    with pytest.raises(Exception):
        pg.execute(text("""
            INSERT INTO exercise_library (id, name, movement_pattern, visibility, created_at, updated_at)
            VALUES (:id, 'Secret Lift', 'push', 'private', NOW(), NOW())
        """), {"id": eid})
        pg.commit()
    pg.rollback()


@requires_pg
def test_scope_constraint_rejects_a_global_exercise_with_an_owner(pg, athletes):
    alice, _, _ = athletes
    eid = f"m0-ex-{uuid.uuid4().hex[:12]}"
    with pytest.raises(Exception):
        pg.execute(text("""
            INSERT INTO exercise_library
                (id, name, movement_pattern, visibility, owner_user_id, created_at, updated_at)
            VALUES (:id, 'Bench Press', 'push', 'global', :u, NOW(), NOW())
        """), {"id": eid, "u": alice})
        pg.commit()
    pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# Quarantine
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_quarantine_is_idempotent_per_row(pg, athletes):
    """A second audit run must not duplicate a decision already recorded."""
    _, _, orphan = athletes
    args = {
        "t": "food_log", "r": f"row-{uuid.uuid4().hex[:10]}", "o": orphan,
    }
    for _ in range(2):
        pg.execute(text("""
            INSERT INTO fitness_ownership_quarantine
                (id, table_name, row_id, observed_owner, reason, last_seen_at)
            VALUES (:id, :t, :r, :o, 'owner_not_in_app_user', NOW())
            ON CONFLICT (table_name, row_id)
            DO UPDATE SET last_seen_at = NOW()
        """), {**args, "id": str(uuid.uuid4())})
    pg.commit()
    n = pg.execute(text("""
        SELECT COUNT(*) FROM fitness_ownership_quarantine
        WHERE table_name = :t AND row_id = :r
    """), args).scalar()
    assert n == 1, "re-running the audit must update, not duplicate"
    pg.execute(text("DELETE FROM fitness_ownership_quarantine WHERE row_id = :r"), {"r": args["r"]})
    pg.commit()


@requires_pg
def test_quarantine_status_is_constrained(pg, athletes):
    _, _, orphan = athletes
    with pytest.raises(Exception):
        pg.execute(text("""
            INSERT INTO fitness_ownership_quarantine
                (id, table_name, row_id, observed_owner, reason, status)
            VALUES (:id, 'food_log', 'x', :o, 'r', 'definitely-davids')
        """), {"id": str(uuid.uuid4()), "o": orphan})
        pg.commit()
    pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# The audit itself
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_audit_reports_orphan_owners_without_reassigning_them(pg, athletes):
    alice, _, orphan = athletes
    audit = _load_audit()

    pg.execute(text("""
        INSERT INTO food_log (id, user_id, meal_type, food_items, calories, logged_at, created_at, updated_at)
        VALUES (:id, :u, 'lunch', '[]', 500, NOW(), NOW(), NOW())
    """), {"id": str(uuid.uuid4()), "u": orphan})
    pg.commit()
    try:
        findings = audit.run_audit(os.environ["DATABASE_URL"])
        orphans = [f for f in findings if f.check == "orphan_owner:food_log"]
        assert orphans, "an unresolvable owner must be reported"
        assert any(orphan in f.detail for f in orphans)
        assert all(f.severity != "block" for f in orphans), (
            "a historical orphan must not block new owned records"
        )

        # Nothing moved.
        still_there = pg.execute(text(
            "SELECT COUNT(*) FROM food_log WHERE user_id = :u"), {"u": orphan}).scalar()
        assert still_there == 1
        assert pg.execute(text(
            "SELECT COUNT(*) FROM food_log WHERE user_id = :u"), {"u": alice}).scalar() == 0
    finally:
        pg.rollback()
        pg.execute(text("DELETE FROM food_log WHERE user_id = :u"), {"u": orphan})
        pg.commit()


@requires_pg
def test_audit_does_not_print_values(pg, athletes):
    """Ids and counts, never a bodyweight or a note."""
    alice, _, _ = athletes
    audit = _load_audit()
    secret = 97.531
    pg.execute(text("""
        INSERT INTO health_metric (id, user_id, metric_type, value, recorded_at, source)
        VALUES (:id, :u, 'grip_strength_oddity', :v, NOW(), 'manual')
    """), {"id": str(uuid.uuid4()), "u": alice, "v": secret})
    pg.commit()
    try:
        findings = audit.run_audit(os.environ["DATABASE_URL"])
        blob = json.dumps([f.as_dict() for f in findings])
        assert "97.5" not in blob, "the audit leaked an observed value"
        # It does name the metric type, which is a column-level fact.
        assert any("grip_strength_oddity" in f.detail for f in findings)
    finally:
        pg.rollback()
        pg.execute(text("DELETE FROM health_metric WHERE user_id = :u"), {"u": alice})
        pg.commit()


@requires_pg
def test_audit_flags_cross_owner_session_reference_as_blocking(pg, athletes):
    """The one finding that genuinely blocks: a set owned by someone other
    than the session it hangs off. Analytics that trust session ownership
    would attribute Alice's volume to Bob."""
    alice, bob, _ = athletes
    audit = _load_audit()
    sid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO active_workout_session (id, user_id, status, started_at, version)
        VALUES (:id, :u, 'completed', NOW(), 1)
    """), {"id": sid, "u": bob})
    pg.execute(text("""
        INSERT INTO workout_log
            (id, workout_id, user_id, exercise_id, set_index, weight, reps,
             active_session_id, set_kind, created_at)
        VALUES (:id, :w, :u, 'Bench Press', 1, 100, 5, :s, 'working', NOW())
    """), {"id": str(uuid.uuid4()), "w": _make_workout(pg, alice), "u": alice, "s": sid})
    pg.commit()
    try:
        findings = audit.run_audit(os.environ["DATABASE_URL"])
        blocking = [f for f in findings if f.check == "cross_owner_session_reference"]
        assert blocking, "a cross-owner set/session pair must be reported"
        assert blocking[0].severity == "block"
    finally:
        pg.rollback()
        pg.execute(text("DELETE FROM workout_log WHERE active_session_id = :s"), {"s": sid})
        pg.execute(text("DELETE FROM workout WHERE user_id = :u"), {"u": alice})
        pg.execute(text("DELETE FROM active_workout_session WHERE id = :s"), {"s": sid})
        pg.commit()


@requires_pg
def test_audit_reports_exercise_scope_without_publishing_private_names(pg, athletes):
    alice, _, _ = athletes
    audit = _load_audit()
    eid = f"m0-ex-{uuid.uuid4().hex[:12]}"
    pg.execute(text("""
        INSERT INTO exercise_library (id, name, movement_pattern, created_at, updated_at)
        VALUES (:id, 'Alices Weird Cable Thing', 'pull', NOW(), NOW())
    """), {"id": eid})
    pg.execute(text("""
        INSERT INTO workout_log
            (id, workout_id, user_id, exercise_id, exercise_library_id, set_index,
             weight, reps, set_kind, created_at)
        VALUES (:id, :w, :u, 'Alices Weird Cable Thing', :e, 1, 20, 12, 'working', NOW())
    """), {"id": str(uuid.uuid4()), "w": _make_workout(pg, alice), "u": alice, "e": eid})
    pg.commit()
    try:
        findings = audit.run_audit(os.environ["DATABASE_URL"])
        single = [f for f in findings if f.check == "exercise_scope:single_user"]
        assert single and single[0].count >= 1
        blob = json.dumps([f.as_dict() for f in findings])
        assert "Alices Weird Cable Thing" not in blob, (
            "a single-user exercise name is private and must not appear in a report"
        )
        # Nothing was reclassified.
        assert pg.execute(text(
            "SELECT visibility FROM exercise_library WHERE id = :id"), {"id": eid}
        ).scalar() == "unscoped"
    finally:
        pg.rollback()
        pg.execute(text("DELETE FROM workout_log WHERE exercise_library_id = :e"), {"e": eid})
        pg.execute(text("DELETE FROM workout WHERE user_id = :u"), {"u": alice})
        pg.execute(text("DELETE FROM exercise_library WHERE id = :id"), {"id": eid})
        pg.commit()


@requires_pg
def test_audit_detects_overlapping_phases(pg, athletes):
    alice, _, _ = athletes
    audit = _load_audit()
    prog = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_program (id, user_id, name, goal, is_active, created_at, updated_at)
        VALUES (:id, :u, 'Overlap test', 'hypertrophy', false, NOW(), NOW())
    """), {"id": prog, "u": alice})
    for start, end in (("2026-01-01", "2026-02-15"), ("2026-02-01", "2026-03-15")):
        pg.execute(text("""
            INSERT INTO fitness_phase
                (id, user_id, program_id, name, start_date, end_date, status, created_at, updated_at)
            VALUES (:id, :u, :p, 'Block', :s, :e, 'completed', NOW(), NOW())
        """), {"id": str(uuid.uuid4()), "u": alice, "p": prog, "s": start, "e": end})
    pg.commit()
    try:
        findings = audit.run_audit(os.environ["DATABASE_URL"])
        assert any(f.check == "overlapping_phases" for f in findings), (
            "a date covered by two phases has no single effective target"
        )
    finally:
        pg.rollback()
        pg.execute(text("DELETE FROM fitness_phase WHERE program_id = :p"), {"p": prog})
        pg.execute(text("DELETE FROM fitness_program WHERE id = :p"), {"p": prog})
        pg.commit()


@requires_pg
def test_audit_marks_default_valued_targets_as_unprovable(pg, athletes):
    """`fitness_goals` defaults to 2000/150/200/70.

    A row sitting exactly on those is not evidence anyone chose them, so a
    seeded target revision must not claim them for past months.
    """
    alice, _, _ = athletes
    audit = _load_audit()
    pg.execute(text("""
        INSERT INTO fitness_goals (id, user_id, calories, protein, carbs, fats)
        VALUES (:id, :u, 2000, 150, 200, 70)
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.commit()
    try:
        findings = audit.run_audit(os.environ["DATABASE_URL"])
        assert any(f.check == "target_history_unprovable" for f in findings)
    finally:
        pg.rollback()
        pg.execute(text("DELETE FROM fitness_goals WHERE user_id = :u"), {"u": alice})
        pg.commit()


# ─────────────────────────────────────────────────────────────────────────
# Reviewed reassignment
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_apply_requires_a_real_destination(pg, athletes, tmp_path):
    """"The only other user" is not a reviewed mapping."""
    _, _, orphan = athletes
    audit = _load_audit()
    mapping = tmp_path / "bad.json"
    mapping.write_text(json.dumps({orphan: "nobody-at-all"}))
    with pytest.raises(SystemExit) as e:
        audit.apply_mapping(os.environ["DATABASE_URL"], str(mapping), dry_run=True)
    assert "not an app_user" in str(e.value)


@requires_pg
def test_apply_refuses_to_move_rows_that_already_have_a_real_owner(pg, athletes, tmp_path):
    """This resolves orphans. It is not a general "move Alice's data to Bob"."""
    alice, bob, _ = athletes
    audit = _load_audit()
    mapping = tmp_path / "steal.json"
    mapping.write_text(json.dumps({alice: bob}))
    with pytest.raises(SystemExit) as e:
        audit.apply_mapping(os.environ["DATABASE_URL"], str(mapping), dry_run=True)
    assert "only resolves orphans" in str(e.value)


@requires_pg
def test_apply_dry_run_changes_nothing_then_real_run_moves_only_intended_rows(
    pg, athletes, tmp_path
):
    alice, bob, orphan = athletes
    audit = _load_audit()
    url = os.environ["DATABASE_URL"]

    orphan_meal = str(uuid.uuid4())
    bobs_meal = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO food_log (id, user_id, meal_type, food_items, calories, logged_at, created_at, updated_at)
        VALUES (:id, :u, 'lunch', '[]', 500, NOW(), NOW(), NOW())
    """), {"id": orphan_meal, "u": orphan})
    pg.execute(text("""
        INSERT INTO food_log (id, user_id, meal_type, food_items, calories, logged_at, created_at, updated_at)
        VALUES (:id, :u, 'dinner', '[]', 700, NOW(), NOW(), NOW())
    """), {"id": bobs_meal, "u": bob})
    pg.commit()

    mapping = tmp_path / "reviewed.json"
    mapping.write_text(json.dumps({orphan: alice}))
    try:
        report = audit.apply_mapping(url, str(mapping), dry_run=True)
        assert report["dry_run"] is True
        assert report["tables"].get("food_log") == 1
        assert pg.execute(text(
            "SELECT user_id FROM food_log WHERE id = :id"), {"id": orphan_meal}
        ).scalar() == orphan, "a dry run must write nothing"

        audit.apply_mapping(url, str(mapping), dry_run=False)
        assert pg.execute(text(
            "SELECT user_id FROM food_log WHERE id = :id"), {"id": orphan_meal}
        ).scalar() == alice
        assert pg.execute(text(
            "SELECT user_id FROM food_log WHERE id = :id"), {"id": bobs_meal}
        ).scalar() == bob, "an unrelated athlete's row was touched"

        # Idempotent: the source id no longer matches anything.
        second = audit.apply_mapping(url, str(mapping), dry_run=False)
        assert second["tables"] == {}, "a re-run must be a no-op, not a second move"
    finally:
        pg.rollback()
        pg.execute(text("DELETE FROM food_log WHERE id = ANY(:ids)"),
                   {"ids": [orphan_meal, bobs_meal]})
        pg.commit()


@requires_pg
def test_valid_histories_survive_the_migration(pg, athletes):
    """The point of M0: a row written in the solo era still reads correctly."""
    _, _, orphan = athletes
    rid = str(uuid.uuid4())
    # daily_recovery_log, not workout_log: the latter already carries a
    # user_id FK, so a solo-era owner string cannot even be inserted there.
    pg.execute(text("""
        INSERT INTO daily_recovery_log
            (id, user_id, log_date, hrv, sleep_hours, body_weight, weight_unit,
             created_at, updated_at)
        VALUES (:id, :u, CURRENT_DATE - 400, 62, 7.25, 182.4, 'lbs',
                NOW() - INTERVAL '400 days', NOW() - INTERVAL '400 days')
    """), {"id": rid, "u": orphan})
    pg.commit()
    try:
        row = pg.execute(text("""
            SELECT user_id, hrv, sleep_hours, body_weight, weight_unit
            FROM daily_recovery_log WHERE id = :id
        """), {"id": rid}).fetchone()
        assert row.user_id == orphan, "the historical owner value is preserved verbatim"
        assert row.hrv == 62
        assert float(row.sleep_hours) == 7.25
        assert float(row.body_weight) == 182.4
        assert row.weight_unit == "lbs"
    finally:
        pg.rollback()
        pg.execute(text("DELETE FROM daily_recovery_log WHERE id = :id"), {"id": rid})
        pg.commit()
