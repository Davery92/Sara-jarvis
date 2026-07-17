"""
PatternDetector - Identifies recurring patterns in observations.

Analyzes observations to detect meaningful patterns such as:
- Recurring errors
- Successful approaches
- Timing issues
- Calibration problems
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from .scratchpad import (
    ReflectionScratchpad, Observation, Pattern,
    ObservationType, PatternType, PatternStatus
)

logger = logging.getLogger(__name__)


@dataclass
class DetectedPattern:
    """A newly detected pattern."""
    pattern_type: PatternType
    description: str
    affected_agent: Optional[str]
    affected_dimension: Optional[str]
    observation_count: int
    confidence: float
    supporting_observations: List[int]  # observation_ids
    proposed_action: Optional[str] = None


class PatternDetector:
    """
    Analyzes observations to detect meaningful patterns.

    Uses clustering and frequency analysis to identify:
    - Recurring errors (same type of failure multiple times)
    - Missed opportunities (consistent misses in similar contexts)
    - Successful approaches (what works well)
    - Timing patterns (issues at specific times)
    - Calibration issues (over/under confidence)
    """

    # Thresholds for pattern detection
    THRESHOLDS = {
        "min_observations": 3,      # Need at least 3 instances
        "time_window_days": 7,      # Within this time window
        "confidence_threshold": 0.6  # Minimum confidence to report
    }

    def __init__(self, db: AsyncSession, scratchpad: ReflectionScratchpad):
        self.db = db
        self.scratchpad = scratchpad

    async def detect_patterns(self) -> List[DetectedPattern]:
        """
        Run pattern detection across recent observations.

        Returns list of newly detected patterns.
        """
        patterns = []

        # Get recent observations
        observations = await self.scratchpad.get_recent_observations(
            days=self.THRESHOLDS["time_window_days"]
        )

        if not observations:
            return patterns

        # Run different pattern detectors
        patterns.extend(await self._detect_recurring_errors(observations))
        patterns.extend(await self._detect_consolidation_patterns(observations))
        patterns.extend(await self._detect_timing_patterns(observations))
        patterns.extend(await self._detect_successful_approaches(observations))

        # Filter by confidence threshold
        patterns = [p for p in patterns if p.confidence >= self.THRESHOLDS["confidence_threshold"]]

        return patterns

    async def _detect_recurring_errors(
        self,
        observations: List[Observation],
    ) -> List[DetectedPattern]:
        """Find errors that keep happening in similar contexts."""
        patterns = []

        # Filter to negative outcomes
        errors = [
            o for o in observations
            if o.observation_type == ObservationType.ACTION_OUTCOME
            and o.details
            and o.details.get("outcome") == "failure"
        ]

        if len(errors) < self.THRESHOLDS["min_observations"]:
            return patterns

        # Group by action type
        by_action_type = defaultdict(list)
        for error in errors:
            action_type = error.details.get("action_type", "unknown")
            by_action_type[action_type].append(error)

        # Check each group for patterns
        for action_type, group in by_action_type.items():
            if len(group) >= self.THRESHOLDS["min_observations"]:
                # Calculate confidence based on count and consistency
                confidence = self._calculate_confidence(group)

                patterns.append(DetectedPattern(
                    pattern_type=PatternType.RECURRING_ERROR,
                    description=f"Recurring failure in '{action_type}' actions: "
                               f"{len(group)} failures in {self.THRESHOLDS['time_window_days']} days",
                    affected_agent="sara",
                    affected_dimension="helpfulness",
                    observation_count=len(group),
                    confidence=confidence,
                    supporting_observations=[o.observation_id for o in group],
                    proposed_action=f"Review and improve handling of '{action_type}' actions",
                ))

        return patterns

    async def _detect_consolidation_patterns(
        self,
        observations: List[Observation],
    ) -> List[DetectedPattern]:
        """Find patterns in consolidation audit results."""
        patterns = []

        # Filter to consolidation audits
        audits = [
            o for o in observations
            if o.observation_type == ObservationType.CONSOLIDATION_AUDIT
            and o.details
        ]

        if not audits:
            return patterns

        # Check for consistent misses
        misses = [o for o in audits if o.details.get("missed_count", 0) > 0]

        if len(misses) >= self.THRESHOLDS["min_observations"]:
            total_misses = sum(o.details.get("missed_count", 0) for o in misses)
            confidence = min(1.0, len(misses) / 5)  # Saturates at 5 observations

            patterns.append(DetectedPattern(
                pattern_type=PatternType.CONSOLIDATION_ISSUE,
                description=f"Consolidation is missing important items: "
                           f"{total_misses} misses across {len(misses)} audits",
                affected_agent="consolidation",
                affected_dimension="accuracy",
                observation_count=len(misses),
                confidence=confidence,
                supporting_observations=[o.observation_id for o in misses],
                proposed_action="Lower consolidation relevance threshold to catch more items",
            ))

        # Check for low accuracy trend
        accuracy_scores = [
            o.details.get("accuracy_score", 1.0)
            for o in audits
            if "accuracy_score" in o.details
        ]

        if accuracy_scores and sum(accuracy_scores) / len(accuracy_scores) < 0.8:
            patterns.append(DetectedPattern(
                pattern_type=PatternType.CONSOLIDATION_ISSUE,
                description=f"Consolidation accuracy is below target: "
                           f"avg={sum(accuracy_scores)/len(accuracy_scores):.2f}",
                affected_agent="consolidation",
                affected_dimension="accuracy",
                observation_count=len(accuracy_scores),
                confidence=0.7,
                supporting_observations=[o.observation_id for o in audits],
                proposed_action="Review consolidation configuration and thresholds",
            ))

        return patterns

    async def _detect_timing_patterns(
        self,
        observations: List[Observation],
    ) -> List[DetectedPattern]:
        """Find patterns related to timing."""
        patterns = []

        # Group observations by hour of day
        by_hour = defaultdict(list)
        for obs in observations:
            hour = obs.created_at.hour
            by_hour[hour].append(obs)

        # Look for hours with unusually high negative observations
        total_negative = 0
        negative_by_hour = {}

        for hour, obs_list in by_hour.items():
            negative_count = sum(
                1 for o in obs_list
                if o.subject_dimension == "timing" or
                (o.details and o.details.get("outcome") == "failure")
            )
            negative_by_hour[hour] = negative_count
            total_negative += negative_count

        if total_negative < self.THRESHOLDS["min_observations"]:
            return patterns

        # Find hours with above-average negative observations
        avg_negative = total_negative / 24
        for hour, count in negative_by_hour.items():
            if count >= self.THRESHOLDS["min_observations"] and count > avg_negative * 2:
                hour_str = f"{hour:02d}:00"
                patterns.append(DetectedPattern(
                    pattern_type=PatternType.TIMING_PATTERN,
                    description=f"Issues frequently occur around {hour_str}: "
                               f"{count} incidents (avg={avg_negative:.1f})",
                    affected_agent="sara",
                    affected_dimension="timing",
                    observation_count=count,
                    confidence=min(1.0, count / 5),
                    supporting_observations=[
                        o.observation_id for o in by_hour[hour]
                    ][:10],  # Limit to 10
                    proposed_action=f"Adjust notification thresholds during {hour_str} hour",
                ))

        return patterns

    async def _detect_successful_approaches(
        self,
        observations: List[Observation],
    ) -> List[DetectedPattern]:
        """Find patterns in successful outcomes."""
        patterns = []

        # Filter to successful outcomes
        successes = [
            o for o in observations
            if o.observation_type == ObservationType.ACTION_OUTCOME
            and o.details
            and o.details.get("outcome") == "success"
        ]

        if len(successes) < self.THRESHOLDS["min_observations"]:
            return patterns

        # Group by action type
        by_action_type = defaultdict(list)
        for success in successes:
            action_type = success.details.get("action_type", "unknown")
            by_action_type[action_type].append(success)

        # Find consistently successful action types
        for action_type, group in by_action_type.items():
            if len(group) >= self.THRESHOLDS["min_observations"]:
                confidence = self._calculate_confidence(group)

                patterns.append(DetectedPattern(
                    pattern_type=PatternType.SUCCESSFUL_APPROACH,
                    description=f"'{action_type}' actions are consistently successful: "
                               f"{len(group)} successes",
                    affected_agent="sara",
                    affected_dimension="helpfulness",
                    observation_count=len(group),
                    confidence=confidence,
                    supporting_observations=[o.observation_id for o in group],
                    proposed_action=f"Continue and possibly expand '{action_type}' approach",
                ))

        return patterns

    def _calculate_confidence(self, observations: List[Observation]) -> float:
        """
        Calculate confidence in a pattern based on observations.

        Factors:
        - Number of observations (more = higher confidence)
        - Consistency (similar observations = higher confidence)
        - Recency (recent observations weighted more)
        """
        n = len(observations)

        # Base confidence from count (saturates at 10)
        count_confidence = min(n / 10, 1.0)

        # Time spread factor (patterns spread over time are more reliable)
        if n >= 2:
            time_range = (
                max(o.created_at for o in observations) -
                min(o.created_at for o in observations)
            )
            # Prefer patterns that span at least a day
            time_factor = min(1.0, time_range.total_seconds() / 86400)
        else:
            time_factor = 0.5

        # Combine factors
        confidence = count_confidence * 0.6 + time_factor * 0.4

        return round(confidence, 2)

    async def persist_pattern(self, detected: DetectedPattern) -> str:
        """Save a detected pattern to the scratchpad."""
        pattern_id = await self.scratchpad.add_pattern(
            pattern_type=detected.pattern_type,
            description=detected.description,
            affected_agent=detected.affected_agent,
            affected_dimension=detected.affected_dimension,
            confidence=detected.confidence,
            proposed_action=detected.proposed_action,
            metadata={
                "supporting_observations": detected.supporting_observations,
                "observation_count": detected.observation_count,
            }
        )

        # Link observations to this pattern
        for obs_id in detected.supporting_observations:
            await self.scratchpad.update_observation(
                obs_id,
                pattern_id=pattern_id,
            )

        return pattern_id

    async def update_existing_pattern(
        self,
        pattern_id: str,
        new_observations: List[int],
    ) -> None:
        """Update an existing pattern with new observations."""
        # Get current pattern
        pattern = await self.scratchpad.get_pattern(pattern_id)
        if not pattern:
            return

        # Calculate new confidence based on increased observation count
        new_count = len(new_observations)
        total_count = pattern.observation_count + new_count
        new_confidence = min(1.0, total_count / 10)

        await self.scratchpad.update_pattern(
            pattern_id,
            observation_count_delta=new_count,
            confidence=new_confidence,
        )

        # Link new observations
        for obs_id in new_observations:
            await self.scratchpad.update_observation(obs_id, pattern_id=pattern_id)
