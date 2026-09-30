"""Living-world-context plan §12 acceptance matrix: 'Worker/broker outage
and restart | Durable events recover exactly once in effect; failed gaps
remain visible; snapshot completeness is not inferred from max sequence.'

append_world_event() always writes the WorldEvent + a 'pending'
WorldEventProcessing row in the SAME transaction as the domain mutation;
the after_commit hook's immediate Celery dispatch is only an
acceleration, never the source of durability. This proves the recovery
path: events that were committed but never picked up (Celery/Redis down at
commit time) are exactly what drain_pending()/catch_up_user() are for.

Run inside the backend container:

    docker compose exec -T backend pytest tests/test_worker_broker_recovery_pg.py
"""
import os
import uuid

import pytest
from sqlalchemy import func, select, text

pytestmark = pytest.mark.integration


def _pg_available() -> bool:
    return os.getenv("DATABASE_URL", "").startswith("postgresql")


requires_pg = pytest.mark.skipif(
    not _pg_available(), reason="needs the PostgreSQL dev database (run inside the backend container)"
)


@pytest.fixture(autouse=True)
def _world_events_enabled(monkeypatch):
    monkeypatch.setenv("WORLD_EVENTS_ENABLED", "true")
    from app.celery_app import celery_app
    # Simulates the broker being down: dispatch never happens, so nothing
    # but drain_pending()/catch_up_user() can ever process these events.
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
    uid = f"test-recovery-{uuid.uuid4()}"
    yield uid
    pg.rollback()
    pg.execute(text("""
        DELETE FROM world_event_processing
        WHERE event_id IN (SELECT event_id FROM world_event WHERE user_id = :u)
    """), {"u": uid})
    for table in ("world_event", "world_thread", "world_fact", "world_snapshot"):
        pg.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": uid})
    pg.commit()


def _append(pg, user_id, kind, place_id, dedupe_key):
    from app.services.world_state.writer import append_world_event
    row = append_world_event(
        pg, user_id=user_id, kind=kind, source="test",
        aggregate_type="location", aggregate_id=place_id, dedupe_key=dedupe_key,
        payload={"place_id": place_id, "label": "the office", "place_type": "work"},
    )
    pg.commit()
    return row


@requires_pg
class TestBrokerOutageRecovery:
    def test_events_left_pending_are_picked_up_by_drain(self, pg, user_id):
        """Broker down at commit time: three events land as durable rows
        with nothing dispatched. A later drain (the periodic
        drain_pending_events beat job, or a manual catch-up after restart)
        must process every one of them."""
        from app.services.world_state.coordinator import drain_pending
        from app.services.world_state.chat_facts import render_world_state_core
        from app.models.world_model import WorldEventProcessing, WorldEvent

        for i in range(3):
            _append(pg, user_id, "location.entered", str(uuid.uuid4()), f"loc-{i}:{uuid.uuid4()}")

        pending_before = pg.execute(select(WorldEventProcessing).join(WorldEvent).where(
            WorldEvent.user_id == user_id, WorldEventProcessing.status == "pending",
        )).scalars().all()
        assert len(pending_before) == 3

        result = drain_pending(pg, limit=100)
        assert result["completed"] >= 3
        assert result["failures"] == 0

        pending_after = pg.execute(select(WorldEventProcessing).join(WorldEvent).where(
            WorldEvent.user_id == user_id, WorldEventProcessing.status == "pending",
        )).scalars().all()
        assert pending_after == []

        # And the effect actually landed — not just "marked completed".
        core = render_world_state_core(pg, user_id)
        assert "David is at the office" in core

    def test_catch_up_user_is_scoped_to_one_user_and_reports_completeness(self, pg, user_id):
        from app.services.world_state.coordinator import catch_up_user

        other_user = f"test-recovery-other-{uuid.uuid4()}"
        _append(pg, user_id, "location.entered", str(uuid.uuid4()), f"mine:{uuid.uuid4()}")
        _append(pg, other_user, "location.entered", str(uuid.uuid4()), f"theirs:{uuid.uuid4()}")

        result = catch_up_user(pg, user_id, limit=50)
        assert result["complete"] is True
        assert result["completed"] == 1  # only this user's event, not the other user's

        from app.services.world_state.chat_facts import render_world_state_core
        assert "David is at the office" in render_world_state_core(pg, user_id)

        # Clean up the other user's rows too (not covered by the `user_id` fixture).
        pg.execute(text("DELETE FROM world_event_processing WHERE event_id IN (SELECT event_id FROM world_event WHERE user_id = :u)"), {"u": other_user})
        pg.execute(text("DELETE FROM world_event WHERE user_id = :u"), {"u": other_user})
        pg.commit()

    def test_reprocessing_an_already_completed_event_is_a_safe_no_op(self, pg, user_id):
        """'Recover exactly once in EFFECT' — draining twice (e.g. a worker
        restart mid-drain, or an overlapping manual catch-up) must not
        double-apply anything."""
        from app.services.world_state.coordinator import drain_pending
        from app.models.world_model import WorldThread
        from sqlalchemy import func

        place_id = str(uuid.uuid4())
        _append(pg, user_id, "location.entered", place_id, f"loc-dup:{uuid.uuid4()}")

        first = drain_pending(pg, limit=100)
        assert first["completed"] == 1
        second = drain_pending(pg, limit=100)
        assert second["completed"] == 0  # nothing left ready — already completed, not re-claimed

        from app.models.world_model import WorldFact
        count = pg.execute(select(func.count()).select_from(WorldFact).where(
            WorldFact.user_id == user_id, WorldFact.fact_key.like("location:%:latest"),
        )).scalar()
        assert count == 1  # not double-applied

    def test_a_failing_reduction_retries_with_backoff_not_silently_lost(self, pg, user_id, monkeypatch):
        """A worker crash mid-reduction (or a transient DB error) must not
        drop the event — it must be visible as 'retry' with a recorded
        error, not vanish from the pending set."""
        from app.services.world_state import coordinator
        from app.models.world_model import WorldEventProcessing, WorldEvent

        _append(pg, user_id, "location.entered", str(uuid.uuid4()), f"loc-fail:{uuid.uuid4()}")

        def _boom(db, event):
            raise RuntimeError("simulated reduction failure")

        monkeypatch.setattr(coordinator, "reduce_world_event", _boom)

        ids = coordinator.ready_event_ids(pg, user_id=user_id)
        assert len(ids) == 1
        result = coordinator.process_one(pg, ids[0])
        assert result["effect"] == "failed"

        processing = pg.execute(select(WorldEventProcessing).join(WorldEvent).where(
            WorldEvent.user_id == user_id,
        )).scalar_one()
        assert processing.status == "retry"
        assert processing.attempt_count == 1
        assert "simulated reduction failure" in (processing.last_error or "")
        assert processing.next_attempt_at is not None  # backoff scheduled, not lost
