"""
Rating service for episode memory system.

Implements Wilson Score confidence intervals and temporal decay for rating-aware memory retrieval.
"""

import math
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select
import logging

from ..main_simple import Episode, EpisodeRating
from .rating_cache import RatingCache, get_rating_cache

logger = logging.getLogger(__name__)


class RatingService:
    """Service for managing episode ratings with Wilson Score and temporal decay."""

    def __init__(self, db: Session, redis_url: str = "redis://localhost:6379/0"):
        """
        Initialize rating service.

        Args:
            db: SQLAlchemy database session
            redis_url: Redis connection URL
        """
        self.db = db
        self.cache = get_rating_cache(redis_url)

    async def rate_episode(
        self,
        episode_id: str,
        user_id: str,
        rating: int
    ) -> Dict:
        """
        Rate an episode (1-5 stars).

        Args:
            episode_id: Episode UUID
            user_id: User UUID
            rating: Rating value (1-5)

        Returns:
            Dict with updated rating data

        Raises:
            ValueError: If rating is not 1-5
            LookupError: If episode doesn't exist
        """
        # Validate rating
        if not (1 <= rating <= 5):
            raise ValueError(f"Rating must be 1-5, got {rating}")

        # Verify episode exists
        episode = self.db.query(Episode).filter(Episode.id == episode_id).first()
        if not episode:
            raise LookupError(f"Episode {episode_id} not found")

        # Update Redis cache (fast, real-time)
        rating_data = await self.cache.update_episode_rating(episode_id, rating, user_id)

        logger.info(f"User {user_id} rated episode {episode_id}: {rating} stars")

        return rating_data

    async def get_episode_rating(self, episode_id: str) -> Optional[Dict]:
        """
        Get rating data for an episode (from cache or DB).

        Args:
            episode_id: Episode UUID

        Returns:
            Dict with rating data or None if not rated
        """
        # Try cache first
        cached = await self.cache.get_episode_rating(episode_id)
        if cached:
            return cached

        # Fall back to database
        rating = self.db.query(EpisodeRating).filter(
            EpisodeRating.episode_id == episode_id
        ).first()

        if not rating:
            return None

        return {
            "episode_id": episode_id,
            "user_rating": rating.user_rating,
            "rating_count": rating.rating_count,
            "average_rating": rating.average_rating,
            "rating_sum": rating.rating_sum,
            "last_rated": rating.last_rated.isoformat() if rating.last_rated else None
        }

    async def get_user_rating(self, user_id: str, episode_id: str) -> Optional[int]:
        """
        Get a user's rating for a specific episode.

        Args:
            user_id: User UUID
            episode_id: Episode UUID

        Returns:
            Rating value (1-5) or None if not rated
        """
        return await self.cache.get_user_rating(user_id, episode_id)

    async def delete_rating(self, episode_id: str, user_id: str) -> bool:
        """
        Delete a user's rating for an episode.

        Args:
            episode_id: Episode UUID
            user_id: User UUID

        Returns:
            True if deleted successfully
        """
        # Get current rating
        current_rating = await self.cache.get_user_rating(user_id, episode_id)
        if not current_rating:
            return False

        # Get episode rating data
        episode_rating = await self.cache.get_episode_rating(episode_id)
        if not episode_rating:
            return False

        # Calculate new values (remove the rating)
        new_rating_count = episode_rating["rating_count"] - 1
        new_rating_sum = episode_rating["rating_sum"] - current_rating

        if new_rating_count > 0:
            new_average = new_rating_sum / new_rating_count
        else:
            new_average = 0.0

        # Update cache
        await self.cache.set_episode_rating(
            episode_id=episode_id,
            user_rating=None,
            rating_count=new_rating_count,
            average_rating=new_average,
            rating_sum=new_rating_sum,
            last_rated=episode_rating["last_rated"]
        )

        # Delete user rating
        await self.cache.delete_user_rating(user_id, episode_id)

        # Mark dirty for sync
        await self.cache.mark_dirty(episode_id)

        logger.info(f"User {user_id} deleted rating for episode {episode_id}")

        return True

    async def sync_rating_to_db(self, episode_id: str) -> bool:
        """
        Sync rating from Redis cache to PostgreSQL.

        This is called by the nightly consolidation job.

        Args:
            episode_id: Episode UUID

        Returns:
            True if synced successfully
        """
        # Get from cache
        cached = await self.cache.get_episode_rating(episode_id)
        if not cached:
            logger.warning(f"No cached rating for episode {episode_id}, skipping sync")
            return False

        try:
            # Get or create episode rating record
            rating = self.db.query(EpisodeRating).filter(
                EpisodeRating.episode_id == episode_id
            ).first()

            if not rating:
                rating = EpisodeRating(episode_id=episode_id)
                self.db.add(rating)

            # Update fields
            rating.user_rating = cached["user_rating"]
            rating.rating_count = cached["rating_count"]
            rating.average_rating = cached["average_rating"]
            rating.rating_sum = cached["rating_sum"]
            if cached["last_rated"]:
                rating.last_rated = datetime.fromisoformat(cached["last_rated"])
            rating.updated_at = datetime.utcnow()

            # Calculate and update rating_boost on Episode
            episode = self.db.query(Episode).filter(Episode.id == episode_id).first()
            if episode:
                rating_boost = self.calculate_rating_boost(
                    rating_sum=cached["rating_sum"],
                    rating_count=cached["rating_count"],
                    created_at=episode.created_at
                )
                episode.rating_boost = rating_boost

            self.db.commit()

            logger.debug(f"Synced rating for episode {episode_id} to database")
            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to sync rating for episode {episode_id}: {e}")
            return False

    def calculate_rating_boost(
        self,
        rating_sum: int,
        rating_count: int,
        created_at: datetime
    ) -> float:
        """
        Calculate rating boost using Wilson Score confidence interval + temporal decay.

        The Wilson Score provides a confidence interval for the true rating, preventing
        manipulation by single votes. Temporal decay ensures old ratings fade gracefully.

        Formula:
            1. Calculate Wilson Score lower bound (95% confidence)
            2. Apply exponential temporal decay
            3. Scale to 0-0.25 range (25% of importance weight)

        Args:
            rating_sum: Sum of all rating values
            rating_count: Number of ratings
            created_at: Episode creation timestamp

        Returns:
            Rating boost value (0-0.25)
        """
        if rating_count == 0:
            return 0.0

        # Normalize ratings to 0-1 scale (rating_sum is 1-5 stars)
        p = rating_sum / (5.0 * rating_count)  # Success rate

        # Wilson Score parameters
        z = 1.96  # 95% confidence interval (z-score)
        n = rating_count

        # Wilson Score lower bound
        # Formula: (p + z²/2n - z√(p(1-p)/n + z²/4n²)) / (1 + z²/n)
        numerator = (
            p +
            (z * z) / (2 * n) -
            z * math.sqrt((p * (1 - p) / n) + (z * z) / (4 * n * n))
        )
        denominator = 1 + (z * z) / n
        confidence = numerator / denominator

        # Temporal decay (exponential decay with 30-day half-life)
        age_days = (datetime.utcnow() - created_at).days
        decay_constant = math.log(2) / 30.0  # Half-life of 30 days
        age_decay = math.exp(-decay_constant * age_days)

        # Final boost (0-0.25 range, which is 25% of importance weight)
        rating_boost = confidence * age_decay * 0.25

        return rating_boost

    def should_prompt_for_rating(
        self,
        message_content: str,
        role: str,
        conversation_ratings_count: int = 0
    ) -> bool:
        """
        Determine if we should prompt the user to rate this message.

        Implements rating fatigue prevention by filtering low-value messages.

        Args:
            message_content: The message text
            role: "user" or "assistant"
            conversation_ratings_count: Number of rating prompts in current conversation

        Returns:
            True if we should show rating UI
        """
        # Don't prompt for user's own messages (only assistant)
        if role == "user":
            return False

        # Limit rating prompts per conversation (prevent fatigue)
        if conversation_ratings_count >= 3:
            return False

        # Filter out very short messages (< 50 characters)
        if len(message_content) < 50:
            return False

        # Filter out low-value assistant messages
        low_value_starts = [
            "I'm ", "Let me ", "Sure", "Okay", "Got it",
            "I'll ", "I can ", "Here you go", "No problem"
        ]
        for start in low_value_starts:
            if message_content.strip().startswith(start):
                return False

        return True

    async def get_rating_stats(self) -> Dict:
        """
        Get global rating statistics.

        Returns:
            Dict with statistics (from cache and DB)
        """
        cache_stats = await self.cache.get_rating_stats()

        # Get database stats
        try:
            total_db_ratings = self.db.query(EpisodeRating).count()
            avg_rating_db = self.db.query(func.avg(EpisodeRating.average_rating)).scalar() or 0.0

            return {
                "cache_stats": cache_stats,
                "database": {
                    "total_ratings": total_db_ratings,
                    "average_rating": float(avg_rating_db)
                }
            }
        except Exception as e:
            logger.error(f"Failed to get database rating stats: {e}")
            return {
                "cache_stats": cache_stats,
                "database": {
                    "total_ratings": 0,
                    "average_rating": 0.0
                }
            }


def get_rating_service(db: Session, redis_url: str = "redis://localhost:6379/0") -> RatingService:
    """Factory function to create RatingService instance."""
    return RatingService(db, redis_url)
