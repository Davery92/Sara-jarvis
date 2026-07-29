"""
Tests for Arc 4.3: "ambient wakes with no David-work pull the top intent —
boredom's sanctioned outlet is pursuit, never narration." Curiosity pursuit
(the existing generate_candidates/select_and_pursue machinery) is triggered
as a natural consequence of an ambient turn discovering there was nothing to
do for David — not a new wake_reason or a parallel cognition (per the
Arc 3.1 ruling: "wake reasons shape context, they never select a different
cognition"). Retires the standalone curiosity-sweep schedule this replaces.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.curiosity import pursued_today


class TestPursuedTodayThrottle:
    """The old standalone curiosity-sweep job enforced '<=1 investigation/
    day' structurally, by only running once on its own schedule. Now that
    pursuit can be triggered by any idle ambient wake, the budget needs its
    own explicit check."""

    @pytest.mark.asyncio
    async def test_active_goal_counts_as_pursued(self):
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.first.return_value = (1,)
        mock_db.execute = AsyncMock(return_value=mock_result)
        assert await pursued_today(mock_db) is True

    @pytest.mark.asyncio
    async def test_no_active_or_completed_today_allows_pursuit(self):
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        assert await pursued_today(mock_db) is False


class TestAmbientTurnCuriosityTrigger:
    @pytest.mark.asyncio
    async def test_no_david_work_triggers_curiosity_pursuit(self):
        from app.services import kernel

        mock_result = MagicMock(thought="", duration_seconds=1.0)
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value=mock_result)

        empty_summary = {
            "notifications_sent": 0, "home_actions_executed": 0,
            "tasks_dispatched": 0, "tasks_proposed": 0, "research_dispatched": 0,
            "observations_consumed": 0,
        }

        mock_coordinator = MagicMock()
        mock_coordinator.acquire_exclusive = AsyncMock(return_value=True)
        mock_coordinator.release_exclusive = AsyncMock()

        with patch("app.services.autonomy.coordination.get_coordinator", return_value=mock_coordinator), \
             patch("app.services.deliberation.deliberation_engine", mock_engine), \
             patch("app.services.deliberation_gate.process_deliberation_result",
                   new=AsyncMock(return_value=empty_summary)), \
             patch("app.services.curiosity.pursued_today", new=AsyncMock(return_value=False)), \
             patch("app.services.curiosity.generate_candidates", new=AsyncMock(return_value={"minted": 1})), \
             patch("app.services.curiosity.select_and_pursue",
                   new=AsyncMock(return_value={"effect": "pursued", "domain": "home"})) as mock_pursue:
            result = await kernel.ambient_turn("user-1", force=True)

        mock_pursue.assert_awaited_once()
        assert result["curiosity_pursued"] == {"effect": "pursued", "domain": "home"}

    @pytest.mark.asyncio
    async def test_david_work_present_skips_curiosity(self):
        from app.services import kernel

        mock_result = MagicMock(thought="", duration_seconds=1.0)
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value=mock_result)

        busy_summary = {
            "notifications_sent": 1, "home_actions_executed": 0,
            "tasks_dispatched": 0, "tasks_proposed": 0, "research_dispatched": 0,
            "observations_consumed": 0,
        }

        mock_coordinator = MagicMock()
        mock_coordinator.acquire_exclusive = AsyncMock(return_value=True)
        mock_coordinator.release_exclusive = AsyncMock()

        with patch("app.services.autonomy.coordination.get_coordinator", return_value=mock_coordinator), \
             patch("app.services.deliberation.deliberation_engine", mock_engine), \
             patch("app.services.deliberation_gate.process_deliberation_result",
                   new=AsyncMock(return_value=busy_summary)), \
             patch("app.services.curiosity.select_and_pursue", new=AsyncMock()) as mock_pursue:
            result = await kernel.ambient_turn("user-1", force=True)

        mock_pursue.assert_not_awaited()
        assert result["curiosity_pursued"] is None

    @pytest.mark.asyncio
    async def test_already_pursued_today_skips_a_second_pursuit(self):
        """The explicit budget check — the whole point of pursued_today."""
        from app.services import kernel

        mock_result = MagicMock(thought="", duration_seconds=1.0)
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value=mock_result)

        empty_summary = {
            "notifications_sent": 0, "home_actions_executed": 0,
            "tasks_dispatched": 0, "tasks_proposed": 0, "research_dispatched": 0,
            "observations_consumed": 0,
        }

        mock_coordinator = MagicMock()
        mock_coordinator.acquire_exclusive = AsyncMock(return_value=True)
        mock_coordinator.release_exclusive = AsyncMock()

        with patch("app.services.autonomy.coordination.get_coordinator", return_value=mock_coordinator), \
             patch("app.services.deliberation.deliberation_engine", mock_engine), \
             patch("app.services.deliberation_gate.process_deliberation_result",
                   new=AsyncMock(return_value=empty_summary)), \
             patch("app.services.curiosity.pursued_today", new=AsyncMock(return_value=True)), \
             patch("app.services.curiosity.select_and_pursue", new=AsyncMock()) as mock_pursue:
            result = await kernel.ambient_turn("user-1", force=True)

        mock_pursue.assert_not_awaited()
        assert result["curiosity_pursued"] is None

    @pytest.mark.asyncio
    async def test_curiosity_failure_does_not_break_the_turn(self):
        """Best-effort — a broken curiosity pursuit must never take down
        the ambient turn it's riding along on."""
        from app.services import kernel

        mock_result = MagicMock(thought="", duration_seconds=1.0)
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value=mock_result)

        empty_summary = {
            "notifications_sent": 0, "home_actions_executed": 0,
            "tasks_dispatched": 0, "tasks_proposed": 0, "research_dispatched": 0,
            "observations_consumed": 0,
        }

        mock_coordinator = MagicMock()
        mock_coordinator.acquire_exclusive = AsyncMock(return_value=True)
        mock_coordinator.release_exclusive = AsyncMock()

        with patch("app.services.autonomy.coordination.get_coordinator", return_value=mock_coordinator), \
             patch("app.services.deliberation.deliberation_engine", mock_engine), \
             patch("app.services.deliberation_gate.process_deliberation_result",
                   new=AsyncMock(return_value=empty_summary)), \
             patch("app.services.curiosity.pursued_today", new=AsyncMock(side_effect=RuntimeError("db exploded"))):
            result = await kernel.ambient_turn("user-1", force=True)

        assert result["status"] == "completed"
        assert result["curiosity_pursued"] is None
