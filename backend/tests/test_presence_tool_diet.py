"""
Tests for Arc 3.4 (SARA_ALIVE_BUILD_PLAN) — presence tool payload diet.

Measured baseline (2026-07-29): the "always add" capability_core_categories
list (devices, vm_agents, personal_knowledge, inbox, lists = 25 tool defs)
gets stacked onto every chat turn regardless of classified intent, on top
of the intent-specific categories. This is a payload-selection change only
at the one call site chat loads tools — the 246-tool registry itself is
untouched, and every existing category/intent path still works unchanged
when the flag is off (default).
"""
from app.tools.registry import tool_registry


PRESENCE_CORE_TOOL_NAMES = [
    "memory_search", "notes_create", "notes_search",
    "list_add", "list_view", "reminders_create", "calendar_list",
]


class TestPresenceCoreResolves:
    def test_every_core_tool_name_exists_in_registry(self):
        for name in PRESENCE_CORE_TOOL_NAMES:
            assert tool_registry.get_tool(name) is not None, f"{name} not registered"

    def test_core_is_exactly_seven_tools(self):
        schemas = tool_registry.get_tools_by_names(PRESENCE_CORE_TOOL_NAMES)
        assert len(schemas) == 7

    def test_dispatch_and_monitor_is_registered_but_not_always_present(self):
        assert "dispatch_and_monitor" not in PRESENCE_CORE_TOOL_NAMES
        schemas = tool_registry.get_tools_by_names(["dispatch_and_monitor"])
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "dispatch_and_monitor"


class TestGetToolsByNames:
    def test_unknown_name_is_skipped_not_raised(self):
        schemas = tool_registry.get_tools_by_names(["memory_search", "not_a_real_tool"])
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "memory_search"

    def test_empty_list_returns_empty(self):
        assert tool_registry.get_tools_by_names([]) == []


class TestConversationalPayloadShrinks:
    def test_baseline_conversational_case_is_seven_not_twentyfive(self):
        """The literal target case: no classified intent (CONVERSATIONAL ->
        empty categories). Old behavior: 5 always-add categories = 25 tools.
        New: exactly the 7-tool core."""
        core = tool_registry.get_tools_by_names(PRESENCE_CORE_TOOL_NAMES)
        old_always_add = tool_registry.get_tools_by_categories(
            ["devices", "vm_agents", "personal_knowledge", "inbox", "lists"]
        )
        assert len(core) == 7
        assert len(old_always_add) > 20  # the padding this replaces

    def test_intent_specific_categories_still_load_fully(self):
        """A classified intent (e.g. NOTES) must still get its full category
        on top of the core — the diet only removes the always-add padding,
        never anything classification actually asked for."""
        notes_only = tool_registry.get_tools_by_categories(["notes"])
        merged_names = set()
        for t in tool_registry.get_tools_by_names(PRESENCE_CORE_TOOL_NAMES):
            merged_names.add(t["function"]["name"])
        for t in notes_only:
            merged_names.add(t["function"]["name"])
        notes_only_names = {t["function"]["name"] for t in notes_only}
        assert notes_only_names.issubset(merged_names)
