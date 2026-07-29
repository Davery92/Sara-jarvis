"""
Tests for the Arc 2.1 world_state projection (context_snapshot.get_world_state).

Each slice (david, home, calendar_horizon, health_today, work, fleet) is
independently stamped with updated_at/source/confidence so a broken source
degrades only its own slice, never the whole object.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.context_snapshot import get_world_state, _slice


class TestSliceHelper:
    def test_slice_carries_data_through(self):
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        s = _slice(now, "test_source", 0.8, foo="bar", n=3)
        assert s.source == "test_source"
        assert s.confidence == 0.8
        assert s.data == {"foo": "bar", "n": 3}
        assert s.updated_at == now


class TestGetWorldStateSliceIsolation:
    @pytest.mark.asyncio
    async def test_all_six_slices_present_on_success(self):
        db = MagicMock()
        scalar_result = MagicMock()
        scalar_result.scalar.return_value = 1
        fetchall_result = MagicMock()
        fetchall_result.fetchall.return_value = []
        db.execute.side_effect = lambda *a, **k: scalar_result

        with patch("app.services.unified_context.read_snapshot", new=AsyncMock(
            return_value=MagicMock(
                activity_state="UNKNOWN", interruptibility=0.5, current_place=None,
                mood=None, hours_since_last_chat=0.0, home_occupied=True,
                active_rooms=[], temperature_inside=None, temperature_outside=None,
                weather_condition=None,
            )
        )):
            world = await get_world_state(db, user_id="u1")

        assert world.david is not None
        assert world.home is not None
        assert world.calendar_horizon is not None
        assert world.health_today is not None
        assert world.work is not None
        assert world.fleet is not None

    @pytest.mark.asyncio
    async def test_broken_unified_context_only_degrades_david_and_home(self):
        """A failure reading unified_context must not touch calendar_horizon,
        work, or fleet — slice isolation is the whole point of Arc 2.1."""
        db = MagicMock()
        scalar_result = MagicMock()
        scalar_result.scalar.return_value = 2
        db.execute.side_effect = lambda *a, **k: scalar_result

        with patch("app.services.unified_context.read_snapshot", new=AsyncMock(
            side_effect=RuntimeError("redis down")
        )):
            world = await get_world_state(db, user_id="u1")

        assert world.david is None
        assert world.home is None
        assert world.calendar_horizon is not None
        assert world.calendar_horizon.confidence == 1.0
        assert world.work is not None
        assert world.fleet is not None
