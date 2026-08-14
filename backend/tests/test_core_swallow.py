"""
Tests for app/core/swallow.py — durable, cross-process silent-failure
telemetry (B2, docs/plans/HYGIENE_AND_STALE_CONTEXT_FIX_PLAN_2026_08_12.md).

swallow() must never itself raise (it wraps a fire-and-forget path — if
recording the failure could fail loudly, it defeats the purpose), must log
at DEBUG, and must increment a daily-bucketed Redis counter keyed by site.
"""
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.swallow import swallow, _KEY_PREFIX, _today


@pytest.fixture
def logger():
    return logging.getLogger("test.swallow")


class TestSwallow:
    @pytest.mark.asyncio
    async def test_increments_todays_redis_bucket(self, logger):
        mock_redis = AsyncMock()
        with patch("app.core.swallow.get_redis", new=AsyncMock(return_value=mock_redis)):
            await swallow(logger, "chat_stream.event_bus_emit", RuntimeError("boom"))

        expected_key = f"{_KEY_PREFIX}:chat_stream.event_bus_emit:{_today()}"
        mock_redis.incr.assert_awaited_once_with(expected_key)
        mock_redis.expire.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_never_raises_when_redis_unavailable(self, logger):
        with patch("app.core.swallow.get_redis", new=AsyncMock(side_effect=RuntimeError("redis down"))):
            await swallow(logger, "chat_stream.event_bus_emit", RuntimeError("boom"))  # must not raise

    @pytest.mark.asyncio
    async def test_logs_at_debug_not_higher(self, logger, caplog):
        mock_redis = AsyncMock()
        with patch("app.core.swallow.get_redis", new=AsyncMock(return_value=mock_redis)):
            with caplog.at_level(logging.DEBUG, logger="test.swallow"):
                await swallow(logger, "pkg_context_provider.query_semantic", ValueError("bad vector"))

        assert any(r.levelno == logging.DEBUG for r in caplog.records)
        assert not any(r.levelno > logging.DEBUG for r in caplog.records)
