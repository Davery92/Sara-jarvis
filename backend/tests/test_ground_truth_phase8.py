"""Ground-truth Phase 8: cadence and cost.

~140 deliberations a day, including through 1–5 AM, because the daemon proxy
passed `force=True` on every tick and skipped the salience check entirely. Four
overnight cycles on 2026-09-01 paraphrased one settled concern; all four were
held for sleep and flushed into David's inbox at 06:00. Meanwhile background model
calls reported nothing to `token_usage`, so none of it was measurable.
"""
from __future__ import annotations

import pathlib
from unittest.mock import patch

import pytest

from app.services.kernel import (
    NIGHT_WAKE_REASONS, QUIET_NIGHT_HOURS, WakeReason, _wakes_the_sleeping_mind,
)


class TestTheDaemonNoLongerForces:
    def test_the_proxy_passes_force_false(self):
        source = pathlib.Path("app/routes/acs_daemon.py").read_text()
        assert "WakeReason.DAEMON_PROXY, force=True" not in source
        assert "WakeReason.DAEMON_PROXY, force=False" in source

    def test_the_fallback_is_the_only_forcer_and_only_when_awake(self):
        source = pathlib.Path("app/tasks/autonomy.py").read_text()
        block = source.split("async def _deliberation_fallback_async")[1].split("\nasync def ")[0]
        assert "if not (6 <= hour < 22)" in block
        assert "force=True" in block


class TestTheMindSleeps:
    def test_the_quiet_window_is_one_to_five(self):
        assert list(QUIET_NIGHT_HOURS) == [1, 2, 3, 4]

    def test_only_interoception_and_a_human_wake_it(self):
        assert _wakes_the_sleeping_mind(WakeReason.INTEROCEPTION)
        assert _wakes_the_sleeping_mind(WakeReason.MANUAL)
        for reason in (WakeReason.PROMOTED_EVENT, WakeReason.SLEEP_PRESSURE,
                       WakeReason.DAEMON_PROXY, WakeReason.CHECKIN,
                       WakeReason.ANTICIPATION, WakeReason.SCHEDULED_ANCHOR):
            assert not _wakes_the_sleeping_mind(reason), reason

    def test_the_night_set_is_exactly_those_two(self):
        assert NIGHT_WAKE_REASONS == {WakeReason.INTEROCEPTION, WakeReason.MANUAL}

    @pytest.mark.asyncio
    async def test_an_ordinary_wake_is_skipped_at_three_am(self):
        import datetime
        from app.services import kernel

        three_am = datetime.datetime(2026, 9, 2, 3, 0, tzinfo=datetime.timezone.utc)
        with patch("app.core.timezone.now", return_value=three_am.replace(hour=3)):
            result = await kernel.ambient_turn(
                "u1", wake_reason=WakeReason.DAEMON_PROXY,
            )
        assert result.get("skipped") == "quiet_hours"


class TestExplorationStopsOvernight:
    @pytest.mark.parametrize("hour,context,expected", [
        (23, "idle", 0.0),
        (3, "idle", 0.0),
        (5, "idle", 0.0),
        (10, "idle", 0.1),
        (10, "focused_work", 0.05),
        (14, "FOCUSED_WORK", 0.05),
    ])
    def test_epsilon_by_hour_and_context(self, hour, context, expected):
        import datetime
        from app.services import subconscious

        moment = datetime.datetime(2026, 9, 2, hour, 0)
        with patch("app.core.timezone.now", return_value=moment):
            assert subconscious.effective_explore_rate(0.1, context) == expected

    def test_a_real_anomaly_still_promotes_with_zero_epsilon(self):
        """The anomaly floor is untouched by the quiet hours."""
        from app.services.subconscious import decide_promotion

        promoted, reason = decide_promotion(0.99, 0.8, 0.92, 0.0, 0.5)
        assert promoted and reason == "override"


class TestCostIsMeasurable:
    def test_background_calls_report_their_job_name(self):
        source = pathlib.Path("app/core/llm.py").read_text()
        assert "def _record_background_usage" in source
        # Both tiers — a fast-lane call is still a call.
        assert source.count("_record_background_usage(result, caller, use_model)") == 2

    @pytest.mark.parametrize("module,caller", [
        ("app/services/deliberation.py", "deliberation"),
        ("app/services/appraisal.py", "appraisal"),
        ("app/services/judge.py", "judge"),
        ("app/services/review.py", "review"),
        ("app/services/compose.py", "compose"),
        ("app/services/consolidation.py", "consolidation"),
    ])
    def test_every_cognition_job_names_itself(self, module, caller):
        assert f'caller="{caller}"' in pathlib.Path(module).read_text()

    def test_there_is_somewhere_to_read_the_number(self):
        source = pathlib.Path("app/routes/debug_notifications.py").read_text()
        assert "/debug/cognition-cost" in source
        assert "deliberations_per_day" in source
