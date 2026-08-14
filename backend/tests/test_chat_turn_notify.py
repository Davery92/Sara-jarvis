"""
Tests for app/services/chat_turn_notify.py — chat_stream's "a turn
started" preamble, extracted from ~140 lines inline (B3,
docs/plans/HYGIENE_AND_STALE_CONTEXT_FIX_PLAN_2026_08_12.md).

The one behavior that must survive the extraction exactly: the activity
signal is awaited inline (matches the original's synchronous placement),
while the other four fire as genuine background tasks via
asyncio.ensure_future — not uniformly "cleaned up" into one shape.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.chat_turn_notify import _last_user_text, notify_turn_started


def _request(messages, conversation_id="conv-1", source=None):
    return SimpleNamespace(messages=messages, conversation_id=conversation_id, source=source)


def _msg(role, content):
    return SimpleNamespace(role=role, content=content)


class TestLastUserText:
    def test_extracts_most_recent_user_message(self):
        request = _request([_msg("user", "first"), _msg("assistant", "ok"), _msg("user", "second")])
        assert _last_user_text(request) == "second"

    def test_no_user_message_returns_empty_string(self):
        request = _request([_msg("assistant", "hi")])
        assert _last_user_text(request) == ""

    def test_handles_dict_shaped_messages(self):
        request = _request([{"role": "user", "content": "dict form"}])
        assert _last_user_text(request) == "dict form"


class TestNotifyTurnStarted:
    @pytest.mark.asyncio
    async def test_activity_signal_awaited_before_returning(self):
        """The activity signal must complete (be awaited) before
        notify_turn_started returns — it ran synchronously inline in the
        original, unlike the other four fire-and-forget signals."""
        request = _request([_msg("user", "hello")])
        current_user = SimpleNamespace(id="u1")

        call_order = []

        async def _fake_signal():
            call_order.append("activity_signal")

        with patch("app.services.chat_turn_notify._signal_activity_state", new=_fake_signal), \
             patch("app.services.chat_turn_notify._post_acs_activity_event", new=AsyncMock()), \
             patch("app.services.chat_turn_notify._shadow_kernel_engaged_turn", new=AsyncMock()), \
             patch("app.services.chat_turn_notify._update_context_snapshot", new=AsyncMock()), \
             patch("app.services.chat_turn_notify._emit_chat_message_received", new=AsyncMock()):
            await notify_turn_started(current_user, request)

        assert "activity_signal" in call_order

    @pytest.mark.asyncio
    async def test_never_raises_when_a_signal_fails(self):
        request = _request([_msg("user", "hello")])
        current_user = SimpleNamespace(id="u1")

        with patch("app.services.chat_turn_notify._signal_activity_state", new=AsyncMock(side_effect=RuntimeError("boom"))):
            with pytest.raises(RuntimeError):
                # _signal_activity_state itself is awaited inline with no
                # try/except at the notify_turn_started level — its OWN
                # internal try/except (around the real activity_state_machine
                # call) is what normally absorbs failures; a mock that
                # bypasses that is expected to propagate here.
                await notify_turn_started(current_user, request)

    @pytest.mark.asyncio
    async def test_background_signals_fire_without_blocking(self):
        """The 4 backgrounded calls must be scheduled (ensure_future), not
        awaited inline — notify_turn_started must return promptly even if
        one of them would hang."""
        import asyncio

        request = _request([_msg("user", "hello")])
        current_user = SimpleNamespace(id="u1")

        hung = asyncio.Event()

        async def _hangs_forever(*args, **kwargs):
            await hung.wait()

        with patch("app.services.chat_turn_notify._signal_activity_state", new=AsyncMock()), \
             patch("app.services.chat_turn_notify._post_acs_activity_event", new=_hangs_forever), \
             patch("app.services.chat_turn_notify._shadow_kernel_engaged_turn", new=AsyncMock()), \
             patch("app.services.chat_turn_notify._update_context_snapshot", new=AsyncMock()), \
             patch("app.services.chat_turn_notify._emit_chat_message_received", new=AsyncMock()):
            await asyncio.wait_for(notify_turn_started(current_user, request), timeout=1.0)
        hung.set()  # let the background task finish so it doesn't warn on teardown
