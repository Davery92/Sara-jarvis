"""
Tests for memory_recall.py's fact-kind handling (Arc 5.1) — the recall-door
migration found that `_from_facts` returned empty text for virtually every
real PKG fact (query_semantic() merges full Neo4j node properties into each
row, not a `content_text` key, which only exists in the Neo4j-unavailable
fallback branch) before any of pkg_context_provider's live callers could be
safely routed through here. These tests lock in the fix and the new
query-free "top confidence" path + the shared prose formatter.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.memory_recall import _fact_text, _from_facts, _from_search_memory, recall_facts_prose


class TestFactText:
    def test_routine_type_formats_via_pkg_context_provider(self):
        row = {"type": "Routine", "activity": "logs meals", "day_of_week": "any",
               "typical_time": "morning", "frequency": "daily"}
        text = _fact_text(row)
        assert "logs meals" in text
        assert text != ""

    def test_falls_back_to_value_when_formatter_returns_bare_david(self):
        """A Routine row with no `activity` (e.g. consolidation-sourced,
        carries `value` instead) — _fact_to_sentence produces just 'David '
        (stripped: 'David'), which must not be treated as real text."""
        row = {"type": "Routine", "value": "David sometimes multitasks during meetings."}
        text = _fact_text(row)
        assert text == "David sometimes multitasks during meetings."

    def test_falls_back_to_description_when_no_value(self):
        row = {"type": "Routine", "description": "Recurring event on Mondays."}
        text = _fact_text(row)
        assert text == "Recurring event on Mondays."

    def test_unknown_fact_type_falls_back_to_content_text(self):
        row = {"type": "SomethingNew", "content_text": "a raw fallback string"}
        text = _fact_text(row)
        assert text == "a raw fallback string"

    def test_completely_empty_row_returns_empty_string(self):
        assert _fact_text({"type": "Unknown"}) == ""


class TestFromFacts:
    @pytest.mark.asyncio
    async def test_real_query_uses_semantic_search(self):
        with patch("app.services.personal_knowledge_graph.personal_kg.query_semantic",
                   new=AsyncMock(return_value=[
                       {"type": "Preference", "value": "espresso", "domain": "coffee",
                        "strength": "love", "confidence": 0.9, "similarity": 0.7, "pkg_id": "p1"},
                   ])) as mock_semantic, \
             patch("app.services.personal_knowledge_graph.personal_kg.query_top_confidence",
                   new=AsyncMock(return_value=[])) as mock_top:
            traces = await _from_facts("coffee", 8)

        mock_semantic.assert_awaited_once()
        mock_top.assert_not_awaited()
        assert len(traces) == 1
        assert "espresso" in traces[0]["text"]
        assert traces[0]["confidence"] == "confirmed"  # 0.9 >= 0.75

    @pytest.mark.asyncio
    async def test_empty_query_uses_top_confidence_browse(self):
        """No message to embed/compare against — e.g. a context-free brief
        summary request — must not call query_semantic (which would embed
        an empty string and return near-arbitrary results)."""
        with patch("app.services.personal_knowledge_graph.personal_kg.query_semantic",
                   new=AsyncMock(return_value=[])) as mock_semantic, \
             patch("app.services.personal_knowledge_graph.personal_kg.query_top_confidence",
                   new=AsyncMock(return_value=[
                       {"type": "Goal", "description": "Ship Arc 5", "status": "active",
                        "confidence": 0.95, "similarity": 0.95, "pkg_id": "p2"},
                   ])) as mock_top:
            traces = await _from_facts("", 8)

        mock_semantic.assert_not_awaited()
        mock_top.assert_awaited_once()
        assert len(traces) == 1
        assert "Ship Arc 5" in traces[0]["text"]

    @pytest.mark.asyncio
    async def test_source_failure_returns_empty_not_raises(self):
        with patch("app.services.personal_knowledge_graph.personal_kg.query_semantic",
                   new=AsyncMock(side_effect=RuntimeError("neo4j down"))):
            traces = await _from_facts("coffee", 8)
        assert traces == []


class TestRecallFactsProse:
    @pytest.mark.asyncio
    async def test_renders_header_and_bullets_with_confidence_tier(self):
        fake_result = {
            "query": "coffee", "paths": ["fact"],
            "traces": [
                {"kind": "fact", "text": "David loves espresso", "confidence": "confirmed", "score": 0.8},
                {"kind": "fact", "text": "", "confidence": "observed", "score": 0.1},  # must be skipped
            ],
            "by_kind": {"fact": 2},
        }
        with patch("app.services.memory_recall.recall", new=AsyncMock(return_value=fake_result)):
            prose = await recall_facts_prose(query="coffee")

        assert "What Sara Knows About David" in prose
        assert "David loves espresso (confirmed)" in prose
        assert prose.count("- ") == 1  # the empty-text trace was skipped

    @pytest.mark.asyncio
    async def test_no_facts_returns_empty_string(self):
        fake_result = {"query": "", "paths": ["fact"], "traces": [], "by_kind": {}}
        with patch("app.services.memory_recall.recall", new=AsyncMock(return_value=fake_result)):
            prose = await recall_facts_prose(query="")
        assert prose == ""


class TestEpisodeConfidenceTier:
    """Arc 5.2: episode traces used to always report a hardcoded 'observed'
    tier regardless of the episode's actual importance score — not a real
    graduated scale. Now the real importance (exposed by memory_service.
    search_memory as of this change) grades through the same shared
    confidence_ladder every other kind uses."""

    @pytest.mark.asyncio
    async def test_high_importance_episode_grades_confirmed(self):
        with patch("app.services.memory_service.get_memory_service") as mock_get_svc, \
             patch("app.services.memory_recall._strengthen_recalled_episodes", new=AsyncMock()):
            mock_svc = MagicMock()
            mock_svc.SessionLocal = MagicMock()
            mock_svc.search_memory = AsyncMock(return_value=[
                {"type": "episode", "episode_id": "ep-1", "text": "important thing",
                 "score": 0.6, "importance": 0.9},
            ])
            mock_get_svc.return_value = mock_svc

            traces = await _from_search_memory("user-1", "q", ["episode"], 5)

        assert traces[0]["confidence"] == "confirmed"

    @pytest.mark.asyncio
    async def test_low_importance_episode_grades_observed(self):
        with patch("app.services.memory_service.get_memory_service") as mock_get_svc, \
             patch("app.services.memory_recall._strengthen_recalled_episodes", new=AsyncMock()):
            mock_svc = MagicMock()
            mock_svc.SessionLocal = MagicMock()
            mock_svc.search_memory = AsyncMock(return_value=[
                {"type": "episode", "episode_id": "ep-2", "text": "minor thing",
                 "score": 0.6, "importance": 0.1},
            ])
            mock_get_svc.return_value = mock_svc

            traces = await _from_search_memory("user-1", "q", ["episode"], 5)

        assert traces[0]["confidence"] == "observed"

    @pytest.mark.asyncio
    async def test_missing_importance_falls_back_to_default_label(self):
        """No importance field at all (e.g. a row shape that predates this
        change, or a different scope) must not crash — falls back to the
        old fixed per-kind default rather than grading None."""
        with patch("app.services.memory_service.get_memory_service") as mock_get_svc, \
             patch("app.services.memory_recall._strengthen_recalled_episodes", new=AsyncMock()):
            mock_svc = MagicMock()
            mock_svc.SessionLocal = MagicMock()
            mock_svc.search_memory = AsyncMock(return_value=[
                {"type": "episode", "episode_id": "ep-3", "text": "no importance field", "score": 0.6},
            ])
            mock_get_svc.return_value = mock_svc

            traces = await _from_search_memory("user-1", "q", ["episode"], 5)

        assert traces[0]["confidence"] == "observed"  # _KIND_CONFIDENCE default


class TestRetrievalStrengthening:
    """Brain Alignment H4: a recalled episode earns a small, capped bump to
    its intrinsic importance. Used to live only inside main_simple.py's
    IntelligentMemoryService.intelligent_memory_search — every caller
    already going through memory.recall() for episodes (the live
    post-Arc-2.3 chat context path included) had been silently missing it,
    since recall() never called that method. Moved into the door itself
    (_from_search_memory) so every present and future caller gets it."""

    def _mock_db_factory(self):
        mock_db = MagicMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session_cm)
        return mock_factory, mock_db

    @pytest.mark.asyncio
    async def test_episode_results_trigger_strengthening_update(self):
        mock_factory, mock_db = self._mock_db_factory()
        with patch("app.services.memory_service.get_memory_service") as mock_get_svc, \
             patch("app.db.session.get_async_session_factory", return_value=mock_factory):
            mock_svc = MagicMock()
            mock_svc.SessionLocal = MagicMock()
            mock_svc.search_memory = AsyncMock(return_value=[
                {"type": "episode", "episode_id": "ep-1", "text": "hello", "role": "user",
                 "source": "chat", "created_at": "2026-01-01", "score": 0.6},
            ])
            mock_get_svc.return_value = mock_svc

            traces = await _from_search_memory("user-1", "hello", ["episode"], 5)

        assert len(traces) == 1
        mock_db.execute.assert_awaited_once()
        call_args = mock_db.execute.call_args
        assert call_args[0][1]["ids"] == ["ep-1"]
        assert call_args[0][1]["uid"] == "user-1"
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_note_only_results_do_not_trigger_strengthening(self):
        mock_factory, mock_db = self._mock_db_factory()
        with patch("app.services.memory_service.get_memory_service") as mock_get_svc, \
             patch("app.db.session.get_async_session_factory", return_value=mock_factory):
            mock_svc = MagicMock()
            mock_svc.SessionLocal = MagicMock()
            mock_svc.search_memory = AsyncMock(return_value=[
                {"type": "note", "note_id": "n-1", "title": "t", "text": "body", "score": 0.5},
            ])
            mock_get_svc.return_value = mock_svc

            traces = await _from_search_memory("user-1", "hello", ["note"], 5)

        assert len(traces) == 1
        mock_db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_strengthening_failure_does_not_break_recall(self):
        with patch("app.services.memory_service.get_memory_service") as mock_get_svc, \
             patch("app.db.session.get_async_session_factory", side_effect=RuntimeError("db down")):
            mock_svc = MagicMock()
            mock_svc.SessionLocal = MagicMock()
            mock_svc.search_memory = AsyncMock(return_value=[
                {"type": "episode", "episode_id": "ep-1", "text": "hello", "score": 0.6},
            ])
            mock_get_svc.return_value = mock_svc

            traces = await _from_search_memory("user-1", "hello", ["episode"], 5)

        assert len(traces) == 1  # the recall itself still succeeds
