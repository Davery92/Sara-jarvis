"""
Tests for kernel_hands.py (work-order item 11, 2026-07-30): lane-routed
tool execution for the kernel's ambient cognition, closing the capability
gap the selves=1 daemon cutover left open.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.services.kernel_hands import (
    READ_ONLY_TOOLS,
    REVERSIBLE_WRITE_TOOLS,
    PROPOSE_FIRST_TOOLS,
    RETIRED_TOOLS,
    lane_for,
    execute_kernel_tool,
)


class TestLaneMapping:
    def test_all_15_migrated_tools_have_a_lane(self):
        migrated = READ_ONLY_TOOLS | REVERSIBLE_WRITE_TOOLS | PROPOSE_FIRST_TOOLS
        assert len(migrated) == 15
        assert migrated.isdisjoint(RETIRED_TOOLS)

    def test_retired_tools_are_exactly_the_zero_call_two(self):
        assert RETIRED_TOOLS == {"destroy_container", "bump_interest"}

    def test_read_only_examples(self):
        for name in ("web_search", "search_notes", "search_memory", "list_goals", "node_status"):
            assert lane_for(name) == "read"

    def test_reversible_write_examples(self):
        for name in ("write_note", "add_interest", "touch_interest", "create_goal", "update_goal"):
            assert lane_for(name) == "write"

    def test_propose_first_matches_old_substantive_vm_tools_gate(self):
        # The old Mind class's _SUBSTANTIVE_VM_TOOLS = {"provision_container",
        # "exec_in_container"} — exactly these two, not destroy/list/status.
        assert lane_for("provision_container") == "propose"
        assert lane_for("exec_in_container") == "propose"
        assert lane_for("list_containers") == "read"
        assert lane_for("node_status") == "read"

    def test_retired_tools_return_retired_lane(self):
        assert lane_for("destroy_container") == "retired"
        assert lane_for("bump_interest") == "retired"

    def test_unknown_tool_returns_none(self):
        assert lane_for("delete_everything") is None


class TestExecuteKernelTool:
    @pytest.mark.asyncio
    async def test_retired_tool_never_executes(self):
        with patch("app.services.kernel_hands._call_tool_handler", new=AsyncMock()) as mock_call:
            result = await execute_kernel_tool("destroy_container", {"vmid": 100}, "user1")
        mock_call.assert_not_called()
        assert result["status"] == "retired"

    @pytest.mark.asyncio
    async def test_unknown_tool_never_executes(self):
        with patch("app.services.kernel_hands._call_tool_handler", new=AsyncMock()) as mock_call:
            result = await execute_kernel_tool("rm_rf_root", {}, "user1")
        mock_call.assert_not_called()
        assert result["status"] == "no_lane"

    @pytest.mark.asyncio
    async def test_read_lane_executes_and_ledgers(self):
        with patch("app.services.kernel_hands._call_tool_handler", new=AsyncMock(return_value={"count": 3})) as mock_call, \
             patch("app.services.kernel_hands._ledger", new=AsyncMock()) as mock_ledger:
            result = await execute_kernel_tool("search_notes", {"query": "test"}, "user1")
        mock_call.assert_called_once_with("search_notes", {"query": "test"})
        mock_ledger.assert_called_once()
        assert result == {"status": "ok", "result": {"count": 3}}

    @pytest.mark.asyncio
    async def test_write_lane_executes_and_ledgers(self):
        with patch("app.services.kernel_hands._call_tool_handler", new=AsyncMock(return_value={"id": "abc"})) as mock_call, \
             patch("app.services.kernel_hands._ledger", new=AsyncMock()) as mock_ledger:
            result = await execute_kernel_tool("write_note", {"title": "t", "body": "b"}, "user1")
        mock_call.assert_called_once()
        mock_ledger.assert_called_once()
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_propose_lane_never_calls_tool_handler(self):
        """Irreversible/resource-creating tools must NEVER execute from the
        kernel, no exceptions — this is the one lane where "propose first"
        really does mean never auto-execute."""
        with patch("app.services.kernel_hands._call_tool_handler", new=AsyncMock()) as mock_call, \
             patch("app.services.kernel_hands._propose_first", new=AsyncMock(return_value={"status": "proposed", "candidate_id": "x"})) as mock_propose:
            result = await execute_kernel_tool(
                "provision_container", {"preset": "research"}, "user1", reason="testing"
            )
        mock_call.assert_not_called()
        mock_propose.assert_called_once_with("provision_container", {"preset": "research"}, "user1", "testing")
        assert result["status"] == "proposed"

    @pytest.mark.asyncio
    async def test_exec_in_container_also_never_auto_executes(self):
        with patch("app.services.kernel_hands._call_tool_handler", new=AsyncMock()) as mock_call, \
             patch("app.services.kernel_hands._propose_first", new=AsyncMock(return_value={"status": "proposed"})):
            await execute_kernel_tool("exec_in_container", {"vmid": 100, "command": "rm -rf /"}, "user1")
        mock_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_handler_exception_degrades_not_raises(self):
        with patch("app.services.kernel_hands._call_tool_handler", new=AsyncMock(side_effect=RuntimeError("boom"))), \
             patch("app.services.kernel_hands._ledger", new=AsyncMock()) as mock_ledger:
            result = await execute_kernel_tool("web_search", {"query": "x"}, "user1")
        assert result["status"] == "error"
        assert "boom" in result["error"]
        mock_ledger.assert_called_once()


class TestProposeFirst:
    @pytest.mark.asyncio
    async def test_creates_candidate_with_inform_kind_and_source(self):
        from app.services.kernel_hands import _propose_first
        from unittest.mock import MagicMock
        mock_db = AsyncMock()
        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        mock_factory = MagicMock(return_value=mock_session_cm)

        with patch("app.db.session.get_async_session_factory", return_value=mock_factory), \
             patch("app.services.say_candidate.create_candidate", new=AsyncMock(return_value="cand-123")) as mock_create, \
             patch("app.services.kernel_hands._ledger", new=AsyncMock()):
            result = await _propose_first("provision_container", {"preset": "research"}, "user1", "need a sandbox")

        assert mock_create.call_args.kwargs["source"] == "kernel_hands"
        assert mock_create.call_args.kwargs["kind"] == "inform"
        assert "provision_container" in mock_create.call_args.kwargs["summary"]
        assert result["status"] == "proposed"

    @pytest.mark.asyncio
    async def test_duplicate_suppressed_returns_that_status(self):
        from app.services.kernel_hands import _propose_first
        from unittest.mock import MagicMock
        mock_db = AsyncMock()
        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        mock_factory = MagicMock(return_value=mock_session_cm)

        with patch("app.db.session.get_async_session_factory", return_value=mock_factory), \
             patch("app.services.say_candidate.create_candidate", new=AsyncMock(return_value=None)):
            result = await _propose_first("exec_in_container", {"vmid": 1}, "user1", "")

        assert result["status"] == "duplicate_suppressed"
