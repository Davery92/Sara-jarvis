"""set_plan.resolve_set_plan (TWO_A_DAY_AM_SETS_AND_FOOD_REPEAT_PLAN Part A2/A8).

Resolves the 8-week top/backoff loading table
(backend/scripts/plans/add_set_plan_two_a_day.py, SET_PLANS) into the ordered
per-set list a session actually prescribes, applying the advance rule
(clean top set -> the calendar week; anything else -> hold at the prior week).

Imports SET_PLANS from the migration script directly rather than
hand-retyping the numbers here, so this test can never silently drift from
what's actually written into the database.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

from app.services.set_plan import is_plan_driven, next_entry, resolve_set_plan
from app.services.workout_prescription import program_week

# The migration script lives under scripts/, not a package — import it by path.
_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "plans" / "add_set_plan_two_a_day.py"
_spec = importlib.util.spec_from_file_location("add_set_plan_two_a_day", _SCRIPT_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)
SET_PLANS = _module.SET_PLANS


def _spec_for(lift: str) -> dict:
    return {"name": lift, "sets": 4, "reps": "2-6", "set_plan": SET_PLANS[lift]}


class TestResolveEachLift:
    """Week 1 (build), week 4 (deload) and week 8 (rep PR) for all 4 AM lifts."""

    @pytest.mark.parametrize("lift,top_w,top_r,backoff_w,backoff_r,backoff_sets", [
        ("Newtech Flat", 270, "2", 230, "4-6", 3),
        ("Deadlift", 315, "1-3", 275, "3-5", 2),
        ("Smith Machine Press", 145, "2-4", 130, "4-6", 3),
        ("Back Squat", 225, "2-4", 200, "4-6", 3),
    ])
    def test_week_1(self, lift, top_w, top_r, backoff_w, backoff_r, backoff_sets):
        resolved = resolve_set_plan(_spec_for(lift), week=1)
        assert resolved["effective_week"] == 1
        assert resolved["held"] is False
        top = next(s for s in resolved["sets"] if s["kind"] == "top")
        assert (top["weight"], top["reps"]) == (top_w, top_r)
        backoffs = [s for s in resolved["sets"] if s["kind"] == "backoff"]
        assert len(backoffs) == backoff_sets
        assert (backoffs[0]["weight"], backoffs[0]["reps"]) == (backoff_w, backoff_r)
        assert resolved["working_set_count"] == 1 + backoff_sets

    @pytest.mark.parametrize("lift,top_w,top_r,backoff_w,backoff_sets", [
        ("Newtech Flat", 230, "4", 210, 2),
        ("Deadlift", 285, "2", 250, 2),
        ("Smith Machine Press", 125, "4", 115, 2),
        ("Back Squat", 205, "3", 180, 2),
    ])
    def test_week_4_is_deload(self, lift, top_w, top_r, backoff_w, backoff_sets):
        resolved = resolve_set_plan(_spec_for(lift), week=4)
        assert resolved["note"] == "DELOAD"
        top = next(s for s in resolved["sets"] if s["kind"] == "top")
        assert (top["weight"], top["reps"]) == (top_w, top_r)
        backoffs = [s for s in resolved["sets"] if s["kind"] == "backoff"]
        assert len(backoffs) == backoff_sets
        assert backoffs[0]["weight"] == backoff_w
        # Deload sets are NOT the ×0.6 / halved-sets flat-progression path —
        # they're the plan's own authoritative deload row.
        assert resolved["working_set_count"] == 1 + backoff_sets

    @pytest.mark.parametrize("lift,top_w,top_r", [
        ("Newtech Flat", 270, "5"),
        ("Deadlift", 325, "3"),
        ("Smith Machine Press", 155, "4+"),
        ("Back Squat", 230, "4+"),
    ])
    def test_week_8_is_rep_pr(self, lift, top_w, top_r):
        resolved = resolve_set_plan(_spec_for(lift), week=8)
        assert resolved["note"] == "REP PR"
        top = next(s for s in resolved["sets"] if s["kind"] == "top")
        assert (top["weight"], top["reps"]) == (top_w, top_r)

    def test_warmups_come_first_in_index_order(self):
        resolved = resolve_set_plan(_spec_for("Back Squat"), week=1)
        kinds = [s["kind"] for s in resolved["sets"]]
        assert kinds == ["warmup", "warmup", "warmup", "warmup", "top",
                          "backoff", "backoff", "backoff"]
        assert [s["index"] for s in resolved["sets"]] == list(range(8))


class TestAdvanceRule:
    def test_first_session_uses_the_planned_week(self):
        """No last_top_set at all (or one with no plan_week) -> no hold."""
        resolved = resolve_set_plan(_spec_for("Back Squat"), week=2, last_top_set=None)
        assert resolved["held"] is False
        assert resolved["effective_week"] == 2

        legacy_set = {"rpe": 9.0, "reps": 1, "plan_week": None}  # predates this feature
        resolved = resolve_set_plan(_spec_for("Back Squat"), week=2, last_top_set=legacy_set)
        assert resolved["held"] is False
        assert resolved["effective_week"] == 2

    def test_a_dirty_top_set_holds_at_the_prior_week(self):
        """Week 1 top set was RPE 9 (> the RPE 8 cap) -> week 2 holds at week 1."""
        last_top_set = {"rpe": 9.0, "reps": 3, "plan_week": 1}
        resolved = resolve_set_plan(_spec_for("Back Squat"), week=2, last_top_set=last_top_set)
        assert resolved["held"] is True
        assert resolved["effective_week"] == 1
        assert resolved["requested_week"] == 2
        top = next(s for s in resolved["sets"] if s["kind"] == "top")
        assert top["weight"] == 225  # week 1's load, not week 2's 230
        assert "RPE 9" in resolved["note"]

    def test_reps_below_the_low_end_also_holds(self):
        """Week 1 top range is 2-4; 1 rep at RPE 7 still misses the rep target."""
        last_top_set = {"rpe": 7.0, "reps": 1, "plan_week": 1}
        resolved = resolve_set_plan(_spec_for("Back Squat"), week=2, last_top_set=last_top_set)
        assert resolved["held"] is True
        assert resolved["effective_week"] == 1

    def test_a_clean_top_set_advances_to_the_planned_week(self):
        last_top_set = {"rpe": 7.5, "reps": 3, "plan_week": 1}
        resolved = resolve_set_plan(_spec_for("Back Squat"), week=2, last_top_set=last_top_set)
        assert resolved["held"] is False
        assert resolved["effective_week"] == 2
        top = next(s for s in resolved["sets"] if s["kind"] == "top")
        assert top["weight"] == 230

    def test_deload_and_rep_pr_weeks_are_never_held(self):
        """Calendar-fixed weeks are authoritative regardless of the last top set."""
        dirty = {"rpe": 10.0, "reps": 1, "plan_week": 3}
        resolved = resolve_set_plan(_spec_for("Back Squat"), week=4, last_top_set=dirty)
        assert resolved["held"] is False
        assert resolved["effective_week"] == 4
        resolved = resolve_set_plan(_spec_for("Back Squat"), week=8, last_top_set=dirty)
        assert resolved["held"] is False
        assert resolved["effective_week"] == 8


class TestLegacyPathUnchanged:
    def test_no_set_plan_key_yields_nothing(self):
        spec = {"name": "Incline Press", "sets": 3, "reps": "6-10"}
        assert is_plan_driven(spec) is False
        resolved = resolve_set_plan(spec, week=1)
        assert resolved["sets"] == []

    def test_a_week_outside_the_table_holds_at_the_last_defined_week(self):
        resolved = resolve_set_plan(_spec_for("Back Squat"), week=99)
        assert resolved["requested_week"] == 8

    def test_no_week_yields_nothing(self):
        resolved = resolve_set_plan(_spec_for("Back Squat"), week=None)
        assert resolved["sets"] == []


class TestNextEntry:
    def test_warmups_are_consumed_before_working_sets(self):
        resolved = resolve_set_plan(_spec_for("Back Squat"), week=1)["sets"]
        assert next_entry(resolved, completed_warmup=0, completed_working=0)["kind"] == "warmup"
        assert next_entry(resolved, completed_warmup=3, completed_working=0)["kind"] == "warmup"
        assert next_entry(resolved, completed_warmup=4, completed_working=0)["kind"] == "top"

    def test_default_resolution_shows_warmups_first(self):
        """No `requested_kind` (display/prefill use) — warm-ups before working,
        the natural default order shown before the user picks a kind."""
        resolved = resolve_set_plan(_spec_for("Back Squat"), week=1)["sets"]
        assert next_entry(resolved, completed_warmup=0, completed_working=0) == resolved[0]
        assert next_entry(resolved, completed_warmup=0, completed_working=0)["kind"] == "warmup"

    def test_skip_warmups_resolves_against_the_working_sequence_only(self):
        """A5/A4 'Skip warm-ups': logging a WORKING set resolves against the
        working sequence directly — no warm-ups logged does not block it, and
        it is never confused for a warm-up regardless of warm-up count."""
        resolved = resolve_set_plan(_spec_for("Back Squat"), week=1)["sets"]
        entry = next_entry(resolved, completed_warmup=0, completed_working=0, requested_kind="working")
        assert entry["kind"] == "top"
        entry = next_entry(resolved, completed_warmup=0, completed_working=1, requested_kind="working")
        assert entry["kind"] == "backoff"

    def test_requested_warmup_kind_stops_once_warmups_are_done(self):
        resolved = resolve_set_plan(_spec_for("Back Squat"), week=1)["sets"]
        assert next_entry(resolved, 4, 0, requested_kind="warmup") is None

    def test_backoffs_advance_in_order_then_none_when_done(self):
        resolved = resolve_set_plan(_spec_for("Back Squat"), week=1)["sets"]
        assert next_entry(resolved, 4, 1)["kind"] == "backoff"
        assert next_entry(resolved, 4, 3)["kind"] == "backoff"
        assert next_entry(resolved, 4, 4) is None  # 1 top + 3 backoffs all done


class TestProgramWeekVsPhaseWeek:
    """Build 2 starts 2026-10-12 as phase-week 1 but program-week 5 — the
    set_plan table is keyed by program week, so this distinction matters."""

    def test_build_2_start_is_program_week_5(self, db):
        from datetime import date
        # program starts 2026-09-14 (week 1); 4 weeks later (28 days) is week 5.
        assert program_week(db, "prog-week-test", date(2026, 10, 12)) == 5

    @pytest.fixture
    def db(self):
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        session = sessionmaker(bind=engine)()
        session.execute(text("""
            CREATE TABLE fitness_program (id TEXT PRIMARY KEY, user_id TEXT,
                                          is_active BOOLEAN, start_date DATE)
        """))
        session.execute(text(
            "INSERT INTO fitness_program VALUES ('p1', 'prog-week-test', 1, '2026-09-14')"))
        session.commit()
        try:
            yield session
        finally:
            session.close()
            engine.dispose()
