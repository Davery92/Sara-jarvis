"""
Tests for the SINGULAR_SARA_MASTER_PLAN §C7 `kernel.focused_turn()` — a real
kernel wrapper around the existing mission-dispatch pipeline
(agent_dispatch_service.dispatch_task), not a shadow probe: publishes
ENGAGED->FOCUSED kernel state and binds a correlation ID around the call
without changing dispatch_task's own behavior.
"""

from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from app.services import kernel


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


class TestFocusedTurn:
    @pytest.mark.asyncio
    async def test_calls_dispatch_task_unchanged_and_stamps_correlation(self, fake_redis_everywhere, monkeypatch):
        mock_service = MagicMock()
        mock_service.dispatch_task = AsyncMock(return_value={"task_id": "task-1", "status": "pending"})
        monkeypatch.setattr("app.services.agent_dispatch.agent_dispatch_service", mock_service)

        db = MagicMock()
        result = await kernel.focused_turn(
            db, "user-1", task_description="research something",
            mode="auto", working_directory="/tmp", notify_on_complete=True, target_host="mac-studio",
        )

        mock_service.dispatch_task.assert_awaited_once_with(
            db=db, user_id="user-1", task_description="research something",
            mode="auto", working_directory="/tmp", notify_on_complete=True, target_host="mac-studio",
        )
        assert result["task_id"] == "task-1"
        assert result["correlation_id"].startswith("turn_")

    @pytest.mark.asyncio
    async def test_records_target_path(self, fake_redis_everywhere, monkeypatch):
        mock_service = MagicMock()
        mock_service.dispatch_task = AsyncMock(return_value={"task_id": "task-2", "status": "pending"})
        monkeypatch.setattr("app.services.agent_dispatch.agent_dispatch_service", mock_service)

        db = MagicMock()
        await kernel.focused_turn(db, "user-1", task_description="x")

        from app.services.legacy_path_counters import get_counts
        counts = await get_counts("focused_cognition", days=1)
        assert counts["target"] == 1

    @pytest.mark.asyncio
    async def test_returns_to_ambient_even_when_dispatch_raises(self, fake_redis_everywhere, monkeypatch):
        mock_service = MagicMock()
        mock_service.dispatch_task = AsyncMock(side_effect=RuntimeError("VM unreachable"))
        monkeypatch.setattr("app.services.agent_dispatch.agent_dispatch_service", mock_service)

        db = MagicMock()
        with pytest.raises(RuntimeError):
            await kernel.focused_turn(db, "user-1", task_description="x")

        state = await kernel.get_state("user-1")
        assert state["detail"] == "resting"

    @pytest.mark.asyncio
    async def test_error_result_from_dispatch_still_returned(self, fake_redis_everywhere, monkeypatch):
        """dispatch_task returning {"status": "error", ...} (e.g. unknown
        target_host) is a normal result, not an exception — must pass through."""
        mock_service = MagicMock()
        mock_service.dispatch_task = AsyncMock(return_value={
            "task_id": None, "status": "error", "error": "No managed host named 'x'.",
        })
        monkeypatch.setattr("app.services.agent_dispatch.agent_dispatch_service", mock_service)

        db = MagicMock()
        result = await kernel.focused_turn(db, "user-1", task_description="x", target_host="x")

        assert result["status"] == "error"
        assert "correlation_id" in result
