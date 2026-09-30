"""The read-only World Context page (living-world-context plan, Phase 6):
proves the page derives from the SAME maintained projections chat uses,
by driving a real workout event through the real pipeline and reading it
back through the actual route handler function — not a reconstruction of
what the response is supposed to look like.

Run inside the backend container:

    docker compose exec -T backend pytest tests/test_world_context_page_integration_pg.py
"""
import os
import uuid
from types import SimpleNamespace

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
    monkeypatch.setenv("WORLD_EVENTS_ENABLED", "true")
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
    uid = f"test-worldctx-{uuid.uuid4()}"
    yield uid
    pg.rollback()
    pg.execute(text("""
        DELETE FROM world_event_processing
        WHERE event_id IN (SELECT event_id FROM world_event WHERE user_id = :u)
    """), {"u": uid})
    for table in ("world_event", "world_thread", "world_fact", "world_snapshot"):
        pg.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": uid})
    pg.commit()


@requires_pg
@pytest.mark.asyncio
class TestWorldContextPage:
    async def test_an_active_workout_appears_on_the_page(self, pg, user_id):
        from app.routes.world_context import get_world_context
        from app.services.world_state.writer import append_world_event
        from app.services.world_state.coordinator import process_one

        session_id = str(uuid.uuid4())
        row = append_world_event(
            pg, user_id=user_id, kind="workout.started", source="test",
            aggregate_type="workout_session", aggregate_id=session_id,
            dedupe_key=f"workout-started:{session_id}",
            payload={"session_id": session_id, "title": "Leg Day", "name": "Leg Day"},
        )
        pg.commit()
        process_one(pg, row.event_id)

        result = await get_world_context(db=pg, current_user=SimpleNamespace(id=user_id))

        assert any("Workout in progress: Leg Day" in line for line in result["current_situation"])
        assert result["last_event_sequence"] >= row.sequence
        assert "as_of" in result and "brief" in result

    async def test_coverage_reflects_the_domain_that_actually_wrote(self, pg, user_id):
        from app.routes.world_context import get_world_context
        from app.services.world_state.writer import append_world_event
        from app.services.world_state.coordinator import process_one

        session_id = str(uuid.uuid4())
        row = append_world_event(
            pg, user_id=user_id, kind="workout.started", source="test",
            aggregate_type="workout_session", aggregate_id=session_id,
            dedupe_key=f"workout-started:{session_id}",
            payload={"session_id": session_id, "title": "Push Day", "name": "Push Day"},
        )
        pg.commit()
        process_one(pg, row.event_id)

        result = await get_world_context(db=pg, current_user=SimpleNamespace(id=user_id))

        domains = {c["domain"]: c for c in result["coverage"]}
        assert "workout" in domains
        assert domains["workout"]["age_seconds"] is not None
        assert domains["workout"]["age_seconds"] < 60
        assert domains["workout"]["degraded"] is False

    async def test_a_quiet_user_with_no_history_is_not_reported_as_degraded_for_lack_of_coverage_rows(self, pg, user_id):
        """No events at all -> no coverage rows at all (nothing to report as
        stale) -> the page must not look broken; it should just be quiet."""
        from app.routes.world_context import get_world_context

        result = await get_world_context(db=pg, current_user=SimpleNamespace(id=user_id))
        assert result["current_situation"] == []
        assert result["coverage"] == []
        assert result["degraded_domains"] == []
