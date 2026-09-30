"""
Two sessions on one date (HRV_PIPELINE_AND_TWO_A_DAY_PROGRAM_2026_09_14 §B4).

The Two-A-Day Powerbuilding program runs an AM strength session and a PM
hypertrophy session on each of Mon-Thu. Every "today's workout" reader in the
backend was written when a weekday had at most one template, so each of them
looped the day's templates and `break`ed on the first match — which would have
hidden the PM session from the brief, the suggestions and the chat context.

These pin the two pieces that make a two-a-day legible: the day resolves to a
*list* of sessions in plan order, and the AM lift's 8-week loading table (which
lives in the exercise `notes`, the only place the importer has for it) reads
back as this week's actual prescription.
"""
import json
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.services.workout_prescription import (
    describe_day, describe_exercise, prescription_for_week,
)

USER = "test-user-2aday"
PHASE = "phase-build-1"

AM_NOTES = (
    "Warm-up: 90x10, 180x5, 230x2 (easy). Set 1 = TOP SET, sets 2-4 = BACKOFF x4-6 @1-2 RIR.\n"
    "TOP: Wk1 270x2 · Wk2 270x3 · Wk3 270x4 · Wk4 DELOAD 230x4 · Wk5 280x2 · Wk6 280x3 "
    "· Wk7 280x4 · Wk8 REP PR 270x5 target\n"
    "BACKOFF: Wk1 230 · Wk2 230 · Wk3 240 · Wk4 DELOAD 210x5x2 · Wk5 240 · Wk6 250 "
    "· Wk7 250 · Wk8 235"
)

AM_TEMPLATE = {
    "name": "Mon AM — NewTech Flat Press (Strength)",
    "order_in_phase": 0,
    "exercises": [{"name": "Newtech Flat", "sets": 4, "reps": "2-6",
                   "rpe_target": 8, "notes": AM_NOTES}],
}
PM_TEMPLATE = {
    "name": "Mon PM — Chest + Triceps (Hypertrophy)",
    "order_in_phase": 1,
    "exercises": [
        {"name": "Incline Press", "sets": 3, "reps": "6-10", "notes": "1-2 RIR."},
        {"name": "Cable Fly", "sets": 3, "reps": "10-15", "notes": "0-2 RIR."},
        {"name": "Triceps Pushdown", "sets": 3, "reps": "10-15", "notes": "0-2 RIR."},
    ],
}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    session = sessionmaker(bind=engine)()
    session.execute(text("""
        CREATE TABLE fitness_template (
            id TEXT PRIMARY KEY, user_id TEXT, phase_id TEXT, name TEXT,
            scheduled_days TEXT, exercises TEXT, notes TEXT, order_in_phase INTEGER
        )
    """))
    session.execute(text("""
        CREATE TABLE workout_session (id TEXT PRIMARY KEY, user_id TEXT, session_date DATE)
    """))
    session.execute(text("""
        CREATE TABLE day_type_override (user_id TEXT, override_date DATE, day_type TEXT)
    """))
    session.execute(text("""
        CREATE TABLE fitness_program (id TEXT PRIMARY KEY, user_id TEXT,
                                      is_active BOOLEAN, start_date DATE)
    """))
    session.execute(text(
        "INSERT INTO fitness_program VALUES ('prog-1', :uid, 1, '2026-09-14')"), {"uid": USER})

    # PM is inserted FIRST so a correct reader cannot pass by accident of
    # insertion order — only `order_in_phase` puts AM back in front.
    for i, t in enumerate([PM_TEMPLATE, AM_TEMPLATE]):
        session.execute(text("""
            INSERT INTO fitness_template
                (id, user_id, phase_id, name, scheduled_days, exercises, notes, order_in_phase)
            VALUES (:id, :uid, :pid, :name, :days, :ex, '', :oi)
        """), {
            "id": f"tmpl-{i}", "uid": USER, "pid": PHASE, "name": t["name"],
            "days": json.dumps(["monday"]), "ex": json.dumps(t["exercises"]),
            "oi": t["order_in_phase"],
        })
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def phase():
    return {"id": PHASE, "name": "Build 1 (Weeks 1-3)"}


MONDAY = date(2026, 9, 14)      # week 1 of the program
SATURDAY = date(2026, 9, 19)


class TestTemplatesForDay:
    def test_both_sessions_are_returned_in_plan_order(self, db, phase):
        from app.services.training_day import templates_for_day
        found = templates_for_day(db, USER, MONDAY, phase=phase)
        assert [t["name"] for t in found] == [AM_TEMPLATE["name"], PM_TEMPLATE["name"]]

    def test_exercises_are_parsed(self, db, phase):
        from app.services.training_day import templates_for_day
        found = templates_for_day(db, USER, MONDAY, phase=phase)
        assert found[0]["exercises"][0]["name"] == "Newtech Flat"
        assert len(found[1]["exercises"]) == 3

    def test_a_rest_day_has_no_sessions(self, db, phase):
        from app.services.training_day import templates_for_day
        assert templates_for_day(db, USER, SATURDAY, phase=phase) == []


class TestIsTrainingDay:
    def _patched(self, monkeypatch, phase):
        import app.services.training_day as td
        monkeypatch.setattr(td, "get_effective_phase", lambda *a, **k: phase)
        return td

    def test_training_day_lists_both_templates(self, db, phase, monkeypatch):
        td = self._patched(monkeypatch, phase)
        result = td.is_training_day(db, USER, MONDAY)
        assert result["is_training_day"] is True
        assert result["reason"] == "scheduled"
        assert [t["name"] for t in result["templates"]] == [
            AM_TEMPLATE["name"], PM_TEMPLATE["name"]]

    def test_legacy_single_template_fields_still_point_at_the_first(self, db, phase, monkeypatch):
        """Callers that predate two-a-days keep working, and get the AM session
        — the one that happens first — not an arbitrary row."""
        td = self._patched(monkeypatch, phase)
        result = td.is_training_day(db, USER, MONDAY)
        assert result["template_name"] == AM_TEMPLATE["name"]

    def test_logging_the_am_session_does_not_hide_the_pm_one(self, db, phase, monkeypatch):
        """A `workout_session` row short-circuits the day as training. With two
        sessions a date, that must not blank out the day's template list."""
        td = self._patched(monkeypatch, phase)
        db.execute(text("INSERT INTO workout_session VALUES ('s1', :uid, :d)"),
                   {"uid": USER, "d": MONDAY})
        result = td.is_training_day(db, USER, MONDAY)
        assert result["reason"] == "session_logged"
        assert [t["name"] for t in result["templates"]] == [
            AM_TEMPLATE["name"], PM_TEMPLATE["name"]]

    def test_rest_day(self, db, phase, monkeypatch):
        td = self._patched(monkeypatch, phase)
        result = td.is_training_day(db, USER, SATURDAY)
        assert result["is_training_day"] is False
        assert result["templates"] == []


class TestProgramWeek:
    def test_week_counts_from_the_program_start(self, db):
        from app.services.workout_prescription import program_week
        assert program_week(db, USER, MONDAY) == 1
        assert program_week(db, USER, date(2026, 9, 20)) == 1   # end of week 1
        assert program_week(db, USER, date(2026, 9, 21)) == 2
        assert program_week(db, USER, date(2026, 10, 5)) == 4   # deload
        assert program_week(db, USER, date(2026, 11, 2)) == 8   # rep PR

    def test_before_the_program_starts_there_is_no_week(self, db):
        from app.services.workout_prescription import program_week
        assert program_week(db, USER, date(2026, 9, 13)) is None


class TestPrescription:
    """The loading table lives in the exercise notes — the importer has nowhere
    structured to put it — so reading it back has to be reliable."""

    @pytest.mark.parametrize("week,top,backoff", [
        (1, "270x2", "230"),
        (3, "270x4", "240"),
        (4, "DELOAD 230x4", "DELOAD 210x5x2"),
        (7, "280x4", "250"),
        (8, "REP PR 270x5 target", "235"),
    ])
    def test_each_week_reads_back(self, week, top, backoff):
        p = prescription_for_week(AM_NOTES, week)
        assert p["top"] == top
        assert p["backoff"] == backoff

    def test_a_week_outside_the_table_yields_nothing(self):
        assert prescription_for_week(AM_NOTES, 99) == {}

    def test_no_week_yields_nothing(self):
        assert prescription_for_week(AM_NOTES, None) == {}

    def test_notes_without_a_table_yield_nothing(self):
        assert prescription_for_week("Rope pressdown. 0-2 RIR.", 1) == {}

    def test_description_uses_the_backoff_rep_range_not_the_combined_one(self):
        """`reps` is "2-6" because it spans the top set; the backoffs are 4-6."""
        line = describe_exercise(AM_TEMPLATE["exercises"][0], week=1)
        assert "top set 270x2" in line
        assert "3×4-6 @230" in line

    def test_deload_backoff_is_not_mangled_into_a_sets_times_reps(self):
        """Week 4's backoff already spells out load×reps×sets ("210x5x2")."""
        line = describe_exercise(AM_TEMPLATE["exercises"][0], week=4)
        assert "top set 230x4" in line
        assert "backoff 210x5x2" in line
        assert "[DELOAD]" in line

    def test_an_exercise_with_no_table_falls_back_to_sets_by_reps(self):
        assert describe_exercise(PM_TEMPLATE["exercises"][0], week=1) == "Incline Press 3×6-10"


class TestDescribeDay:
    def test_both_sessions_appear_with_the_am_load(self, db, phase):
        from app.services.training_day import templates_for_day
        line = describe_day(templates_for_day(db, USER, MONDAY, phase=phase), week=1)
        assert "Mon AM — NewTech Flat Press (Strength)" in line
        assert "top set 270x2" in line
        assert "Mon PM — Chest + Triceps (Hypertrophy)" in line
        assert "3 exercises" in line
        # AM first.
        assert line.index("Mon AM") < line.index("Mon PM")


# ──────────────────────────────────────────────────────────────────────────
# A6 — /templates/today's session_status: "next outstanding", not "the
# first". Needs real Postgres (ANY(:tids), AT TIME ZONE — see
# training_day._with_session_status), so this runs against the disposable
# test database rather than the SQLite fixture above.
# ──────────────────────────────────────────────────────────────────────────
import os
import uuid


def _pg_available() -> bool:
    return os.getenv("DATABASE_URL", "").startswith("postgresql")


requires_pg = pytest.mark.skipif(
    not _pg_available(), reason="needs a real PostgreSQL database")


@pytest.fixture
def pg():
    from app.db.session import SessionLocal
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def pg_user_and_templates(pg):
    """A real active program/phase with an AM + PM template scheduled today,
    matching the AM/PM shape this whole file tests against."""
    from app.core.timezone import now as local_now

    uid = str(uuid.uuid4())
    pg.execute(text("INSERT INTO app_user (id, email, password_hash) VALUES (:id, :email, 'x')"),
               {"id": uid, "email": f"a6-test-{uid}@example.invalid"})

    today = local_now().date()
    weekday = today.strftime("%A").lower()
    program_id, phase_id = str(uuid.uuid4()), str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_program (id, user_id, name, goal, start_date, end_date, is_active)
        VALUES (:id, :uid, 'A6 Test Program', 'recomp', :start, :end, true)
    """), {"id": program_id, "uid": uid,
           "start": today - timedelta(days=14), "end": today + timedelta(days=14)})
    pg.execute(text("""
        INSERT INTO fitness_phase (id, user_id, program_id, name, order_index,
                                   start_date, end_date, status)
        VALUES (:id, :uid, :pid, 'Build 1', 0, :start, :end, 'active')
    """), {"id": phase_id, "uid": uid, "pid": program_id,
           "start": today - timedelta(days=14), "end": today + timedelta(days=14)})

    am_id, pm_id = str(uuid.uuid4()), str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_template (id, user_id, phase_id, name, scheduled_days,
                                      exercises, order_in_phase)
        VALUES (:id, :uid, :pid, :name, CAST(:days AS jsonb), CAST(:ex AS jsonb), :oi)
    """), [
        {"id": am_id, "uid": uid, "pid": phase_id, "name": "AM Squat",
         "days": json.dumps([weekday]), "ex": json.dumps([{"name": "Back Squat", "sets": 4, "reps": "2-6"}]),
         "oi": 0},
        {"id": pm_id, "uid": uid, "pid": phase_id, "name": "PM Legs",
         "days": json.dumps([weekday]), "ex": json.dumps([{"name": "Leg Press", "sets": 3, "reps": "8-12"}]),
         "oi": 1},
    ])
    pg.commit()

    yield uid, am_id, pm_id

    for stmt in (
        "DELETE FROM active_workout_session WHERE user_id = :uid",
        "DELETE FROM fitness_template WHERE user_id = :uid",
        "DELETE FROM fitness_phase WHERE user_id = :uid",
        "DELETE FROM fitness_program WHERE user_id = :uid",
        "DELETE FROM app_user WHERE id = :uid",
    ):
        try:
            pg.execute(text(stmt), {"uid": uid})
            pg.commit()
        except Exception:
            pg.rollback()


@requires_pg
class TestSessionStatusNextOutstanding:
    def test_nothing_started_yet_next_outstanding_is_am(self, pg, pg_user_and_templates):
        from app.core.timezone import now as local_now
        from app.services.training_day import is_training_day
        uid, am_id, pm_id = pg_user_and_templates

        result = is_training_day(pg, uid, local_now().date())
        assert result["template_id"] == am_id
        statuses = {t["id"]: t.get("session_status") for t in result["templates"]}
        assert statuses[am_id] is None and statuses[pm_id] is None

    def test_am_completed_next_outstanding_is_pm(self, pg, pg_user_and_templates):
        from app.core.timezone import now as local_now
        from app.services.training_day import is_training_day
        uid, am_id, pm_id = pg_user_and_templates

        pg.execute(text("""
            INSERT INTO active_workout_session (id, user_id, template_id, status, started_at, completed_at)
            VALUES (:id, :uid, :tid, 'completed', now(), now())
        """), {"id": str(uuid.uuid4()), "uid": uid, "tid": am_id})
        pg.commit()

        result = is_training_day(pg, uid, local_now().date())
        assert result["template_id"] == pm_id
        assert result["template_name"] == "PM Legs"
        statuses = {t["id"]: t.get("session_status") for t in result["templates"]}
        assert statuses[am_id] == "completed"
        assert statuses[pm_id] is None

    def test_both_completed_falls_back_to_the_first(self, pg, pg_user_and_templates):
        from app.core.timezone import now as local_now
        from app.services.training_day import is_training_day
        uid, am_id, pm_id = pg_user_and_templates

        for tid in (am_id, pm_id):
            pg.execute(text("""
                INSERT INTO active_workout_session (id, user_id, template_id, status, started_at, completed_at)
                VALUES (:id, :uid, :tid, 'completed', now(), now())
            """), {"id": str(uuid.uuid4()), "uid": uid, "tid": tid})
        pg.commit()

        result = is_training_day(pg, uid, local_now().date())
        assert result["template_id"] == am_id
        assert all(t.get("session_status") == "completed" for t in result["templates"])
