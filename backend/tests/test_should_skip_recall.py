"""Regression for SARA_CONVERSATION_COMPETENCE_PLAN_2026_09_10 Phase 2:
the old recall gate skipped memory for ANY message of 5 words or fewer,
which correctly silenced vector recall on "Good morning!" but also silenced
it on equally short messages that need memory, like "What did we decide?"
and "Same as yesterday?" (both cited in the plan's evidence).
"""

from app.services.context_snapshot import should_skip_recall


class TestShouldSkipRecall:
    def test_bare_greeting_is_skipped(self):
        assert should_skip_recall("Good morning!")
        assert should_skip_recall("Hey")
        assert should_skip_recall("Thanks!")
        assert should_skip_recall("How's it going?")

    def test_short_recall_question_is_not_skipped(self):
        assert not should_skip_recall("What did we decide?")
        assert not should_skip_recall("Same as yesterday?")
        assert not should_skip_recall("Did I log that?")

    def test_empty_message_is_skipped(self):
        assert should_skip_recall("")
        assert should_skip_recall("   ")

    def test_non_greeting_short_message_is_not_skipped(self):
        # Not a recall cue, but also not a pure greeting — should default to
        # running recall rather than assuming it's phatic.
        assert not should_skip_recall("log 3 eggs")

    def test_longer_conversational_message_is_not_skipped(self):
        assert not should_skip_recall("Ok, let's talk about the trip next week")
