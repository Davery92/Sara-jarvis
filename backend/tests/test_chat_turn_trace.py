"""Per-turn chat trace (harness rebuild Phase 9).

On 2026-09-11 David asked for his attachments and waited. One turn ran 500
seconds; there was no way for him to see that Sara had spent it calling fifteen
tools, and reconstructing what happened took a 20-minute docker log window read
by hand.

`ended_by` is the field that matters: anything other than `model` means the
harness — a deadline, a round cap, a disconnect, an error — decided when Sara
stopped talking, rather than Sara deciding she was finished.
"""

import asyncio
import json

import pytest

from app import main_simple as ms
from tests.test_chat_tool_loop import MESSAGES, make_client, tool_call


@pytest.fixture
def traces(monkeypatch):
    """Capture what _write_turn_trace would have inserted, without a DB."""
    captured = []

    class _Session:
        def execute(self, stmt, params=None):
            captured.append(params)

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(ms, "SessionLocal", lambda: _Session())
    return captured


@pytest.mark.asyncio
class TestATraceIsWrittenForEveryOutcome:
    async def test_a_normal_turn_ends_by_model(self, monkeypatch, traces):
        monkeypatch.setattr(ms, "CHAT_TURN_DEADLINE_S", 9999)
        client, stream, _ = make_client(monkeypatch, [
            {"content": "Nothing tomorrow but the family birthday.", "tool_calls": None},
        ])
        await client.chat_with_tools(MESSAGES, [], "u1", "conv-1")

        assert len(traces) == 1
        assert traces[0]["ended"] == "model"
        assert traces[0]["cid"] == "conv-1"
        assert traces[0]["reply"] == len("Nothing tomorrow but the family birthday.")

    async def test_a_deadline_turn_says_so(self, monkeypatch, traces):
        monkeypatch.setattr(ms, "CHAT_TURN_DEADLINE_S", 0)
        client, stream, _ = make_client(monkeypatch, [
            {"content": "", "tool_calls": [tool_call("email_search")]},
            {"content": "Three files from Jim, all PDFs, none filed yet.", "tool_calls": None},
        ])
        await client.chat_with_tools(MESSAGES, [], "u1", "conv-1")

        assert traces[-1]["ended"] == "deadline"

    async def test_a_round_capped_turn_says_so(self, monkeypatch, traces):
        monkeypatch.setattr(ms, "CHAT_TURN_DEADLINE_S", 9999)
        monkeypatch.setattr(ms, "CHAT_TOOL_ROUNDS_MAX", 2)
        client, stream, _ = make_client(monkeypatch, [
            {"content": "", "tool_calls": [tool_call("email_search")]},
            {"content": "", "tool_calls": [tool_call("email_search", "c2")]},
            {"content": "Both searches came back with Jim's three threads.", "tool_calls": None},
        ])
        await client.chat_with_tools(MESSAGES, [], "u1", "conv-1")

        assert traces[-1]["ended"] == "rounds"

    async def test_a_cancelled_turn_is_still_recorded(self, monkeypatch, traces):
        """The turns worth seeing are the ones that did not end normally —
        this is the 500-second zombie's row."""
        monkeypatch.setattr(ms, "CHAT_TURN_DEADLINE_S", 9999)
        client, stream, _ = make_client(monkeypatch, [asyncio.CancelledError()])

        with pytest.raises(asyncio.CancelledError):
            await client.chat_with_tools(MESSAGES, [], "u1", "conv-1")

        assert len(traces) == 1
        assert traces[0]["ended"] == "cancelled"
        assert traces[0]["reply"] == 0

    async def test_an_errored_turn_is_recorded(self, monkeypatch, traces):
        monkeypatch.setattr(ms, "CHAT_TURN_DEADLINE_S", 9999)
        client, stream, _ = make_client(monkeypatch, [
            {"content": "", "tool_calls": [tool_call("email_search")]},
            RuntimeError("llama-server said no"),
            {"content": "Jim's three threads are there; I could not read them.",
             "tool_calls": None},
        ])
        await client.chat_with_tools(MESSAGES, [], "u1", "conv-1")

        assert traces[-1]["ended"] == "error"


@pytest.mark.asyncio
class TestWhatTheTraceRecords:
    async def test_every_tool_call_with_its_timing_and_size(self, monkeypatch, traces):
        monkeypatch.setattr(ms, "CHAT_TURN_DEADLINE_S", 9999)
        client, stream, _ = make_client(monkeypatch, [
            {"content": "", "tool_calls": [
                tool_call("email_search", "c1"),
                tool_call("files_to_studio", "c2"),
            ]},
            {"content": "Filed both of Jim's attachments to the Studio.", "tool_calls": None},
        ])
        await client.chat_with_tools(MESSAGES, [], "u1", "conv-1")

        tools = json.loads(traces[-1]["tools"])
        assert [t["name"] for t in tools] == ["email_search", "files_to_studio"]
        for t in tools:
            assert t["success"] is True
            assert t["result_chars"] > 0
            assert isinstance(t["ms"], int)

    async def test_a_failing_tool_is_marked_failed(self, monkeypatch, traces):
        monkeypatch.setattr(ms, "CHAT_TURN_DEADLINE_S", 9999)
        client, stream, _ = make_client(
            monkeypatch,
            [
                {"content": "", "tool_calls": [tool_call("files_to_studio")]},
                {"content": "That one did not go through; nothing was filed.",
                 "tool_calls": None},
            ],
            tool_result=json.dumps({"success": False, "message": "no such bucket"}),
        )
        await client.chat_with_tools(MESSAGES, [], "u1", "conv-1")

        tools = json.loads(traces[-1]["tools"])
        assert tools[0]["success"] is False

    async def test_rounds_and_tool_count(self, monkeypatch, traces):
        monkeypatch.setattr(ms, "CHAT_TURN_DEADLINE_S", 9999)
        schemas = [{"type": "function", "function": {"name": f"t{i}", "description": "x",
                                                     "parameters": {}}} for i in range(9)]
        client, stream, _ = make_client(monkeypatch, [
            {"content": "", "tool_calls": [tool_call("email_search")]},
            {"content": "Here is what the search actually returned.", "tool_calls": None},
        ])
        await client.chat_with_tools(MESSAGES, schemas, "u1", "conv-1")

        assert traces[-1]["rounds"] == 1
        assert traces[-1]["tcount"] == 9

    async def test_no_tools_means_an_empty_list_not_a_null(self, monkeypatch, traces):
        monkeypatch.setattr(ms, "CHAT_TURN_DEADLINE_S", 9999)
        client, stream, _ = make_client(monkeypatch, [
            {"content": "Good morning — quiet house, nothing on today.", "tool_calls": None},
        ])
        await client.chat_with_tools(MESSAGES, [], "u1", "conv-1")

        assert json.loads(traces[-1]["tools"]) == []


@pytest.mark.asyncio
class TestTracingNeverBreaksTheTurn:
    async def test_a_failing_trace_write_does_not_fail_the_reply(self, monkeypatch):
        monkeypatch.setattr(ms, "CHAT_TURN_DEADLINE_S", 9999)

        def _explode():
            raise RuntimeError("database is on fire")

        client, stream, _ = make_client(monkeypatch, [
            {"content": "The answer survives a broken trace table.", "tool_calls": None},
        ])
        monkeypatch.setattr(ms, "SessionLocal", _explode)

        out = await client.chat_with_tools(MESSAGES, [], "u1", "conv-1")
        assert out == "The answer survives a broken trace table."


class TestTheEndpointExists:
    def test_it_is_registered_outside_a_try_except(self):
        """Inline rule from the project memory: route registration must be
        OUTSIDE try/except, or a route that silently fails to register is a
        route that does not exist and nobody notices."""
        import inspect
        import re

        src = inspect.getsource(ms)
        idx = src.index("debug_chat_turns_router")
        window = src[max(0, idx - 400): idx]
        assert not re.search(r"\btry:\s*\n(?:(?!\n\S).)*$", window, re.S)

    def test_the_router_declares_the_path(self):
        from app.routes.debug_chat_turns import router

        assert any(r.path == "/debug/chat-turns" for r in router.routes)
