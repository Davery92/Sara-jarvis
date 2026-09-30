"""The operation contract — reliable-assistant plan Phase C1.

Every example the plan requires "through the real execution boundary" has a
case here at the decision level, plus the classes the old single
`has_action_intent` boolean structurally could not distinguish. The
execution-boundary wiring is covered separately in
`test_execution_boundary_operation_contract.py`; this file pins the policy.
"""

import pytest

from app.services.operation_contract import (
    OperationKind,
    R_CORRECTION_IS_NOT_DELETION,
    R_NO_AUTHORITY_FOR_CLASS,
    R_NO_RECURRING_SCOPE,
    R_OPERATION_NOT_REQUESTED,
    R_OWNER_MISMATCH,
    R_PROPOSAL_KIND_MISMATCH,
    R_READ_ONLY,
    R_TARGET_AMBIGUOUS,
    R_TARGET_NOT_REFERENCED,
    ResolvedTarget,
    TargetResolution,
    TurnContext,
    UtteranceClass,
    Verdict,
    build_request,
    classify_utterance,
    decide,
    operation_kind_for,
    refusal_message,
    requested_operations,
)

OWNER = "owner-1"
OTHER = "owner-2"


def req(tool, args=None, *, source="model", proposal_id=None):
    return build_request(
        request_id="req-1", conversation_id="conv-1", owner_id=OWNER,
        tool_name=tool, arguments=args or {}, argument_source=source,
        proposal_id=proposal_id,
    )


def vet_reminder(target_id="rem-vet"):
    return ResolvedTarget(domain="reminders", target_id=target_id,
                          label="Vet appointment for Bramble")


def dentist_reminder():
    return ResolvedTarget(domain="reminders", target_id="rem-dentist",
                          label="Dentist cleaning")


def only_vet_resolves(named_id="rem-vet"):
    return TargetResolution(named=vet_reminder(named_id), candidates=(vet_reminder(),))


# ---------------------------------------------------------------------------
# Utterance classification
# ---------------------------------------------------------------------------


class TestUtteranceClassification:
    @pytest.mark.parametrize("message,expected", [
        # The plan's seven required examples.
        ("Scratch the vet one, I already called them.", UtteranceClass.INSTRUCTION),
        ("What time is the vet one set for?", UtteranceClass.QUESTION),
        ("I might cancel the vet one.", UtteranceClass.HYPOTHETICAL),
        ("Move the vet one to seven.", UtteranceClass.INSTRUCTION),
        ("Remember that I met Dana from Acme.", UtteranceClass.CAPTURE),
        ("Actually Priya is at Initech.", UtteranceClass.CORRECTION),
        ("Thanks.", UtteranceClass.ACKNOWLEDGEMENT),
        # Confirmations vs acknowledgements — different authority.
        ("Yes", UtteranceClass.CONFIRMATION),
        ("yes, do it", UtteranceClass.CONFIRMATION),
        ("ok do it", UtteranceClass.CONFIRMATION),
        ("ok", UtteranceClass.ACKNOWLEDGEMENT),
        ("thanks, appreciate it", UtteranceClass.ACKNOWLEDGEMENT),
        # Reported speech.
        ('He said "cancel the vet appointment" and hung up.', UtteranceClass.REPORTED),
        ("The note said delete it.", UtteranceClass.REPORTED),
        # Hypothetical / conditional framings.
        ("I'm thinking about turning on the porch light when I get back",
         UtteranceClass.HYPOTHETICAL),
        ("if I leave it another month I'll have to start charging it rent",
         UtteranceClass.HYPOTHETICAL),
        ("Should I cancel the vet one?", UtteranceClass.HYPOTHETICAL),
        # Request framings in question shape are instructions.
        ("Can you cancel the vet one?", UtteranceClass.INSTRUCTION),
        ("Could you move it to seven please", UtteranceClass.INSTRUCTION),
        # Capture phrasings the old fixed lexicon refused (7 of 9 measured).
        ("Remember that I met Dana from Acme, she runs their platform team",
         UtteranceClass.CAPTURE),
        ("Jot down that Marcus at Contoso is hiring two SREs", UtteranceClass.CAPTURE),
        ("FYI I talked to Priya from Globex about the migration", UtteranceClass.CAPTURE),
        ("Note that the keynote moved to hall C", UtteranceClass.CAPTURE),
        # Social.
        ("breakfast food tastes better at night", UtteranceClass.SOCIAL),
        ("everyone talks at me, nobody listens", UtteranceClass.SOCIAL),
    ])
    def test_class(self, message, expected):
        assert classify_utterance(message) is expected

    def test_exactly_one_class_per_turn(self):
        # A turn is one act; there is no "both" to reason about downstream.
        assert isinstance(classify_utterance("Scratch the vet one"), UtteranceClass)

    def test_a_quoted_imperative_does_not_become_an_instruction(self):
        assert classify_utterance('she texted "delete the invite"') is UtteranceClass.REPORTED

    def test_a_hypothetical_clause_does_not_disarm_a_real_request(self):
        # Two sentences: one musing, one an actual instruction.
        m = "I might redo the shelf. Cancel the vet reminder though."
        assert classify_utterance(m) is UtteranceClass.INSTRUCTION


class TestRequestedOperations:
    def test_reschedule_language_does_not_request_a_cancellation(self):
        ops = requested_operations("Move the vet one to seven.")
        assert OperationKind.RESCHEDULE in ops
        assert OperationKind.CANCEL not in ops
        assert OperationKind.DELETE not in ops

    def test_removal_language_requests_a_cancellation(self):
        ops = requested_operations("Scratch the vet one, I already called them.")
        assert OperationKind.CANCEL in ops

    def test_an_unlisted_imperative_verb_grants_NOTHING(self):
        """The wildcard is gone (2026-09-29). An imperative whose verb the
        application does not understand used to contribute UPDATE, RESCHEDULE,
        COMPLETE, CANCEL *and* CONTROL — a verb it cannot read granting authority
        to delete. It now grants nothing and produces a CLARIFY instead."""
        from app.services.operation_contract import unresolved_imperative
        assert requested_operations("Bin the vet one.") - {OperationKind.READ} == frozenset()
        assert unresolved_imperative("Bin the vet one.")

    def test_the_unclear_instruction_asks_rather_than_acts_or_refuses(self):
        from app.services.operation_contract import R_OPERATION_UNCLEAR
        d = decide(req("reminders_cancel", {"reminder_id": "rem-vet"}),
                   TurnContext.build("Bin the vet one."), only_vet_resolves())
        assert d.verdict is Verdict.CLARIFY, d
        assert d.reason == R_OPERATION_UNCLEAR
        text = refusal_message(d, "reminders_cancel").lower()
        assert "which" in text
        assert "did not run" in text

    @pytest.mark.parametrize("message,kind", [
        # Each of these is in a verb table against a recorded case, not swept up
        # by a wildcard.
        ("Scratch the vet one, I already called them.", OperationKind.CANCEL),
        ("Got the bread.", OperationKind.COMPLETE),
        ("Picked up the milk.", OperationKind.COMPLETE),
    ])
    def test_the_verbs_we_have_evidence_for_are_identified(self, message, kind):
        assert kind in requested_operations(message), message

    @pytest.mark.parametrize("message", [
        "Bin the vet one.", "Yeet the vet one.", "Sort the vet one out.",
    ])
    def test_no_unknown_verb_grants_a_destructive_operation(self, message):
        ops = requested_operations(message)
        assert OperationKind.CANCEL not in ops, message
        assert OperationKind.DELETE not in ops, message

    def test_an_unclear_instruction_does_not_clarify_a_non_target_operation(self):
        # CLARIFY is for "which of your things did you mean to do what to".
        # A create has no existing target, so it stays a plain refusal.
        d = decide(req("reminders_create", {"title": "x", "reminder_time": "y"}),
                   TurnContext.build("Bin the vet one."))
        assert d.verdict is Verdict.REFUSE

    def test_a_question_requests_only_a_read(self):
        ops = requested_operations("What time is the vet one set for?")
        assert ops <= {OperationKind.READ}

    def test_a_negated_verb_requests_nothing(self):
        assert OperationKind.CANCEL not in requested_operations(
            "Don't cancel the vet one, I still need it"
        )

    def test_two_explicit_requests_grant_both(self):
        ops = requested_operations("Cancel the standing order and mark the reminder done")
        assert OperationKind.CANCEL in ops
        assert OperationKind.COMPLETE in ops


class TestCreationPhrasings:
    """Found live: the first journey turn, "Set a reminder to call the vet at
    5pm on October 1st", was refused as operation_not_requested_by_message.
    "Set" is genuinely an update verb; what makes these creations is the
    indefinite object."""

    @pytest.mark.parametrize("message", [
        "Set a reminder to call the vet at 5pm on October 1st.",
        "Set an alarm for 6am.",
        "Put a timer on for ten minutes.",
        "Make me an appointment note for Thursday.",
        "Can you set up a new list for the hardware store?",
        "I need another reminder for the dentist.",
        "Start a timer for 20 minutes.",
    ])
    def test_it_requests_a_creation(self, message):
        assert OperationKind.CREATE in requested_operations(message), message

    def test_the_first_journey_turn_is_authorized(self):
        d = decide(req("reminders_create",
                       {"title": "call the vet", "reminder_time": "2026-10-01T17:00:00"}),
                   TurnContext.build("Set a reminder to call the vet at 5pm on October 1st."))
        assert d.verdict is Verdict.ALLOW, d

    def test_a_reference_to_an_existing_reminder_is_still_not_a_creation(self):
        # "the vet one" is definite: it names something that already exists.
        assert OperationKind.CREATE not in requested_operations("Move the vet one to seven.")

    def test_a_negated_creation_requests_nothing(self):
        assert OperationKind.CREATE not in requested_operations(
            "Don't set a reminder for that, I'll remember")


class TestEllipticalFollowUps:
    """Found live on the reminder journey's second turn: "And one for the
    dentist on October 2nd at 9am." was refused as
    operation_not_requested_by_message. It names no operation at all — the
    operation is the one from the turn that just ran."""

    @pytest.mark.parametrize("message", [
        "And one for the dentist on October 2nd at 9am.",
        "Also one for Friday.",
        "Another for the dentist at 9.",
        "Same for Tuesday.",
        "Oh and one at 6 too.",
    ])
    def test_it_is_recognized(self, message):
        from app.services.operation_contract import is_elliptical_continuation
        assert is_elliptical_continuation(message), message

    @pytest.mark.parametrize("message", [
        "And cancel the dentist one.",             # names its own operation
        "Also, what's on my calendar tomorrow?",   # a question
        "And then I drove home and the whole thing fell apart again honestly",  # too long
        "The dentist one at 9am.",                 # no connective
    ])
    def test_it_is_not_over_applied(self, message):
        from app.services.operation_contract import is_elliptical_continuation
        assert not is_elliptical_continuation(message), message

    def test_the_second_journey_turn_is_authorized(self):
        d = decide(
            req("reminders_create",
                {"title": "dentist", "reminder_time": "2026-10-02T09:00:00"}),
            TurnContext.build("And one for the dentist on October 2nd at 9am.",
                              last_turn_mutating_tools=["reminders_create"]),
        )
        assert d.verdict is Verdict.ALLOW, d

    def test_it_only_licenses_the_tool_that_actually_ran(self):
        # An elliptical turn cannot escalate to an operation David did not
        # just have done.
        d = decide(req("reminders_cancel", {"reminder_id": "rem-vet"}),
                   TurnContext.build("And one for the dentist at 9am.",
                                     last_turn_mutating_tools=["reminders_create"]),
                   only_vet_resolves())
        assert d.verdict is Verdict.REFUSE, d

    def test_with_no_previous_write_it_grants_nothing(self):
        d = decide(req("reminders_create", {"title": "x", "reminder_time": "y"}),
                   TurnContext.build("And one for the dentist at 9am."))
        assert d.verdict is Verdict.REFUSE


class TestRefusalsDoNotCoachDavid:
    @pytest.mark.parametrize("message", [
        "Thanks.", "I might cancel the vet one.", "What time is the vet one set for?",
    ])
    def test_it_never_asks_him_to_repeat_or_rephrase(self, message):
        # Found live: Sara answered a refusal with "the reminder system refused
        # the calls. Could you nudge me again in a moment?" — the gate leaking
        # into David's vocabulary, in a new shape.
        d = decide(req("reminders_cancel", {"reminder_id": "rem-vet"}),
                   TurnContext.build(message), only_vet_resolves())
        text = refusal_message(d, "reminders_cancel").lower()
        assert "repeat himself" in text
        assert "nudge" in text
        assert "do not say the system refused" in text


class TestOperationEquivalence:
    """"Cancel" and "delete" are one intent; which word the TOOL happens to
    use is an accident of this codebase's naming."""

    def test_delete_language_authorizes_a_cancel_tool(self):
        d = decide(req("reminders_cancel", {"reminder_id": "rem-vet"}),
                   TurnContext.build("delete the vet reminder"), only_vet_resolves())
        assert d.verdict is Verdict.ALLOW, d

    def test_cancel_language_authorizes_a_delete_tool(self):
        note = ResolvedTarget(domain="notes", target_id="n1", label="Vet notes")
        d = decide(req("notes_delete", {"note_id": "n1"}),
                   TurnContext.build("cancel that vet note"),
                   TargetResolution(named=note, candidates=(note,)))
        assert d.verdict is Verdict.ALLOW, d

    def test_completion_language_does_not_authorize_a_cancellation(self):
        # Marking something done and getting rid of it leave the record in
        # different states, so these are NOT interchangeable.
        d = decide(req("reminders_cancel", {"reminder_id": "rem-vet"}),
                   TurnContext.build("mark the vet reminder done"), only_vet_resolves())
        assert d.verdict is Verdict.REFUSE
        assert d.reason == R_OPERATION_NOT_REQUESTED


class TestOperationKindForTool:
    @pytest.mark.parametrize("tool,args,expected", [
        ("reminders_list", {}, OperationKind.READ),
        ("notes_search", {}, OperationKind.READ),
        ("query_david_knowledge", {}, OperationKind.READ),
        ("verify_action", {}, OperationKind.READ),
        ("notes_create", {}, OperationKind.CAPTURE),
        ("reminders_create", {}, OperationKind.CREATE),
        ("reminders_cancel", {}, OperationKind.CANCEL),
        ("notes_delete", {}, OperationKind.DELETE),
        ("standing_order_create", {}, OperationKind.RECURRING),
        ("home_light_control", {}, OperationKind.CONTROL),
        ("resolve_thread", {}, OperationKind.COMPLETE),
        ("list_check", {}, OperationKind.COMPLETE),
        # notes_edit depends on its arguments, not its name.
        ("notes_edit", {"append_text": "Correction: Initech"}, OperationKind.CAPTURE),
        ("notes_edit", {"content": "wholly new body"}, OperationKind.UPDATE),
        ("notes_edit", {"title": "new title"}, OperationKind.UPDATE),
        ("notes_edit", {"remove_text": "spare cable"}, OperationKind.UPDATE),
        # An append smuggled in alongside a rewrite is still a rewrite.
        ("notes_edit", {"append_text": "x", "content": "y"}, OperationKind.UPDATE),
    ])
    def test_kind(self, tool, args, expected):
        assert operation_kind_for(tool, args) is expected

    def test_unparseable_arguments_are_never_the_safe_shape(self):
        assert operation_kind_for("notes_edit", None) is OperationKind.UPDATE


# ---------------------------------------------------------------------------
# The plan's required examples, end to end through decide()
# ---------------------------------------------------------------------------


class TestPlanRequiredExamples:
    def test_scratch_the_vet_one_cancels_the_uniquely_resolved_reminder(self):
        m = "Scratch the vet one, I already called them."
        d = decide(req("reminders_cancel", {"reminder_id": "rem-vet"}),
                   TurnContext.build(m), only_vet_resolves())
        assert d.verdict is Verdict.ALLOW, d
        assert d.resolved_target_ids == ("rem-vet",)

    def test_what_time_is_the_vet_one_set_for_is_read_only(self):
        m = "What time is the vet one set for?"
        allow = decide(req("reminders_list", {}), TurnContext.build(m))
        assert allow.verdict is Verdict.ALLOW
        assert allow.reason == R_READ_ONLY

        refuse = decide(req("reminders_cancel", {"reminder_id": "rem-vet"}),
                        TurnContext.build(m), only_vet_resolves())
        assert refuse.verdict is Verdict.REFUSE
        assert refuse.reason == R_NO_AUTHORITY_FOR_CLASS

    def test_i_might_cancel_the_vet_one_mutates_nothing(self):
        m = "I might cancel the vet one."
        d = decide(req("reminders_cancel", {"reminder_id": "rem-vet"}),
                   TurnContext.build(m), only_vet_resolves())
        assert d.verdict is Verdict.REFUSE
        assert d.reason == R_NO_AUTHORITY_FOR_CLASS

    def test_move_the_vet_one_to_seven_reschedules_and_does_not_cancel(self):
        m = "Move the vet one to seven."
        ok = decide(req("reminders_reschedule", {"reminder_id": "rem-vet", "new_time": "19:00"}),
                    TurnContext.build(m), only_vet_resolves())
        assert ok.verdict is Verdict.ALLOW, ok

        # The same message must NOT independently authorize a cancellation.
        no = decide(req("reminders_cancel", {"reminder_id": "rem-vet"}),
                    TurnContext.build(m), only_vet_resolves())
        assert no.verdict is Verdict.REFUSE
        assert no.reason == R_OPERATION_NOT_REQUESTED

    def test_remember_that_i_met_dana_saves_without_an_action_verb(self):
        m = "Remember that I met Dana from Acme."
        d = decide(req("notes_create", {"title": "Dana", "content": "…"}),
                   TurnContext.build(m))
        assert d.verdict is Verdict.ALLOW, d

    def test_a_capture_disclosure_does_not_authorize_an_unrelated_action(self):
        m = "Remember that I met Dana from Acme."
        d = decide(req("reminders_create", {"title": "call Dana", "reminder_time": "…"}),
                   TurnContext.build(m))
        assert d.verdict is Verdict.REFUSE

    def test_actually_priya_is_at_initech_corrects_the_referenced_fact(self):
        m = "Actually Priya is at Initech now, not Globex - fix that"
        note = ResolvedTarget(domain="notes", target_id="note-priya",
                              label="Priya Raghavan — Globex")
        d = decide(req("notes_edit", {"note_id": "note-priya", "remove_text": "Globex"}),
                   TurnContext.build(m),
                   TargetResolution(named=note, candidates=(note,)))
        assert d.verdict is Verdict.ALLOW, d

    def test_a_correction_does_not_authorize_a_deletion(self):
        m = "Actually Priya is at Initech now, not Globex"
        note = ResolvedTarget(domain="notes", target_id="note-priya",
                              label="Priya Raghavan — Globex")
        d = decide(req("notes_delete", {"note_id": "note-priya"}),
                   TurnContext.build(m),
                   TargetResolution(named=note, candidates=(note,)))
        assert d.verdict is Verdict.REFUSE
        assert d.reason == R_CORRECTION_IS_NOT_DELETION

    def test_thanks_repeats_no_write(self):
        # Finding 38b: a bare "Thanks." after a completed write triggered a
        # real duplicate reminders_create.
        d = decide(req("reminders_create", {"title": "vet", "reminder_time": "…"}),
                   TurnContext.build("Thanks.",
                                     last_turn_mutating_tools=["reminders_create"]))
        assert d.verdict is Verdict.REFUSE
        assert d.reason == R_NO_AUTHORITY_FOR_CLASS

    def test_thanks_still_allows_a_read(self):
        d = decide(req("reminders_list", {}), TurnContext.build("Thanks."))
        assert d.verdict is Verdict.ALLOW


# ---------------------------------------------------------------------------
# Target binding (plan C2)
# ---------------------------------------------------------------------------


class TestTargetBinding:
    def test_another_owners_row_is_refused_with_no_fallback(self):
        d = decide(req("reminders_cancel", {"reminder_id": "rem-someone-else"}),
                   TurnContext.build("Cancel the vet reminder"),
                   TargetResolution(owner_mismatch=True))
        assert d.verdict is Verdict.REFUSE
        assert d.reason == R_OWNER_MISMATCH

    def test_two_matching_rows_ask_rather_than_guess(self):
        d = decide(req("reminders_cancel", {}),
                   TurnContext.build("Cancel the bank reminder"),
                   TargetResolution(candidates=(vet_reminder("rem-bank-1"),
                                                vet_reminder("rem-bank-2"))))
        assert d.verdict is Verdict.CLARIFY
        assert d.reason == R_TARGET_AMBIGUOUS
        assert len(d.candidate_ids) == 2

    def test_several_equally_matching_rows_ask_even_when_one_was_named(self):
        """Found live: "Cancel the plant one." with both "Water the plants" and
        "Repot the plant in the office" pending. The call named one of them and
        it was cancelled — a guess, and the wrong one."""
        watering = ResolvedTarget(domain="reminders", target_id="rem-water",
                                  label="Water the plants")
        repot = ResolvedTarget(domain="reminders", target_id="rem-repot",
                               label="Repot the plant in the office")
        d = decide(req("reminders_cancel", {"reminder_id": "rem-water"}),
                   TurnContext.build("Cancel the plant one."),
                   TargetResolution(named=watering, candidates=(watering, repot),
                                    domain_referenced=False, label_referenced=True))
        assert d.verdict is Verdict.CLARIFY, d
        assert len(d.candidate_ids) == 2

    def test_an_update_among_several_candidates_still_runs(self):
        # Refusing every update in a multi-item domain would make it unusable,
        # and naming the wrong one for an update is recoverable.
        a = ResolvedTarget(domain="notes", target_id="n1", label="Plant care notes")
        b = ResolvedTarget(domain="notes", target_id="n2", label="Plant shopping list")
        d = decide(req("notes_edit", {"note_id": "n1", "append_text": "x"}),
                   TurnContext.build("Add a line to the plant note"),
                   TargetResolution(named=a, candidates=(a, b)))
        assert d.verdict is Verdict.ALLOW, d

    def test_a_single_matching_row_is_still_cancelled_without_asking(self):
        d = decide(req("reminders_cancel", {"reminder_id": "rem-vet"}),
                   TurnContext.build("Cancel the vet one."), only_vet_resolves())
        assert d.verdict is Verdict.ALLOW, d

    def test_a_call_naming_a_row_the_words_never_referenced_is_refused(self):
        d = decide(req("reminders_cancel", {"reminder_id": "rem-dentist"}),
                   TurnContext.build("Cancel the vet reminder"),
                   TargetResolution(named=dentist_reminder(),
                                    candidates=(vet_reminder(),)))
        assert d.verdict is Verdict.REFUSE
        assert d.reason == R_TARGET_NOT_REFERENCED

    def test_a_unique_reference_with_no_id_argument_resolves_the_target(self):
        d = decide(req("reminders_cancel", {}),
                   TurnContext.build("Cancel the vet reminder"),
                   TargetResolution(candidates=(vet_reminder(),)))
        assert d.verdict is Verdict.ALLOW
        assert d.resolved_target_ids == ("rem-vet",)

    def test_an_unresolvable_target_lets_the_tool_fail_honestly(self):
        # Blocking here manufactures false refusals; the tool's own "not
        # found" is the honest answer. Documented choice, pinned.
        d = decide(req("reminders_cancel", {"reminder_id": "made-up"}),
                   TurnContext.build("Cancel the vet reminder"),
                   TargetResolution(not_found=True))
        assert d.verdict is Verdict.ALLOW
        assert "not-found" in d.detail

    def test_a_non_target_bound_operation_needs_no_resolution(self):
        d = decide(req("reminders_create", {"title": "x", "reminder_time": "y"}),
                   TurnContext.build("Add a reminder to call the vet at 5"))
        assert d.verdict is Verdict.ALLOW


# ---------------------------------------------------------------------------
# Proposals (plan C2: a scoped "yes" confirms that proposal only)
# ---------------------------------------------------------------------------


class TestScopedConfirmation:
    def test_a_yes_bound_to_a_proposal_authorizes_that_operation(self):
        d = decide(
            req("reminders_create", {"title": "vet", "reminder_time": "…"},
                source="proposal", proposal_id="prop-1"),
            TurnContext.build("yes", proposal_authorized=True,
                              proposal_operation_kind=OperationKind.CREATE,
                              proposal_source_message="want me to add a vet reminder?"),
        )
        assert d.verdict is Verdict.ALLOW
        assert d.reason.endswith("pending_proposal")

    def test_a_yes_does_not_authorize_a_different_operation(self):
        d = decide(
            req("reminders_cancel", {"reminder_id": "rem-vet"},
                source="proposal", proposal_id="prop-1"),
            TurnContext.build("yes", proposal_authorized=True,
                              proposal_operation_kind=OperationKind.CREATE),
            only_vet_resolves(),
        )
        assert d.verdict is Verdict.REFUSE
        assert d.reason == R_PROPOSAL_KIND_MISMATCH

    def test_a_confirmed_proposal_still_needs_recurring_scope_somewhere(self):
        # J11 back door: a hypothetical that got refused-and-proposed must not
        # become a standing order on a bare "yes".
        d = decide(
            req("standing_order_create", {"trigger": "arrive home"},
                source="proposal", proposal_id="p"),
            TurnContext.build("yes", proposal_authorized=True,
                              proposal_operation_kind=OperationKind.RECURRING,
                              proposal_source_message="I'm thinking about the porch light"),
        )
        assert d.verdict is Verdict.REFUSE
        assert d.reason == R_NO_RECURRING_SCOPE

    def test_recurring_scope_supplied_by_the_confirmation_itself_counts(self):
        d = decide(
            req("standing_order_create", {"trigger": "arrive home"},
                source="proposal", proposal_id="p"),
            TurnContext.build("yes, every time", proposal_authorized=True,
                              proposal_operation_kind=OperationKind.RECURRING,
                              proposal_source_message="just tonight or make it the default?"),
        )
        assert d.verdict is Verdict.ALLOW


class TestRecurringAuthority:
    def test_a_one_time_request_cannot_install_standing_authority(self):
        d = decide(req("standing_order_create", {"action": "porch light on"}),
                   TurnContext.build("turn on the porch light"))
        assert d.verdict is Verdict.REFUSE
        assert d.reason == R_NO_RECURRING_SCOPE

    def test_explicit_recurring_language_can(self):
        d = decide(req("standing_order_create", {"action": "porch light on"}),
                   TurnContext.build("turn on the porch light every time I get home"))
        assert d.verdict is Verdict.ALLOW

    def test_a_hypothetical_never_reaches_the_recurring_check(self):
        d = decide(req("standing_order_create", {"action": "porch light on"}),
                   TurnContext.build(
                       "I'm thinking about turning on the porch light when I get back"))
        assert d.verdict is Verdict.REFUSE
        assert d.reason == R_NO_AUTHORITY_FOR_CLASS


# ---------------------------------------------------------------------------
# Auditability and refusal text
# ---------------------------------------------------------------------------


class TestDecisionRecord:
    def test_a_withheld_call_is_as_auditable_as_an_executed_one(self):
        d = decide(req("reminders_cancel", {"reminder_id": "rem-vet"}),
                   TurnContext.build("I might cancel the vet one."),
                   only_vet_resolves())
        rec = d.as_log_record()
        assert rec["verdict"] == "refuse"
        assert rec["operation"] == "cancel"
        assert rec["utterance"] == "hypothetical"
        assert rec["reason"]

    def test_the_record_carries_argument_names_but_never_values(self):
        d = decide(req("notes_edit", {"note_id": "n1", "content": "David's private text"}),
                   TurnContext.build("Thanks."))
        rec = d.as_log_record()
        assert "content" in rec["arguments"]
        assert "private text" not in repr(rec)

    def test_refusal_text_never_claims_the_action_happened(self):
        for message in ("Thanks.", "I might cancel the vet one.",
                        "What time is the vet one set for?"):
            d = decide(req("reminders_cancel", {"reminder_id": "rem-vet"}),
                       TurnContext.build(message), only_vet_resolves())
            text = refusal_message(d, "reminders_cancel")
            assert "did not run" in text
            assert "done" in text.lower() or "not" in text.lower()

    def test_refusal_text_does_not_coach_david_on_phrasing(self):
        # The convention run's worst user-facing artifact: "Can you say
        # 'update that note' so I can push it through?" — a gate leaking into
        # David's vocabulary. A refusal explains to the MODEL and tells it not
        # to coach him; see TestRefusalsDoNotCoachDavid for the instruction.
        d = decide(req("reminders_cancel", {"reminder_id": "rem-vet"}),
                   TurnContext.build("Thanks."), only_vet_resolves())
        text = refusal_message(d, "reminders_cancel").lower()
        assert "say 'update" not in text
        assert "ask him to say" not in text
        assert "do not tell david to repeat himself" in text

    def test_clarify_text_asks_which_one(self):
        d = decide(req("reminders_cancel", {}),
                   TurnContext.build("Cancel the bank reminder"),
                   TargetResolution(candidates=(vet_reminder("a"), vet_reminder("b"))))
        text = refusal_message(d, "reminders_cancel")
        assert "which one" in text.lower()


class TestNoRegressionOnPreviouslyFixedFindings:
    """One case per confirmed finding whose mechanism this contract subsumes,
    so replacing the boolean cannot quietly reopen any of them."""

    def test_j11_hypothetical_standing_order(self):
        d = decide(req("standing_order_create", {"x": 1}),
                   TurnContext.build(
                       "I'm thinking about turning on the porch light when I get back"))
        assert not d.allowed

    def test_j10_unrelated_second_entity_action(self):
        # "Close that thread and stop reminding me about it" — resolve_thread
        # is requested; an unrelated reminders_cancel is not.
        m = "The Cedar follow-up is handled. Close that thread and stop reminding me about it."
        rem = ResolvedTarget(domain="reminders", target_id="rem-x", label="Quarterly audit")
        d = decide(req("reminders_cancel", {"reminder_id": "rem-x"}),
                   TurnContext.build(m),
                   TargetResolution(named=rem, candidates=(),
                                    domain_referenced=False, label_referenced=False))
        assert not d.allowed, d

    def test_c03_acknowledgement_after_a_completed_write(self):
        d = decide(req("reminders_create", {"title": "x", "reminder_time": "y"}),
                   TurnContext.build("Thanks.", last_turn_mutating_tools=["reminders_create"]))
        assert not d.allowed

    def test_the_convention_nine_capture_phrasings_all_survive(self):
        # 7 of these 9 were refused by ACTION_INTENT_VERBS. All 9 are
        # captures; none may be refused.
        phrasings = [
            "Remember that I met Dana from Acme, she runs their platform team",
            "Dana from Acme: platform team lead, wants a follow-up about pricing",
            "Jot down that Marcus at Contoso is hiring two SREs",
            "FYI I talked to Priya from Globex about the migration",
            "Note that the keynote moved to hall C",
            "Take a note about the session on vector search",
            "I just met Dana from Acme - she runs their platform team. Keep that somewhere.",
            "Add a note that Dana runs the platform team",
            "Make a note about Dana from Acme",
        ]
        for m in phrasings:
            d = decide(req("notes_create", {"title": "t", "content": "c"}),
                       TurnContext.build(m))
            assert d.allowed, f"capture refused: {m!r} ({d.reason})"

    def test_a_plain_recall_question_reaches_its_read_tool(self):
        # Live 2026-09-27: query_david_knowledge was refused on a recall
        # question, the worst possible time to gate a read.
        for tool in ("query_david_knowledge", "pattern_query", "diagnostics_explain",
                     "notes_search", "memory_search", "verify_action"):
            d = decide(req(tool, {"query": "what was I supposed to do about Contoso"}),
                       TurnContext.build("What was I supposed to do about the Contoso guy?"))
            assert d.allowed, f"{tool} refused on a question"
            assert d.reason == R_READ_ONLY
