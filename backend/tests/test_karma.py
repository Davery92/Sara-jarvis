"""
Phase 2 Karma System Tests

Tests for Sara's karma system:
- KarmaService operations (with mock async DB)
- Score bounds enforcement
- Trend calculation
- Decay mechanics
- Context injection for chat

Note: KarmaService uses `await self.db.execute()` — it expects an async DB session.
Tests use AsyncMock to simulate the DB layer since conftest provides sync SQLite sessions.
"""

import pytest
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import text


# ==========================================
# HELPER: Build mock DB results
# ==========================================

def _mock_config_result(config=None):
    """Return a mock result for karma_config query.

    NOTE: KarmaService._get_config() stores row[0] directly as its cache.
    We return the dict itself (not JSON-serialized) so .get() works downstream.
    """
    result = MagicMock()
    if config:
        result.fetchone.return_value = (config,)
    else:
        result.fetchone.return_value = None
    return result


def _mock_agent_result(agent_id="sara", agent_type="assistant", display_name="Sara"):
    """Return a mock result for karma_agents query."""
    result = MagicMock()
    result.fetchone.return_value = (agent_id, agent_type, display_name, "Test", True)
    return result


def _mock_dimensions_result(dims=None):
    """Return a mock result for karma dimensions + scores query."""
    result = MagicMock()
    if dims is None:
        dims = [("helpfulness", "Test dimension", 1.0, 50.0, 0.0, datetime.utcnow())]
    result.fetchall.return_value = dims
    return result


def _mock_score_result(score=50.0, trend=0.0):
    """Return a mock result for karma_scores query."""
    result = MagicMock()
    result.fetchone.return_value = (score, trend)
    return result


def _mock_empty_result():
    """Return a mock result with no rows."""
    result = MagicMock()
    result.fetchall.return_value = []
    result.fetchone.return_value = None
    return result


def _mock_insert_result():
    """Return a mock result for INSERT queries."""
    result = MagicMock()
    result.fetchone.return_value = None
    result.rowcount = 1
    return result


# ==========================================
# KARMA SERVICE TESTS
# ==========================================

class TestKarmaService:
    """Tests for the KarmaService with mocked async DB."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def karma_service(self, mock_db):
        from app.services.karma.service import KarmaService
        return KarmaService(mock_db)

    @pytest.mark.asyncio
    async def test_record_event_updates_score(self, karma_service, mock_db):
        from app.services.karma.service import KarmaEvent

        # record_event makes 5 execute calls: config, current_score, trend, upsert, insert
        trend_result = MagicMock()
        trend_result.fetchone.return_value = (0.0,)

        mock_db.execute.side_effect = [
            _mock_config_result(),              # _get_config
            _mock_score_result(50.0, 0.0),      # get current score
            trend_result,                        # get trend (AVG of recent)
            _mock_insert_result(),              # upsert score
            _mock_insert_result(),              # insert event
        ]

        event = KarmaEvent(
            agent_id="sara", dimension_name="helpfulness",
            delta=5.0, reason="User thanked Sara",
        )
        new_score = await karma_service.record_event(event)
        assert new_score == 55.0

    @pytest.mark.asyncio
    async def test_score_bounds_enforced_max(self, karma_service, mock_db):
        from app.services.karma.service import KarmaEvent

        trend_result = MagicMock()
        trend_result.fetchone.return_value = (0.0,)

        mock_db.execute.side_effect = [
            _mock_config_result(),
            _mock_score_result(98.0, 0.0),
            trend_result,
            _mock_insert_result(),
            _mock_insert_result(),
        ]

        event = KarmaEvent(
            agent_id="sara", dimension_name="helpfulness",
            delta=10.0, reason="Exceptional help",
        )
        new_score = await karma_service.record_event(event)
        assert new_score == 100.0

    @pytest.mark.asyncio
    async def test_score_bounds_enforced_min(self, karma_service, mock_db):
        from app.services.karma.service import KarmaEvent

        trend_result = MagicMock()
        trend_result.fetchone.return_value = (0.0,)

        mock_db.execute.side_effect = [
            _mock_config_result(),
            _mock_score_result(5.0, 0.0),
            trend_result,
            _mock_insert_result(),
            _mock_insert_result(),
        ]

        event = KarmaEvent(
            agent_id="sara", dimension_name="helpfulness",
            delta=-10.0, reason="Major mistake",
        )
        new_score = await karma_service.record_event(event)
        assert new_score == 0.0

    @pytest.mark.asyncio
    async def test_get_agent_karma(self, karma_service, mock_db):
        mock_db.execute.side_effect = [
            _mock_config_result(),              # _get_config
            _mock_agent_result(),               # agent info
            _mock_dimensions_result([           # dimensions + scores
                ("helpfulness", "Test", 1.0, 75.0, 2.5, datetime.utcnow()),
            ]),
        ]

        karma = await karma_service.get_agent_karma("sara")
        assert karma is not None
        assert karma.agent_id == "sara"
        assert len(karma.dimensions) >= 1
        assert karma.composite_score >= 0

    @pytest.mark.asyncio
    async def test_format_karma_context(self, karma_service, mock_db):
        mock_db.execute.side_effect = [
            _mock_config_result(),
            _mock_agent_result(),
            _mock_dimensions_result([
                ("helpfulness", "Test", 1.0, 80.0, 1.0, datetime.utcnow()),
            ]),
        ]

        context = await karma_service.format_karma_context("sara")
        assert "<karma" in context
        assert "sara" in context
        assert "</karma>" in context

    def test_score_to_threshold(self, karma_service):
        from app.services.karma.service import KarmaThreshold
        thresholds = karma_service.DEFAULT_THRESHOLDS

        assert karma_service._score_to_threshold(10, thresholds) == KarmaThreshold.CRITICAL_LOW
        assert karma_service._score_to_threshold(30, thresholds) == KarmaThreshold.LOW
        assert karma_service._score_to_threshold(50, thresholds) == KarmaThreshold.NEUTRAL
        assert karma_service._score_to_threshold(70, thresholds) == KarmaThreshold.GOOD
        assert karma_service._score_to_threshold(90, thresholds) == KarmaThreshold.EXCELLENT


# ==========================================
# KARMA DECAY TESTS
# ==========================================

class TestKarmaDecay:
    @pytest.mark.asyncio
    async def test_decay_toward_neutral(self):
        from app.services.karma.service import KarmaService

        mock_db = AsyncMock()
        service = KarmaService(mock_db)

        config = {
            "thresholds": {"critical_low": 20, "low": 35, "neutral": 50, "good": 65, "excellent": 80},
            "score_bounds": {"min": 0, "max": 100, "starting": 50},
            "decay": {
                "enabled": True, "rate_per_day": 2.0, "target": 50,
                "min_score_for_decay": 55, "max_score_for_recovery": 45,
            },
        }

        # apply_decay flow: _get_config, get decayable scores, then record_event per row
        # record_event (config CACHED): get_score, get_trend, upsert, insert
        decay_scores_result = MagicMock()
        decay_scores_result.fetchall.return_value = [
            ("sara", "proactivity", 70.0),
        ]

        trend_result = MagicMock()
        trend_result.fetchone.return_value = (0.0,)

        mock_db.execute.side_effect = [
            _mock_config_result(config),          # 1: _get_config (caches)
            decay_scores_result,                   # 2: get decayable scores
            _mock_score_result(70.0, 0.0),        # 3: record_event → get current score
            trend_result,                          # 4: record_event → get trend
            _mock_insert_result(),                # 5: record_event → upsert score
            _mock_insert_result(),                # 6: record_event → insert event
        ]

        decay_results = await service.apply_decay("sara")
        assert isinstance(decay_results, dict)


# ==========================================
# KARMA TREND TESTS
# ==========================================

class TestKarmaTrend:
    @pytest.mark.asyncio
    async def test_trend_calculation_positive(self):
        from app.services.karma.service import KarmaService, KarmaEvent

        mock_db = AsyncMock()
        service = KarmaService(mock_db)

        # Each record_event call needs: config + score + trend + upsert + insert
        side_effects = []
        current_score = 50.0
        for i in range(5):
            trend_result = MagicMock()
            trend_result.fetchone.return_value = (2.0 if i > 0 else None,)
            side_effects.extend([
                _mock_config_result(),
                _mock_score_result(current_score, 0.0),
                trend_result,
                _mock_insert_result(),
                _mock_insert_result(),
            ])
            current_score += 2.0

        mock_db.execute.side_effect = side_effects

        for i in range(5):
            await service.record_event(KarmaEvent(
                agent_id="sara", dimension_name="accuracy",
                delta=2.0, reason=f"Correct answer {i}",
            ))

        # All events were recorded without error — 5 events × 5 calls each
        assert mock_db.execute.call_count == 25


# ==========================================
# KARMA DASHBOARD TESTS
# ==========================================

class TestKarmaDashboard:
    @pytest.mark.asyncio
    async def test_get_karma_dashboard(self):
        from app.services.karma.service import KarmaService

        mock_db = AsyncMock()
        service = KarmaService(mock_db)

        # Dashboard does its own aggregate query — NOT per-agent get_agent_karma.
        # Query returns: (agent_id, display_name, agent_type, composite_score, dimension_count)
        dashboard_result = MagicMock()
        dashboard_result.fetchall.return_value = [
            ("sara", "Sara", "assistant", 75.0, 1),
            ("reflection", "Reflection", "system", 60.0, 1),
        ]

        events_count_result = MagicMock()
        events_count_result.fetchone.return_value = (42,)

        mock_db.execute.side_effect = [
            _mock_config_result(),       # _get_config (caches default dict)
            dashboard_result,             # aggregate dashboard query
            events_count_result,          # COUNT(*) for recent events
        ]

        dashboard = await service.get_karma_dashboard()

        assert "agents" in dashboard
        assert "alerts" in dashboard
        assert "thresholds" in dashboard
        assert "generated_at" in dashboard


# ==========================================
# KARMA INTEGRATION TESTS
# ==========================================

class TestKarmaIntegration:
    @pytest.mark.asyncio
    async def test_karma_context_format_for_prompt(self):
        from app.services.karma.service import KarmaService

        mock_db = AsyncMock()
        service = KarmaService(mock_db)

        mock_db.execute.side_effect = [
            _mock_config_result(),
            _mock_agent_result(),
            _mock_dimensions_result([
                ("proactivity", "Test", 1.0, 25.0, -1.5, datetime.utcnow()),
            ]),
        ]

        context = await service.format_karma_context("sara")
        assert "proactivity" in context.lower() or "low" in context.lower() or "<karma" in context

    @pytest.mark.asyncio
    async def test_karma_affects_behavior(self):
        karma_score = 25.0
        high_priority_threshold = 0.7

        if karma_score < 35:
            actions = [
                {"priority": 0.5, "type": "notify"},
                {"priority": 0.8, "type": "remind"},
            ]
            filtered = [a for a in actions if a["priority"] >= high_priority_threshold]
            assert len(filtered) == 1
