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
    async def test_expectations_slice_present_on_success(self):
        """Arc 4.1: the expected-day model — wake window, training slot,
        departure, quiet hours, next meeting. A prediction, not an
        observation, but built from the same slice-isolation discipline."""
        db = MagicMock()
        scalar_result = MagicMock()
        scalar_result.scalar.return_value = 1
        fetchone_result = MagicMock()
        fetchone_result.title = "Risk Ninja call"
        import datetime
        fetchone_result.start_time = datetime.datetime(2026, 7, 29, 14, 30)
        exec_result = MagicMock()
        exec_result.scalar.return_value = 1
        exec_result.fetchone.return_value = fetchone_result
        db.execute.side_effect = lambda *a, **k: exec_result

        with patch("app.services.unified_context.read_snapshot", new=AsyncMock(
            return_value=MagicMock(
                activity_state="UNKNOWN", interruptibility=0.5, current_place=None,
                mood=None, hours_since_last_chat=0.0, home_occupied=True,
                active_rooms=[], temperature_inside=None, temperature_outside=None,
                weather_condition=None,
            )
        )), patch("app.services.daily_rhythm.build_rhythm_summary",
                   return_value="Rhythm: wake ~5:34, gym ~13:08 (weekday)"), \
             patch("app.services.daily_rhythm.get_upcoming_rhythm_window",
                   return_value={"rhythm_key": "work_end", "label": "usually wrap up work",
                                 "minutes_until": 3, "confidence": 0.54}), \
             patch("app.services.training_day.is_training_day",
                   return_value={"is_training_day": True}):
            world = await get_world_state(db, user_id="u1")

        assert world.expectations is not None
        assert world.expectations.data["is_training_day"] is True
        assert world.expectations.data["next_meeting"] == "Risk Ninja call"
        assert world.expectations.data["next_rhythm_window"] == "usually wrap up work"
        assert world.expectations.confidence == 1.0

    @pytest.mark.asyncio
    async def test_expectations_slice_degrades_independently(self):
        """A broken daily_rhythm call must not touch any other slice."""
        db = MagicMock()
        scalar_result = MagicMock()
        scalar_result.scalar.return_value = 1
        db.execute.side_effect = lambda *a, **k: scalar_result

        with patch("app.services.unified_context.read_snapshot", new=AsyncMock(
            return_value=MagicMock(
                activity_state="UNKNOWN", interruptibility=0.5, current_place=None,
                mood=None, hours_since_last_chat=0.0, home_occupied=True,
                active_rooms=[], temperature_inside=None, temperature_outside=None,
                weather_condition=None,
            )
        )), patch("app.services.daily_rhythm.build_rhythm_summary",
                   side_effect=RuntimeError("db exploded")):
            world = await get_world_state(db, user_id="u1")

        assert world.expectations is None
        assert world.calendar_horizon is not None
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
