"""Living-world-context plan, Turn 3 item 3 ("Unavailable sources"): what
the maintained World Context / chat payload does when a source stops
reporting — a location feed that stops updating, an email sync job that
starts failing, anything upstream of a world event going dark for a while.

The claim under test, in four parts:
  1. Last-known evidence is PRESERVED, with its ORIGINAL observation time —
     an outage does not erase the WorldFact/WorldThread rows already
     written.
  2. Degraded coverage is EXPOSED — the World Context page's per-domain
     `degraded` flag (routes/world_context.py's `_coverage_rows`,
     `_STALE_COVERAGE_AFTER_SECONDS`) flips true once a domain's last event
     is old enough, so a source that has gone quiet is visibly different
     from one that is simply idle-but-healthy.
  3. Reads are PURE — re-reading the same stale fact/coverage row twice
     must not itself refresh its timestamp. An outage must not make old
     information look fresh just because something asked about it.
  4. RECOVERY — once the source resumes and a new event lands, both the
     fact-level phrasing and the domain's coverage flag return to current.

Real writer -> coordinator -> reducer pipeline, real Postgres, same
`observed_at`-backdating technique test_location_world_state_integration_pg.py
already uses to simulate aging without sleeping real wall-clock time: a
source outage and "nothing new has arrived in N hours" are indistinguishable
from the reducer's point of view, so backdating `observed_at` on the last
real event IS the outage simulation, not a stand-in for it.

Run inside the backend container:

    docker compose exec -T backend pytest tests/test_source_outage_reconciliation_pg.py
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
    uid = f"test-outage-{uuid.uuid4()}"
    yield uid
    pg.rollback()
    pg.execute(text("""
        DELETE FROM world_event_processing
        WHERE event_id IN (SELECT event_id FROM world_event WHERE user_id = :u)
    """), {"u": uid})
    for table in ("world_event", "world_thread", "world_fact", "world_snapshot"):
        pg.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": uid})
    pg.commit()


def _emit(pg, user_id, kind, place_id, *, dedupe_key, label, occurred_at=None, observed_at=None):
    from app.services.world_state.writer import append_world_event
    row = append_world_event(
        pg, user_id=user_id, kind=kind, source="test",
        aggregate_type="location", aggregate_id=place_id,
        dedupe_key=dedupe_key, occurred_at=occurred_at,
        observed_at=observed_at if observed_at is not None else occurred_at,
        payload={"place_id": place_id, "label": label, "place_type": "other"},
    )
    pg.commit()
    return row


def _emit_and_process(pg, user_id, kind, place_id, **kw):
    from app.services.world_state.coordinator import process_one
    row = _emit(pg, user_id, kind, place_id, **kw)
    assert row is not None, "WORLD_EVENTS_ENABLED must be on for this test"
    return process_one(pg, row.event_id)


def _coverage_for(pg, user_id, domain):
    from app.services.world_state.context import get_snapshot
    from app.routes.world_context import _coverage_rows
    snap = get_snapshot(pg, user_id)
    rows = {r["domain"]: r for r in _coverage_rows(snap.coverage, datetime.now(timezone.utc))}
    return rows.get(domain)


@requires_pg
class TestSourceOutageReconciliation:
    def test_last_known_evidence_survives_an_outage_with_its_original_time(self, pg, user_id):
        """A source that stops reporting must not erase what it already
        told us — the fact stays, dated to when it was actually observed,
        not silently updated to look recent."""
        from app.models.world_model import WorldFact
        from sqlalchemy import select

        place_id = str(uuid.uuid4())
        observed = datetime.now(timezone.utc) - timedelta(hours=30)  # the outage: last real signal 30h ago
        _emit_and_process(
            pg, user_id, "location.entered", place_id,
            dedupe_key=f"loc-enter:{place_id}:1", label="the office",
            occurred_at=observed, observed_at=observed,
        )

        fact = pg.execute(
            select(WorldFact).where(
                WorldFact.user_id == user_id,
                WorldFact.fact_key == f"location:{place_id}:latest",
                WorldFact.status == "active",
            )
        ).scalar_one_or_none()
        assert fact is not None, "the fact must still exist — an outage does not delete evidence"
        # The original observation time is preserved verbatim, not bumped
        # to "now" because time has since passed.
        assert abs((fact.observed_at - observed).total_seconds()) < 2

        from app.services.world_state.chat_facts import render_world_state_core
        core = render_world_state_core(pg, user_id)
        assert "David was last known at the office" in core
        assert "may have moved since" in core
        # Honest degradation, not silence and not a false "currently at".
        assert "David is at the office" not in core

    def test_a_quiet_domain_exposes_as_degraded_coverage(self, pg, user_id):
        place_id = str(uuid.uuid4())
        observed = datetime.now(timezone.utc) - timedelta(hours=30)
        _emit_and_process(
            pg, user_id, "location.entered", place_id,
            dedupe_key=f"loc-enter:{place_id}:1", label="the office",
            occurred_at=observed, observed_at=observed,
        )

        row = _coverage_for(pg, user_id, "location")
        assert row is not None
        assert row["degraded"] is True
        assert row["age_seconds"] > 24 * 60 * 60

    def test_a_fresh_domain_does_not_read_as_degraded(self, pg, user_id):
        """Control case: the same coverage check on a domain that just
        reported must read as healthy — degraded must mean something."""
        place_id = str(uuid.uuid4())
        _emit_and_process(
            pg, user_id, "location.entered", place_id,
            dedupe_key=f"loc-enter:{place_id}:1", label="the gym",
        )

        row = _coverage_for(pg, user_id, "location")
        assert row is not None
        assert row["degraded"] is False
        assert row["age_seconds"] < 60

    def test_reading_stale_evidence_repeatedly_does_not_refresh_it(self, pg, user_id):
        """An outage must not make old information look fresh — merely
        asking about a stale fact (rendering the core, checking coverage)
        must be a pure read, not a side-effecting one."""
        place_id = str(uuid.uuid4())
        observed = datetime.now(timezone.utc) - timedelta(hours=30)
        _emit_and_process(
            pg, user_id, "location.entered", place_id,
            dedupe_key=f"loc-enter:{place_id}:1", label="the office",
            occurred_at=observed, observed_at=observed,
        )

        from app.services.world_state.chat_facts import render_world_state_core
        first_core = render_world_state_core(pg, user_id)
        first_row = _coverage_for(pg, user_id, "location")

        # Read it again — several times, as a page left open or repeated
        # chat turns during the same outage would.
        for _ in range(3):
            render_world_state_core(pg, user_id)
            _coverage_for(pg, user_id, "location")

        second_core = render_world_state_core(pg, user_id)
        second_row = _coverage_for(pg, user_id, "location")

        assert second_core == first_core
        assert second_row["updated_at"] == first_row["updated_at"]
        assert second_row["degraded"] is True

    def test_recovery_after_a_source_resumes(self, pg, user_id):
        """Once the source starts reporting again, both the fact-level
        phrasing and the domain's coverage flag must return to current —
        an outage is not a one-way, permanently-degraded state."""
        place_id_stale = str(uuid.uuid4())
        observed = datetime.now(timezone.utc) - timedelta(hours=30)
        _emit_and_process(
            pg, user_id, "location.entered", place_id_stale,
            dedupe_key=f"loc-enter:{place_id_stale}:1", label="the office",
            occurred_at=observed, observed_at=observed,
        )
        assert _coverage_for(pg, user_id, "location")["degraded"] is True

        # The source resumes: a fresh event for the same domain.
        place_id_fresh = str(uuid.uuid4())
        _emit_and_process(
            pg, user_id, "location.entered", place_id_fresh,
            dedupe_key=f"loc-enter:{place_id_fresh}:1", label="the gym",
        )

        row = _coverage_for(pg, user_id, "location")
        assert row["degraded"] is False
        assert row["age_seconds"] < 60

        from app.services.world_state.chat_facts import render_world_state_core
        core = render_world_state_core(pg, user_id)
        assert "David is at the gym" in core
