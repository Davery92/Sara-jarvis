"""
Tests for the SINGULAR_SARA_MASTER_PLAN §C4 `kernel.engaged_turn()` shadow
implementation: it must assemble real context, record itself as the target
path, and — critically — never raise, since it's called fire-and-forget from
the live chat handler and must never be able to affect a real response.
"""

import fakeredis.aioredis
import pytest

from app.services import kernel


@pytest.fixture
def fake_redis_everywhere(monkeypatch):
    """kernel.set_state/get_state and legacy_path_counters both hit Redis —
    point everything at one fake instance."""
    import app.services.legacy_path_counters as counters

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _fake_redis():
        return fake

    import app.core.redis as core_redis
    monkeypatch.setattr(core_redis, "get_redis", _fake_redis)
    monkeypatch.setattr(counters, "_get_redis", _fake_redis)
    return fake


class TestEngagedTurn:
    @pytest.mark.asyncio
    async def test_assembles_context_and_records_target_path(self, fake_redis_everywhere, monkeypatch):
        from app.schemas.contracts import RelationshipStateV1, SelfStateV1, WorldStateV1
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)

        async def _fake_context_snapshot(db, user_id):
            return {
                "world_state": WorldStateV1(as_of=now, user_id=user_id).model_dump(mode="json"),
                "self_state": SelfStateV1(as_of=now, kernel_state="ambient").model_dump(mode="json"),
                "relationship_state": RelationshipStateV1(as_of=now, user_id=user_id).model_dump(mode="json"),
            }

        def _fake_intent_graph(db, user_id):
            return {"total": 7, "by_source": {}, "source_errors": {}, "intents": []}

        async def _fake_recall(user_id, query, k=5):
            return {"traces": [{"kind": "note", "id": "1"}], "by_kind": {}, "paths": []}

        class _FakeDb:
            def close(self):
                pass

        monkeypatch.setattr("app.db.session.SessionLocal", lambda: _FakeDb())
        monkeypatch.setattr("app.services.context_snapshot.get_context_snapshot", _fake_context_snapshot)
        monkeypatch.setattr("app.services.intent_graph_projection.get_intent_graph", _fake_intent_graph)
        monkeypatch.setattr("app.services.memory_recall.recall", _fake_recall)

        result = await kernel.engaged_turn("user-1", conversation_id="conv-1", message_preview="hello")

        assert result["state"] == "engaged"
        assert result["conversation_id"] == "conv-1"
        assert result["open_intents"] == 7
        assert result["recall_traces"] == 1
        assert result["context"]["self_state"]["kernel_state"] == "ambient"
        assert result["correlation_id"].startswith("turn_")

        from app.services.legacy_path_counters import get_counts
        counts = await get_counts("engaged_cognition", days=1)
        assert counts["target"] == 1

    @pytest.mark.asyncio
    async def test_never_raises_when_context_assembly_fails(self, fake_redis_everywhere, monkeypatch):
        def _broken_session_local():
            raise ConnectionError("db down")

        monkeypatch.setattr("app.db.session.SessionLocal", _broken_session_local)

        async def _broken_recall(user_id, query, k=5):
            raise RuntimeError("recall exploded")

        monkeypatch.setattr("app.services.memory_recall.recall", _broken_recall)

        # Must not raise even though every internal source is broken.
        result = await kernel.engaged_turn("user-1")

        assert result["state"] == "engaged"
        assert result["context"] == {}
        assert result["open_intents"] == 0
        assert result["recall_traces"] == 0


class TestShadowFlagWiring:
    def test_flag_off_by_default(self, monkeypatch):
        """The shadow call in /chat/stream is gated on this flag; confirm
        the default (no app_settings row) really is OFF."""
        import app.db.session as db_session
        from app.core.feature_flags import Flag, is_enabled

        class _EmptySettings:
            def execute(self, *a, **kw):
                from types import SimpleNamespace
                return SimpleNamespace(fetchall=lambda: [])

            def close(self):
                pass

        monkeypatch.setattr(db_session, "SessionLocal", lambda: _EmptySettings())
        assert is_enabled(Flag.SINGULAR_KERNEL) is False
