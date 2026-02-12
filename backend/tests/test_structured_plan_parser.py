"""
Tests for structured plan parser (Phase 1 — Cortana Evolution).

Scenarios:
- Valid JSON plan
- Invalid JSON (fallback to None)
- Partial JSON (missing fields)
- Empty plan
- Plan with unknown tool names
"""

import pytest
from app.services.autonomy.state_machine import (
    parse_structured_plan,
    ExecutionPlan,
    PlannedAction,
    PlannedNotification,
)


class TestValidJsonPlan:
    """Test parsing well-formed JSON plans."""

    def test_parse_json_code_block(self):
        raw = '''Here is my plan:
```json
{
  "actions": [
    {"action_name": "home_light_control", "action_args": {"entity_id": "light.office", "action": "turn_on"}, "reason": "Dark room"}
  ],
  "notifications": [
    {"title": "Lights on", "message": "Turned on office light", "priority": "normal"}
  ],
  "observations": ["Office was dark"],
  "handoff_note": "Lights are on now",
  "watching_for": "Motion sensor going off"
}
```
That's my plan.'''
        plan = parse_structured_plan(raw)
        assert plan is not None
        assert len(plan.actions) == 1
        assert plan.actions[0].action_name == "home_light_control"
        assert plan.actions[0].action_args["entity_id"] == "light.office"
        assert plan.actions[0].reason == "Dark room"
        assert len(plan.notifications) == 1
        assert plan.notifications[0].title == "Lights on"
        assert plan.observations == ["Office was dark"]
        assert plan.handoff_note == "Lights are on now"
        assert plan.watching_for == "Motion sensor going off"
        assert plan.fallback is False

    def test_parse_raw_json(self):
        raw = '{"actions": [], "notifications": [], "observations": ["All quiet"]}'
        plan = parse_structured_plan(raw)
        assert plan is not None
        assert len(plan.actions) == 0
        assert plan.observations == ["All quiet"]

    def test_parse_json_with_surrounding_text(self):
        raw = 'I analyzed the situation. {"actions": [{"action_name": "check_emails", "action_args": {}}], "notifications": []} End of response.'
        plan = parse_structured_plan(raw)
        assert plan is not None
        assert len(plan.actions) == 1
        assert plan.actions[0].action_name == "check_emails"

    def test_parse_code_block_without_json_tag(self):
        raw = '''```
{"actions": [{"action_name": "get_weather"}], "notifications": []}
```'''
        plan = parse_structured_plan(raw)
        assert plan is not None
        assert plan.actions[0].action_name == "get_weather"

    def test_multiple_actions(self):
        raw = '''{
  "actions": [
    {"action_name": "check_habits", "action_args": {}, "reason": "Morning check"},
    {"action_name": "check_emails", "action_args": {}, "reason": "Inbox scan"},
    {"action_name": "home_light_control", "action_args": {"entity_id": "light.kitchen"}, "reason": "Morning light"}
  ],
  "notifications": [],
  "observations": ["Good morning routine starting"]
}'''
        plan = parse_structured_plan(raw)
        assert plan is not None
        assert len(plan.actions) == 3
        assert plan.actions[2].action_args["entity_id"] == "light.kitchen"


class TestInvalidJson:
    """Test that invalid JSON returns None (triggering 4-phase fallback)."""

    def test_completely_invalid(self):
        assert parse_structured_plan("This is just text, no JSON at all") is None

    def test_malformed_json(self):
        raw = '{"actions": [{"action_name": "test"'  # Truncated
        assert parse_structured_plan(raw) is None

    def test_empty_string(self):
        assert parse_structured_plan("") is None

    def test_only_braces_no_content(self):
        assert parse_structured_plan("{ invalid json here }") is None

    def test_json_array_not_object(self):
        """A bare JSON array with no inner object returns empty plan (parser finds no top-level object)."""
        raw = '[1, 2, 3]'
        assert parse_structured_plan(raw) is None

    def test_code_block_with_invalid_json(self):
        raw = '```json\n{not valid json}\n```'
        assert parse_structured_plan(raw) is None

    def test_nested_incomplete_braces(self):
        raw = '{"actions": [{"action_name": "test", "action_args": {"entity_id": "light.office"'
        assert parse_structured_plan(raw) is None


class TestPartialJson:
    """Test plans with missing optional fields."""

    def test_actions_only(self):
        raw = '{"actions": [{"action_name": "check_habits"}]}'
        plan = parse_structured_plan(raw)
        assert plan is not None
        assert len(plan.actions) == 1
        assert plan.notifications == []
        assert plan.observations == []
        assert plan.handoff_note == ""

    def test_no_actions_field(self):
        raw = '{"notifications": [{"title": "Hi", "message": "Hello"}]}'
        plan = parse_structured_plan(raw)
        assert plan is not None
        assert plan.actions == []
        assert len(plan.notifications) == 1

    def test_action_missing_args(self):
        raw = '{"actions": [{"action_name": "get_weather"}]}'
        plan = parse_structured_plan(raw)
        assert plan is not None
        assert plan.actions[0].action_args == {}

    def test_empty_object(self):
        raw = '{}'
        plan = parse_structured_plan(raw)
        assert plan is not None
        assert plan.actions == []
        assert plan.notifications == []

    def test_action_missing_action_name_raises(self):
        """Actions missing required action_name should cause parse failure."""
        raw = '{"actions": [{"action_args": {"entity_id": "test"}}]}'
        plan = parse_structured_plan(raw)
        assert plan is None  # KeyError from PlannedAction construction


class TestEmptyPlan:
    """Test empty or effectively empty plans."""

    def test_empty_actions_list(self):
        raw = '{"actions": [], "notifications": [], "observations": []}'
        plan = parse_structured_plan(raw)
        assert plan is not None
        assert len(plan.actions) == 0

    def test_whitespace_only(self):
        assert parse_structured_plan("   \n\t  ") is None


class TestUnknownToolNames:
    """Test plans that reference tools not in the risk matrix."""

    def test_unknown_tool_parses_successfully(self):
        """Parser doesn't validate tool names — that's the policy engine's job."""
        raw = '{"actions": [{"action_name": "totally_made_up_tool", "action_args": {"foo": "bar"}}]}'
        plan = parse_structured_plan(raw)
        assert plan is not None
        assert plan.actions[0].action_name == "totally_made_up_tool"

    def test_multiple_unknown_tools(self):
        raw = '''{
  "actions": [
    {"action_name": "launch_missiles", "action_args": {}},
    {"action_name": "send_money", "action_args": {"amount": 1000000}}
  ]
}'''
        plan = parse_structured_plan(raw)
        assert plan is not None
        assert len(plan.actions) == 2
        # These should be blocked by policy engine, not parser


class TestExecutionPlanSerialization:
    """Test round-trip serialization."""

    def test_to_json_and_back(self):
        plan = ExecutionPlan(
            actions=[
                PlannedAction(action_name="test", action_args={"k": "v"}, reason="testing"),
            ],
            notifications=[
                PlannedNotification(title="T", message="M", priority="high"),
            ],
            observations=["obs1"],
            handoff_note="note",
            watching_for="something",
            reasoning="because",
        )
        data = plan.to_json()
        restored = ExecutionPlan.from_json(data)
        assert restored.actions[0].action_name == "test"
        assert restored.actions[0].action_args == {"k": "v"}
        assert restored.notifications[0].title == "T"
        assert restored.notifications[0].priority == "high"
        assert restored.observations == ["obs1"]
        assert restored.handoff_note == "note"
        assert restored.fallback is False

    def test_fallback_flag_serializes(self):
        plan = ExecutionPlan(fallback=True)
        data = plan.to_json()
        assert data["fallback"] is True
        restored = ExecutionPlan.from_json(data)
        assert restored.fallback is True
