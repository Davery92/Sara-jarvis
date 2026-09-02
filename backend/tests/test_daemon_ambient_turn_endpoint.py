"""
Tests for the Arc 3.3 backend half of daemon retirement: `POST
/api/acs/v2/ambient-turn`, the endpoint the VM daemon's tick will call
instead of running its own `mind.think()`/`mind.reflect()` once wired.

NOT the cutover itself — `acs-daemon/daemon.py` on the live sara-VM is
unchanged and doesn't call this yet (that's a coordinated remote deploy,
held for explicit sign-off). This only verifies the backend side: the route
proxies to `kernel.ambient_turn(wake_reason=DAEMON_PROXY)` and maps its
result honestly into the daemon-consumable `produced` signal.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.routes.acs_daemon import AmbientTurnIn, daemon_ambient_turn


class TestDaemonAmbientTurnEndpoint:
    @pytest.mark.asyncio
    async def test_routes_through_kernel_with_daemon_proxy_wake_reason(self):
        fake_result = {
            "status": "completed", "state": "ambient", "wake_reason": "daemon_proxy",
            "notifications": 1, "home_actions": 0, "tasks_dispatched": 0,
            "tasks_proposed": 0, "correlation_id": "turn_abc",
        }
        mock_ambient_turn = AsyncMock(return_value=fake_result)

        with patch("app.services.kernel.ambient_turn", mock_ambient_turn):
            out = await daemon_ambient_turn(AmbientTurnIn(world_delta=["David got home"]))

        mock_ambient_turn.assert_awaited_once()
        args, kwargs = mock_ambient_turn.call_args
        assert kwargs["wake_reason"].value == "daemon_proxy"
        # Ground-truth plan, Phase 8 §1: the proxy does NOT force. `force=True`
        # skipped should_deliberate entirely, so every daemon tick became a
        # deliberation whether or not anything had happened — the single largest
        # contributor to ~140 deliberations a day, 1-5 AM included. The daemon
        # keeps its cadence; whether there is anything worth thinking about is
        # the kernel's call.
        assert kwargs["force"] is False
        assert out.status == "completed"
        assert out.produced is True  # 1 notification sent
        assert out.correlation_id == "turn_abc"

    @pytest.mark.asyncio
    async def test_produced_is_false_when_the_turn_did_nothing(self):
        fake_result = {
            "status": "completed", "state": "ambient", "wake_reason": "daemon_proxy",
            "notifications": 0, "home_actions": 0, "tasks_dispatched": 0,
            "tasks_proposed": 0, "correlation_id": "turn_xyz",
        }
        with patch("app.services.kernel.ambient_turn", new=AsyncMock(return_value=fake_result)):
            out = await daemon_ambient_turn(AmbientTurnIn())

        assert out.produced is False

    @pytest.mark.asyncio
    async def test_skipped_turn_maps_to_a_readable_status(self):
        fake_result = {"skipped": "below_threshold", "state": "ambient", "correlation_id": "turn_skip"}
        with patch("app.services.kernel.ambient_turn", new=AsyncMock(return_value=fake_result)):
            out = await daemon_ambient_turn(AmbientTurnIn())

        assert out.status == "below_threshold"
        assert out.produced is False
