"""
Tests for the SINGULAR_SARA_MASTER_PLAN §C3 periodic intent-graph sync task.
"""

from unittest.mock import MagicMock, patch

from app.tasks.intent_graph import sync_intent_graph


class TestSyncIntentGraphTask:
    def test_returns_outcome_contract_with_counts(self):
        mock_db = MagicMock()
        mock_result = {"seen": 46, "upserted": 46, "errors": [], "by_source": {}}

        with patch("app.db.session.SessionLocal", return_value=mock_db), \
             patch("app.services.intent_graph_service.sync_from_projections", return_value=mock_result) as mock_sync:

            outcome = sync_intent_graph()

        mock_sync.assert_called_once_with(mock_db, "64f37c56-85cb-4590-8de9-adfc17d343ed")
        mock_db.close.assert_called_once()
        assert outcome == {
            "effect": "intent_graph_synced",
            "seen": 46,
            "upserted": 46,
            "error_count": 0,
        }

    def test_closes_db_even_when_sync_raises(self):
        mock_db = MagicMock()

        with patch("app.db.session.SessionLocal", return_value=mock_db), \
             patch("app.services.intent_graph_service.sync_from_projections", side_effect=RuntimeError("boom")):
            try:
                sync_intent_graph()
            except RuntimeError:
                pass

        mock_db.close.assert_called_once()
