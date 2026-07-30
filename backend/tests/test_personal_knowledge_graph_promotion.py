"""
Tests for PersonalKnowledgeGraph.promote_corroborated_facts() (Arc 5.2
minter ruling) — the only place PKG confidence increases now. Dreaming-
only, idempotent by construction (sets confidence TO a tier floor, not
additive).
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.personal_knowledge_graph import PersonalKnowledgeGraph
from app.services.confidence_ladder import CONFIRMED_AT, INFERRED_AT


@pytest.fixture
def pkg():
    return PersonalKnowledgeGraph()


class TestPromoteCorroboratedFacts:
    def test_no_driver_returns_zero(self, pkg):
        with patch.object(pkg, "_ensure_driver", return_value=False):
            result = pkg.promote_corroborated_facts()
        assert result == 0

    def test_sums_both_promotion_tiers(self, pkg):
        mock_session = MagicMock()
        # First .run() = observed->inferred (2 promoted), second = inferred->confirmed (5 promoted)
        mock_session.run.return_value.single.side_effect = [
            {"promoted": 2}, {"promoted": 5},
        ]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(pkg, "_ensure_driver", return_value=True), \
             patch.object(pkg, "driver", mock_driver):
            result = pkg.promote_corroborated_facts()

        assert result == 7

    def test_promotion_sets_confidence_to_tier_floor_not_additive(self, pkg):
        """The idempotency property: SET n.confidence = <floor>, never
        n.confidence = n.confidence + x."""
        mock_session = MagicMock()
        mock_session.run.return_value.single.return_value = {"promoted": 0}
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(pkg, "_ensure_driver", return_value=True), \
             patch.object(pkg, "driver", mock_driver):
            pkg.promote_corroborated_facts()

        queries = [c.args[0] for c in mock_session.run.call_args_list]
        assert any(f"SET n.confidence = {INFERRED_AT}" in q for q in queries)
        assert any(f"SET n.confidence = {CONFIRMED_AT}" in q for q in queries)
        assert not any("n.confidence +" in q for q in queries)

    def test_confirmation_thresholds_are_passed_through(self, pkg):
        mock_session = MagicMock()
        mock_session.run.return_value.single.return_value = {"promoted": 0}
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(pkg, "_ensure_driver", return_value=True), \
             patch.object(pkg, "driver", mock_driver):
            pkg.promote_corroborated_facts(min_confirmations_for_inferred=5, min_confirmations_for_confirmed=10)

        params = [c.args[1] for c in mock_session.run.call_args_list]
        assert params[0]["min_confirmations"] == 5
        assert params[1]["min_confirmations"] == 10

    def test_cypher_exception_returns_zero_not_raises(self, pkg):
        mock_session = MagicMock()
        mock_session.run.side_effect = RuntimeError("neo4j exploded")
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(pkg, "_ensure_driver", return_value=True), \
             patch.object(pkg, "driver", mock_driver):
            result = pkg.promote_corroborated_facts()
        assert result == 0
