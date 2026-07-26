"""Approval boundary with the v2 cutover enabled (§11, §6.8, §13 Phase 7).

With WORKOUT_COMMAND_V2_ENABLED on, progression stops being something Sara
applies and becomes something she proposes: the workout starts on the weight
David last actually lifted, and her new number waits for a yes. These tests
pin that behaviour, and the HealthKit ingestion link that stops one workout
being counted twice.

`_v2_enabled` is monkeypatched rather than flipping the real flag row — the
flag lives in shared `app_settings`, and a test must not leave the dev system
half cut over if it fails.

    docker compose exec -T backend pytest tests/test_workout_approval_enforcement.py
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

requires_pg = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="needs the PostgreSQL dev database (run inside the backend container)",
)

EXERCISES = [{"name": "Front Squat", "sets": 3, "reps": "5", "rpe_target": 8, "rest_seconds": 180}]


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
               {"id": uid, "e": f"approval-test-{uid}@example.invalid"})
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
        "DELETE FROM external_workout WHERE user_id = :uid",
        "DELETE FROM fitness_template WHERE user_id = :uid",
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
        VALUES (:id, :uid, 'Legs A', CAST(:ex AS jsonb))
    """), {"id": tid, "uid": user_id, "ex": json.dumps(EXERCISES)})
    pg.commit()
    return tid


@pytest.fixture
def svc():
    from app.services.workout_command_service import workout_command_service
    return workout_command_service


@pytest.fixture
def v2_on(monkeypatch):
    import app.services.workout_command_service as mod
    monkeypatch.setattr(mod, "_v2_enabled", lambda: True)


def _history(pg, user_id, exercise, weight, reps, rpe, days_ago):
    """A completed session in the past, so progression has something to read."""
    wid = str(uuid.uuid4())
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    pg.execute(text("""
        INSERT INTO workout (id, user_id, title, status) VALUES (:id, :uid, 'past', 'completed')
    """), {"id": wid, "uid": user_id})
    for i in range(3):
        pg.execute(text("""
            INSERT INTO workout_log (
                id, workout_id, user_id, exercise_id, set_index, weight, reps, rpe,
                session_date, session_time
            ) VALUES (:id, :wid, :uid, :ex, :si, :w, :r, :rpe, :d, :t)
        """), {"id": str(uuid.uuid4()), "wid": wid, "uid": user_id, "ex": exercise,
               "si": i + 1, "w": weight, "r": reps, "rpe": rpe,
               "d": when.date(), "t": when})
    pg.commit()


@requires_pg
@pytest.mark.asyncio
async def test_start_prefills_the_approved_weight_not_the_progression(
    pg, svc, user_id, template, v2_on
):
    """§6.8 — calculation is not application."""
    _history(pg, user_id, "Front Squat", 185, 5, 7, days_ago=4)

    proj = (await svc.start(pg, user_id, template))["projection"]
    ex = proj["exercises"][0]

    # Last session was easy, so Sara wants more. She may not just take it.
    assert ex["calculated_suggestion"] > ex["approved_weight"]
    assert ex["approved_weight"] == 185.0
    # And what the phone UI actually lifts from is the approved value.
    assert ex["approved_weight"] == proj["current_exercise"]["approved_weight"]


@requires_pg
@pytest.mark.asyncio
async def test_start_raises_the_progression_as_a_pending_proposal(
    pg, svc, user_id, template, v2_on
):
    _history(pg, user_id, "Front Squat", 185, 5, 7, days_ago=4)
    proj = (await svc.start(pg, user_id, template))["projection"]

    pending = proj["pending_proposal"]
    assert pending is not None
    assert pending["kind"] == "exercise_weight"
    assert pending["current_value"]["weight"] == 185.0
    assert pending["proposed_value"]["weight"] > 185.0


@requires_pg
@pytest.mark.asyncio
async def test_approving_the_start_proposal_moves_only_that_exercise(
    pg, svc, user_id, template, v2_on
):
    _history(pg, user_id, "Front Squat", 185, 5, 7, days_ago=4)
    start = await svc.start(pg, user_id, template)
    proj = start["projection"]
    sid, pid = proj["session_id"], proj["pending_proposal"]["proposal_id"]
    proposed = proj["pending_proposal"]["proposed_value"]["weight"]

    result = await svc.execute(pg, user_id, {
        "schema_version": 1, "command_id": str(uuid.uuid4()), "session_id": sid,
        "expected_version": proj["version"], "origin_device": "watch",
        "kind": "approve_proposal", "payload": {"proposal_id": pid},
    })

    assert result["applied"] is True
    assert result["projection"]["exercises"][0]["approved_weight"] == proposed


@requires_pg
@pytest.mark.asyncio
async def test_completion_proposes_next_session_weights_without_applying(
    pg, svc, user_id, template, v2_on
):
    """§6.8 — approve progression outside the gym, not at the next start."""
    _history(pg, user_id, "Front Squat", 185, 5, 7, days_ago=4)
    sid = (await svc.start(pg, user_id, template))["projection"]["session_id"]

    await svc.execute(pg, user_id, {
        "schema_version": 1, "command_id": str(uuid.uuid4()), "session_id": sid,
        "expected_version": 1, "origin_device": "phone",
        "kind": "complete", "payload": {},
    })

    proposals = svc.list_proposals(pg, user_id, status="pending")
    next_session = [p for p in proposals if p["kind"] == "next_session_weight"]
    assert next_session, "expected a next-session progression proposal"
    assert next_session[0]["scope"]["exercise"] == "Front Squat"
    assert next_session[0]["proposed_value"]["weight"] != next_session[0]["current_value"]["weight"]


@requires_pg
@pytest.mark.asyncio
async def test_without_the_flag_progression_is_applied_as_before(pg, svc, user_id, template):
    """Rollback path: flag off means today's behaviour, no proposal gate."""
    _history(pg, user_id, "Front Squat", 185, 5, 7, days_ago=4)
    proj = (await svc.start(pg, user_id, template))["projection"]
    ex = proj["exercises"][0]

    assert ex["approved_weight"] == ex["calculated_suggestion"]
    assert proj["pending_proposal"] is None


@requires_pg
@pytest.mark.asyncio
async def test_abandon_supersedes_pending_proposals(pg, svc, user_id, template, v2_on):
    _history(pg, user_id, "Front Squat", 185, 5, 7, days_ago=4)
    start = await svc.start(pg, user_id, template)
    sid = start["projection"]["session_id"]
    pid = start["projection"]["pending_proposal"]["proposal_id"]

    await svc.execute(pg, user_id, {
        "schema_version": 1, "command_id": str(uuid.uuid4()), "session_id": sid,
        "expected_version": 1, "origin_device": "phone", "kind": "abandon", "payload": {},
    })

    assert pg.execute(text(
        "SELECT status FROM workout_adjustment_proposal WHERE id = :p"
    ), {"p": pid}).scalar() == "superseded"


# ────────────────────────────────────────────────────────────────────────
# HealthKit ingestion linking (§6.4)
# ────────────────────────────────────────────────────────────────────────

@requires_pg
def test_ingestion_links_a_workout_that_names_its_sara_session(pg, user_id, template):
    from app.routes.health_metrics import WorkoutInput, _resolve_sara_session, SARA_SESSION_METADATA_KEY

    sid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO active_workout_session (id, user_id, template_id, status, workout_snapshot)
        VALUES (:id, :uid, :tid, 'completed', CAST('{}' AS jsonb))
    """), {"id": sid, "uid": user_id, "tid": template})
    pg.commit()

    w = WorkoutInput(
        external_id=str(uuid.uuid4()), activity_type="50",
        started_at="2026-07-26T10:00:00Z", ended_at="2026-07-26T11:00:00Z",
        duration_seconds=3600, workout_metadata={SARA_SESSION_METADATA_KEY: sid},
    )
    assert _resolve_sara_session(pg, user_id, w) == sid


@requires_pg
def test_ingestion_ignores_a_session_id_belonging_to_someone_else(pg, user_id):
    """A client-supplied id is a claim, not a fact."""
    from app.routes.health_metrics import WorkoutInput, _resolve_sara_session, SARA_SESSION_METADATA_KEY

    w = WorkoutInput(
        external_id=str(uuid.uuid4()), activity_type="50",
        started_at="2026-07-26T10:00:00Z", ended_at="2026-07-26T11:00:00Z",
        duration_seconds=3600,
        workout_metadata={SARA_SESSION_METADATA_KEY: str(uuid.uuid4())},
    )
    assert _resolve_sara_session(pg, user_id, w) is None


@requires_pg
def test_ingestion_falls_back_to_the_uuid_the_session_recorded(pg, user_id, template):
    from app.routes.health_metrics import WorkoutInput, _resolve_sara_session

    sid, hk = str(uuid.uuid4()), str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO active_workout_session (
            id, user_id, template_id, status, workout_snapshot, healthkit_workout_uuid
        ) VALUES (:id, :uid, :tid, 'completed', CAST('{}' AS jsonb), :hk)
    """), {"id": sid, "uid": user_id, "tid": template, "hk": hk})
    pg.commit()

    w = WorkoutInput(
        external_id=hk, activity_type="50",
        started_at="2026-07-26T10:00:00Z", ended_at="2026-07-26T11:00:00Z",
        duration_seconds=3600,
    )
    assert _resolve_sara_session(pg, user_id, w) == sid


@requires_pg
def test_ingestion_leaves_an_ordinary_watch_workout_unlinked(pg, user_id):
    from app.routes.health_metrics import WorkoutInput, _resolve_sara_session

    w = WorkoutInput(
        external_id=str(uuid.uuid4()), activity_type="52",
        started_at="2026-07-26T10:00:00Z", ended_at="2026-07-26T10:30:00Z",
        duration_seconds=1800,
    )
    assert _resolve_sara_session(pg, user_id, w) is None
