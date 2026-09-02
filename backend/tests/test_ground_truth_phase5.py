"""Ground-truth Phase 5: the chat context agrees with itself.

At 06:02 on 2026-09-02 Sara assembled 28,985 characters of context for one turn.
In it: three different departure times, a habit of "taking lunch at 2 AM", a pet
that was a dog in one place and a kitten in another, "eight live items requiring
attention" against a real three, "open_threads=0" printed above eight open
threads, a journal line reading "09:38 AM David is asleep" written at 05:38, six
fleet hosts reported unreachable that had never been enrolled, ten consecutive
outside-temperature lines as "what happened while you were away", four of five
memory hits that were notes Sara had written herself the night before, a 14,000
character JSON blob cut mid-word, and a self-story that said "cowardice wearing a
mask… I am terrified…" on a day nothing had happened.
"""
from __future__ import annotations

import pathlib
import re

import pytest

MAIN = pathlib.Path("app/main_simple.py")
SNAPSHOT = pathlib.Path("app/services/context_snapshot.py")
WORLD_CONTEXT = pathlib.Path("app/services/world_state/context.py")


class TestNoJsonDump:
    def test_format_context_for_prompt_is_gone(self):
        assert "def format_context_for_prompt" not in WORLD_CONTEXT.read_text()

    def test_nothing_imports_it_any_more(self):
        for path in (MAIN, pathlib.Path("app/services/deliberation.py")):
            source = path.read_text()
            assert "import build_context_bundle, format_context_for_prompt" not in source
            assert "format_context_for_prompt(" not in source

    def test_chat_injects_the_rendered_brief_instead(self):
        source = MAIN.read_text()
        assert "get_rendered_brief" in source


class TestOneStateOneFact:
    def test_the_second_user_state_store_is_no_longer_written(self):
        source = pathlib.Path("app/tasks/working_memory.py").read_text()
        assert 'user_state_key = f"working_memory:{solo_user_id}:user_state"' not in source
        assert 'system_state_key' not in source

    def test_working_memory_reads_through_to_the_one_snapshot(self):
        source = pathlib.Path("app/services/cognitive/working_memory.py").read_text()
        assert "from app.services.unified_context import read_snapshot" in source

    def test_a_chat_turn_states_what_david_is_doing(self):
        """Nothing is more certain than the message in front of her."""
        source = pathlib.Path("app/services/chat_turn_notify.py").read_text()
        assert 'activity_state="engaged"' in source
        assert "app_active=1" in source

    def test_an_ambiguous_device_does_not_invent_a_place(self):
        from app.services.chat_turn_notify import _place_for_device

        assert _place_for_device("desktop") == "Office"
        assert _place_for_device("ios") is None
        assert _place_for_device("unknown") is None

    def test_the_thread_count_reads_the_table_with_closers(self):
        source = SNAPSHOT.read_text()
        assert "FROM followup_thread WHERE user_id = :uid AND status = 'open'" not in source
        assert "FROM world_thread" in source


class TestDeadSlicesDropped:
    def test_a_fleet_of_never_reported_hosts_is_not_reported(self):
        from app.services.context_snapshot import _slice_is_dead

        assert _slice_is_dead("fleet", {"host_count": 6, "never_reported": list("abcdef")})
        assert _slice_is_dead("fleet", {"host_count": 0, "never_reported": []})
        assert not _slice_is_dead("fleet", {"host_count": 6, "never_reported": ["a"]})

    def test_lock_and_light_cycles_are_not_insight(self):
        from app.services.context_snapshot import _patterns_are_noise

        assert _patterns_are_noise("kitchen light cycle 100%; front door lock cycle 99%")
        assert _patterns_are_noise("")
        assert not _patterns_are_noise("David trains at 1pm 85%")

    def test_weather_refresh_is_not_news(self):
        from app.services.context_writer import is_meaningful_change

        assert not is_meaningful_change("[06:12] Outside temperature: 61°F")
        assert not is_meaningful_change("[06:14] Weather: cloudy")
        assert is_meaningful_change("[07:02] David left home")
        assert is_meaningful_change("[08:00] Next up: Risk Ninja call")


class TestSelfStoryIsNotPromptInput:
    def test_the_renderer_no_longer_injects_it(self):
        source = SNAPSHOT.read_text()
        assert "### Your ongoing self-story" not in source

    def test_it_folds_once_nightly_not_every_four_hours(self):
        source = pathlib.Path("app/services/reflection/agent.py").read_text()
        assert "_is_nightly_window()" in source
        assert source.count("if _is_nightly_window():") == 2

    def test_deliberation_journal_lines_are_excluded_from_it(self):
        # The follow-up plan moved this from an inline literal to a named set,
        # which also excludes the machine's own audit rows (truth_maintenance,
        # self_audit) — see test_ground_truth_followup.py.
        from app.services.sara_journal_service import SELF_STORY_EXCLUDED_TYPES

        assert "deliberation" in SELF_STORY_EXCLUDED_TYPES
        source = pathlib.Path("app/services/sara_journal_service.py").read_text()
        assert "e.entry_type not in SELF_STORY_EXCLUDED_TYPES" in source

    def test_both_documents_are_capped_short(self):
        source = pathlib.Path("app/services/sara_journal_service.py").read_text()
        assert "AT MOST 80 WORDS" in source
        assert "AT MOST 120 WORDS" in source


class TestTruncationEndsAtABoundary:
    def test_nothing_is_cut_mid_word(self):
        from app.services.context_snapshot import _clip_to_paragraph

        clipped = _clip_to_paragraph("One sentence here. Two sentence here. Three.", 25)
        assert clipped == "One sentence here."
        assert not clipped.endswith("sente")

    def test_short_text_is_untouched(self):
        from app.services.context_snapshot import _clip_to_paragraph

        assert _clip_to_paragraph("Short.", 100) == "Short."


class TestBudget:
    def test_the_volatile_block_has_a_hard_cap_with_named_shares(self):
        from app.services.context_budget import SECTION_ALLOTMENTS, VOLATILE_BLOCK_MAX_TOKENS

        assert VOLATILE_BLOCK_MAX_TOKENS == 6000
        assert sum(SECTION_ALLOTMENTS.values()) <= VOLATILE_BLOCK_MAX_TOKENS
        for section in ("brief", "calendar", "memory", "unacked", "lessons", "device", "reentry"):
            assert section in SECTION_ALLOTMENTS

    def test_a_section_cannot_exceed_its_share(self):
        from app.services.context_budget import SectionBudget, estimate_tokens

        budget = SectionBudget()
        budget.add("calendar", "x " * 5000)   # allotment is 400 tokens
        budget.add("memory", "y " * 5000)     # allotment is 600 tokens
        rendered = budget.render()
        assert estimate_tokens(rendered) <= 1100

    def test_the_whole_block_stays_under_the_cap(self):
        from app.services.context_budget import SectionBudget, estimate_tokens

        budget = SectionBudget()
        for name in ("brief", "calendar", "memory", "unacked", "lessons"):
            budget.add(name, "word " * 20000)
        assert estimate_tokens(budget.render()) <= 6000

    def test_sections_are_split_by_their_headers(self):
        from app.services.context_snapshot import _split_sections

        names = [n for n, _ in _split_sections([
            "## Current Situation", "- david",
            "### Calendar — verified upcoming", "  - Tue Sep 2: thing",
            "### Relevant memory (memory.recall)", "- [note] hi",
        ])]
        assert names == ["brief", "calendar", "memory"]


class TestOneFactPerPredicate:
    def test_a_weak_rhythm_is_not_an_answer(self):
        """The 6:24 departure came from 8 samples at 0.48 confidence."""
        from app.services.life_facts import RHYTHM_MIN_CONFIDENCE, RHYTHM_MIN_SAMPLES

        assert RHYTHM_MIN_CONFIDENCE >= 0.5
        assert RHYTHM_MIN_SAMPLES >= 10

    @pytest.mark.asyncio
    async def test_an_unknown_predicate_resolves_to_nothing(self):
        from app.services.life_facts import resolve_predicate

        assert await resolve_predicate("u1", "not_a_predicate") is None


class TestRecallExcludesSarasOwnOutput:
    def test_duplicate_titles_collapse_to_one_hit(self):
        from app.services.memory_recall import _dedupe_by_title

        traces = [
            {"kind": "note", "id": "1", "text": "Salem MA Historical Guide - Completed", "score": 1.0},
            {"kind": "note", "id": "2", "text": "Salem MA Historical Guide - Completed", "score": 0.9},
            {"kind": "note", "id": "3", "text": "Salem MA Historical Guide — Completed", "score": 0.8},
            {"kind": "episode", "id": "4", "text": "David asked about Salem", "score": 0.7},
        ]
        kept = _dedupe_by_title(traces)
        assert len(kept) == 2

    def test_asking_about_a_report_still_finds_it(self):
        from app.services.memory_recall import _asked_about_agent_output

        assert _asked_about_agent_output("what did the research find?")
        assert _asked_about_agent_output("did that background task finish")
        assert not _asked_about_agent_output("when is my next meeting")


class TestUnackedBlock:
    def test_the_window_is_six_hours_not_twenty_four(self):
        from app.services.notification_ack import UNACKED_WINDOW_HOURS

        assert UNACKED_WINDOW_HOURS == 6

    def test_it_carries_titles_and_rendered_times_only(self):
        source = pathlib.Path("app/services/notification_ack.py").read_text()
        block = source.split("async def get_unacked_for_context")[1].split("async def ")[0]
        assert "render_when" in block
        assert 'strftime("%a %H:%M")' not in block
        # The full stale body was being replayed on every turn.
        assert "n.get('message')" not in block and 'n.get("message")' not in block

    def test_resolved_entities_are_excluded(self):
        source = pathlib.Path("app/services/notification_ack.py").read_text()
        assert "world_thread" in source
        assert "'resolved','cancelled','expired'" in source
