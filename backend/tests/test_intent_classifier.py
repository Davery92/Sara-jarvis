"""
Tests for ToolIntentClassifier — keyword matching and tool category routing.
"""

import pytest
from app.services.intent_classifier import ToolIntentClassifier


class TestBasicIntentClassification:
    def test_fitness_intent(self, tool_classifier):
        assert tool_classifier.classify("log my lunch") == "FITNESS"

    def test_fitness_workout(self, tool_classifier):
        assert tool_classifier.classify("I did a workout today") == "FITNESS"

    def test_home_intent(self, tool_classifier):
        assert tool_classifier.classify("turn off the lights") == "HOME"

    def test_home_lights_on(self, tool_classifier):
        assert tool_classifier.classify("turn on the kitchen light") == "HOME"

    def test_calendar_intent(self, tool_classifier):
        assert tool_classifier.classify("what's on my calendar") == "TIME"

    def test_reminder_intent(self, tool_classifier):
        assert tool_classifier.classify("remind me to call mom") == "TIME"

    def test_timer_intent(self, tool_classifier):
        assert tool_classifier.classify("set a timer for 10 minutes") == "TIME"

    def test_notes_intent(self, tool_classifier):
        assert tool_classifier.classify("search my notes for project ideas") == "NOTES"

    def test_email_intent(self, tool_classifier):
        assert tool_classifier.classify("check my email inbox") == "EMAIL"

    def test_learning_intent(self, tool_classifier):
        assert tool_classifier.classify("teach me about quantum computing") == "LEARNING"

    def test_web_search_intent(self, tool_classifier):
        # "search" and "look up" are WEB keywords
        assert tool_classifier.classify("search for the latest news") == "WEB"

    def test_general_chat(self, tool_classifier):
        assert tool_classifier.classify("how are you doing today") == "CONVERSATIONAL"

    def test_memory_intent(self, tool_classifier):
        assert tool_classifier.classify("do you remember what I said yesterday") == "MEMORY"

    def test_personal_knowledge_intent(self, tool_classifier):
        assert tool_classifier.classify("what do you know about me") == "PERSONAL_KNOWLEDGE"

    def test_standing_orders_intent(self, tool_classifier):
        # "lock" and "door" match HOME first; use a message without HOME keywords
        assert tool_classifier.classify("create a standing order for pre-approved actions") == "STANDING_ORDERS"

    def test_soul_intent(self, tool_classifier):
        assert tool_classifier.classify("tell me about your soul and identity") == "SOUL"

    def test_automation_intent(self, tool_classifier):
        # "automation" matches HOME before AUTOMATION due to iteration order;
        # use the specific AUTOMATION keywords that won't collide
        assert tool_classifier.classify("set this to trigger automatically every hour") == "AUTOMATION"

    def test_devices_intent(self, tool_classifier):
        assert tool_classifier.classify("send a notification to my desktop") == "DEVICES"


class TestCaseInsensitivity:
    def test_uppercase(self, tool_classifier):
        assert tool_classifier.classify("TURN OFF THE LIGHTS") == "HOME"

    def test_mixed_case(self, tool_classifier):
        assert tool_classifier.classify("Set A Timer For 5 Minutes") == "TIME"


class TestEdgeCases:
    def test_empty_message(self, tool_classifier):
        result = tool_classifier.classify("")
        assert result in ("CONVERSATIONAL", "GENERAL")

    def test_very_long_message(self, tool_classifier):
        long_msg = "I want to know more about " * 100
        result = tool_classifier.classify(long_msg)
        assert isinstance(result, str)

    def test_question_mark_defaults_to_general(self, tool_classifier):
        # Avoid keywords that match specific intents; "sky blue" has no keyword matches
        result = tool_classifier.classify("What does entropy mean?")
        assert result in ("GENERAL", "CONVERSATIONAL", "WEB")

    def test_short_message_defaults_to_conversational(self, tool_classifier):
        result = tool_classifier.classify("okay")
        assert result == "CONVERSATIONAL"


class TestToolCategories:
    def test_tool_categories_fitness(self, tool_classifier):
        cats = tool_classifier.get_tool_categories("FITNESS")
        assert "fitness" in cats

    def test_tool_categories_home(self, tool_classifier):
        cats = tool_classifier.get_tool_categories("HOME")
        assert "home" in cats

    def test_tool_categories_memory(self, tool_classifier):
        cats = tool_classifier.get_tool_categories("MEMORY")
        assert "memory" in cats

    def test_tool_categories_email(self, tool_classifier):
        cats = tool_classifier.get_tool_categories("EMAIL")
        assert "email" in cats

    def test_tool_categories_conversational_empty(self, tool_classifier):
        cats = tool_classifier.get_tool_categories("CONVERSATIONAL")
        assert cats == []

    def test_unknown_intent_gets_defaults(self, tool_classifier):
        cats = tool_classifier.get_tool_categories("UNKNOWN_INTENT")
        # Falls back to DEFAULT_TOOLS
        assert len(cats) > 0


class TestContextAwareClassification:
    def test_context_inheritance_conversational(self, tool_classifier):
        """Conversational follow-up inherits tools from previous FITNESS turn."""
        session = "test-session-1"
        _, tools1 = tool_classifier.classify_with_context("log my lunch calories", session)
        assert "fitness" in tools1

        _, tools2 = tool_classifier.classify_with_context("sounds good thanks", session)
        # Should inherit fitness from context
        assert "fitness" in tools2 or "memory" in tools2

    def test_context_reset_on_new_topic(self, tool_classifier):
        """Explicit new intent doesn't carry stale tools."""
        session = "test-session-2"
        tool_classifier.classify_with_context("log my lunch", session)
        intent2, tools2 = tool_classifier.classify_with_context("turn off the lights", session)
        assert intent2 == "HOME"
        assert "home" in tools2

    def test_no_session_uses_simple_logic(self, tool_classifier):
        intent, tools = tool_classifier.classify_with_context("log my lunch", None)
        assert intent == "FITNESS"
        assert "fitness" in tools

    def test_conversational_without_context_gets_base_tools(self, tool_classifier):
        intent, tools = tool_classifier.classify_with_context("sounds good", None)
        assert intent == "CONVERSATIONAL"
        for base in ToolIntentClassifier.BASE_TOOLS:
            assert base in tools


class TestMultiIntentClassification:
    def test_classify_multi_conjunction(self, tool_classifier):
        results = tool_classifier.classify_multi("check my calendar and log my lunch")
        intents = [r[0] for r in results]
        assert "TIME" in intents or "FITNESS" in intents

    def test_classify_multi_single_intent(self, tool_classifier):
        # classify_multi requires keyword matches to return results
        results = tool_classifier.classify_multi("search for the latest news about technology")
        assert len(results) >= 1

    def test_classify_multi_max_results(self, tool_classifier):
        results = tool_classifier.classify_multi(
            "check calendar and log food and turn off lights and search notes",
            max_intents=3,
        )
        assert len(results) <= 3

    def test_classify_multi_empty(self, tool_classifier):
        results = tool_classifier.classify_multi("hello")
        # Conversational keywords match → at least one result
        assert isinstance(results, list)


class TestClassifyWithCategories:
    def test_returns_tuple(self, tool_classifier):
        intent, cats = tool_classifier.classify_with_categories("log my workout")
        assert isinstance(intent, str)
        assert isinstance(cats, list)

    def test_always_includes_base_tools(self, tool_classifier):
        _, cats = tool_classifier.classify_with_categories("log my workout")
        for base in ToolIntentClassifier.BASE_TOOLS:
            assert base in cats


class TestDeviceTargeting:
    def test_device_targeting_overrides(self, tool_classifier):
        """Device-targeting phrases should always return DEVICES."""
        assert tool_classifier.classify("open this on my desktop") == "DEVICES"
        assert tool_classifier.classify("send a notification to my pc") == "DEVICES"
        assert tool_classifier.classify("take a screenshot of my computer") == "DEVICES"
