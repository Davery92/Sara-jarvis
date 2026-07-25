"""
Tests for the P2 daily non-urgent push budget
(app.services.unified_notification._daily_push_budget_available and its
enforcement inside route_through_attention_queue).

SARA_PROACTIVENESS_IMPLEMENTATION_PLAN_2026_07_25 P2: no more than
DAILY_NON_URGENT_PUSH_BUDGET non-urgent proactive pushes per day, excluding
urgent/critical priority and requested timer/reminder categories.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.unified_notification import (
    _daily_push_budget_available,
    DAILY_NON_URGENT_PUSH_BUDGET,
    route_through_attention_queue,
)


def _mock_db_with_count(count: int):
    db = AsyncMock()
    result = MagicMock()
    result.scalar.return_value = count
    db.execute = AsyncMock(return_value=result)
    return db


class TestDailyPushBudgetAvailable:
    @pytest.mark.asyncio
    async def test_urgent_priority_always_exempt(self):
        db = _mock_db_with_count(999)
        assert await _daily_push_budget_available(db, "u1", "general", "urgent") is True

    @pytest.mark.asyncio
    async def test_critical_priority_always_exempt(self):
        db = _mock_db_with_count(999)
        assert await _daily_push_budget_available(db, "u1", "general", "critical") is True

    @pytest.mark.asyncio
    async def test_timer_category_always_exempt(self):
        db = _mock_db_with_count(999)
        assert await _daily_push_budget_available(db, "u1", "timer", "normal") is True

    @pytest.mark.asyncio
    async def test_reminder_category_always_exempt(self):
        db = _mock_db_with_count(999)
        assert await _daily_push_budget_available(db, "u1", "reminder", "normal") is True

    @pytest.mark.asyncio
    async def test_under_budget_allows_push(self):
        db = _mock_db_with_count(DAILY_NON_URGENT_PUSH_BUDGET - 1)
        assert await _daily_push_budget_available(db, "u1", "general", "normal") is True

    @pytest.mark.asyncio
    async def test_at_budget_blocks_push(self):
        db = _mock_db_with_count(DAILY_NON_URGENT_PUSH_BUDGET)
        assert await _daily_push_budget_available(db, "u1", "general", "normal") is False

    @pytest.mark.asyncio
    async def test_over_budget_blocks_push(self):
        db = _mock_db_with_count(DAILY_NON_URGENT_PUSH_BUDGET + 5)
        assert await _daily_push_budget_available(db, "u1", "general", "high") is False

    @pytest.mark.asyncio
    async def test_fails_open_on_db_error(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=RuntimeError("db exploded"))
        assert await _daily_push_budget_available(db, "u1", "general", "normal") is True


class TestBudgetEnforcedInAttentionQueue:
    @pytest.mark.asyncio
    async def test_high_priority_push_suppressed_when_budget_exhausted(self):
        """A high-priority item would normally always push — the daily
        budget must still be able to veto it once exhausted."""
        db = AsyncMock()

        with patch("app.core.config.settings") as mock_settings, \
             patch("app.services.autonomy.attention_queue.attention_queue") as mock_queue, \
             patch("app.services.unified_notification._daily_push_budget_available",
                   new_callable=AsyncMock) as mock_budget, \
             patch("app.services.unified_notification._cooldown_for", return_value=0), \
             patch("app.services.habituation.note_delivery", new_callable=AsyncMock):
            mock_settings.autonomy_attention_enabled = True
            mock_queue.create_item = AsyncMock(return_value="attn-item-1")
            mock_budget.return_value = False  # budget exhausted

            result = await route_through_attention_queue(
                user_id="u1", title="Heads up", message="Something happened",
                priority="high", category="general", source="test", db=db,
            )

        assert result["sent"] is False
        assert result["reason"] == "daily_push_budget_exhausted"
        assert result["attention_item_id"] == "attn-item-1"

    @pytest.mark.asyncio
    async def test_high_priority_push_delivered_when_budget_available(self):
        db = AsyncMock()

        with patch("app.core.config.settings") as mock_settings, \
             patch("app.services.autonomy.attention_queue.attention_queue") as mock_queue, \
             patch("app.services.unified_notification._daily_push_budget_available",
                   new_callable=AsyncMock) as mock_budget, \
             patch("app.services.unified_notification._cooldown_for", return_value=0), \
             patch("app.services.unified_notification.send_notification",
                   new_callable=AsyncMock) as mock_send, \
             patch("app.services.habituation.note_delivery", new_callable=AsyncMock):
            mock_settings.autonomy_attention_enabled = True
            mock_queue.create_item = AsyncMock(return_value="attn-item-2")
            mock_budget.return_value = True  # budget has room
            mock_send.return_value = {"sent": True, "reason": "sent"}

            result = await route_through_attention_queue(
                user_id="u1", title="Heads up", message="Something happened",
                priority="high", category="general", source="test", db=db,
            )

        assert result["sent"] is True
        mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_timer_category_bypasses_budget_even_when_exhausted(self):
        """Budget-exempt categories short-circuit inside
        _daily_push_budget_available itself, so the queue-level suppression
        branch never fires for them even under a real (unpatched) budget
        check."""
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 999  # would exhaust budget for a non-exempt category
        db.execute = AsyncMock(return_value=count_result)

        with patch("app.core.config.settings") as mock_settings, \
             patch("app.services.autonomy.attention_queue.attention_queue") as mock_queue, \
             patch("app.services.unified_notification._cooldown_for", return_value=0), \
             patch("app.services.unified_notification.send_notification",
                   new_callable=AsyncMock) as mock_send, \
             patch("app.services.habituation.note_delivery", new_callable=AsyncMock):
            mock_settings.autonomy_attention_enabled = True
            mock_queue.create_item = AsyncMock(return_value="attn-item-3")
            mock_send.return_value = {"sent": True, "reason": "sent"}

            result = await route_through_attention_queue(
                user_id="u1", title="Timer done", message="Pasta timer finished",
                priority="high", category="timer", source="test", db=db,
            )

        assert result["sent"] is True
