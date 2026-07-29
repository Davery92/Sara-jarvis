"""
Tests for Arc 4.4: "one affect, computed, consequential" — emotional_state
driven by appraisals (David's day trajectory, her own failure/success
stream, prediction quality), not a free-form LLM mood word alone, and
modulating exactly three things: composer tone, attention pricing, and
initiative margin.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.emotional_state import compute_appraisal


def _db_ctx(execute_results):
    """A db whose successive .execute() calls return the given results in
    order (matching compute_appraisal's 3 sequential queries — calibration
    is via compute_calibration, the other two are raw db.execute calls)."""
    mock_db = MagicMock()
    mock_db.execute = AsyncMock(side_effect=execute_results)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


class TestComputeAppraisal:
    @pytest.mark.asyncio
    async def test_no_signals_returns_none(self):
        empty_cal = {"days": 7, "total_resolved": 0, "overall_by_bucket": {}, "by_domain_bucket": {}, "by_domain": {}}
        judge_result = MagicMock()
        judge_result.first.return_value = None
        health_result = MagicMock()
        health_result.fetchall.return_value = []

        ctx = _db_ctx([judge_result, health_result])
        with patch("app.db.session.get_async_session_factory", return_value=lambda: ctx), \
             patch("app.services.prediction_engine.compute_calibration", new=AsyncMock(return_value=empty_cal)):
            result = await compute_appraisal("user-1")

        assert result is None

    @pytest.mark.asyncio
    async def test_worst_domain_below_threshold_triggers_reflective(self):
        cal = {"days": 7, "total_resolved": 20, "overall_by_bucket": {}, "by_domain_bucket": {},
               "by_domain": {"home": {"n": 10, "hit_rate": 0.2}, "security": {"n": 8, "hit_rate": 0.9}}}
        judge_result = MagicMock()
        judge_result.first.return_value = None
        health_result = MagicMock()
        health_result.fetchall.return_value = []

        ctx = _db_ctx([judge_result, health_result])
        with patch("app.db.session.get_async_session_factory", return_value=lambda: ctx), \
             patch("app.services.prediction_engine.compute_calibration", new=AsyncMock(return_value=cal)):
            result = await compute_appraisal("user-1")

        assert result is not None
        tone, intensity, about = result
        assert tone == "reflective"
        assert "home" in about

    @pytest.mark.asyncio
    async def test_low_sample_domain_does_not_trigger(self):
        """A domain with < 5 resolved predictions is noise, not signal —
        must not trigger reflective even at a terrible hit rate."""
        cal = {"days": 7, "total_resolved": 3, "overall_by_bucket": {}, "by_domain_bucket": {},
               "by_domain": {"routine": {"n": 2, "hit_rate": 0.0}}}
        judge_result = MagicMock()
        judge_result.first.return_value = None
        health_result = MagicMock()
        health_result.fetchall.return_value = []

        ctx = _db_ctx([judge_result, health_result])
        with patch("app.db.session.get_async_session_factory", return_value=lambda: ctx), \
             patch("app.services.prediction_engine.compute_calibration", new=AsyncMock(return_value=cal)):
            result = await compute_appraisal("user-1")

        assert result is None

    @pytest.mark.asyncio
    async def test_high_judge_kill_rate_triggers_reflective(self):
        empty_cal = {"days": 7, "total_resolved": 0, "overall_by_bucket": {}, "by_domain_bucket": {}, "by_domain": {}}
        judge_result = MagicMock()
        judge_result.first.return_value = MagicMock(dropped=9, total=10)
        health_result = MagicMock()
        health_result.fetchall.return_value = []

        ctx = _db_ctx([judge_result, health_result])
        with patch("app.db.session.get_async_session_factory", return_value=lambda: ctx), \
             patch("app.services.prediction_engine.compute_calibration", new=AsyncMock(return_value=empty_cal)):
            result = await compute_appraisal("user-1")

        assert result is not None
        assert result[0] == "reflective"

    @pytest.mark.asyncio
    async def test_low_sleep_triggers_concerned(self):
        empty_cal = {"days": 7, "total_resolved": 0, "overall_by_bucket": {}, "by_domain_bucket": {}, "by_domain": {}}
        judge_result = MagicMock()
        judge_result.first.return_value = None
        health_row = MagicMock(metric_type="sleep_hours", value=4.2)
        health_result = MagicMock()
        health_result.fetchall.return_value = [health_row]

        ctx = _db_ctx([judge_result, health_result])
        with patch("app.db.session.get_async_session_factory", return_value=lambda: ctx), \
             patch("app.services.prediction_engine.compute_calibration", new=AsyncMock(return_value=empty_cal)):
            result = await compute_appraisal("user-1")

        assert result is not None
        assert result[0] == "concerned"
        assert "recovery" in result[2]

    @pytest.mark.asyncio
    async def test_concerned_about_david_outweighs_her_own_reflective_signal(self):
        """Weight ordering: David's day trajectory (1.2) beats her own
        judge-outcome stream (0.6) when both fire the same cycle."""
        empty_cal = {"days": 7, "total_resolved": 0, "overall_by_bucket": {}, "by_domain_bucket": {}, "by_domain": {}}
        judge_result = MagicMock()
        judge_result.first.return_value = MagicMock(dropped=9, total=10)
        health_row = MagicMock(metric_type="hrv_morning", value=20.0)
        health_result = MagicMock()
        health_result.fetchall.return_value = [health_row]

        ctx = _db_ctx([judge_result, health_result])
        with patch("app.db.session.get_async_session_factory", return_value=lambda: ctx), \
             patch("app.services.prediction_engine.compute_calibration", new=AsyncMock(return_value=empty_cal)):
            result = await compute_appraisal("user-1")

        assert result[0] == "concerned"

    @pytest.mark.asyncio
    async def test_calibration_failure_does_not_block_other_signals(self):
        judge_result = MagicMock()
        judge_result.first.return_value = None
        health_row = MagicMock(metric_type="sleep_hours", value=4.0)
        health_result = MagicMock()
        health_result.fetchall.return_value = [health_row]

        ctx = _db_ctx([judge_result, health_result])
        with patch("app.db.session.get_async_session_factory", return_value=lambda: ctx), \
             patch("app.services.prediction_engine.compute_calibration",
                   new=AsyncMock(side_effect=RuntimeError("db exploded"))):
            result = await compute_appraisal("user-1")

        assert result is not None
        assert result[0] == "concerned"


class TestComposerToneModulation:
    @pytest.mark.asyncio
    async def test_affect_block_included_when_not_baseline(self):
        from app.services.compose import _build_prompt
        _, user_msg = _build_prompt(
            candidate={"kind": "prep", "summary": "test", "evidence": [], "judge_reason": ""},
            brief_text="brief", voice_doc="voice",
            affect=("concerned", 0.6, "David's recovery numbers looked rough"),
        )
        assert "feeling concerned" in user_msg
        assert "David's recovery numbers looked rough" in user_msg

    def test_no_affect_block_at_baseline(self):
        from app.services.compose import _build_prompt
        _, user_msg = _build_prompt(
            candidate={"kind": "prep", "summary": "test", "evidence": [], "judge_reason": ""},
            brief_text="brief", voice_doc="voice",
            affect=("attentive", 0.3, ""),
        )
        assert "current mood" not in user_msg

    def test_no_affect_block_when_none(self):
        from app.services.compose import _build_prompt
        _, user_msg = _build_prompt(
            candidate={"kind": "prep", "summary": "test", "evidence": [], "judge_reason": ""},
            brief_text="brief", voice_doc="voice", affect=None,
        )
        assert "current mood" not in user_msg


class TestAttentionPricing:
    @pytest.mark.asyncio
    async def test_concerned_affect_raises_the_bar_in_judge_context(self):
        from app.services.judge import _gather_context

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=0)))
        fake_snap = MagicMock(sara_emotional_tone="concerned", sara_emotional_intensity=0.6,
                               sara_emotional_about="David's recovery numbers looked rough")

        with patch("app.services.activity_state_machine.activity_state_machine") as mock_asm, \
             patch("app.services.interruptibility.compute_interruptibility") as mock_interrupt, \
             patch("app.services.delivery_policy.sense_sleep_state", new=AsyncMock(return_value=MagicMock(asleep=False))), \
             patch("app.services.judge._gather_recent_chat", new=AsyncMock(return_value=[])), \
             patch("app.services.working_memory.read_memory", new=AsyncMock(return_value=fake_snap)):
            mock_asm.current = MagicMock()
            mock_interrupt.return_value = MagicMock(score=0.7)
            ctx = await _gather_context(mock_db, "user-1")

        assert ctx.get("affect_concerned_about_david") == "David's recovery numbers looked rough"

    @pytest.mark.asyncio
    async def test_reflective_affect_does_not_raise_the_bar(self):
        """Her own self-critical mood isn't about David — must not leak
        into attention pricing."""
        from app.services.judge import _gather_context

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=0)))
        fake_snap = MagicMock(sara_emotional_tone="reflective", sara_emotional_intensity=0.6,
                               sara_emotional_about="being wrong about home lately")

        with patch("app.services.activity_state_machine.activity_state_machine") as mock_asm, \
             patch("app.services.interruptibility.compute_interruptibility") as mock_interrupt, \
             patch("app.services.delivery_policy.sense_sleep_state", new=AsyncMock(return_value=MagicMock(asleep=False))), \
             patch("app.services.judge._gather_recent_chat", new=AsyncMock(return_value=[])), \
             patch("app.services.working_memory.read_memory", new=AsyncMock(return_value=fake_snap)):
            mock_asm.current = MagicMock()
            mock_interrupt.return_value = MagicMock(score=0.7)
            ctx = await _gather_context(mock_db, "user-1")

        assert "affect_concerned_about_david" not in ctx


class TestInitiativeMargin:
    @pytest.mark.asyncio
    async def test_reflective_mood_raises_the_auto_execute_threshold(self):
        from app.services.deliberation_gate import _initiative_confidence_threshold

        fake_snap = MagicMock(sara_emotional_tone="reflective", sara_emotional_intensity=0.6)
        with patch("app.services.working_memory.read_memory", new=AsyncMock(return_value=fake_snap)):
            threshold = await _initiative_confidence_threshold("user-1")

        assert threshold == 0.75

    @pytest.mark.asyncio
    async def test_normal_mood_uses_base_threshold(self):
        from app.services.deliberation_gate import _initiative_confidence_threshold

        fake_snap = MagicMock(sara_emotional_tone="attentive", sara_emotional_intensity=0.3)
        with patch("app.services.working_memory.read_memory", new=AsyncMock(return_value=fake_snap)):
            threshold = await _initiative_confidence_threshold("user-1")

        assert threshold == 0.6

    @pytest.mark.asyncio
    async def test_low_intensity_reflective_does_not_raise_threshold(self):
        """A faint reflective mood isn't a real self-doubt period."""
        from app.services.deliberation_gate import _initiative_confidence_threshold

        fake_snap = MagicMock(sara_emotional_tone="reflective", sara_emotional_intensity=0.2)
        with patch("app.services.working_memory.read_memory", new=AsyncMock(return_value=fake_snap)):
            threshold = await _initiative_confidence_threshold("user-1")

        assert threshold == 0.6

    @pytest.mark.asyncio
    async def test_read_failure_falls_back_to_base_threshold(self):
        from app.services.deliberation_gate import _initiative_confidence_threshold

        with patch("app.services.working_memory.read_memory", new=AsyncMock(side_effect=RuntimeError("boom"))):
            threshold = await _initiative_confidence_threshold("user-1")

        assert threshold == 0.6
