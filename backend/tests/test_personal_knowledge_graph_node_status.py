"""
Tests for PersonalKnowledgeGraph.get_node_status() (Arc 5.2) — a single-node
confidence + needs_review read, used by the verification loop's retire half
to decide whether a fact is still unresolved (regardless of which of the two
ways it got flagged: a genuine needs_review contradiction, or just low
confidence).
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.personal_knowledge_graph import PersonalKnowledgeGraph


@pytest.fixture
def pkg():
    return PersonalKnowledgeGraph()


class TestGetNodeStatus:
    def test_no_driver_returns_none(self, pkg):
        with patch.object(pkg, "_ensure_driver", return_value=False):
            result = pkg.get_node_status("p1")
        assert result is None

    def test_node_not_found_returns_none(self, pkg):
        mock_session = MagicMock()
        mock_session.run.return_value.single.return_value = None
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(pkg, "_ensure_driver", return_value=True), \
             patch.object(pkg, "driver", mock_driver):
            result = pkg.get_node_status("p1")
        assert result is None

    def test_returns_confidence_and_needs_review(self, pkg):
        mock_session = MagicMock()
        mock_session.run.return_value.single.return_value = {"confidence": 0.42, "needs_review": True}
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(pkg, "_ensure_driver", return_value=True), \
             patch.object(pkg, "driver", mock_driver):
            result = pkg.get_node_status("p1")
        assert result == {"confidence": 0.42, "needs_review": True}

    def test_null_confidence_defaults_to_half(self, pkg):
        mock_session = MagicMock()
        mock_session.run.return_value.single.return_value = {"confidence": None, "needs_review": False}
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(pkg, "_ensure_driver", return_value=True), \
             patch.object(pkg, "driver", mock_driver):
            result = pkg.get_node_status("p1")
        assert result == {"confidence": 0.5, "needs_review": False}

    def test_cypher_exception_returns_none_not_raises(self, pkg):
        mock_session = MagicMock()
        mock_session.run.side_effect = RuntimeError("neo4j exploded")
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(pkg, "_ensure_driver", return_value=True), \
             patch.object(pkg, "driver", mock_driver):
            result = pkg.get_node_status("p1")
        assert result is None
