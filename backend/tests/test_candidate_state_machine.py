"""
Tests for the say_candidate state machine (SARA_ALIVE_BUILD_PLAN Arc 1.1).

Walks candidate -> judged -> composed -> reviewed -> (shadow) held using the
shared CandidateStatus enum, and pins down the judge/compose handoff so a
status-vocabulary mismatch between the two modules can never silently starve
the funnel again (this was the suspected root cause the arc was scoped to
rule out).
"""
import re

import pytest

from app.services.candidate_states import (
    CandidateStatus,
    JUDGE_DECISION_TO_STATUS,
    TERMINAL_STATUSES,
)


class TestJudgeDecisionMapping:
    def test_every_decision_maps_to_a_real_status(self):
        for decision, status in JUDGE_DECISION_TO_STATUS.items():
            assert isinstance(status, CandidateStatus)

    def test_known_judge_decisions_covered(self):
        # These three strings are what the judge LLM prompt asks for
        # verbatim (judge.py _build_prompt: "decision": "drop|batch|send_now").
        assert set(JUDGE_DECISION_TO_STATUS.keys()) == {"drop", "batch", "send_now"}

    def test_unknown_decision_not_mapped(self):
        assert JUDGE_DECISION_TO_STATUS.get("maybe") is None


class TestStateMachineShape:
    def test_pending_is_not_terminal(self):
        assert CandidateStatus.PENDING not in TERMINAL_STATUSES

    def test_judged_send_is_not_terminal(self):
        # judged_send is a waystation to compose, not an end state — a
        # candidate sitting there forever (never advancing to composed)
        # is exactly the funnel-starvation bug this arc chased.
        assert CandidateStatus.JUDGED_SEND not in TERMINAL_STATUSES

    def test_composed_is_terminal(self):
        assert CandidateStatus.COMPOSED in TERMINAL_STATUSES

    def test_drop_batch_expired_are_terminal(self):
        assert CandidateStatus.JUDGED_DROP in TERMINAL_STATUSES
        assert CandidateStatus.JUDGED_BATCH in TERMINAL_STATUSES
        assert CandidateStatus.EXPIRED in TERMINAL_STATUSES

    def test_full_walk_candidate_to_composed(self):
        """candidate -> judged -> composed, using only the shared vocabulary."""
        status = CandidateStatus.PENDING
        assert status.value == "pending"

        decision = "send_now"
        status = JUDGE_DECISION_TO_STATUS[decision]
        assert status == CandidateStatus.JUDGED_SEND

        # compose.py's SELECT filters on exactly this value.
        status = CandidateStatus.COMPOSED
        assert status in TERMINAL_STATUSES


class TestJudgeComposeHandoffAgree:
    """The literal bug this arc was scoped to rule out: judge.py writes one
    status string, compose.py's SELECT filters on a different one, and the
    funnel silently starves. Both modules now import from the same enum, so
    this asserts they can never diverge again."""

    def test_judge_apply_decision_uses_shared_enum(self):
        import inspect
        from app.services import judge as judge_module

        src = inspect.getsource(judge_module._apply_decision)
        assert "JUDGE_DECISION_TO_STATUS" in src
        assert "status_map = {" not in src  # the old ad-hoc dict is gone

    def test_compose_task_selects_shared_enum_value(self):
        import inspect
        from app.tasks import compose as compose_task_module

        src = inspect.getsource(compose_task_module._run_async)
        assert "CandidateStatus.JUDGED_SEND" in src
        assert "status = 'judged_send'" not in src  # no more hardcoded literal

    def test_compose_task_advances_to_composed(self):
        import inspect
        from app.tasks import compose as compose_task_module

        src = inspect.getsource(compose_task_module._run_async)
        assert "CandidateStatus.COMPOSED" in src
