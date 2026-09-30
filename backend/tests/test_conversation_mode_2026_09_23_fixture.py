"""classify_conversation_mode() against the REAL 2026-09-22/23 conversations
docs/plans/SARA_PERSONAL_CONVERSATION_REMEDIATION_PLAN_2026_09_23.md's
evidence table was written from.

Reads the captured turns directly from tests/replay/fixtures/2026_09_23/
(no DATABASE_URL/replay provisioning needed — this is plain text, not a DB
replay; see test_dialogue_state_2026_09_16_fixture.py for the same
pattern). Locks in a real bug found only by replaying David's actual
message text: "Just relaxing lol I’m tired" carries a curly apostrophe
(iOS autocorrect), which a straight-quote keyword list silently missed —
see TestCurlyApostrophe in test_context_router.py for the unit-level fix.

For the full end-to-end proof (the real fixture replayed through the actual
context-assembly pipeline and, with SARA_REPLAY_MODEL=1, the actual
configured local model), see tests/replay/ — this file is the fast,
infra-free layer that runs everywhere.
"""
import json
from pathlib import Path

import pytest

from app.services.context_router import (
    AMBIENT_SUPPRESS_MODES,
    classify_conversation_mode,
)

FIXTURE_TURNS = (
    Path(__file__).resolve().parent / "replay" / "fixtures" / "2026_09_23" / "turns.json"
)

pytestmark = pytest.mark.skipif(not FIXTURE_TURNS.exists(), reason="fixture not captured")


def _load_turns():
    return json.loads(FIXTURE_TURNS.read_text())


def test_fixture_has_the_three_evidence_table_turns():
    turns = _load_turns()
    assert len(turns) == 3


class TestEachRealTurnClassifiesIntoAnAmbientSuppressMode:
    """All three of the plan's evidence-table turns are casual/vulnerable
    conversation with no explicit request — every one of them should have
    had the ambient world-brief/health/work material withheld."""

    def test_good_evening(self):
        turns = _load_turns()
        mode = classify_conversation_mode(turns[0]["user_text"])
        assert turns[0]["user_text"] == "Good evening"
        assert mode == "social"
        assert mode in AMBIENT_SUPPRESS_MODES

    def test_just_relaxing_lol_im_tired(self):
        """The exact turn whose OBSERVED reply opened with 'Tired + HRV 32
        this morning' — and whose text carries a curly apostrophe that a
        straight-quote-only keyword list would silently miss."""
        turns = _load_turns()
        assert "’" in turns[1]["user_text"], "fixture no longer carries the curly apostrophe"
        mode = classify_conversation_mode(turns[1]["user_text"])
        assert mode == "personal_vulnerable"
        assert mode in AMBIENT_SUPPRESS_MODES

    def test_the_er_visit_turn(self):
        """The exact turn whose OBSERVED reply proposed email/SSL/ACORD
        work and said 'you're up at 7' with no basis for the claim."""
        turns = _load_turns()
        mode = classify_conversation_mode(turns[2]["user_text"])
        assert "er last night" in turns[2]["user_text"]
        assert mode == "personal_vulnerable"
        assert mode in AMBIENT_SUPPRESS_MODES


class TestObservedFailuresAreDocumented:
    """Not assertions about the fix (that lives in test_context_router.py /
    test_render_engaged_context.py / test_world_state_chat_facts.py, and
    end-to-end in tests/replay/) — just pins the fixture's observed text so
    a future re-capture can't silently drop the evidence these tests exist
    to guard."""

    def test_turn_0_observed_reply_recapped_the_day(self):
        turns = _load_turns()
        assert "workout's in the books" in turns[0]["observed_assistant_text"]

    def test_turn_1_observed_reply_surfaced_an_hrv_number(self):
        turns = _load_turns()
        assert "HRV 32" in turns[1]["observed_assistant_text"]

    def test_turn_2_observed_reply_proposed_work_and_a_wake_time(self):
        turns = _load_turns()
        observed = turns[2]["observed_assistant_text"]
        assert "SSL cert" in observed and "ACORD" in observed
        assert "up at 7" in observed
