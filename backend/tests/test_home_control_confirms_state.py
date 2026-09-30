"""Accepted is not confirmed — reliable-assistant plan Phase F, home row.

*"Verify actual device outcome where observable; distinguish accepted command
from confirmed state."*

Finding 21 (`M02_STALE_LOCK_FALSE_SUCCESS_CLAIM`): a lock command reported
success — "Locked... the unavailable state seems to have cleared" — against a
device the adapter's own response explicitly marked
`device_unavailable_no_state_change`. Source-confirmed at the time:
`ha_control_service` returned `{"success": True}` on the strength of the HTTP
call alone and never read the entity state back, for every device on the path.
"""
import pytest

from app.services.ha_control_service import HAControlService


class FakeHA(HAControlService):
    """Records the calls and answers state reads from a script."""

    def __init__(self, states):
        # Deliberately does not call super().__init__ — no settings, no session.
        self.base_url = "http://ha.invalid/api"
        self.headers = {}
        self.calls = []
        self._states = states
        self.state_reads = 0
        self._CONFIRM_DELAY_S = 0  # no sleeping in tests

    async def call_service(self, domain, service, entity_id=None, **kwargs):
        self.calls.append((domain, service, entity_id, kwargs))
        return []

    async def get_state(self, entity_id):
        self.state_reads += 1
        value = self._states
        if callable(value):
            value = value(self.state_reads)
        return {"entity_id": entity_id, "state": value}


class RaisingHA(FakeHA):
    async def get_state(self, entity_id):
        self.state_reads += 1
        raise RuntimeError("HA API error 503")


class TestTheFindingItself:
    @pytest.mark.asyncio
    async def test_a_lock_that_does_not_move_is_not_a_success(self):
        ha = FakeHA("unavailable")
        result = await ha.lock("lock.side_door")
        assert result["accepted"] is True
        assert result["confirmed"] is False
        assert result["success"] is False, (
            "reporting an unmoved lock as success IS finding 21"
        )
        assert "did not move" in result["detail"]
        assert result["observed_state"] == "unavailable"

    @pytest.mark.asyncio
    async def test_a_lock_that_does_move_is_a_success(self):
        ha = FakeHA("locked")
        result = await ha.lock("lock.side_door")
        assert result["success"] is True
        assert result["confirmed"] is True
        assert result["observed_state"] == "locked"

    @pytest.mark.asyncio
    async def test_the_command_is_still_actually_sent(self):
        ha = FakeHA("locked")
        await ha.lock("lock.side_door")
        assert ha.calls == [("lock", "lock", "lock.side_door", {})]


class TestEveryObservableDevice:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,args,good,bad", [
        ("turn_on_light", ("light.desk",), "on", "off"),
        ("turn_off_light", ("light.desk",), "off", "on"),
        ("turn_on_switch", ("switch.fan",), "on", "off"),
        ("turn_off_switch", ("switch.fan",), "off", "on"),
        ("lock", ("lock.door",), "locked", "unlocked"),
        ("unlock", ("lock.door",), "unlocked", "locked"),
        ("open_cover", ("cover.blind",), "open", "closed"),
        ("close_cover", ("cover.blind",), "closed", "open"),
    ])
    async def test_confirmed_and_unconfirmed(self, method, args, good, bad):
        good_result = await getattr(FakeHA(good), method)(*args)
        assert good_result["success"] is True, method
        assert good_result["confirmed"] is True, method

        bad_result = await getattr(FakeHA(bad), method)(*args)
        assert bad_result["success"] is False, method
        assert bad_result["confirmed"] is False, method
        assert bad_result["accepted"] is True, method


class TestEventualConsistency:
    @pytest.mark.asyncio
    async def test_a_state_that_catches_up_on_the_second_read_is_confirmed(self):
        """HA's state machine can lag a service call; a single read would
        report a working device as stuck."""
        ha = FakeHA(lambda attempt: "unlocked" if attempt == 1 else "locked")
        result = await ha.lock("lock.door")
        assert result["success"] is True
        assert ha.state_reads == 2

    @pytest.mark.asyncio
    async def test_an_unavailable_device_is_not_retried(self):
        """A device reporting nothing at all will not report something else a
        moment later — retrying only delays the honest answer."""
        ha = FakeHA("unavailable")
        await ha.lock("lock.door")
        assert ha.state_reads == 1

    @pytest.mark.asyncio
    async def test_retries_are_bounded(self):
        ha = FakeHA("unlocked")
        await ha.lock("lock.door")
        assert ha.state_reads == HAControlService._CONFIRM_ATTEMPTS


class TestUnreadableState:
    @pytest.mark.asyncio
    async def test_a_failed_readback_does_not_become_a_failed_command(self):
        """If the state cannot be read at all, the command was still accepted
        and we simply do not know — which is a different answer from "the
        device did not move", and the reply must be able to tell them apart."""
        ha = RaisingHA("locked")
        result = await ha.lock("lock.door")
        assert result["accepted"] is True
        assert result["confirmed"] is False
        assert result["success"] is True, (
            "an unreadable state is 'unknown', not 'it failed' — the turn "
            "ledger renders UNKNOWN for this, not FAILED"
        )
        assert "could not read" in result["detail"]
