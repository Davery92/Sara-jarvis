"""
Tests for ActionSimulator (Phase 1 — Cortana Evolution).

Scenarios:
- Entity not found
- HA unreachable (timeout)
- Temperature bounds violations
- Rate limit hit
- Concurrent standing order conflict
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.autonomy.action_simulator import (
    ActionSimulator,
    SimulationResult,
    CLIMATE_TEMP_MIN,
    CLIMATE_TEMP_MAX,
    RATE_LIMIT_WINDOW_SECONDS,
)

# The HA control is imported inside _check_entity_exists, so patch at its source
HA_CONTROL_PATH = "app.services.ha_control_service.ha_control"


@pytest.fixture
def simulator():
    return ActionSimulator()


class TestEntityExists:
    """Test entity existence checks for HA actions."""

    @pytest.mark.asyncio
    async def test_entity_not_found(self, simulator):
        """Entity that doesn't exist should fail simulation."""
        with patch(HA_CONTROL_PATH) as mock_ha:
            mock_ha.get_entity_state = AsyncMock(return_value=None)
            result = await simulator.simulate(
                "home_light_control",
                {"entity_id": "light.nonexistent"},
            )
        assert not result.allowed
        assert any(c.name == "entity_exists" and not c.passed for c in result.checks)

    @pytest.mark.asyncio
    async def test_entity_unavailable(self, simulator):
        """Entity with 'unavailable' state should fail simulation."""
        with patch(HA_CONTROL_PATH) as mock_ha:
            mock_ha.get_entity_state = AsyncMock(return_value={"state": "unavailable"})
            result = await simulator.simulate(
                "home_light_control",
                {"entity_id": "light.broken"},
            )
        assert not result.allowed

    @pytest.mark.asyncio
    async def test_entity_exists_ok(self, simulator):
        """Entity that exists should pass."""
        with patch(HA_CONTROL_PATH) as mock_ha:
            mock_ha.get_entity_state = AsyncMock(return_value={"state": "on"})
            result = await simulator.simulate(
                "home_light_control",
                {"entity_id": "light.office"},
            )
        assert result.allowed
        assert any(c.name == "entity_exists" and c.passed for c in result.checks)

    @pytest.mark.asyncio
    async def test_ha_unreachable_timeout(self, simulator):
        """When HA is unreachable, entity check should fail (fail closed)."""
        with patch(HA_CONTROL_PATH) as mock_ha:
            mock_ha.get_entity_state = AsyncMock(side_effect=TimeoutError("Connection timed out"))
            result = await simulator.simulate(
                "home_light_control",
                {"entity_id": "light.office"},
            )
        assert not result.allowed
        assert any("unreachable" in c.reason.lower() for c in result.checks)

    @pytest.mark.asyncio
    async def test_ha_unreachable_connection_error(self, simulator):
        """ConnectionError from HA should also fail closed."""
        with patch(HA_CONTROL_PATH) as mock_ha:
            mock_ha.get_entity_state = AsyncMock(side_effect=ConnectionError("refused"))
            result = await simulator.simulate(
                "home_switch_control",
                {"entity_id": "switch.pump"},
            )
        assert not result.allowed

    @pytest.mark.asyncio
    async def test_non_ha_action_skips_entity_check(self, simulator):
        """Non-HA actions should skip entity existence check entirely."""
        result = await simulator.simulate(
            "check_emails",
            {},
        )
        assert result.allowed
        assert not any(c.name == "entity_exists" for c in result.checks)


class TestTemperatureBounds:
    """Test bounds checking for climate control."""

    def test_temperature_in_bounds(self, simulator):
        """Direct test of _check_temperature_bounds (no HA needed)."""
        check = simulator._check_temperature_bounds(72)
        assert check.passed

    def test_temperature_too_low(self, simulator):
        check = simulator._check_temperature_bounds(50)
        assert not check.passed
        assert "outside" in check.reason.lower()

    def test_temperature_too_high(self, simulator):
        check = simulator._check_temperature_bounds(95)
        assert not check.passed

    def test_temperature_at_min_boundary(self, simulator):
        check = simulator._check_temperature_bounds(CLIMATE_TEMP_MIN)
        assert check.passed

    def test_temperature_at_max_boundary(self, simulator):
        check = simulator._check_temperature_bounds(CLIMATE_TEMP_MAX)
        assert check.passed

    @pytest.mark.asyncio
    async def test_climate_action_out_of_bounds_blocked(self, simulator):
        """Full simulate() should block out-of-bounds temperature."""
        # Climate action without entity_id skips entity check
        result = await simulator.simulate(
            "home_climate_control",
            {"temperature": 95},
        )
        assert not result.allowed
        assert any(c.name == "temperature_bounds" and not c.passed for c in result.checks)

    @pytest.mark.asyncio
    async def test_no_temperature_skips_bounds_check(self, simulator):
        """Climate action without temperature arg should skip bounds check."""
        result = await simulator.simulate(
            "home_climate_control",
            {"mode": "auto"},
        )
        assert not any(c.name == "temperature_bounds" for c in result.checks)


class TestRateLimit:
    """Test rate limiting based on recent traces.
    Uses send_notification (non-HA) to isolate the rate limit check.
    """

    @pytest.mark.asyncio
    async def test_duplicate_action_within_window(self, simulator):
        recent_time = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        recent_traces = [
            {
                "action_name": "send_notification",
                "action_args": {"device": "mobile"},
                "created_at": recent_time,
            }
        ]
        result = await simulator.simulate(
            "send_notification",
            {"device": "mobile"},
            recent_traces=recent_traces,
        )
        assert not result.allowed
        assert any(c.name == "rate_limit" and not c.passed for c in result.checks)

    @pytest.mark.asyncio
    async def test_same_action_outside_window(self, simulator):
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS + 60)).isoformat()
        recent_traces = [
            {
                "action_name": "send_notification",
                "action_args": {"device": "mobile"},
                "created_at": old_time,
            }
        ]
        result = await simulator.simulate(
            "send_notification",
            {"device": "mobile"},
            recent_traces=recent_traces,
        )
        rate_checks = [c for c in result.checks if c.name == "rate_limit"]
        assert len(rate_checks) == 1
        assert rate_checks[0].passed

    @pytest.mark.asyncio
    async def test_different_entity_not_rate_limited(self, simulator):
        recent_time = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        recent_traces = [
            {
                "action_name": "send_notification",
                "action_args": {"device": "desktop"},
                "created_at": recent_time,
            }
        ]
        result = await simulator.simulate(
            "send_notification",
            {"device": "mobile"},
            recent_traces=recent_traces,
        )
        rate_checks = [c for c in result.checks if c.name == "rate_limit"]
        assert len(rate_checks) == 1
        assert rate_checks[0].passed

    @pytest.mark.asyncio
    async def test_no_recent_traces(self, simulator):
        result = await simulator.simulate(
            "send_notification",
            {"device": "mobile"},
            recent_traces=[],
        )
        assert not any(c.name == "rate_limit" for c in result.checks)


class TestStandingOrderConflict:
    """Test conflict detection with standing orders already executed this cycle.
    Uses send_notification (non-HA) to isolate the conflict check.
    """

    @pytest.mark.asyncio
    async def test_same_action_same_entity_conflicts(self, simulator):
        standing_order_actions = [
            {"action_name": "send_notification", "args": {"device": "mobile"}},
        ]
        result = await simulator.simulate(
            "send_notification",
            {"device": "mobile"},
            standing_order_actions=standing_order_actions,
        )
        assert not result.allowed
        assert any(c.name == "standing_order_conflict" and not c.passed for c in result.checks)

    @pytest.mark.asyncio
    async def test_same_action_different_entity_no_conflict(self, simulator):
        standing_order_actions = [
            {"action_name": "send_notification", "args": {"device": "desktop"}},
        ]
        result = await simulator.simulate(
            "send_notification",
            {"device": "mobile"},
            standing_order_actions=standing_order_actions,
        )
        conflict_checks = [c for c in result.checks if c.name == "standing_order_conflict"]
        assert len(conflict_checks) == 1
        assert conflict_checks[0].passed

    @pytest.mark.asyncio
    async def test_different_action_no_conflict(self, simulator):
        standing_order_actions = [
            {"action_name": "flag_conversation", "args": {"device": "mobile"}},
        ]
        result = await simulator.simulate(
            "send_notification",
            {"device": "mobile"},
            standing_order_actions=standing_order_actions,
        )
        conflict_checks = [c for c in result.checks if c.name == "standing_order_conflict"]
        assert len(conflict_checks) == 1
        assert conflict_checks[0].passed

    @pytest.mark.asyncio
    async def test_no_standing_orders(self, simulator):
        result = await simulator.simulate(
            "send_notification",
            {"device": "mobile"},
            standing_order_actions=[],
        )
        assert not any(c.name == "standing_order_conflict" for c in result.checks)
