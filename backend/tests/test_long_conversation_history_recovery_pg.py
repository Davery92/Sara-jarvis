"""Living-world-context plan, Turn 3 item 5 ("Long conversations"): removing
the false "I remember everything in this thread" claim from the system
prompt (chat_system_prompt.py's `_session_block`, see
test_chat_system_prompt.py::TestMemoryContractIsHonest) is only honest if
there's an actual mechanism behind the honest replacement text, which points
David at `memory_search` for anything outside the visible window.

This proves that mechanism actually recovers an older statement — using the
REAL memory_search tool surface (app.tools.memory.MemorySearchTool, the
exact tool the model calls), real Postgres, real embeddings. No mock, no
new code: per the plan's explicit instruction ("Add a recovery mechanism
only if the existing one fails"), this is a verification test, not a
feature test — search_memory (app/services/memory_service.py) already
queries Postgres directly by embedding similarity, entirely independent of
whatever the CLIENT happens to have loaded as local conversation history.
"Partial client history after reconnecting" is therefore not a special case
this needs to simulate — the tool never reads client-side history at all,
so an old episode is exactly as findable after a fresh reconnect as it was
mid-conversation. What's demonstrated here is that this really is true for
an episode old enough (45 days) that no reasonable client-side window would
still hold it, found via a natural paraphrase rather than a keyword match.

Run inside the backend container:

    docker compose exec -T backend pytest tests/test_long_conversation_history_recovery_pg.py
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.db.base import SessionLocal


@pytest.fixture
async def old_statement():
    """A distinctive statement from 45 days ago — well outside any
    plausible client-side local history window — plus a recent, unrelated
    episode standing in for 'what the reconnected client actually has
    loaded locally'.

    Milestone A review, 2026-09-22 incident follow-up: this used to write
    under `get_owner_id()` — the real David account, not a synthetic one
    (see docs/plans/incidents/2026-09-22_test_run_against_live_db.md §6c).
    A fresh synthetic principal, scoped to nothing but this test's own
    rows, proves the exact same thing (search_memory is parametrized
    entirely by the `user_id` argument it's given — confirmed no internal
    owner-id special-casing in app/tools/memory.py or
    app/services/memory_service.py) without ever touching a real
    identity. `episode.user_id` carries no foreign-key constraint, so an
    arbitrary synthetic UUID needs no companion `app_user` row."""
    from app.services.embeddings import get_embedding

    nonce = uuid.uuid4().hex[:8]
    old_content = (
        f"PHASE_RECOVERY_TEST_{nonce} My sister's birthday is October 3rd "
        "and she's been dropping hints about wanting a succulent garden kit this year."
    )
    recent_content = f"PHASE_RECOVERY_TEST_{nonce} unrelated recent turn about tomorrow's weather"

    try:
        old_vec = await get_embedding(old_content)
        recent_vec = await get_embedding(recent_content)
    except Exception:
        old_vec = recent_vec = None
    if not old_vec or not recent_vec:
        pytest.skip("embedding service unavailable")

    user_id = f"test-synth-{uuid.uuid4()}"
    old_id, recent_id = str(uuid.uuid4()), str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    old_created = now - timedelta(days=45)

    db = SessionLocal()
    try:
        db.execute(text("""
            INSERT INTO episode
              (id, user_id, role, content, importance, access_count, created_at, embedding, source)
            VALUES
              (:old_id, :uid, 'user', :old_content, 0.5, 0, :old_created, CAST(:old_vec AS vector), 'test'),
              (:recent_id, :uid, 'user', :recent_content, 0.5, 0, :now, CAST(:recent_vec AS vector), 'test')
        """), {
            "old_id": old_id, "recent_id": recent_id, "uid": user_id,
            "old_content": old_content, "recent_content": recent_content,
            "old_created": old_created, "now": now,
            "old_vec": str(old_vec), "recent_vec": str(recent_vec),
        })
        db.commit()
        yield {"user_id": user_id, "old_id": old_id, "recent_id": recent_id, "nonce": nonce}
    finally:
        db.execute(text("DELETE FROM episode WHERE id = ANY(:ids)"), {"ids": [old_id, recent_id]})
        db.commit()
        db.close()


class TestLongConversationHistoryRecovery:
    @pytest.mark.asyncio
    async def test_memory_search_tool_recovers_an_old_statement_by_paraphrase(self, old_statement, monkeypatch):
        """The exact tool surface the model calls — not search_memory
        internals directly — with a NATURAL PARAPHRASE query (not the
        stored content's own wording), the realistic shape of what David
        would actually ask days later."""
        from app.tools.memory import MemorySearchTool

        # get_db() would otherwise pull the request-scoped session; the
        # tool opens its own regardless, so this only needs to exist.
        tool = MemorySearchTool()
        result = await tool.execute(
            user_id=old_statement["user_id"],
            query="when is my sister's birthday and what does she want",
            scopes=["episodes"],
            limit=10,
        )

        assert result.success is True
        contents = [r.get("content", "") for r in result.data["results"]]
        assert any(old_statement["nonce"] in c and "October 3rd" in c for c in contents), (
            f"old statement not recovered; got: {contents}"
        )

    @pytest.mark.asyncio
    async def test_recovery_does_not_depend_on_any_client_side_history(self, old_statement):
        """Proves the independence claim directly: calling search_memory
        with an EMPTY conversation history (the literal 'just reconnected,
        client has nothing loaded yet' state) still recovers the old
        statement, because the tool never reads client history at all."""
        from app.services.memory_service import MemoryService

        svc = MemoryService(db_session_factory=SessionLocal)
        # No conversation_history parameter exists on search_memory at all —
        # its signature (user_id, query, scopes, limit) is the proof; this
        # call is the demonstration.
        results = await svc.search_memory(
            old_statement["user_id"],
            "what does my sister want for her birthday",
            scopes=["episodes"], limit=10,
        )
        found_ids = {r["episode_id"] for r in results}
        assert old_statement["old_id"] in found_ids
