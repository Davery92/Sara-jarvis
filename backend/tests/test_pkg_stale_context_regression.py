"""
Regression tests for the "still recovering" stale-context bug fix.

docs/plans/HYGIENE_AND_STALE_CONTEXT_FIX_PLAN_2026_08_12.md, Part A2/A3/A4:
nightly decay correctly dropped Neo4j confidence on a Feb 23 illness note,
but the pgvector shadow never received that decay and the merge fallback in
query_semantic() re-injected the shadow's stale content whenever Neo4j
didn't return a match for a pkg_id — including when Neo4j *deliberately*
filtered that node out. Sara kept telling David he was still recovering,
six months later.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.personal_knowledge_graph import PersonalKnowledgeGraph, personal_kg
from app.services.pkg_context_provider import PKGContextProvider


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


class _FakeRow:
    """Stand-in for a pgvector query result row (attribute access, not dict)."""
    def __init__(self, pkg_id, node_type, content_text, similarity):
        self.pkg_id = pkg_id
        self.node_type = node_type
        self.content_text = content_text
        self.similarity = similarity


@pytest.fixture
def pkg():
    return PersonalKnowledgeGraph()


def _patch_pgvector_rows(rows):
    """query_semantic() acquires its pgvector session via the shared
    app.db.base.SessionLocal (B1 — no more per-call create_engine())."""
    mock_session = MagicMock()
    mock_session.execute.return_value.fetchall.return_value = rows
    return patch("app.db.base.SessionLocal", return_value=mock_session)


def _patch_embedding():
    return patch(
        "app.services.embedding_service.EmbeddingService.generate_embedding",
        new=AsyncMock(return_value=[0.1, 0.2, 0.3]),
    )


def _mock_neo4j_driver(records):
    """records: list of {"pkg_id", "labels", "props"} dicts, or an
    exception instance to raise instead of returning results."""
    mock_session = MagicMock()
    if isinstance(records, Exception):
        mock_session.run.side_effect = records
    else:
        mock_session.run.return_value = records
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session
    return mock_driver


class TestQuerySemanticConfidenceFloor:
    """A2 + A3: a decayed Neo4j node must not be resurrected from a shadow
    that never received the decay."""

    @pytest.mark.asyncio
    async def test_decayed_neo4j_node_dropped_despite_fresh_shadow(self, pkg):
        shadow_rows = [_FakeRow("h1", "Health", "David's flu-like symptoms: present", 0.9)]
        neo4j_records = [{
            "pkg_id": "h1",
            "labels": ["PKG_Health"],
            "props": {
                "metric": "flu-like symptoms", "current_value": "present",
                "confidence": 0.18, "last_confirmed": _iso(180),
            },
        }]
        mock_driver = _mock_neo4j_driver(neo4j_records)

        with _patch_embedding(), _patch_pgvector_rows(shadow_rows), \
             patch.object(pkg, "_ensure_driver", return_value=True), \
             patch.object(pkg, "driver", mock_driver):
            results = await pkg.query_semantic("how am I feeling", min_similarity=0.3)

        assert results == []

    @pytest.mark.asyncio
    async def test_recent_low_confidence_node_kept(self, pkg):
        """Recently-observed low confidence (last_confirmed within 14 days)
        is not the same as decayed — must survive the floor."""
        shadow_rows = [_FakeRow("h2", "Health", "David's mood: uncertain", 0.9)]
        neo4j_records = [{
            "pkg_id": "h2",
            "labels": ["PKG_Health"],
            "props": {
                "metric": "mood", "current_value": "uncertain",
                "confidence": 0.3, "last_confirmed": _iso(2),
            },
        }]
        mock_driver = _mock_neo4j_driver(neo4j_records)

        with _patch_embedding(), _patch_pgvector_rows(shadow_rows), \
             patch.object(pkg, "_ensure_driver", return_value=True), \
             patch.object(pkg, "driver", mock_driver):
            results = await pkg.query_semantic("how am I feeling", min_similarity=0.3)

        assert len(results) == 1
        assert results[0]["metric"] == "mood"


class TestQuerySemanticFallbackDistinction:
    """A2: Neo4j deliberately excluding a node must not fall back to the
    shadow, but Neo4j being unreachable still must (two different cases the
    old code conflated into one 'not in neo4j_data' branch)."""

    @pytest.mark.asyncio
    async def test_neo4j_excluded_node_not_returned_via_shadow(self, pkg):
        shadow_rows = [_FakeRow("g1", "Goal", "David's goal: recover from illness", 0.9)]
        mock_driver = _mock_neo4j_driver([])  # Neo4j answered, found nothing (filtered out)

        with _patch_embedding(), _patch_pgvector_rows(shadow_rows), \
             patch.object(pkg, "_ensure_driver", return_value=True), \
             patch.object(pkg, "driver", mock_driver):
            results = await pkg.query_semantic("goals", min_similarity=0.3)

        assert results == []

    @pytest.mark.asyncio
    async def test_neo4j_unreachable_falls_back_to_shadow(self, pkg):
        shadow_rows = [_FakeRow("g1", "Goal", "David's goal: ship the release", 0.9)]
        mock_driver = _mock_neo4j_driver(RuntimeError("neo4j connection refused"))

        with _patch_embedding(), _patch_pgvector_rows(shadow_rows), \
             patch.object(pkg, "_ensure_driver", return_value=True), \
             patch.object(pkg, "driver", mock_driver):
            results = await pkg.query_semantic("goals", min_similarity=0.3)

        assert len(results) == 1
        assert results[0]["content_text"] == "David's goal: ship the release"


class TestGetRelevantContextExcludesStaleFact:
    """End-to-end: get_relevant_context() must not surface the stale fact
    through any path even though the shadow still has it at high confidence."""

    @pytest.mark.asyncio
    async def test_stale_health_not_surfaced_in_chat_context(self):
        provider = PKGContextProvider()
        with patch.object(personal_kg, "query_semantic", new=AsyncMock(return_value=[])), \
             patch.object(personal_kg, "query_relevant", return_value=[]), \
             patch.object(personal_kg, "get_david_summary", return_value="David's goal: ship the release"):
            context = await provider.get_relevant_context("user-1", "how am I feeling today?")

        assert "flu" not in context.lower()
        assert "recovering" not in context.lower()


class TestFactToSentenceAgeAndTTL:
    """A4: age suffix past 21 days for Health/Goal/Fact; transient Health
    states drop out entirely past their 14-day TTL."""

    def test_health_as_of_suffix_past_48h(self):
        """HEALTH_DATA_ACCURACY_FIX_PLAN 2.3: Health facts get a 48-hour rule,
        not the generic 21-day one. A six-day-old health line rendering clean is
        how a stale guess became indistinguishable from a fresh reading."""
        provider = PKGContextProvider()
        props = {"metric": "chest development",
                 "current_value": "underdeveloped relative to back",
                 "last_confirmed": _iso(6)}
        sentence = provider._fact_to_sentence("Health", props)
        assert "not a current reading" in sentence
        assert "as of" in sentence
        assert "chest development" in sentence

    def test_health_no_suffix_when_recent(self):
        provider = PKGContextProvider()
        props = {"metric": "chest development",
                 "current_value": "underdeveloped relative to back",
                 "last_confirmed": _iso(0)}
        sentence = provider._fact_to_sentence("Health", props)
        assert "not a current reading" not in sentence
        assert "chest development" in sentence

    def test_measured_health_fact_never_rendered(self):
        """HEALTH_DATA_ACCURACY_FIX_PLAN 2.1: `health_metric` is the only
        authority for a number about David's body. A legacy PKG node holding one
        — like the fabricated `hrv = 80` minted on 2026-08-31 — renders empty so
        no read path can surface it beside (or instead of) the real reading."""
        provider = PKGContextProvider()
        for metric, value in [("hrv", "80"), ("resting heart rate", "58 bpm"),
                              ("sleep_duration", "7.5 hours"),
                              ("Sleep Quality", "Poor (barely slept)")]:
            props = {"metric": metric, "current_value": value, "last_confirmed": _iso(0)}
            assert provider._fact_to_sentence("Health", props) == "", metric

    def test_transient_health_excluded_past_ttl(self):
        provider = PKGContextProvider()
        props = {"metric": "flu-like symptoms", "current_value": "present", "last_confirmed": _iso(30)}
        assert provider._fact_to_sentence("Health", props) == ""

    def test_transient_health_kept_within_ttl(self):
        provider = PKGContextProvider()
        props = {"metric": "flu-like symptoms", "current_value": "present", "last_confirmed": _iso(3)}
        sentence = provider._fact_to_sentence("Health", props)
        assert "flu-like symptoms" in sentence

    def test_transient_health_excluded_past_explicit_expires_at(self):
        provider = PKGContextProvider()
        props = {
            "metric": "sore shoulder", "current_value": "present",
            "last_confirmed": _iso(3), "expires_at": _iso(1),  # expired yesterday
        }
        assert provider._fact_to_sentence("Health", props) == ""

    def test_goal_age_suffix_past_21_days(self):
        provider = PKGContextProvider()
        props = {"description": "ship the release", "status": "active", "last_confirmed": _iso(100)}
        sentence = provider._fact_to_sentence("Goal", props)
        assert "may be stale" in sentence
