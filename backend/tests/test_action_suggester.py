"""
Tests for ActionSuggester — contextual follow-up suggestions after tool use.
"""

import pytest
from app.services.action_suggester import suggest, TOOL_SUGGESTIONS


class TestToolSpecificSuggestions:
    def test_calendar_suggestions(self):
        results = suggest(["calendar_list"], "Here's your schedule for today.")
        labels = [s["label"] for s in results]
        assert "Add event" in labels or "Tomorrow" in labels

    def test_food_log_suggestions(self):
        results = suggest(["log_food"], "Logged your chicken salad.")
        labels = [s["label"] for s in results]
        assert "Nutrition summary" in labels

    def test_notes_search_suggestions(self):
        results = suggest(["search_notes"], "Found 3 matching notes.")
        labels = [s["label"] for s in results]
        assert "Create note" in labels

    def test_weather_suggestions(self):
        results = suggest(["get_weather"], "It's 72°F and sunny.")
        labels = [s["label"] for s in results]
        assert "Tomorrow?" in labels

    def test_home_suggestions(self):
        results = suggest(["home_status"], "All lights are on.")
        labels = [s["label"] for s in results]
        assert "All lights off" in labels

    def test_timer_suggestions(self):
        results = suggest(["start_timer"], "Timer set for 5 minutes.")
        labels = [s["label"] for s in results]
        assert "Cancel timer" in labels

    def test_reminder_suggestions(self):
        results = suggest(["create_reminder"], "Reminder set.")
        labels = [s["label"] for s in results]
        assert "My reminders" in labels

    def test_email_search_suggestions(self):
        results = suggest(["email_search"], "Found 5 matching emails.")
        labels = [s["label"] for s in results]
        assert "Recent emails" in labels

    def test_learning_topic_suggestions(self):
        results = suggest(["learning_topic_list"], "Here are your topics.")
        labels = [s["label"] for s in results]
        assert "Continue Learning" in labels


class TestNoToolSuggestions:
    def test_no_suggestions_for_short_chitchat(self):
        results = suggest([], "You're welcome!")
        # Short response, no tool → minimal/no suggestions
        assert len(results) <= 1

    def test_long_response_gets_summarize(self):
        long_response = "x " * 300  # > 500 chars
        results = suggest([], long_response)
        labels = [s["label"] for s in results]
        assert "Summarize" in labels

    def test_medium_response_gets_tell_more(self):
        medium = "x " * 120  # > 200 chars, < 500 chars
        results = suggest([], medium)
        labels = [s["label"] for s in results]
        assert "Tell me more" in labels

    def test_sara_question_no_suggestions(self):
        # Sara asked a question → don't suggest, let user answer
        results = suggest([], "That sounds interesting! What kind of food do you want?")
        labels = [s["label"] for s in results]
        assert "Summarize" not in labels


class TestContextAwareSuggestions:
    def test_low_calories_suggest_log_meal(self):
        ctx = {"calories_today": 200, "calorie_goal": 2000}
        results = suggest([], "Anything else?", unified_context=ctx)
        labels = [s["label"] for s in results]
        assert "Log a meal" in labels

    def test_open_threads_suggest_followup(self):
        ctx = {"open_thread_count": 2, "ripe_thread_topics": ["dentist appointment"]}
        results = suggest([], "Anything else?", unified_context=ctx)
        labels = [s["label"] for s in results]
        assert any("Follow up" in l for l in labels)

    def test_learning_reviews_suggest_review(self):
        ctx = {"reviews_due": 3}
        results = suggest([], "Anything else?", unified_context=ctx)
        labels = [s["label"] for s in results]
        assert "Start review" in labels


class TestSuggestionLimits:
    def test_max_suggestions_limit(self):
        # Use a tool with 2 suggestions + context with 3 more
        ctx = {
            "calories_today": 200, "calorie_goal": 2000,
            "open_thread_count": 1, "ripe_thread_topics": ["project"],
            "reviews_due": 5,
        }
        results = suggest(["calendar_list"], "Your schedule.", unified_context=ctx)
        assert len(results) <= 4

    def test_no_duplicate_labels(self):
        # Multiple tools that produce same suggestions
        results = suggest(["calendar_list", "list_events"], "Calendar data.")
        labels = [s["label"] for s in results]
        assert len(labels) == len(set(labels))


class TestSuggestionFormat:
    def test_suggestion_has_label(self):
        results = suggest(["get_weather"], "Sunny.")
        for s in results:
            assert "label" in s
            assert isinstance(s["label"], str)

    def test_suggestion_has_message_or_action(self):
        results = suggest(["get_weather"], "Sunny.")
        for s in results:
            assert "message" in s or "action" in s

    def test_navigation_suggestion_has_target(self):
        results = suggest(["list_notes"], "Here are your notes.")
        nav = [s for s in results if s.get("action") == "navigate"]
        for s in nav:
            assert "target" in s
