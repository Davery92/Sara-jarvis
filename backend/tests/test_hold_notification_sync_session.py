"""MORNING_NOTIFICATIONS_PLAN_2026_08_18 Phase 2: hold_notification (and the
rest of delivery_policy.py) must work against a sync Session, not just an
AsyncSession — the 2 AM research-brief Celery path passes a sync Session,
and `await db.execute(...)` on one raises TypeError, silently rolling back
the INSERT and losing the notification.
"""
from unittest.mock import MagicMock

import pytest

from app.services.delivery_policy import hold_notification, DeliveryDecision


def _mock_sync_db(held_id: int = 42):
    """A MagicMock standing in for a sync SQLAlchemy Session: execute/commit/
    rollback are plain (non-awaitable) methods, unlike AsyncSession's."""
    result = MagicMock()
    result.first.return_value = (held_id,)
    db = MagicMock()
    db.execute.return_value = result
    db.commit.return_value = None
    db.rollback.return_value = None
    return db


class TestHoldNotificationSyncSession:
    @pytest.mark.asyncio
    async def test_persists_row_with_sync_session(self):
        db = _mock_sync_db(held_id=42)
        decision = DeliveryDecision(action="hold", reason="asleep:sensed")

        hid = await hold_notification(
            db, user_id="u1", title="Research brief ready",
            message="Overnight research complete", category="research",
            priority="normal", source="research_brief", topic="research:overnight",
            payload=None, decision=decision,
        )

        assert hid == 42
        db.execute.assert_called_once()
        db.commit.assert_called_once()
        db.rollback.assert_not_called()

    @pytest.mark.asyncio
    async def test_rolls_back_and_returns_none_on_failure(self):
        db = MagicMock()
        db.execute.side_effect = RuntimeError("db exploded")
        db.rollback.return_value = None
        decision = DeliveryDecision(action="hold", reason="asleep:sensed")

        hid = await hold_notification(
            db, user_id="u1", title="x", message="y", category="general",
            priority="normal", source="test", topic=None,
            payload=None, decision=decision,
        )

        assert hid is None
        db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_persists_row_with_async_session(self):
        """Regression guard: the fix must not break the AsyncSession path."""
        from unittest.mock import AsyncMock

        result = MagicMock()
        result.first.return_value = (7,)
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock(return_value=None)
        db.rollback = AsyncMock(return_value=None)
        decision = DeliveryDecision(action="hold", reason="asleep:sensed")

        hid = await hold_notification(
            db, user_id="u1", title="x", message="y", category="general",
            priority="normal", source="test", topic=None,
            payload=None, decision=decision,
        )

        assert hid == 7
        db.commit.assert_awaited_once()
