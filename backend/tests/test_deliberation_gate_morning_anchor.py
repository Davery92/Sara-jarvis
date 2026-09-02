"""MORNING_NOTIFICATIONS_PLAN_2026_08_18 Phase 3b: greeting/schedule
proposals in the 4am-noon window get gated once the morning brief (wake
anchor) has already logged today — checkins suppress, schedule content
routes to the departure-brief queue instead of being dropped.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.deliberation import NotificationProposal
from app.services.deliberation_gate import _morning_anchor_logged_today, _queue_for_departure_brief


class TestMorningAnchorLoggedToday:
    @pytest.mark.asyncio
    async def test_true_when_topic_exists(self):
        result = MagicMock()
        result.scalar.return_value = True
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        assert await _morning_anchor_logged_today(db, "u1") is True

    @pytest.mark.asyncio
    async def test_false_when_topic_absent(self):
        result = MagicMock()
        result.scalar.return_value = False
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        assert await _morning_anchor_logged_today(db, "u1") is False

    @pytest.mark.asyncio
    async def test_fails_closed_on_db_error(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=RuntimeError("db exploded"))

        # Fail-closed (False) here just means "don't assume covered" — the
        # gate falls through to the normal delivery pipeline, which has its
        # own independent dedup/cooldown safety nets.
        assert await _morning_anchor_logged_today(db, "u1") is False


class TestQueueForDepartureBrief:
    @pytest.mark.asyncio
    async def test_holds_with_await_departure_reason(self):
        db = AsyncMock()
        proposal = NotificationProposal(
            title="Iron Forums at 1", message="Don't forget", category="schedule", priority="normal",
        )

        with patch("app.services.delivery_policy.hold_notification", new_callable=AsyncMock) as mock_hold:
            mock_hold.return_value = 99
            await _queue_for_departure_brief(db, "u1", proposal)

        mock_hold.assert_awaited_once()
        _, kwargs = mock_hold.call_args
        assert kwargs["category"] == "schedule"
        assert kwargs["title"] == "Iron Forums at 1"
        assert kwargs["decision"].reason == "await_departure"
        assert kwargs["decision"].action == "hold"
