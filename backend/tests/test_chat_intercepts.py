"""
Tests for app/services/chat_intercepts.py — chat_stream's early intercept
chain, extracted from ~260 lines inline (B3,
docs/plans/HYGIENE_AND_STALE_CONTEXT_FIX_PLAN_2026_08_12.md).

Covers: last-user-message extraction, the shared ack-stream shape (incl.
chess's full_content omission), first-match-wins dispatch ordering, and
per-handler exception isolation (one broken handler can't block the rest
of the chain).
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.chat_intercepts import (
    ChatTurnContext,
    INTERCEPT_HANDLERS,
    _ack_stream,
    build_context,
    dispatch_intercepts,
)


def _request(messages, conversation_id="conv-1", source=None):
    return SimpleNamespace(messages=messages, conversation_id=conversation_id, source=source)


def _msg(role, content):
    return SimpleNamespace(role=role, content=content)


async def _drain(stream):
    return [chunk async for chunk in stream]


def _parse_events(chunks):
    return [json.loads(c[len("data: "):].strip()) for c in chunks]


class TestBuildContext:
    def test_extracts_last_user_message(self):
        request = _request([_msg("assistant", "hi"), _msg("user", "hello there")])
        ctx = build_context(request, current_user=SimpleNamespace(id="u1"), db=None)
        assert ctx.last_user_message == "hello there"

    def test_no_user_message_yields_none(self):
        request = _request([_msg("assistant", "hi")])
        ctx = build_context(request, current_user=SimpleNamespace(id="u1"), db=None)
        assert ctx.last_user_message is None

    def test_picks_most_recent_user_message(self):
        request = _request([_msg("user", "first"), _msg("assistant", "ok"), _msg("user", "second")])
        ctx = build_context(request, current_user=SimpleNamespace(id="u1"), db=None)
        assert ctx.last_user_message == "second"


class TestAckStream:
    @pytest.mark.asyncio
    async def test_default_includes_full_content(self):
        events = _parse_events(await _drain(_ack_stream("hello", "conv-1")))
        assert events[0]["type"] == "text_chunk"
        assert events[0]["data"]["full_content"] == "hello"
        assert events[1]["type"] == "final_response"
        assert events[1]["data"]["content"] == "hello"
        assert events[1]["data"]["conversation_id"] == "conv-1"
        assert events[2]["type"] == "done"

    @pytest.mark.asyncio
    async def test_chess_shape_omits_full_content(self):
        """Chess's original inline code never included full_content in its
        text_chunk — preserved as-is, not 'fixed' into consistency."""
        events = _parse_events(await _drain(_ack_stream("e4", "conv-1", include_full_content=False)))
        assert "full_content" not in events[0]["data"]


class TestDispatchOrdering:
    @pytest.mark.asyncio
    async def test_first_match_wins(self):
        async def handler_a(ctx):
            return None

        async def handler_b(ctx):
            async def _gen():
                yield "data: b\n\n"
            return _gen()

        async def handler_c(ctx):
            raise AssertionError("should never be called — b already matched")

        with patch("app.services.chat_intercepts.INTERCEPT_HANDLERS", [handler_a, handler_b, handler_c]):
            ctx = ChatTurnContext(request=_request([]), current_user=None, db=None, last_user_message=None)
            result = await dispatch_intercepts(ctx)
            chunks = await _drain(result)
            assert chunks == ["data: b\n\n"]

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self):
        async def handler_a(ctx):
            return None

        with patch("app.services.chat_intercepts.INTERCEPT_HANDLERS", [handler_a]):
            ctx = ChatTurnContext(request=_request([]), current_user=None, db=None, last_user_message=None)
            result = await dispatch_intercepts(ctx)
            assert result is None

    @pytest.mark.asyncio
    async def test_broken_handler_does_not_block_the_next(self):
        async def handler_broken(ctx):
            raise RuntimeError("boom")

        async def handler_ok(ctx):
            async def _gen():
                yield "data: ok\n\n"
            return _gen()

        with patch("app.services.chat_intercepts.INTERCEPT_HANDLERS", [handler_broken, handler_ok]):
            ctx = ChatTurnContext(request=_request([]), current_user=None, db=None, last_user_message=None)
            result = await dispatch_intercepts(ctx)
            chunks = await _drain(result)
            assert chunks == ["data: ok\n\n"]


class TestChessIntercept:
    @pytest.mark.asyncio
    async def test_matches_and_streams_chess_response(self):
        from app.services.chat_intercepts import _try_chess

        request = _request([_msg("user", "/chess new game")])
        ctx = ChatTurnContext(request=request, current_user=SimpleNamespace(id="u1"), db=None, last_user_message="/chess new game")

        with patch(
            "app.services.chess_command_handler.handle_chess_command",
            new=AsyncMock(return_value=("Game started.", False)),
        ):
            result = await _try_chess(ctx)

        assert result is not None
        events = _parse_events(await _drain(result))
        assert events[0]["data"]["content"] == "Game started."
        assert "full_content" not in events[0]["data"]

    @pytest.mark.asyncio
    async def test_no_message_no_match(self):
        from app.services.chat_intercepts import _try_chess
        request = _request([])
        ctx = ChatTurnContext(request=request, current_user=SimpleNamespace(id="u1"), db=None, last_user_message=None)
        assert await _try_chess(ctx) is None

    @pytest.mark.asyncio
    async def test_handler_returns_none_when_not_a_chess_command(self):
        from app.services.chat_intercepts import _try_chess
        request = _request([_msg("user", "what's the weather")])
        ctx = ChatTurnContext(request=request, current_user=SimpleNamespace(id="u1"), db=None, last_user_message="what's the weather")
        with patch(
            "app.services.chess_command_handler.handle_chess_command",
            new=AsyncMock(return_value=None),
        ):
            assert await _try_chess(ctx) is None


class TestUiCommandIntercept:
    @pytest.mark.asyncio
    async def test_matches_and_emits_ui_command_before_ack(self):
        from app.services.chat_intercepts import _try_ui_command
        request = _request([_msg("user", "show me my nutrition")], source="webapp")
        ctx = ChatTurnContext(request=request, current_user=SimpleNamespace(id="u1"), db=None, last_user_message="show me my nutrition")

        with patch("app.services.ui_intent.parse_ui_intent", return_value={"overlay": "nutrition"}), \
             patch("app.services.ui_intent.resolve_ui_intent", return_value={"command": {"kind": "nutrition"}, "ack": "Here you go."}):
            result = await _try_ui_command(ctx)

        assert result is not None
        events = _parse_events(await _drain(result))
        assert events[0]["type"] == "ui_command"
        assert events[1]["type"] == "text_chunk"
        assert events[1]["data"]["full_content"] == "Here you go."

    @pytest.mark.asyncio
    async def test_no_intent_no_match(self):
        from app.services.chat_intercepts import _try_ui_command
        request = _request([_msg("user", "tell me a joke")])
        ctx = ChatTurnContext(request=request, current_user=SimpleNamespace(id="u1"), db=None, last_user_message="tell me a joke")
        with patch("app.services.ui_intent.parse_ui_intent", return_value=None):
            assert await _try_ui_command(ctx) is None


class TestAllHandlersRegistered:
    def test_handlers_in_order(self):
        names = [h.__name__ for h in INTERCEPT_HANDLERS]
        assert names == [
            "_try_chess",
            "_try_code_mode",
            "_try_host_inspection",
            "_try_ui_command",
            "_try_interest_model_verb",
            # Ground-truth plan, Phase 2 §3. Deliberately an intercept rather
            # than a prompt instruction: on 2026-09-02 David wrote "ENOUGH WITH
            # THE LAURA WEIPPERT OVERDUE NONSENSE WE HAD OUR MEETING" and the
            # model, having no closer tool, cancelled two unrelated reminders
            # while the three real threads stayed open. Closing what David says
            # is done must not depend on a model choosing to call a tool.
            "_try_thread_resolution",
        ]

    def test_web_investigation_does_not_bypass_chat(self):
        names = [h.__name__ for h in INTERCEPT_HANDLERS]
        assert "_try_web_investigation" not in names
