"""Phase 3 of NOTIFICATION_DELIVERY_FIX_PLAN_2026_08_17: learned-buzz gate.

The old gate (engaged_rate >= 40%, cold-start grace only below 5 sends) was
unreachable in practice — engagement only accrues from pushes, so a category
stuck below 40% could never climb out. These tests exercise the revised
_learned_buzz_decision against a mocked DB session and mocked tunables.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone as dt_tz, timedelta

from app.services import unified_notification as un


def _mock_db(sent, engaged, read_count, last_sent_at):
    """Row shape matches the SELECT in _learned_buzz_decision:
    (sent, engaged, read_count, last_sent_at)."""
    row = (sent, engaged, read_count, last_sent_at)
    result = MagicMock()
    result.fetchone.return_value = row
    db = MagicMock()
    db.execute.return_value = result
    return db


def _mock_grace_db(count_today):
    result = MagicMock()
    result.scalar.return_value = count_today
    db = MagicMock()
    db.execute.return_value = result
    return db


DEFAULT_TUNABLES = {
    un._BUZZ_ENGAGED_RATE_KEY: un.DEFAULT_BUZZ_ENGAGED_RATE,
    un._BUZZ_READ_RATE_KEY: un.DEFAULT_BUZZ_READ_RATE,
    un._BUZZ_INTERRUPTIBILITY_KEY: un.DEFAULT_BUZZ_INTERRUPTIBILITY,
    un._BUZZ_SILENT_DAYS_KEY: un.DEFAULT_BUZZ_SILENT_DAYS,
}


def _patch_tunables(overrides=None):
    values = {**DEFAULT_TUNABLES, **(overrides or {})}
    return patch(
        "app.services.tunables.get_tunable_float",
        side_effect=lambda key, default: values.get(key, default),
    )


class TestLearnedBuzzDecision:
    @pytest.mark.asyncio
    async def test_high_read_rate_low_engagement_buzzes(self):
        """50% read-rate, 10% engagement -> buzzes (read path)."""
        db = _mock_db(sent=10, engaged=1, read_count=5, last_sent_at=datetime.now(dt_tz.utc))
        with _patch_tunables(), \
             patch("app.services.activity_state_machine.activity_state_machine") as asm, \
             patch("app.services.interruptibility.compute_interruptibility") as ci:
            asm.current = MagicMock()
            ci.return_value = MagicMock(score=0.9)
            decision = await un._learned_buzz_decision(db, "user-1", "general")
        assert decision is True

    @pytest.mark.asyncio
    async def test_low_read_low_engagement_inbox_only(self):
        """10% read + 10% engagement, sent recently -> inbox-only (no grace)."""
        db = _mock_db(sent=10, engaged=1, read_count=1, last_sent_at=datetime.now(dt_tz.utc))
        with _patch_tunables():
            decision = await un._learned_buzz_decision(db, "user-1", "checkin")
        assert decision is False

    @pytest.mark.asyncio
    async def test_zero_pushes_in_7_days_gets_grace(self):
        """Below threshold but silent >= 7 days -> grace push granted."""
        stale = datetime.now(dt_tz.utc) - timedelta(days=8)
        db = _mock_db(sent=10, engaged=1, read_count=1, last_sent_at=stale)
        with _patch_tunables(), \
             patch.object(un, "_grace_push_available", new=AsyncMock(return_value=True)) as grace:
            decision = await un._learned_buzz_decision(db, "user-1", "agent_task")
        assert decision is True
        grace.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_grace_capped_per_day(self):
        """Silent category, but the day's grace allotment is already spent."""
        stale = datetime.now(dt_tz.utc) - timedelta(days=30)
        db = _mock_db(sent=10, engaged=0, read_count=0, last_sent_at=stale)
        with _patch_tunables(), \
             patch.object(un, "_grace_push_available", new=AsyncMock(return_value=False)):
            decision = await un._learned_buzz_decision(db, "user-1", "checkin")
        assert decision is False

    @pytest.mark.asyncio
    async def test_cold_start_under_5_sends_defers_to_grace(self):
        db = _mock_db(sent=2, engaged=0, read_count=0, last_sent_at=None)
        with _patch_tunables(), \
             patch.object(un, "_grace_push_available", new=AsyncMock(return_value=True)) as grace:
            decision = await un._learned_buzz_decision(db, "user-1", "email")
        assert decision is True
        grace.assert_awaited_once_with(db, "user-1", "email")

    @pytest.mark.asyncio
    async def test_qualifies_but_not_interruptible(self):
        db = _mock_db(sent=10, engaged=5, read_count=5, last_sent_at=datetime.now(dt_tz.utc))
        with _patch_tunables(), \
             patch("app.services.activity_state_machine.activity_state_machine") as asm, \
             patch("app.services.interruptibility.compute_interruptibility") as ci:
            asm.current = MagicMock()
            ci.return_value = MagicMock(score=0.1)
            decision = await un._learned_buzz_decision(db, "user-1", "general")
        assert decision is False

    @pytest.mark.asyncio
    async def test_db_error_fails_closed(self):
        db = MagicMock()
        db.execute.side_effect = Exception("connection lost")
        decision = await un._learned_buzz_decision(db, "user-1", "general")
        assert decision is False


class TestGracePushAvailable:
    @pytest.mark.asyncio
    async def test_under_cap_available(self):
        db = _mock_grace_db(count_today=0)
        assert await un._grace_push_available(db, "user-1", "email") is True

    @pytest.mark.asyncio
    async def test_at_cap_unavailable(self):
        db = _mock_grace_db(count_today=un.GRACE_PUSHES_PER_CATEGORY_PER_DAY)
        assert await un._grace_push_available(db, "user-1", "email") is False
