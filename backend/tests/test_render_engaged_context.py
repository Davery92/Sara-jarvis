"""
Tests for context_snapshot.render_engaged_context() — the Arc 2.3 staged
rollout comparison renderer (SARA_ALIVE_BUILD_PLAN, per David's 2026-07-29
review: apply the same flag+log+diff+verify mechanism used for Arc 3.4's
tool diet to the context-assembly cutover, instead of declaring it
foreclosed).

Live evidence gathered with this renderer (5 real chat turns, logged
2026-07-29): old ~19-source budget assembly averages ~12,500 chars across
9-11 active sources; the new 4-source kernel assembly averages ~1,450 chars
(6 world_state slices + 5 recall traces + an intent count) — consistently
~8x smaller, with several source categories (pkg, daily_brief, journal,
personality, patterns, device) present in old and entirely absent from new.
That's real, evidence-based grounds to hold the cutover, not risk-aversion.
"""
from datetime import datetime, timezone

from app.services.context_snapshot import render_engaged_context


def _context(world_state=None, self_state=None, relationship_state=None):
    return {
        "world_state": world_state or {},
        "self_state": self_state or {},
        "relationship_state": relationship_state or {},
    }


class TestRenderEngagedContext:
    def test_empty_context_still_renders_header(self):
        text = render_engaged_context(_context(), open_intents=0, recall_traces=[])
        assert "Current Situation" in text
        assert "open_intents" in text

    def test_world_state_slice_with_data_renders(self):
        world_state = {
            "david": {"source": "unified_context", "confidence": 1.0,
                      "data": {"activity_state": "WORKING", "current_place": "Home"}},
        }
        text = render_engaged_context(_context(world_state=world_state), open_intents=3, recall_traces=[])
        assert "david" in text
        assert "activity_state=WORKING" in text
        assert "unified_context" in text

    def test_empty_slice_data_is_skipped(self):
        world_state = {"fleet": {"source": "managed_host", "confidence": 0.0, "data": {}}}
        text = render_engaged_context(_context(world_state=world_state), open_intents=0, recall_traces=[])
        assert "fleet" not in text

    def test_self_state_concerns_render(self):
        self_state = {"kernel_state": "ambient", "open_concerns": ["consolidation stalled"]}
        text = render_engaged_context(_context(self_state=self_state), open_intents=0, recall_traces=[])
        assert "kernel_state=ambient" in text
        assert "consolidation stalled" in text

    def test_self_story_is_never_injected(self):
        """Ground-truth plan, Phase 5 §5 — reverses Arc 4.2's "included in
        every context in every state".

        `reflection/agent.py` regenerated this every four hours from a
        deliberation journal that produces ~130 "staying quiet" lines a day, and
        it drifted into "cowardice wearing a mask… I am terrified…" on a day when
        nothing had happened. Sara then read that back as established fact about
        herself on every single chat turn. The row is still written for the UI;
        it is no longer prompt input."""
        self_state = {"kernel_state": "ambient", "self_story": "I've been helping David with Risk Ninja this week."}
        text = render_engaged_context(_context(self_state=self_state), open_intents=0, recall_traces=[])
        assert "Your ongoing self-story" not in text
        assert "I've been helping David with Risk Ninja this week." not in text

    def test_no_self_story_omits_the_heading(self):
        self_state = {"kernel_state": "ambient"}
        text = render_engaged_context(_context(self_state=self_state), open_intents=0, recall_traces=[])
        assert "Your ongoing self-story" not in text

    def test_theory_of_david_renders_under_own_heading(self):
        """Arc 4.5: same 'every context in every state' treatment as
        self-story, but sourced from relationship_state."""
        relationship_state = {"theory_of_david": "David trains around 1pm and is a bit stressed this week."}
        text = render_engaged_context(_context(relationship_state=relationship_state), open_intents=0, recall_traces=[])
        assert "What you understand about David" in text
        assert "David trains around 1pm and is a bit stressed this week." in text

    def test_no_theory_of_david_omits_the_heading(self):
        relationship_state = {"active_conversation_id": "conv-1"}
        text = render_engaged_context(_context(relationship_state=relationship_state), open_intents=0, recall_traces=[])
        assert "What you understand about David" not in text

    def test_recall_traces_render_under_own_heading(self):
        traces = [{"kind": "episode", "confidence": "observed", "text": "David mentioned the Q3 report"}]
        text = render_engaged_context(_context(), open_intents=0, recall_traces=traces)
        assert "Relevant memory" in text
        assert "Q3 report" in text

    def test_recall_traces_capped_at_five(self):
        traces = [{"kind": "episode", "confidence": "observed", "text": f"item {i}"} for i in range(10)]
        text = render_engaged_context(_context(), open_intents=0, recall_traces=traces)
        assert text.count("item ") == 5


class TestExtendedSignalsRendering:
    """Arc 2.3 gap-closing (2026-07-29): the categories the comparison log
    measured present in the old assembly and missing from the new one —
    pkg/daily_brief/journal/patterns/device/emotional_tone — folded in via
    the optional `extended` param before the flag ever flips."""

    def test_no_extended_arg_is_backward_compatible(self):
        text = render_engaged_context(_context(), open_intents=0, recall_traces=[])
        assert "Current Situation" in text

    def test_empty_extended_dict_adds_nothing(self):
        text = render_engaged_context(_context(), open_intents=0, recall_traces=[], extended={})
        assert "sara_feels" not in text

    def test_none_values_in_extended_are_skipped(self):
        extended = {"pkg": None, "daily_brief": None, "journal": None,
                    "patterns": None, "device": None, "emotional_tone": None}
        text = render_engaged_context(_context(), open_intents=0, recall_traces=[], extended=extended)
        assert "sara_feels" not in text
        assert "Today's Brief" not in text

    def test_each_present_category_renders(self):
        extended = {
            "pkg": "David co-founded Risk Ninja.",
            "daily_brief": "Meeting at 2pm.",
            "journal": "Quiet morning, nothing urgent.",
            "patterns": "David trains around 1pm on weekdays (82%)",
            "device": "[Device awareness] iPhone online.",
            "emotional_tone": "attentive (0.60)",
        }
        text = render_engaged_context(_context(), open_intents=0, recall_traces=[], extended=extended)
        assert "attentive (0.60)" in text
        assert "David trains around 1pm" in text
        assert "[Device awareness] iPhone online." in text
        assert "Meeting at 2pm." in text
        assert "David co-founded Risk Ninja." in text
        assert "Quiet morning" in text

    def test_lock_and_light_cycles_are_dropped_as_noise(self):
        """Ground-truth plan, Phase 5 §8: a "patterns" line that is only the
        house behaving normally reads as insight into David and crowds out the
        patterns that are. It is omitted rather than reported."""
        extended = {"patterns": "Side door locks around midnight (100%); kitchen light cycle (99%)"}
        text = render_engaged_context(_context(), open_intents=0, recall_traces=[], extended=extended)
        assert "Side door locks" not in text
        assert "patterns" not in text

    def test_long_extended_values_are_truncated(self):
        extended = {"daily_brief": "x" * 5000, "pkg": "y" * 5000, "journal": "z" * 5000}
        text = render_engaged_context(_context(), open_intents=0, recall_traces=[], extended=extended)
        assert text.count("x") <= 1600  # 1500 cap + a little header slack
        assert text.count("y") <= 1100  # 1000 cap
        assert text.count("z") <= 1100  # 1000 cap
