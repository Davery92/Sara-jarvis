"""
Nightly rating consolidation job.

Syncs rating data from Redis cache to PostgreSQL and Neo4j, calculates rating boosts
and exploration bonuses, and performs data consistency checks.
"""

import logging
from datetime import datetime
from typing import List, Dict, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from ..main_simple import Episode, EpisodeRating
from .rating_cache import RatingCache, get_rating_cache
from .rating_service import RatingService
from .thompson_sampling import ThompsonSampler, get_thompson_sampler
from .rating_events import RatingEventPublisher, get_rating_publisher
from .neo4j_service import Neo4jService

logger = logging.getLogger(__name__)


class RatingConsolidationJob:
    """Nightly job to consolidate ratings from Redis to PostgreSQL and Neo4j."""

    def __init__(
        self,
        db: Session,
        redis_url: str = "redis://localhost:6379/0",
        neo4j_service: Neo4jService = None
    ):
        """
        Initialize consolidation job.

        Args:
            db: SQLAlchemy database session
            redis_url: Redis connection URL
            neo4j_service: Neo4j service instance (optional)
        """
        self.db = db
        self.cache = get_rating_cache(redis_url)
        self.sampler = get_thompson_sampler()
        self.publisher = get_rating_publisher(redis_url)
        self.neo4j_service = neo4j_service

    async def run(self, batch_size: int = 100) -> Dict[str, int]:
        """
        Run the consolidation job.

        Args:
            batch_size: Number of episodes to process per batch

        Returns:
            Dict with statistics: episodes_processed, success_count, error_count
        """
        logger.info("Starting nightly rating consolidation job")
        start_time = datetime.utcnow()

        total_processed = 0
        success_count = 0
        error_count = 0
        synced_episode_ids = []

        try:
            # Get count of dirty episodes
            dirty_count = await self.cache.get_dirty_count()
            logger.info(f"Found {dirty_count} episodes with rating changes to sync")

            # Process in batches
            while True:
                # Get batch of dirty episode IDs
                episode_ids = await self.cache.get_dirty_episodes(batch_size)
                if not episode_ids:
                    break

                # Process batch
                batch_results = await self._process_batch(episode_ids)
                total_processed += len(episode_ids)
                success_count += batch_results["success"]
                error_count += batch_results["error"]
                synced_episode_ids.extend(batch_results["synced_ids"])

                logger.info(
                    f"Processed batch: {len(episode_ids)} episodes "
                    f"({batch_results['success']} success, {batch_results['error']} errors)"
                )

            # Publish sync completion event
            if synced_episode_ids:
                await self.publisher.publish_rating_synced(
                    episode_ids=synced_episode_ids,
                    success_count=success_count,
                    error_count=error_count
                )

            # Run consistency checks
            consistency_results = await self._check_consistency()

            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.info(
                f"Rating consolidation completed in {duration:.2f}s: "
                f"{total_processed} episodes processed "
                f"({success_count} success, {error_count} errors)"
            )

            return {
                "episodes_processed": total_processed,
                "success_count": success_count,
                "error_count": error_count,
                "duration_seconds": duration,
                "consistency_checks": consistency_results
            }

        except Exception as e:
            logger.error(f"Rating consolidation job failed: {e}", exc_info=True)
            return {
                "episodes_processed": total_processed,
                "success_count": success_count,
                "error_count": error_count + 1,
                "error": str(e)
            }

    async def _process_batch(self, episode_ids: List[str]) -> Dict[str, any]:
        """
        Process a batch of episodes.

        Args:
            episode_ids: List of episode UUIDs to process

        Returns:
            Dict with success count, error count, and synced IDs
        """
        success = 0
        error = 0
        synced_ids = []

        # Get cached rating data for all episodes
        cached_ratings = await self.cache.get_episode_ratings_batch(episode_ids)

        for episode_id in episode_ids:
            try:
                # Get cached rating
                cached = cached_ratings.get(episode_id)
                if not cached:
                    logger.warning(f"No cached rating for episode {episode_id}, skipping")
                    error += 1
                    continue

                # Sync to PostgreSQL
                sync_success = await self._sync_episode_to_db(episode_id, cached)
                if not sync_success:
                    error += 1
                    continue

                # Sync to Neo4j (if available)
                if self.neo4j_service:
                    await self._sync_episode_to_neo4j(episode_id, cached)

                success += 1
                synced_ids.append(episode_id)

            except Exception as e:
                logger.error(f"Failed to process episode {episode_id}: {e}")
                error += 1

        return {
            "success": success,
            "error": error,
            "synced_ids": synced_ids
        }

    async def _sync_episode_to_db(self, episode_id: str, cached_rating: Dict) -> bool:
        """
        Sync rating from cache to PostgreSQL.

        Args:
            episode_id: Episode UUID
            cached_rating: Cached rating data dict

        Returns:
            True if synced successfully
        """
        try:
            # Get or create episode rating record
            rating = self.db.query(EpisodeRating).filter(
                EpisodeRating.episode_id == episode_id
            ).first()

            if not rating:
                rating = EpisodeRating(episode_id=episode_id)
                self.db.add(rating)

            # Update rating fields
            rating.user_rating = cached_rating["user_rating"]
            rating.rating_count = cached_rating["rating_count"]
            rating.average_rating = cached_rating["average_rating"]
            rating.rating_sum = cached_rating["rating_sum"]
            if cached_rating["last_rated"]:
                rating.last_rated = datetime.fromisoformat(cached_rating["last_rated"])
            rating.updated_at = datetime.utcnow()

            # Get episode for boost calculations
            episode = self.db.query(Episode).filter(Episode.id == episode_id).first()
            if not episode:
                logger.warning(f"Episode {episode_id} not found in database")
                return False

            # Calculate rating boost (Wilson Score + temporal decay)
            rating_boost = self._calculate_rating_boost(
                rating_sum=cached_rating["rating_sum"],
                rating_count=cached_rating["rating_count"],
                created_at=episode.created_at
            )

            # Calculate exploration bonus (Thompson Sampling)
            exploration_bonus = self.sampler.calculate_exploration_bonus(
                rating_sum=cached_rating["rating_sum"],
                rating_count=cached_rating["rating_count"],
                created_at=episode.created_at
            )

            # Update episode
            episode.rating_boost = rating_boost
            episode.exploration_bonus = exploration_bonus

            self.db.commit()

            logger.debug(
                f"Synced rating for episode {episode_id}: "
                f"boost={rating_boost:.4f}, exploration={exploration_bonus:.4f}"
            )

            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to sync episode {episode_id} to database: {e}")
            return False

    def _calculate_rating_boost(
        self,
        rating_sum: int,
        rating_count: int,
        created_at: datetime
    ) -> float:
        """
        Calculate rating boost using Wilson Score + temporal decay.

        This duplicates the logic from RatingService to avoid circular imports.
        """
        import math

        if rating_count == 0:
            return 0.0

        # Normalize to 0-1 scale
        p = rating_sum / (5.0 * rating_count)

        # Wilson Score parameters
        z = 1.96  # 95% confidence
        n = rating_count

        # Wilson Score lower bound
        numerator = (
            p +
            (z * z) / (2 * n) -
            z * math.sqrt((p * (1 - p) / n) + (z * z) / (4 * n * n))
        )
        denominator = 1 + (z * z) / n
        confidence = numerator / denominator

        # Temporal decay (exponential, 30-day half-life)
        age_days = (datetime.utcnow() - created_at).days
        decay_constant = math.log(2) / 30.0
        age_decay = math.exp(-decay_constant * age_days)

        # Final boost (0-0.25 range)
        rating_boost = confidence * age_decay * 0.25

        return rating_boost

    async def _sync_episode_to_neo4j(self, episode_id: str, cached_rating: Dict) -> bool:
        """
        Sync rating to Neo4j graph.

        Args:
            episode_id: Episode UUID
            cached_rating: Cached rating data dict

        Returns:
            True if synced successfully
        """
        if not self.neo4j_service:
            return False

        try:
            # Update episode node properties
            await self.neo4j_service.update_episode_rating(
                episode_id=episode_id,
                user_rating=cached_rating["user_rating"],
                rating_count=cached_rating["rating_count"],
                average_rating=cached_rating["average_rating"],
                rating_sum=cached_rating["rating_sum"]
            )

            logger.debug(f"Synced rating for episode {episode_id} to Neo4j")
            return True

        except Exception as e:
            logger.error(f"Failed to sync episode {episode_id} to Neo4j: {e}")
            return False

    async def _check_consistency(self) -> Dict[str, any]:
        """
        Run data consistency checks between Redis and PostgreSQL.

        Returns:
            Dict with consistency check results
        """
        logger.info("Running rating data consistency checks")

        try:
            # Count total ratings in PostgreSQL
            db_count = self.db.query(EpisodeRating).filter(
                EpisodeRating.rating_count > 0
            ).count()

            # Get cache stats
            cache_stats = await self.cache.get_rating_stats()
            cache_count = cache_stats["total_rated_episodes"]

            # Calculate discrepancy
            if db_count > 0:
                discrepancy_pct = abs(cache_count - db_count) / db_count * 100
            else:
                discrepancy_pct = 0.0

            # Log warning if discrepancy is high
            if discrepancy_pct > 10:
                logger.warning(
                    f"High data discrepancy detected: "
                    f"DB={db_count}, Cache={cache_count}, "
                    f"Discrepancy={discrepancy_pct:.1f}%"
                )
            elif discrepancy_pct > 5:
                logger.info(
                    f"Minor data discrepancy: "
                    f"DB={db_count}, Cache={cache_count}, "
                    f"Discrepancy={discrepancy_pct:.1f}%"
                )
            else:
                logger.info(f"Data consistency check passed (discrepancy={discrepancy_pct:.1f}%)")

            return {
                "db_count": db_count,
                "cache_count": cache_count,
                "discrepancy_percent": discrepancy_pct,
                "status": "ok" if discrepancy_pct <= 10 else "warning"
            }

        except Exception as e:
            logger.error(f"Consistency check failed: {e}")
            return {
                "error": str(e),
                "status": "error"
            }


async def run_rating_consolidation_job(db: Session, neo4j_service: Neo4jService = None):
    """
    Entry point for nightly rating consolidation job.

    Args:
        db: SQLAlchemy database session
        neo4j_service: Neo4j service instance (optional)
    """
    job = RatingConsolidationJob(db, neo4j_service=neo4j_service)
    results = await job.run()

    logger.info(f"Rating consolidation job completed: {results}")

    return results
