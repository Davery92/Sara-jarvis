"""Planning text addressed to the model, not to David.

Finding 12: "internal reasoning/scratchpad text leaked directly into a
user-facing reply", reproduced three times in the 2026-09-24 study and a fourth
time on this task's acceptance trial, where a reply about filing two notes
contained, mid-message:

    The task is done — both notes are filed. No coding task is actually pending;
    the system nudge is generic. I should just give the final result.

`strip_thinking_content` cannot catch that: no marker, no tag, no channel — it
is ordinary prose that happens to be addressed to the model itself.
"""
import pytest

from app.core.text_utils import strip_self_addressed_planning


class TestTheLeakFromTheAcceptanceTrial:
    def test_the_exact_text_is_removed(self):
        reply = (
            "Both are filed under a new People folder. "
            "The task is done — both notes are filed. "
            "No coding task is actually pending; the system nudge is generic. "
            "I should just give the final result. "
            "Marcus Iyer — Contoso: hiring two SREs."
        )
        out = strip_self_addressed_planning(reply)
        assert "the task is done" not in out.lower()
        assert "system nudge" not in out.lower()
        assert "i should just give" not in out.lower()
        assert "Both are filed under a new People folder." in out
        assert "Marcus Iyer" in out


class TestItLeavesRealRepliesAlone:
    @pytest.mark.parametrize("reply", [
        "Done — vet reminder set for 5pm.",
        "It does. Something about eating eggs when the world has stopped.",
        "I should probably tell you the vet closes at six.",
        "You should just give it another day.",
        "The task you gave me is done — the note's filed.",
        "Industrial mobilization for a single leaf.",
        "",
    ])
    def test_unchanged(self, reply):
        assert strip_self_addressed_planning(reply) == reply

    def test_a_sentence_about_david_survives_even_with_a_planning_phrase(self):
        # Second-person address means he is being spoken to, not reasoned about.
        reply = "The task is done for you, David — both notes are filed."
        assert strip_self_addressed_planning(reply) == reply


class TestItNeverEmptiesAReply:
    def test_an_all_planning_reply_is_kept_whole(self):
        """Far likelier a bad match than a reply made entirely of scratchpad —
        and an empty reply is worse than a leaked one."""
        reply = "I should just give the final result."
        assert strip_self_addressed_planning(reply) == reply

    def test_none_and_non_strings_are_safe(self):
        assert strip_self_addressed_planning(None) == ""
        assert strip_self_addressed_planning(123) == ""
