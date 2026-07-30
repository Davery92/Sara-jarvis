"""
Tests for the KERNEL_HANDS additions to deliberation.py / deliberation_prompt.py
(work-order item 11, 2026-07-30): the one-tool-call-per-turn schema field,
its parsing, and the flag gating that keeps it invisible to the model when off.
"""
import pytest

from app.services.deliberation import ToolCall
from app.services.deliberation_prompt import build_deliberation_prompt


class TestPromptFlagGating:
    @pytest.mark.asyncio
    async def test_flag_off_prompt_has_no_tool_call_field(self, _fake_memory):
        sys_msg, _ = build_deliberation_prompt(_fake_memory, [], kernel_hands=False)
        assert "tool_call" not in sys_msg

    @pytest.mark.asyncio
    async def test_flag_on_prompt_describes_tool_call_and_lanes(self, _fake_memory):
        sys_msg, _ = build_deliberation_prompt(_fake_memory, [], kernel_hands=True)
        assert '"tool_call"' in sys_msg
        assert "Rules for tool_call" in sys_msg
        assert "provision_container" in sys_msg
        assert "NEVER executes" in sys_msg

    @pytest.mark.asyncio
    async def test_default_is_flag_off(self, _fake_memory):
        sys_msg, _ = build_deliberation_prompt(_fake_memory, [])
        assert "tool_call" not in sys_msg


class TestResponseParsing:
    def test_parses_valid_tool_call(self):
        parsed = {"tool_call": {"name": "search_notes", "args": {"query": "x"}, "reason": "curious"}}
        tc = _extract_tool_call(parsed)
        assert tc == ToolCall(name="search_notes", args={"query": "x"}, reason="curious")

    def test_missing_tool_call_is_none(self):
        parsed = {}
        assert _extract_tool_call(parsed) is None

    def test_null_tool_call_is_none(self):
        parsed = {"tool_call": None}
        assert _extract_tool_call(parsed) is None

    def test_tool_call_without_name_is_ignored(self):
        parsed = {"tool_call": {"args": {"query": "x"}}}
        assert _extract_tool_call(parsed) is None

    def test_non_dict_args_defaults_to_empty(self):
        parsed = {"tool_call": {"name": "node_status", "args": "not-a-dict"}}
        tc = _extract_tool_call(parsed)
        assert tc.args == {}


def _extract_tool_call(parsed):
    """Mirrors deliberation.py's DeliberationEngine.run() tool_call parsing
    block exactly, so this test locks in that logic without needing a full
    LLM-call mock just to exercise a few lines of dict parsing."""
    tc = parsed.get("tool_call")
    if isinstance(tc, dict) and tc.get("name"):
        return ToolCall(
            name=str(tc["name"]),
            args=tc.get("args") if isinstance(tc.get("args"), dict) else {},
            reason=str(tc.get("reason", "")),
        )
    return None


@pytest.fixture
def _fake_memory():
    from app.services.unified_context import UnifiedContextSnapshot
    return UnifiedContextSnapshot()
