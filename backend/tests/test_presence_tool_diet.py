"""
Tests for the chat lane's tool payload diet.

Originally Arc 3.4 (SARA_ALIVE_BUILD_PLAN): a hand-picked 7-tool core replacing
25 always-add tools. Rewritten for SARA_CHAT_HARNESS_REBUILD_PLAN_2026_09_11
Phase 2, which replaced sticky *categories* (append-only, reached 94 schemas
and 16.9k prompt tokens in one conversation on 2026-09-11) with a fixed core
plus embedding retrieval plus a `find_tools` escape hatch, hard-capped at 35.
"""
from app.services.tool_retrieval import (
    CORE_TOOLS,
    MAX_TOOLS_PER_CALL,
    select_chat_tools,
    tool_names,
)
from app.tools.registry import tool_registry


class TestCoreResolves:
    def test_every_core_tool_name_exists_in_registry(self):
        for name in CORE_TOOLS:
            assert tool_registry.get_tool(name) is not None, f"{name} not registered"

    def test_core_is_small(self):
        # The core is paid for on every single turn; if it starts creeping
        # toward the cap the retrieval budget disappears.
        assert len(CORE_TOOLS) <= 16

    def test_core_carries_the_escape_hatches(self):
        assert "find_tools" in CORE_TOOLS
        assert "get_tool_result_details" in CORE_TOOLS

    def test_dispatch_and_monitor_is_registered_but_not_core(self):
        assert "dispatch_and_monitor" not in CORE_TOOLS
        schemas = tool_registry.get_tools_by_names(["dispatch_and_monitor"])
        assert len(schemas) == 1


class TestGetToolsByNames:
    def test_unknown_name_is_skipped_not_raised(self):
        schemas = tool_registry.get_tools_by_names(["memory_search", "not_a_real_tool"])
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "memory_search"

    def test_empty_list_returns_empty(self):
        assert tool_registry.get_tools_by_names([]) == []


class TestSelectChatTools:
    def test_core_only_when_nothing_retrieved(self):
        schemas = select_chat_tools(CORE_TOOLS, [], [])
        assert tool_names(schemas) == list(CORE_TOOLS)

    def test_core_comes_first_in_declared_order(self):
        schemas = select_chat_tools(CORE_TOOLS, ["web_search", "home_light_control"], [])
        names = tool_names(schemas)
        assert names[: len(CORE_TOOLS)] == list(CORE_TOOLS)

    def test_tail_is_sorted_so_the_prefix_is_stable(self):
        a = tool_names(select_chat_tools(CORE_TOOLS, ["web_search", "open_page"], []))
        b = tool_names(select_chat_tools(CORE_TOOLS, ["open_page", "web_search"], []))
        assert a == b

    def test_duplicates_between_core_sticky_and_retrieved_collapse(self):
        schemas = select_chat_tools(
            CORE_TOOLS, ["memory_search", "web_search"], ["web_search", "notes_search"]
        )
        names = tool_names(schemas)
        assert len(names) == len(set(names))

    def test_hard_cap_is_enforced(self):
        many = [
            n for n in tool_names(tool_registry.get_openai_schemas())
            if n not in CORE_TOOLS
        ]
        assert len(many) > MAX_TOOLS_PER_CALL  # the registry really is big
        schemas = select_chat_tools(CORE_TOOLS, many, [])
        assert len(schemas) <= MAX_TOOLS_PER_CALL

    def test_cap_can_be_lowered_to_reserve_dispatch_slots(self):
        many = [
            n for n in tool_names(tool_registry.get_openai_schemas())
            if n not in CORE_TOOLS
        ]
        schemas = select_chat_tools(CORE_TOOLS, many, [], max_tools=MAX_TOOLS_PER_CALL - 2)
        assert len(schemas) <= MAX_TOOLS_PER_CALL - 2
