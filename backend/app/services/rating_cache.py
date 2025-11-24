"""
Redis cache service for episode ratings.

Provides fast real-time rating storage with eventual consistency to PostgreSQL.
"""

import redis.asyncio as redis
from typing import Optional, Dict, List
from datetime import datetime, timedelta
import json
import logging

logger = logging.getLogger(__name__)


class RatingCache:
    """Redis-based cache for episode ratings with eventual PostgreSQL sync."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        """Initialize Redis connection."""
        self.redis_url = redis_url
        self._client: Optional[redis.Redis] = None

    async def connect(self):
        """Establish Redis connection."""
        if not self._client:
            self.redis = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
        return self._client

    async def close(self):
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None

    @property
    def client(self) -> redis.Redis:
        """Get Redis client (lazy initialization)."""
        if not self._client:
            self._client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
        return self._client

    # Episode Rating Cache Methods

    async def get_episode_rating(self, episode_id: str) -> Optional[Dict]:
        """
        Get rating data for an episode from Redis cache.

        Returns:
            Dict with keys: user_rating, rating_count, average_rating, rating_sum, last_rated
            None if not cached
        """
        key = f"episode_rating:{episode_id}"
        data = await self.client.hgetall(key)

        if not data:
            return None

        return {
            "user_rating": int(data["user_rating"]) if data.get("user_rating") else None,
            "rating_count": int(data.get("rating_count", 0)),
            "average_rating": float(data.get("average_rating", 0.0)),
            "rating_sum": int(data.get("rating_sum", 0)),
            "last_rated": data.get("last_rated"),
        }

    async def set_episode_rating(
        self,
        episode_id: str,
        user_rating: Optional[int] = None,
        rating_count: int = 0,
        average_rating: float = 0.0,
        rating_sum: int = 0,
        last_rated: Optional[str] = None,
        ttl_days: int = 30
    ) -> bool:
        """
        Store rating data for an episode in Redis cache.

        Args:
            episode_id: Episode UUID
            user_rating: User's 1-5 star rating
            rating_count: Total number of ratings
            average_rating: Average rating score
            rating_sum: Sum of all rating values
            last_rated: ISO timestamp of last rating
            ttl_days: TTL in days (default 30)

        Returns:
            True if stored successfully
        """
        key = f"episode_rating:{episode_id}"
        data = {
            "rating_count": rating_count,
            "average_rating": average_rating,
            "rating_sum": rating_sum,
            "last_rated": last_rated or datetime.utcnow().isoformat(),
        }

        if user_rating is not None:
            data["user_rating"] = user_rating

        try:
            await self.client.hset(key, mapping=data)
            await self.client.expire(key, timedelta(days=ttl_days))
            return True
        except Exception as e:
            logger.error(f"Failed to cache episode rating {episode_id}: {e}")
            return False

    async def update_episode_rating(
        self,
        episode_id: str,
        user_rating: int,
        user_id: str
    ) -> Dict:
        """
        Update rating for an episode (increment/change rating).

        This method handles the logic of updating ratings when a user rates or changes their rating.

        Args:
            episode_id: Episode UUID
            user_rating: New rating value (1-5)
            user_id: User UUID

        Returns:
            Updated rating data dict
        """
        # Get current cached rating
        current = await self.get_episode_rating(episode_id)

        if current is None:
            # First rating for this episode
            current = {
                "user_rating": None,
                "rating_count": 0,
                "average_rating": 0.0,
                "rating_sum": 0,
                "last_rated": None
            }

        # Get user's previous rating
        prev_user_rating = await self.get_user_rating(user_id, episode_id)

        # Calculate new values
        if prev_user_rating is None:
            # New rating
            new_rating_count = current["rating_count"] + 1
            new_rating_sum = current["rating_sum"] + user_rating
        else:
            # Update existing rating
            new_rating_count = current["rating_count"]
            new_rating_sum = current["rating_sum"] - prev_user_rating + user_rating

        new_average_rating = new_rating_sum / new_rating_count if new_rating_count > 0 else 0.0
        now_iso = datetime.utcnow().isoformat()

        # Update episode rating cache
        await self.set_episode_rating(
            episode_id=episode_id,
            user_rating=user_rating,
            rating_count=new_rating_count,
            average_rating=new_average_rating,
            rating_sum=new_rating_sum,
            last_rated=now_iso
        )

        # Update user rating cache
        await self.set_user_rating(user_id, episode_id, user_rating)

        # Mark episode as dirty (needs PostgreSQL sync)
        await self.mark_dirty(episode_id)

        return {
            "episode_id": episode_id,
            "user_rating": user_rating,
            "rating_count": new_rating_count,
            "average_rating": new_average_rating,
            "rating_sum": new_rating_sum,
            "last_rated": now_iso
        }

    # User Rating Cache Methods

    async def get_user_rating(self, user_id: str, episode_id: str) -> Optional[int]:
        """
        Get a user's rating for a specific episode.

        Returns:
            Rating value (1-5) or None if not rated
        """
        key = f"user_rating:{user_id}:{episode_id}"
        rating = await self.client.get(key)
        return int(rating) if rating else None

    async def set_user_rating(
        self,
        user_id: str,
        episode_id: str,
        rating: int,
        ttl_days: int = 30
    ) -> bool:
        """
        Store a user's rating for an episode.

        Args:
            user_id: User UUID
            episode_id: Episode UUID
            rating: Rating value (1-5)
            ttl_days: TTL in days (default 30)

        Returns:
            True if stored successfully
        """
        key = f"user_rating:{user_id}:{episode_id}"
        try:
            await self.client.set(key, rating, ex=timedelta(days=ttl_days))
            return True
        except Exception as e:
            logger.error(f"Failed to cache user rating {user_id}:{episode_id}: {e}")
            return False

    async def delete_user_rating(self, user_id: str, episode_id: str) -> bool:
        """Delete a user's rating for an episode."""
        key = f"user_rating:{user_id}:{episode_id}"
        try:
            await self.client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Failed to delete user rating {user_id}:{episode_id}: {e}")
            return False

    # Dirty Set Management (for nightly sync)

    async def mark_dirty(self, episode_id: str) -> bool:
        """
        Mark an episode as dirty (needs PostgreSQL sync).

        The dirty set is used by the nightly consolidation job to know which
        episodes have rating changes that need to be synced.
        """
        try:
            await self.client.sadd("rating_dirty_set", episode_id)
            return True
        except Exception as e:
            logger.error(f"Failed to mark episode {episode_id} as dirty: {e}")
            return False

    async def get_dirty_episodes(self, batch_size: int = 100) -> List[str]:
        """
        Get a batch of dirty episode IDs for syncing.

        Args:
            batch_size: Number of IDs to retrieve

        Returns:
            List of episode IDs
        """
        try:
            # Use SPOP to atomically get and remove items
            episode_ids = []
            for _ in range(batch_size):
                episode_id = await self.client.spop("rating_dirty_set")
                if not episode_id:
                    break
                episode_ids.append(episode_id)
            return episode_ids
        except Exception as e:
            logger.error(f"Failed to get dirty episodes: {e}")
            return []

    async def get_dirty_count(self) -> int:
        """Get count of episodes needing sync."""
        try:
            return await self.client.scard("rating_dirty_set")
        except Exception as e:
            logger.error(f"Failed to get dirty count: {e}")
            return 0

    async def clear_dirty_set(self) -> bool:
        """Clear the entire dirty set (use after successful batch sync)."""
        try:
            await self.client.delete("rating_dirty_set")
            return True
        except Exception as e:
            logger.error(f"Failed to clear dirty set: {e}")
            return False

    # Batch Operations

    async def get_episode_ratings_batch(self, episode_ids: List[str]) -> Dict[str, Dict]:
        """
        Get ratings for multiple episodes in a single operation.

        Args:
            episode_ids: List of episode UUIDs

        Returns:
            Dict mapping episode_id -> rating data dict
        """
        pipeline = self.client.pipeline()
        for episode_id in episode_ids:
            key = f"episode_rating:{episode_id}"
            pipeline.hgetall(key)

        results = await pipeline.execute()

        ratings = {}
        for episode_id, data in zip(episode_ids, results):
            if data:
                ratings[episode_id] = {
                    "user_rating": int(data["user_rating"]) if data.get("user_rating") else None,
                    "rating_count": int(data.get("rating_count", 0)),
                    "average_rating": float(data.get("average_rating", 0.0)),
                    "rating_sum": int(data.get("rating_sum", 0)),
                    "last_rated": data.get("last_rated"),
                }
        return ratings

    # Statistics & Monitoring

    async def get_rating_stats(self) -> Dict:
        """
        Get global rating statistics from Redis cache.

        Returns:
            Dict with stats: total_rated_episodes, pending_sync_count
        """
        try:
            # Count all episode rating keys
            cursor = 0
            total_rated = 0
            async for key in self.client.scan_iter(match="episode_rating:*"):
                total_rated += 1

            pending_sync = await self.get_dirty_count()

            return {
                "total_rated_episodes": total_rated,
                "pending_sync_count": pending_sync,
            }
        except Exception as e:
            logger.error(f"Failed to get rating stats: {e}")
            return {
                "total_rated_episodes": 0,
                "pending_sync_count": 0,
            }


# Global instance
_rating_cache: Optional[RatingCache] = None


def get_rating_cache(redis_url: str = "redis://localhost:6379/0") -> RatingCache:
    """Get or create global RatingCache instance."""
    global _rating_cache
    if _rating_cache is None:
        _rating_cache = RatingCache(redis_url)
    return _rating_cache
