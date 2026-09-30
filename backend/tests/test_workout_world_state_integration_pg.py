"""End-to-end proof: workout.* events through the REAL writer -> coordinator
-> reducer pipeline, into the maintained WorldThread/WorldFact projections,
read back by chat_facts.render_world_state_core() — the living-world-context
plan's workout-lifecycle proving step. Real Postgres, no mocks: this is the
same code path a workout started/finished while every client is closed
actually goes through.

Run inside the backend container:

    docker compose exec -T backend pytest tests/test_workout_world_state_integration_pg.py
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


def _pg_available() -> bool:
    return os.getenv("DATABASE_URL", "").startswith("postgresql")


requires_pg = pytest.mark.skipif(
    not _pg_available(), reason="needs the PostgreSQL dev database (run inside the backend container)"
)


@pytest.fixture(autouse=True)
def _world_events_enabled(monkeypatch):
    # conftest.py disables world-event writes by default for the rest of the
    # suite ("No current test asserts on world_event; one that wants to can
    # re-enable this itself.") — this is that test.
    monkeypatch.setenv("WORLD_EVENTS_ENABLED", "true")
    # This container's Celery workers are live and real (this is a shared
    # dev deployment, not an isolated test sandbox) — writer.py's
    # after_commit hook would otherwise hand every event this test commits
    # to the REAL "critical"/"cognitive" queues, racing this test's own
    # direct, synchronous process_one() calls against a live background
    # worker. Disabling dispatch keeps this test's outcome deterministic
    # and keeps it from touching production task queues at all — the
    # "disabled production task dispatch" isolation the plan requires for
    # integration tests. process_one() is still called directly below, so
    # reduction itself is exercised for real; only the async hand-off is not.
    from app.celery_app import celery_app
    monkeypatch.setattr(celery_app, "send_task", lambda *a, **kw: None)


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
    uid = f"test-workout-{uuid.uuid4()}"
    yield uid
    # Reuse `pg`'s own connection rather than opening a second one: pytest
    # tears fixtures down LIFO, so a fresh SessionLocal() here would run its
    # DELETE while `pg`'s own transaction (from the test body's last query)
    # is still open on a DIFFERENT connection — no locks are actually held
    # across them, but the two idle/uncommitted transactions raced pg_stat
    # -level lock waits in practice on this shared box. One connection, one
    # rollback before the delete, no race.
    pg.rollback()
    pg.execute(text("""
        DELETE FROM world_event_processing
        WHERE event_id IN (SELECT event_id FROM world_event WHERE user_id = :u)
    """), {"u": uid})
    for table in ("world_event", "world_thread", "world_fact", "world_snapshot"):
        pg.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": uid})
    pg.commit()


def _emit(pg, user_id, kind, session_id, *, dedupe_key, title="Workout", occurred_at=None):
    from app.services.world_state.writer import append_world_event
    row = append_world_event(
        pg, user_id=user_id, kind=kind, source="test",
        aggregate_type="workout_session", aggregate_id=session_id,
        dedupe_key=dedupe_key, occurred_at=occurred_at,
        payload={"session_id": session_id, "title": title, "name": title},
    )
    pg.commit()
    return row


def _emit_and_process(pg, user_id, kind, session_id, **kw):
    from app.services.world_state.coordinator import process_one
    row = _emit(pg, user_id, kind, session_id, **kw)
    assert row is not None, "WORLD_EVENTS_ENABLED must be on for this test"
    return process_one(pg, row.event_id)


@requires_pg
class TestWorkoutLifecycle:
    def test_a_started_workout_shows_in_progress(self, pg, user_id):
        from app.services.world_state.chat_facts import render_world_state_core

        morning_id = str(uuid.uuid4())
        _emit_and_process(
            pg, user_id, "workout.started", morning_id,
            dedupe_key=f"workout-started:{morning_id}", title="Morning Upper Body",
        )

        core = render_world_state_core(pg, user_id)
        assert "Workout in progress: Morning Upper Body" in core

    def test_morning_completes_then_evening_starts_without_confusion(self, pg, user_id):
        """The plan's named scenario: a morning workout followed by an
        evening workout. The evening session must read as current; the
        morning session must not resurface as still in progress, and must
        not vanish either (it remains history)."""
        from app.services.world_state.chat_facts import render_world_state_core

        morning_id = str(uuid.uuid4())
        evening_id = str(uuid.uuid4())

        _emit_and_process(pg, user_id, "workout.started", morning_id,
                           dedupe_key=f"workout-started:{morning_id}", title="Morning Upper Body")
        _emit_and_process(pg, user_id, "workout.completed", morning_id,
                           dedupe_key=f"workout-completed:{morning_id}", title="Morning Upper Body")

        core = render_world_state_core(pg, user_id)
        assert "Last workout: Morning Upper Body" in core
        assert "in progress" not in core.lower()

        _emit_and_process(pg, user_id, "workout.started", evening_id,
                           dedupe_key=f"workout-started:{evening_id}", title="Evening Legs")

        core = render_world_state_core(pg, user_id)
        assert "Workout in progress: Evening Legs" in core
        # Separately identified sessions, separately keyed threads — the
        # morning session's own completion is unaffected and must not be
        # what's shown as "current" now that a different session is open.
        assert "Morning Upper Body" not in core

    def test_duplicate_start_event_creates_only_one_session(self, pg, user_id):
        """A retried client command resends the identical event — same
        dedupe_key, exactly as workout_command_service constructs it for a
        replayed `command_id`."""
        from app.services.world_state.chat_facts import render_world_state_core

        session_id = str(uuid.uuid4())
        dk = f"workout-started:{session_id}"

        _emit_and_process(pg, user_id, "workout.started", session_id, dedupe_key=dk, title="Leg Day")
        _emit_and_process(pg, user_id, "workout.started", session_id, dedupe_key=dk, title="Leg Day")

        count = pg.execute(
            text("SELECT count(*) FROM world_thread WHERE user_id = :u AND thread_key = :k"),
            {"u": user_id, "k": f"workout:{session_id}"},
        ).scalar()
        assert count == 1
        core = render_world_state_core(pg, user_id)
        assert core.count("Workout in progress") == 1

    def test_a_delayed_out_of_order_start_does_not_reopen_a_completed_session(self, pg, user_id):
        """Living-world-context plan: 'late-arriving old events must not
        roll state backward.' Per-event Celery dispatch (writer.py's
        after_commit hook) has no cross-event ordering guarantee, so the
        'completed' event for a session can be reduced before its own
        'started' event if delivery is delayed. The reducer must apply
        state by event sequence, not by arrival order."""
        from app.services.world_state.coordinator import process_one
        from app.models.world_model import WorldFact
        from sqlalchemy import select

        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        started = _emit(
            pg, user_id, "workout.started", session_id,
            dedupe_key=f"workout-started:{session_id}", title="Leg Day", occurred_at=now,
        )
        completed = _emit(
            pg, user_id, "workout.completed", session_id,
            dedupe_key=f"workout-completed:{session_id}", title="Leg Day",
            occurred_at=now + timedelta(minutes=45),
        )
        # started.sequence < completed.sequence (assigned in commit order),
        # but PROCESS them in the opposite order — the delayed-delivery case.
        assert started.sequence < completed.sequence

        process_one(pg, completed.event_id)
        process_one(pg, started.event_id)

        from app.services.world_state.chat_facts import render_world_state_core
        core = render_world_state_core(pg, user_id)
        assert "Last workout: Leg Day" in core
        assert "Workout in progress" not in core

        # The state fact must also reflect the newer (completed) event, not
        # have been silently overwritten back to "started" by the stale one.
        fact = pg.execute(
            select(WorldFact).where(
                WorldFact.user_id == user_id,
                WorldFact.fact_key == f"workout:{session_id}:state",
                WorldFact.status == "active",
            )
        ).scalar_one_or_none()
        assert fact is not None
        assert fact.value.get("kind") == "workout.completed"

    def test_no_open_or_recent_session_renders_nothing(self, pg, user_id):
        from app.services.world_state.chat_facts import render_world_state_core
        assert render_world_state_core(pg, user_id) == ""


@requires_pg
class TestExternalEventAppearsOnNextTurn:
    """Living-world-context plan, Turn 3 item 2's second scenario, kept
    separate from the mid-turn-refresh mechanism on purpose: an event that
    happens BETWEEN two user messages (not mid-tool-loop within one turn)
    reaching the next turn's actual outgoing payload — the same
    'David closes the app, does a workout, opens it again' case the plan
    names, proven against assemble_non_local_provider_messages's real
    all_messages, not render_world_state_core alone."""

    def test_a_workout_started_between_messages_reaches_the_next_turns_actual_payload(self, pg, user_id):
        from app.schemas.chat import ChatMessage
        from app.services.chat_assembly import assemble_non_local_provider_messages
        from app.services.world_state.chat_facts import render_world_state_core

        def _turn_payload(user_text: str) -> str:
            core = render_world_state_core(pg, user_id)
            result = assemble_non_local_provider_messages(
                full_sys="You are Sara, David's assistant.",
                dialogue_block="", world_state_core=core,
                datetime_line="It's Thursday, 6pm ET.",
                conversation_history=[],
                merged_request_messages=[ChatMessage(role="user", content=user_text)],
            )
            return result["all_messages"][0].content

        # Turn 1: nothing has happened yet.
        turn1 = _turn_payload("what's up")
        assert "Workout in progress" not in turn1

        # External event, entirely outside this "conversation" — the exact
        # thing a HealthKit/Watch-triggered start, or a workout begun from
        # the web app while the phone client is closed, produces.
        session_id = str(uuid.uuid4())
        _emit_and_process(
            pg, user_id, "workout.started", session_id,
            dedupe_key=f"workout-started:{session_id}", title="Evening Legs",
        )

        # Turn 2: a fresh render (exactly what main_simple.py does at the
        # start of every turn) must carry the new fact into the real
        # outgoing payload, with no code path in between needing to know an
        # event happened.
        turn2 = _turn_payload("how's it going")
        assert "Workout in progress: Evening Legs" in turn2
