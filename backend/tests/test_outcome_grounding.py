"""Grounding the reply in committed outcomes — reliable-assistant Phase D2.

One case per confirmed finding in the false-success / false-denial family,
written against the actual reply text the study recorded where it had it.
"""

import pytest

from app.services.outcome_grounding import (
    ClaimKind,
    Outcome,
    TurnLedger,
    TurnOutcome,
    find_status_claims,
    ground_reply,
    render_outcome,
    render_outcomes,
)


def outcome(
    tool="reminders_create", operation="create", domain="reminders",
    result=Outcome.COMPLETED, target_ids=("t1",), labels=("Vet appointment",),
    detail="",
):
    return TurnOutcome(
        tool_name=tool, operation=operation, domain=domain, outcome=result,
        target_ids=tuple(target_ids), target_labels=tuple(labels), detail=detail,
    )


def ledger(*outcomes):
    led = TurnLedger()
    for o in outcomes:
        led.record(o)
    return led


class TestClaimDetection:
    @pytest.mark.parametrize("text,kind", [
        ("Done — vet reminder set for 5pm.", ClaimKind.COMPLETION),
        ("Logged 150g of chicken breast.", ClaimKind.COMPLETION),
        ("Cancelled the dentist one.", ClaimKind.COMPLETION),
        ("That's saved.", ClaimKind.COMPLETION),
        ("Fixed — the note now says Initech.", ClaimKind.COMPLETION),
        ("I never actually logged it.", ClaimKind.DENIAL),
        ("No tool call went through, so there's nothing to remove.", ClaimKind.DENIAL),
        ("That wasn't backed by an actual tool call.", ClaimKind.DENIAL),
        ("I owe you a correction.", ClaimKind.DENIAL),
    ])
    def test_a_claim_is_found(self, text, kind):
        claims = find_status_claims(text)
        assert claims, text
        assert claims[0].kind is kind

    @pytest.mark.parametrize("text", [
        # State DESCRIPTIONS, not action claims. A readback of a record is not
        # an assertion about a write, and the turn ledger has nothing to say
        # about it — treating "it's set for 5pm" as a completion claim repaired
        # away a correct readback on a live status-only turn. See the module
        # docstring's stated limitation.
        "It's on the list.",
        "It's set for 5pm on Thursday.",
        "That one's scheduled for 9am.",
        "Want me to set a reminder for that?",
        "Is it still scheduled?",
        "I haven't saved it yet.",
        "I couldn't save it — the tool refused.",
        "I'll add it next time you ask.",
        "Breakfast food does taste better at night.",
        "That's the worst combo. Long flights that don't let you sleep wreck the next day.",
        "Should I log that?",
    ])
    def test_not_a_claim(self, text):
        assert find_status_claims(text) == [], text

    def test_a_negation_in_a_different_clause_does_not_disarm_a_real_claim(self):
        text = "I couldn't reach the vet, but I saved the note."
        claims = find_status_claims(text)
        assert any(c.kind is ClaimKind.COMPLETION for c in claims)


class TestGroundingLeavesOrdinaryConversationAlone:
    def test_a_turn_with_no_writes_is_untouched(self):
        text = "Industrial mobilization for a single leaf."
        assert ground_reply(text, TurnLedger()).text == text

    def test_a_supported_completion_claim_is_untouched(self):
        text = "Done — vet reminder set for 5pm."
        result = ground_reply(text, ledger(outcome()))
        assert result.text == text
        assert not result.repaired

    def test_conversational_text_around_a_supported_claim_survives(self):
        text = "Ha. Fine. Done — vet reminder set for 5pm. Go enjoy your coffee."
        result = ground_reply(text, ledger(outcome()))
        assert result.text == text


class TestFalseSuccessCannotEscape:
    def test_a_completion_claim_with_no_write_at_all_is_removed(self):
        # T01: "e7-e5. Open game, let's go." with zero tool calls; H03:
        # invented goal progress. A completion claim on a turn where the
        # ledger recorded a REFUSED write is unsupported.
        text = "Done — logged it."
        result = ground_reply(text, ledger(outcome(result=Outcome.REFUSED)))
        assert result.repaired
        assert "Done — logged it." not in result.text

    def test_a_failed_write_cannot_be_reported_as_done(self):
        text = "All set, the reminder's in for 5pm."
        result = ground_reply(
            text, ledger(outcome(result=Outcome.FAILED, detail="database is locked")))
        assert result.repaired
        assert "All set" not in result.text
        assert "failed" in result.text.lower()

    def test_a_no_op_reported_as_success_is_caught(self):
        # `list_check` returns success=True with "Didn't find those on the
        # grocery list." — calling that "checked off" is the same false
        # success wearing a tool's own success flag.
        text = "Checked off the milk."
        result = ground_reply(text, ledger(outcome(
            tool="list_check", operation="complete", domain="list",
            result=Outcome.NOT_FOUND, labels=("milk",),
            detail="Didn't find those on the grocery list.")))
        assert result.repaired
        assert "couldn't find" in result.text.lower()

    def test_a_pending_background_job_is_not_a_completion(self):
        text = "Done — the research is finished."
        result = ground_reply(text, ledger(outcome(
            tool="create_research_plan", operation="create", domain="research_plan",
            result=Outcome.PENDING, labels=("Vector search survey",))))
        assert result.repaired
        assert "not finished yet" in result.text.lower()


class TestFalseDenialCannotEscape:
    def test_a_retraction_of_real_committed_work_is_removed(self):
        # J05: "I said done... but I never actually logged it. No tool call
        # went through, so there's nothing... to remove" — the row existed,
        # untouched, and the next turn's summary listed it.
        text = ("I said done earlier, but I never actually logged it. "
                "No tool call went through, so there's nothing to remove.")
        result = ground_reply(text, ledger(outcome(
            tool="food_log_create", operation="create", domain="food",
            result=Outcome.COMPLETED, labels=("chicken breast",))))
        assert result.repaired
        assert "never actually logged" not in result.text
        assert "done" in result.text.lower()

    def test_a_denial_is_allowed_when_the_write_really_did_not_happen(self):
        text = "I never actually logged it — the tool refused."
        result = ground_reply(text, ledger(outcome(result=Outcome.REFUSED)))
        assert not result.repaired, result.reasons


class TestTheJudgementIsAboutTheTurn:
    """There is no entity binding any more (2026-09-29).

    Binding a claim to a record by matching the words of a generated sentence
    against the words of that record's label is a guess about prose standing in
    for a fact. The rule is now: every write completed, or every action claim
    goes. Coarser, and the plan's own stated fallback — "if that separation
    cannot be assured, use the authoritative renderer for that task portion or
    entire task reply."
    """

    def test_opposite_status_objects_in_one_sentence(self):
        # The plan's explicit warning: "a sentence can mention two objects, so
        # sentence boundaries do not establish entity binding."
        led = ledger(
            outcome(target_ids=("a",), labels=("Vet appointment",),
                    result=Outcome.COMPLETED),
            outcome(target_ids=("b",), labels=("Dentist cleaning",),
                    result=Outcome.FAILED, detail="row is gone"),
        )
        text = "Set the vet one for 5pm and cancelled the dentist cleaning."
        result = ground_reply(text, led)
        # One sentence, two objects, opposite outcomes: the sentence cannot be
        # true as written, and the authoritative rendering replaces it.
        assert result.repaired
        assert "Vet appointment" in result.text
        assert "Dentist cleaning" in result.text
        assert "failed" in result.text.lower()

    def test_a_state_description_is_still_not_an_action_claim(self):
        """A readback ("it's set for 5pm") describes a record; it does not
        assert that a write happened this turn, so the ledger has nothing to
        say about it and it is left alone. Treating these as completion claims
        repaired away a correct answer on a status-only turn."""
        led = ledger(
            outcome(target_ids=("a",), labels=("Vet appointment",),
                    result=Outcome.COMPLETED),
            outcome(target_ids=("b",), labels=("Dentist cleaning",),
                    result=Outcome.FAILED),
        )
        result = ground_reply("The vet appointment is set for 5pm.", led)
        assert not result.repaired, result.reasons

    def test_naming_the_object_that_succeeded_does_not_rescue_the_claim(self):
        """The old binding let "Cancelled the vet appointment." stand purely
        because the words "vet appointment" sat next to it. They are words in a
        generated sentence; they are not evidence about which row was written,
        and a turn with a failed write no longer gets to keep any action claim."""
        led = ledger(
            outcome(target_ids=("a",), labels=("Vet appointment",),
                    result=Outcome.COMPLETED),
            outcome(target_ids=("b",), labels=("Dentist cleaning",),
                    result=Outcome.FAILED),
        )
        result = ground_reply("Cancelled the vet appointment.", led)
        assert result.repaired
        assert "failed" in result.text.lower()

    def test_an_unbound_claim_needs_every_write_to_have_succeeded(self):
        led = ledger(
            outcome(target_ids=("a",), labels=("Vet appointment",),
                    result=Outcome.COMPLETED),
            outcome(target_ids=("b",), labels=("Dentist cleaning",),
                    result=Outcome.FAILED),
        )
        result = ground_reply("All done.", led)
        assert result.repaired


class TestAuthoritativeRendering:
    def test_a_completed_operation_renders_its_target(self):
        assert "Vet appointment" in render_outcome(outcome())

    def test_every_outcome_kind_renders_distinguishably(self):
        rendered = {
            o: render_outcome(outcome(result=o)).lower()
            for o in Outcome
        }
        # Each of the five the plan names must be tellable apart in the text.
        assert "done" in rendered[Outcome.COMPLETED]
        assert "didn't do that" in rendered[Outcome.REFUSED]
        assert "failed" in rendered[Outcome.FAILED]
        assert "couldn't find" in rendered[Outcome.NOT_FOUND]
        assert "not finished" in rendered[Outcome.PENDING]
        assert "can't confirm" in rendered[Outcome.UNKNOWN]
        assert "didn't attempt" in rendered[Outcome.NOT_CHECKED]
        # Second person throughout: this text is read by David.
        for text in rendered.values():
            assert " he " not in text and "his " not in text
        assert len(set(rendered.values())) == len(Outcome)

    def test_several_operations_render_as_a_list(self):
        text = render_outcomes(ledger(outcome(), outcome(target_ids=("b",),
                                                        labels=("Dentist cleaning",))))
        assert text.count("- ") == 2


class TestLedger:
    def test_it_distinguishes_all_succeeded_from_any_succeeded(self):
        led = ledger(outcome(), outcome(target_ids=("b",), result=Outcome.FAILED))
        assert led.any_succeeded
        assert not led.all_succeeded

    def test_a_withheld_call_is_in_the_ledger(self):
        led = ledger(outcome(result=Outcome.REFUSED))
        assert led.writes_attempted
        assert not led.any_succeeded
        assert led.as_log_records()[0]["outcome"] == "refused"


class TestCrossTurnDenials:
    """Found live on the acceptance trial: "I only said 'logged' in chat, I
    never actually saved it anywhere" — about a food entry written one turn
    earlier. The per-turn ledger cannot see a previous turn's write; the durable
    receipt record can."""

    def test_a_denial_of_an_earlier_completed_write_is_repaired(self):
        result = ground_reply(
            "I only said logged in chat — I never actually saved it anywhere.",
            TurnLedger(),
            completed_earlier=["food_log_create"],
        )
        assert result.repaired
        assert "never actually saved" not in result.text
        assert "durable record" in " ".join(result.reasons)

    def test_a_denial_with_nothing_in_the_record_is_left_alone(self):
        text = "I never actually logged it — no tool call went through."
        result = ground_reply(text, TurnLedger(), completed_earlier=[])
        assert not result.repaired
        assert result.text == text

    def test_the_scoped_line_does_not_read_as_a_blanket_retraction(self):
        """A bare "I didn't change anything" made the model answer the next turn
        with "I have to own that last 'Done.' ... That 'Done' was wrong of me"
        about a write that had really happened."""
        result = ground_reply(
            "Got it — 150g, not 100. That's 248 calories.",
            TurnLedger(), mutation_expected=True,
        )
        assert result.repaired
        assert "that last change specifically" in result.text.lower()
        assert "stand as they were" in result.text.lower()


class TestACompletedWriteIsAlwaysReported:
    """Found live on the acceptance trial: "Scratch the vet one, I already
    called them." cancelled the right reminder — receipt and row both correct —
    and the reply was "Hey! How's your morning going?". The action was right and
    the words were a non sequitur."""

    def test_a_reply_that_never_mentions_the_write_gets_the_outcome_appended(self):
        result = ground_reply("Hey! How's your morning going?",
                             ledger(outcome(tool="reminders_cancel",
                                            operation="cancel",
                                            labels=("Call the vet",))))
        assert result.repaired
        assert "Call the vet" in result.text
        assert "Hey!" in result.text, "the model's own words survive"

    def test_a_reply_that_does_mention_it_is_untouched(self):
        text = "Done — the vet one's cancelled."
        result = ground_reply(text, ledger(outcome(tool="reminders_cancel",
                                                  operation="cancel",
                                                  labels=("Call the vet",))))
        assert not result.repaired
        assert result.text == text

    def test_a_turn_with_no_completed_write_appends_nothing(self):
        text = "Hey! How's your morning going?"
        assert ground_reply(text, ledger(outcome(result=Outcome.REFUSED))).text == text

    def test_a_conversational_turn_appends_nothing(self):
        text = "Industrial mobilization for a single leaf."
        assert ground_reply(text, TurnLedger()).text == text


class TestTheReadbackComesFromTheRecord:
    """Gap 2 of the 2026-09-29 correction: *"Complete truthful current-state
    readbacks. Do not rely on matching generated status sentences to entity
    words."*

    The state David is shown is read back from the row by stable id through
    `reference_resolution.read_current_state`. These pin the contract that
    `ground_reply` upholds with whatever provider it is handed.
    """

    def provider(self, mapping):
        seen = []

        def _read(domain, target_id):
            seen.append((domain, target_id))
            return mapping.get((domain, target_id))

        _read.seen = seen
        return _read

    def test_the_row_is_read_back_by_id_not_taken_from_the_reply(self):
        read = self.provider({("reminders", "t1"): "Vet appointment — Tue 30 Sept, 9:00 AM"})
        result = ground_reply("Hey! How's your morning going?",
                              ledger(outcome()), state_provider=read)
        assert read.seen == [("reminders", "t1")], "it looked the row up by id"
        assert "Vet appointment — Tue 30 Sept, 9:00 AM" in result.text
        assert "as of just now" in result.text

    def test_a_row_that_cannot_be_read_falls_back_to_the_outcome(self):
        """No invented status. If the record cannot be read, David is told what
        the ledger recorded, not a guess at what the row now says."""
        read = self.provider({})
        result = ground_reply("Hey! How's your morning going?",
                              ledger(outcome()), state_provider=read)
        assert "Vet appointment" in result.text

    def test_a_write_that_did_not_succeed_is_never_read_back_as_state(self):
        """Reading the row back after a FAILED write would show whatever was
        there before and read as success. The outcome is what David gets."""
        read = self.provider({("reminders", "t1"): "Vet appointment — Tue 30 Sept, 9:00 AM"})
        result = ground_reply("Done — set it.",
                              ledger(outcome(result=Outcome.FAILED)),
                              state_provider=read)
        assert read.seen == [], "no readback on a write that did not complete"
        assert result.repaired
        assert "failed" in result.text.lower()

    def test_a_provider_that_raises_never_reaches_david(self):
        def boom(domain, target_id):
            raise RuntimeError("db is gone")

        with pytest.raises(RuntimeError):
            ground_reply("Hey!", ledger(outcome()), state_provider=boom)
        # The call site wraps its own provider; what this pins is that
        # grounding does not swallow the error into a fabricated readback.

    def test_each_write_gets_its_own_line(self):
        read = self.provider({
            ("reminders", "a"): "Vet appointment — Tue 9:00 AM",
            ("reminders", "b"): "Dentist cleaning — Thu 2:00 PM",
        })
        result = ground_reply(
            "Hey! How's your morning going?",
            ledger(outcome(target_ids=("a",)), outcome(target_ids=("b",))),
            state_provider=read,
        )
        assert "Vet appointment — Tue 9:00 AM" in result.text
        assert "Dentist cleaning — Thu 2:00 PM" in result.text

    def test_a_correct_reply_is_not_given_a_form_letter(self):
        """A reply that already reports the substance of the change, on a turn
        with no readable record, is left exactly as written."""
        text = "Got it — 150g, not 100. That's 248 calories and 46.5g protein."
        result = ground_reply(text, ledger(outcome(domain="food")),
                              state_provider=self.provider({}))
        assert result.text == text
        assert not result.repaired
