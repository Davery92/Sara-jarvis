"""
Tests for PersonalKnowledgeGraph.upsert_fact()'s Arc 5.2 minter-ruling fix —
"any path may mint facts at entry tiers... but dreaming is the sole
promotion authority: only it graduates." upsert_fact() used to bump
confidence +0.1 on every repeat confirmation from ANY caller (dreaming or
not) — the one structural violation the minter audit found. It now only
records the observation (times_confirmed, last_confirmed); confidence
moves only in promote_corroborated_facts(), called from dreaming.
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.personal_knowledge_graph import PersonalKnowledgeGraph


@pytest.fixture
def pkg():
    return PersonalKnowledgeGraph()


def _mock_session_with_match(match_result):
    """A session whose first .run(...).single() call (the dedup-key MATCH
    lookup) returns match_result; subsequent .run(...) calls (the SET
    statements) return a generic mock — upsert_fact doesn't read their
    result."""
    mock_session = MagicMock()
    mock_session.run.return_value.single.return_value = match_result
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    return mock_session


class TestUpsertFactConfirmation:
    def test_repeat_match_does_not_bump_confidence(self, pkg):
        """The core Arc 5.2 fix: confirming an existing fact must leave
        its confidence untouched — only times_confirmed/last_confirmed
        move at write time."""
        existing = {"pkg_id": "p1", "confidence": 0.5, "times_confirmed": 2, "status": "active"}
        mock_session = _mock_session_with_match(existing)
        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(pkg, "_ensure_driver", return_value=True), \
             patch.object(pkg, "driver", mock_driver), \
             patch.object(pkg, "_schedule_embedding"):
            result = pkg.upsert_fact("Preference", {"value": "tea"}, confidence=0.9, source="explicit_statement")

        assert result == "p1"
        # Find the SET call that updates times_confirmed and assert it
        # never touches n.confidence.
        set_calls = [c for c in mock_session.run.call_args_list if "SET" in c.args[0]]
        confirmation_call = next(c for c in set_calls if "times_confirmed" in c.args[0])
        assert "n.confidence" not in confirmation_call.args[0]
        assert confirmation_call.args[1]["times_confirmed"] == 3

    def test_closed_status_facts_are_not_touched(self, pkg):
        """Pre-existing behavior, unrelated to the Arc 5.2 fix but must
        survive it: a completed/abandoned/archived/stale fact doesn't get
        its last_confirmed bumped just because it was mentioned again."""
        existing = {"pkg_id": "p1", "confidence": 0.9, "times_confirmed": 5, "status": "completed"}
        mock_session = _mock_session_with_match(existing)
        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(pkg, "_ensure_driver", return_value=True), \
             patch.object(pkg, "driver", mock_driver):
            result = pkg.upsert_fact("Goal", {}, confidence=0.5)

        assert result == "p1"
        set_calls = [c for c in mock_session.run.call_args_list if "SET" in c.args[0]]
        assert not any("times_confirmed" in c.args[0] for c in set_calls)

    def test_new_fact_is_created_at_given_confidence(self, pkg):
        """No existing match — this is a genuine new mint, not a
        confirmation, so the caller's requested confidence is what's
        actually written (the minter ruling governs what confidence a
        caller is ALLOWED to request, not what upsert_fact does with a
        request it's given)."""
        mock_session = _mock_session_with_match(None)  # no existing match
        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(pkg, "_ensure_driver", return_value=True), \
             patch.object(pkg, "driver", mock_driver), \
             patch.object(pkg, "_schedule_embedding"):
            result = pkg.upsert_fact("Preference", {"value": "tea"}, confidence=0.6)

        assert result is not None
        create_calls = [c for c in mock_session.run.call_args_list if "CREATE" in c.args[0]]
        assert len(create_calls) == 1
        assert create_calls[0].args[1]["confidence"] == 0.6


class TestUpsertFactHealthGuard:
    """A5: refuse Health upserts that are neither a metric/value observation
    nor the health_consolidation weekly_summary sub-schema (kind + headline,
    no metric/current_value) — verified live 2026-08-12 that the naive
    'metric IS NULL AND current_value IS NULL' garbage filter would have
    caught 15 real weekly summaries and zero actual garbage."""

    def test_missing_metric_and_value_rejected(self, pkg):
        with patch.object(pkg, "_ensure_driver", return_value=True):
            result = pkg.upsert_fact("Health", {"notes": "something"}, confidence=0.9)
        assert result is None

    def test_metric_without_value_rejected(self, pkg):
        with patch.object(pkg, "_ensure_driver", return_value=True):
            result = pkg.upsert_fact("Health", {"metric": "resting heart rate"}, confidence=0.9)
        assert result is None

    def test_weekly_summary_kind_bypasses_metric_value_requirement(self, pkg):
        mock_session = _mock_session_with_match(None)
        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(pkg, "_ensure_driver", return_value=True), \
             patch.object(pkg, "driver", mock_driver), \
             patch.object(pkg, "_schedule_embedding"):
            result = pkg.upsert_fact(
                "Health",
                {"kind": "weekly_summary", "headline": "Recovery dipped hard Saturday"},
                confidence=0.95,
            )

        assert result is not None

    def test_transient_health_state_gets_expires_at(self, pkg):
        mock_session = _mock_session_with_match(None)
        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(pkg, "_ensure_driver", return_value=True), \
             patch.object(pkg, "driver", mock_driver), \
             patch.object(pkg, "_schedule_embedding"):
            pkg.upsert_fact(
                "Health",
                {"metric": "flu-like symptoms", "current_value": "present"},
                confidence=0.8,
            )

        create_calls = [c for c in mock_session.run.call_args_list if "CREATE" in c.args[0]]
        assert len(create_calls) == 1
        assert "expires_at" in create_calls[0].args[1]

    def test_durable_health_attribute_gets_no_expires_at(self, pkg):
        mock_session = _mock_session_with_match(None)
        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(pkg, "_ensure_driver", return_value=True), \
             patch.object(pkg, "driver", mock_driver), \
             patch.object(pkg, "_schedule_embedding"):
            pkg.upsert_fact(
                "Health",
                {"metric": "resting heart rate", "current_value": "58 bpm"},
                confidence=0.8,
            )

        create_calls = [c for c in mock_session.run.call_args_list if "CREATE" in c.args[0]]
        assert len(create_calls) == 1
        assert "expires_at" not in create_calls[0].args[1]
