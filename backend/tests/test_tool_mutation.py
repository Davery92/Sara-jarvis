"""Mutation gate for chat tool selection (chat harness repair Phase 5).

Covers the exact "Required selection outcomes" table from
docs/plans/SARA_CHAT_HARNESS_MTP_REPAIR_PLAN_2026_09_16.md §8: semantic
proximity alone must never load a mutating tool into a casual turn.
"""
import pytest

from app.services.tool_mutation import (
    ALWAYS_ALLOWED_MUTATING,
    APPEND_ONLY_CAPABLE,
    CAPTURE_TOOLS,
    find_ambiguous_same_turn_removals,
    gate_mutating_tools,
    has_action_intent,
    has_bulk_intent,
    is_mutating_tool,
    is_removal_tool,
)
from app.services.tool_retrieval import CORE_TOOLS
from app.tools.registry import tool_registry


def _schema(name):
    return {"function": {"name": name}}


class TestClassification:
    def test_search_list_read_view_are_read_only(self):
        for name in ("memory_search", "notes_search", "calendar_list", "email_read",
                     "list_view", "email_attachment_read", "get_self_knowledge",
                     "get_tool_result_details", "find_tools"):
            assert not is_mutating_tool(name), name

    def test_create_add_delete_are_mutating(self):
        for name in ("notes_create", "list_add", "reminders_create",
                      "notes_delete", "list_remove", "calendar_create"):
            assert is_mutating_tool(name), name

    def test_mutating_token_wins_over_read_token_on_conflict(self):
        # "food_search_and_log" contains both "search" and "log"; it writes.
        assert is_mutating_tool("food_search_and_log")

    def test_unrecognized_name_defaults_to_mutating(self):
        assert is_mutating_tool("frobnicate_the_whatsit")

    def test_every_core_tool_resolves_to_a_classification(self):
        # No exception, no ambiguity — every CORE_TOOLS member classifies cleanly.
        for name in CORE_TOOLS:
            is_mutating_tool(name)  # must not raise


class TestActionIntent:
    def test_greetings_and_reactions_have_no_action_intent(self):
        for msg in (
            "Good morning Sara",
            "Shoulder workout was good, excited for hypertrophy work later",
            "I'm going zero-cal Monster or something",
            "It was 4 sets of 135x6",
            "Shoulder pain has gone away",
        ):
            assert not has_action_intent(msg), msg

    def test_imperative_requests_have_action_intent(self):
        for msg in (
            "Add four sets of 135x6 to my workout log",
            "Can you create a reminder for tomorrow at 9am?",
            "log this workout",
            "schedule a meeting with the team",
            "delete that note",
            "put the PDFs in the studio",
            "download those attachments and put them in a folder",
        ):
            assert has_action_intent(msg), msg

    def test_separable_take_off_out_phrasal_verb_has_action_intent(self):
        """R01 review remediation, live-model validation 2026-09-25: 'Take
        bread off the Grocery Run note, leave everything else' — a
        plainly explicit edit request — matched no verb at all before this
        fix (the object sits BETWEEN 'take' and 'off', so a flat substring
        list can't express it) and a real notes_edit call was wrongly
        refused by the execution-boundary check as a result."""
        for msg in (
            "Take bread off the Grocery Run note, leave everything else.",
            "Take out the trash reminder.",
            "Can you take that off my list?",
            "Take the rain jacket out of the packing list.",
        ):
            assert has_action_intent(msg), msg

    def test_take_without_off_or_out_has_no_action_intent(self):
        """The narrow phrasal-verb pattern must not become a bare 'take'
        match — these have no off/out at all, or too far away."""
        for msg in (
            "It'll take a while to get there.",
            "Just take it easy today.",
            "Take a look at this when you get a chance.",
        ):
            assert not has_action_intent(msg), msg

    def test_negated_take_off_out_has_no_action_intent(self):
        assert not has_action_intent("Don't take that off the list.")

    def test_negation_and_reported_facts_have_no_action_intent(self):
        """Living-world-context plan §3 finding: 'Tool gating treats words as
        authorization' — a listed verb appearing in a prohibition, a plain
        noun reference, or a past-state description is not a request."""
        for msg in (
            "Don't delete anything",
            "The email was interesting",
            "My workout is complete",
            "Please don't remove the reminder about the dentist",
            "I won't be able to send that today",
        ):
            assert not has_action_intent(msg), msg

    def test_action_verb_survives_alongside_an_unrelated_negation(self):
        # The gate is conservative about false positives, not about missing
        # a real request that happens to share a sentence with a denial.
        assert has_action_intent("Don't worry about that email, but can you schedule a meeting for 3pm")

    def test_dismissal_idiom_does_not_negate_a_following_clause(self):
        # "never mind" is a dismissal of what was just said, not a negation
        # of "cancel that" — the actual instruction in the second clause.
        assert has_action_intent("never mind, cancel that")


class TestHypotheticalObligationFix:
    """2026-09-24 fix: "if i leave it another month i'll have to start
    charging it rent" (pure hyperbole about a donation box) matched
    has_action_intent via "start", with no existing guard against a
    hypothetical/conditional-obligation framing. Reproduced live:
    gate_mutating_tools reopened reminders_create on the strength of this
    match with no real request behind it, producing a genuine duplicate
    write (SARA_NATURAL_CONVERSATION_EVALUATION_PLAN_2026_09_23.md's
    FINDINGS.md, item 2, case 23/context_fix_only/trial 2/turn 5 —
    verified against that run's turns.jsonl: reminders_create fired a
    second time for an already-fulfilled request).
    """

    def test_reproduced_bug_hypothetical_start(self):
        msg = "if i leave it another month i'll have to start charging it rent"
        assert not has_action_intent(msg), msg

    def test_hypothetical_obligation_generalizes_across_verbs_and_pronouns(self):
        for msg in (
            "if i don't get to it soon i'll have to start over from scratch",
            "we would have to cancel the whole trip if that happens",
            "i'd have to reschedule everything if the flight moves",
        ):
            assert not has_action_intent(msg), msg

    def test_a_real_request_in_a_different_clause_from_the_hypothetical_still_triggers(self):
        msg = "can you schedule a reminder, I'll have to leave early tomorrow"
        assert has_action_intent(msg), msg

    def test_genuine_bare_imperative_with_start_still_triggers(self):
        for msg in ("start a timer for 10 minutes", "can you start the laundry"):
            assert has_action_intent(msg), msg


class TestSelfFutureIntentFix:
    """Correction (2026-09-24, second review pass): a prior version of
    this patch asserted "I'll start the report tomorrow" SHOULD trigger
    has_action_intent, on the reasoning that bare future tense is a more
    genuine expression of intent than "I'll have to start X" (a reluctant
    hypothetical). That was wrong — has_action_intent gates whether a
    MUTATING TOOL is offered at all, and "I'll start the report tomorrow"
    describes DAVID's own future action, not a request for SARA to do
    anything. It must not itself grant mutation authority. This class
    replaces that incorrect assertion with the corrected one and covers
    the surrounding cases the correction must not break.
    """

    def test_bare_first_person_future_intent_has_no_action_intent(self):
        for msg in (
            "I'll start the report tomorrow",
            "I'm going to cancel my subscription next week",
            "I will reschedule that myself later",
        ):
            assert not has_action_intent(msg), msg

    def test_first_person_plural_future_intent_has_no_action_intent(self):
        assert not has_action_intent("we're going to reschedule the whole trip")

    def test_bare_imperative_with_no_subject_still_triggers(self):
        # No "I'll"/"we're going to" framing at all -- an unqualified
        # imperative still reads as a request.
        for msg in ("start a timer for 10 minutes", "schedule a meeting with the team"):
            assert has_action_intent(msg), msg

    def test_can_you_phrasing_is_unaffected_by_the_self_future_intent_guard(self):
        assert has_action_intent("can you start the laundry")

    def test_real_request_in_a_different_clause_from_self_future_intent_still_triggers(self):
        msg = "can you schedule a reminder, I'll be out most of tomorrow"
        assert has_action_intent(msg), msg

    def test_ordinary_modifiers_between_future_marker_and_verb_still_exclude(self):
        """Correction (2026-09-24, second review pass): the original
        pattern required the verb IMMEDIATELY after "I'll"/"I'm going to"
        with nothing in between, so an ordinary hedge adverb broke it —
        "I'll PROBABLY start the report tomorrow" matched has_action_intent
        (True) when it should not have, the same failure the guard exists
        to prevent, just with one word inserted."""
        for msg in (
            "I'll probably start the report tomorrow",
            "we're likely going to cancel the trip",
        ):
            assert not has_action_intent(msg), msg

    def test_a_separate_explicit_request_after_a_modified_future_intent_still_triggers(self):
        msg = "I'll probably start the report tomorrow, but can you set a reminder for 2pm"
        assert has_action_intent(msg), msg

    def test_a_non_modifier_word_in_the_gap_is_not_swallowed(self):
        """The modifier list is explicit and narrow, not "any word" — a
        first attempt at this fix allowed any 0-3 filler words and started
        excluding phrases like "I'll need you to start..." as a side
        effect. "need" is not a hedge adverb, so this stays actionable."""
        assert has_action_intent("I'll definitely need you to start the car")


class TestQuotedSpeechFix:
    """A verb inside a quoted span is reported/quoted speech ("he said
    'start the car'"), not David addressing Sara. Scoped to double quotes
    (straight and curly) only — single quotes are too often plain
    apostrophes to use safely as a quotation delimiter."""

    def test_quoted_verb_has_no_action_intent(self):
        for msg in (
            'he said "start the car" and walked off',
            'the note just says "cancel it"',
        ):
            assert not has_action_intent(msg), msg

    def test_unquoted_verb_after_a_quoted_span_still_triggers(self):
        # The quote closes before the real instruction — parity-based
        # detection must not treat everything after an opening quote as
        # permanently quoted.
        msg = 'he said "never mind" but actually can you cancel my 3pm'
        assert has_action_intent(msg), msg

    def test_quote_spanning_a_sentence_boundary_still_excludes_the_second_half(self):
        """2026-09-24 fix: quote parity used to be computed per-sentence,
        which reset to "not inside a quote" at every sentence boundary
        even when the quotation itself continues across it. 'he said
        "cancel this. also delete that" and hung up' splits into two
        sentences at the internal period; the second sentence
        ('also delete that" and hung up.') has only ONE quote character
        on its own (even count = 0 before "delete"), so the old
        per-sentence check incorrectly read it as unquoted."""
        msg = 'he said "cancel this. also delete that" and hung up'
        assert not has_action_intent(msg), msg

    def test_a_second_quote_later_in_a_multi_sentence_message_still_works(self):
        # A second, separate quotation later in the message must still be
        # detected correctly once the first one has closed -- confirms
        # the fix tracks parity across the whole message, not just "is
        # there ever an unmatched quote".
        msg = 'he said "never mind" then later added "cancel it too" as a joke'
        assert not has_action_intent(msg), msg


class TestContinuationDetection:
    def test_short_affirmatives_are_continuations(self):
        from app.services.tool_mutation import is_continuation_of_pending_action as cont
        for msg in ("yes", "yeah", "sure", "do it", "go ahead", "please", "correct"):
            assert cont(msg), msg

    def test_a_long_unrelated_message_containing_yes_is_not_a_continuation(self):
        from app.services.tool_mutation import is_continuation_of_pending_action as cont
        assert not cont(
            "yes I saw the game last night, did you catch the highlights from the third quarter"
        )

    def test_a_fresh_topic_change_is_not_a_continuation(self):
        from app.services.tool_mutation import is_continuation_of_pending_action as cont
        assert not cont("what's on my calendar today")

    def test_empty_message_is_not_a_continuation(self):
        from app.services.tool_mutation import is_continuation_of_pending_action as cont
        assert not cont("")
        assert not cont(None)


class TestGateMutatingTools:
    def test_casual_message_drops_all_mutating_tools_except_explicit_exception(self):
        schemas = [_schema(n) for n in CORE_TOOLS]
        kept, dropped = gate_mutating_tools(schemas, "Good morning Sara")

        kept_names = {(s["function"]["name"]) for s in kept}
        exempt = ALWAYS_ALLOWED_MUTATING | CAPTURE_TOOLS | APPEND_ONLY_CAPABLE
        for name in CORE_TOOLS:
            if is_mutating_tool(name) and name not in exempt:
                assert name not in kept_names, name
                assert name in dropped
        assert "acknowledge_notifications" in kept_names

    def test_capture_tools_survive_a_casual_message_deliberately(self):
        """The carve-out above is intentional, not an accidental leak.

        Capture tools are exempt because "remember that I met Dana from Acme"
        carries no verb from ACTION_INTENT_VERBS at all — see
        `tool_mutation.is_additive_capture_call`. Selection offers them; the
        execution boundary still decides whether the call that was actually
        made was additive or destructive.
        """
        schemas = [_schema(n) for n in sorted(CAPTURE_TOOLS | APPEND_ONLY_CAPABLE)]
        kept, dropped = gate_mutating_tools(schemas, "Good morning Sara")
        assert dropped == []
        assert len(kept) == len(CAPTURE_TOOLS | APPEND_ONLY_CAPABLE)

    def test_explicit_write_request_keeps_the_matching_mutating_tool(self):
        schemas = [_schema("reminders_create"), _schema("memory_search")]
        kept, dropped = gate_mutating_tools(
            schemas, "Can you create a reminder for tomorrow at 9am?"
        )
        names = {s["function"]["name"] for s in kept}
        assert "reminders_create" in names
        assert "memory_search" in names
        assert dropped == []

    def test_read_only_tools_are_never_gated(self):
        schemas = [_schema("memory_search"), _schema("notes_search"), _schema("email_read")]
        kept, dropped = gate_mutating_tools(schemas, "Good morning Sara")
        assert len(kept) == 3
        assert dropped == []

    def test_a_confirming_reply_continues_a_just_executed_operation(self):
        """'Yes, do it' continues a SPECIFIC just-performed/proposed action
        — not standing permission for the rest of the conversation."""
        schemas = [_schema("notes_create")]
        kept, dropped = gate_mutating_tools(
            schemas, "yes, do it", last_turn_mutating_tools=["notes_create"]
        )
        assert kept == schemas
        assert dropped == []

    def test_a_generic_later_message_gets_no_benefit_from_a_recent_write(self):
        """Living-world-context plan follow-up: executing a tool once must
        not become blanket authorization. 'okay what else' is not a
        confirmation of anything — it must NOT ride on reminders_create having
        run last turn, however recently.

        Exemplar changed from `notes_create` (2026-09-27): capture tools are
        now deliberately exempt from this gate, so they can no longer
        demonstrate the principle. `reminders_create` is a consequential write
        and is what this test was always actually about — see
        `test_capture_tools_survive_a_casual_message_deliberately`.
        """
        schemas = [_schema("reminders_create")]
        kept, dropped = gate_mutating_tools(
            schemas, "okay what else", last_turn_mutating_tools=["reminders_create"]
        )
        assert kept == []
        assert dropped == ["reminders_create"]

    def test_a_confirmation_does_not_authorize_a_DIFFERENT_tool(self):
        """The continuation is scoped to the specific tool that actually
        ran — confirming one operation must not wave through an unrelated
        mutating tool that merely happens to be offered the same turn."""
        schemas = [_schema("notes_create"), _schema("calendar_create")]
        kept, dropped = gate_mutating_tools(
            schemas, "yes, do it", last_turn_mutating_tools=["notes_create"]
        )
        names = {s["function"]["name"] for s in kept}
        assert names == {"notes_create"}
        assert dropped == ["calendar_create"]

    def test_a_confirmation_with_no_recent_mutation_authorizes_nothing(self):
        """'Yes, do it' out of the blue, with nothing to continue, is not
        evidence of anything — it must still be gated like any other
        message with no action evidence.

        Exemplar changed from `notes_create` to a consequential write
        (2026-09-27) for the reason given above.
        """
        schemas = [_schema("reminders_create")]
        kept, dropped = gate_mutating_tools(schemas, "yes, do it")
        assert kept == []
        assert dropped == ["reminders_create"]

    def test_workout_correction_without_add_verb_is_gated(self):
        """'It was 4 sets of 135x6' is a correction, not a request to log a
        new set — the plan's table allows a specific correction tool ONLY if
        authorized; absent that, no mutating tool should ride along."""
        schemas = [_schema("workout_log_create"), _schema("workout_details")]
        kept, dropped = gate_mutating_tools(schemas, "It was 4 sets of 135x6")
        names = {s["function"]["name"] for s in kept}
        assert "workout_log_create" not in names
        assert "workout_details" in names  # read-only, never gated


class TestGateMutatingToolsForThisRevisionsFixes:
    """The three fixes above (hypothetical obligation, self-future-intent,
    quoted speech) all operate through `has_action_intent`, one layer
    below the actual tool list `gate_mutating_tools` returns. These tests
    check the returned KEPT/DROPPED tool names directly — not just the
    boolean — since that tool list is what actually reaches the model.
    """

    def _reminders_and_read_tools(self):
        return [_schema("reminders_create"), _schema("memory_search")]

    def test_hypothetical_start_drops_the_mutating_tool_read_tool_stays(self):
        schemas = self._reminders_and_read_tools()
        kept, dropped = gate_mutating_tools(
            schemas, "if i leave it another month i'll have to start charging it rent"
        )
        kept_names = {s["function"]["name"] for s in kept}
        assert "reminders_create" not in kept_names
        assert "memory_search" in kept_names
        assert dropped == ["reminders_create"]

    def test_genuine_start_keeps_the_mutating_tool(self):
        schemas = self._reminders_and_read_tools()
        kept, dropped = gate_mutating_tools(schemas, "start a timer for 10 minutes")
        kept_names = {s["function"]["name"] for s in kept}
        assert "reminders_create" in kept_names
        assert dropped == []

    def test_self_future_intent_drops_the_mutating_tool(self):
        schemas = self._reminders_and_read_tools()
        kept, dropped = gate_mutating_tools(schemas, "I'll start the report tomorrow")
        kept_names = {s["function"]["name"] for s in kept}
        assert "reminders_create" not in kept_names
        assert dropped == ["reminders_create"]

    def test_self_future_intent_with_an_ordinary_modifier_drops_the_mutating_tool(self):
        schemas = self._reminders_and_read_tools()
        kept, dropped = gate_mutating_tools(schemas, "I'll probably start the report tomorrow")
        kept_names = {s["function"]["name"] for s in kept}
        assert "reminders_create" not in kept_names
        assert dropped == ["reminders_create"]

    def test_a_separate_request_after_a_modified_future_intent_keeps_the_mutating_tool(self):
        schemas = self._reminders_and_read_tools()
        kept, dropped = gate_mutating_tools(
            schemas, "I'll probably start the report tomorrow, but can you set a reminder for 2pm"
        )
        kept_names = {s["function"]["name"] for s in kept}
        assert "reminders_create" in kept_names
        assert dropped == []

    def test_quoted_verb_drops_the_mutating_tool(self):
        schemas = self._reminders_and_read_tools()
        kept, dropped = gate_mutating_tools(schemas, 'he said "cancel it" and left')
        kept_names = {s["function"]["name"] for s in kept}
        assert "reminders_create" not in kept_names
        assert dropped == ["reminders_create"]

    def test_real_request_after_a_quoted_span_keeps_the_mutating_tool(self):
        schemas = self._reminders_and_read_tools()
        kept, dropped = gate_mutating_tools(
            schemas, 'he said "never mind" but can you set a reminder for 3pm'
        )
        kept_names = {s["function"]["name"] for s in kept}
        assert "reminders_create" in kept_names
        assert dropped == []


class TestPlanOutcomesTable:
    """The exact table from Phase 5 §"Required selection outcomes"."""

    def test_add_four_sets_keeps_workout_write_tool(self):
        schemas = [_schema("workout_log_create")]
        kept, _ = gate_mutating_tools(
            schemas, "Add four sets of 135x6 to my workout log"
        )
        assert kept == schemas

    def test_pull_email_attachments_needs_no_gate_since_reads_are_never_mutating(self):
        schemas = [_schema("email_search"), _schema("email_read"), _schema("email_attachment_read")]
        kept, dropped = gate_mutating_tools(
            schemas, "Can you pull the attachments from that email?"
        )
        assert kept == schemas
        assert dropped == []


def _call(name, call_id, **args):
    import json
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


class TestIsRemovalTool:
    def test_delete_remove_cancel_are_removal_tools(self):
        for name in ("reminders_cancel", "notes_delete", "list_remove", "timers_cancel"):
            assert is_removal_tool(name), name

    def test_create_and_update_are_not_removal_tools(self):
        for name in ("reminders_create", "notes_edit", "workout_log_create"):
            assert not is_removal_tool(name), name


class TestHasBulkIntent:
    @pytest.mark.parametrize("message", [
        "delete both", "cancel all of them", "remove every one", "delete all",
        "cancel the whole list", "remove everything",
    ])
    def test_recognized_bulk_phrases(self, message):
        assert has_bulk_intent(message) is True

    @pytest.mark.parametrize("message", [
        "delete the bank reminder", "cancel my 3pm meeting", "remove the note about taxes",
    ])
    def test_ordinary_singular_requests_are_not_bulk(self, message):
        assert has_bulk_intent(message) is False

    # Post-hoc correction (Milestone-A review, 2026-09-22): has_bulk_intent
    # used to be a bare regex search over the WHOLE message, so a bulk
    # word anywhere — negated, or in an unrelated clause — incorrectly
    # authorized bulk deletion. Both of the exact examples from that
    # review are covered explicitly below, not just similar-shaped ones.
    @pytest.mark.parametrize("message", [
        "Delete the bank reminder, not both.",
        "Delete the bank reminder, not both of them.",
        "Don't delete all of them, just the bank one.",
        "Cancel the bank reminder, not every one of them.",
    ])
    def test_negated_bulk_word_is_not_bulk_intent(self, message):
        assert has_bulk_intent(message) is False

    @pytest.mark.parametrize("message", [
        "Delete the bank reminder after checking all my calendars.",
        "Cancel the dentist reminder, and while you're at it check all my notes.",
        "Remove the tax note before you look at every one of my emails.",
    ])
    def test_bulk_word_in_an_unrelated_clause_is_not_bulk_intent(self, message):
        assert has_bulk_intent(message) is False

    def test_a_removal_verb_with_no_bulk_word_anywhere_is_not_bulk(self):
        assert has_bulk_intent("Delete the bank reminder.") is False

    def test_bulk_word_with_no_removal_verb_anywhere_is_not_bulk_intent(self):
        """A message that never asks to delete/remove/cancel anything has
        nothing for bulk intent to authorize, regardless of "all"/"both"."""
        assert has_bulk_intent("I checked all my calendars today.") is False

    @pytest.mark.parametrize("message", [
        "Delete both bank reminders.",
        "Cancel all of them.",
        "Please delete both, they're duplicates.",
        "Remove every one of the test notes.",
    ])
    def test_genuine_bulk_requests_still_authorize(self, message):
        assert has_bulk_intent(message) is True


class TestFindAmbiguousSameTurnRemovals:
    """Harness/thinking/personality plan, Phase 4 — the exact incident this
    exists to stop: two reminders match "the bank," the model calls
    reminders_cancel on both instead of asking which one."""

    def test_two_different_targets_no_bulk_language_is_blocked(self):
        calls = [_call("reminders_cancel", "c1", reminder_id="rem-1"),
                 _call("reminders_cancel", "c2", reminder_id="rem-2")]
        blocked = find_ambiguous_same_turn_removals(calls, "Delete the reminder about the bank.")
        assert set(blocked) == {"c1", "c2"}

    def test_explicit_bulk_language_authorizes_both(self):
        calls = [_call("reminders_cancel", "c1", reminder_id="rem-1"),
                 _call("reminders_cancel", "c2", reminder_id="rem-2")]
        blocked = find_ambiguous_same_turn_removals(calls, "Delete both bank reminders.")
        assert blocked == []

    def test_a_single_removal_call_is_never_blocked(self):
        calls = [_call("reminders_cancel", "c1", reminder_id="rem-1")]
        assert find_ambiguous_same_turn_removals(calls, "Delete the dentist reminder.") == []

    def test_identical_arguments_repeated_is_not_this_checks_concern(self):
        """Same target called twice — that's _repeat_tool_note's territory
        (a duplicate call), not "acted on every candidate.\""""
        calls = [_call("reminders_cancel", "c1", reminder_id="rem-1"),
                 _call("reminders_cancel", "c2", reminder_id="rem-1")]
        assert find_ambiguous_same_turn_removals(calls, "Delete the dentist reminder.") == []

    def test_different_removal_tools_are_tracked_independently(self):
        """Two DIFFERENT ambiguous removals in one round — a reminder and a
        note both matched multiple candidates — must each be caught."""
        calls = [
            _call("reminders_cancel", "c1", reminder_id="rem-1"),
            _call("reminders_cancel", "c2", reminder_id="rem-2"),
            _call("notes_delete", "c3", note_id="note-1"),
            _call("notes_delete", "c4", note_id="note-2"),
        ]
        blocked = find_ambiguous_same_turn_removals(calls, "Delete the bank reminder and the tax note.")
        assert set(blocked) == {"c1", "c2", "c3", "c4"}

    def test_a_create_call_alongside_an_ambiguous_delete_is_not_touched(self):
        calls = [
            _call("reminders_cancel", "c1", reminder_id="rem-1"),
            _call("reminders_cancel", "c2", reminder_id="rem-2"),
            _call("reminders_create", "c3", text="new one"),
        ]
        blocked = find_ambiguous_same_turn_removals(calls, "Delete the bank reminder and add a new one.")
        assert set(blocked) == {"c1", "c2"}

    def test_empty_tool_calls_is_safe(self):
        assert find_ambiguous_same_turn_removals([], "delete the bank reminder") == []

    def test_three_way_ambiguity_blocks_all_three(self):
        calls = [_call("reminders_cancel", f"c{i}", reminder_id=f"rem-{i}") for i in range(3)]
        blocked = find_ambiguous_same_turn_removals(calls, "Delete the bank reminder.")
        assert set(blocked) == {"c0", "c1", "c2"}


class TestCrossRoundAmbiguousRemovals:
    """Post-hoc correction (Milestone-A review, 2026-09-22): the original
    guard only ever looked at one round's tool_calls, so a model calling
    reminders_cancel(rem-1) in round 1 and reminders_cancel(rem-2) in round
    2 sailed through both times — neither round's batch alone looked
    "multiple." `prior_attempts` (populated across rounds via
    `record_removal_attempts`) closes that."""

    def test_a_second_round_different_target_is_blocked_by_history(self):
        prior = {"reminders_cancel": {'{"reminder_id": "rem-1"}'}}
        round2 = [_call("reminders_cancel", "c2", reminder_id="rem-2")]
        blocked = find_ambiguous_same_turn_removals(
            round2, "Delete the bank reminder.", prior_attempts=prior)
        assert blocked == ["c2"]

    def test_a_second_round_identical_target_is_not_blocked(self):
        """Retrying the SAME target across rounds is not the ambiguous
        shape — that's _repeat_tool_note's territory."""
        prior = {"reminders_cancel": {'{"reminder_id": "rem-1"}'}}
        round2 = [_call("reminders_cancel", "c2", reminder_id="rem-1")]
        blocked = find_ambiguous_same_turn_removals(
            round2, "Delete the bank reminder.", prior_attempts=prior)
        assert blocked == []

    def test_no_prior_history_behaves_like_a_fresh_turn(self):
        round1 = [_call("reminders_cancel", "c1", reminder_id="rem-1")]
        assert find_ambiguous_same_turn_removals(
            round1, "Delete the bank reminder.", prior_attempts={}) == []
        assert find_ambiguous_same_turn_removals(
            round1, "Delete the bank reminder.", prior_attempts=None) == []

    def test_bulk_intent_still_clears_a_cross_round_match(self):
        prior = {"reminders_cancel": {'{"reminder_id": "rem-1"}'}}
        round2 = [_call("reminders_cancel", "c2", reminder_id="rem-2")]
        blocked = find_ambiguous_same_turn_removals(
            round2, "Delete both bank reminders.", prior_attempts=prior)
        assert blocked == []

    def test_record_removal_attempts_accumulates_across_calls(self):
        from app.services.tool_mutation import record_removal_attempts
        history: dict = {}
        record_removal_attempts(history, [_call("reminders_cancel", "c1", reminder_id="rem-1")])
        record_removal_attempts(history, [_call("reminders_cancel", "c2", reminder_id="rem-2")])
        assert history["reminders_cancel"] == {
            '{"reminder_id": "rem-1"}', '{"reminder_id": "rem-2"}',
        }

    def test_record_removal_attempts_ignores_non_removal_and_reads(self):
        from app.services.tool_mutation import record_removal_attempts
        history: dict = {}
        record_removal_attempts(history, [
            _call("reminders_create", "c1", text="new"),
            _call("reminders_list", "c2"),
        ])
        assert history == {}

    def test_a_blocked_attempt_still_counts_toward_a_later_third_target(self):
        """A blocked call still means "the model tried this" — a THIRD
        distinct target in a later round must also be caught, not treated
        as fresh because the second one never executed."""
        prior = {"reminders_cancel": {
            '{"reminder_id": "rem-1"}', '{"reminder_id": "rem-2"}',
        }}
        round3 = [_call("reminders_cancel", "c3", reminder_id="rem-3")]
        blocked = find_ambiguous_same_turn_removals(
            round3, "Delete the bank reminder.", prior_attempts=prior)
        assert blocked == ["c3"]
