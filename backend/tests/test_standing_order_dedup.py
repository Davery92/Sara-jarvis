"""
Tests for standing order dedup between PLAN and EXECUTE phases.

Scenarios:
- Standing order fires in PLAN, same action in LLM plan → skipped in EXECUTE
- Different entity → not skipped

Uses non-HA actions (send_notification) to avoid entity existence checks
that would require a live HA connection.
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.services.autonomy.action_simulator import ActionSimulator

HA_CONTROL_PATH = "app.services.ha_control_service.ha_control"


@pytest.fixture
def simulator():
    return ActionSimulator()


class TestStandingOrderDedup:
    """
    In the 6-phase cycle, standing orders execute deterministically in the PLAN phase
    BEFORE the LLM loop. When the LLM then plans the same action on the same entity,
    the SIMULATE phase's standing_order_conflict check catches it and prevents duplicate
    execution in EXECUTE.

    Uses send_notification (Tier 1, non-HA) to isolate the conflict check from entity checks.
    """

    @pytest.mark.asyncio
    async def test_same_action_same_entity_skipped(self, simulator):
        """
        Standing order already sent notification → LLM plans the same → blocked.
        """
        standing_order_actions = [
            {
                "action_name": "send_notification",
                "args": {"device": "mobile", "message": "Hello"},
            },
        ]
        result = await simulator.simulate(
            "send_notification",
            {"device": "mobile", "message": "Hello"},
            standing_order_actions=standing_order_actions,
        )
        assert not result.allowed
        assert "standing order" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_same_action_different_entity_not_skipped(self, simulator):
        """
        Standing order sent to mobile → LLM plans to desktop → allowed.
        """
        standing_order_actions = [
            {
                "action_name": "send_notification",
                "args": {"device": "mobile"},
            },
        ]
        result = await simulator.simulate(
            "send_notification",
            {"device": "desktop"},
            standing_order_actions=standing_order_actions,
        )
        conflict_checks = [c for c in result.checks if c.name == "standing_order_conflict"]
        assert len(conflict_checks) == 1
        assert conflict_checks[0].passed  # Different device, no conflict

    @pytest.mark.asyncio
    async def test_different_action_same_entity_not_skipped(self, simulator):
        """
        Standing order used flag_conversation → LLM plans send_notification → allowed.
        Different action_name means no conflict.
        """
        standing_order_actions = [
            {
                "action_name": "flag_conversation",
                "args": {"device": "mobile"},
            },
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
    async def test_multiple_standing_orders_one_conflict(self, simulator):
        """Multiple standing orders, only one conflicts."""
        standing_order_actions = [
            {"action_name": "flag_conversation", "args": {"device": "desktop"}},
            {"action_name": "send_notification", "args": {"device": "mobile"}},
        ]
        result = await simulator.simulate(
            "send_notification",
            {"device": "mobile"},
            standing_order_actions=standing_order_actions,
        )
        assert not result.allowed
        assert "standing order" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_standing_order_no_entity_conflicts_any(self, simulator):
        """
        Standing order that doesn't specify entity conflicts with any entity
        for the same action.
        """
        standing_order_actions = [
            {"action_name": "send_notification", "args": {}},
        ]
        result = await simulator.simulate(
            "send_notification",
            {"device": "mobile"},
            standing_order_actions=standing_order_actions,
        )
        assert not result.allowed

    @pytest.mark.asyncio
    async def test_no_standing_orders_always_passes(self, simulator):
        """No standing orders → no conflict possible."""
        result = await simulator.simulate(
            "send_notification",
            {"device": "mobile"},
            standing_order_actions=[],
        )
        # No conflict check should even appear
        assert not any(c.name == "standing_order_conflict" for c in result.checks)

    @pytest.mark.asyncio
    async def test_ha_action_with_mock_entity_check(self, simulator):
        """
        Verify standing order conflict works for HA actions too
        (with mocked entity check so it doesn't fail on HA unavailable).
        """
        with patch(HA_CONTROL_PATH) as mock_ha:
            mock_ha.get_entity_state = AsyncMock(return_value={"state": "on"})
            standing_order_actions = [
                {"action_name": "home_light_control", "args": {"entity_id": "light.office"}},
            ]
            result = await simulator.simulate(
                "home_light_control",
                {"entity_id": "light.office"},
                standing_order_actions=standing_order_actions,
            )
        assert not result.allowed
        assert "standing order" in result.reason.lower()
