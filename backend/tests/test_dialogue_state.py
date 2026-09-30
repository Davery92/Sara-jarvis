"""Deterministic dialogue-state capsule (chat harness repair Phase 4).

Reproduces the concrete failures from the 2026-09-16 morning conversation:
Sara re-asked the same shoulder question after David answered it, reasserted
a superseded set count, and could have described a completed workout as
still active.
"""
from app.services.dialogue_state import (
    Correction,
    build_dialogue_state,
    extract_questions,
    is_duplicate_or_answered_trailing_question,
    render_dialogue_state_block,
    strip_duplicate_trailing_question,
)


def _msg(role, content):
    return {"role": role, "content": content}


class TestExtractQuestions:
    def test_finds_trailing_question(self):
        assert extract_questions("Good morning! How's your shoulder feeling today?") == [
            "How's your shoulder feeling today?"
        ]

    def test_no_question_returns_empty(self):
        assert extract_questions("Glad the workout went well.") == []

    def test_multiple_sentences_only_questions_kept(self):
        text = "Nice work today. How's the shoulder holding up? Let me know."
        assert extract_questions(text) == ["How's the shoulder holding up?"]


class TestUnansweredQuestions:
    def test_question_with_no_later_reply_is_unanswered(self):
        messages = [
            _msg("user", "just finished shoulder day"),
            _msg("assistant", "Nice! How's the shoulder feeling?"),
        ]
        state = build_dialogue_state(messages)
        assert "How's the shoulder feeling?" in state.unanswered_questions

    def test_question_answered_by_later_message_is_not_unanswered(self):
        messages = [
            _msg("user", "just finished shoulder day"),
            _msg("assistant", "Nice! How's the shoulder feeling?"),
            _msg("user", "Shoulder pain has gone away, feels great"),
        ]
        state = build_dialogue_state(messages)
        assert state.unanswered_questions == []

    def test_only_looks_at_last_two_assistant_turns(self):
        messages = [
            _msg("assistant", "How's the shoulder?"),
            _msg("user", "fine I guess"),
            _msg("assistant", "Cool, what's for lunch?"),
            _msg("user", "not sure yet"),
            _msg("assistant", "Any plans tonight?"),
        ]
        state = build_dialogue_state(messages)
        # The shoulder question is 3 assistant-turns back — out of the window.
        assert "How's the shoulder?" not in state.unanswered_questions
        assert "Any plans tonight?" in state.unanswered_questions


class TestNumericCorrections:
    def test_user_restating_a_different_count_is_a_correction(self):
        messages = [
            _msg("assistant", "Got it — logged 1 set of 135x6."),
            _msg("user", "it was 4 sets of 135x6"),
        ]
        state = build_dialogue_state(messages)
        assert len(state.corrections) == 1
        c = state.corrections[0]
        assert c.supersession_key == "count_of:135x6"
        assert "4 sets of 135x6" in c.value
        assert "1 sets of 135x6" in c.old_value or "1 set of 135x6" in c.old_value

    def test_sara_restating_her_own_number_is_not_a_correction(self):
        messages = [
            _msg("assistant", "Logged 1 set of 135x6."),
            _msg("assistant", "Just to confirm, that's 1 set of 135x6."),
        ]
        state = build_dialogue_state(messages)
        assert state.corrections == []

    def test_same_count_restated_is_not_a_correction(self):
        messages = [
            _msg("assistant", "Logged 4 sets of 135x6."),
            _msg("user", "yep 4 sets of 135x6"),
        ]
        state = build_dialogue_state(messages)
        assert state.corrections == []


class TestActivitySignal:
    def test_completion_phrase_sets_completed_signal(self):
        messages = [_msg("user", "shoulder workout was good, excited for later")]
        state = build_dialogue_state(messages)
        assert state.activity_signal == "completed"

    def test_no_signal_when_nothing_indicates_completion(self):
        messages = [_msg("user", "what's on my calendar today")]
        state = build_dialogue_state(messages)
        assert state.activity_signal is None

    def test_later_restart_resets_an_earlier_completion(self):
        # The exact 2026-09-16 scenario (section 3 finding "Old activity
        # completion overrides new activity"): morning workout finishes,
        # then an evening workout starts. The prompt must not still say
        # "the workout is over" once the evening session is under way.
        messages = [
            _msg("user", "finished morning workout"),
            _msg("assistant", "Nice work!"),
            _msg("user", "started evening workout, between sets right now"),
        ]
        state = build_dialogue_state(messages)
        assert state.activity_signal is None

    def test_heading_to_the_gym_is_not_a_completion_signal(self):
        messages = [_msg("user", "heading to the gym now")]
        state = build_dialogue_state(messages)
        assert state.activity_signal is None

    def test_pain_gone_is_not_a_workout_completion_signal(self):
        # A symptom observation about David's body, not a claim that any
        # workout is over.
        messages = [_msg("user", "shoulder pain is gone today")]
        state = build_dialogue_state(messages)
        assert state.activity_signal is None

    def test_completion_after_restart_is_still_detected(self):
        messages = [
            _msg("user", "starting my workout"),
            _msg("assistant", "Have a great session!"),
            _msg("user", "just finished, that's done"),
        ]
        state = build_dialogue_state(messages)
        assert state.activity_signal == "completed"


class TestRenderBlock:
    def test_empty_state_renders_nothing(self):
        from app.services.dialogue_state import DialogueState
        assert render_dialogue_state_block(DialogueState()) == ""

    def test_full_state_renders_all_sections(self):
        from app.services.dialogue_state import DialogueState
        state = DialogueState(
            corrections=[Correction("count_of:135x6", "4 sets of 135x6", "1 set of 135x6", "it was 4 sets")],
            activity_signal="completed",
            unanswered_questions=["How's the shoulder?"],
        )
        block = render_dialogue_state_block(state)
        assert "4 sets of 135x6" in block
        assert "not describe it as in progress" in block
        assert "How's the shoulder?" in block


class TestDuplicateQuestionDetectionAndRepair:
    def test_near_duplicate_trailing_question_detected(self):
        from app.services.dialogue_state import DialogueState
        state = DialogueState(unanswered_questions=[])
        candidate = "Glad it went well! How's your shoulder feeling now?"
        recent = ["Nice work! How's your shoulder feeling?"]
        assert is_duplicate_or_answered_trailing_question(candidate, recent, state) is True

    def test_new_question_on_new_topic_is_not_flagged(self):
        from app.services.dialogue_state import DialogueState
        state = DialogueState(unanswered_questions=["What's for dinner?"])
        candidate = "Sounds good. What's for dinner?"
        recent = ["How's your shoulder feeling?"]
        assert is_duplicate_or_answered_trailing_question(candidate, recent, state) is False

    def test_strip_duplicate_trailing_question_keeps_the_rest(self):
        candidate = "Great to hear the shoulder feels good. How's your shoulder feeling now?"
        repaired = strip_duplicate_trailing_question(candidate)
        assert repaired == "Great to hear the shoulder feels good."

    def test_strip_leaves_response_unchanged_when_no_question(self):
        candidate = "Sounds like a solid session."
        assert strip_duplicate_trailing_question(candidate) == candidate

    def test_strip_does_not_produce_empty_response(self):
        candidate = "How's your shoulder feeling now?"
        # Whole response is the question — nothing safe to fall back to.
        assert strip_duplicate_trailing_question(candidate) == candidate
