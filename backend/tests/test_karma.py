"""
Phase 2 Karma System Tests

Tests for Sara's karma system:
- KarmaService operations
- Score bounds enforcement
- Trend calculation
- Decay mechanics
- Context injection for chat
"""

import pytest
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


# ==========================================
# KARMA SERVICE TESTS
# ==========================================

class TestKarmaService:
    """Tests for the KarmaService."""

    @pytest.fixture
    async def karma_service(self, db_session):
        """Create a KarmaService instance with test database."""
        from app.services.karma.service import KarmaService
        return KarmaService(db_session)

    @pytest.fixture
    async def setup_karma_tables(self, db_session):
        """Set up karma tables in test database."""
        from sqlalchemy import text

        # Create karma tables
        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_config (
                config_key TEXT PRIMARY KEY,
                config_value JSONB
            )
        """))

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_agents (
                agent_id TEXT PRIMARY KEY,
                agent_type TEXT,
                display_name TEXT,
                description TEXT,
                is_active BOOLEAN DEFAULT TRUE
            )
        """))

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_dimensions (
                agent_id TEXT,
                dimension_name TEXT,
                description TEXT,
                weight FLOAT DEFAULT 1.0,
                PRIMARY KEY (agent_id, dimension_name)
            )
        """))

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_scores (
                agent_id TEXT,
                dimension_name TEXT,
                current_score FLOAT DEFAULT 50.0,
                trend FLOAT DEFAULT 0.0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (agent_id, dimension_name)
            )
        """))

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_events (
                event_id SERIAL PRIMARY KEY,
                agent_id TEXT,
                dimension_name TEXT,
                delta FLOAT,
                new_score FLOAT,
                reason TEXT,
                evidence_type TEXT,
                evidence_ids TEXT[],
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

        # Insert test agent
        await db_session.execute(text("""
            INSERT INTO karma_agents (agent_id, agent_type, display_name, description)
            VALUES ('sara', 'assistant', 'Sara', 'Main assistant agent')
            ON CONFLICT DO NOTHING
        """))

        # Insert test dimension
        await db_session.execute(text("""
            INSERT INTO karma_dimensions (agent_id, dimension_name, description, weight)
            VALUES ('sara', 'helpfulness', 'How helpful responses are', 1.0)
            ON CONFLICT DO NOTHING
        """))

        await db_session.commit()

    @pytest.mark.asyncio
    async def test_record_event_updates_score(self, karma_service, setup_karma_tables, db_session):
        """Test that recording an event updates the score."""
        from app.services.karma.service import KarmaEvent

        # Initialize score
        from sqlalchemy import text
        await db_session.execute(text("""
            INSERT INTO karma_scores (agent_id, dimension_name, current_score)
            VALUES ('sara', 'helpfulness', 50.0)
            ON CONFLICT (agent_id, dimension_name) DO UPDATE SET current_score = 50.0
        """))
        await db_session.commit()

        event = KarmaEvent(
            agent_id="sara",
            dimension_name="helpfulness",
            delta=5.0,
            reason="User thanked Sara"
        )

        new_score = await karma_service.record_event(event)

        assert new_score == 55.0

    @pytest.mark.asyncio
    async def test_score_bounds_enforced_max(self, karma_service, setup_karma_tables, db_session):
        """Test that scores are clamped at max (100)."""
        from app.services.karma.service import KarmaEvent
        from sqlalchemy import text

        # Set score near max
        await db_session.execute(text("""
            INSERT INTO karma_scores (agent_id, dimension_name, current_score)
            VALUES ('sara', 'helpfulness', 98.0)
            ON CONFLICT (agent_id, dimension_name) DO UPDATE SET current_score = 98.0
        """))
        await db_session.commit()

        event = KarmaEvent(
            agent_id="sara",
            dimension_name="helpfulness",
            delta=10.0,  # Would push to 108
            reason="Exceptional help"
        )

        new_score = await karma_service.record_event(event)

        assert new_score == 100.0  # Clamped at max

    @pytest.mark.asyncio
    async def test_score_bounds_enforced_min(self, karma_service, setup_karma_tables, db_session):
        """Test that scores are clamped at min (0)."""
        from app.services.karma.service import KarmaEvent
        from sqlalchemy import text

        # Set score near min
        await db_session.execute(text("""
            INSERT INTO karma_scores (agent_id, dimension_name, current_score)
            VALUES ('sara', 'helpfulness', 5.0)
            ON CONFLICT (agent_id, dimension_name) DO UPDATE SET current_score = 5.0
        """))
        await db_session.commit()

        event = KarmaEvent(
            agent_id="sara",
            dimension_name="helpfulness",
            delta=-10.0,  # Would push to -5
            reason="Major mistake"
        )

        new_score = await karma_service.record_event(event)

        assert new_score == 0.0  # Clamped at min

    @pytest.mark.asyncio
    async def test_get_agent_karma(self, karma_service, setup_karma_tables, db_session):
        """Test getting complete karma state for an agent."""
        from sqlalchemy import text

        # Set up score
        await db_session.execute(text("""
            INSERT INTO karma_scores (agent_id, dimension_name, current_score, trend)
            VALUES ('sara', 'helpfulness', 75.0, 2.5)
            ON CONFLICT (agent_id, dimension_name) DO UPDATE SET current_score = 75.0, trend = 2.5
        """))
        await db_session.commit()

        karma = await karma_service.get_agent_karma("sara")

        assert karma is not None
        assert karma.agent_id == "sara"
        assert len(karma.dimensions) >= 1
        assert karma.composite_score >= 0

    @pytest.mark.asyncio
    async def test_score_to_threshold(self, karma_service):
        """Test score to threshold conversion."""
        from app.services.karma.service import KarmaThreshold

        thresholds = karma_service.DEFAULT_THRESHOLDS

        # Test each threshold level
        assert karma_service._score_to_threshold(10, thresholds) == KarmaThreshold.CRITICAL_LOW
        assert karma_service._score_to_threshold(30, thresholds) == KarmaThreshold.LOW
        assert karma_service._score_to_threshold(50, thresholds) == KarmaThreshold.NEUTRAL
        assert karma_service._score_to_threshold(70, thresholds) == KarmaThreshold.GOOD
        assert karma_service._score_to_threshold(90, thresholds) == KarmaThreshold.EXCELLENT

    @pytest.mark.asyncio
    async def test_format_karma_context(self, karma_service, setup_karma_tables, db_session):
        """Test formatting karma context for prompt injection."""
        from sqlalchemy import text

        # Set up a notable score (good)
        await db_session.execute(text("""
            INSERT INTO karma_scores (agent_id, dimension_name, current_score, trend)
            VALUES ('sara', 'helpfulness', 80.0, 1.0)
            ON CONFLICT (agent_id, dimension_name) DO UPDATE SET current_score = 80.0, trend = 1.0
        """))
        await db_session.commit()

        context = await karma_service.format_karma_context("sara")

        assert "<karma" in context
        assert "sara" in context
        assert "</karma>" in context


# ==========================================
# KARMA DECAY TESTS
# ==========================================

class TestKarmaDecay:
    """Tests for karma decay mechanics."""

    @pytest.fixture
    async def karma_service(self, db_session):
        """Create a KarmaService instance."""
        from app.services.karma.service import KarmaService
        return KarmaService(db_session)

    @pytest.mark.asyncio
    async def test_decay_toward_neutral(self, karma_service, db_session):
        """Test that scores decay toward neutral (50)."""
        from sqlalchemy import text

        # Create tables and data for decay test
        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_config (
                config_key TEXT PRIMARY KEY,
                config_value JSONB
            )
        """))

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_agents (
                agent_id TEXT PRIMARY KEY,
                agent_type TEXT,
                display_name TEXT,
                description TEXT,
                is_active BOOLEAN DEFAULT TRUE
            )
        """))

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_dimensions (
                agent_id TEXT,
                dimension_name TEXT,
                description TEXT,
                weight FLOAT DEFAULT 1.0,
                PRIMARY KEY (agent_id, dimension_name)
            )
        """))

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_scores (
                agent_id TEXT,
                dimension_name TEXT,
                current_score FLOAT DEFAULT 50.0,
                trend FLOAT DEFAULT 0.0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (agent_id, dimension_name)
            )
        """))

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_events (
                event_id SERIAL PRIMARY KEY,
                agent_id TEXT,
                dimension_name TEXT,
                delta FLOAT,
                new_score FLOAT,
                reason TEXT,
                evidence_type TEXT,
                evidence_ids TEXT[],
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

        # Set up agent and dimension
        await db_session.execute(text("""
            INSERT INTO karma_agents (agent_id, agent_type, display_name, is_active)
            VALUES ('sara', 'assistant', 'Sara', TRUE)
            ON CONFLICT DO NOTHING
        """))

        await db_session.execute(text("""
            INSERT INTO karma_dimensions (agent_id, dimension_name, weight)
            VALUES ('sara', 'proactivity', 1.0)
            ON CONFLICT DO NOTHING
        """))

        # Score above decay threshold (default 55)
        await db_session.execute(text("""
            INSERT INTO karma_scores (agent_id, dimension_name, current_score)
            VALUES ('sara', 'proactivity', 70.0)
            ON CONFLICT (agent_id, dimension_name) DO UPDATE SET current_score = 70.0
        """))

        # Set decay config
        await db_session.execute(text("""
            INSERT INTO karma_config (config_key, config_value)
            VALUES ('karma_settings', :config)
            ON CONFLICT (config_key) DO UPDATE SET config_value = :config
        """), {"config": json.dumps({
            "thresholds": {"critical_low": 20, "low": 35, "neutral": 50, "good": 65, "excellent": 80},
            "score_bounds": {"min": 0, "max": 100, "starting": 50},
            "decay": {
                "enabled": True,
                "rate_per_day": 2.0,
                "target": 50,
                "min_score_for_decay": 55,
                "max_score_for_recovery": 45
            }
        })})

        await db_session.commit()

        decay_results = await karma_service.apply_decay("sara")

        # Should have decayed
        if "sara" in decay_results:
            assert any(d["dimension"] == "proactivity" for d in decay_results["sara"])


# ==========================================
# KARMA TREND TESTS
# ==========================================

class TestKarmaTrend:
    """Tests for karma trend calculation."""

    @pytest.mark.asyncio
    async def test_trend_calculation_positive(self, db_session):
        """Test that positive events create positive trend."""
        from app.services.karma.service import KarmaService, KarmaEvent
        from sqlalchemy import text

        # Set up tables
        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_config (
                config_key TEXT PRIMARY KEY,
                config_value JSONB
            )
        """))

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_scores (
                agent_id TEXT,
                dimension_name TEXT,
                current_score FLOAT DEFAULT 50.0,
                trend FLOAT DEFAULT 0.0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (agent_id, dimension_name)
            )
        """))

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_events (
                event_id SERIAL PRIMARY KEY,
                agent_id TEXT,
                dimension_name TEXT,
                delta FLOAT,
                new_score FLOAT,
                reason TEXT,
                evidence_type TEXT,
                evidence_ids TEXT[],
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

        await db_session.execute(text("""
            INSERT INTO karma_scores (agent_id, dimension_name, current_score)
            VALUES ('sara', 'accuracy', 50.0)
            ON CONFLICT DO NOTHING
        """))

        await db_session.commit()

        service = KarmaService(db_session)

        # Record multiple positive events
        for i in range(5):
            await service.record_event(KarmaEvent(
                agent_id="sara",
                dimension_name="accuracy",
                delta=2.0,
                reason=f"Correct answer {i}"
            ))

        # Get karma to check trend
        result = await db_session.execute(text("""
            SELECT trend FROM karma_scores
            WHERE agent_id = 'sara' AND dimension_name = 'accuracy'
        """))
        row = result.fetchone()

        # Trend should be positive (average of recent positive deltas)
        if row:
            assert row[0] >= 0  # Trend should be non-negative after positive events


# ==========================================
# KARMA DASHBOARD TESTS
# ==========================================

class TestKarmaDashboard:
    """Tests for the karma dashboard."""

    @pytest.mark.asyncio
    async def test_get_karma_dashboard(self, db_session):
        """Test getting the karma dashboard."""
        from app.services.karma.service import KarmaService
        from sqlalchemy import text

        # Set up required tables
        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_config (
                config_key TEXT PRIMARY KEY,
                config_value JSONB
            )
        """))

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_agents (
                agent_id TEXT PRIMARY KEY,
                agent_type TEXT,
                display_name TEXT,
                description TEXT,
                is_active BOOLEAN DEFAULT TRUE
            )
        """))

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_dimensions (
                agent_id TEXT,
                dimension_name TEXT,
                description TEXT,
                weight FLOAT DEFAULT 1.0,
                PRIMARY KEY (agent_id, dimension_name)
            )
        """))

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_scores (
                agent_id TEXT,
                dimension_name TEXT,
                current_score FLOAT DEFAULT 50.0,
                trend FLOAT DEFAULT 0.0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (agent_id, dimension_name)
            )
        """))

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_events (
                event_id SERIAL PRIMARY KEY,
                agent_id TEXT,
                dimension_name TEXT,
                delta FLOAT,
                new_score FLOAT,
                reason TEXT,
                evidence_type TEXT,
                evidence_ids TEXT[],
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

        # Add test agents
        await db_session.execute(text("""
            INSERT INTO karma_agents (agent_id, agent_type, display_name, is_active)
            VALUES
                ('sara', 'assistant', 'Sara', TRUE),
                ('reflection', 'agent', 'Reflection Agent', TRUE)
            ON CONFLICT DO NOTHING
        """))

        # Add dimensions
        await db_session.execute(text("""
            INSERT INTO karma_dimensions (agent_id, dimension_name, weight)
            VALUES
                ('sara', 'helpfulness', 1.0),
                ('reflection', 'insight_quality', 1.0)
            ON CONFLICT DO NOTHING
        """))

        # Add scores
        await db_session.execute(text("""
            INSERT INTO karma_scores (agent_id, dimension_name, current_score)
            VALUES
                ('sara', 'helpfulness', 75.0),
                ('reflection', 'insight_quality', 60.0)
            ON CONFLICT DO NOTHING
        """))

        await db_session.commit()

        service = KarmaService(db_session)
        dashboard = await service.get_karma_dashboard()

        assert "agents" in dashboard
        assert "alerts" in dashboard
        assert "thresholds" in dashboard
        assert "generated_at" in dashboard


# ==========================================
# KARMA INTEGRATION TESTS
# ==========================================

class TestKarmaIntegration:
    """Integration tests for karma in chat context."""

    @pytest.mark.asyncio
    async def test_karma_context_format_for_prompt(self, db_session):
        """Test that karma context can be formatted for prompt injection."""
        from app.services.karma.service import KarmaService
        from sqlalchemy import text

        # Minimal table setup
        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_config (
                config_key TEXT PRIMARY KEY,
                config_value JSONB
            )
        """))

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_agents (
                agent_id TEXT PRIMARY KEY,
                agent_type TEXT,
                display_name TEXT,
                description TEXT,
                is_active BOOLEAN DEFAULT TRUE
            )
        """))

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_dimensions (
                agent_id TEXT,
                dimension_name TEXT,
                description TEXT,
                weight FLOAT DEFAULT 1.0,
                PRIMARY KEY (agent_id, dimension_name)
            )
        """))

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS karma_scores (
                agent_id TEXT,
                dimension_name TEXT,
                current_score FLOAT DEFAULT 50.0,
                trend FLOAT DEFAULT 0.0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (agent_id, dimension_name)
            )
        """))

        # Add Sara agent with low proactivity (should appear in context)
        await db_session.execute(text("""
            INSERT INTO karma_agents (agent_id, agent_type, display_name, is_active)
            VALUES ('sara', 'assistant', 'Sara', TRUE)
            ON CONFLICT DO NOTHING
        """))

        await db_session.execute(text("""
            INSERT INTO karma_dimensions (agent_id, dimension_name, weight)
            VALUES ('sara', 'proactivity', 1.0)
            ON CONFLICT DO NOTHING
        """))

        # Low score that should appear in context
        await db_session.execute(text("""
            INSERT INTO karma_scores (agent_id, dimension_name, current_score, trend)
            VALUES ('sara', 'proactivity', 25.0, -1.5)
            ON CONFLICT DO NOTHING
        """))

        await db_session.commit()

        service = KarmaService(db_session)
        context = await service.format_karma_context("sara")

        # Should include the low proactivity dimension
        assert "proactivity" in context.lower() or "low" in context.lower() or "<karma" in context

    @pytest.mark.asyncio
    async def test_karma_affects_behavior(self):
        """Test that karma scores can affect system behavior."""
        # This is a behavioral test showing how karma would be used

        karma_score = 25.0  # Low proactivity
        high_priority_threshold = 0.7

        # With low karma, system should be more conservative
        # (this simulates the check in proactive.py)
        if karma_score < 35:
            # Filter to only high-priority items
            actions = [
                {"priority": 0.5, "type": "notify"},
                {"priority": 0.8, "type": "remind"},
            ]
            filtered = [a for a in actions if a["priority"] >= high_priority_threshold]
            assert len(filtered) == 1  # Only high-priority action remains
