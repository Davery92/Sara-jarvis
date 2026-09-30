"""A correction keeps the tools of the domain it corrects.

Found live on the acceptance trial's food journey, in BOTH trials: "That was
actually 150 grams, not 100." classified GENERAL, which loads
`['memory','notes','time','web','home','fleet']` — no `fitness` — so
`food_log_correct` was never offered, the correction could not run, and Sara
truthfully told David she had no food tool. The turn before had written a food
entry.

This is the study's "intent routing excludes the needed tool family" class
(findings 27, 29, 38c, 38d, 40 — five instances). The retention logic itself
lives at the selection site in main_simple.py; what is testable in isolation is
the decision it makes, which is what these cases pin.
"""
import pytest

from app.services.operation_contract import (
    OperationKind,
    UtteranceClass,
    classify_utterance,
    domain_for_tool,
    is_elliptical_continuation,
    operation_kind_for,
)
from app.tools.registry import tool_registry


def would_retain(message: str, last_turn_mutating):
    """The same decision main_simple's selection site makes."""
    utterance = classify_utterance(message)
    continuing = (
        utterance is UtteranceClass.CORRECTION
        or is_elliptical_continuation(message)
    )
    if not (continuing and last_turn_mutating):
        return []
    active = {domain_for_tool(n) for n in last_turn_mutating}
    return sorted(
        name for name in tool_registry.tools
        if domain_for_tool(name) in active
        and operation_kind_for(name, None) in (
            OperationKind.UPDATE, OperationKind.RESCHEDULE, OperationKind.READ,
        )
    )


class TestTheLiveFailure:
    def test_a_food_correction_retains_the_food_tools(self):
        retained = would_retain("That was actually 150 grams, not 100.",
                                ["food_log_create"])
        assert "food_log_correct" in retained, (
            "the correction tool for the domain just written must be offered"
        )

    def test_it_also_retains_the_domains_reads(self):
        retained = would_retain("That was actually 150 grams, not 100.",
                                ["food_log_create"])
        assert "food_log_search" in retained or "food_log_summary" in retained

    def test_a_reminder_correction_retains_reschedule(self):
        retained = would_retain("Actually make it nine, not eight.",
                                ["reminders_create"])
        assert "reminders_reschedule" in retained
        assert "reminders_update" in retained

    def test_a_list_correction_retains_the_list_correction_tool(self):
        retained = would_retain("Make that two gallons of milk, not one.",
                                ["list_add"])
        assert "list_correct_item" in retained

    def test_an_elliptical_follow_up_retains_the_domain_too(self):
        retained = would_retain("And one for the dentist on October 2nd at 9am.",
                                ["reminders_create"])
        assert any(n.startswith("reminders_") for n in retained)


class TestItDoesNotOverReach:
    def test_nothing_is_retained_with_no_previous_write(self):
        assert would_retain("That was actually 150 grams, not 100.", []) == []

    def test_an_ordinary_instruction_retains_nothing(self):
        assert would_retain("Add milk to my grocery list.", ["food_log_create"]) == []

    def test_a_question_retains_nothing(self):
        assert would_retain("What did I eat today?", ["food_log_create"]) == []

    def test_only_the_active_domain_is_retained(self):
        retained = would_retain("That was actually 150 grams, not 100.",
                                ["food_log_create"])
        assert all(domain_for_tool(n) == "food" for n in retained), retained

    def test_no_destructive_tool_is_retained(self):
        """Retention offers the tools a correction needs. It does not put a
        delete on the menu because a create happened."""
        for last in (["food_log_create"], ["reminders_create"], ["list_add"],
                     ["notes_create"]):
            retained = would_retain("Actually that's wrong, make it X not Y.", last)
            for name in retained:
                assert operation_kind_for(name, None) not in (
                    OperationKind.DELETE, OperationKind.CANCEL,
                ), (last, name)
