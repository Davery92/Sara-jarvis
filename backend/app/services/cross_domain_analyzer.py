"""
Cross-Domain Analyzer

Performs statistical correlation analysis across different domains
(git, health, food, home, mood) to discover patterns.

Usage:
    from app.services.cross_domain_analyzer import cross_domain_analyzer

    # Calculate correlation between two metrics
    result = await cross_domain_analyzer.analyze_correlation(
        db, user_id,
        metric_a='health.sleep_hours',
        metric_b='git.commit_count',
        lag_days=1  # sleep affects NEXT day's commits
    )
"""

import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional, Dict, Any, Tuple
from statistics import mean, stdev, correlation

from sqlalchemy.orm import Session

from app.services.temporal_bin_service import temporal_bin_service

logger = logging.getLogger(__name__)


@dataclass
class CorrelationResult:
    """Result of a correlation analysis."""
    metric_a: str
    metric_b: str
    correlation_coefficient: float
    sample_size: int
    p_value: Optional[float]
    effect_size: Optional[float]  # Cohen's d equivalent
    lag_days: int
    is_significant: bool
    interpretation: str


@dataclass
class TimePattern:
    """A detected time-based pattern."""
    pattern_type: str  # 'day_of_week' or 'time_of_day'
    metric: str
    pattern_data: Dict[str, float]  # e.g., {Monday: 7.2, Tuesday: 6.8, ...}
    peak_value: float
    peak_label: str
    trough_value: float
    trough_label: str
    variance: float


@dataclass
class ThresholdPattern:
    """A pattern based on threshold conditions."""
    metric_a: str
    metric_b: str
    threshold_a: float
    direction: str  # 'above' or 'below'
    avg_b_when_met: float
    avg_b_when_not_met: float
    effect_size: float
    sample_size_met: int
    sample_size_not_met: int


class CrossDomainAnalyzer:
    """
    Analyzes correlations and patterns across domains.

    Supports:
    - Pearson correlation with significance testing
    - Lagged correlations (e.g., sleep affects next-day productivity)
    - Day-of-week patterns
    - Time-of-day patterns
    - Threshold-based patterns (e.g., when sleep > 7h, commits increase)
    """

    async def analyze_correlation(
        self,
        db: Session,
        user_id: str,
        metric_a: str,
        metric_b: str,
        days: int = 30,
        lag_days: int = 0
    ) -> Optional[CorrelationResult]:
        """
        Calculate Pearson correlation between two metrics.

        Args:
            metric_a: First metric (e.g., 'health.sleep_hours')
            metric_b: Second metric (e.g., 'git.commit_count')
            days: Number of days to analyze
            lag_days: Offset for metric_b (positive = B is from later date)
                      Example: lag_days=1 means "does A today affect B tomorrow?"

        Returns:
            CorrelationResult with coefficient, significance, and interpretation
        """
        # Get paired data
        paired_data = await temporal_bin_service.get_correlation_data(
            db, user_id, metric_a, metric_b, days, lag_days
        )

        if len(paired_data) < 7:  # Minimum sample size
            logger.info(f"Insufficient data for correlation: {len(paired_data)} points")
            return None

        values_a = [p['value_a'] for p in paired_data]
        values_b = [p['value_b'] for p in paired_data]

        try:
            # Calculate Pearson correlation
            r = correlation(values_a, values_b)
            n = len(paired_data)

            # Calculate p-value using t-distribution approximation
            p_value = self._calculate_p_value(r, n)

            # Calculate effect size (Cohen's d approximation from r)
            effect_size = self._r_to_cohens_d(r)

            # Determine significance
            is_significant = p_value < 0.05 if p_value else False

            # Generate interpretation
            interpretation = self._interpret_correlation(
                r, n, p_value, metric_a, metric_b, lag_days
            )

            return CorrelationResult(
                metric_a=metric_a,
                metric_b=metric_b,
                correlation_coefficient=round(r, 4),
                sample_size=n,
                p_value=round(p_value, 4) if p_value else None,
                effect_size=round(effect_size, 3) if effect_size else None,
                lag_days=lag_days,
                is_significant=is_significant,
                interpretation=interpretation
            )

        except Exception as e:
            logger.error(f"Correlation calculation failed: {e}")
            return None

    async def analyze_lagged_correlations(
        self,
        db: Session,
        user_id: str,
        metric_a: str,
        metric_b: str,
        max_lag_days: int = 3,
        days: int = 30
    ) -> List[CorrelationResult]:
        """
        Find optimal lag for correlation between metrics.

        Checks correlations at lag 0, 1, 2, ... max_lag_days.
        Returns all results sorted by absolute correlation strength.
        """
        results = []

        for lag in range(max_lag_days + 1):
            result = await self.analyze_correlation(
                db, user_id, metric_a, metric_b, days, lag
            )
            if result:
                results.append(result)

        # Sort by absolute correlation strength
        results.sort(key=lambda x: abs(x.correlation_coefficient), reverse=True)

        return results

    async def analyze_day_of_week_pattern(
        self,
        db: Session,
        user_id: str,
        metric: str,
        days: int = 60
    ) -> Optional[TimePattern]:
        """
        Detect day-of-week patterns for a metric.

        Returns pattern showing average value per day of week.
        """
        series = await temporal_bin_service.get_time_series(
            db, user_id, [metric], days
        )

        metric_data = series.get(metric, [])
        if len(metric_data) < 14:  # Need at least 2 weeks
            return None

        # Group by day of week
        day_values: Dict[int, List[float]] = {i: [] for i in range(7)}
        day_names = ['Sunday', 'Monday', 'Tuesday', 'Wednesday',
                     'Thursday', 'Friday', 'Saturday']

        for point in metric_data:
            if point['value'] is not None and point['day_of_week'] is not None:
                day_values[point['day_of_week']].append(point['value'])

        # Calculate averages
        day_averages = {}
        for day_num, values in day_values.items():
            if values:
                day_averages[day_names[day_num]] = round(mean(values), 2)

        if len(day_averages) < 5:  # Need most days represented
            return None

        # Find peak and trough
        peak_day = max(day_averages.items(), key=lambda x: x[1])
        trough_day = min(day_averages.items(), key=lambda x: x[1])

        # Calculate variance
        all_values = [v for v in day_averages.values()]
        variance = round(stdev(all_values) if len(all_values) > 1 else 0, 3)

        return TimePattern(
            pattern_type='day_of_week',
            metric=metric,
            pattern_data=day_averages,
            peak_value=peak_day[1],
            peak_label=peak_day[0],
            trough_value=trough_day[1],
            trough_label=trough_day[0],
            variance=variance
        )

    async def analyze_threshold_pattern(
        self,
        db: Session,
        user_id: str,
        metric_a: str,
        metric_b: str,
        threshold_a: float,
        direction: str = 'above',
        days: int = 30,
        lag_days: int = 0
    ) -> Optional[ThresholdPattern]:
        """
        Analyze how metric_b differs when metric_a is above/below a threshold.

        Example: "When sleep > 7 hours, commits average 6.3 vs 3.1"
        """
        paired_data = await temporal_bin_service.get_correlation_data(
            db, user_id, metric_a, metric_b, days, lag_days
        )

        if len(paired_data) < 10:
            return None

        # Split data by threshold
        met_values = []
        not_met_values = []

        for point in paired_data:
            if direction == 'above':
                condition_met = point['value_a'] >= threshold_a
            else:
                condition_met = point['value_a'] <= threshold_a

            if condition_met:
                met_values.append(point['value_b'])
            else:
                not_met_values.append(point['value_b'])

        if len(met_values) < 3 or len(not_met_values) < 3:
            return None

        avg_met = mean(met_values)
        avg_not_met = mean(not_met_values)

        # Calculate effect size (Cohen's d)
        pooled_std = math.sqrt(
            ((len(met_values) - 1) * (stdev(met_values) if len(met_values) > 1 else 0) ** 2 +
             (len(not_met_values) - 1) * (stdev(not_met_values) if len(not_met_values) > 1 else 0) ** 2) /
            (len(met_values) + len(not_met_values) - 2)
        ) if len(met_values) > 1 and len(not_met_values) > 1 else 1

        effect_size = (avg_met - avg_not_met) / pooled_std if pooled_std > 0 else 0

        return ThresholdPattern(
            metric_a=metric_a,
            metric_b=metric_b,
            threshold_a=threshold_a,
            direction=direction,
            avg_b_when_met=round(avg_met, 2),
            avg_b_when_not_met=round(avg_not_met, 2),
            effect_size=round(effect_size, 3),
            sample_size_met=len(met_values),
            sample_size_not_met=len(not_met_values)
        )

    async def analyze_all_domain_correlations(
        self,
        db: Session,
        user_id: str,
        days: int = 30
    ) -> Dict[str, List[CorrelationResult]]:
        """
        Run correlation analysis for all meaningful domain pairs.

        Returns dict with domain pair keys and list of significant correlations.
        """
        # Define metric pairs to analyze
        metric_pairs = [
            # Git <-> Health
            ('health.sleep_hours', 'git.commit_count', 1),  # Sleep affects next-day commits
            ('health.hrv', 'git.commit_count', 0),          # Same-day HRV vs productivity
            ('health.resting_hr', 'git.commit_count', 0),   # Resting HR vs productivity
            ('git.late_commits', 'health.hrv', 1),          # Late coding affects next-day HRV

            # Food <-> Productivity
            ('food.protein_g', 'git.commit_count', 0),      # Protein vs same-day commits
            ('food.first_meal_hour', 'git.commit_count', 0),  # Meal timing vs productivity
            ('food.total_calories', 'mood.avg_energy', 0),  # Calories vs energy

            # Home <-> Health
            ('home.first_motion_hour', 'health.sleep_hours', 0),  # Wake time vs sleep
            ('home.light_events', 'health.steps', 0),       # Activity proxy

            # Mood <-> Everything
            ('mood.avg_sentiment', 'git.commit_count', 0),  # Mood vs productivity
            ('mood.avg_energy', 'git.commit_count', 0),     # Energy vs productivity
            ('health.sleep_hours', 'mood.avg_sentiment', 0),  # Sleep vs mood
        ]

        results = {}

        for metric_a, metric_b, lag in metric_pairs:
            domain_pair = f"{metric_a.split('.')[0]}_{metric_b.split('.')[0]}"

            if domain_pair not in results:
                results[domain_pair] = []

            correlation = await self.analyze_correlation(
                db, user_id, metric_a, metric_b, days, lag
            )

            if correlation and abs(correlation.correlation_coefficient) >= 0.3:
                results[domain_pair].append(correlation)

        return results

    def _calculate_p_value(self, r: float, n: int) -> Optional[float]:
        """
        Calculate approximate p-value for Pearson correlation.

        Uses t-distribution approximation.
        """
        if n < 3:
            return None

        try:
            # t-statistic
            t = r * math.sqrt((n - 2) / (1 - r * r))

            # Approximate p-value using normal distribution for large n
            # For small n, this is an approximation
            import math
            z = abs(t) / math.sqrt(1 + t * t / (2 * (n - 2)))
            p = 2 * (1 - self._normal_cdf(z))
            return max(0.0001, min(1.0, p))

        except (ValueError, ZeroDivisionError):
            return None

    def _normal_cdf(self, x: float) -> float:
        """Approximate normal CDF using error function."""
        return (1 + math.erf(x / math.sqrt(2))) / 2

    def _r_to_cohens_d(self, r: float) -> float:
        """Convert correlation coefficient to Cohen's d equivalent."""
        if abs(r) >= 1:
            return float('inf') if r > 0 else float('-inf')
        return (2 * r) / math.sqrt(1 - r * r)

    def _interpret_correlation(
        self,
        r: float,
        n: int,
        p_value: Optional[float],
        metric_a: str,
        metric_b: str,
        lag_days: int
    ) -> str:
        """Generate human-readable interpretation of correlation."""
        # Strength
        abs_r = abs(r)
        if abs_r < 0.2:
            strength = "very weak"
        elif abs_r < 0.4:
            strength = "weak"
        elif abs_r < 0.6:
            strength = "moderate"
        elif abs_r < 0.8:
            strength = "strong"
        else:
            strength = "very strong"

        # Direction
        direction = "positive" if r > 0 else "negative"

        # Significance
        sig_text = ""
        if p_value is not None:
            if p_value < 0.01:
                sig_text = " (highly significant)"
            elif p_value < 0.05:
                sig_text = " (significant)"
            else:
                sig_text = " (not statistically significant)"

        # Lag
        lag_text = ""
        if lag_days == 1:
            lag_text = " with a 1-day delay"
        elif lag_days > 1:
            lag_text = f" with a {lag_days}-day delay"

        # Metric names (simplified)
        a_name = metric_a.split('.')[-1].replace('_', ' ')
        b_name = metric_b.split('.')[-1].replace('_', ' ')

        return f"There is a {strength} {direction} correlation (r={r:.2f}) between {a_name} and {b_name}{lag_text}{sig_text}. Based on {n} data points."


# Singleton instance
cross_domain_analyzer = CrossDomainAnalyzer()
