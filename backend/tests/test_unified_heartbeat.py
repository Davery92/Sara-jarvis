"""
Tests for UnifiedHeartbeatAgent — Sara's background mind.

Tests parsing helpers, prompt construction, and nutrition stripping.
The full run() method is too integration-heavy; we test the pure logic helpers.
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.unified_agent import (
    UnifiedAgent,
    _strip_nutrition_context,
)


@pytest.fixture
def heartbeat_agent():
    """Create an agent with mocked LLM."""
    with patch("app.services.unified_agent.get_background_llm_client") as mock_get:
        mock_llm = MagicMock()
        mock_get.return_value = mock_llm
        agent = UnifiedAgent(user_id="test-user-id")
        yield agent


class TestToolCallParsing:
    def test_parse_text_tool_call(self, heartbeat_agent):
        text = 'Let me check. {"tool": "check_emails", "args": {"check_type": "action_required"}}'
        result = heartbeat_agent._parse_tool_call(text)
        assert result is not None
        tool_name, args = result
        assert tool_name == "check_emails"
        assert args["check_type"] == "action_required"

    def test_parse_tool_call_no_tool(self, heartbeat_agent):
        text = "Everything looks good. HEARTBEAT_OK"
        result = heartbeat_agent._parse_tool_call(text)
        assert result is None

    def test_parse_tool_call_malformed_json(self, heartbeat_agent):
        text = '{"tool": "broken", "args": {"key": invalid}}'
        result = heartbeat_agent._parse_tool_call(text)
        assert result is None

    def test_parse_tool_call_json_without_tool_key(self, heartbeat_agent):
        text = '{"name": "not_a_tool", "data": 42}'
        result = heartbeat_agent._parse_tool_call(text)
        assert result is None

    def test_parse_tool_call_nested_json(self, heartbeat_agent):
        text = 'Some text {"tool": "send_notification", "args": {"title": "Hey", "message": "How\'s it going?"}}'
        result = heartbeat_agent._parse_tool_call(text)
        assert result is not None
        assert result[0] == "send_notification"
        assert result[1]["title"] == "Hey"


class TestApiToolCallParsing:
    def test_parse_api_tool_call_direct(self, heartbeat_agent):
        tool_calls = [{
            "function": {
                "name": "check_emails",
                "arguments": json.dumps({"check_type": "action_required"}),
            }
        }]
        result = heartbeat_agent._parse_api_tool_call(tool_calls)
        assert result is not None
        assert result[0] == "check_emails"
        assert result[1]["check_type"] == "action_required"

    def test_parse_api_tool_call_wrapped(self, heartbeat_agent):
        tool_calls = [{
            "function": {
                "name": "tool.exec",
                "arguments": json.dumps({"tool": "home_status", "args": {}}),
            }
        }]
        result = heartbeat_agent._parse_api_tool_call(tool_calls)
        assert result is not None
        assert result[0] == "home_status"

    def test_parse_api_tool_call_empty(self, heartbeat_agent):
        result = heartbeat_agent._parse_api_tool_call([])
        assert result is None

    def test_parse_api_tool_call_none(self, heartbeat_agent):
        result = heartbeat_agent._parse_api_tool_call(None)
        assert result is None


class TestHandoffExtraction:
    def test_handoff_note_single_line(self, heartbeat_agent):
        text = "All checks done.\nHANDOFF: David seems busy, defer non-urgent items.\nHEARTBEAT_OK"
        result = heartbeat_agent._extract_handoff_note(text)
        assert result is not None
        assert "David seems busy" in result

    def test_handoff_note_case_insensitive(self, heartbeat_agent):
        text = "Done.\nhandoff: Keep watching the weather alert."
        result = heartbeat_agent._extract_handoff_note(text)
        assert result is not None
        assert "weather alert" in result

    def test_handoff_note_missing(self, heartbeat_agent):
        text = "Everything looks fine. HEARTBEAT_OK"
        result = heartbeat_agent._extract_handoff_note(text)
        assert result is None


class TestWatchingForExtraction:
    def test_watching_for_present(self, heartbeat_agent):
        text = "Checks complete. I'm watching for the delivery notification."
        result = heartbeat_agent._extract_watching_for(text)
        assert result is not None
        assert "delivery" in result

    def test_watching_for_keeping_eye(self, heartbeat_agent):
        text = "All good. Keeping an eye on David's sleep tonight."
        result = heartbeat_agent._extract_watching_for(text)
        assert result is not None
        assert "sleep" in result

    def test_watching_for_missing(self, heartbeat_agent):
        text = "Nothing to report. HEARTBEAT_OK"
        result = heartbeat_agent._extract_watching_for(text)
        assert result is None


class TestNutritionStripping:
    def test_strips_blood_sugar(self):
        ctx = "Activity: Active\nBlood sugar is low\nRoom: Office"
        result = _strip_nutrition_context(ctx)
        assert "blood sugar" not in result.lower()
        assert "Office" in result

    def test_strips_nutrition_line(self):
        ctx = "Nutrition: 1200/2000 cal\nMood: neutral"
        result = _strip_nutrition_context(ctx)
        assert "nutrition" not in result.lower()
        assert "Mood: neutral" in result

    def test_strips_meal_references(self):
        ctx = "Last meal was 3 hours ago\nCalendar: Meeting at 2pm"
        result = _strip_nutrition_context(ctx)
        assert "meal" not in result.lower()
        assert "Meeting" in result

    def test_empty_input(self):
        assert _strip_nutrition_context(None) == ""
        assert _strip_nutrition_context("") == ""

    def test_truncates_to_150(self):
        ctx = "Normal line one\n" * 20  # Long context
        result = _strip_nutrition_context(ctx)
        assert len(result) <= 150


class TestContextSummarizer:
    def test_summarize_with_state(self, heartbeat_agent):
        from app.services.unified_agent import SensedState
        state = SensedState(
            inferred_mood="focused",
            activity_state="active",
        )
        context = {
            "calendar": [{"title": "Meeting"}],
            "hours_since_last_chat": 2.5,
        }
        summary = heartbeat_agent._summarize_context(state, context)
        assert "mood=focused" in summary
        assert "1 events" in summary
        assert "last_chat=2.5h" in summary

    def test_summarize_empty(self, heartbeat_agent):
        from app.services.unified_agent import SensedState
        state = SensedState()
        summary = heartbeat_agent._summarize_context(state, {})
        assert summary == "minimal context"


class TestAgentInitialization:
    def test_agent_defaults(self, heartbeat_agent):
        assert heartbeat_agent.user_id == "test-user-id"
        assert heartbeat_agent.max_tool_iterations == 12

    def test_notification_queue_starts_empty(self, heartbeat_agent):
        assert heartbeat_agent._notification_queue == []

    def test_observations_start_empty(self, heartbeat_agent):
        assert heartbeat_agent._observations == []
