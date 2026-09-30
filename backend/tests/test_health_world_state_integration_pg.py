"""End-to-end proof for health: drives the REAL ingestion endpoint
(ingest_metrics_batch) — the actual gap this session found and fixed.
health.sync_completed was registered in the catalog (coalesce=True, six
metric-type kinds expected) but EventType.HEALTH_DATA_SYNCED was only ever
subscribed to across the codebase, never published anywhere. This proves
the new producer, the maintained snapshot, and the actual chat payload.

Run inside the backend container:

    docker compose exec -T backend pytest tests/test_health_world_state_integration_pg.py
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

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
    # health_metric.user_id is VARCHAR(36) — a bare UUID, unlike world_event
    # /world_thread/world_fact's unconstrained String columns every other
    # domain test in this session used a "test-<domain>-<uuid>" prefix for.
    uid = str(uuid.uuid4())
    yield uid
    pg.rollback()
    pg.execute(text("""
        DELETE FROM world_event_processing
        WHERE event_id IN (SELECT event_id FROM world_event WHERE user_id = :u)
    """), {"u": uid})
    for table in ("world_event", "world_thread", "world_fact", "world_snapshot"):
        pg.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": uid})
    pg.execute(text("DELETE FROM health_metric WHERE user_id = :u"), {"u": uid})
    pg.commit()


@requires_pg
@pytest.mark.asyncio
class TestHealthSyncProducer:
    async def test_a_real_batch_ingest_reaches_the_snapshot_and_chat_payload(self, pg, user_id):
        from app.routes.health_metrics import ingest_metrics_batch, BatchMetricsRequest, MetricInput
        from app.services.world_state.coordinator import process_one
        from app.services.world_state.chat_facts import render_world_state_core
        from app.services.chat_assembly import assemble_local_provider_messages
        from app.schemas.chat import ChatMessage
        from app.models.world_model import WorldEvent

        now = datetime.now(timezone.utc)
        request = BatchMetricsRequest(metrics=[
            MetricInput(metric_type="hrv_morning", value=62.0, recorded_at=now.isoformat()),
            MetricInput(metric_type="resting_hr", value=54.0, recorded_at=(now - timedelta(minutes=5)).isoformat()),
        ])

        response = await ingest_metrics_batch(
            request=request, db=pg, current_user=SimpleNamespace(id=user_id),
        )
        assert response.success
        assert response.inserted_count == 2

        event = pg.execute(select(WorldEvent).where(
            WorldEvent.user_id == user_id, WorldEvent.kind == "health.sync_completed",
        )).scalar_one()
        process_one(pg, event.event_id)

        core = render_world_state_core(pg, user_id)
        assert "Health data synced" in core
        assert "hrv_morning 62" in core

        stable = "You are Sara."
        assembly = assemble_local_provider_messages(
            full_sys=stable + "\n\n" + ("z" * 6000),
            stable_system_prompt=stable,
            conversation_history=[],
            merged_request_messages=[ChatMessage(role="user", content="how'd I sleep")],
            dialogue_block="", world_state_core=core, world_brief="",
            datetime_line="It's Thursday, 7am ET.", live_context_char_budget=4500,
        )
        user_msgs = [m for m in assembly["all_messages"] if m.role == "user"]
        content = user_msgs[-1].content
        text_ = "\n".join(p.get("text", "") for p in content) if isinstance(content, list) else content
        assert "hrv_morning" in text_

    async def test_a_resync_of_only_duplicates_emits_no_event(self, pg, user_id):
        """'A resync that was all duplicates isn't a fresh observation' —
        the ON CONFLICT DO NOTHING dedup at the metric level must not
        still produce a fresh-looking world event every time the iOS
        background sync retries the same batch."""
        from app.routes.health_metrics import ingest_metrics_batch, BatchMetricsRequest, MetricInput
        from app.models.world_model import WorldEvent

        now = datetime.now(timezone.utc)
        request = BatchMetricsRequest(metrics=[
            MetricInput(metric_type="steps", value=8000.0, recorded_at=now.isoformat()),
        ])
        await ingest_metrics_batch(request=request, db=pg, current_user=SimpleNamespace(id=user_id))
        await ingest_metrics_batch(request=request, db=pg, current_user=SimpleNamespace(id=user_id))

        events = pg.execute(select(WorldEvent).where(
            WorldEvent.user_id == user_id, WorldEvent.kind == "health.sync_completed",
        )).scalars().all()
        assert len(events) == 1

    async def test_a_stale_sync_no_longer_shows_as_recent(self, pg, user_id):
        from app.services.world_state.writer import append_world_event
        from app.services.world_state.coordinator import process_one
        from app.services.world_state.chat_facts import render_world_state_core

        stale_time = datetime.now(timezone.utc) - timedelta(hours=8)
        row = append_world_event(
            pg, user_id=user_id, kind="health.sync_completed", source="test",
            aggregate_type="health_sync", aggregate_id=user_id,
            dedupe_key=f"health-sync-stale:{uuid.uuid4()}",
            occurred_at=stale_time, observed_at=stale_time,
            payload={"inserted_count": 1, "metric_types": ["steps"], "latest_metric_type": "steps", "latest_value": 5000},
        )
        pg.commit()
        process_one(pg, row.event_id)

        core = render_world_state_core(pg, user_id)
        assert "Health data synced" not in core
