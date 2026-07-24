"""
Tests for the SINGULAR_SARA_MASTER_PLAN §C7 body-capability registry:
upsert/list against a mocked AsyncSession, and that the heartbeat contract's
new `capabilities` field is genuinely additive (old payloads without it
still validate).
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.body_capability_service import list_capabilities, upsert_capability


class TestUpsertCapability:
    @pytest.mark.asyncio
    async def test_issues_upsert_with_json_encoded_fields(self):
        db = MagicMock()
        db.execute = AsyncMock()

        await upsert_capability(
            db, name="vm_workshop", kind="vm", version="0.3.0+abc12345",
            capabilities=["shell", "browser"], metadata={"hostname": "sara-vm"},
        )

        db.execute.assert_awaited_once()
        _, params = db.execute.call_args[0][0], db.execute.call_args[0][1]
        assert params["name"] == "vm_workshop"
        assert params["kind"] == "vm"
        assert json.loads(params["capabilities"]) == ["shell", "browser"]
        assert json.loads(params["metadata"]) == {"hostname": "sara-vm"}


class TestListCapabilities:
    @pytest.mark.asyncio
    async def test_computes_alive_flag_from_age(self):
        db = MagicMock()
        rows = [
            {"name": "vm_workshop", "kind": "vm", "version": "1.0", "capabilities": ["shell"],
             "capability_metadata": {}, "last_seen_at": None, "age_seconds": 30},
            {"name": "host:mac-studio", "kind": "managed_host", "version": None, "capabilities": [],
             "capability_metadata": {}, "last_seen_at": None, "age_seconds": 10_000},
        ]
        exec_result = MagicMock()
        exec_result.mappings.return_value.all.return_value = rows
        db.execute = AsyncMock(return_value=exec_result)

        result = await list_capabilities(db, stale_after_seconds=900)

        by_name = {r["name"]: r for r in result}
        assert by_name["vm_workshop"]["alive"] is True
        assert by_name["host:mac-studio"]["alive"] is False
        assert "age_seconds" not in by_name["vm_workshop"]


class TestHeartbeatContractBackwardCompat:
    def test_capabilities_field_defaults_when_absent(self):
        from app.routes.acs_daemon import HeartbeatIn
        from datetime import datetime, timezone

        payload = HeartbeatIn(
            state="idle", version="0.2.0", pid=123, hostname="sara-vm",
            started_at=datetime.now(timezone.utc),
        )
        assert payload.capabilities == []

    def test_capabilities_field_accepted_when_present(self):
        from app.routes.acs_daemon import HeartbeatIn
        from datetime import datetime, timezone

        payload = HeartbeatIn(
            state="idle", version="0.3.0", pid=123, hostname="sara-vm",
            started_at=datetime.now(timezone.utc),
            capabilities=["shell", "browser", "write_note"],
        )
        assert payload.capabilities == ["shell", "browser", "write_note"]
