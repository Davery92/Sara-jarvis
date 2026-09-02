"""Ground-truth Phase 6: Sara and David see the same task world.

On 2026-09-01 David asked for a background report at 17:05. At 17:15 he asked "is
it running?" and Sara said the plan did not exist — `get_background_tasks` read
`background_task` and was blind to `research_plan`. He asked three more times, got
three more plans, and all four ran to completion. The result landed at 21:28, was
batched to the 08:00–12:00 morning window, and he leaves for work at 07:00.
"""
from __future__ import annotations

import pathlib

import pytest

from app.tools.research_plan import COMPLETED_PLAN_REUSE_HOURS, normalize_plan_title


class TestSingleFlight:
    @pytest.mark.parametrize("a,b", [
        ("Salem MA Historical Guide", "salem ma historical guide"),
        ("Salem MA Historical Guide!", "Salem MA  Historical   Guide"),
        ("Research: Salem, MA", "research salem ma"),
    ])
    def test_the_same_question_normalizes_the_same_way(self, a, b):
        assert normalize_plan_title(a) == normalize_plan_title(b)

    def test_different_questions_stay_different(self):
        assert normalize_plan_title("Salem history") != normalize_plan_title("Boston history")

    def test_an_empty_title_matches_nothing(self):
        assert normalize_plan_title("") == ""
        assert normalize_plan_title("!!!") == ""

    def test_a_finished_plan_is_reused_for_the_rest_of_the_day(self):
        assert COMPLETED_PLAN_REUSE_HOURS >= 12

    def test_the_tool_tells_sara_what_to_say(self):
        from app.tools.research_plan import CreateResearchPlanTool

        assert "already running as" in CreateResearchPlanTool().description


class TestOneTaskWorld:
    def test_the_wiring_check_catches_a_divergence(self):
        from app.tasks.system_wiring_check import _check_one_task_world

        assert _check_one_task_world() == []

    def test_the_tool_reads_the_shared_activity_function(self):
        source = pathlib.Path("app/tools/agents.py").read_text()
        assert "get_agent_activity" in source


class TestDavidChatResultsNeverBatch:
    def _candidate(self, **kw):
        base = {"id": "c1", "source": "research_executor", "kind": "inform", "evidence": []}
        base.update(kw)
        return base

    def test_a_requested_result_is_recognised(self):
        from app.services.judge import _is_david_chat_result

        cands = [self._candidate(evidence=[{"plan_id": "p1", "origin": "david_chat"}])]
        assert _is_david_chat_result(cands, "c1")

    def test_an_alert_from_a_result_source_counts(self):
        from app.services.judge import _is_david_chat_result

        assert _is_david_chat_result([self._candidate(kind="alert")], "c1")

    def test_saras_own_background_research_may_still_batch(self):
        from app.services.judge import _is_david_chat_result

        cands = [self._candidate(evidence=[{"plan_id": "p1", "origin": "sara_internal"}])]
        assert not _is_david_chat_result(cands, "c1")

    def test_an_unrelated_candidate_is_untouched(self):
        from app.services.judge import _is_david_chat_result

        assert not _is_david_chat_result([self._candidate(source="appraisal")], "c1")

    def test_the_override_is_wired_into_the_decision_loop(self):
        source = pathlib.Path("app/services/judge.py").read_text()
        assert 'if decision == "batch" and _is_david_chat_result' in source


class TestOneResultNotePerPlanPerDay:
    def test_a_second_run_appends_instead_of_duplicating(self):
        source = pathlib.Path("app/services/research/executor.py").read_text()
        assert "## Run " in source
        assert "SET content = content || :addition" in source

    def test_result_notes_are_tagged_as_saras_own(self):
        source = pathlib.Path("app/services/research/executor.py").read_text()
        assert "SARA_GENERATED_TAG" in source
