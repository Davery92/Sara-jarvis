"""Regression suite for the existing phone workout flow (§13 Phase 0, §14.1).

`workout_session_service`'s mutating methods are now thin adapters over
`workout_command_service` (§6.5). That refactor is only safe if the shape the
current iOS app reads is byte-for-byte what it was — the app parses
`coaching_feedback`, `next_set.suggested_weight`, `logged.set_number` and
friends directly, so a renamed key is a broken workout, not a failed test.

Every action `WorkoutModeContext` can take has a test here. They run against
real PostgreSQL for the same reason as `test_workout_command_service`.

    docker compose exec -T backend pytest tests/test_workout_session_legacy_compat.py
"""

import json
import os
import uuid

import pytest
from sqlalchemy import text
from tests.conftest import WORLD_MODEL_CLEANUP_STATEMENTS

pytestmark = pytest.mark.integration

requires_pg = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="needs the PostgreSQL dev database (run inside the backend container)",
)

EXERCISES = [
    {"name": "Overhead Press", "sets": 2, "reps": "8-10", "rpe_target": 8, "rest_seconds": 120},
    {"name": "Lat Pulldown", "sets": 2, "reps": "10-12", "rpe_target": 8, "rest_seconds": 90},
]


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
    pg.execute(text("INSERT INTO app_user (id, email, password_hash) VALUES (:id, :e, 'x')"),
               {"id": uid, "e": f"legacy-test-{uid}@example.invalid"})
    pg.commit()
    yield uid
    for stmt in (
        "DELETE FROM workout_log WHERE user_id = :uid",
        "DELETE FROM exercise_pr WHERE user_id = :uid",
        "DELETE FROM workout_session_event WHERE user_id = :uid",
        "DELETE FROM workout_session_command WHERE user_id = :uid",
        "DELETE FROM workout_adjustment_proposal WHERE user_id = :uid",
        "DELETE FROM workout_approved_policy WHERE user_id = :uid",
        "DELETE FROM active_workout_session WHERE user_id = :uid",
        "DELETE FROM workout WHERE user_id = :uid",
        "DELETE FROM fitness_template WHERE user_id = :uid",
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


@pytest.fixture
def template(pg, user_id):
    tid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_template (id, user_id, name, exercises)
        VALUES (:id, :uid, 'Push A', CAST(:ex AS jsonb))
    """), {"id": tid, "uid": user_id, "ex": json.dumps(EXERCISES)})
    pg.commit()
    return tid


@pytest.fixture
def svc():
    from app.services.workout_session_service import workout_session_service
    return workout_session_service


@pytest.fixture
def no_llm(monkeypatch):
    """Pin coaching to the deterministic fallback.

    The legacy path still awaits the sentence inline, and these tests are about
    response *shape*, not about whether Qwen was reachable.
    """
    from app.services.workout_session_service import workout_session_service as legacy

    async def fake(**kwargs):
        return {"text": "Good set.", "rest_seconds": kwargs.get("rest_seconds", 0),
                "weight_adjustment": None, "workout_complete": kwargs.get("workout_complete", False)}

    monkeypatch.setattr(legacy, "_generate_set_feedback", fake)


@requires_pg
@pytest.mark.asyncio
async def test_start_workout_returns_the_legacy_session_shape(pg, svc, user_id, template):
    result = await svc.start_workout(user_id, template, pg)

    assert set(result) >= {
        "id", "status", "started_at", "template_name", "workout_snapshot",
        "current_exercise_index", "current_set_index", "total_sets_completed",
    }
    assert result["status"] == "active"
    assert result["template_name"] == "Push A"
    assert result["current_exercise_index"] == 0
    assert result["total_sets_completed"] == 0

    snapshot = result["workout_snapshot"]
    assert snapshot["total_sets"] == 4
    ex = snapshot["exercises"][0]
    # The keys WorkoutPanel renders from must all survive the refactor.
    for key in ("name", "sets", "reps", "rpe_target", "rest_seconds",
                "suggested_weight", "progression_note", "last_session",
                "metric_type", "is_per_side", "superset_group", "set_technique"):
        assert key in ex, f"snapshot exercise lost {key}"


@requires_pg
@pytest.mark.asyncio
async def test_start_still_replaces_an_active_workout_while_v2_is_off(pg, svc, user_id, template):
    """Rollback path (§16.2): with the flag off, Start behaves as it always has."""
    t2 = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_template (id, user_id, name, exercises)
        VALUES (:id, :uid, 'Pull A', CAST(:ex AS jsonb))
    """), {"id": t2, "uid": user_id, "ex": json.dumps(EXERCISES)})
    pg.commit()

    first = await svc.start_workout(user_id, template, pg)
    second = await svc.start_workout(user_id, t2, pg)

    assert second["id"] != first["id"]
    assert pg.execute(text(
        "SELECT status FROM active_workout_session WHERE id = :s"
    ), {"s": first["id"]}).scalar() == "abandoned"


@requires_pg
@pytest.mark.asyncio
async def test_get_active_session_shape(pg, svc, user_id, template):
    await svc.start_workout(user_id, template, pg)
    session = await svc.get_active_session(user_id, pg)

    assert session["status"] == "active"
    assert session["sets_logged"] == []
    assert session["workout_snapshot"]["exercises"][0]["completed_sets"] == 0
    # Additive fields the cross-device UI needs; must not displace the old ones.
    assert session["version"] == 1
    assert "healthkit_state" in session


@requires_pg
@pytest.mark.asyncio
async def test_log_set_returns_the_legacy_response(pg, svc, user_id, template, no_llm):
    await svc.start_workout(user_id, template, pg)
    result = await svc.log_set(user_id, 95, 9, None, "moderate", None, pg)

    assert result["success"] is True
    assert result["logged"] == {
        "exercise": "Overhead Press", "set_number": 1, "weight": 95.0, "reps": 9, "rpe": 7,
    }
    assert result["coaching_feedback"] == "Good set."
    assert result["total_sets_completed"] == 1
    assert result["total_volume"] == pytest.approx(855.0)

    next_set = result["next_set"]
    assert set(next_set) == {
        "exercise", "set_number", "suggested_weight", "workout_complete",
        "exercise_complete", "weight_adjustment", "rest_seconds",
    }
    assert next_set["exercise"] == "Overhead Press"
    assert next_set["set_number"] == 2
    assert next_set["workout_complete"] is False


@requires_pg
@pytest.mark.asyncio
async def test_log_set_advances_to_the_next_exercise(pg, svc, user_id, template, no_llm):
    await svc.start_workout(user_id, template, pg)
    await svc.log_set(user_id, 95, 9, None, None, None, pg)
    result = await svc.log_set(user_id, 95, 8, None, None, None, pg)

    assert result["next_set"]["exercise_complete"] is True
    assert result["next_set"]["exercise"] == "Lat Pulldown"
    assert result["next_set"]["set_number"] == 1


@requires_pg
@pytest.mark.asyncio
async def test_log_set_detects_a_pr(pg, svc, user_id, template, no_llm):
    await svc.start_workout(user_id, template, pg)
    result = await svc.log_set(user_id, 135, 5, None, None, None, pg)

    assert result["pr"] is not None and result["pr"]["is_pr"] is True
    assert pg.execute(text(
        "SELECT is_pr FROM workout_log WHERE user_id = :u"
    ), {"u": user_id}).scalar() is True


@requires_pg
@pytest.mark.asyncio
async def test_log_set_defaults_weight_and_reps_from_the_snapshot(pg, svc, user_id, template, no_llm):
    """The chat-side "just log it" path passes nothing but a feeling."""
    await svc.start_workout(user_id, template, pg)
    result = await svc.log_set(user_id, None, None, None, "hard", None, pg)

    assert result["logged"]["rpe"] == 9
    # "8-10" -> lower bound + 1, unchanged from the original implementation.
    assert result["logged"]["reps"] == 9


@requires_pg
@pytest.mark.asyncio
async def test_skip_exercise_shape(pg, svc, user_id, template):
    await svc.start_workout(user_id, template, pg)
    result = await svc.skip_exercise(user_id, pg)

    assert result == {
        "success": True, "skipped_exercise": "Overhead Press",
        "next_exercise": "Lat Pulldown", "workout_complete": False,
    }


@requires_pg
@pytest.mark.asyncio
async def test_skipped_exercise_can_be_returned_to(pg, svc, user_id, template, no_llm):
    await svc.start_workout(user_id, template, pg)
    await svc.skip_exercise(user_id, pg)
    await svc.log_set(user_id, 120, 12, None, None, None, pg)
    await svc.log_set(user_id, 120, 11, None, None, None, pg)

    # Pulldown is finished, so the cursor wraps back to the skipped press.
    session = await svc.get_active_session(user_id, pg)
    assert session["current_exercise_index"] == 0


@requires_pg
@pytest.mark.asyncio
async def test_select_exercise_shape(pg, svc, user_id, template):
    await svc.start_workout(user_id, template, pg)
    result = await svc.select_exercise(user_id, 1, pg)

    assert result["success"] is True
    assert result["current_exercise_index"] == 1
    assert result["current_set_index"] == 0
    assert result["exercise"] == "Lat Pulldown"


@requires_pg
@pytest.mark.asyncio
async def test_set_variant_shape_and_revert(pg, svc, user_id, template):
    await svc.start_workout(user_id, template, pg)

    result = await svc.set_exercise_variant(user_id, 0, "Smith Machine Press", pg)
    assert result["success"] is True
    assert result["variant"] == "Smith Machine Press"
    assert result["effective_name"] == "Smith Machine Press"
    assert "suggested_weight" in result and "last_session" in result

    reverted = await svc.set_exercise_variant(user_id, 0, "", pg)
    assert reverted["variant"] is None
    assert reverted["effective_name"] == "Overhead Press"


@requires_pg
@pytest.mark.asyncio
async def test_rest_timer_start_status_and_stop(pg, svc, user_id, template):
    await svc.start_workout(user_id, template, pg)

    started = await svc.start_rest_timer(user_id, 90, pg)
    assert started["success"] is True and started["duration_seconds"] == 90

    status = await svc.get_rest_timer_status(user_id, pg)
    assert status["is_active"] is True
    assert status["total_seconds"] == 90
    assert 0 < status["remaining_seconds"] <= 90

    await svc.stop_rest_timer(user_id, pg)
    assert (await svc.get_rest_timer_status(user_id, pg))["is_active"] is False


@requires_pg
@pytest.mark.asyncio
async def test_complete_workout_shape(pg, svc, user_id, template, no_llm):
    await svc.start_workout(user_id, template, pg)
    await svc.log_set(user_id, 95, 9, None, None, None, pg)

    result = await svc.complete_workout(user_id, pg)

    assert result["success"] is True
    assert result["session_id"]
    summary = result["summary"]
    assert set(summary) == {
        "workout_name", "duration_minutes", "total_sets", "total_volume",
        "exercises_completed", "heart_rate",
    }
    assert summary["workout_name"] == "Push A"
    assert summary["total_sets"] == 1
    assert await svc.get_active_session(user_id, pg) is None


@requires_pg
@pytest.mark.asyncio
async def test_abandon_workout_discards_logged_sets(pg, svc, user_id, template, no_llm):
    session = await svc.start_workout(user_id, template, pg)
    await svc.log_set(user_id, 95, 9, None, None, None, pg)

    result = await svc.abandon_workout(user_id, pg)

    assert result == {"success": True, "message": "Workout abandoned"}
    assert pg.execute(text(
        "SELECT COUNT(*) FROM workout_log WHERE active_session_id = :s"
    ), {"s": session["id"]}).scalar() == 0
    assert pg.execute(text(
        "SELECT COUNT(*) FROM workout WHERE id = :s"
    ), {"s": session["id"]}).scalar() == 0


@requires_pg
@pytest.mark.asyncio
async def test_abandon_with_no_active_workout_is_not_an_error(pg, svc, user_id):
    """The other device may already have ended it (§4.6)."""
    assert await svc.abandon_workout(user_id, pg) == {
        "success": True, "message": "No active workout",
    }


@requires_pg
@pytest.mark.asyncio
async def test_workout_context_still_renders_for_chat(pg, svc, user_id, template, no_llm):
    await svc.start_workout(user_id, template, pg)
    await svc.log_set(user_id, 95, 9, None, None, None, pg)

    context = await svc.get_workout_context(user_id, pg)
    assert "**Workout**: Push A" in context
    assert "### Current Exercise: Overhead Press" in context
    assert "Last Set Logged" in context
