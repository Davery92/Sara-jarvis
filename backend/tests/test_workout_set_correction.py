"""Correcting a workout set in place — reliable-assistant plan Phase C4.

The plan lists the coherent operations to expose: *"correct food quantity,
correct workout set…"* Food got its correction tool; the workout set was the one
still missing, and the 2026-09-29 correction called that out as unfinished work.

Why it matters more than the food one, not less: `workout_log` is what
`progressive_overload.py` reads (see the "progression single brain" note). A
corrected COPY leaves the wrong set in the history, so the next prescription is
computed from a set David never did.
"""
import uuid

import pytest
from sqlalchemy import text

from app.tools.fitness.workout_log import WorkoutLogCorrectTool


def _db():
    from app.db.session import get_db
    return next(get_db())


@pytest.fixture
def owner():
    from app.models.user import User
    db = _db()
    try:
        u = User(email=f"sets-{uuid.uuid4().hex[:8]}@test.invalid", password_hash="x")
        db.add(u)
        db.commit()
        db.refresh(u)
        return str(u.id)
    finally:
        db.close()


@pytest.fixture
def a_set(owner):
    """One real logged set: 225lbs x 3 @ RPE 8."""
    db = _db()
    try:
        workout_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO workout (id, user_id, title, phase, week, day_of_week,
                                 status, prescription, created_at)
            VALUES (:id, :uid, 'Workout - test', 'Ad-hoc', 1, 0, 'completed', '{}', NOW())
        """), {"id": workout_id, "uid": owner})
        log_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO workout_log (id, workout_id, user_id, exercise_id, set_index,
                                     weight, reps, rpe, notes, session_date,
                                     session_time, created_at)
            VALUES (:id, :wid, :uid, NULL, 1, 225, 3, 8, '', CURRENT_DATE, NOW(), NOW())
        """), {"id": log_id, "wid": workout_id, "uid": owner})
        db.commit()
        return log_id
    finally:
        db.close()


def read_set(log_id):
    db = _db()
    try:
        return db.execute(text(
            "SELECT set_index, weight, reps, rpe, notes FROM workout_log WHERE id = :id"
        ), {"id": log_id}).mappings().first()
    finally:
        db.close()


def count_sets(owner):
    db = _db()
    try:
        return db.execute(text(
            "SELECT count(*) FROM workout_log WHERE user_id = :uid"
        ), {"uid": owner}).scalar()
    finally:
        db.close()


@pytest.mark.asyncio
class TestItCorrectsInPlace:
    async def test_reps_are_corrected_and_no_second_set_appears(self, owner, a_set):
        result = await WorkoutLogCorrectTool().execute(owner, log_id=a_set, reps=5)
        assert result.success, result.message
        row = read_set(a_set)
        assert row["reps"] == 5
        assert float(row["weight"]) == 225
        assert count_sets(owner) == 1, "a correction must not leave a second set behind"

    async def test_weight_is_corrected(self, owner, a_set):
        result = await WorkoutLogCorrectTool().execute(owner, log_id=a_set, weight=235)
        assert result.success, result.message
        assert float(read_set(a_set)["weight"]) == 235

    async def test_several_fields_at_once(self, owner, a_set):
        result = await WorkoutLogCorrectTool().execute(
            owner, log_id=a_set, weight=235, reps=5, rpe=9)
        assert result.success, result.message
        row = read_set(a_set)
        assert (float(row["weight"]), row["reps"], row["rpe"]) == (235.0, 5, 9)

    async def test_the_message_reads_the_row_back(self, owner, a_set):
        """The summary states what the TABLE holds afterwards, not what the
        arguments asked for — the same rule the grounding layer applies."""
        result = await WorkoutLogCorrectTool().execute(owner, log_id=a_set, reps=5)
        assert "225lbs x 5 reps" in result.message, result.message
        assert "RPE 8" in result.message

    async def test_the_before_state_is_reported(self, owner, a_set):
        result = await WorkoutLogCorrectTool().execute(owner, log_id=a_set, reps=5)
        assert result.data["before"]["reps"] == 3
        assert result.data["after"]["reps"] == 5


@pytest.mark.asyncio
class TestItRefusesTruthfully:
    async def test_a_set_that_does_not_exist(self, owner):
        result = await WorkoutLogCorrectTool().execute(
            owner, log_id=str(uuid.uuid4()), reps=5)
        assert not result.success
        assert "nothing was changed" in result.message

    async def test_another_owners_set_is_untouchable(self, owner, a_set):
        from app.models.user import User
        db = _db()
        try:
            other = User(email=f"sets-{uuid.uuid4().hex[:8]}@test.invalid",
                         password_hash="x")
            db.add(other)
            db.commit()
            other_id = str(other.id)
        finally:
            db.close()
        result = await WorkoutLogCorrectTool().execute(other_id, log_id=a_set, reps=99)
        assert not result.success
        assert read_set(a_set)["reps"] == 3, "the row must be untouched"

    async def test_nothing_to_correct_is_said_plainly(self, owner, a_set):
        result = await WorkoutLogCorrectTool().execute(owner, log_id=a_set)
        assert not result.success
        assert "say what changed" in result.message

    async def test_a_no_op_correction_says_so_rather_than_claiming_a_change(self, owner, a_set):
        """The truthful-no-op rule this task applied to lists and reminders:
        reporting "fixed" when the row already read that way is a false success
        the grounding layer would have to repair."""
        result = await WorkoutLogCorrectTool().execute(owner, log_id=a_set, reps=3)
        assert not result.success
        assert "already reads that way" in result.message

    async def test_an_impossible_rpe_is_refused(self, owner, a_set):
        result = await WorkoutLogCorrectTool().execute(owner, log_id=a_set, rpe=14)
        assert not result.success
        assert read_set(a_set)["rpe"] == 8

    async def test_zero_weight_is_refused_rather_than_written(self, owner, a_set):
        result = await WorkoutLogCorrectTool().execute(owner, log_id=a_set, weight=0)
        assert not result.success
        assert float(read_set(a_set)["weight"]) == 225


class TestItIsWiredIn:
    def test_the_registry_offers_it(self):
        from app.tools.registry import tool_registry
        assert "workout_log_correct" in tool_registry.tools

    def test_the_contract_reads_it_as_an_update_on_the_fitness_domain(self):
        from app.services.operation_contract import (
            OperationKind, domain_for_tool, operation_kind_for,
        )
        assert domain_for_tool("workout_log_correct") == "fitness"
        assert operation_kind_for("workout_log_correct", None) is OperationKind.UPDATE

    def test_a_fitness_correction_retains_it(self):
        """The active-domain retention this task added must actually offer it —
        that was the live food failure ("That was actually 150 grams, not 100."
        classified GENERAL, so no fitness tool was on the menu)."""
        from tests.test_active_domain_tool_retention import would_retain
        retained = would_retain("Actually that was 5 reps, not 3.",
                                ["workout_log_create"])
        assert "workout_log_correct" in retained, retained
