"""Structured, authority-ordered allocation for the final local-provider
live-context clip (living-world-context plan §3 Finding #1).

Before this, the final clip was one call to enforce_live_context_budget()
on the whole assembled volatile string. Engaged context (~4,400 chars) sits
first in that string and already nearly fills the 4,500-char budget on its
own, so anything appended after it — the World Brief, in particular — was
silently, almost always dropped entirely. A reproduction confirmed the
exact failure: "the whole brief gone, no warning."
"""
from app.services.context_budget import (
    LIVE_CONTEXT_SECTION_ALLOTMENTS,
    allocate_live_context_sections,
)


class TestWorldBriefSurvivesAllocation:
    def test_a_large_rest_section_no_longer_zeroes_out_the_brief(self):
        """The exact Finding #1 reproduction: engaged context (folded into
        `rest`, as it is in production) alone is big enough to have
        consumed the entire old 4,500-char budget. The brief must still
        get its guaranteed share."""
        huge_engaged_context = "y" * 6000
        world_brief = "## What's true in David's world right now\nDavid is mid-workout, started 12 minutes ago."

        rendered, raw = allocate_live_context_sections(
            world_brief=world_brief, rest=huge_engaged_context, max_chars=4500,
        )

        assert "mid-workout" in rendered
        assert raw > 4500  # the old bug: individually-budgeted pieces, sum uncapped
        assert len(rendered) <= 4500 + 50  # small slack for join newlines/headers

    def test_world_state_core_also_survives_a_large_rest_section(self):
        huge_rest = "z" * 6000
        core = "Workout in progress: Upper Body A (started 8 minutes ago)."

        rendered, _ = allocate_live_context_sections(
            world_state_core=core, rest=huge_rest, max_chars=4500,
        )
        assert "Workout in progress" in rendered

    def test_empty_sections_render_nothing_for_that_slot(self):
        rendered, raw = allocate_live_context_sections(max_chars=4500)
        assert rendered == ""
        assert raw == 0

    def test_everything_fits_when_small(self):
        rendered, raw = allocate_live_context_sections(
            dialogue_state="correction: 4 sets not 1",
            world_state_core="Workout in progress: leg day.",
            world_brief="Calendar: 3pm dentist.",
            rest="engaged context here",
            max_chars=4500,
        )
        for expected in ("correction:", "Workout in progress", "Calendar:", "engaged context"):
            assert expected in rendered
        # raw is the sum of section lengths before the "\n\n" join separators;
        # nothing was cut, so it must be smaller than the rendered text by
        # exactly the separator overhead, never larger.
        assert raw < len(rendered)

    def test_join_overhead_never_pushes_the_result_over_budget(self):
        """Allotments sum to exactly max_chars/4 tokens (see the next test) —
        if all four sections independently max out their allotment, the
        "\\n\\n" join separators between them sit outside that per-section
        accounting and could push the total a few chars over. The caller's
        hard assert on LIVE_CONTEXT_CHAR_BUDGET must never fire."""
        rendered, _ = allocate_live_context_sections(
            dialogue_state="d " * 200,
            world_state_core="w " * 400,
            world_brief="b " * 600,
            rest="r " * 3000,
            max_chars=4500,
        )
        assert len(rendered) <= 4500

    def test_allotments_sum_to_the_default_char_budget(self):
        # Keeps LIVE_CONTEXT_SECTION_ALLOTMENTS honest against
        # LIVE_CONTEXT_CHAR_BUDGET (4,500 chars / 4 chars-per-token = 1,125
        # tokens) — a silent mismatch here would either waste budget or
        # quietly reintroduce an uncapped remainder.
        assert sum(LIVE_CONTEXT_SECTION_ALLOTMENTS.values()) == 1125

    def test_dialogue_state_and_core_both_survive_together(self):
        """Neither guaranteed section may starve the other — both are
        "current state" the model must not contradict."""
        rendered, _ = allocate_live_context_sections(
            dialogue_state="Corrections David has made this conversation:\n- 4 sets not 1",
            world_state_core="Workout in progress: Upper Body A.",
            rest="x" * 6000,
            max_chars=4500,
        )
        assert "Corrections David has made" in rendered
        assert "Workout in progress" in rendered
