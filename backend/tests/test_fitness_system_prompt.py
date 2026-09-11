"""Regression for SARA_CONVERSATION_COMPETENCE_PLAN_2026_09_10 Phase 5: the
fitness system prompt told the model to "offer to log" on any mention of a
meal/workout/goal, and its own worked example showed logging on a casual
mention — actively contradicting the grounding/plan-language gate added to
food_search_and_log.py in Phase 1. A persona instruction that tells the
model to do the opposite of what the tool enforces is exactly the kind of
duplicated behavioral patch Phase 5 asks to remove.
"""

from app.prompts.fitness_system_prompt import get_fitness_system_prompt


def test_does_not_instruct_unsolicited_logging_offers():
    prompt = get_fitness_system_prompt()
    assert "offer to log them" not in prompt
    assert "Log only what's confirmed" in prompt


def test_includes_a_plan_vs_logged_example():
    prompt = get_fitness_system_prompt()
    assert "a plan, not something eaten" in prompt


def test_does_not_encourage_repeated_recovery_nagging():
    prompt = get_fitness_system_prompt()
    assert "Encourage the user to log recovery metrics" not in prompt
