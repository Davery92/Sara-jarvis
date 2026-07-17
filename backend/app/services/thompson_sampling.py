"""
Thompson Sampling service for exploration/exploitation tradeoff in memory retrieval.

Addresses the cold-start problem by giving new memories a probabilistic boost based on
uncertainty (Beta distribution sampling).
"""

import numpy as np
from datetime import datetime, timezone
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class ThompsonSampler:
    """
    Thompson Sampling for memory exploration.

    Uses Beta distribution to balance exploration (trying new memories) vs exploitation
    (using highly-rated memories). High uncertainty (few ratings) leads to more exploration.
    """

    def __init__(self, cold_start_days: int = 7, max_bonus: float = 0.1):
        """
        Initialize Thompson Sampler.

        Args:
            cold_start_days: Number of days to apply exploration bonus (default 7)
            max_bonus: Maximum exploration bonus value (default 0.1 = 10% of retrieval score)
        """
        self.cold_start_days = cold_start_days
        self.max_bonus = max_bonus

    def calculate_exploration_bonus(
        self,
        rating_sum: int,
        rating_count: int,
        created_at: datetime,
        current_time: Optional[datetime] = None
    ) -> float:
        """
        Calculate exploration bonus using Beta distribution sampling.

        Beta(α, β) distribution where:
        - α (alpha) = successes + 1 = rating_sum + 1
        - β (beta) = failures + 1 = (5*rating_count - rating_sum) + 1

        High uncertainty (low rating_count) → wider distribution → higher exploration chance
        Recent memories (< cold_start_days) → bonus applied with age decay
        Old memories (>= cold_start_days) → no bonus

        Args:
            rating_sum: Sum of all rating values (e.g., 15 from three 5-star ratings)
            rating_count: Number of ratings
            created_at: When the memory was created
            current_time: Current time (defaults to now)

        Returns:
            Exploration bonus (0 to max_bonus)
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        # Calculate age in days
        age_days = (current_time - created_at).total_seconds() / 86400.0

        # No exploration bonus after cold-start period
        if age_days >= self.cold_start_days:
            return 0.0

        # If no ratings yet, treat as completely uncertain (alpha=1, beta=1 → Uniform[0,1])
        if rating_count == 0:
            alpha = 1.0
            beta = 1.0
        else:
            # Beta distribution parameters
            # Success = high ratings (closer to 5)
            # Failure = low ratings (closer to 1)
            alpha = rating_sum + 1
            beta = (5 * rating_count - rating_sum) + 1

        # Sample from Beta distribution
        # This gives us a probabilistic estimate of the "true quality"
        try:
            sample = np.random.beta(alpha, beta)
        except Exception as e:
            logger.warning(f"Beta sampling failed (α={alpha}, β={beta}): {e}, using mean")
            # Fall back to mean if sampling fails
            sample = alpha / (alpha + beta)

        # Scale by remaining cold-start period (linear decay)
        age_factor = (self.cold_start_days - age_days) / self.cold_start_days

        # Final bonus: sample * age_factor * max_bonus
        exploration_bonus = sample * age_factor * self.max_bonus

        return exploration_bonus

    def calculate_exploration_bonus_deterministic(
        self,
        rating_sum: int,
        rating_count: int,
        created_at: datetime,
        current_time: Optional[datetime] = None
    ) -> float:
        """
        Calculate exploration bonus using Beta distribution MEAN (deterministic).

        This is useful for testing or when you want reproducible results.
        Uses the same Beta distribution but takes the mean instead of sampling.

        Args:
            rating_sum: Sum of all rating values
            rating_count: Number of ratings
            created_at: When the memory was created
            current_time: Current time (defaults to now)

        Returns:
            Exploration bonus (0 to max_bonus)
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        # Calculate age in days
        age_days = (current_time - created_at).total_seconds() / 86400.0

        # No exploration bonus after cold-start period
        if age_days >= self.cold_start_days:
            return 0.0

        # Beta distribution parameters
        if rating_count == 0:
            alpha = 1.0
            beta = 1.0
        else:
            alpha = rating_sum + 1
            beta = (5 * rating_count - rating_sum) + 1

        # Mean of Beta(α, β) = α / (α + β)
        mean_estimate = alpha / (alpha + beta)

        # Scale by remaining cold-start period
        age_factor = (self.cold_start_days - age_days) / self.cold_start_days

        # Final bonus
        exploration_bonus = mean_estimate * age_factor * self.max_bonus

        return exploration_bonus

    def get_beta_distribution_stats(
        self,
        rating_sum: int,
        rating_count: int
    ) -> dict:
        """
        Get statistics about the Beta distribution for a given rating state.

        Useful for debugging and understanding exploration behavior.

        Args:
            rating_sum: Sum of all rating values
            rating_count: Number of ratings

        Returns:
            Dict with mean, variance, std_dev, confidence_interval
        """
        if rating_count == 0:
            alpha = 1.0
            beta = 1.0
        else:
            alpha = rating_sum + 1
            beta = (5 * rating_count - rating_sum) + 1

        # Beta distribution statistics
        mean = alpha / (alpha + beta)
        variance = (alpha * beta) / ((alpha + beta) ** 2 * (alpha + beta + 1))
        std_dev = np.sqrt(variance)

        # 95% confidence interval (approximate)
        # Using normal approximation: mean ± 1.96 * std_dev
        ci_lower = max(0.0, mean - 1.96 * std_dev)
        ci_upper = min(1.0, mean + 1.96 * std_dev)

        return {
            "alpha": alpha,
            "beta": beta,
            "mean": mean,
            "variance": variance,
            "std_dev": std_dev,
            "confidence_interval": (ci_lower, ci_upper),
            "uncertainty": std_dev  # Higher = more uncertain
        }


# Global instance
_thompson_sampler: Optional[ThompsonSampler] = None


def get_thompson_sampler(
    cold_start_days: int = 7,
    max_bonus: float = 0.1
) -> ThompsonSampler:
    """Get or create global ThompsonSampler instance."""
    global _thompson_sampler
    if _thompson_sampler is None:
        _thompson_sampler = ThompsonSampler(cold_start_days, max_bonus)
    return _thompson_sampler
