"""End-to-end proof for the SECOND domain in the living-world-context
plan's coverage inventory: location. Same pipeline as the workout proof
(real writer -> coordinator -> reducer -> WorldFact, read back by
chat_facts.render_world_state_core()), but exercising the plan's explicit
freshness-aging example (§4): "mark location last-known after 15 minutes
without a new observation... Never infer 'home' from silence."

Run inside the backend container:

    docker compose exec -T backend pytest tests/test_location_world_state_integration_pg.py
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
    uid = f"test-location-{uuid.uuid4()}"
    yield uid
    pg.rollback()
    pg.execute(text("""
        DELETE FROM world_event_processing
        WHERE event_id IN (SELECT event_id FROM world_event WHERE user_id = :u)
    """), {"u": uid})
    for table in ("world_event", "world_thread", "world_fact", "world_snapshot"):
        pg.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": uid})
    pg.commit()


def _emit(pg, user_id, kind, place_id, *, dedupe_key, label, place_type="other",
          occurred_at=None, observed_at=None):
    from app.services.world_state.writer import append_world_event
    row = append_world_event(
        pg, user_id=user_id, kind=kind, source="test",
        aggregate_type="location", aggregate_id=place_id,
        dedupe_key=dedupe_key, occurred_at=occurred_at,
        # The 15-minute freshness rule is measured against observed_at, not
        # occurred_at — a late-delivered-but-just-observed event must read
        # as current, not stale, so tests exercising the aging window need
        # to set both to the same simulated past moment.
        observed_at=observed_at if observed_at is not None else occurred_at,
        payload={"place_id": place_id, "label": label, "place_type": place_type},
    )
    pg.commit()
    return row


def _emit_and_process(pg, user_id, kind, place_id, **kw):
    from app.services.world_state.coordinator import process_one
    row = _emit(pg, user_id, kind, place_id, **kw)
    assert row is not None, "WORLD_EVENTS_ENABLED must be on for this test"
    return process_one(pg, row.event_id)


@requires_pg
class TestLocationFreshness:
    def test_a_recent_arrival_shows_as_current(self, pg, user_id):
        from app.services.world_state.chat_facts import render_world_state_core

        place_id = str(uuid.uuid4())
        _emit_and_process(
            pg, user_id, "location.entered", place_id,
            dedupe_key=f"loc-enter:{place_id}:1", label="the gym", place_type="gym",
        )

        core = render_world_state_core(pg, user_id)
        assert "David is at the gym" in core

    def test_an_arrival_older_than_15_minutes_becomes_last_known(self, pg, user_id):
        """The plan's exact freshness rule: 'mark location last-known after
        15 minutes without a new observation.'"""
        from app.services.world_state.chat_facts import render_world_state_core

        place_id = str(uuid.uuid4())
        stale_time = datetime.now(timezone.utc) - timedelta(minutes=20)
        _emit_and_process(
            pg, user_id, "location.entered", place_id,
            dedupe_key=f"loc-enter:{place_id}:1", label="the office",
            occurred_at=stale_time,
        )

        core = render_world_state_core(pg, user_id)
        assert "last known at the office" in core
        assert "David is at the office" not in core

    def test_leaving_a_place_does_not_infer_home(self, pg, user_id):
        """'Never infer home from silence' — an exit with no subsequent
        arrival must say location is unknown, not assume he went home."""
        from app.services.world_state.chat_facts import render_world_state_core

        place_id = str(uuid.uuid4())
        _emit_and_process(pg, user_id, "location.entered", place_id,
                           dedupe_key=f"loc-enter:{place_id}:1", label="the store")
        _emit_and_process(pg, user_id, "location.exited", place_id,
                           dedupe_key=f"loc-exit:{place_id}:1", label="the store")

        core = render_world_state_core(pg, user_id)
        assert "David left the store" in core
        assert "not observed since" in core
        assert "home" not in core.lower()

    def test_a_later_arrival_at_a_different_place_supersedes_the_earlier_one(self, pg, user_id):
        """Two different places are two different fact_keys (reducer.py
        keys location facts by aggregate/place id) — "current location"
        must be whichever transition is actually most recent, not
        whichever place's own fact_key happens to sort first."""
        from app.services.world_state.chat_facts import render_world_state_core

        gym_id = str(uuid.uuid4())
        home_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        _emit_and_process(pg, user_id, "location.entered", gym_id,
                           dedupe_key=f"loc-enter:{gym_id}:1", label="the gym",
                           occurred_at=now - timedelta(minutes=5))
        _emit_and_process(pg, user_id, "location.exited", gym_id,
                           dedupe_key=f"loc-exit:{gym_id}:1", label="the gym",
                           occurred_at=now - timedelta(minutes=2))
        _emit_and_process(pg, user_id, "location.entered", home_id,
                           dedupe_key=f"loc-enter:{home_id}:1", label="home",
                           occurred_at=now)

        core = render_world_state_core(pg, user_id)
        assert "David is at home" in core
        assert "the gym" not in core

    def test_no_location_history_renders_nothing(self, pg, user_id):
        from app.services.world_state.chat_facts import render_world_state_core
        assert render_world_state_core(pg, user_id) == ""
