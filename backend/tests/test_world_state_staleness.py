"""
Tests for Arc 2.4 (SARA_ALIVE_BUILD_PLAN) — staleness is an event.

A world_state slice whose updated_at exceeds its freshness budget emits a
prediction.violated event instead of silently reading as current. Also
covers the fleet "never reported" gap found live: 6 real managed_host rows
all had last_seen_at = NULL, and a naive fallback would have called that
fresh — the exact class of bug body_state_projection.py's docstring warns
about ("never observed a heartbeat — say so rather than defaulting healthy").
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.contracts import WorldStateV1, WorldStateSliceV1
from app.services.context_snapshot import check_staleness, _FRESHNESS_BUDGET


def _world(**slices):
    now = datetime.now(timezone.utc)
    return WorldStateV1(as_of=now, user_id="u1", **slices)


def _slice_at(age: timedelta, source="test"):
    return WorldStateSliceV1(
        updated_at=datetime.now(timezone.utc) - age, source=source, confidence=1.0, data={},
    )


class TestStalenessDetection:
    @pytest.mark.asyncio
    async def test_fresh_slice_emits_nothing(self):
        world = _world(david=_slice_at(timedelta(minutes=5)))
        with patch("app.services.event_bus.emit_event", new=AsyncMock()) as mock_emit:
            stale = await check_staleness(world)
        assert stale == []
        mock_emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_stale_slice_emits_prediction_violated(self):
        world = _world(fleet=_slice_at(timedelta(hours=48), source="managed_host"))
        with patch("app.services.event_bus.emit_event", new=AsyncMock()) as mock_emit:
            stale = await check_staleness(world)
        assert stale == ["fleet"]
        mock_emit.assert_called_once()
        _, kwargs = mock_emit.call_args
        assert kwargs["payload"]["kind"] == "world_state_slice_stale"
        assert kwargs["payload"]["slice"] == "fleet"

    @pytest.mark.asyncio
    async def test_missing_slice_is_not_stale(self):
        """A slice that failed to load (None) is a confidence/availability
        problem, not a staleness one — check_staleness must not crash on it."""
        world = _world(david=None)
        with patch("app.services.event_bus.emit_event", new=AsyncMock()) as mock_emit:
            stale = await check_staleness(world)
        assert stale == []
        mock_emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_every_budgeted_slice_stale_reports_all(self):
        old = timedelta(days=10)
        world = _world(
            david=_slice_at(old), home=_slice_at(old),
            health_today=_slice_at(old), fleet=_slice_at(old),
        )
        with patch("app.services.event_bus.emit_event", new=AsyncMock()):
            stale = await check_staleness(world)
        assert set(stale) == set(_FRESHNESS_BUDGET.keys())


class TestFleetNeverReportedGap:
    @pytest.mark.asyncio
    async def test_never_reported_hosts_are_maximally_stale_not_fresh(self):
        """The literal live bug: 6 managed_host rows with last_seen_at=NULL.
        A `fresh if no data` fallback would silently call this healthy."""
        from unittest.mock import MagicMock
        from app.services.context_snapshot import get_world_state

        db = MagicMock()
        row = MagicMock()
        row.name, row.last_status, row.last_seen_at = "sara", None, None

        def execute_side_effect(*args, **kwargs):
            result = MagicMock()
            result.scalar.return_value = 0
            result.fetchall.return_value = [row]
            return result

        db.execute.side_effect = execute_side_effect

        with patch("app.services.unified_context.read_snapshot", new=AsyncMock(
            side_effect=RuntimeError("skip")
        )), patch("app.services.event_bus.emit_event", new=AsyncMock()):
            world = await get_world_state(db, user_id="u1")

        assert world.fleet is not None
        assert world.fleet.confidence == 0.0
        assert "sara" in world.fleet.data["unreachable"]
        assert "sara" in world.fleet.data["never_reported"]
        # epoch, not "now" — this is what makes it register as stale
        assert world.fleet.updated_at.year == 1970
