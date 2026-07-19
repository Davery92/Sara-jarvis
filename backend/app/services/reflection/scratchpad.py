"""
ReflectionScratchpad - The reflection agent's extended memory.

Manages observations, patterns, and hypotheses that enable
the reflection agent to identify trends and propose improvements.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ObservationType(str, Enum):
    """Types of observations the reflection agent can make."""
    CONSOLIDATION_AUDIT = "consolidation_audit"
    ACTION_OUTCOME = "action_outcome"
    PATTERN_DETECTED = "pattern_detected"
    HYPOTHESIS = "hypothesis"
    UNCERTAINTY_FLAG = "uncertainty_flag"


class PatternType(str, Enum):
    """Types of patterns that can be detected."""
    RECURRING_ERROR = "recurring_error"
    MISSED_OPPORTUNITY = "missed_opportunity"
    SUCCESSFUL_APPROACH = "successful_approach"
    CALIBRATION_ISSUE = "calibration_issue"
    TIMING_PATTERN = "timing_pattern"
    CONSOLIDATION_ISSUE = "consolidation_issue"


class PatternStatus(str, Enum):
    """Status of detected patterns."""
    ACTIVE = "active"
    ADDRESSED = "addressed"
    DISMISSED = "dismissed"
    MONITORING = "monitoring"


# Retention policy for different observation types
RETENTION_POLICY = {
    ObservationType.CONSOLIDATION_AUDIT: timedelta(days=7),
    ObservationType.ACTION_OUTCOME: timedelta(days=14),
    ObservationType.PATTERN_DETECTED: timedelta(days=30),
    ObservationType.HYPOTHESIS: timedelta(days=60),
    ObservationType.UNCERTAINTY_FLAG: timedelta(days=7),
}


@dataclass
class Observation:
    """A reflection observation."""
    observation_id: int
    observation_type: ObservationType
    subject_agent: Optional[str]
    subject_dimension: Optional[str]
    summary: str
    details: Optional[Dict]
    confidence: float
    evidence_refs: Optional[Dict]
    pattern_id: Optional[str]
    resolved: bool
    resolution: Optional[str]
    created_at: datetime
    expires_at: Optional[datetime]


@dataclass
class Pattern:
    """A detected pattern."""
    pattern_id: str
    pattern_type: PatternType
    description: str
    affected_agent: Optional[str]
    affected_dimension: Optional[str]
    observation_count: int
    first_observed: datetime
    last_observed: datetime
    confidence: float
    status: PatternStatus
    proposed_action: Optional[str]
    action_taken: Optional[str]
    metadata: Optional[Dict]


@dataclass
class Hypothesis:
    """A hypothesis being tested."""
    hypothesis_id: int
    hypothesis: str
    supporting_evidence: List[Dict]
    contradicting_evidence: List[Dict]
    confidence: float
    test_criteria: Optional[str]
    test_deadline: Optional[datetime]
    status: str
    outcome: Optional[str]
    created_at: datetime


class ReflectionScratchpad:
    """
    The reflection agent's extended memory system.

    Stores and queries:
    - Observations (audits, outcomes, detected patterns)
    - Patterns (recurring issues or successful approaches)
    - Hypotheses (things being tested)
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ===========================================
    # Observation Management
    # ===========================================

    async def add_observation(
        self,
        observation_type: ObservationType,
        summary: str,
        subject_agent: Optional[str] = None,
        subject_dimension: Optional[str] = None,
        details: Optional[Dict] = None,
        confidence: float = 0.5,
        evidence_refs: Optional[Dict] = None,
        pattern_id: Optional[str] = None,
    ) -> int:
        """Add a new observation to the scratchpad."""
        # Calculate expiration based on type. reflection_observations.expires_at is
        # a naive `timestamp` column (naive UTC); bind naive to satisfy asyncpg.
        from app.core.timezone import to_naive_utc
        retention = RETENTION_POLICY.get(observation_type)
        expires_at = to_naive_utc(datetime.now(timezone.utc) + retention) if retention else None

        result = await self.db.execute(
            text("""
                INSERT INTO reflection_observations
                (observation_type, subject_agent, subject_dimension, summary,
                 details, confidence, evidence_refs, pattern_id, expires_at)
                VALUES
                (:obs_type, :agent, :dimension, :summary,
                 :details, :confidence, :evidence, :pattern_id, :expires)
                RETURNING observation_id
            """),
            {
                "obs_type": observation_type.value,
                "agent": subject_agent,
                "dimension": subject_dimension,
                "summary": summary,
                "details": json.dumps(details) if details else None,
                "confidence": confidence,
                "evidence": json.dumps(evidence_refs) if evidence_refs else None,
                "pattern_id": pattern_id,
                "expires": expires_at,
            }
        )
        await self.db.commit()

        obs_id = result.fetchone()[0]
        logger.info(f"Added observation {obs_id}: {observation_type.value} - {summary[:50]}")
        return obs_id

    async def get_observation(self, observation_id: int) -> Optional[Observation]:
        """Get a specific observation by ID."""
        result = await self.db.execute(
            text("""
                SELECT observation_id, observation_type, subject_agent, subject_dimension,
                       summary, details, confidence, evidence_refs, pattern_id,
                       resolved, resolution, created_at, expires_at
                FROM reflection_observations
                WHERE observation_id = :obs_id
            """),
            {"obs_id": observation_id}
        )
        row = result.fetchone()
        if not row:
            return None

        return Observation(
            observation_id=row[0],
            observation_type=ObservationType(row[1]),
            subject_agent=row[2],
            subject_dimension=row[3],
            summary=row[4],
            details=row[5],
            confidence=row[6],
            evidence_refs=row[7],
            pattern_id=row[8],
            resolved=row[9],
            resolution=row[10],
            created_at=row[11],
            expires_at=row[12],
        )

    async def get_recent_observations(
        self,
        days: int = 7,
        observation_type: Optional[ObservationType] = None,
        subject_agent: Optional[str] = None,
        limit: int = 100,
    ) -> List[Observation]:
        """Get recent observations, optionally filtered."""
        query = """
            SELECT observation_id, observation_type, subject_agent, subject_dimension,
                   summary, details, confidence, evidence_refs, pattern_id,
                   resolved, resolution, created_at, expires_at
            FROM reflection_observations
            WHERE created_at > NOW() - INTERVAL '%s days'
            AND (expires_at IS NULL OR expires_at > NOW())
        """ % days

        params = {}

        if observation_type:
            query += " AND observation_type = :obs_type"
            params["obs_type"] = observation_type.value

        if subject_agent:
            query += " AND subject_agent = :agent"
            params["agent"] = subject_agent

        query += " ORDER BY created_at DESC LIMIT :limit"
        params["limit"] = limit

        result = await self.db.execute(text(query), params)

        observations = []
        for row in result.fetchall():
            observations.append(Observation(
                observation_id=row[0],
                observation_type=ObservationType(row[1]),
                subject_agent=row[2],
                subject_dimension=row[3],
                summary=row[4],
                details=row[5],
                confidence=row[6],
                evidence_refs=row[7],
                pattern_id=row[8],
                resolved=row[9],
                resolution=row[10],
                created_at=row[11],
                expires_at=row[12],
            ))

        return observations

    async def update_observation(
        self,
        observation_id: int,
        resolved: Optional[bool] = None,
        resolution: Optional[str] = None,
        confidence: Optional[float] = None,
        pattern_id: Optional[str] = None,
    ) -> None:
        """Update an observation."""
        updates = []
        params = {"obs_id": observation_id}

        if resolved is not None:
            updates.append("resolved = :resolved")
            params["resolved"] = resolved

        if resolution is not None:
            updates.append("resolution = :resolution")
            params["resolution"] = resolution

        if confidence is not None:
            updates.append("confidence = :confidence")
            params["confidence"] = confidence

        if pattern_id is not None:
            updates.append("pattern_id = :pattern_id")
            params["pattern_id"] = pattern_id

        if not updates:
            return

        await self.db.execute(
            text(f"UPDATE reflection_observations SET {', '.join(updates)} WHERE observation_id = :obs_id"),
            params
        )
        await self.db.commit()

    # ===========================================
    # Pattern Management
    # ===========================================

    async def add_pattern(
        self,
        pattern_type: PatternType,
        description: str,
        affected_agent: Optional[str] = None,
        affected_dimension: Optional[str] = None,
        confidence: float = 0.5,
        proposed_action: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> str:
        """Add or update a detected pattern."""
        pattern_id = f"{pattern_type.value}_{uuid.uuid4().hex[:8]}"

        await self.db.execute(
            text("""
                INSERT INTO reflection_patterns
                (pattern_id, pattern_type, description, affected_agent, affected_dimension,
                 observation_count, first_observed, last_observed, confidence,
                 proposed_action, metadata)
                VALUES
                (:pattern_id, :pattern_type, :description, :agent, :dimension,
                 1, NOW(), NOW(), :confidence, :proposed_action, :metadata)
            """),
            {
                "pattern_id": pattern_id,
                "pattern_type": pattern_type.value,
                "description": description,
                "agent": affected_agent,
                "dimension": affected_dimension,
                "confidence": confidence,
                "proposed_action": proposed_action,
                "metadata": json.dumps(metadata) if metadata else None,
            }
        )
        await self.db.commit()

        logger.info(f"Added pattern {pattern_id}: {description[:50]}")
        return pattern_id

    async def get_pattern(self, pattern_id: str) -> Optional[Pattern]:
        """Get a pattern by ID."""
        result = await self.db.execute(
            text("""
                SELECT pattern_id, pattern_type, description, affected_agent, affected_dimension,
                       observation_count, first_observed, last_observed, confidence, status,
                       proposed_action, action_taken, metadata
                FROM reflection_patterns
                WHERE pattern_id = :pattern_id
            """),
            {"pattern_id": pattern_id}
        )
        row = result.fetchone()
        if not row:
            return None

        return Pattern(
            pattern_id=row[0],
            pattern_type=PatternType(row[1]),
            description=row[2],
            affected_agent=row[3],
            affected_dimension=row[4],
            observation_count=row[5],
            first_observed=row[6],
            last_observed=row[7],
            confidence=row[8],
            status=PatternStatus(row[9]),
            proposed_action=row[10],
            action_taken=row[11],
            metadata=row[12],
        )

    async def get_active_patterns(
        self,
        pattern_type: Optional[PatternType] = None,
        min_confidence: float = 0.0,
    ) -> List[Pattern]:
        """Get active patterns, optionally filtered."""
        query = """
            SELECT pattern_id, pattern_type, description, affected_agent, affected_dimension,
                   observation_count, first_observed, last_observed, confidence, status,
                   proposed_action, action_taken, metadata
            FROM reflection_patterns
            WHERE status = 'active'
            AND confidence >= :min_confidence
        """
        params = {"min_confidence": min_confidence}

        if pattern_type:
            query += " AND pattern_type = :pattern_type"
            params["pattern_type"] = pattern_type.value

        query += " ORDER BY confidence DESC, observation_count DESC"

        result = await self.db.execute(text(query), params)

        patterns = []
        for row in result.fetchall():
            patterns.append(Pattern(
                pattern_id=row[0],
                pattern_type=PatternType(row[1]),
                description=row[2],
                affected_agent=row[3],
                affected_dimension=row[4],
                observation_count=row[5],
                first_observed=row[6],
                last_observed=row[7],
                confidence=row[8],
                status=PatternStatus(row[9]),
                proposed_action=row[10],
                action_taken=row[11],
                metadata=row[12],
            ))

        return patterns

    async def update_pattern(
        self,
        pattern_id: str,
        observation_count_delta: int = 0,
        confidence: Optional[float] = None,
        status: Optional[PatternStatus] = None,
        action_taken: Optional[str] = None,
    ) -> None:
        """Update a pattern."""
        updates = ["last_observed = NOW()", "updated_at = NOW()"]
        params = {"pattern_id": pattern_id}

        if observation_count_delta:
            updates.append(f"observation_count = observation_count + {observation_count_delta}")

        if confidence is not None:
            updates.append("confidence = :confidence")
            params["confidence"] = confidence

        if status is not None:
            updates.append("status = :status")
            params["status"] = status.value

        if action_taken is not None:
            updates.append("action_taken = :action_taken")
            params["action_taken"] = action_taken

        await self.db.execute(
            text(f"UPDATE reflection_patterns SET {', '.join(updates)} WHERE pattern_id = :pattern_id"),
            params
        )
        await self.db.commit()

    # ===========================================
    # Hypothesis Management
    # ===========================================

    async def add_hypothesis(
        self,
        hypothesis: str,
        test_criteria: Optional[str] = None,
        test_deadline: Optional[datetime] = None,
    ) -> int:
        """Add a new hypothesis to test."""
        result = await self.db.execute(
            text("""
                INSERT INTO reflection_hypotheses
                (hypothesis, test_criteria, test_deadline)
                VALUES (:hypothesis, :criteria, :deadline)
                RETURNING hypothesis_id
            """),
            {
                "hypothesis": hypothesis,
                "criteria": test_criteria,
                "deadline": test_deadline,
            }
        )
        await self.db.commit()

        hyp_id = result.fetchone()[0]
        logger.info(f"Added hypothesis {hyp_id}: {hypothesis[:50]}")
        return hyp_id

    async def update_hypothesis(
        self,
        hypothesis_id: int,
        supporting_evidence: Optional[List[Dict]] = None,
        contradicting_evidence: Optional[List[Dict]] = None,
        confidence: Optional[float] = None,
        status: Optional[str] = None,
        outcome: Optional[str] = None,
    ) -> None:
        """Update a hypothesis."""
        updates = ["updated_at = NOW()"]
        params = {"hyp_id": hypothesis_id}

        if supporting_evidence is not None:
            updates.append("supporting_evidence = :supporting")
            params["supporting"] = supporting_evidence

        if contradicting_evidence is not None:
            updates.append("contradicting_evidence = :contradicting")
            params["contradicting"] = contradicting_evidence

        if confidence is not None:
            updates.append("confidence = :confidence")
            params["confidence"] = confidence

        if status is not None:
            updates.append("status = :status")
            params["status"] = status

        if outcome is not None:
            updates.append("outcome = :outcome")
            params["outcome"] = outcome

        await self.db.execute(
            text(f"UPDATE reflection_hypotheses SET {', '.join(updates)} WHERE hypothesis_id = :hyp_id"),
            params
        )
        await self.db.commit()

    async def get_pending_hypotheses(self) -> List[Hypothesis]:
        """Get hypotheses that need evaluation."""
        result = await self.db.execute(
            text("""
                SELECT hypothesis_id, hypothesis, supporting_evidence, contradicting_evidence,
                       confidence, test_criteria, test_deadline, status, outcome, created_at
                FROM reflection_hypotheses
                WHERE status = 'testing'
                AND (test_deadline IS NULL OR test_deadline <= NOW())
                ORDER BY created_at
            """)
        )

        hypotheses = []
        for row in result.fetchall():
            hypotheses.append(Hypothesis(
                hypothesis_id=row[0],
                hypothesis=row[1],
                supporting_evidence=row[2] or [],
                contradicting_evidence=row[3] or [],
                confidence=row[4],
                test_criteria=row[5],
                test_deadline=row[6],
                status=row[7],
                outcome=row[8],
                created_at=row[9],
            ))

        return hypotheses

    # ===========================================
    # Cleanup
    # ===========================================

    async def cleanup_expired(self) -> int:
        """Remove expired observations."""
        result = await self.db.execute(
            text("""
                DELETE FROM reflection_observations
                WHERE expires_at IS NOT NULL AND expires_at < NOW()
            """)
        )
        await self.db.commit()

        count = result.rowcount
        if count:
            logger.info(f"Cleaned up {count} expired observations")
        return count

    async def get_scratchpad_summary(self) -> Dict[str, Any]:
        """Get a summary of scratchpad contents for the reflection agent."""
        # Count observations by type
        obs_result = await self.db.execute(
            text("""
                SELECT observation_type, COUNT(*)
                FROM reflection_observations
                WHERE (expires_at IS NULL OR expires_at > NOW())
                AND created_at > NOW() - INTERVAL '7 days'
                GROUP BY observation_type
            """)
        )
        observation_counts = dict(obs_result.fetchall())

        # Count active patterns
        pattern_result = await self.db.execute(
            text("""
                SELECT COUNT(*), AVG(confidence)
                FROM reflection_patterns
                WHERE status = 'active'
            """)
        )
        pattern_row = pattern_result.fetchone()

        # Count pending hypotheses
        hyp_result = await self.db.execute(
            text("""
                SELECT COUNT(*)
                FROM reflection_hypotheses
                WHERE status = 'testing'
            """)
        )
        hyp_count = hyp_result.fetchone()[0]

        return {
            "observation_counts": observation_counts,
            "active_patterns": pattern_row[0] if pattern_row else 0,
            "avg_pattern_confidence": round(pattern_row[1], 2) if pattern_row and pattern_row[1] else 0,
            "pending_hypotheses": hyp_count,
        }


# Singleton instance
_scratchpad: Optional[ReflectionScratchpad] = None


async def get_reflection_scratchpad(db: AsyncSession) -> ReflectionScratchpad:
    """Get or create ReflectionScratchpad instance."""
    global _scratchpad
    if _scratchpad is None or _scratchpad.db != db:
        _scratchpad = ReflectionScratchpad(db)
    return _scratchpad
