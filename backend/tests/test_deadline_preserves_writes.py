"""
A turn that runs out of time must not throw away a write.

2026-09-15, 06:36 ET: Sara offered to log a rough night in the recovery log and
David said yes. Tool retrieval had handed her only note tools, so the turn spent
two rounds getting back to the right one (`notes_search` → 59,045 chars →
`find_tools`), then called `recovery_log_create` at 69.2s — nine seconds past
the 60s deadline. The guard dropped every pending call, the forced final
returned nothing twice, and the canned fallback told David she had "run out of
room" and to ask again. `daily_recovery_log.notes` was still NULL.

Two invariants here: the reads of a cut-short round are droppable, the writes
are not; and whatever Sara says afterwards has to know the write happened —
including the last-resort string, where "ask me again" would invite a duplicate
entry.
"""
import json

import pytest

from app.tools.mutating import (
    WRITE_TOOLS, is_write_tool, partition_by_effect, tool_call_name,
)


def call(name, cid="c1", **args):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


class TestWriteClassification:
    """The list is explicit because a name heuristic gets these wrong: a regex
    over `_create|_add|_log|…` also matches `recovery_log_get`,
    `food_log_search` and `food_log_summary`, where "log" names the store."""

    @pytest.mark.parametrize("name", [
        "recovery_log_create", "notes_create", "notes_edit", "notes_delete",
        "food_log_create", "reminders_create", "list_add", "timers_start",
        "calendar_create", "workout_log_create", "remember_about_david",
        "home_light_control", "run_command", "write_file",
    ])
    def test_writes_are_writes(self, name):
        assert is_write_tool(name) is True

    @pytest.mark.parametrize("name", [
        "recovery_log_get", "recovery_log_recent", "food_log_search",
        "food_log_summary", "notes_search", "memory_search", "find_tools",
        "email_search", "web_search", "read_file", "workout_history",
    ])
    def test_reads_are_reads(self, name):
        assert is_write_tool(name) is False

    def test_unknown_tool_is_not_a_write(self):
        """The safe default: a tool added later keeps the old skip behaviour
        rather than being silently re-run past a deadline."""
        assert is_write_tool("some_tool_invented_next_year") is False

    @pytest.mark.parametrize("bad", [None, "", 0])
    def test_junk_names_are_not_writes(self, bad):
        assert is_write_tool(bad) is False

    def test_every_listed_name_is_a_real_tool(self):
        """A typo here is invisible in production — the write just keeps being
        dropped — so the list is checked against the registry."""
        from app.tools.registry import tool_registry
        unknown = sorted(WRITE_TOOLS - set(tool_registry.tools.keys()))
        assert unknown == [], f"not in the registry: {unknown}"


class TestPartition:
    def test_splits_and_keeps_order(self):
        calls = [call("notes_search", "a"), call("recovery_log_create", "b"),
                 call("memory_search", "c"), call("notes_create", "d")]
        writes, reads = partition_by_effect(calls)
        assert [tool_call_name(w) for w in writes] == ["recovery_log_create", "notes_create"]
        assert [tool_call_name(r) for r in reads] == ["notes_search", "memory_search"]

    def test_all_reads(self):
        writes, reads = partition_by_effect([call("notes_search"), call("find_tools")])
        assert writes == []
        assert len(reads) == 2

    def test_empty_and_malformed(self):
        assert partition_by_effect([]) == ([], [])
        assert partition_by_effect(None) == ([], [])
        writes, reads = partition_by_effect([{"id": "x"}, {"function": "nope"}, None])
        assert writes == []
        assert len(reads) == 3

    def test_tool_call_name_survives_junk(self):
        assert tool_call_name({}) == ""
        assert tool_call_name({"function": None}) == ""
        assert tool_call_name(None) == ""
        assert tool_call_name({"function": {"name": "notes_create"}}) == "notes_create"


class _Harness:
    """The pieces of the streaming handler the past-deadline path touches."""

    def __init__(self):
        self.executed = []
        self._turn_tools_called = []
        self.events = []

    async def emit_event(self, name, payload=None):
        self.events.append((name, payload))

    async def emit_activity(self, *a, **k):
        pass

    async def execute_tool(self, tool_call, user_id, conversation_id=None, session_cache=None):
        name = tool_call["function"]["name"]
        self.executed.append(name)
        return {"role": "tool", "tool_call_id": tool_call.get("id", ""),
                "content": json.dumps({"success": True, "message": f"{name} ok"})}

    def _remember_tool_result(self, tool_call, tool_response):
        pass


def _bind():
    """Bind the real methods onto the harness."""
    from app.main_simple import SimpleLLMClient as H
    h = _Harness()
    h._run_pending_writes_past_deadline = H._run_pending_writes_past_deadline.__get__(h, _Harness)
    return h


class TestRunPendingWritesPastDeadline:
    @pytest.mark.asyncio
    async def test_writes_run_and_reads_do_not(self):
        h = _bind()
        message = {"content": "", "tool_calls": [
            call("notes_search", "r1"), call("recovery_log_create", "w1")]}
        writes, _ = partition_by_effect(message["tool_calls"])
        msgs = []

        await h._run_pending_writes_past_deadline(
            message, writes, msgs, "u1", "conv1", None, 3)

        assert h.executed == ["recovery_log_create"]

    @pytest.mark.asyncio
    async def test_every_pending_call_gets_a_response(self):
        """The protocol needs one tool message per tool_call; an unanswered one
        makes the forced-final payload malformed."""
        h = _bind()
        message = {"content": "", "tool_calls": [
            call("notes_search", "r1"), call("recovery_log_create", "w1"),
            call("memory_search", "r2")]}
        writes, _ = partition_by_effect(message["tool_calls"])
        msgs = []

        await h._run_pending_writes_past_deadline(
            message, writes, msgs, "u1", "conv1", None, 3)

        assistant, *tools = msgs
        assert assistant["role"] == "assistant"
        assert len(assistant["tool_calls"]) == 3
        assert [t["tool_call_id"] for t in tools] == ["r1", "w1", "r2"]

    @pytest.mark.asyncio
    async def test_the_write_result_reaches_the_final_answer(self):
        """Without this the row is written and the reply still says she ran out
        of time — the same failure wearing a better outcome."""
        h = _bind()
        message = {"content": "", "tool_calls": [call("recovery_log_create", "w1")]}
        writes, _ = partition_by_effect(message["tool_calls"])
        msgs = []

        await h._run_pending_writes_past_deadline(
            message, writes, msgs, "u1", "conv1", None, 3)

        written = json.loads(msgs[-1]["content"])
        assert written["success"] is True
        assert "recovery_log_create ok" in written["message"]

    @pytest.mark.asyncio
    async def test_skipped_reads_say_they_were_skipped(self):
        h = _bind()
        message = {"content": "", "tool_calls": [
            call("notes_search", "r1"), call("recovery_log_create", "w1")]}
        writes, _ = partition_by_effect(message["tool_calls"])
        msgs = []

        await h._run_pending_writes_past_deadline(
            message, writes, msgs, "u1", "conv1", None, 3)

        skipped = json.loads(msgs[1]["content"])
        assert skipped["success"] is False
        assert "notes_search" in skipped["message"]
        assert "not executed" in skipped["message"].lower()

    @pytest.mark.asyncio
    async def test_the_write_is_traced(self):
        h = _bind()
        message = {"content": "", "tool_calls": [call("recovery_log_create", "w1")]}
        writes, _ = partition_by_effect(message["tool_calls"])

        await h._run_pending_writes_past_deadline(
            message, writes, [], "u1", "conv1", None, 3)

        assert len(h._turn_tools_called) == 1
        assert h._turn_tools_called[0]["name"] == "recovery_log_create"
        assert h._turn_tools_called[0]["past_deadline"] is True
        assert h._turn_tools_called[0]["success"] is True

    @pytest.mark.asyncio
    async def test_a_raising_write_is_reported_not_swallowed(self):
        """Nothing retries after this point, so a failure has to reach David."""
        h = _bind()

        async def boom(tool_call, *a, **k):
            raise RuntimeError("db down")
        h.execute_tool = boom

        message = {"content": "", "tool_calls": [call("recovery_log_create", "w1")]}
        writes, _ = partition_by_effect(message["tool_calls"])
        msgs = []

        await h._run_pending_writes_past_deadline(
            message, writes, msgs, "u1", "conv1", None, 3)

        failed = json.loads(msgs[-1]["content"])
        assert failed["success"] is False
        assert "did not save" in failed["message"].lower()


class TestLastResortFallback:
    """Even when the forced final produces nothing — which is what happened on
    2026-09-15, twice — the fallback must not invite a duplicate write."""

    def _fallback(self, tools_called):
        from app.main_simple import SimpleLLMClient as H
        h = type("_Stub", (), {})()
        h._turn_tools_called = tools_called
        return H._last_resort_reply(h)

    def test_a_successful_write_is_reported_as_done(self):
        out = self._fallback([
            {"name": "notes_search", "success": True},
            {"name": "recovery_log_create", "success": True},
        ])
        assert "recovery_log_create" in out
        assert "saved" in out.lower()
        assert "ask me again" not in out.lower()

    def test_reads_only_keeps_the_ask_again_wording(self):
        out = self._fallback([
            {"name": "notes_search", "success": True},
            {"name": "find_tools", "success": True},
        ])
        assert "ask me again" in out.lower()
        assert "saved" not in out.lower()

    def test_a_failed_write_does_not_claim_it_saved(self):
        out = self._fallback([{"name": "recovery_log_create", "success": False}])
        assert "saved" not in out.lower()

    def test_no_tools_at_all(self):
        out = self._fallback([])
        assert "ran out of room" in out.lower()
