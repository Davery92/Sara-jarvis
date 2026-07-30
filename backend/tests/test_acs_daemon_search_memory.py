"""
Tests for the ACS daemon's /search_memory route (Arc 5.1) — migrated from a
private pgvector query onto memory.recall(), the one door. `role` is the one
field the daemon's response model needs that a generic recall trace doesn't
carry for every kind, so memory_recall._trace grew an episode-only optional
`role` field for this.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.routes.acs_daemon_tools import search_memory, SearchMemoryIn


class TestAcsSearchMemory:
    @pytest.mark.asyncio
    async def test_maps_recall_traces_to_memory_hits(self):
        fake_result = {
            "query": "Risk Ninja", "paths": ["episode"],
            "traces": [
                {"kind": "episode", "id": "ep-1", "text": "Discussed pricing.",
                 "score": 0.72, "confidence": "observed", "provenance": "store:episode:chat",
                 "when": "2026-07-01T12:00:00", "role": "assistant"},
            ],
            "by_kind": {"episode": 1},
        }
        with patch("app.core.config.settings.acs_owner_user_id", "user-1"), \
             patch("app.services.memory_recall.recall", new=AsyncMock(return_value=fake_result)) as mock_recall:
            hits = await search_memory(SearchMemoryIn(query="Risk Ninja", limit=8))

        mock_recall.assert_awaited_once()
        assert mock_recall.call_args.kwargs["kinds"] == ["episode"]
        assert len(hits) == 1
        assert hits[0].id == "ep-1"
        assert hits[0].role == "assistant"
        assert hits[0].content == "Discussed pricing."
        assert hits[0].similarity == 0.72

    @pytest.mark.asyncio
    async def test_traces_with_empty_text_are_skipped(self):
        fake_result = {
            "query": "x", "paths": ["episode"],
            "traces": [{"kind": "episode", "id": "ep-2", "text": "", "score": 0.1,
                        "confidence": "observed", "provenance": "", "when": None, "role": None}],
            "by_kind": {"episode": 1},
        }
        with patch("app.core.config.settings.acs_owner_user_id", "user-1"), \
             patch("app.services.memory_recall.recall", new=AsyncMock(return_value=fake_result)):
            hits = await search_memory(SearchMemoryIn(query="xx", limit=8))
        assert hits == []

    @pytest.mark.asyncio
    async def test_no_owner_configured_raises_503(self):
        from fastapi import HTTPException
        with patch("app.core.config.settings.acs_owner_user_id", ""):
            with pytest.raises(HTTPException) as exc_info:
                await search_memory(SearchMemoryIn(query="xx", limit=8))
        assert exc_info.value.status_code == 503
