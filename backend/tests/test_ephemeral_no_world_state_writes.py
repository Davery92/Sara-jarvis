"""Living-world-context plan acceptance matrix: 'Ephemeral chat and two
users | No durable ephemeral-world writes and no cross-user cache, event,
page, or history leakage.'

persist_user_turn() and store_conversation() both short-circuit on
self._ephemeral before ever calling intelligent_memory_service.store_episode
— and the world-event emission for chat.user_turn_stored /
chat.assistant_turn_stored lives INSIDE store_episode, attached to the same
episode-creation transaction. This proves the whole chain: an ephemeral
turn must produce zero episode writes and zero world events.
"""
import pytest

from app import main_simple as ms


@pytest.mark.asyncio
class TestEphemeralChatWritesNothingDurable:
    async def test_ephemeral_user_turn_never_calls_store_episode(self, monkeypatch):
        client = ms.SimpleLLMClient()
        client._ephemeral = True

        called = {"n": 0}

        async def _fake_store_episode(**kw):
            called["n"] += 1
            return None

        monkeypatch.setattr(
            ms.intelligent_memory_service, "store_episode", _fake_store_episode
        )

        await client.persist_user_turn(
            user_id="u1", conversation_id="c1", content="hello", client_message_id="m1",
        )

        assert called["n"] == 0

    async def test_ephemeral_assistant_turn_never_calls_store_episode(self, monkeypatch):
        client = ms.SimpleLLMClient()
        client._ephemeral = True

        called = {"n": 0}

        async def _fake_store_episode(**kw):
            called["n"] += 1
            return None

        monkeypatch.setattr(
            ms.intelligent_memory_service, "store_episode", _fake_store_episode
        )

        result = await client.store_conversation(
            messages=[{"role": "user", "content": "hi"}],
            response_content="hello back",
            user_id="u1",
            conversation_id="c1",
        )

        assert called["n"] == 0
        assert result is None

    async def test_a_normal_non_ephemeral_turn_still_calls_store_episode(self, monkeypatch):
        """Guards against the trivial false-positive of a broken check that
        always skips storage regardless of the ephemeral flag."""
        client = ms.SimpleLLMClient()
        client._ephemeral = False

        called = {"n": 0}

        async def _fake_store_episode(**kw):
            called["n"] += 1

            class _Ep:
                id = "ep-1"
            return _Ep()

        monkeypatch.setattr(
            ms.intelligent_memory_service, "store_episode", _fake_store_episode
        )
        monkeypatch.setattr(
            ms.SimpleLLMClient, "_store_legacy_conversation",
            lambda self, *a, **kw: _noop_coro(), raising=False,
        )
        monkeypatch.setattr(ms, "_mark_shown_discoveries", lambda *a, **kw: _noop_coro(), raising=False)

        await client.store_conversation(
            messages=[{"role": "user", "content": "hi"}],
            response_content="hello back",
            user_id="u1",
            conversation_id="c1",
        )

        assert called["n"] == 1


async def _noop_coro():
    return None
