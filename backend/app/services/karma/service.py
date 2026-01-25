"""
KarmaService - Performance tracking for Sara's cognitive agents.

Provides multi-dimensional karma tracking with:
- Score recording and retrieval
- Trend analysis
- Decay mechanics (drift toward neutral)
- Dashboard aggregation
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class KarmaThreshold(str, Enum):
    """Karma score threshold levels."""
    CRITICAL_LOW = "critical_low"
    LOW = "low"
    NEUTRAL = "neutral"
    GOOD = "good"
    EXCELLENT = "excellent"


@dataclass
class KarmaEvent:
    """A karma-affecting event."""
    agent_id: str
    dimension_name: str
    delta: float
    reason: str
    evidence_type: Optional[str] = None
    evidence_ids: Optional[List[str]] = None


@dataclass
class KarmaDimension:
    """Current state of a karma dimension."""
    dimension_name: str
    current_score: float
    trend: float
    threshold: KarmaThreshold
    last_updated: datetime
    weight: float
    description: Optional[str] = None


@dataclass
class AgentKarma:
    """Complete karma state for an agent."""
    agent_id: str
    agent_type: str
    display_name: str
    description: Optional[str]
    dimensions: List[KarmaDimension]
    composite_score: float
    overall_threshold: KarmaThreshold
    is_active: bool


class KarmaService:
    """
    Service for managing karma scores across Sara's cognitive agents.

    Karma provides "skin in the game" for agents through:
    - Multi-dimensional performance tracking
    - Historical trend analysis
    - Configurable decay toward neutral
    - Threshold-based alerts
    """

    # Default thresholds (loaded from DB config on init)
    DEFAULT_THRESHOLDS = {
        "critical_low": 20,
        "low": 35,
        "neutral": 50,
        "good": 65,
        "excellent": 80
    }

    DEFAULT_SCORE_BOUNDS = {
        "min": 0,
        "max": 100,
        "starting": 50
    }

    def __init__(self, db: AsyncSession):
        self.db = db
        self._config_cache: Optional[Dict] = None
        self._config_loaded_at: Optional[datetime] = None

    async def _get_config(self) -> Dict:
        """Get karma configuration, with caching."""
        # Cache config for 5 minutes
        if (self._config_cache and self._config_loaded_at and
            datetime.utcnow() - self._config_loaded_at < timedelta(minutes=5)):
            return self._config_cache

        result = await self.db.execute(
            text("SELECT config_value FROM karma_config WHERE config_key = 'karma_settings'")
        )
        row = result.fetchone()

        if row:
            self._config_cache = row[0]
            self._config_loaded_at = datetime.utcnow()
            return self._config_cache

        # Return defaults if no config
        return {
            "thresholds": self.DEFAULT_THRESHOLDS,
            "score_bounds": self.DEFAULT_SCORE_BOUNDS
        }

    def _score_to_threshold(self, score: float, thresholds: Dict) -> KarmaThreshold:
        """Convert a score to its threshold level."""
        if score < thresholds.get("critical_low", 20):
            return KarmaThreshold.CRITICAL_LOW
        elif score < thresholds.get("low", 35):
            return KarmaThreshold.LOW
        elif score < thresholds.get("good", 65):
            return KarmaThreshold.NEUTRAL
        elif score < thresholds.get("excellent", 80):
            return KarmaThreshold.GOOD
        else:
            return KarmaThreshold.EXCELLENT

    async def get_agent_karma(self, agent_id: str) -> Optional[AgentKarma]:
        """
        Get complete karma state for an agent.

        Returns all dimensions with current scores, trends, and thresholds.
        """
        config = await self._get_config()
        thresholds = config.get("thresholds", self.DEFAULT_THRESHOLDS)

        # Get agent info
        agent_result = await self.db.execute(
            text("""
                SELECT agent_id, agent_type, display_name, description, is_active
                FROM karma_agents WHERE agent_id = :agent_id
            """),
            {"agent_id": agent_id}
        )
        agent_row = agent_result.fetchone()

        if not agent_row:
            return None

        # Get dimensions with scores
        dims_result = await self.db.execute(
            text("""
                SELECT
                    d.dimension_name,
                    d.description,
                    d.weight,
                    COALESCE(s.current_score, 50.0) as current_score,
                    COALESCE(s.trend, 0.0) as trend,
                    COALESCE(s.last_updated, NOW()) as last_updated
                FROM karma_dimensions d
                LEFT JOIN karma_scores s ON d.agent_id = s.agent_id
                    AND d.dimension_name = s.dimension_name
                WHERE d.agent_id = :agent_id
                ORDER BY d.weight DESC, d.dimension_name
            """),
            {"agent_id": agent_id}
        )

        dimensions = []
        total_weighted_score = 0.0
        total_weight = 0.0

        for row in dims_result.fetchall():
            dim = KarmaDimension(
                dimension_name=row[0],
                description=row[1],
                weight=row[2],
                current_score=row[3],
                trend=row[4],
                last_updated=row[5],
                threshold=self._score_to_threshold(row[3], thresholds)
            )
            dimensions.append(dim)
            total_weighted_score += dim.current_score * dim.weight
            total_weight += dim.weight

        # Calculate composite score
        composite_score = total_weighted_score / total_weight if total_weight > 0 else 50.0

        return AgentKarma(
            agent_id=agent_row[0],
            agent_type=agent_row[1],
            display_name=agent_row[2],
            description=agent_row[3],
            is_active=agent_row[4],
            dimensions=dimensions,
            composite_score=composite_score,
            overall_threshold=self._score_to_threshold(composite_score, thresholds)
        )

    async def record_event(self, event: KarmaEvent) -> float:
        """
        Record a karma-affecting event and update scores.

        Args:
            event: The karma event to record

        Returns:
            The new score after applying the delta
        """
        config = await self._get_config()
        bounds = config.get("score_bounds", self.DEFAULT_SCORE_BOUNDS)
        min_score = bounds.get("min", 0)
        max_score = bounds.get("max", 100)

        # Get current score
        result = await self.db.execute(
            text("""
                SELECT current_score FROM karma_scores
                WHERE agent_id = :agent_id AND dimension_name = :dimension
            """),
            {"agent_id": event.agent_id, "dimension": event.dimension_name}
        )
        row = result.fetchone()
        current_score = row[0] if row else 50.0

        # Apply delta with bounds
        new_score = max(min_score, min(max_score, current_score + event.delta))

        # Calculate trend from recent events
        trend_result = await self.db.execute(
            text("""
                SELECT AVG(delta) FROM (
                    SELECT delta FROM karma_events
                    WHERE agent_id = :agent_id
                    AND dimension_name = :dimension
                    AND created_at > NOW() - INTERVAL '72 hours'
                    ORDER BY created_at DESC
                    LIMIT 10
                ) recent
            """),
            {"agent_id": event.agent_id, "dimension": event.dimension_name}
        )
        trend_row = trend_result.fetchone()
        trend = trend_row[0] if trend_row and trend_row[0] else 0.0

        # Update or insert score
        await self.db.execute(
            text("""
                INSERT INTO karma_scores (agent_id, dimension_name, current_score, trend, last_updated)
                VALUES (:agent_id, :dimension, :score, :trend, NOW())
                ON CONFLICT (agent_id, dimension_name)
                DO UPDATE SET
                    current_score = :score,
                    trend = :trend,
                    last_updated = NOW()
            """),
            {
                "agent_id": event.agent_id,
                "dimension": event.dimension_name,
                "score": new_score,
                "trend": trend
            }
        )

        # Record the event
        evidence_ids = event.evidence_ids if event.evidence_ids else []
        await self.db.execute(
            text("""
                INSERT INTO karma_events
                (agent_id, dimension_name, delta, new_score, reason, evidence_type, evidence_ids)
                VALUES (:agent_id, :dimension, :delta, :new_score, :reason, :evidence_type, :evidence_ids)
            """),
            {
                "agent_id": event.agent_id,
                "dimension": event.dimension_name,
                "delta": event.delta,
                "new_score": new_score,
                "reason": event.reason,
                "evidence_type": event.evidence_type,
                "evidence_ids": evidence_ids
            }
        )

        await self.db.commit()

        logger.info(
            f"Karma event: {event.agent_id}/{event.dimension_name} "
            f"{current_score:.1f} -> {new_score:.1f} ({event.delta:+.1f}) - {event.reason}"
        )

        return new_score

    async def apply_decay(self, agent_id: Optional[str] = None) -> Dict[str, List[Dict]]:
        """
        Apply karma decay - drift scores toward neutral.

        Scores above min_score_for_decay drift down.
        Scores below max_score_for_recovery drift up.

        Args:
            agent_id: Optional specific agent to decay (None = all agents)

        Returns:
            Dict mapping agent_id to list of decay events applied
        """
        config = await self._get_config()
        decay_config = config.get("decay", {})

        if not decay_config.get("enabled", True):
            return {}

        rate = decay_config.get("rate_per_day", 1.0)
        target = decay_config.get("target", 50)
        min_for_decay = decay_config.get("min_score_for_decay", 55)
        max_for_recovery = decay_config.get("max_score_for_recovery", 45)

        # Get scores that need decay
        query = """
            SELECT s.agent_id, s.dimension_name, s.current_score
            FROM karma_scores s
            JOIN karma_agents a ON s.agent_id = a.agent_id
            WHERE a.is_active = TRUE
            AND (s.current_score > :min_for_decay OR s.current_score < :max_for_recovery)
        """
        params = {"min_for_decay": min_for_decay, "max_for_recovery": max_for_recovery}

        if agent_id:
            query += " AND s.agent_id = :agent_id"
            params["agent_id"] = agent_id

        result = await self.db.execute(text(query), params)

        decay_events = {}

        for row in result.fetchall():
            aid, dimension, current = row[0], row[1], row[2]

            # Calculate decay direction and amount
            if current > min_for_decay:
                # Decay down toward target
                delta = -min(rate, current - target)
            elif current < max_for_recovery:
                # Recover up toward target
                delta = min(rate, target - current)
            else:
                continue

            if abs(delta) < 0.01:
                continue

            event = KarmaEvent(
                agent_id=aid,
                dimension_name=dimension,
                delta=delta,
                reason="Natural decay toward neutral",
                evidence_type="decay"
            )

            await self.record_event(event)

            if aid not in decay_events:
                decay_events[aid] = []
            decay_events[aid].append({
                "dimension": dimension,
                "delta": delta,
                "old_score": current,
                "new_score": current + delta
            })

        return decay_events

    async def get_karma_dashboard(self) -> Dict[str, Any]:
        """
        Get aggregated karma dashboard for all agents.

        Returns overview suitable for monitoring and display.
        """
        config = await self._get_config()
        thresholds = config.get("thresholds", self.DEFAULT_THRESHOLDS)

        # Get all active agents with their composite scores
        result = await self.db.execute(
            text("""
                SELECT
                    a.agent_id,
                    a.display_name,
                    a.agent_type,
                    COALESCE(
                        SUM(s.current_score * d.weight) / NULLIF(SUM(d.weight), 0),
                        50.0
                    ) as composite_score,
                    COUNT(DISTINCT d.dimension_name) as dimension_count
                FROM karma_agents a
                LEFT JOIN karma_dimensions d ON a.agent_id = d.agent_id
                LEFT JOIN karma_scores s ON d.agent_id = s.agent_id
                    AND d.dimension_name = s.dimension_name
                WHERE a.is_active = TRUE
                GROUP BY a.agent_id, a.display_name, a.agent_type
                ORDER BY composite_score DESC
            """)
        )

        agents = []
        alerts = []

        for row in result.fetchall():
            agent_id, display_name, agent_type, composite, dim_count = row
            threshold = self._score_to_threshold(composite, thresholds)

            agents.append({
                "agent_id": agent_id,
                "display_name": display_name,
                "agent_type": agent_type,
                "composite_score": round(composite, 1),
                "threshold": threshold.value,
                "dimension_count": dim_count
            })

            # Check for alerts
            if threshold == KarmaThreshold.CRITICAL_LOW:
                alerts.append({
                    "agent_id": agent_id,
                    "display_name": display_name,
                    "level": "critical",
                    "message": f"{display_name} karma is critically low ({composite:.1f})"
                })
            elif threshold == KarmaThreshold.LOW:
                alerts.append({
                    "agent_id": agent_id,
                    "display_name": display_name,
                    "level": "warning",
                    "message": f"{display_name} karma is low ({composite:.1f})"
                })

        # Get recent events count
        events_result = await self.db.execute(
            text("""
                SELECT COUNT(*) FROM karma_events
                WHERE created_at > NOW() - INTERVAL '24 hours'
            """)
        )
        recent_events = events_result.fetchone()[0]

        return {
            "agents": agents,
            "alerts": alerts,
            "recent_events_24h": recent_events,
            "thresholds": thresholds,
            "generated_at": datetime.utcnow().isoformat()
        }

    async def get_event_history(
        self,
        agent_id: str,
        dimension_name: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        """Get recent karma events for an agent."""
        query = """
            SELECT
                event_id, dimension_name, delta, new_score,
                reason, evidence_type, created_at
            FROM karma_events
            WHERE agent_id = :agent_id
        """
        params = {"agent_id": agent_id, "limit": limit}

        if dimension_name:
            query += " AND dimension_name = :dimension"
            params["dimension"] = dimension_name

        query += " ORDER BY created_at DESC LIMIT :limit"

        result = await self.db.execute(text(query), params)

        return [
            {
                "event_id": row[0],
                "dimension_name": row[1],
                "delta": row[2],
                "new_score": row[3],
                "reason": row[4],
                "evidence_type": row[5],
                "created_at": row[6].isoformat() if row[6] else None
            }
            for row in result.fetchall()
        ]

    async def format_karma_context(self, agent_id: str = "sara") -> str:
        """
        Format karma state for injection into agent's system prompt.

        Provides self-awareness of performance without overwhelming detail.
        """
        karma = await self.get_agent_karma(agent_id)
        if not karma:
            return ""

        lines = [f"<karma agent=\"{agent_id}\" composite=\"{karma.composite_score:.1f}\" status=\"{karma.overall_threshold.value}\">"]

        # Only include dimensions that are notably good or bad
        notable = [d for d in karma.dimensions
                   if d.threshold in (KarmaThreshold.CRITICAL_LOW, KarmaThreshold.LOW,
                                     KarmaThreshold.GOOD, KarmaThreshold.EXCELLENT)]

        if notable:
            for dim in notable:
                trend_indicator = "↑" if dim.trend > 0.5 else "↓" if dim.trend < -0.5 else "→"
                lines.append(
                    f"  <dimension name=\"{dim.dimension_name}\" "
                    f"score=\"{dim.current_score:.1f}\" "
                    f"trend=\"{trend_indicator}\" "
                    f"status=\"{dim.threshold.value}\"/>"
                )
        else:
            lines.append("  <status>All dimensions within normal range</status>")

        lines.append("</karma>")
        return "\n".join(lines)


# Singleton instance management
_karma_service: Optional[KarmaService] = None


async def get_karma_service(db: AsyncSession) -> KarmaService:
    """Get or create KarmaService instance."""
    global _karma_service
    if _karma_service is None or _karma_service.db != db:
        _karma_service = KarmaService(db)
    return _karma_service
