"""Living-world-context plan §12 acceptance matrix: 'Slow interpretation
races a new correction | Old model output is rejected/rebased; the
correction remains authoritative.'

The scenario: an email's follow-up thread is opened. The background
interpreter starts reading that same email (an LLM call, up to 90s).
While it's running, David resolves the thread through chat — a fast,
trusted-producer correction that commits (and gets its OWN, EARLIER
sequence number) well before the interpreter returns. The interpretation
event is only created — and sequenced — once the model call finishes,
so it lands LATER in commit order despite describing information that was
already stale when it was read.

Comparing interpretation against its own event.sequence (what this
session's earlier stale-event guard did) would let it win: its sequence is
numerically higher than the correction's, so the old guard would treat it
as "newer" and let it reopen an already-resolved thread. Comparing it
against source_sequence — the sequence of the ORIGINAL event it read,
captured by interpreter.py at extraction time — correctly rejects it as
stale relative to the correction, regardless of when interpretation itself
happened to commit.

Run inside the backend container:

    docker compose exec -T backend pytest tests/test_interpretation_vs_correction_pg.py
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
    uid = f"test-interp-race-{uuid.uuid4()}"
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
class TestSlowInterpretationRacesACorrection:
    def test_a_late_committing_interpretation_cannot_reopen_a_resolved_thread(self, pg, user_id):
        from app.services.world_state.writer import append_world_event
        from app.services.world_state.coordinator import process_one
        from app.services.world_state.reducer import email_thread_key
        from app.models.world_model import WorldThread

        conv_id = str(uuid.uuid4())
        email_id = str(uuid.uuid4())
        thread_key = email_thread_key(conv_id, email_id)

        # 1. Source event: the email arrives and needs action. Opens the thread.
        source = append_world_event(
            pg, user_id=user_id, kind="email.analyzed", source="email_analyzer",
            source_ref=f"email:{email_id}", aggregate_type="email", aggregate_id=email_id,
            correlation_id=conv_id, dedupe_key=f"email-analyzed:{conv_id}:1",
            payload={
                "email_id": email_id, "conversation_id": conv_id,
                "subject": "Can we move this call?", "action_required": True,
                "summary": "Can we move this call?",
            },
        )
        pg.commit()
        process_one(pg, source.event_id)
        source_sequence = source.sequence

        thread = pg.execute(select(WorldThread).where(
            WorldThread.user_id == user_id, WorldThread.thread_key == thread_key,
        )).scalar_one()
        assert thread.status == "open"

        # 2. David resolves it through chat — fast, trusted, commits and is
        #    processed well before the interpreter (below) finishes.
        correction = append_world_event(
            pg, user_id=user_id, kind="thread.resolved", source="chat_tool",
            aggregate_type="world_thread", aggregate_id=thread.id,
            dedupe_key=f"thread-resolved:{thread.id}:1",
            payload={"thread_id": thread.id, "reason": "David handled it directly"},
        )
        pg.commit()
        process_one(pg, correction.event_id)

        thread = pg.execute(select(WorldThread).where(WorldThread.id == thread.id)).scalar_one()
        assert thread.status == "resolved"
        resolved_last_seq = thread.last_event_sequence

        # 3. NOW the slow interpreter's result finally lands — appended (and
        #    sequenced) AFTER the correction, but describing what it read
        #    back when the email first arrived (source_sequence points at
        #    step 1, not "now").
        interpretation = append_world_event(
            pg, user_id=user_id, kind="world.interpretation.completed", source="world_interpreter",
            source_ref=f"email:{email_id}", aggregate_type="email", aggregate_id=email_id,
            causation_id=source.event_id, correlation_id=conv_id,
            dedupe_key=f"world-interpretation:{source.event_id}:v1",
            payload={
                "headline": "Email needs a reply", "detail": None, "entities": [], "facts": [],
                "threads": [{
                    "thread_key": thread_key, "kind": "follow_up",
                    "title": "Can we move this call?", "status": "open",
                    "next_step": "Reply about rescheduling",
                }],
                "source_event_id": source.event_id,
                "source_event_kind": "email.analyzed",
                "source_sequence": source_sequence,
            },
            confidence=0.75, confidence_basis="inferred",
        )
        pg.commit()
        assert interpretation.sequence > correction.sequence > source.sequence

        result = process_one(pg, interpretation.event_id)

        thread = pg.execute(select(WorldThread).where(WorldThread.id == thread.id)).scalar_one()
        assert thread.status == "resolved", (
            "the stale interpretation reopened an already-resolved thread"
        )
        # The correction's freshness marker must survive untouched too —
        # not just the status field.
        assert thread.last_event_sequence == resolved_last_seq

    def test_an_interpretation_that_is_still_current_still_applies(self, pg, user_id):
        """The guard must not become 'interpretation never applies' — only
        genuinely stale ones are rejected. No correction happened here, so
        the interpretation (reflecting the only evidence that exists) must
        still open the thread."""
        from app.services.world_state.writer import append_world_event
        from app.services.world_state.coordinator import process_one
        from app.services.world_state.reducer import email_thread_key
        from app.models.world_model import WorldThread

        conv_id = str(uuid.uuid4())
        email_id = str(uuid.uuid4())
        thread_key = email_thread_key(conv_id, email_id)

        source = append_world_event(
            pg, user_id=user_id, kind="email.received", source="microsoft_graph",
            source_ref=f"email:{email_id}", aggregate_type="email", aggregate_id=email_id,
            correlation_id=conv_id, dedupe_key=f"email-received:{email_id}:v1",
            payload={"email_id": email_id, "conversation_id": conv_id, "subject": "Quick question"},
        )
        pg.commit()
        process_one(pg, source.event_id)

        interpretation = append_world_event(
            pg, user_id=user_id, kind="world.interpretation.completed", source="world_interpreter",
            source_ref=f"email:{email_id}", aggregate_type="email", aggregate_id=email_id,
            causation_id=source.event_id, correlation_id=conv_id,
            dedupe_key=f"world-interpretation:{source.event_id}:v1",
            payload={
                "headline": "Needs a reply", "detail": None, "entities": [], "facts": [],
                "threads": [{
                    "thread_key": thread_key, "kind": "follow_up",
                    "title": "Quick question", "status": "open",
                    "next_step": "Reply",
                }],
                "source_event_id": source.event_id, "source_event_kind": "email.received",
                "source_sequence": source.sequence,
            },
            confidence=0.75, confidence_basis="inferred",
        )
        pg.commit()
        process_one(pg, interpretation.event_id)

        thread = pg.execute(select(WorldThread).where(
            WorldThread.user_id == user_id, WorldThread.thread_key == thread_key,
        )).scalar_one_or_none()
        assert thread is not None
        assert thread.status == "open"
