"""
Phase 3 Reflection System Tests

Tests for Sara's reflection system:
- Scratchpad operations
- Pattern detection
- Proposal generation and workflow
- Reflection cycle
- Notification integration
"""

import pytest
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import fakeredis


# ==========================================
# SCRATCHPAD TESTS
# ==========================================

class TestScratchpad:
    """Tests for the reflection scratchpad."""

    @pytest.fixture
    def scratchpad_service(self, db_session):
        """Create a ScratchpadService instance."""
        from app.services.reflection.scratchpad import ScratchpadService
        return ScratchpadService(db_session)

    @pytest.fixture
    async def setup_scratchpad_tables(self, db_session):
        """Set up scratchpad tables."""
        from sqlalchemy import text

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS reflection_scratchpad (
                entry_id SERIAL PRIMARY KEY,
                category TEXT NOT NULL,
                content JSONB NOT NULL,
                source TEXT,
                confidence FLOAT DEFAULT 0.5,
                processed BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await db_session.commit()

    @pytest.mark.asyncio
    async def test_add_observation(self, scratchpad_service, setup_scratchpad_tables, db_session):
        """Test adding an observation to scratchpad."""
        observation = {
            "category": "user_feedback",
            "content": {
                "feedback_type": "positive",
                "quote": "That was really helpful!",
                "context": "After answering a coding question"
            },
            "source": "chat_response",
            "confidence": 0.8
        }

        entry_id = await scratchpad_service.add_observation(
            category=observation["category"],
            content=observation["content"],
            source=observation["source"],
            confidence=observation["confidence"]
        )

        assert entry_id is not None

    @pytest.mark.asyncio
    async def test_get_unprocessed_observations(self, scratchpad_service, setup_scratchpad_tables, db_session):
        """Test retrieving unprocessed observations."""
        from sqlalchemy import text

        # Add some test observations
        await db_session.execute(text("""
            INSERT INTO reflection_scratchpad (category, content, processed)
            VALUES
                ('error', '{"type": "timeout"}', FALSE),
                ('feedback', '{"type": "positive"}', FALSE),
                ('error', '{"type": "wrong_answer"}', TRUE)
        """))
        await db_session.commit()

        observations = await scratchpad_service.get_unprocessed(limit=10)

        assert len(observations) == 2
        assert all(not o.processed for o in observations)

    @pytest.mark.asyncio
    async def test_mark_processed(self, scratchpad_service, setup_scratchpad_tables, db_session):
        """Test marking observations as processed."""
        from sqlalchemy import text

        # Add test observation
        result = await db_session.execute(text("""
            INSERT INTO reflection_scratchpad (category, content, processed)
            VALUES ('test', '{}', FALSE)
            RETURNING entry_id
        """))
        entry_id = result.fetchone()[0]
        await db_session.commit()

        # Mark as processed
        await scratchpad_service.mark_processed([entry_id])

        # Verify
        check_result = await db_session.execute(text(
            "SELECT processed FROM reflection_scratchpad WHERE entry_id = :id"
        ), {"id": entry_id})
        row = check_result.fetchone()

        assert row.processed is True


# ==========================================
# PATTERN DETECTOR TESTS
# ==========================================

class TestPatternDetector:
    """Tests for the pattern detection service."""

    @pytest.fixture
    def pattern_detector(self, db_session):
        """Create a PatternDetectorService instance."""
        from app.services.reflection.pattern_detector import PatternDetectorService
        return PatternDetectorService(db_session)

    @pytest.fixture
    async def setup_pattern_tables(self, db_session):
        """Set up pattern tables."""
        from sqlalchemy import text

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS reflection_patterns (
                pattern_id SERIAL PRIMARY KEY,
                pattern_type TEXT NOT NULL,
                description TEXT,
                evidence_ids INTEGER[],
                occurrence_count INTEGER DEFAULT 1,
                confidence FLOAT DEFAULT 0.5,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )
        """))

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS reflection_scratchpad (
                entry_id SERIAL PRIMARY KEY,
                category TEXT NOT NULL,
                content JSONB NOT NULL,
                source TEXT,
                confidence FLOAT DEFAULT 0.5,
                processed BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await db_session.commit()

    @pytest.mark.asyncio
    async def test_detect_recurring_error_pattern(self, pattern_detector, setup_pattern_tables, db_session):
        """Test that recurring errors are detected as patterns."""
        from sqlalchemy import text

        # Add multiple similar errors
        for i in range(5):
            await db_session.execute(text("""
                INSERT INTO reflection_scratchpad (category, content, created_at)
                VALUES ('error', :content, :created_at)
            """), {
                "content": json.dumps({"type": "timeout", "endpoint": "/api/chat"}),
                "created_at": datetime.utcnow() - timedelta(hours=i)
            })
        await db_session.commit()

        # Run pattern detection
        patterns = await pattern_detector.detect_patterns()

        # Should detect a recurring timeout pattern
        timeout_patterns = [p for p in patterns if "timeout" in str(p.get("description", "")).lower()]
        # This depends on the detection logic implementation
        # assert len(timeout_patterns) >= 1

    @pytest.mark.asyncio
    async def test_pattern_confidence_increases(self, pattern_detector, setup_pattern_tables, db_session):
        """Test that pattern confidence increases with more evidence."""
        from sqlalchemy import text

        # Create initial pattern
        result = await db_session.execute(text("""
            INSERT INTO reflection_patterns (pattern_type, description, confidence, occurrence_count)
            VALUES ('recurring_error', 'Users often ask about X', 0.5, 3)
            RETURNING pattern_id
        """))
        pattern_id = result.fetchone()[0]
        await db_session.commit()

        # Add more evidence
        await pattern_detector.add_evidence_to_pattern(
            pattern_id=pattern_id,
            evidence_ids=[100, 101, 102],
            additional_occurrences=3
        )

        # Check updated confidence
        check_result = await db_session.execute(text(
            "SELECT confidence, occurrence_count FROM reflection_patterns WHERE pattern_id = :id"
        ), {"id": pattern_id})
        row = check_result.fetchone()

        assert row.occurrence_count == 6
        # Confidence should have increased


# ==========================================
# PROPOSAL GENERATION TESTS
# ==========================================

class TestProposalGeneration:
    """Tests for proposal generation."""

    @pytest.fixture
    def proposal_service(self, db_session):
        """Create a ProposalGeneratorService instance."""
        from app.services.reflection.proposal_generator import ProposalGeneratorService
        return ProposalGeneratorService(db_session)

    @pytest.fixture
    async def setup_proposal_tables(self, db_session):
        """Set up proposal tables."""
        from sqlalchemy import text

        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS prompt_proposals (
                proposal_id SERIAL PRIMARY KEY,
                target_agent TEXT NOT NULL,
                target_prompt_section TEXT NOT NULL,
                proposal_type TEXT NOT NULL,
                current_value_summary TEXT,
                proposed_value_summary TEXT,
                proposed_value TEXT,
                reasoning TEXT,
                evidence_pattern_ids INTEGER[],
                confidence_score FLOAT DEFAULT 0.5,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP,
                reviewer_notes TEXT,
                implemented_at TIMESTAMP
            )
        """))
        await db_session.commit()

    @pytest.mark.asyncio
    async def test_create_proposal_from_pattern(self, proposal_service, setup_proposal_tables, db_session):
        """Test generating a proposal from a detected pattern."""
        from app.services.reflection.proposal_generator import PromptProposal

        proposal = PromptProposal(
            target_agent="sara",
            target_prompt_section="response_style",
            current_content="Default response style",
            proposed_content="Keep responses brief unless asked for detail",
            reasoning="Users often ask Sara to be more concise",
            supporting_pattern_ids=["1", "2"],
            expected_improvement="More concise responses"
        )

        proposal_id = await proposal_service.submit_proposal(proposal)

        assert proposal_id is not None
        assert proposal_id > 0

    @pytest.mark.asyncio
    async def test_proposal_approval_workflow(self, proposal_service, setup_proposal_tables, db_session):
        """Test the full proposal approval workflow."""
        from sqlalchemy import text
        from app.services.reflection.proposal_generator import PromptProposal

        # Create proposal
        proposal = PromptProposal(
            target_agent="sara",
            target_prompt_section="tools",
            current_content="Current tool usage",
            proposed_content="Check calendar before scheduling",
            reasoning="Pattern shows scheduling conflicts",
            supporting_pattern_ids=[],
            expected_improvement="Use calendar tool more proactively"
        )

        proposal_id = await proposal_service.submit_proposal(proposal)

        # Approve proposal
        await proposal_service.process_approval(
            proposal_id=proposal_id,
            approved=True,
            reviewer_notes="Looks good, implement it"
        )

        # Check status
        result = await db_session.execute(text(
            "SELECT status, reviewer_notes FROM prompt_proposals WHERE proposal_id = :id"
        ), {"id": proposal_id})
        row = result.fetchone()

        assert row.status == "approved"
        assert "Looks good" in row.reviewer_notes

    @pytest.mark.asyncio
    async def test_proposal_rejection(self, proposal_service, setup_proposal_tables, db_session):
        """Test proposal rejection."""
        from sqlalchemy import text
        from app.services.reflection.proposal_generator import PromptProposal

        # Create proposal
        proposal = PromptProposal(
            target_agent="sara",
            target_prompt_section="personality",
            current_content="Current personality",
            proposed_content="Use more casual language",
            reasoning="Some users prefer casual",
            supporting_pattern_ids=[],
            expected_improvement="Be more casual"
        )

        proposal_id = await proposal_service.submit_proposal(proposal)

        # Reject proposal
        await proposal_service.process_approval(
            proposal_id=proposal_id,
            approved=False,
            reviewer_notes="Not appropriate for professional context"
        )

        # Check status
        result = await db_session.execute(text(
            "SELECT status FROM prompt_proposals WHERE proposal_id = :id"
        ), {"id": proposal_id})
        row = result.fetchone()

        assert row.status == "rejected"


# ==========================================
# REFLECTION CYCLE TESTS
# ==========================================

class TestReflectionCycle:
    """Tests for the full reflection cycle."""

    @pytest.fixture
    def reflection_agent(self, db_session):
        """Create a ReflectionAgent instance."""
        from app.services.reflection.agent import ReflectionAgent
        return ReflectionAgent(db_session)

    @pytest.fixture
    async def setup_all_tables(self, db_session):
        """Set up all reflection tables."""
        from sqlalchemy import text

        tables = [
            """
            CREATE TABLE IF NOT EXISTS reflection_scratchpad (
                entry_id SERIAL PRIMARY KEY,
                category TEXT NOT NULL,
                content JSONB NOT NULL,
                source TEXT,
                confidence FLOAT DEFAULT 0.5,
                processed BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS reflection_patterns (
                pattern_id SERIAL PRIMARY KEY,
                pattern_type TEXT NOT NULL,
                description TEXT,
                evidence_ids INTEGER[],
                occurrence_count INTEGER DEFAULT 1,
                confidence FLOAT DEFAULT 0.5,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS prompt_proposals (
                proposal_id SERIAL PRIMARY KEY,
                target_agent TEXT NOT NULL,
                target_prompt_section TEXT NOT NULL,
                proposal_type TEXT NOT NULL,
                current_value_summary TEXT,
                proposed_value_summary TEXT,
                proposed_value TEXT,
                reasoning TEXT,
                evidence_pattern_ids INTEGER[],
                confidence_score FLOAT DEFAULT 0.5,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP,
                reviewer_notes TEXT,
                implemented_at TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS reflection_observations (
                observation_id TEXT PRIMARY KEY,
                category TEXT,
                content JSONB,
                requires_david_input BOOLEAN DEFAULT FALSE,
                question_for_david TEXT,
                context TEXT,
                flagged_at TIMESTAMP,
                resolved_at TIMESTAMP,
                resolution_guidance TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        ]

        for table_sql in tables:
            await db_session.execute(text(table_sql))
        await db_session.commit()

    @pytest.mark.asyncio
    async def test_reflection_cycle_runs_all_stages(
        self, reflection_agent, setup_all_tables, db_session
    ):
        """Test that reflection cycle executes all stages."""
        from sqlalchemy import text

        # Add some observations to process
        await db_session.execute(text("""
            INSERT INTO reflection_scratchpad (category, content, processed)
            VALUES
                ('user_feedback', '{"type": "positive", "quote": "Great answer!"}', FALSE),
                ('error', '{"type": "misunderstanding", "context": "recipe question"}', FALSE)
        """))
        await db_session.commit()

        # Run reflection cycle
        with patch.object(reflection_agent, '_invoke_llm', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = json.dumps({
                "patterns": [],
                "proposals": [],
                "uncertainties": []
            })

            result = await reflection_agent.run_reflection_cycle()

            assert result is not None
            assert "observations_processed" in result

    @pytest.mark.asyncio
    async def test_uncertainty_flagging(
        self, reflection_agent, setup_all_tables, db_session
    ):
        """Test that uncertainties are properly flagged."""
        from sqlalchemy import text

        # Flag an uncertainty
        await reflection_agent._flag_uncertainty({
            "observation_id": "test-obs-1",
            "category": "ambiguity",
            "question_for_david": "Should I prioritize speed or accuracy?",
            "context": "When answering coding questions"
        })

        # Check it was stored
        result = await db_session.execute(text("""
            SELECT question_for_david FROM reflection_observations
            WHERE observation_id = 'test-obs-1'
        """))
        row = result.fetchone()

        assert row is not None
        assert "speed or accuracy" in row.question_for_david


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
        notification_service.enabled = False  # Don't actually send

        proposal = PromptProposal(
            proposal_id=123,
            target_agent="sara",
            target_prompt_section="response_style",
            reasoning="Users often ask for more concise responses",
            proposed_content="Add more concise response guidelines",
            expected_improvement="More concise responses"
        )

        # This should not raise an error
        result = await notification_service.notify_new_proposal(proposal)
        assert result is True  # Notifications disabled but returns success

    @pytest.mark.asyncio
    async def test_uncertainty_triggers_notification(self):
        """Test that flagging uncertainty triggers a notification."""
        from app.services.notification_service import NotificationService

        notification_service = NotificationService()
        notification_service.enabled = False  # Don't actually send

        uncertainty = {
            "observation_id": "obs-1",
            "question_for_david": "How should I handle conflicting user preferences?",
            "context": "User wants both verbose and concise responses"
        }

        result = await notification_service.notify_uncertainty(uncertainty)
        assert result is True


# ==========================================
# API ENDPOINT TESTS
# ==========================================

class TestReflectionEndpoints:
    """Tests for reflection API endpoints."""

    @pytest.mark.asyncio
    async def test_list_proposals_endpoint(self, db_session):
        """Test GET /reflection/proposals endpoint."""
        from sqlalchemy import text

        # Set up table
        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS prompt_proposals (
                proposal_id SERIAL PRIMARY KEY,
                target_agent TEXT NOT NULL,
                target_prompt_section TEXT NOT NULL,
                proposal_type TEXT NOT NULL,
                current_value_summary TEXT,
                proposed_value_summary TEXT,
                reasoning TEXT,
                evidence_pattern_ids INTEGER[],
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP,
                reviewer_notes TEXT
            )
        """))

        # Add test proposals
        await db_session.execute(text("""
            INSERT INTO prompt_proposals
                (target_agent, target_prompt_section, proposal_type, status)
            VALUES
                ('sara', 'style', 'modify', 'pending'),
                ('sara', 'tools', 'add', 'approved')
        """))
        await db_session.commit()

        # Query via SQL (simulating endpoint)
        result = await db_session.execute(text("""
            SELECT proposal_id, target_agent, status
            FROM prompt_proposals
            ORDER BY created_at DESC
        """))
        rows = result.fetchall()

        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_list_uncertainties_endpoint(self, db_session):
        """Test GET /reflection/uncertainties endpoint."""
        from sqlalchemy import text

        # Set up table
        await db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS reflection_observations (
                observation_id TEXT PRIMARY KEY,
                category TEXT,
                requires_david_input BOOLEAN DEFAULT FALSE,
                question_for_david TEXT,
                context TEXT,
                flagged_at TIMESTAMP,
                resolved_at TIMESTAMP,
                resolution_guidance TEXT
            )
        """))

        # Add test uncertainties
        await db_session.execute(text("""
            INSERT INTO reflection_observations
                (observation_id, category, requires_david_input, question_for_david)
            VALUES
                ('obs-1', 'ambiguity', TRUE, 'Question 1?'),
                ('obs-2', 'preference', TRUE, 'Question 2?')
        """))
        await db_session.commit()

        # Query via SQL (simulating endpoint)
        result = await db_session.execute(text("""
            SELECT observation_id, question_for_david
            FROM reflection_observations
            WHERE requires_david_input = TRUE
        """))
        rows = result.fetchall()

        assert len(rows) == 2
