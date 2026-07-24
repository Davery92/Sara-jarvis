"""
Tests for the SINGULAR_SARA_MASTER_PLAN §C10 real-effect verification:
`StandingOrderService._verify_action_effect` — a read-only check that
`_run_action_once`'s bare "no exception was raised" success signal actually
matches the entity's real state, so `action_receipt` can say `partial`
instead of a false `completed`.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.standing_order_service import StandingOrderService

HA = "app.services.ha_control_service.ha_control"


@pytest.fixture
def service():
    return StandingOrderService()


class TestHomeControlVerification:
    @pytest.mark.asyncio
    async def test_lock_verified_true_when_state_matches(self, service):
        with patch(f"{HA}.get_state", new=AsyncMock(return_value={"state": "locked"})):
            result = await service._verify_action_effect(
                "home_control", {"service": "lock.lock", "entity_id": "lock.front_door"}
            )
        assert result is True

    @pytest.mark.asyncio
    async def test_lock_verified_false_when_state_does_not_match(self, service):
        with patch(f"{HA}.get_state", new=AsyncMock(return_value={"state": "unlocked"})):
            result = await service._verify_action_effect(
                "home_control", {"service": "lock.lock", "entity_id": "lock.front_door"}
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_turn_off_verified_against_off_state(self, service):
        with patch(f"{HA}.get_state", new=AsyncMock(return_value={"state": "off"})):
            result = await service._verify_action_effect(
                "home_control", {"service": "light.turn_off", "entity_id": "light.kitchen"}
            )
        assert result is True

    @pytest.mark.asyncio
    async def test_unrecognized_service_returns_none(self, service):
        result = await service._verify_action_effect(
            "home_control", {"service": "climate.set_temperature", "entity_id": "climate.hall"}
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_entity_id_returns_none(self, service):
        result = await service._verify_action_effect("home_control", {"service": "lock.lock"})
        assert result is None

    @pytest.mark.asyncio
    async def test_ha_error_fails_open_to_none_not_false(self, service):
        """A verification-check failure must never be recorded as proof the
        action failed — that would be a false negative on top of whatever
        real outcome happened."""
        with patch(f"{HA}.get_state", new=AsyncMock(side_effect=RuntimeError("HA down"))):
            result = await service._verify_action_effect(
                "home_control", {"service": "lock.lock", "entity_id": "lock.front_door"}
            )
        assert result is None


class TestAllLightsOffVerification:
    @pytest.mark.asyncio
    async def test_verified_true_when_no_lights_on(self, service):
        states = [
            {"entity_id": "light.kitchen", "state": "off"},
            {"entity_id": "light.hall", "state": "off"},
            {"entity_id": "lock.front_door", "state": "locked"},
        ]
        with patch(f"{HA}.get_states", new=AsyncMock(return_value=states)):
            result = await service._verify_action_effect("all_lights_off", {})
        assert result is True

    @pytest.mark.asyncio
    async def test_verified_false_when_a_light_is_still_on(self, service):
        states = [
            {"entity_id": "light.kitchen", "state": "on"},
            {"entity_id": "light.hall", "state": "off"},
        ]
        with patch(f"{HA}.get_states", new=AsyncMock(return_value=states)):
            result = await service._verify_action_effect("all_lights_off", {})
        assert result is False


class TestLockAllVerification:
    @pytest.mark.asyncio
    async def test_verified_false_when_a_lock_is_still_unlocked(self, service):
        states = [
            {"entity_id": "lock.front_door", "state": "locked"},
            {"entity_id": "lock.back_door", "state": "unlocked"},
        ]
        with patch(f"{HA}.get_states", new=AsyncMock(return_value=states)):
            result = await service._verify_action_effect("lock_all", {})
        assert result is False


class TestNonVerifiableActionTypes:
    @pytest.mark.asyncio
    async def test_notification_action_returns_none(self, service):
        result = await service._verify_action_effect("notification", {"title": "hi"})
        assert result is None
