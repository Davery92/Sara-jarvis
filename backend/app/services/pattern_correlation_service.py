"""
Pattern Correlation Service

Central coordinator for pattern discovery, storage, and retrieval.
Manages the lifecycle of cross-domain patterns from detection to confirmation.

Usage:
    from app.services.pattern_correlation_service import pattern_correlation_service

    # Run nightly discovery
    await pattern_correlation_service.run_discovery(db, user_id)

    # Get patterns relevant to conversation
    patterns = await pattern_correlation_service.get_relevant_patterns(
        db, user_id, context_embedding
    )
"""

import json
import logging
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.temporal_bin_service import temporal_bin_service
from app.services.cross_domain_analyzer import (
    cross_domain_analyzer,
    CorrelationResult,
    TimePattern,
    ThresholdPattern
)

logger = logging.getLogger(__name__)


# Pattern definitions for discovery
PATTERN_DEFINITIONS = [
    # Git <-> Health patterns
    {
        "category": "git_health",
        "metric_a": "health.sleep_hours",
        "metric_b": "git.commit_count",
        "lag_days": 1,
        "threshold_a": 7.0,
        "direction": "above",
        "title_template": "Sleep and Coding Productivity",
        "narrative_template": "When you get {threshold}+ hours of sleep, your commit count the next day averages {avg_met} compared to {avg_not_met} on days following less sleep."
    },
    {
        "category": "git_health",
        "metric_a": "health.hrv",
        "metric_b": "git.commit_count",
        "lag_days": 0,
        "threshold_a": None,  # Use correlation, not threshold
        "title_template": "HRV and Daily Productivity",
        "narrative_template": "Your heart rate variability shows a {strength} {direction} correlation with daily coding output."
    },
    {
        "category": "git_health",
        "metric_a": "git.late_commits",
        "metric_b": "health.hrv",
        "lag_days": 1,
        "threshold_a": 1,
        "direction": "above",
        "title_template": "Late Night Coding Impact",
        "narrative_template": "When you code past 10 PM, your next-day HRV drops to {avg_met} compared to {avg_not_met} on days following earlier nights."
    },

    # Food <-> Productivity patterns
    {
        "category": "food_productivity",
        "metric_a": "food.protein_g",
        "metric_b": "git.commit_count",
        "lag_days": 0,
        "threshold_a": 100,
        "direction": "above",
        "title_template": "Protein Intake and Productivity",
        "narrative_template": "On days when you eat {threshold}g+ of protein, you average {avg_met} commits compared to {avg_not_met} on lower protein days."
    },
    {
        "category": "food_productivity",
        "metric_a": "food.first_meal_hour",
        "metric_b": "git.commit_count",
        "lag_days": 0,
        "threshold_a": 9,
        "direction": "below",
        "title_template": "Early Eating and Productivity",
        "narrative_template": "When you eat breakfast before 9 AM, you average {avg_met} commits compared to {avg_not_met} on days with later first meals."
    },

    # Home <-> Health patterns
    {
        "category": "home_health",
        "metric_a": "home.first_motion_hour",
        "metric_b": "health.sleep_hours",
        "lag_days": 0,
        "threshold_a": None,
        "title_template": "Wake Time Consistency",
        "narrative_template": "Your wake time (first motion) shows a {strength} correlation with sleep duration."
    },

    # Mood <-> Productivity patterns
    {
        "category": "mood_productivity",
        "metric_a": "mood.avg_sentiment",
        "metric_b": "git.commit_count",
        "lag_days": 0,
        "threshold_a": 0.3,
        "direction": "above",
        "title_template": "Mood and Coding Output",
        "narrative_template": "On days with positive sentiment, you average {avg_met} commits compared to {avg_not_met} on lower mood days."
    },

    # Sleep <-> Mood patterns
    {
        "category": "sleep_mood",
        "metric_a": "health.sleep_hours",
        "metric_b": "mood.avg_sentiment",
        "lag_days": 0,
        "threshold_a": 7,
        "direction": "above",
        "title_template": "Sleep and Mood",
        "narrative_template": "When you sleep {threshold}+ hours, your average sentiment is {avg_met} compared to {avg_not_met} on days with less sleep."
    },

    # Exercise <-> Recovery patterns
    {
        "category": "exercise_recovery",
        "metric_a": "health.active_energy",
        "metric_b": "health.hrv",
        "lag_days": 1,
        "threshold_a": 400,
        "direction": "above",
        "title_template": "Exercise and Next-Day Recovery",
        "narrative_template": "After active days (400+ calories burned), your next-day HRV averages {avg_met} compared to {avg_not_met} after rest days."
    },
]


class PatternCorrelationService:
    """
    Manages cross-domain pattern discovery and lifecycle.

    Pattern States:
    - emerging: Newly detected, needs more validation
    - confirmed: Validated with high confidence (>= 0.75)
    - stale: No recent evidence (14+ days)
    - invalidated: Contradicted by recent data
    """

    async def run_discovery(
        self,
        db: Session,
        user_id: str,
        lookback_days: int = 30
    ) -> Dict[str, Any]:
        """
        Run full pattern discovery cycle.

        1. Ensure temporal bins are up to date
        2. Analyze all defined pattern pairs
        3. Create or update pattern records
        4. Validate existing patterns
        5. Decay stale patterns

        Returns summary of discovery run.
        """
        run_id = str(uuid4())
        started_at = datetime.utcnow()

        logger.info(f"🔍 Starting pattern discovery run {run_id} for user {user_id}")

        try:
            # Log discovery start
            db.execute(text("""
                INSERT INTO pattern_discovery_log
                    (id, user_id, run_type, started_at, status, lookback_days)
                VALUES
                    (:id, :user_id, 'nightly', :started_at, 'running', :lookback_days)
            """), {
                "id": run_id,
                "user_id": user_id,
                "started_at": started_at,
                "lookback_days": lookback_days
            })
            db.commit()

            # Step 1: Backfill temporal bins
            logger.info("📊 Step 1: Ensuring temporal bins are current...")
            bin_result = await temporal_bin_service.backfill_bins(db, user_id, lookback_days)

            # Step 2: Run pattern analysis
            logger.info("🔬 Step 2: Analyzing pattern definitions...")
            patterns_discovered = 0
            patterns_updated = 0

            for pattern_def in PATTERN_DEFINITIONS:
                result = await self._analyze_pattern_definition(
                    db, user_id, pattern_def, lookback_days
                )
                if result:
                    if result.get('created'):
                        patterns_discovered += 1
                    else:
                        patterns_updated += 1

            # Step 3: Validate existing patterns
            logger.info("✅ Step 3: Validating existing patterns...")
            validated, invalidated = await self._validate_existing_patterns(db, user_id)

            # Step 4: Decay stale patterns
            logger.info("⏳ Step 4: Decaying stale patterns...")
            decayed = await self._decay_stale_patterns(db, user_id)

            # Update discovery log
            db.execute(text("""
                UPDATE pattern_discovery_log
                SET completed_at = NOW(),
                    status = 'completed',
                    bins_created = :bins_created,
                    bins_updated = :bins_updated,
                    patterns_discovered = :patterns_discovered,
                    patterns_validated = :patterns_validated,
                    patterns_invalidated = :patterns_invalidated
                WHERE id = :id
            """), {
                "id": run_id,
                "bins_created": bin_result.get('created', 0),
                "bins_updated": bin_result.get('updated', 0),
                "patterns_discovered": patterns_discovered,
                "patterns_validated": validated,
                "patterns_invalidated": invalidated
            })
            db.commit()

            summary = {
                "run_id": run_id,
                "status": "completed",
                "bins_created": bin_result.get('created', 0),
                "bins_updated": bin_result.get('updated', 0),
                "patterns_discovered": patterns_discovered,
                "patterns_updated": patterns_updated,
                "patterns_validated": validated,
                "patterns_invalidated": invalidated,
                "patterns_decayed": decayed,
                "duration_seconds": (datetime.utcnow() - started_at).total_seconds()
            }

            logger.info(f"✅ Pattern discovery complete: {summary}")
            return summary

        except Exception as e:
            logger.error(f"❌ Pattern discovery failed: {e}", exc_info=True)

            db.execute(text("""
                UPDATE pattern_discovery_log
                SET completed_at = NOW(),
                    status = 'failed',
                    error_message = :error
                WHERE id = :id
            """), {"id": run_id, "error": str(e)})
            db.commit()

            return {"run_id": run_id, "status": "failed", "error": str(e)}

    async def _analyze_pattern_definition(
        self,
        db: Session,
        user_id: str,
        pattern_def: Dict,
        days: int
    ) -> Optional[Dict]:
        """Analyze a single pattern definition and store results."""
        try:
            metric_a = pattern_def['metric_a']
            metric_b = pattern_def['metric_b']
            lag_days = pattern_def.get('lag_days', 0)
            threshold_a = pattern_def.get('threshold_a')
            direction = pattern_def.get('direction', 'above')
            category = pattern_def['category']

            # Run correlation analysis
            correlation = await cross_domain_analyzer.analyze_correlation(
                db, user_id, metric_a, metric_b, days, lag_days
            )

            if not correlation or correlation.sample_size < 10:
                return None

            # Check if pattern is meaningful (|r| >= 0.3 or significant)
            if abs(correlation.correlation_coefficient) < 0.3 and not correlation.is_significant:
                return None

            # Run threshold analysis if defined
            threshold_result = None
            if threshold_a is not None:
                threshold_result = await cross_domain_analyzer.analyze_threshold_pattern(
                    db, user_id, metric_a, metric_b, threshold_a, direction, days, lag_days
                )

            # Generate narrative
            narrative = self._generate_narrative(pattern_def, correlation, threshold_result)

            # Calculate confidence
            confidence = self._calculate_confidence(correlation, threshold_result)

            # Check for existing pattern
            existing = db.execute(text("""
                SELECT id, validation_count, invalidation_count
                FROM correlation_pattern
                WHERE user_id = :user_id
                  AND metric_a = :metric_a
                  AND metric_b = :metric_b
                  AND (temporal_lag_hours = :lag_hours OR (temporal_lag_hours IS NULL AND :lag_hours = 0))
            """), {
                "user_id": user_id,
                "metric_a": metric_a,
                "metric_b": metric_b,
                "lag_hours": lag_days * 24
            }).fetchone()

            if existing:
                # Update existing pattern
                new_status = self._determine_status(
                    confidence,
                    existing.validation_count + 1,
                    existing.invalidation_count
                )

                db.execute(text("""
                    UPDATE correlation_pattern
                    SET correlation_coefficient = :r,
                        sample_size = :n,
                        confidence = :confidence,
                        p_value = :p_value,
                        narrative = :narrative,
                        status = :status,
                        validation_count = validation_count + 1,
                        last_validated_at = NOW(),
                        last_evidence_at = NOW(),
                        updated_at = NOW()
                    WHERE id = :id
                """), {
                    "id": existing.id,
                    "r": correlation.correlation_coefficient,
                    "n": correlation.sample_size,
                    "confidence": confidence,
                    "p_value": correlation.p_value,
                    "narrative": narrative,
                    "status": new_status
                })
                db.commit()

                return {"updated": True, "pattern_id": existing.id}

            else:
                # Create new pattern
                pattern_id = str(uuid4())
                status = 'emerging' if confidence < 0.75 else 'confirmed'

                db.execute(text("""
                    INSERT INTO correlation_pattern
                        (id, user_id, pattern_type, pattern_category,
                         title, description, narrative,
                         source_domains, metric_a, metric_b,
                         correlation_coefficient, sample_size, confidence, p_value,
                         status, temporal_lag_hours, temporal_window,
                         threshold_a, threshold_direction)
                    VALUES
                        (:id, :user_id, 'cross_domain', :category,
                         :title, :description, :narrative,
                         :domains, :metric_a, :metric_b,
                         :r, :n, :confidence, :p_value,
                         :status, :lag_hours, 'daily',
                         :threshold_a, :threshold_direction)
                """), {
                    "id": pattern_id,
                    "user_id": user_id,
                    "category": category,
                    "title": pattern_def['title_template'],
                    "description": correlation.interpretation,
                    "narrative": narrative,
                    "domains": json.dumps([metric_a.split('.')[0], metric_b.split('.')[0]]),
                    "metric_a": metric_a,
                    "metric_b": metric_b,
                    "r": correlation.correlation_coefficient,
                    "n": correlation.sample_size,
                    "confidence": confidence,
                    "p_value": correlation.p_value,
                    "status": status,
                    "lag_hours": lag_days * 24 if lag_days > 0 else None,
                    "threshold_a": threshold_a,
                    "threshold_direction": direction if threshold_a else None
                })
                db.commit()

                logger.info(f"📊 Discovered new pattern: {pattern_def['title_template']} "
                           f"(r={correlation.correlation_coefficient:.2f}, conf={confidence:.2f})")

                return {"created": True, "pattern_id": pattern_id}

        except Exception as e:
            logger.error(f"Pattern analysis failed for {pattern_def.get('title_template')}: {e}")
            return None

    def _generate_narrative(
        self,
        pattern_def: Dict,
        correlation: CorrelationResult,
        threshold_result: Optional[ThresholdPattern]
    ) -> str:
        """Generate human-readable narrative for Sara."""
        template = pattern_def.get('narrative_template', '')

        if threshold_result:
            return template.format(
                threshold=pattern_def.get('threshold_a', ''),
                avg_met=threshold_result.avg_b_when_met,
                avg_not_met=threshold_result.avg_b_when_not_met,
                strength=self._strength_word(correlation.correlation_coefficient),
                direction='positive' if correlation.correlation_coefficient > 0 else 'negative'
            )
        else:
            return template.format(
                strength=self._strength_word(correlation.correlation_coefficient),
                direction='positive' if correlation.correlation_coefficient > 0 else 'negative',
                r=correlation.correlation_coefficient
            )

    def _strength_word(self, r: float) -> str:
        """Convert correlation coefficient to strength word."""
        abs_r = abs(r)
        if abs_r >= 0.7:
            return "strong"
        elif abs_r >= 0.5:
            return "moderate"
        elif abs_r >= 0.3:
            return "weak"
        else:
            return "very weak"

    def _calculate_confidence(
        self,
        correlation: CorrelationResult,
        threshold_result: Optional[ThresholdPattern]
    ) -> float:
        """
        Calculate composite confidence score.

        Formula:
        - 30% correlation strength
        - 20% sample adequacy
        - 20% statistical significance
        - 20% effect size (from threshold or correlation)
        - 10% reserved for historical accuracy (starts at 0.5)
        """
        # Correlation strength (|r|)
        strength_score = min(1.0, abs(correlation.correlation_coefficient) / 0.7) * 0.30

        # Sample adequacy (30 samples = full score)
        sample_score = min(1.0, correlation.sample_size / 30) * 0.20

        # Statistical significance
        if correlation.p_value is not None:
            if correlation.p_value < 0.01:
                sig_score = 1.0 * 0.20
            elif correlation.p_value < 0.05:
                sig_score = 0.8 * 0.20
            elif correlation.p_value < 0.10:
                sig_score = 0.5 * 0.20
            else:
                sig_score = 0.2 * 0.20
        else:
            sig_score = 0.3 * 0.20

        # Effect size
        if threshold_result and abs(threshold_result.effect_size) > 0:
            effect_score = min(1.0, abs(threshold_result.effect_size) / 0.8) * 0.20
        elif correlation.effect_size:
            effect_score = min(1.0, abs(correlation.effect_size) / 0.8) * 0.20
        else:
            effect_score = 0.3 * 0.20

        # Historical accuracy placeholder (starts at neutral)
        history_score = 0.5 * 0.10

        return round(strength_score + sample_score + sig_score + effect_score + history_score, 3)

    def _determine_status(self, confidence: float, validations: int, invalidations: int) -> str:
        """Determine pattern status based on confidence and history."""
        if invalidations > validations * 2:
            return 'invalidated'
        elif confidence >= 0.75 and validations >= 3:
            return 'confirmed'
        else:
            return 'emerging'

    async def _validate_existing_patterns(self, db: Session, user_id: str) -> tuple:
        """Validate existing patterns against recent data."""
        # For now, validation happens in _analyze_pattern_definition
        # This method can be extended for additional validation logic
        return (0, 0)

    async def _decay_stale_patterns(self, db: Session, user_id: str) -> int:
        """Mark patterns as stale if no evidence in 14+ days."""
        result = db.execute(text("""
            UPDATE correlation_pattern
            SET status = 'stale',
                updated_at = NOW()
            WHERE user_id = :user_id
              AND status IN ('emerging', 'confirmed')
              AND last_evidence_at < NOW() - INTERVAL '14 days'
            RETURNING id
        """), {"user_id": user_id})
        db.commit()

        decayed = result.rowcount
        if decayed > 0:
            logger.info(f"⏳ Decayed {decayed} stale patterns")
        return decayed

    async def get_relevant_patterns(
        self,
        db: Session,
        user_id: str,
        context: Optional[str] = None,
        limit: int = 3
    ) -> List[Dict]:
        """
        Get patterns relevant to the current conversation context.

        For context injection into Sara's responses.
        """
        # Get confirmed patterns with high confidence
        result = db.execute(text("""
            SELECT
                id, title, narrative, pattern_category,
                metric_a, metric_b, correlation_coefficient,
                confidence, sample_size, temporal_lag_hours
            FROM correlation_pattern
            WHERE user_id = :user_id
              AND status = 'confirmed'
              AND confidence >= 0.6
            ORDER BY confidence DESC, last_validated_at DESC
            LIMIT :limit
        """), {"user_id": user_id, "limit": limit}).fetchall()

        patterns = []
        for row in result:
            patterns.append({
                "id": str(row.id),
                "title": row.title,
                "narrative": row.narrative,
                "category": row.pattern_category,
                "metric_a": row.metric_a,
                "metric_b": row.metric_b,
                "correlation": row.correlation_coefficient,
                "confidence": row.confidence,
                "sample_size": row.sample_size,
                "lag_hours": row.temporal_lag_hours
            })

        return patterns

    async def get_all_patterns(
        self,
        db: Session,
        user_id: str,
        include_emerging: bool = False
    ) -> List[Dict]:
        """Get all patterns for a user."""
        statuses = ['confirmed']
        if include_emerging:
            statuses.append('emerging')

        result = db.execute(text("""
            SELECT
                id, title, description, narrative, pattern_category,
                metric_a, metric_b, correlation_coefficient, correlation_pairs,
                confidence, sample_size, p_value, effect_size,
                status, temporal_lag_hours, temporal_window,
                threshold_a, threshold_direction,
                validation_count, invalidation_count,
                first_detected_at, last_validated_at, surfaced_count
            FROM correlation_pattern
            WHERE user_id = :user_id
              AND status = ANY(:statuses)
            ORDER BY confidence DESC, last_validated_at DESC
        """), {"user_id": user_id, "statuses": statuses}).fetchall()

        patterns = []
        for row in result:
            patterns.append({
                "id": str(row.id),
                "title": row.title,
                "description": row.description,
                "narrative": row.narrative,
                "category": row.pattern_category,
                "metric_a": row.metric_a,
                "metric_b": row.metric_b,
                "correlation": row.correlation_coefficient,
                "confidence": row.confidence,
                "sample_size": row.sample_size,
                "p_value": row.p_value,
                "status": row.status,
                "lag_hours": row.temporal_lag_hours,
                "threshold": row.threshold_a,
                "threshold_direction": row.threshold_direction,
                "validations": row.validation_count,
                "invalidations": row.invalidation_count,
                "first_detected": row.first_detected_at.isoformat() if row.first_detected_at else None,
                "last_validated": row.last_validated_at.isoformat() if row.last_validated_at else None,
                "surfaced_count": row.surfaced_count
            })

        return patterns

    async def get_correlation_matrix(
        self,
        db: Session,
        user_id: str,
        days: int = 30
    ) -> Dict[str, Dict[str, float]]:
        """
        Get correlation matrix for all metric pairs.

        Returns nested dict: matrix[metric_a][metric_b] = correlation
        """
        all_metrics = [
            'health.sleep_hours', 'health.hrv', 'health.resting_hr',
            'health.steps', 'health.active_energy',
            'git.commit_count', 'git.additions', 'git.late_commits',
            'food.total_calories', 'food.protein_g', 'food.first_meal_hour',
            'mood.avg_sentiment', 'mood.message_count'
        ]

        matrix = {m: {} for m in all_metrics}

        for i, metric_a in enumerate(all_metrics):
            for metric_b in all_metrics[i:]:
                if metric_a == metric_b:
                    matrix[metric_a][metric_b] = 1.0
                    continue

                correlation = await cross_domain_analyzer.analyze_correlation(
                    db, user_id, metric_a, metric_b, days, lag_days=0
                )

                if correlation:
                    matrix[metric_a][metric_b] = correlation.correlation_coefficient
                    matrix[metric_b][metric_a] = correlation.correlation_coefficient
                else:
                    matrix[metric_a][metric_b] = None
                    matrix[metric_b][metric_a] = None

        return matrix


# Singleton instance
pattern_correlation_service = PatternCorrelationService()
