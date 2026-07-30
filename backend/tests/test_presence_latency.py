"""
Tests for presence_latency.py (Arc 6.1, work-order item 6) — "the three-
speed contract, enforced." Timing assertions + red-line surfacing for
presence's <2s-to-first-token budget.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.services.presence_latency import (
    PRESENCE_BUDGET_SECONDS,
    get_presence_latency_status,
    record_first_token_latency,
)


def _mock_redis(recent_entries=None, breach=None):
    mock_r = AsyncMock()
    mock_r.lpush = AsyncMock()
    mock_r.ltrim = AsyncMock()
    mock_r.set = AsyncMock()
    mock_r.lrange = AsyncMock(return_value=recent_entries or [])
    mock_r.get = AsyncMock(return_value=breach)
    return mock_r


class TestRecordFirstTokenLatency:
    @pytest.mark.asyncio
    async def test_under_budget_does_not_set_breach(self):
        mock_r = _mock_redis()
        with patch("app.services.unified_context._get_redis", new=AsyncMock(return_value=mock_r)):
            await record_first_token_latency(1.2)

        mock_r.lpush.assert_awaited_once()
        mock_r.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_over_budget_sets_breach(self):
        mock_r = _mock_redis()
        with patch("app.services.unified_context._get_redis", new=AsyncMock(return_value=mock_r)):
            await record_first_token_latency(3.5)

        mock_r.set.assert_awaited_once()
        breach_payload = mock_r.set.call_args[0][1]
        assert '"elapsed": 3.5' in breach_payload

    @pytest.mark.asyncio
    async def test_redis_failure_does_not_raise(self):
        with patch("app.services.unified_context._get_redis", new=AsyncMock(side_effect=RuntimeError("down"))):
            await record_first_token_latency(1.0)  # must not raise


class TestGetPresenceLatencyStatus:
    @pytest.mark.asyncio
    async def test_no_samples_returns_empty_status(self):
        mock_r = _mock_redis()
        with patch("app.services.unified_context._get_redis", new=AsyncMock(return_value=mock_r)):
            status = await get_presence_latency_status()

        assert status["sample_count"] == 0
        assert status["p50"] is None
        assert status["red_line"] is False
        assert status["budget_seconds"] == PRESENCE_BUDGET_SECONDS

    @pytest.mark.asyncio
    async def test_computes_p50_from_samples(self):
        import json
        entries = [json.dumps({"at": f"t{i}", "elapsed": e}) for i, e in enumerate([1.0, 1.5, 2.0, 0.5, 1.2])]
        mock_r = _mock_redis(recent_entries=entries)
        with patch("app.services.unified_context._get_redis", new=AsyncMock(return_value=mock_r)):
            status = await get_presence_latency_status()

        assert status["sample_count"] == 5
        assert status["p50"] is not None

    @pytest.mark.asyncio
    async def test_recent_breach_within_window_is_reported(self):
        import json
        breach_entry = json.dumps({"at": "2026-07-30T10:00:00", "elapsed": 3.5})
        entries = [breach_entry, json.dumps({"at": "2026-07-30T09:00:00", "elapsed": 1.0})]
        breach_payload = json.dumps({"at": "2026-07-30T10:00:00", "elapsed": 3.5, "budget": 2.0})
        mock_r = _mock_redis(recent_entries=entries, breach=breach_payload)
        with patch("app.services.unified_context._get_redis", new=AsyncMock(return_value=mock_r)):
            status = await get_presence_latency_status()

        assert status["red_line"] is True
        assert status["last_breach"]["elapsed"] == 3.5

    @pytest.mark.asyncio
    async def test_aged_out_breach_is_not_reported(self):
        """A breach whose timestamp no longer appears in the trimmed
        recent-samples window must not read as a current red line."""
        import json
        entries = [json.dumps({"at": "2026-07-30T09:00:00", "elapsed": 1.0})]
        breach_payload = json.dumps({"at": "2026-07-25T10:00:00", "elapsed": 3.5, "budget": 2.0})
        mock_r = _mock_redis(recent_entries=entries, breach=breach_payload)
        with patch("app.services.unified_context._get_redis", new=AsyncMock(return_value=mock_r)):
            status = await get_presence_latency_status()

        assert status["red_line"] is False

    @pytest.mark.asyncio
    async def test_redis_failure_returns_safe_default(self):
        with patch("app.services.unified_context._get_redis", new=AsyncMock(side_effect=RuntimeError("down"))):
            status = await get_presence_latency_status()

        assert status["sample_count"] == 0
        assert status["red_line"] is False
