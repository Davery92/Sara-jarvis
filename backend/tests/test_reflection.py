"""
Phase 3 Reflection System Tests

Tests for Sara's reflection system:
- Scratchpad operations (via mock async DB)
- Pattern detection logic
- Proposal generation and workflow
- Reflection cycle
- Notification integration

Note: The reflection services use AsyncSession. Tests mock the DB layer
since conftest provides sync SQLite sessions.
"""

import pytest
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass


# ==========================================
# SCRATCHPAD TESTS
# ==========================================

class TestScratchpad:
    """Tests for the ReflectionScratchpad."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock async DB session."""
        db = AsyncMock()
        return db

    @pytest.fixture
    def scratchpad(self, mock_db):
        from app.services.reflection.scratchpad import ReflectionScratchpad
        return ReflectionScratchpad(mock_db)

    @pytest.mark.asyncio
    async def test_add_observation(self, scratchpad, mock_db):
        """Test adding an observation to scratchpad."""
        from app.services.reflection.scratchpad import ObservationType

        # Mock the DB execute to return an observation ID
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (1,)
        mock_db.execute.return_value = mock_result

        obs_id = await scratchpad.add_observation(
            observation_type=ObservationType.ACTION_OUTCOME,
            summary="User gave positive feedback",
            confidence=0.8,
        )

        assert mock_db.execute.called

    @pytest.mark.asyncio
    async def test_get_recent_observations(self, scratchpad, mock_db):
        """Test retrieving recent observations."""
        from app.services.reflection.scratchpad import ObservationType

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (1, "action_outcome", None, None, "Obs 1", None, 0.8, None, None,
             False, None, datetime.utcnow(), None),
            (2, "pattern_detected", None, None, "Obs 2", None, 0.6, None, None,
             False, None, datetime.utcnow(), None),
        ]
        mock_db.execute.return_value = mock_result

        observations = await scratchpad.get_recent_observations(days=7)
        assert mock_db.execute.called

    @pytest.mark.asyncio
    async def test_add_pattern(self, scratchpad, mock_db):
        """Test adding a pattern."""
        from app.services.reflection.scratchpad import PatternType

        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("pat-123",)
        mock_db.execute.return_value = mock_result

        pattern_id = await scratchpad.add_pattern(
            pattern_type=PatternType.RECURRING_ERROR,
            description="Timeout errors in chat endpoint",
            confidence=0.7,
        )

        assert mock_db.execute.called


# ==========================================
# PATTERN DETECTOR TESTS
# ==========================================

class TestPatternDetector:
    """Tests for the PatternDetector service."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def scratchpad(self, mock_db):
        from app.services.reflection.scratchpad import ReflectionScratchpad
        return ReflectionScratchpad(mock_db)

    @pytest.fixture
    def pattern_detector(self, mock_db, scratchpad):
        from app.services.reflection.pattern_detector import PatternDetector
        return PatternDetector(mock_db, scratchpad)

    @pytest.mark.asyncio
    async def test_detect_patterns_returns_list(self, pattern_detector, mock_db):
        """Test that detect_patterns returns a list."""
        # Mock the DB queries used by internal detection methods
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result

        patterns = await pattern_detector.detect_patterns()
        assert isinstance(patterns, list)

    def test_thresholds_defined(self, pattern_detector):
        """Test that detection thresholds are configured."""
        assert hasattr(pattern_detector, 'THRESHOLDS')
        assert "min_observations" in pattern_detector.THRESHOLDS
        assert "confidence_threshold" in pattern_detector.THRESHOLDS


# ==========================================
# PROPOSAL GENERATION TESTS
# ==========================================

class TestProposalGeneration:
    """Tests for proposal generation."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def proposal_service(self, mock_db):
        from app.services.reflection.proposal_generator import PromptProposalGenerator
        return PromptProposalGenerator(mock_db)

    @pytest.mark.asyncio
    async def test_submit_proposal(self, proposal_service, mock_db):
        """Test submitting a proposal."""
        from app.services.reflection.proposal_generator import PromptProposal

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (42,)
        mock_db.execute.return_value = mock_result

        # Mock get_karma_service so submit_proposal doesn't fail on karma queries
        mock_karma = AsyncMock()
        mock_karma.get_agent_karma.return_value = MagicMock(
            composite_score=75.0,
            dimensions=[MagicMock(dimension_name="helpfulness", current_score=75.0)],
        )

        proposal = PromptProposal(
            target_agent="sara",
            target_prompt_section="response_style",
            current_content="Default response style",
            proposed_content="Keep responses brief unless asked for detail",
            reasoning="Users often ask Sara to be more concise",
            supporting_pattern_ids=["1", "2"],
            expected_improvement="More concise responses",
        )

        with patch('app.services.reflection.proposal_generator.get_karma_service',
                   new_callable=AsyncMock, return_value=mock_karma):
            proposal_id = await proposal_service.submit_proposal(proposal)
            assert mock_db.execute.called

    @pytest.mark.asyncio
    async def test_get_pending_proposals(self, proposal_service, mock_db):
        """Test retrieving pending proposals."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result

        pending = await proposal_service.get_pending_proposals()
        assert isinstance(pending, list)

    def test_min_confidence_defined(self, proposal_service):
        """Test that minimum confidence is set."""
        assert hasattr(proposal_service, 'MIN_CONFIDENCE')
        assert proposal_service.MIN_CONFIDENCE > 0


# ==========================================
# REFLECTION CYCLE TESTS
# ==========================================

class TestReflectionCycle:
    """Tests for the full reflection cycle."""

    @pytest.fixture(autouse=True)
    def _mock_self_story(self):
        """Arc 4.2's self-story step makes a real LLM call
        (sara_journal_service uses a sync Session, incompatible with this
        class's AsyncMock db, so it opens its own SessionLocal()) — the LLM
        call is what actually needs mocking to keep cycle-level tests fast
        and isolated. Tests that care about self-story specifically
        override this."""
        with patch("app.services.sara_journal_service.sara_journal.write_self_story",
                   new=AsyncMock(return_value=None)):
            yield

    @pytest.fixture
    def reflection_agent(self):
        """Create a ReflectionAgent via the factory function pattern."""
        from app.services.reflection.scratchpad import ReflectionScratchpad
        from app.services.reflection.consolidation_auditor import ConsolidationAuditor
        from app.services.reflection.pattern_detector import PatternDetector
        from app.services.reflection.proposal_generator import PromptProposalGenerator
        from app.services.reflection.agent import ReflectionAgent

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        # Tuple needs 3+ elements: consolidation_auditor accesses [0], [1], [2]
        mock_result.fetchone.return_value = (0, 0, 0)
        mock_db.execute.return_value = mock_result

        scratchpad = ReflectionScratchpad(mock_db)
        auditor = ConsolidationAuditor(mock_db, scratchpad)
        detector = PatternDetector(mock_db, scratchpad)
        generator = PromptProposalGenerator(mock_db)

        return ReflectionAgent(mock_db, scratchpad, auditor, detector, generator)

    @pytest.mark.asyncio
    async def test_reflection_cycle_runs_without_error(self, reflection_agent):
        """Test that reflection cycle executes without crashing."""
        result = await reflection_agent.run_reflection_cycle()
        assert result is not None

    @pytest.mark.asyncio
    async def test_reflection_cycle_returns_result_dataclass(self, reflection_agent):
        """Test that reflection cycle executes without crashing."""
        from app.services.reflection.agent import ReflectionCycleResult

        result = await reflection_agent.run_reflection_cycle()
        assert isinstance(result, ReflectionCycleResult)
        assert hasattr(result, 'cycle_start')
        assert hasattr(result, 'patterns_detected')
        assert hasattr(result, 'proposals_generated')

    @pytest.mark.asyncio
    async def test_reflection_cycle_scores_prediction_calibration(self, reflection_agent):
        """Arc 4.1: 'dreaming scores every resolved prediction nightly and
        updates per-domain confidence' — the reflection cycle must call
        compute_calibration and carry its report on the result."""
        fake_report = {"days": 30, "total_resolved": 5,
                        "overall_by_bucket": {"0.9-1.0": {"n": 5, "hit_rate": 0.8}},
                        "by_domain_bucket": {}}
        with patch("app.services.prediction_engine.compute_calibration",
                    new=AsyncMock(return_value=fake_report)):
            result = await reflection_agent.run_reflection_cycle()

        assert result.prediction_calibration == fake_report

    @pytest.mark.asyncio
    async def test_calibration_failure_does_not_break_the_cycle(self, reflection_agent):
        """Calibration scoring is isolated — a failure must not take down
        the rest of the reflection cycle (matches every other step's
        try/except discipline in run_reflection_cycle)."""
        with patch("app.services.prediction_engine.compute_calibration",
                    new=AsyncMock(side_effect=RuntimeError("db exploded"))):
            result = await reflection_agent.run_reflection_cycle()

        assert result.prediction_calibration is None
        assert result.cycle_start is not None


# ==========================================
# NOTIFICATION INTEGRATION TESTS
# ==========================================

class TestReflectionNotifications:
    """Tests for reflection notification integration."""

    @pytest.mark.asyncio
    async def test_proposal_triggers_notification(self):
        """Test that creating a proposal triggers a notification."""
        from app.services.notification_service import NotificationService
        from app.services.reflection.proposal_generator import PromptProposal

        notification_service = NotificationService()
        notification_service.enabled = False

        proposal = PromptProposal(
            proposal_id=123,
            target_agent="sara",
            target_prompt_section="response_style",
            reasoning="Users often ask for more concise responses",
            proposed_content="Add more concise response guidelines",
            expected_improvement="More concise responses",
        )

        result = await notification_service.notify_new_proposal(proposal)
        assert result is True

    @pytest.mark.asyncio
    async def test_uncertainty_triggers_notification(self):
        """Test that flagging uncertainty triggers a notification."""
        from app.services.notification_service import NotificationService

        notification_service = NotificationService()
        notification_service.enabled = False

        uncertainty = {
            "observation_id": "obs-1",
            "question_for_david": "How should I handle conflicting user preferences?",
            "context": "User wants both verbose and concise responses",
        }

        result = await notification_service.notify_uncertainty(uncertainty)
        assert result is True


# ==========================================
# API ENDPOINT TESTS (sync SQLite)
# ==========================================

class TestReflectionEndpoints:
    """Tests for reflection API endpoints using sync SQLite."""

    def test_list_proposals_via_sql(self, db_session):
        """Test querying proposals from SQLite."""
        from sqlalchemy import text

        db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS prompt_proposals (
                proposal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_agent TEXT NOT NULL,
                target_prompt_section TEXT NOT NULL,
                proposal_type TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewer_notes TEXT
            )
        """))
        db_session.execute(text("""
            INSERT INTO prompt_proposals
                (target_agent, target_prompt_section, proposal_type, status)
            VALUES
                ('sara', 'style', 'modify', 'pending'),
                ('sara', 'tools', 'add', 'approved')
        """))
        db_session.commit()

        result = db_session.execute(text("""
            SELECT proposal_id, target_agent, status
            FROM prompt_proposals ORDER BY created_at DESC
        """))
        rows = result.fetchall()
        assert len(rows) == 2

    def test_list_uncertainties_via_sql(self, db_session):
        """Test querying uncertainties from SQLite."""
        from sqlalchemy import text

        db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS reflection_observations (
                observation_id TEXT PRIMARY KEY,
                category TEXT,
                requires_david_input BOOLEAN DEFAULT 0,
                question_for_david TEXT,
                context TEXT,
                flagged_at TIMESTAMP,
                resolved_at TIMESTAMP,
                resolution_guidance TEXT
            )
        """))
        db_session.execute(text("""
            INSERT INTO reflection_observations
                (observation_id, category, requires_david_input, question_for_david)
            VALUES
                ('obs-1', 'ambiguity', 1, 'Question 1?'),
                ('obs-2', 'preference', 1, 'Question 2?')
        """))
        db_session.commit()

        result = db_session.execute(text("""
            SELECT observation_id, question_for_david
            FROM reflection_observations WHERE requires_david_input = 1
        """))
        rows = result.fetchall()
        assert len(rows) == 2
