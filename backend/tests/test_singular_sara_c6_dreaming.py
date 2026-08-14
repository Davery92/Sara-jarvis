"""
Tests for the SINGULAR_SARA_MASTER_PLAN §C6 `kernel.dreaming_turn()` and its
fold-in to `app.tasks.reflection._run_reflection_async`.

Arc 3 write-freeze (2026-07-29): the legacy `get_reflection_agent()` branch
(used pre-SINGULAR_KERNEL, or when the flag was off) was deleted after
`legacy_path_counters` confirmed 0 legacy calls / 16 kernel calls over a
3-day live window — see ARC3_JOB_INVENTORY_2026_07_29.md. There is no longer
a flag-off code path to test.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from app.services import kernel
from app.tasks import reflection


@pytest.fixture
def fake_redis_everywhere(monkeypatch):
    import app.services.legacy_path_counters as counters

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _fake_redis():
        return fake

    import app.core.redis as core_redis
    monkeypatch.setattr(core_redis, "get_redis", _fake_redis)
    monkeypatch.setattr(counters, "_get_redis", _fake_redis)
    return fake


class TestDreamingTurn:
    @pytest.mark.asyncio
    async def test_wraps_reflection_agent_and_records_target_path(self, fake_redis_everywhere):
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"patterns_found": 3, "proposals": 1}

        mock_agent = AsyncMock()
        mock_agent.run_reflection_cycle = AsyncMock(return_value=mock_result)

        mock_db_ctx = MagicMock()
        mock_db_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_db_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.session.get_async_session_factory", return_value=lambda: mock_db_ctx), \
             patch("app.services.reflection.agent.get_reflection_agent", new=AsyncMock(return_value=mock_agent)):

            result = await kernel.dreaming_turn("user-1")

        assert result["state"] == "dreaming"
        assert result["patterns_found"] == 3
        assert result["proposals"] == 1
        assert result["correlation_id"].startswith("turn_")

        from app.services.legacy_path_counters import get_counts
        counts = await get_counts("dreaming_cognition", days=1)
        assert counts["target"] == 1


class TestReflectionFoldIn:
    @pytest.mark.asyncio
    async def test_routes_through_kernel(self):
        fake_kernel_result = {"state": "dreaming", "correlation_id": "turn_xyz", "patterns_found": 5}

        with patch("app.services.kernel.dreaming_turn", new=AsyncMock(return_value=fake_kernel_result)) as mock_dt, \
             patch("app.core.config.settings") as mock_settings:
            mock_settings.autonomy_policy_candidates_enabled = False

            result = await reflection._run_reflection_async()

        mock_dt.assert_awaited_once()
        assert result["patterns_found"] == 5
        assert result["correlation_id"] == "turn_xyz"
