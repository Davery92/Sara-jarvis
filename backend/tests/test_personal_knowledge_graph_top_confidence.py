"""
Tests for PersonalKnowledgeGraph.query_top_confidence() (Arc 5.1) — the
query-free "top N facts by confidence" browse memory_recall._from_facts
falls back to when there's no message to embed/compare against. Same
Cypher shape as the existing get_david_summary(), but returns raw rows
instead of pre-formatted text.
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.personal_knowledge_graph import PersonalKnowledgeGraph


@pytest.fixture
def pkg():
    return PersonalKnowledgeGraph()


class TestQueryTopConfidence:
    @pytest.mark.asyncio
    async def test_no_driver_returns_empty_list(self, pkg):
        with patch.object(pkg, "_ensure_driver", return_value=False):
            result = await pkg.query_top_confidence(limit=10)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_rows_with_type_and_similarity_stand_in(self, pkg):
        fake_record = {
            "pkg_id": "abc-123",
            "labels": ["PKG_Goal"],
            "props": {"description": "Ship Arc 5", "status": "active", "confidence": 0.92},
        }
        mock_session = MagicMock()
        mock_session.run.return_value = [fake_record]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(pkg, "_ensure_driver", return_value=True), \
             patch.object(pkg, "driver", mock_driver), \
             patch.object(pkg, "_extract_pkg_label", return_value="Goal"):
            result = await pkg.query_top_confidence(limit=10)

        assert len(result) == 1
        row = result[0]
        assert row["type"] == "Goal"
        assert row["pkg_id"] == "abc-123"
        assert row["description"] == "Ship Arc 5"
        assert row["similarity"] == 0.92  # confidence used as the stand-in score

    @pytest.mark.asyncio
    async def test_cypher_exception_returns_empty_list_not_raises(self, pkg):
        mock_session = MagicMock()
        mock_session.run.side_effect = RuntimeError("neo4j exploded")
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(pkg, "_ensure_driver", return_value=True), \
             patch.object(pkg, "driver", mock_driver):
            result = await pkg.query_top_confidence(limit=10)
        assert result == []
