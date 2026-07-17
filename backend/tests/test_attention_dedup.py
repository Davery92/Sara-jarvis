"""
Tests for attention queue dedup (Phase 2 — Cortana Evolution).

Since AttentionQueueService uses raw SQL with AsyncSession (PostgreSQL-specific),
these tests mock the DB layer to verify the dedup logic.

Scenarios:
- Same dedupe_key → returns existing id (INSERT ON CONFLICT DO NOTHING)
- Different key → new item
- NULL key → always inserts
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.autonomy.attention_queue import AttentionQueueService


@pytest.fixture
def queue():
    return AttentionQueueService()


def _mock_db_insert_returning(item_id: str):
    """Mock DB that returns an ID on INSERT."""
    db = AsyncMock()
    row = MagicMock()
    row.__getitem__ = MagicMock(return_value=item_id)
    result = MagicMock()
    result.fetchone.return_value = row
    db.execute = AsyncMock(return_value=result)
    return db


def _mock_db_dedup_conflict(existing_id: str):
    """Mock DB that returns None on INSERT (conflict) then finds existing."""
    db = AsyncMock()

    # First call: INSERT returns None (ON CONFLICT DO NOTHING)
    insert_result = MagicMock()
    insert_result.fetchone.return_value = None

    # Second call: SELECT returns existing ID
    select_row = MagicMock()
    select_row.__getitem__ = MagicMock(return_value=existing_id)
    select_result = MagicMock()
    select_result.fetchone.return_value = select_row

    db.execute = AsyncMock(side_effect=[insert_result, select_result])
    return db


def _mock_db_insert_no_dedup():
    """Mock DB that returns None on both INSERT and SELECT (no dedup, NULL key)."""
    db = AsyncMock()
    insert_result = MagicMock()
    insert_result.fetchone.return_value = None
    db.execute = AsyncMock(return_value=insert_result)
    return db


class TestAttentionDedup:
    """Test dedup behavior of create_item."""

    @pytest.mark.asyncio
    async def test_new_item_with_dedupe_key(self, queue):
        """New item with dedupe_key returns new ID."""
        new_id = "abc-123"
        db = _mock_db_insert_returning(new_id)

        result = await queue.create_item(
            db, user_id="user-1", title="Test",
            dedupe_key="unique-key", priority="normal",
        )
        assert result == new_id
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_duplicate_dedupe_key_returns_existing(self, queue):
        """Same dedupe_key in active status → returns existing item ID."""
        existing_id = "existing-456"
        db = _mock_db_dedup_conflict(existing_id)

        result = await queue.create_item(
            db, user_id="user-1", title="Test",
            dedupe_key="already-exists", priority="normal",
        )
        assert result == existing_id
        # Two calls: INSERT (conflict) + SELECT
        assert db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_null_dedupe_key_always_inserts(self, queue):
        """NULL dedupe_key always creates a new item (no conflict possible)."""
        new_id = "new-789"
        db = _mock_db_insert_returning(new_id)

        result = await queue.create_item(
            db, user_id="user-1", title="Test 1",
            dedupe_key=None, priority="normal",
        )
        assert result == new_id

    @pytest.mark.asyncio
    async def test_null_dedupe_key_no_select_fallback(self, queue):
        """When dedupe_key is None and INSERT returns None, no SELECT follows."""
        db = AsyncMock()
        insert_result = MagicMock()
        insert_result.fetchone.return_value = None
        db.execute = AsyncMock(return_value=insert_result)

        result = await queue.create_item(
            db, user_id="user-1", title="Test",
            dedupe_key=None, priority="low",
        )
        # Should return None — no second query because dedupe_key is None
        assert result is None
        assert db.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_different_dedupe_keys_create_separate_items(self, queue):
        """Different dedupe keys create separate items."""
        db1 = _mock_db_insert_returning("id-1")
        db2 = _mock_db_insert_returning("id-2")

        result1 = await queue.create_item(
            db1, user_id="user-1", title="Item A", dedupe_key="key-a",
        )
        result2 = await queue.create_item(
            db2, user_id="user-1", title="Item B", dedupe_key="key-b",
        )
        assert result1 == "id-1"
        assert result2 == "id-2"

    @pytest.mark.asyncio
    async def test_db_error_returns_none(self, queue):
        """DB errors should return None, not raise."""
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("Connection lost"))

        result = await queue.create_item(
            db, user_id="user-1", title="Test", dedupe_key="key",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_payload_passed_through(self, queue):
        """Verify payload dict gets serialized and passed to the query."""
        db = _mock_db_insert_returning("new-id")
        payload = {"run_uuid": "abc-123", "action_name": "test"}

        result = await queue.create_item(
            db, user_id="user-1", title="Test",
            dedupe_key="key", payload=payload,
        )
        assert result == "new-id"
        # Verify execute was called with params containing the payload
        call_args = db.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
        if isinstance(params, dict):
            import json
            assert "payload" in params
            parsed = json.loads(params["payload"])
            assert parsed["run_uuid"] == "abc-123"

    @pytest.mark.asyncio
    async def test_priority_values(self, queue):
        """Various priority values should work."""
        for priority in ["low", "normal", "high", "urgent", "critical"]:
            db = _mock_db_insert_returning(f"id-{priority}")
            result = await queue.create_item(
                db, user_id="user-1", title=f"Test {priority}",
                priority=priority, dedupe_key=f"key-{priority}",
            )
            assert result == f"id-{priority}"
