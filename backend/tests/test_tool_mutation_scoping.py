"""Operation-and-target scoping and recurring-action authorization (Sara
repair plan R01 review remediation — round 1, 2026-09-25, and round 2,
2026-09-26).

The execution-boundary check (main_simple.py execute_tool, added for J11)
closed the pure bypass where a mutating tool could reach execution with NO
action evidence at all. But `has_action_intent` only asks "does this
message evidence SOME mutation" — it grants broad authority from any
action verb, with no binding to the SPECIFIC operation or target being
executed. This file tests the two additional, deterministic checks added
to close that gap:

1. `has_recurring_scope` / `RECURRING_ESTABLISHING_TOOLS` — a message with
   real, one-time action intent ("turn on the porch light") must not be
   sufficient by itself to authorize `standing_order_create`, which
   installs STANDING authority to act again on every future occurrence.

2. `find_target_unscoped_mutations` / `tool_domain_evidenced` — J10
   (J10_trial1_TURN3_WRONG_ENTITY_CANCELLED_CROSS_CONTEXT /
   J10_trial2_TURN3_SECOND_WRONG_ENTITY_ACTION): "permission to close one
   thread does not authorize cancelling unrelated work."

Round 1's version of check 2 (`find_cross_tool_unscoped_mutations`, now
removed) authorized scope-sensitive calls "by call order" — how many
action-evidenced CLAUSES the message had, counted against calls in the
order they arrived. Review correction: that is not target scoping. A
wrong-target call occurring first, or alone, passed regardless of whether
IT specifically was evidenced. It also had a real retry-bypass: blocked
calls were recorded into the same `seen_signatures` history as allowed
ones, so a retried blocked call matched "already seen" and was silently
let through the second time.

`find_target_unscoped_mutations` replaces it with a stateless, per-call
domain-evidence check — every scope-sensitive call, independent of order,
count, or whether it's a retry, is blocked unless the message actually
names the domain of entity that tool acts on. `TestFiveReviewScenarios`
below tests exactly the five scenarios the 2026-09-26 review named:
wrong target first, a single wrong-target call, a blocked call repeated in
a later round, explicit multiple requests, and bulk wording with targets
outside the requested scope.
"""
from app.services.tool_mutation import (
    find_target_unscoped_mutations,
    has_recurring_scope,
    is_scope_sensitive_tool,
    tool_domain_evidenced,
)

J11_HYPOTHETICAL = "I'm thinking about turning on the porch light when I get back."
J11_ONE_TIME_REQUEST = "Turn the test porch light on now at 30 percent."
J10_MESSAGE = "The Cedar follow-up is handled. Close that thread and stop reminding me about it."


def _tc(name, call_id, args="{}"):
    return {"id": call_id, "function": {"name": name, "arguments": args}}


class TestRecurringScope:
    def test_one_time_action_intent_has_no_recurring_scope(self):
        assert has_recurring_scope(J11_ONE_TIME_REQUEST) is False

    def test_hypothetical_musing_has_no_recurring_scope_either(self):
        assert has_recurring_scope(J11_HYPOTHETICAL) is False

    def test_explicit_recurring_language_is_recognized(self):
        assert has_recurring_scope("turn on the porch light every time I get home") is True
        assert has_recurring_scope("set up a standing order for the lights") is True
        assert has_recurring_scope("lock the doors every night at 11") is True
        assert has_recurring_scope("do this automatically from now on") is True

    def test_standing_order_create_is_the_recurring_establishing_tool(self):
        from app.services.tool_mutation import RECURRING_ESTABLISHING_TOOLS
        assert "standing_order_create" in RECURRING_ESTABLISHING_TOOLS
        # A one-time home-control tool must NOT be in this set — only the
        # tool that installs standing authority needs the extra check.
        assert "home_control" not in RECURRING_ESTABLISHING_TOOLS


class TestScopeSensitiveClassification:
    def test_cancel_delete_remove_resolve_complete_are_scope_sensitive(self):
        # Real registered tool names (app/tools/registry.py), not
        # hypothetical ones — verified against the actual registry so this
        # test can't drift from what production actually routes.
        for name in ("reminders_cancel", "notes_delete", "list_remove",
                     "resolve_thread", "cancel_research_plan",
                     "daily_task_complete", "timers_cancel",
                     "remove_directive", "map_delete_node"):
            assert is_scope_sensitive_tool(name) is True, name

    def test_reads_and_creates_are_not_scope_sensitive(self):
        for name in ("notes_search", "reminders_create", "notes_list", "calendar_list"):
            assert is_scope_sensitive_tool(name) is False, name


class TestDomainEvidence:
    def test_thread_domain_matches_literal_thread_noun(self):
        assert tool_domain_evidenced("resolve_thread", J10_MESSAGE) is True

    def test_reminders_domain_requires_the_noun_not_the_verb(self):
        # "stop reminding me about it" is a VERB form describing an action
        # on the thread, not a NOUN reference to a separate reminder
        # entity — this is exactly why the real trial-2 failure must not
        # be re-authorized by this phrase.
        assert tool_domain_evidenced("reminders_cancel", J10_MESSAGE) is False
        assert tool_domain_evidenced("reminders_cancel", "cancel my dentist reminder") is True
        assert tool_domain_evidenced("reminders_cancel", "cancel my reminders about the dentist") is True

    def test_research_plan_domain_requires_research_evidence(self):
        assert tool_domain_evidenced("cancel_research_plan", J10_MESSAGE) is False
        assert tool_domain_evidenced("cancel_research_plan", "cancel that research plan") is True

    def test_generic_fallback_matches_stem_words(self):
        assert tool_domain_evidenced("remove_directive", "remove that directive") is True
        assert tool_domain_evidenced("remove_directive", J10_MESSAGE) is False


class TestFiveReviewScenarios:
    """The five scenarios named verbatim in the 2026-09-26 review."""

    def test_wrong_target_first(self):
        """A wrong-target call occurring FIRST in the round must still be
        blocked — call order carries no authorization weight."""
        calls = [
            _tc("cancel_research_plan", "wrong_first"),  # no domain evidence
            _tc("resolve_thread", "correct_second"),      # "thread" is evidenced
        ]
        blocked = find_target_unscoped_mutations(calls, J10_MESSAGE)
        assert blocked == ["wrong_first"]

    def test_single_wrong_target_call(self):
        """The wrong-target call is the ONLY call this round — the old
        clause-count mechanism authorized exactly this shape ("1 clause, 1
        call" looked fine); target scoping must still refuse it."""
        message = "Cancel my dentist reminder."
        calls = [_tc("cancel_research_plan", "only_call")]
        blocked = find_target_unscoped_mutations(calls, message)
        assert blocked == ["only_call"]

    def test_blocked_call_repeated_in_a_later_round(self):
        """A call blocked in round 1 must remain blocked when retried,
        with identical arguments, in round 2 of the SAME turn — the
        retry-bypass this replaces let an exact repeat slip through as
        'already counted, not a new ask'. This check is stateless, so
        calling it again with the same (tool, message) must reproduce the
        same verdict, no history required."""
        message = "Cancel my dentist reminder."
        round1_calls = [_tc("cancel_research_plan", "r1", args='{"plan_id": "p1"}')]
        blocked_round1 = find_target_unscoped_mutations(round1_calls, message)
        assert blocked_round1 == ["r1"]

        round2_calls = [_tc("cancel_research_plan", "r2", args='{"plan_id": "p1"}')]
        blocked_round2 = find_target_unscoped_mutations(round2_calls, message)
        assert blocked_round2 == ["r2"]

    def test_explicit_multiple_requests(self):
        """Two genuinely distinct, explicitly evidenced requests, two
        different tools — both must be authorized. Target scoping must
        never degrade into 'only one mutating tool per turn, ever'."""
        message = "Cancel my research plan and mark my reminder done."
        calls = [
            _tc("cancel_research_plan", "c1"),
            _tc("reminders_cancel", "c2"),
        ]
        blocked = find_target_unscoped_mutations(calls, message)
        assert blocked == []

    def test_bulk_wording_with_targets_outside_the_requested_scope(self):
        """'Cancel all my reminders' only evidences the REMINDERS domain —
        it must not blanket-authorize an unrelated research_plan call just
        because bulk language appears somewhere in the message. (Multiple
        reminder TARGETS within the evidenced domain are a separate
        concern, owned by find_ambiguous_same_turn_removals /
        has_bulk_intent — this check only ever gates DOMAIN presence.)"""
        message = "Cancel all my reminders."
        calls = [
            _tc("reminders_cancel", "in_scope_1", args='{"reminder_id": "a"}'),
            _tc("reminders_cancel", "in_scope_2", args='{"reminder_id": "b"}'),
            _tc("cancel_research_plan", "out_of_scope"),
        ]
        blocked = find_target_unscoped_mutations(calls, message)
        assert blocked == ["out_of_scope"]


class TestTargetScopingGeneral:
    def test_j10_trial1_shape_research_plan_blocked_thread_allowed(self):
        calls = [
            _tc("resolve_thread", "c1"),
            _tc("cancel_research_plan", "c2"),
        ]
        blocked = find_target_unscoped_mutations(calls, J10_MESSAGE)
        assert blocked == ["c2"]

    def test_j10_trial2_shape_reminder_blocked_thread_allowed(self):
        calls = [
            _tc("resolve_thread", "c1"),
            _tc("reminders_cancel", "c2", args='{"reminder_id": "unrelated-123"}'),
        ]
        blocked = find_target_unscoped_mutations(calls, J10_MESSAGE)
        assert blocked == ["c2"]

    def test_same_tool_same_target_repeated_both_pass_when_domain_evidenced(self):
        """An exact repeat of an in-scope call is not this check's concern
        (find_ambiguous_same_turn_removals owns duplicate/multi-target
        policy for the SAME tool) — this check only cares whether the
        domain is evidenced, which it is for both calls here."""
        message = "Cancel that reminder."
        calls = [
            _tc("reminders_cancel", "c1", args='{"reminder_id": "t1"}'),
            _tc("reminders_cancel", "c2", args='{"reminder_id": "t1"}'),
        ]
        blocked = find_target_unscoped_mutations(calls, message)
        assert blocked == []

    def test_read_only_and_non_scope_sensitive_tools_are_never_blocked(self):
        calls = [
            _tc("notes_search", "c1"),
            _tc("reminders_create", "c2"),
        ]
        blocked = find_target_unscoped_mutations(calls, "hi there")
        assert blocked == []

    def test_empty_message_blocks_every_scope_sensitive_call(self):
        calls = [_tc("resolve_thread", "c1"), _tc("cancel_research_plan", "c2")]
        blocked = find_target_unscoped_mutations(calls, "")
        assert set(blocked) == {"c1", "c2"}
