"""
Tests for the SINGULAR_SARA_MASTER_PLAN §C5 fold-in: `_deliberation_fallback_
async` and `_deep_deliberation_async` in app/tasks/autonomy.py must behave
EXACTLY as before when SINGULAR_KERNEL is off (the default), and route
through `kernel.ambient_turn` — without double-acquiring the "heavy_llm"
exclusive lock — when it's on.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks import autonomy


def _mock_flag(enabled: bool):
    return patch("app.core.feature_flags.is_enabled", return_value=enabled)


class TestDeliberationFallbackFlagOff:
    @pytest.mark.asyncio
    async def test_legacy_path_unchanged_when_flag_off(self):
        with patch("app.services.observation_log.prune_old", new=AsyncMock(return_value=3)), \
             patch("app.services.salience.salience_scorer.should_deliberate", new=AsyncMock(return_value=True)), \
             _mock_flag(False):

            mock_coordinator = MagicMock()
            mock_coordinator.acquire_exclusive = AsyncMock(return_value=True)
            mock_coordinator.release_exclusive = AsyncMock()

            mock_result = MagicMock(duration_seconds=1.5)
            mock_engine = MagicMock()
            mock_engine.run = AsyncMock(return_value=mock_result)

            with patch("app.services.autonomy.coordination.get_coordinator", return_value=mock_coordinator), \
                 patch("app.services.deliberation.deliberation_engine", mock_engine), \
                 patch("app.services.deliberation_gate.process_deliberation_result",
                       new=AsyncMock(return_value={"notifications_sent": 2})), \
                 patch("app.services.legacy_path_counters.record_legacy_path", new=AsyncMock()) as mock_legacy:

                result = await autonomy._deliberation_fallback_async()

        assert result == {"status": "deliberated", "pruned": 3, "notifications": 2, "duration": 1.5}
        mock_coordinator.acquire_exclusive.assert_awaited_once_with("deliberation-fallback", "heavy_llm")
        mock_legacy.assert_awaited_once_with("ambient_cognition")

    @pytest.mark.asyncio
    async def test_no_deliberation_needed_short_circuits_before_flag_check(self):
        with patch("app.services.observation_log.prune_old", new=AsyncMock(return_value=0)), \
             patch("app.services.salience.salience_scorer.should_deliberate", new=AsyncMock(return_value=False)):
            result = await autonomy._deliberation_fallback_async()

        assert result == {"status": "no_deliberation_needed", "pruned": 0}


class TestDeliberationFallbackFlagOn:
    @pytest.mark.asyncio
    async def test_routes_through_kernel_without_double_locking(self):
        with patch("app.services.observation_log.prune_old", new=AsyncMock(return_value=1)), \
             patch("app.services.salience.salience_scorer.should_deliberate", new=AsyncMock(return_value=True)), \
             _mock_flag(True):

            fake_kernel_result = {
                "status": "completed", "notifications": 4, "duration": 9.9,
                "correlation_id": "turn_abc",
            }
            mock_ambient_turn = AsyncMock(return_value=fake_kernel_result)

            with patch("app.services.kernel.ambient_turn", mock_ambient_turn), \
                 patch("app.services.autonomy.coordination.get_coordinator") as mock_get_coord:

                result = await autonomy._deliberation_fallback_async()

        # The outer function must NOT touch the coordinator at all in this
        # branch — kernel.ambient_turn owns its own lock.
        mock_get_coord.assert_not_called()
        mock_ambient_turn.assert_awaited_once()
        _, kwargs = mock_ambient_turn.call_args
        assert kwargs["force"] is True
        assert result["status"] == "deliberated"
        assert result["pruned"] == 1
        assert result["routed_via"] == "kernel"
        assert result["correlation_id"] == "turn_abc"

    @pytest.mark.asyncio
    async def test_kernel_skip_is_surfaced_not_swallowed(self):
        with patch("app.services.observation_log.prune_old", new=AsyncMock(return_value=0)), \
             patch("app.services.salience.salience_scorer.should_deliberate", new=AsyncMock(return_value=True)), \
             _mock_flag(True):

            mock_ambient_turn = AsyncMock(return_value={"skipped": "exclusive_group_busy", "state": "ambient"})

            with patch("app.services.kernel.ambient_turn", mock_ambient_turn):
                result = await autonomy._deliberation_fallback_async()

        assert result["skipped"] == "exclusive_group_busy"
        assert result["routed_via"] == "kernel"


class TestDeepDeliberationFlagOff:
    @pytest.mark.asyncio
    async def test_legacy_path_unchanged_when_flag_off(self):
        with _mock_flag(False):
            mock_coordinator = MagicMock()
            mock_coordinator.acquire_exclusive = AsyncMock(return_value=True)
            mock_coordinator.release_exclusive = AsyncMock()

            mock_result = MagicMock(duration_seconds=42.0)
            mock_engine = MagicMock()
            mock_engine.run = AsyncMock(return_value=mock_result)

            fake_summary = {"notifications_sent": 1, "tasks_dispatched": 2, "tasks_proposed": 3}

            with patch("app.services.autonomy.coordination.get_coordinator", return_value=mock_coordinator), \
                 patch("app.services.deliberation.deliberation_engine", mock_engine), \
                 patch("app.services.deliberation_gate.process_deliberation_result",
                       new=AsyncMock(return_value=fake_summary)), \
                 patch("app.services.legacy_path_counters.record_legacy_path", new=AsyncMock()):

                result = await autonomy._deep_deliberation_async("user-1")

        assert result == {
            "status": "completed", "deep": True, "notifications": 1,
            "tasks_dispatched": 2, "tasks_proposed": 3, "duration": 42.0,
        }
        mock_coordinator.acquire_exclusive.assert_awaited_once_with("deep-deliberation", "heavy_llm")
        mock_engine.run.assert_awaited_once_with("user-1", deep=True)


class TestDeepDeliberationFlagOn:
    @pytest.mark.asyncio
    async def test_routes_through_kernel_with_deep_and_scheduled_anchor(self):
        with _mock_flag(True):
            fake_kernel_result = {
                "status": "completed", "notifications": 5,
                "tasks_dispatched": 1, "tasks_proposed": 2, "duration": 30.0,
                "correlation_id": "turn_deep",
            }
            mock_ambient_turn = AsyncMock(return_value=fake_kernel_result)

            with patch("app.services.kernel.ambient_turn", mock_ambient_turn), \
                 patch("app.services.autonomy.coordination.get_coordinator") as mock_get_coord:

                result = await autonomy._deep_deliberation_async("user-1")

        mock_get_coord.assert_not_called()
        args, kwargs = mock_ambient_turn.call_args
        assert kwargs["deep"] is True
        assert kwargs["force"] is True
        assert kwargs["wake_reason"].value == "scheduled_anchor"
        assert result["routed_via"] == "kernel"
        assert result["tasks_dispatched"] == 1
        assert result["tasks_proposed"] == 2
