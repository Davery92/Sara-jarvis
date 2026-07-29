"""
Tests for Arc 4.1's "consequence with teeth": the compose cycle must kill
an unhedged claim in a domain whose calibration confidence is below
threshold, regardless of what the LLM review verdict said. This is the
mechanical fix for the morning brief announcing a "9:30 standing meeting
today" the calendar actually had Wednesday 2:30 PM — claims carry
provenance; loops are not calendars.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.compose import _run_async


def _candidate_row(id_="cand-1", kind="prep", summary="You have a meeting today"):
    r = MagicMock()
    r.id = id_
    r.kind = kind
    r.summary = summary
    r.evidence = []
    r.judge_reason = "worth telling him"
    return r


def _make_db_ctx(select_rows):
    """One mock db whose .execute() returns fetchall()=select_rows on the
    first call (candidate SELECT) and a generic MagicMock afterward (the
    INSERT/UPDATE calls, whose return value is never inspected)."""
    mock_db = MagicMock()
    call_count = {"n": 0}

    def _execute(*a, **k):
        call_count["n"] += 1
        if call_count["n"] == 1:
            m = MagicMock()
            m.fetchall.return_value = select_rows
            return m
        return MagicMock()

    mock_db.execute = AsyncMock(side_effect=_execute)
    mock_db.commit = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, mock_db


class TestHedgingEnforcement:
    @pytest.mark.asyncio
    async def test_unhedged_low_confidence_claim_gets_killed_despite_approval(self):
        rows = [_candidate_row(summary="You have a meeting today")]
        ctx, mock_db = _make_db_ctx(rows)

        fake_calibration = {
            "days": 30, "total_resolved": 5,
            "overall_by_bucket": {}, "by_domain_bucket": {},
            "by_domain": {"calendar": {"n": 5, "hit_rate": 0.43}},
        }

        with patch("app.db.session.get_async_session_factory", return_value=lambda: ctx), \
             patch("app.services.world_brief.get_rendered_brief", new=AsyncMock(return_value="brief")), \
             patch("app.services.judge._gather_utterance_history", new=AsyncMock(return_value=[])), \
             patch("app.services.judge._gather_recent_chat", new=AsyncMock(return_value=[])), \
             patch("app.services.prediction_engine.compute_calibration",
                   new=AsyncMock(return_value=fake_calibration)), \
             patch("app.services.compose.compose_utterance", new=AsyncMock(return_value={
                 "text": "You have a 9:30 standing meeting today.",
                 "refs": [], "urgency": "normal",
             })), \
             patch("app.services.review.review_utterance", new=AsyncMock(return_value={
                 "verdict": "approve", "reason": "sounds right", "edited_text": None,
             })):
            stats = await _run_async()

        assert stats["killed"] == 1
        assert stats["approved"] == 0
        # Find the INSERT INTO composed_utterance call and check its verdict param.
        insert_calls = [
            c for c in mock_db.execute.call_args_list
            if len(c[0]) > 1 and isinstance(c[0][1], dict) and "verdict" in c[0][1]
        ]
        assert insert_calls, "expected an INSERT INTO composed_utterance call"
        assert insert_calls[0][0][1]["verdict"] == "kill"
        assert "hedging linter" in insert_calls[0][0][1]["reason"]

    @pytest.mark.asyncio
    async def test_hedged_low_confidence_claim_is_not_overridden(self):
        rows = [_candidate_row(summary="You have a meeting today")]
        ctx, mock_db = _make_db_ctx(rows)

        fake_calibration = {
            "days": 30, "total_resolved": 5,
            "overall_by_bucket": {}, "by_domain_bucket": {},
            "by_domain": {"calendar": {"n": 5, "hit_rate": 0.43}},
        }

        with patch("app.db.session.get_async_session_factory", return_value=lambda: ctx), \
             patch("app.services.world_brief.get_rendered_brief", new=AsyncMock(return_value="brief")), \
             patch("app.services.judge._gather_utterance_history", new=AsyncMock(return_value=[])), \
             patch("app.services.judge._gather_recent_chat", new=AsyncMock(return_value=[])), \
             patch("app.services.prediction_engine.compute_calibration",
                   new=AsyncMock(return_value=fake_calibration)), \
             patch("app.services.compose.compose_utterance", new=AsyncMock(return_value={
                 "text": "I think you might have a 9:30 meeting today.",
                 "refs": [], "urgency": "normal",
             })), \
             patch("app.services.review.review_utterance", new=AsyncMock(return_value={
                 "verdict": "approve", "reason": "sounds right", "edited_text": None,
             })):
            stats = await _run_async()

        assert stats["approved"] == 1
        assert stats["killed"] == 0

    @pytest.mark.asyncio
    async def test_high_confidence_domain_is_never_touched_by_hedging_check(self):
        rows = [_candidate_row(summary="You have a meeting today")]
        ctx, mock_db = _make_db_ctx(rows)

        fake_calibration = {
            "days": 30, "total_resolved": 5,
            "overall_by_bucket": {}, "by_domain_bucket": {},
            "by_domain": {"calendar": {"n": 5, "hit_rate": 0.95}},
        }

        with patch("app.db.session.get_async_session_factory", return_value=lambda: ctx), \
             patch("app.services.world_brief.get_rendered_brief", new=AsyncMock(return_value="brief")), \
             patch("app.services.judge._gather_utterance_history", new=AsyncMock(return_value=[])), \
             patch("app.services.judge._gather_recent_chat", new=AsyncMock(return_value=[])), \
             patch("app.services.prediction_engine.compute_calibration",
                   new=AsyncMock(return_value=fake_calibration)), \
             patch("app.services.compose.compose_utterance", new=AsyncMock(return_value={
                 "text": "You have a 9:30 standing meeting today.",
                 "refs": [], "urgency": "normal",
             })), \
             patch("app.services.review.review_utterance", new=AsyncMock(return_value={
                 "verdict": "approve", "reason": "sounds right", "edited_text": None,
             })):
            stats = await _run_async()

        assert stats["approved"] == 1
        assert stats["killed"] == 0

    @pytest.mark.asyncio
    async def test_calibration_fetch_failure_does_not_block_compose(self):
        """Best-effort: if compute_calibration blows up, compose still runs
        (no hedging enforcement that cycle, but nothing crashes)."""
        rows = [_candidate_row(summary="You have a meeting today")]
        ctx, mock_db = _make_db_ctx(rows)

        with patch("app.db.session.get_async_session_factory", return_value=lambda: ctx), \
             patch("app.services.world_brief.get_rendered_brief", new=AsyncMock(return_value="brief")), \
             patch("app.services.judge._gather_utterance_history", new=AsyncMock(return_value=[])), \
             patch("app.services.judge._gather_recent_chat", new=AsyncMock(return_value=[])), \
             patch("app.services.prediction_engine.compute_calibration",
                   new=AsyncMock(side_effect=RuntimeError("db exploded"))), \
             patch("app.services.compose.compose_utterance", new=AsyncMock(return_value={
                 "text": "You have a 9:30 standing meeting today.",
                 "refs": [], "urgency": "normal",
             })), \
             patch("app.services.review.review_utterance", new=AsyncMock(return_value={
                 "verdict": "approve", "reason": "sounds right", "edited_text": None,
             })):
            stats = await _run_async()

        assert stats["approved"] == 1
        assert stats["killed"] == 0
