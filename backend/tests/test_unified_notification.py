"""
Tests for Unified Notification Pipeline — dedup, delivery routing, and logging.

Uses patched internal functions to avoid needing a real database.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.unified_notification import (
    send_notification,
    send_consolidated_notification,
    DEFAULT_COOLDOWNS,
)


@pytest.fixture
def patch_dedup_and_push():
    """Context manager that patches _check_dedup, _log_notification, _get_push_tokens, _send_push, and command_router."""
    with patch("app.services.unified_notification._check_dedup", new_callable=AsyncMock) as mock_dedup, \
         patch("app.services.unified_notification._log_notification", new_callable=AsyncMock) as mock_log, \
         patch("app.services.unified_notification._get_push_tokens", new_callable=AsyncMock) as mock_tokens, \
         patch("app.services.unified_notification._send_push", new_callable=AsyncMock) as mock_push, \
         patch("app.services.unified_notification.command_router", create=True) as mock_cmd:
        mock_cmd.get_connected_devices = MagicMock(return_value=[])
        mock_log.return_value = "notif-log-id"
        yield {
            "dedup": mock_dedup,
            "log": mock_log,
            "tokens": mock_tokens,
            "push": mock_push,
            "cmd": mock_cmd,
        }


class TestDedupLogic:
    @pytest.mark.asyncio
    async def test_dedup_blocks_recent_same_topic(self, patch_dedup_and_push):
        """Same topic within cooldown → blocked."""
        mocks = patch_dedup_and_push
        mocks["dedup"].return_value = True  # Is a duplicate

        db = AsyncMock()
        result = await send_notification(
            user_id="test-user", title="Weather", message="Rain",
            topic="weather:rain", category="weather", db=db,
        )
        assert result["sent"] is False
        assert result["reason"] == "dedup"

    @pytest.mark.asyncio
    async def test_dedup_allows_after_cooldown(self, patch_dedup_and_push):
        """Not a duplicate → sends."""
        mocks = patch_dedup_and_push
        mocks["dedup"].return_value = False
        mocks["tokens"].return_value = ["PushToken[test]"]
        mocks["push"].return_value = True

        db = AsyncMock()
        result = await send_notification(
            user_id="test-user", title="New", message="Thing",
            topic="new:topic", category="general", db=db,
        )
        assert result["sent"] is True

    @pytest.mark.asyncio
    async def test_dedup_different_topics_allowed(self, patch_dedup_and_push):
        """Two different topics should both be allowed."""
        mocks = patch_dedup_and_push
        mocks["dedup"].return_value = False
        mocks["tokens"].return_value = ["PushToken[test]"]
        mocks["push"].return_value = True

        db = AsyncMock()
        r1 = await send_notification(
            user_id="test-user", title="Weather", message="Rain",
            topic="weather:1", category="weather", db=db,
        )
        r2 = await send_notification(
            user_id="test-user", title="Calendar", message="Meeting",
            topic="calendar:1", category="calendar", db=db,
        )
        assert r1["sent"] is True
        assert r2["sent"] is True


class TestNoTokens:
    @pytest.mark.asyncio
    async def test_handles_no_push_tokens(self, patch_dedup_and_push):
        """No tokens and no desktop → graceful skip."""
        mocks = patch_dedup_and_push
        mocks["dedup"].return_value = False
        mocks["tokens"].return_value = []  # No push tokens

        db = AsyncMock()
        result = await send_notification(
            user_id="test-user", title="Test", message="Msg",
            topic="test:1", category="general", db=db,
        )
        assert result["sent"] is False
        assert result["reason"] == "no_tokens"


class TestConsolidatedNotification:
    @pytest.mark.asyncio
    async def test_consolidated_single(self, patch_dedup_and_push):
        """Single notification → sends directly."""
        mocks = patch_dedup_and_push
        mocks["dedup"].return_value = False
        mocks["tokens"].return_value = ["token1"]
        mocks["push"].return_value = True

        db = AsyncMock()
        notifications = [{"title": "Test", "message": "Body", "priority": "normal", "category": "general"}]
        result = await send_consolidated_notification(
            user_id="test-user", notifications=notifications, db=db,
        )
        assert result["sent"] is True
        assert result.get("consolidated_count", 1) == 1

    @pytest.mark.asyncio
    async def test_consolidated_multiple(self, patch_dedup_and_push):
        """Multiple notifications → batched into one push."""
        mocks = patch_dedup_and_push
        mocks["dedup"].return_value = False
        mocks["tokens"].return_value = ["token1"]
        mocks["push"].return_value = True

        db = AsyncMock()
        notifications = [
            {"title": f"Item {i}", "message": f"Body {i}", "priority": "normal", "category": "general"}
            for i in range(3)
        ]
        result = await send_consolidated_notification(
            user_id="test-user", notifications=notifications, db=db,
        )
        assert result["sent"] is True
        assert result["consolidated_count"] == 3

    @pytest.mark.asyncio
    async def test_consolidated_empty(self):
        """Empty list → no send."""
        result = await send_consolidated_notification(
            user_id="test-user", notifications=[],
        )
        assert result["sent"] is False
        assert result["reason"] == "empty_queue"

    @pytest.mark.asyncio
    async def test_consolidated_all_deduped(self, patch_dedup_and_push):
        """All notifications blocked by dedup → no send."""
        mocks = patch_dedup_and_push
        mocks["dedup"].return_value = True  # All are duplicates

        db = AsyncMock()
        notifications = [{"title": "Dup", "message": "Body", "priority": "normal",
                          "category": "general", "topic": "same:topic"}]
        result = await send_consolidated_notification(
            user_id="test-user", notifications=notifications, db=db,
        )
        assert result["sent"] is False
        assert result["reason"] == "all_deduped"


class TestCooldownDefaults:
    def test_category_specific_cooldowns(self):
        assert DEFAULT_COOLDOWNS["calendar"] == 24.0
        assert DEFAULT_COOLDOWNS["weather"] == 8.0
        assert DEFAULT_COOLDOWNS["security"] == 0.0
        assert DEFAULT_COOLDOWNS["reminder"] == 0.0
        assert DEFAULT_COOLDOWNS["checkin"] == 4.0


class TestDesktopFirst:
    @pytest.mark.asyncio
    async def test_desktop_websocket_tried_first(self, patch_dedup_and_push):
        """Desktop delivery is attempted before push."""
        mocks = patch_dedup_and_push
        mocks["dedup"].return_value = False
        mocks["tokens"].return_value = ["token1"]
        mocks["push"].return_value = True

        # Simulate desktop delivery success
        mock_ws_result = AsyncMock(return_value=True)
        mocks["cmd"].get_connected_devices = MagicMock(return_value=["desktop-1"])
        # The command_router.send_command is called
        mocks["cmd"].send_command = mock_ws_result

        db = AsyncMock()
        result = await send_notification(
            user_id="test-user", title="Test", message="Msg",
            topic="test:desktop", category="general", db=db,
        )
        assert result["sent"] is True

    @pytest.mark.asyncio
    async def test_fallback_to_push(self, patch_dedup_and_push):
        """Desktop fails → push notification sent."""
        mocks = patch_dedup_and_push
        mocks["dedup"].return_value = False
        mocks["tokens"].return_value = ["token1"]
        mocks["push"].return_value = True

        db = AsyncMock()
        result = await send_notification(
            user_id="test-user", title="Test", message="Msg",
            topic="test:fallback", category="general", db=db,
        )
        assert result["sent"] is True
        # Push should have been called since no desktop connection
        mocks["push"].assert_called_once()
