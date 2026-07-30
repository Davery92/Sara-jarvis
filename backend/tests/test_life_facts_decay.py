"""
Tests for life_facts.decay_stale_life_facts() (Arc 5.2) — life_fact
confidence previously had no decay at all (upsert_life_fact's GREATEST()
only ever raises it). Mirrors PKG's decay_stale_knowledge shape, but scoped
to inferred facts only — a stated fact (David's own word) is law until he
changes it, decay would be wrong there, not just inconsistent.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.life_facts import AUTHORITY_INFERRED, decay_stale_life_facts


@pytest.fixture
def mock_db():
    db = MagicMock()
    mock_result = MagicMock(rowcount=0)
    db.execute = AsyncMock(return_value=mock_result)
    db.commit = AsyncMock()
    return db


class TestDecayStaleLifeFacts:
    @pytest.mark.asyncio
    async def test_scopes_query_to_inferred_authority_only(self, mock_db):
        await decay_stale_life_facts(mock_db, "user-1", days_threshold=90)

        mock_db.execute.assert_awaited_once()
        query_text = mock_db.execute.call_args[0][0].text
        params = mock_db.execute.call_args[0][1]
        assert "authority = :inferred" in query_text
        assert params["inferred"] == AUTHORITY_INFERRED
        assert params["uid"] == "user-1"
        assert params["days"] == 90

    @pytest.mark.asyncio
    async def test_commits_and_returns_decayed_count(self, mock_db):
        mock_db.execute = AsyncMock(return_value=MagicMock(rowcount=7))

        result = await decay_stale_life_facts(mock_db, "user-1")

        assert result == 7
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_zero_decayed_returns_zero(self, mock_db):
        result = await decay_stale_life_facts(mock_db, "user-1")
        assert result == 0

    @pytest.mark.asyncio
    async def test_custom_days_threshold_passed_through(self, mock_db):
        await decay_stale_life_facts(mock_db, "user-1", days_threshold=30)
        params = mock_db.execute.call_args[0][1]
        assert params["days"] == 30
