"""
Tests for ContextRouter — which context layers get injected for a given message.
"""

import pytest
from app.services.context_router import ContextRouter, ContextDecision


class TestMemoryInjection:
    def test_memory_injected_for_memory_keywords(self, context_router):
        d = context_router.decide("GENERAL", "do you remember when we discussed that?", turn_count=5)
        assert d.inject_memory is True

    def test_memory_injected_first_turn(self, context_router):
        d = context_router.decide("FITNESS", "log my lunch", turn_count=0)
        assert d.inject_memory is True

    def test_memory_injected_for_questions(self, context_router):
        d = context_router.decide("FITNESS", "how many calories did I eat?", turn_count=5)
        assert d.inject_memory is True

    def test_no_memory_for_simple_command(self, context_router):
        d = context_router.decide("TIME", "set a timer for 5 minutes", turn_count=5)
        assert d.inject_memory is False

    def test_memory_injected_for_memory_intent(self, context_router):
        d = context_router.decide("MEMORY", "some message", turn_count=5)
        assert d.inject_memory is True

    def test_memory_injected_for_general_intent(self, context_router):
        d = context_router.decide("GENERAL", "some message", turn_count=5)
        assert d.inject_memory is True


class TestCognitiveInjection:
    def test_cognitive_for_conversational_early(self, context_router):
        d = context_router.decide("CONVERSATIONAL", "hey, how are things?", turn_count=1)
        assert d.inject_cognitive is True

    def test_no_cognitive_after_turn_2(self, context_router):
        d = context_router.decide("CONVERSATIONAL", "tell me more", turn_count=5)
        assert d.inject_cognitive is False

    def test_no_cognitive_for_task_intent(self, context_router):
        d = context_router.decide("FITNESS", "log my workout", turn_count=1)
        assert d.inject_cognitive is False


class TestInsightInjection:
    def test_insight_for_question(self, context_router):
        d = context_router.decide("GENERAL", "what patterns do you see?", turn_count=3)
        assert d.inject_insight is True

    def test_no_insight_for_task_intents(self, context_router):
        d = context_router.decide("TIME", "what's on my calendar?", turn_count=3)
        assert d.inject_insight is False

    def test_no_insight_without_question(self, context_router):
        d = context_router.decide("GENERAL", "just thinking out loud", turn_count=3)
        assert d.inject_insight is False


class TestDailyBriefInjection:
    def test_daily_brief_in_normal_mode(self, context_router):
        d = context_router.decide("GENERAL", "hello", turn_count=1, in_work_mode=False)
        assert d.inject_daily_brief is True

    def test_daily_brief_suppressed_in_work_mode(self, context_router):
        d = context_router.decide("GENERAL", "hello", turn_count=1, in_work_mode=True)
        assert d.inject_daily_brief is False

    def test_daily_brief_in_work_mode_with_keyword(self, context_router):
        d = context_router.decide("TIME", "what's on my calendar today?", turn_count=3, in_work_mode=True)
        assert d.inject_daily_brief is True


class TestBodyStateInjection:
    def test_body_state_in_normal_mode(self, context_router):
        d = context_router.decide("GENERAL", "hello", turn_count=1, in_work_mode=False)
        assert d.inject_body_state is True

    def test_body_state_suppressed_in_work_mode(self, context_router):
        d = context_router.decide("GENERAL", "hello", turn_count=1, in_work_mode=True)
        assert d.inject_body_state is False

    def test_body_state_in_work_mode_with_keyword(self, context_router):
        d = context_router.decide("GENERAL", "I'm feeling tired today", turn_count=3, in_work_mode=True)
        assert d.inject_body_state is True


class TestSoulInjection:
    def test_soul_always_injected(self, context_router):
        d = context_router.decide("TIME", "set timer 5 min", turn_count=10, in_work_mode=True)
        assert d.inject_soul is True


class TestPKGInjection:
    def test_pkg_for_personal_questions(self, context_router):
        d = context_router.decide("GENERAL", "what do you know about me?", turn_count=3)
        assert d.inject_pkg is True

    def test_pkg_first_turn(self, context_router):
        d = context_router.decide("CONVERSATIONAL", "hey there", turn_count=0)
        assert d.inject_pkg is True

    def test_pkg_for_conversational_intent(self, context_router):
        d = context_router.decide("CONVERSATIONAL", "I like cooking Italian food", turn_count=3)
        assert d.inject_pkg is True

    def test_pkg_suppressed_in_work_mode(self, context_router):
        d = context_router.decide("GENERAL", "some task", turn_count=3, in_work_mode=True)
        assert d.inject_pkg is False

    def test_pkg_in_work_mode_with_keyword(self, context_router):
        d = context_router.decide("GENERAL", "what do you know about me?", turn_count=3, in_work_mode=True)
        assert d.inject_pkg is True


class TestPatternInjection:
    def test_patterns_for_keyword(self, context_router):
        d = context_router.decide("GENERAL", "have you noticed any patterns?", turn_count=3)
        assert d.inject_patterns is True

    def test_patterns_first_turn_conversational(self, context_router):
        d = context_router.decide("CONVERSATIONAL", "good morning", turn_count=0)
        assert d.inject_patterns is True

    def test_patterns_suppressed_in_work_mode(self, context_router):
        d = context_router.decide("GENERAL", "some task", turn_count=3, in_work_mode=True)
        assert d.inject_patterns is False


class TestActivityContext:
    def test_activity_context_always_on(self, context_router):
        d = context_router.decide("TIME", "set timer", turn_count=10, in_work_mode=True)
        assert d.inject_activity_context is True


class TestLearningRecall:
    def test_learning_recall_for_topic_question(self, context_router):
        d = context_router.decide("CONVERSATIONAL", "how does quantum computing work exactly?", turn_count=3)
        assert d.inject_learning_recall is True

    def test_learning_recall_suppressed_in_work_mode(self, context_router):
        d = context_router.decide("CONVERSATIONAL", "how does quantum computing work?", turn_count=3, in_work_mode=True)
        assert d.inject_learning_recall is False

    def test_learning_recall_not_for_short_messages(self, context_router):
        d = context_router.decide("CONVERSATIONAL", "ok thanks", turn_count=3)
        assert d.inject_learning_recall is False

    def test_learning_recall_not_for_task_intent(self, context_router):
        d = context_router.decide("TIME", "how does my calendar look for the rest of the day?", turn_count=3)
        assert d.inject_learning_recall is False


class TestChangesBrief:
    def test_changes_brief_first_turn(self, context_router):
        d = context_router.decide("GENERAL", "hey", turn_count=0)
        assert d.inject_changes_brief is True

    def test_changes_brief_catch_me_up(self, context_router):
        d = context_router.decide("GENERAL", "catch me up on what happened", turn_count=5)
        assert d.inject_changes_brief is True

    def test_no_changes_brief_mid_conversation(self, context_router):
        d = context_router.decide("GENERAL", "tell me more", turn_count=5)
        assert d.inject_changes_brief is False


class TestLessonsInjection:
    def test_lessons_for_conversational(self, context_router):
        d = context_router.decide("CONVERSATIONAL", "let's chat", turn_count=1)
        assert d.inject_lessons is True

    def test_lessons_suppressed_in_work_mode(self, context_router):
        d = context_router.decide("CONVERSATIONAL", "let's chat", turn_count=1, in_work_mode=True)
        assert d.inject_lessons is False

    def test_no_lessons_for_task_intents(self, context_router):
        d = context_router.decide("TIME", "set timer 5 min", turn_count=1)
        assert d.inject_lessons is False


class TestDecisionStructure:
    def test_decision_is_namedtuple(self, context_router):
        d = context_router.decide("GENERAL", "hello", turn_count=0)
        assert isinstance(d, ContextDecision)
        assert len(d) == 13  # 12 bool fields + reason string

    def test_reason_string_present(self, context_router):
        d = context_router.decide("GENERAL", "hello", turn_count=0)
        assert isinstance(d.reason, str)
        assert "Injecting:" in d.reason

    def test_work_mode_in_reason(self, context_router):
        d = context_router.decide("GENERAL", "hello", turn_count=0, in_work_mode=True)
        assert "[WORK MODE]" in d.reason


class TestWorkModeSuppression:
    def test_work_mode_suppresses_extras(self, context_router):
        d = context_router.decide("GENERAL", "some task", turn_count=5, in_work_mode=True)
        # Work mode suppresses cognitive, patterns, daily_brief, body_state, pkg, lessons
        assert d.inject_cognitive is False
        assert d.inject_patterns is False
        assert d.inject_daily_brief is False
        assert d.inject_body_state is False
        assert d.inject_pkg is False
        assert d.inject_lessons is False
        # But soul and activity context stay on
        assert d.inject_soul is True
        assert d.inject_activity_context is True
