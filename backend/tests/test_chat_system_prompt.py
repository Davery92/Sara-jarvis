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


class TestNoVolatileContent:
    def test_the_clock_is_not_in_the_stable_prefix(self):
        # The datetime line is its own system message so MTPLX's prompt cache
        # keeps the persona + tool-schema prefix across turns.
        p = build()
        assert "Current Date & Time" not in p

    def test_two_builds_with_the_same_tools_are_identical(self):
        assert build() == build()
