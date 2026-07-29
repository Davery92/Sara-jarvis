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

    def test_recall_traces_render_under_own_heading(self):
        traces = [{"kind": "episode", "confidence": "observed", "text": "David mentioned the Q3 report"}]
        text = render_engaged_context(_context(), open_intents=0, recall_traces=traces)
        assert "Relevant memory" in text
        assert "Q3 report" in text

    def test_recall_traces_capped_at_five(self):
        traces = [{"kind": "episode", "confidence": "observed", "text": f"item {i}"} for i in range(10)]
        text = render_engaged_context(_context(), open_intents=0, recall_traces=traces)
        assert text.count("item ") == 5
