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
from datetime import date

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
