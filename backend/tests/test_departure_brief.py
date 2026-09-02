"""MORNING_NOTIFICATIONS_PLAN_2026_08_18 Phase 4: the departure-brief once-
per-day trigger. Full end-to-end send is exercised live (see the plan's
verification section); these tests cover the pure gating logic that decides
whether _run should fire, skip, or wait.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.departure_brief import _get_departure_time, _already_handled_today


class TestGetDepartureTime:
    @pytest.mark.asyncio
    async def test_reads_configured_value(self):
        result = MagicMock()
        result.fetchone.return_value = ("08:15",)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        assert await _get_departure_time(db) == (8, 15)

    @pytest.mark.asyncio
    async def test_defaults_when_unset(self):
        result = MagicMock()
        result.fetchone.return_value = None
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        assert await _get_departure_time(db) == (7, 40)

    @pytest.mark.asyncio
    async def test_defaults_on_malformed_value(self):
        result = MagicMock()
        result.fetchone.return_value = ("not-a-time",)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        assert await _get_departure_time(db) == (7, 40)

    @pytest.mark.asyncio
    async def test_defaults_on_db_error(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=RuntimeError("db exploded"))

        assert await _get_departure_time(db) == (7, 40)


class TestAlreadyHandledToday:
    @pytest.mark.asyncio
    async def test_true_when_topic_logged(self):
        result = MagicMock()
        result.fetchone.return_value = (True,)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        assert await _already_handled_today(db, "u1", "departure_brief:2026-08-18") is True

    @pytest.mark.asyncio
    async def test_false_when_not_logged(self):
        result = MagicMock()
        result.fetchone.return_value = (False,)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        assert await _already_handled_today(db, "u1", "departure_brief:2026-08-18") is False


class TestAlreadyAway:
    def test_true_when_state_machine_reports_away(self):
        from app.tasks.departure_brief import _already_away
        from app.services.activity_state_machine import ActivityState

        fake_snapshot = type("S", (), {"state": ActivityState.AWAY})()
        with patch("app.services.activity_state_machine.activity_state_machine") as mock_asm:
            mock_asm.current = fake_snapshot
            assert _already_away() is True

    def test_false_when_state_machine_reports_active(self):
        from app.tasks.departure_brief import _already_away
        from app.services.activity_state_machine import ActivityState

        fake_snapshot = type("S", (), {"state": ActivityState.ACTIVE})()
        with patch("app.services.activity_state_machine.activity_state_machine") as mock_asm:
            mock_asm.current = fake_snapshot
            assert _already_away() is False
