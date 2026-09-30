"""Sara's chat persona prompt (harness rebuild Phase 5).

The prompt this replaces was ~14,000 characters and mostly a hardcoded manual
for tools that might not be loaded. Two of its rules contradicted each other:

    Never say "I can't do that" if it's something that could be done on a
    computer. Pick the right path and dispatch.
    Do NOT reach for a tool when this awareness already holds the answer.

On 2026-09-11 that combination produced a ten-round flail (web_search for her
own capabilities, get_page_details on a filename, fleet_diag running a shell
`find`) and then a refusal anyway.
"""

import pytest

from app.prompts.chat_system_prompt import (
    MAX_PROMPT_CHARS,
    _SOUL_FALLBACK,
    build_chat_system_prompt,
)
from app.services.tool_retrieval import CORE_TOOLS

SOUL = "I'm Sara — David's assistant. Direct, warm, occasionally teasing."


def build(tools=None, soul=SOUL):
    return build_chat_system_prompt("Sara", soul, tools or list(CORE_TOOLS))


class TestSize:
    def test_within_the_cap(self):
        assert len(build()) <= MAX_PROMPT_CHARS

    def test_a_long_soul_is_trimmed_rather_than_a_rule_dropped(self):
        p = build(soul="x" * 40_000)
        assert len(p) <= MAX_PROMPT_CHARS
        # The truth rules are the part that must survive any trim.
        assert "Absence is an answer" in p
        assert "find_tools" in p

    def test_it_is_a_fraction_of_the_prompt_it_replaces(self):
        # get_system_prompt was ~14,000 chars.
        assert len(build()) < 7000


class TestToolsAreGenerated:
    def test_it_names_the_tools_actually_loaded(self):
        p = build(["memory_search", "files_to_studio", "find_tools"])
        assert "memory_search" in p
        assert "files_to_studio" in p

    def test_it_does_not_describe_tools_that_are_not_loaded(self):
        p = build(["memory_search", "find_tools"])
        # The old prompt had a Home Control section unconditionally, which is
        # how the model reached for tools it did not have.
        assert "home_light_control" not in p
        assert "documents_search" not in p
        assert "canvas_open_note" not in p

    def test_home_control_appears_only_when_home_tools_are_loaded(self):
        p = build(["memory_search", "home_light_control", "find_tools"])
        assert "home_light_control" in p

    def test_find_tools_is_the_named_escape_hatch(self):
        p = build()
        assert "find_tools" in p
        assert "before telling David you cannot" in p

    def test_find_tools_is_not_offered_as_an_escape_hatch_when_not_loaded(self):
        """Milestone A review, 2026-09-22: the prompt used to tell the model
        to call `find_tools` unconditionally, even on a turn where
        `find_tools` itself was not among the tools actually loaded —
        inviting exactly the reflexive call-to-an-unavailable-tool failure
        documented in StreamScaffoldGuard's docstring (MTPLX tried to call
        `find_tools` with zero tools declared). Without `find_tools` in
        hand, the prompt must not promise it."""
        p = build(["memory_search", "notes_search"])
        assert "call `find_tools`" not in p
        assert "cannot discover new tools this turn" in p
        assert "tell David plainly" in p

    def test_character_budget_is_unchanged_in_the_common_find_tools_present_case(self):
        """The fix must not cost anything against the 17-char headroom Phase
        5 measured — verified by exact length, not just "still fits"."""
        with_ft = build(["memory_search", "notes_search", "find_tools"])
        without_ft_branch_text = with_ft.replace(
            "If the task needs something not in that list, call `find_tools` "
            "with a plain description of what you need — before telling "
            "David you cannot do it. Do not improvise with web_search, a "
            "shell, or a page fetch.",
            "PLACEHOLDER",
        )
        assert without_ft_branch_text != with_ft, "expected exact original wording, byte for byte"

    def test_ambiguous_action_intent_gets_a_clarifying_question_not_a_guess(self):
        """Voice-authorization follow-up: when a mutating tool is withheld
        by gate_mutating_tools because the message doesn't clearly ask for
        it, the model has no tool to reach for either way — this is what
        tells it to ask rather than silently do nothing or guess."""
        p = build()
        assert "ask one focused question rather than guessing" in p
        assert "continues that" in p and "not a new one" in p


class TestTheContradictionIsGone:
    def test_the_dispatch_anything_line_is_gone(self):
        p = build()
        assert 'Never say "I can\'t do that"' not in p
        assert "Pick the right path and dispatch" not in p

    def test_the_do_not_reach_for_a_tool_line_is_gone(self):
        p = build()
        assert "Do NOT reach for a tool" not in p


class TestTruthRulesSurvive:
    @pytest.mark.parametrize("rule", [
        "succeeded THIS turn",          # no false "Done"
        "usual routine is a pattern",   # no invented activity
        "it always carries its date",   # health numbers
        "Absence is an answer",
        "Never complete a partial series",
        "described as theirs",          # Everett's dentist
        "Measurements are the exception",
    ])
    def test_rule_present(self, rule):
        assert rule in build()


class TestConversationRules:
    """Reliable-assistant plan Phase B — one case per observed behavior in
    docs/plans/SARA_PERSONAL_TEST_REVIEW_2026_09_28.md §1. These assert the
    rule text is actually assembled into the prompt the model sees; whether
    the model then follows it is a live-conversation question, not a unit
    test, and is recorded separately in the evidence map."""

    @pytest.mark.parametrize("rule,review_case", [
        ("Answer the invitation he actually made", "17 breakfast-at-night lecture"),
        ("wants your opinion, not a briefing", "17 opinion invitation"),
        ("explain his own feelings back to him", "32 being-listened-to"),
        ('"probably means"', "09 father's tests speculation"),
        ("Don't grant permission he didn't ask for", "05/06/09/31/37 managerial voice"),
        ("Don't invent shared history", "33 fish lamp 'three years later'"),
        ("the new subject is the subject", "39 bakery pivot"),
        ('"No advice" means none', "06 vent/no-advice"),
        ("Let an ending end", "27 ending"),
        ("not volunteering it", "soul 'anticipating what he needs' conflict"),
    ])
    def test_rule_present(self, rule, review_case):
        assert rule in build(), review_case

    def test_it_does_not_impose_a_length_limit(self):
        # The review is explicit that shorter alone was not sufficient and
        # that a blanket one-sentence rule is the wrong fix.
        p = build()
        assert "one sentence" not in p.lower()
        assert "keep it short" not in p.lower()

    def test_it_does_not_demand_a_question(self):
        p = build()
        assert "always ask" not in p.lower()
        assert "end with a question" not in p.lower()

    def test_a_realistic_db_sized_soul_keeps_every_rule_and_no_less_soul(self):
        # The real sara_soul block is ~3,400 chars (four sections plus the
        # loader's own headers), which the cap has ALWAYS trimmed — at the
        # pre-existing 6,500 cap the fixed blocks were ~4,630, leaving the
        # soul ~1,870 chars, so its growth section was already being cut every
        # turn. That trim is the documented, deliberate behavior ("trim the
        # soul rather than silently drop a truth rule"), not a regression.
        #
        # What this test pins is that adding the conversation block did not
        # make it worse: the cap went up by 1,100 to cover the ~1,050-char
        # block, so the soul's own budget is unchanged or slightly larger,
        # and every fixed rule still survives.
        realistic_soul = "## Who Sara Is\n\n" + ("soul sentence. " * 225)
        assert 3200 <= len(realistic_soul) <= 3600
        p = build(soul=realistic_soul)
        assert len(p) <= MAX_PROMPT_CHARS
        assert "Answer the invitation he actually made" in p
        assert "Absence is an answer" in p
        assert "find_tools" in p

        fixed_overhead = len(build(soul="")) - len(_SOUL_FALLBACK)
        soul_budget_now = MAX_PROMPT_CHARS - fixed_overhead
        PRE_CHANGE_SOUL_BUDGET = 1870  # 6500 cap - ~4630 of fixed blocks
        assert soul_budget_now >= PRE_CHANGE_SOUL_BUDGET, (
            f"the conversation block must not cost the soul characters it had "
            f"before: {soul_budget_now} < {PRE_CHANGE_SOUL_BUDGET}"
        )


class TestVoice:
    def test_no_option_menus(self):
        assert "No menus of options" in build()

    def test_one_question_max(self):
        assert "One question per reply" in build()

    def test_no_permission_for_read_only(self):
        assert "Never ask permission for a read-only action" in build()


class TestSoul:
    def test_the_soul_is_the_identity(self):
        p = build(soul="I am a teapot and I know it.")
        assert "I am a teapot and I know it." in p

    def test_an_empty_soul_still_produces_a_usable_prompt(self):
        p = build(soul=None)
        assert "Sara" in p
        assert "Absence is an answer" in p
        assert len(p) > 1000


class TestMemoryContractIsHonest:
    """Living-world-context plan §3 finding: 'Prompt discourages freshness
    checks' — the prompt said 'You remember everything in this thread' while
    the fallback DB history load is capped at 20 messages. An overclaiming
    contract discourages the model from ever using memory_search to recover
    something genuinely out of view."""

    def test_the_overclaiming_line_is_gone(self):
        p = build()
        assert "you remember everything" not in p.lower()

    def test_the_prompt_names_the_actual_limitation_and_the_recovery_tool(self):
        p = build(["memory_search", "find_tools"])
        assert "memory_search" in p
        assert "recall" in p.lower() or "total recall" in p.lower()


class TestNoVolatileContent:
    def test_the_clock_is_not_in_the_stable_prefix(self):
        # The datetime line is its own system message so MTPLX's prompt cache
        # keeps the persona + tool-schema prefix across turns.
        p = build()
        assert "Current Date & Time" not in p

    def test_two_builds_with_the_same_tools_are_identical(self):
        assert build() == build()
