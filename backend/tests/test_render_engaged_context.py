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

    def test_recall_trace_distinguishes_speaker_and_carries_id_and_when(self):
        traces = [
            {"kind": "episode", "role": "user", "confidence": "observed",
             "text": "David mentioned the Q3 report", "id": "ep-1",
             "when": "2026-09-01T10:00:00+00:00"},
            {"kind": "episode", "role": "assistant", "confidence": "observed",
             "text": "Sara offered to draft it", "id": "ep-2"},
            {"kind": "fact", "confidence": "confirmed", "text": "David prefers dark roast", "id": "f-1"},
        ]
        text = render_engaged_context(_context(), open_intents=0, recall_traces=traces)
        assert "David said" in text
        assert "Sara suggested" in text
        assert "a tool confirmed" in text
        assert "id=ep-1" in text
        assert "id=f-1" in text


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
        extended = {"pkg": None, "daily_brief_layers": None, "journal": None,
                    "patterns": None, "device": None, "emotional_tone": None}
        text = render_engaged_context(_context(), open_intents=0, recall_traces=[], extended=extended)
        assert "sara_feels" not in text
        assert "Right now / today / this week" not in text
        assert "Who David is (stable)" not in text

    def test_each_present_category_renders(self):
        extended = {
            "pkg": "David co-founded Risk Ninja.",
            "daily_brief_layers": {"moment": "Meeting at 2pm.", "stable": "David has a kitten named Vesper."},
            "journal": "Quiet morning, nothing urgent.",
            "patterns": "David trains around 1pm on weekdays (82%)",
            "device": "[Device awareness] iPhone online.",
            "emotional_tone": "attentive (0.60)",
        }
        # `intent="PATTERNS"`: harness rebuild Phase 6 gates the patterns line
        # on the turn actually being about patterns (see
        # TestPatternsAreIntentGated below) — in ordinary conversation it was
        # five lines of the house behaving normally.
        text = render_engaged_context(
            _context(), open_intents=0, recall_traces=[], extended=extended,
            intent="PATTERNS",
        )
        assert "attentive (0.60)" in text
        assert "David trains around 1pm" in text
        assert "[Device awareness] iPhone online." in text
        assert "Meeting at 2pm." in text
        assert "David co-founded Risk Ninja." in text
        assert "Quiet morning" in text
        assert "David has a kitten named Vesper." in text
        # Volatile (moment/day/context) must render before stable — the bug
        # this guards against clipped stable-first, eating the trip context.
        assert text.index("Meeting at 2pm.") < text.index("kitten named Vesper")

    def test_lock_and_light_cycles_are_dropped_as_noise(self):
        """Ground-truth plan, Phase 5 §8: a "patterns" line that is only the
        house behaving normally reads as insight into David and crowds out the
        patterns that are. It is omitted rather than reported."""
        extended = {"patterns": "Side door locks around midnight (100%); kitchen light cycle (99%)"}
        text = render_engaged_context(
            _context(), open_intents=0, recall_traces=[], extended=extended,
            intent="PATTERNS",
        )
        assert "Side door locks" not in text
        assert "patterns" not in text

    def test_long_extended_values_are_truncated(self):
        extended = {
            "daily_brief_layers": {"context": "x" * 5000, "stable": "w" * 5000},
            "pkg": "y" * 5000, "journal": "z" * 5000,
        }
        text = render_engaged_context(_context(), open_intents=0, recall_traces=[], extended=extended)
        assert text.count("x") <= 1900  # 1800-char volatile cap + a little slack
        assert text.count("w") <= 1000  # 900-char stable cap + slack
        assert text.count("y") <= 1100  # 1000 cap
        assert text.count("z") <= 1100  # 1000 cap


# ═══════════════════════════════════════════════════════════════════════════
# Harness rebuild Phase 6 — the live-context diet
#
# Measured on 2026-09-11: the assembled volatile block was 19,200 chars, more
# than three times the persona prompt, with the same header twice, a calendar
# rendered twice, two contradicting internal-state lines, three empty headers,
# a keyword bag restating the message being answered, and a memory section
# whose top hit was that same message from one minute earlier.
# ═══════════════════════════════════════════════════════════════════════════

_CAL_SLICE = {
    "calendar_horizon": {
        "source": "calendar_event+world_thread", "confidence": 1.0,
        "data": {
            "active_calendar_events": 1,
            "open_threads": 95,
            "upcoming": [
                "Fri Sep 11 (all day): Pay Day",
                "Wed Sep 16, 5:00 PM ET (in 5d): Meet the Instruments [Everett's]",
            ],
            "later": ["Sun Sep 27 (all day)–Thu Oct 1 (all day): David Applied Net"],
        },
    }
}


class TestCalendarRendersOnce:
    def test_the_verified_upcoming_list_is_gone(self):
        """world_brief's ## AHEAD renders the same events with the same
        ownership tags. Two calendars in one prompt is two chances to
        disagree, and twice the tokens."""
        text = render_engaged_context(
            _context(world_state=_CAL_SLICE), open_intents=0, recall_traces=[]
        )
        assert "Calendar — verified upcoming" not in text
        assert "Meet the Instruments" not in text

    def test_events_beyond_a_week_survive_as_one_line(self):
        """AHEAD's window is 7 days, so `later` is the one part of the old
        block nothing else covered."""
        text = render_engaged_context(
            _context(world_state=_CAL_SLICE), open_intents=0, recall_traces=[]
        )
        assert "David Applied Net" in text
        assert "Further out" in text


class TestOpenThreadCountIsGone:
    def test_the_raw_count_is_not_rendered(self):
        """It said 95 in the same prompt whose OPEN LOOPS listed eight."""
        text = render_engaged_context(
            _context(world_state=_CAL_SLICE), open_intents=0, recall_traces=[]
        )
        assert "open_threads" not in text
        assert "95" not in text

    def test_the_rest_of_the_slice_still_renders(self):
        text = render_engaged_context(
            _context(world_state=_CAL_SLICE), open_intents=0, recall_traces=[]
        )
        assert "active_calendar_events=1" in text


class TestPatternsAreIntentGated:
    EXT = {"patterns": "David trains around 1pm on weekdays (82%)"}

    def test_absent_from_an_ordinary_conversation(self):
        for intent in (None, "CONVERSATIONAL", "GENERAL", "NOTES"):
            text = render_engaged_context(
                _context(), open_intents=0, recall_traces=[], extended=self.EXT,
                intent=intent,
            )
            assert "David trains around 1pm" not in text, intent

    def test_present_when_david_asked_about_patterns(self):
        text = render_engaged_context(
            _context(), open_intents=0, recall_traces=[], extended=self.EXT,
            intent="PATTERNS",
        )
        assert "David trains around 1pm" in text


class TestNoEmptyHeaders:
    def test_a_whitespace_only_journal_renders_no_header(self):
        text = render_engaged_context(
            _context(), open_intents=0, recall_traces=[],
            extended={"journal": "   \n  \n"},
        )
        assert "Recent Journal" not in text

    def test_a_whitespace_only_pkg_renders_no_header(self):
        text = render_engaged_context(
            _context(), open_intents=0, recall_traces=[], extended={"pkg": "  \n "},
        )
        assert "Knowledge Graph" not in text
        assert "What Sara Knows About David" not in text


class TestKnowsAboutDavidHeaderAppearsOnce:
    def test_the_pkg_block_is_not_double_wrapped(self):
        """recall_facts_prose already opens with its own header; the old
        `## Knowledge Graph` wrapper made two headers for one list, the outer
        one looking empty."""
        pkg = ("\n\n## What Sara Knows About David (relevant to this conversation)\n"
               "- David co-founded Risk Ninja (confirmed)\n")
        text = render_engaged_context(
            _context(), open_intents=0, recall_traces=[], extended={"pkg": pkg},
        )
        assert text.count("What Sara Knows About David") == 1
        assert "## Knowledge Graph" not in text
        assert "Risk Ninja" in text


class TestStaleTodayIsRestated:
    def test_yesterdays_today_becomes_an_as_of_date(self):
        from datetime import date
        from app.services.context_snapshot import _restate_stale_today

        out = _restate_stale_today(
            "These are active tasks for today (Sept 10), distinct from older items.",
            today=date(2026, 9, 11),
        )
        assert "today (Sept 10)" not in out
        assert "as of Thu Sep 10" in out

    def test_an_actual_today_is_left_alone(self):
        from datetime import date
        from app.services.context_snapshot import _restate_stale_today

        text = "These are active tasks for today (Sept 11)."
        assert _restate_stale_today(text, today=date(2026, 9, 11)) == text

    def test_text_without_a_date_anchor_is_untouched(self):
        from datetime import date
        from app.services.context_snapshot import _restate_stale_today

        text = "David is working on the memory system today."
        assert _restate_stale_today(text, today=date(2026, 9, 11)) == text


class TestHealthHonesty:
    def _slice(self, **data):
        return {"health_today": {"source": "health_metric", "confidence": 0.75,
                                 "data": data}}

    def test_a_stale_sleep_row_is_keyed_as_unavailable(self):
        """The slice said `sleep_hours=7.13 (measured Thu Sep 10, 6:00 AM ET)`
        and Sara opened the morning with "you slept 7.1 hours". The date was
        right there and read straight past; the KEY now says so."""
        text = render_engaged_context(
            _context(world_state=self._slice(
                sleep_last_night=("unavailable (no row yet); most recent sleep: "
                                  "7.13 (measured Thu Sep 10, 6:00 AM ET)"),
            )),
            open_intents=0, recall_traces=[],
        )
        assert "sleep_last_night=unavailable (no row yet)" in text
        assert "most recent sleep: 7.13" in text

    def test_a_stale_counter_is_labelled_yesterdays(self):
        text = render_engaged_context(
            _context(world_state=self._slice(
                exercise_minutes="yesterday's 1 (measured Thu Sep 10, 11:27 AM ET)",
            )),
            open_intents=0, recall_traces=[],
        )
        assert "yesterday's 1" in text


class TestBudget:
    def test_a_full_realistic_render_fits_the_budget(self):
        """The 4,500-char budget from the rebuild plan, against a fixture
        shaped like the 2026-09-11 snapshot."""
        world_state = dict(_CAL_SLICE)
        world_state["david"] = {
            "source": "unified_context", "confidence": 1.0,
            "data": {"activity_state": "engaged", "interruptibility": 1.0,
                     "current_place": "Home"},
        }
        world_state["health_today"] = {
            "source": "health_metric", "confidence": 0.75,
            "data": {"weight": "240 (measured Fri Sep 11, 7:00 AM ET)",
                     "resting_hr": "64 (measured Fri Sep 11, 7:00 AM ET)",
                     "hrv": "unavailable (nothing recorded in the last 36h)"},
        }
        extended = {
            "emotional_tone": "proud (0.42)",
            "pkg": ("\n\n## What Sara Knows About David\n"
                    + "\n".join(f"- fact number {i} about David" for i in range(8))),
            "daily_brief_layers": {
                "moment": "I'm in conversation with David this morning.",
                "day": "x" * 1200,
                "stable": "y" * 800,
            },
            "journal": "z" * 600,
            "patterns": "Side Door Lock locks around 00:00 (100%)",
            "device": "[Device awareness] iPhone online.",
        }
        traces = [
            {"kind": "episode", "id": f"ep-{i}", "text": "a" * 140,
             "confidence": "observed", "when": None, "role": "user"}
            for i in range(5)
        ]
        text = render_engaged_context(
            _context(world_state=world_state,
                     relationship_state={"theory_of_david": "w" * 900}),
            open_intents=7, recall_traces=traces, extended=extended,
            intent="CONVERSATIONAL",
        )
        assert len(text) <= 4500, f"{len(text)} chars:\n{text[:1500]}"
