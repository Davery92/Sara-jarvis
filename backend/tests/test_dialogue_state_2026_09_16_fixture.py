"""dialogue_state.py against the REAL 2026-09-16 morning conversation.

Reads the captured turns directly from tests/replay/fixtures/2026_09_16/
(no DATABASE_URL/replay provisioning needed — this is plain text, not a DB
replay). Proves the Phase 4 mechanism against what Sara actually said, not
just synthetic examples: the fixture shows her asking a near-identical
shoulder question five times across six replies (twice after David had
already answered it) and repeating "about two hours before that RingCentral
thing at 10" verbatim in four consecutive replies.
"""
import json
from pathlib import Path

import pytest

from app.services.dialogue_state import (
    build_dialogue_state,
    find_repeated_sentences,
    is_duplicate_or_answered_trailing_question,
    strip_duplicate_trailing_question,
)

FIXTURE_TURNS = (
    Path(__file__).resolve().parent / "replay" / "fixtures" / "2026_09_16" / "turns.json"
)

pytestmark = pytest.mark.skipif(not FIXTURE_TURNS.exists(), reason="fixture not captured")


def _load_turns():
    return json.loads(FIXTURE_TURNS.read_text())


def _messages_through(turns, upto_index, include_observed_assistant=True):
    """[{"role","content"}] for every turn up to and including `upto_index`,
    using the OBSERVED (actually-sent) assistant text — this is what the
    next turn's dialogue state is really built from."""
    msgs = []
    for t in turns[: upto_index + 1]:
        msgs.append({"role": "user", "content": t["user_text"]})
        if include_observed_assistant:
            msgs.append({"role": "assistant", "content": t["observed_assistant_text"]})
    return msgs


def test_fixture_has_seven_turns():
    turns = _load_turns()
    assert len(turns) == 7


class TestRepeatedShoulderQuestion:
    """Turns 2-5 (0-indexed) each ask a near-duplicate shoulder question;
    turn 4's own user message answers it and turn 5's user message answers
    it explicitly ('pain has gone away'), yet turns 4 and 5's OBSERVED
    replies ask it again anyway."""

    def test_turn_3_reply_duplicates_turn_2s_question(self):
        turns = _load_turns()
        # State as of just before turn 3's assistant reply: turns 0-2 done,
        # turn 3's user message already in.
        messages = _messages_through(turns, 2) + [{"role": "user", "content": turns[3]["user_text"]}]
        state = build_dialogue_state(messages)
        recent_assistant = [turns[1]["observed_assistant_text"], turns[2]["observed_assistant_text"]]

        candidate = turns[3]["observed_assistant_text"]  # what Sara actually said
        assert is_duplicate_or_answered_trailing_question(candidate, recent_assistant, state) is True

    def test_turn_6_reply_re_asks_a_question_turn_6s_own_user_message_just_answered(self):
        """The sharpest case: David's turn-6 message ('Shoulders all good
        that pain I had has gone away') answers the question in the SAME
        turn whose observed reply asks it again."""
        turns = _load_turns()
        messages = _messages_through(turns, 5) + [{"role": "user", "content": turns[6]["user_text"]}]
        state = build_dialogue_state(messages)

        # The question was answered by turns[6]'s own user message, so it
        # must not still be "unanswered" going into this turn.
        assert not any("shoulder" in q.lower() for q in state.unanswered_questions)

        recent_assistant = [turns[4]["observed_assistant_text"], turns[5]["observed_assistant_text"]]
        candidate = turns[6]["observed_assistant_text"]
        assert is_duplicate_or_answered_trailing_question(candidate, recent_assistant, state) is True

    def test_repair_keeps_the_answer_and_drops_only_the_repeated_question(self):
        turns = _load_turns()
        candidate = turns[6]["observed_assistant_text"]
        repaired = strip_duplicate_trailing_question(candidate)
        assert "pain cleared up" in repaired  # the actual answer survives
        assert not repaired.rstrip().endswith("?")


class TestRepeatedRingCentralTiming:
    """The plain-fact repetition: 'about two hours before that RingCentral
    thing at 10' verbatim in the observed replies for turns 2, 3, 4 and 5."""

    def test_the_sentence_actually_repeats_in_the_raw_transcript(self):
        """Sanity check on the fixture itself before testing the detector."""
        turns = _load_turns()
        hits = [
            t["index"] for t in turns
            if "ringcentral thing at 10" in t["observed_assistant_text"].lower()
        ]
        assert len(hits) >= 3, "fixture no longer reproduces the repeated-timing failure"

    def test_detector_flags_the_repeat(self):
        turns = _load_turns()
        recent_assistant = [turns[3]["observed_assistant_text"]]
        candidate = turns[4]["observed_assistant_text"]
        repeated = find_repeated_sentences(candidate, recent_assistant)
        assert any("ringcentral" in s.lower() for s in repeated), repeated

    def test_detector_does_not_flag_the_first_mention(self):
        turns = _load_turns()
        # Turn 3's reply is the first one to mention the two-hour window —
        # nothing before it said it that way, so it must not be flagged.
        recent_assistant = [turns[1]["observed_assistant_text"], turns[2]["observed_assistant_text"]]
        candidate = turns[3]["observed_assistant_text"]
        repeated = find_repeated_sentences(candidate, recent_assistant)
        assert not any("ringcentral" in s.lower() for s in repeated), repeated


class TestSetCountCorrection:
    """Known, documented limitation, discovered by running the real
    transcript rather than a synthetic example: David's actual correction
    ("It was 4 sets of 135x6") corrects Sara's belief about the WORKOUT LOG
    state (she'd stored one set), not an earlier CHAT-stated count — none of
    her prior replies ever said "1 set of 135x6" in that shape, only "135x6
    is in the books" / "that 135x6 working set". `_detect_corrections` only
    compares explicit "N unit of X" claims against each other, so it can't
    see this one: catching it needs the workout domain's own state, which
    this conversation-text-only module deliberately doesn't reach into.

    This is the correct, conservative behavior for what the module CAN
    see — no correction should be invented from a single unmatched mention
    — documented here so the boundary is explicit rather than silently
    assumed to work.
    """

    def test_no_prior_chat_text_states_a_conflicting_count_so_none_is_flagged(self):
        turns = _load_turns()
        messages = _messages_through(turns, 4) + [{"role": "user", "content": turns[5]["user_text"]}]
        state = build_dialogue_state(messages)
        assert state.corrections == []

    def test_synthetic_equivalent_with_an_explicit_prior_claim_is_caught(self):
        """The mechanism itself works — see test_dialogue_state.py's
        TestNumericCorrections for the fully synthetic version. Repeated
        here against the real turn text to show it's the missing PRIOR
        claim, not the detector, that's the gap."""
        turns = _load_turns()
        messages = [
            {"role": "assistant", "content": "Logged 1 set of 135x6."},
            {"role": "user", "content": turns[5]["user_text"]},  # "It was 4 sets of 135x6"
        ]
        state = build_dialogue_state(messages)
        assert any(c.supersession_key == "count_of:135x6" for c in state.corrections), state.corrections
