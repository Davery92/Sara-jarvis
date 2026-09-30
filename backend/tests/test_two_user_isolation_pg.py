"""Living-world-context plan acceptance matrix: 'Ephemeral chat and two
users | ...no cross-user cache, event, page, or history leakage.'

Drives the ACTUAL World Context page endpoint and the tool-mutation
authorization state for two distinct users concurrently present in the
same process, proving isolation empirically rather than by code-reading
(every world_* table query in this session's work filters by user_id, and
_CHAT_STICKY_TOOL_NAMES/_CHAT_INVOKED_MUTATING_TOOL_NAMES are keyed by
session_id — this is the test that actually exercises those claims).

Run inside the backend container:

    docker compose exec -T backend pytest tests/test_two_user_isolation_pg.py
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
def two_users(pg):
    alice = f"test-iso-alice-{uuid.uuid4()}"
    bob = f"test-iso-bob-{uuid.uuid4()}"
    yield alice, bob
    pg.rollback()
    for uid in (alice, bob):
        pg.execute(text("""
            DELETE FROM world_event_processing
            WHERE event_id IN (SELECT event_id FROM world_event WHERE user_id = :u)
        """), {"u": uid})
        for table in ("world_event", "world_thread", "world_fact", "world_snapshot"):
            pg.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": uid})
    pg.commit()


def _emit_and_process(pg, user_id, session_id, title):
    from app.services.world_state.writer import append_world_event
    from app.services.world_state.coordinator import process_one

    session_id = session_id or str(uuid.uuid4())
    row = append_world_event(
        pg, user_id=user_id, kind="workout.started", source="test",
        aggregate_type="workout_session", aggregate_id=session_id,
        dedupe_key=f"workout-started:{session_id}",
        payload={"session_id": session_id, "title": title, "name": title},
    )
    pg.commit()
    process_one(pg, row.event_id)


@requires_pg
@pytest.mark.asyncio
class TestTwoUserIsolation:
    async def test_the_world_context_page_never_shows_the_other_users_data(self, pg, two_users):
        from app.routes.world_context import get_world_context

        alice, bob = two_users
        _emit_and_process(pg, alice, None, "Alice's Leg Day")
        _emit_and_process(pg, bob, None, "Bob's Arm Day")

        alice_page = await get_world_context(db=pg, current_user=SimpleNamespace(id=alice))
        bob_page = await get_world_context(db=pg, current_user=SimpleNamespace(id=bob))

        alice_text = " ".join(alice_page["current_situation"]) + alice_page["brief"]
        bob_text = " ".join(bob_page["current_situation"]) + bob_page["brief"]

        assert "Alice's Leg Day" in alice_text
        assert "Bob's Arm Day" not in alice_text
        assert "Bob's Arm Day" in bob_text
        assert "Alice's Leg Day" not in bob_text

    async def test_chat_facts_snapshot_is_scoped_per_user(self, pg, two_users):
        from app.services.world_state.chat_facts import render_world_state_core

        alice, bob = two_users
        _emit_and_process(pg, alice, None, "Alice's Push Day")
        # Bob has no events at all.

        assert "Alice's Push Day" in render_world_state_core(pg, alice)
        assert render_world_state_core(pg, bob) == ""

    def test_mutation_authorization_state_does_not_cross_sessions(self):
        """_CHAT_INVOKED_MUTATING_TOOL_NAMES and _CHAT_STICKY_TOOL_NAMES are
        keyed by session_id — Alice executing a mutating tool must not
        authorize the SAME tool name for Bob's unrelated session, even
        within the same process (both dicts are module-level, shared
        across every session in this backend process)."""
        from app import main_simple as ms

        alice_session = f"test-session-alice-{uuid.uuid4()}"
        bob_session = f"test-session-bob-{uuid.uuid4()}"
        ms._CHAT_INVOKED_MUTATING_TOOL_NAMES.pop(alice_session, None)
        ms._CHAT_INVOKED_MUTATING_TOOL_NAMES.pop(bob_session, None)

        ms._CHAT_INVOKED_MUTATING_TOOL_NAMES[alice_session] = ["notes_delete"]

        from app.services.tool_mutation import gate_mutating_tools

        bob_last_turn = ms._CHAT_INVOKED_MUTATING_TOOL_NAMES.get(bob_session, [])
        assert bob_last_turn == []  # Bob's own key was never touched

        schemas = [{"function": {"name": "notes_delete"}}]
        kept, dropped = gate_mutating_tools(schemas, "yes, do it", last_turn_mutating_tools=bob_last_turn)
        assert kept == []
        assert dropped == ["notes_delete"]  # Alice's authorization does not leak to Bob

        ms._CHAT_INVOKED_MUTATING_TOOL_NAMES.pop(alice_session, None)
        ms._CHAT_INVOKED_MUTATING_TOOL_NAMES.pop(bob_session, None)

    async def test_a_stale_domain_gap_for_one_user_does_not_appear_as_the_others_coverage(self, pg, two_users):
        from app.routes.world_context import get_world_context

        alice, bob = two_users
        _emit_and_process(pg, alice, None, "Alice's Cardio Day")
        # Bob has zero events — must show zero coverage rows, not Alice's.

        bob_page = await get_world_context(db=pg, current_user=SimpleNamespace(id=bob))
        assert bob_page["coverage"] == []
        assert bob_page["degraded_domains"] == []
