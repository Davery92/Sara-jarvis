"""End-to-end proof for food: real writer -> coordinator -> reducer pipeline,
exercising the plan's freshness-contract row for food/completed exercise —
"Preserve events as history; recompute edited/deleted totals" — including
the retraction path (`_retract_source`) that workout/location didn't touch,
since food is the only domain in these tests whose real producer emits a
`.deleted` event mirroring the same `source_ref`.

Run inside the backend container:

    docker compose exec -T backend pytest tests/test_food_world_state_integration_pg.py
"""
import os
import uuid

import pytest
from sqlalchemy import select, text

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
    uid = f"test-food-{uuid.uuid4()}"
    yield uid
    pg.rollback()
    pg.execute(text("""
        DELETE FROM world_event_processing
        WHERE event_id IN (SELECT event_id FROM world_event WHERE user_id = :u)
    """), {"u": uid})
    for table in ("world_event", "world_thread", "world_fact", "world_snapshot"):
        pg.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": uid})
    pg.commit()


def _emit_and_process(pg, user_id, kind, log_id, *, dedupe_key, calories=500, summary="chicken and rice"):
    from app.services.world_state.writer import append_world_event
    from app.services.world_state.coordinator import process_one

    row = append_world_event(
        pg, user_id=user_id, kind=kind, source="test",
        source_ref=f"food_log:{log_id}", aggregate_type="food_log", aggregate_id=log_id,
        dedupe_key=dedupe_key,
        payload={"log_id": log_id, "calories": calories, "summary": summary, "meal_type": "lunch"},
    )
    pg.commit()
    assert row is not None, "WORLD_EVENTS_ENABLED must be on for this test"
    return process_one(pg, row.event_id)


@requires_pg
class TestFoodLifecycle:
    def test_a_logged_meal_becomes_an_active_fact(self, pg, user_id):
        from app.models.world_model import WorldFact

        log_id = str(uuid.uuid4())
        _emit_and_process(pg, user_id, "food.logged", log_id, dedupe_key=f"food-logged:{log_id}")

        fact = pg.execute(select(WorldFact).where(
            WorldFact.user_id == user_id, WorldFact.fact_key == f"food:{log_id}:state",
        )).scalar_one_or_none()
        assert fact is not None
        assert fact.status == "active"
        assert fact.value["calories"] == 500

    def test_editing_a_meal_supersedes_the_old_totals(self, pg, user_id):
        from app.models.world_model import WorldFact

        log_id = str(uuid.uuid4())
        _emit_and_process(pg, user_id, "food.logged", log_id, dedupe_key=f"food-logged:{log_id}", calories=500)
        _emit_and_process(pg, user_id, "food.updated", log_id, dedupe_key=f"food-updated:{log_id}:1", calories=650)

        facts = pg.execute(select(WorldFact).where(
            WorldFact.user_id == user_id, WorldFact.fact_key == f"food:{log_id}:state",
        ).order_by(WorldFact.created_at)).scalars().all()

        active = [f for f in facts if f.status == "active"]
        superseded = [f for f in facts if f.status == "superseded"]
        assert len(active) == 1 and active[0].value["calories"] == 650
        assert len(superseded) == 1 and superseded[0].value["calories"] == 500

    def test_deleting_a_meal_retracts_it_so_totals_cannot_resurrect_it(self, pg, user_id):
        """Plan requirement: 'duplicate delivery and late old events cannot
        resurrect the previous value.'"""
        from app.models.world_model import WorldFact

        log_id = str(uuid.uuid4())
        _emit_and_process(pg, user_id, "food.logged", log_id, dedupe_key=f"food-logged:{log_id}")
        _emit_and_process(pg, user_id, "food.deleted", log_id, dedupe_key=f"food-deleted:{log_id}")

        fact = pg.execute(select(WorldFact).where(
            WorldFact.user_id == user_id, WorldFact.fact_key == f"food:{log_id}:state",
        )).scalar_one_or_none()
        assert fact is not None
        assert fact.status == "retracted"

        # A duplicate/late-redelivered "logged" event for the SAME log_id
        # must not un-retract it — dedupe_key collides with the original,
        # so this is exactly the "same event redelivered" case.
        _emit_and_process(pg, user_id, "food.logged", log_id, dedupe_key=f"food-logged:{log_id}")
        fact_again = pg.execute(select(WorldFact).where(
            WorldFact.user_id == user_id, WorldFact.fact_key == f"food:{log_id}:state",
        )).scalar_one_or_none()
        assert fact_again.status == "retracted"
