"""
Tests for the SINGULAR_SARA_MASTER_PLAN §C5 fold-in: `_deliberation_fallback_
async` and `_deep_deliberation_async` in app/tasks/autonomy.py route through
`kernel.ambient_turn` — without double-acquiring the "heavy_llm" exclusive
lock (ambient_turn owns that lock itself).

Arc 3 write-freeze (2026-07-29): the legacy `deliberation_engine.run()`
branch (used pre-SINGULAR_KERNEL, or when the flag was off) was deleted
after `legacy_path_counters` confirmed 0 legacy calls / 65 kernel calls over
a 3-day live window — see ARC3_JOB_INVENTORY_2026_07_29.md. There is no
longer a flag-off code path to test.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.tasks import autonomy


class TestDeliberationFallback:
    @pytest.mark.asyncio
    async def test_routes_through_kernel_without_double_locking(self):
        with patch("app.services.observation_log.prune_old", new=AsyncMock(return_value=1)), \
             patch("app.services.salience.salience_scorer.should_deliberate", new=AsyncMock(return_value=True)):

            fake_kernel_result = {
                "status": "completed", "notifications": 4, "duration": 9.9,
                "correlation_id": "turn_abc",
            }
            mock_ambient_turn = AsyncMock(return_value=fake_kernel_result)

            with patch("app.services.kernel.ambient_turn", mock_ambient_turn), \
                 patch("app.services.autonomy.coordination.get_coordinator") as mock_get_coord:

                result = await autonomy._deliberation_fallback_async()

        # Must NOT touch the coordinator at all — kernel.ambient_turn owns
        # its own lock.
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
             patch("app.services.salience.salience_scorer.should_deliberate", new=AsyncMock(return_value=True)):

            mock_ambient_turn = AsyncMock(return_value={"skipped": "exclusive_group_busy", "state": "ambient"})

            with patch("app.services.kernel.ambient_turn", mock_ambient_turn):
                result = await autonomy._deliberation_fallback_async()

        assert result["skipped"] == "exclusive_group_busy"
        assert result["routed_via"] == "kernel"

    @pytest.mark.asyncio
    async def test_no_deliberation_needed_short_circuits(self):
        with patch("app.services.observation_log.prune_old", new=AsyncMock(return_value=0)), \
             patch("app.services.salience.salience_scorer.should_deliberate", new=AsyncMock(return_value=False)):
            result = await autonomy._deliberation_fallback_async()

        assert result == {"status": "no_deliberation_needed", "pruned": 0}


class TestDeepDeliberation:
    @pytest.mark.asyncio
    async def test_routes_through_kernel_with_deep_and_scheduled_anchor(self):
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

    @pytest.mark.asyncio
    async def test_kernel_skip_is_surfaced_not_swallowed(self):
        mock_ambient_turn = AsyncMock(return_value={"skipped": "exclusive_group_busy", "state": "ambient"})

        with patch("app.services.kernel.ambient_turn", mock_ambient_turn):
            result = await autonomy._deep_deliberation_async("user-1")

        assert result["skipped"] == "exclusive_group_busy"
        assert result["routed_via"] == "kernel"
