"""
Importance Re-Scoring System
Dynamic importance scoring for memories based on:
- Recency decay
- Access frequency
- Cross-reference popularity
- User explicit ratings
"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
import math
import logging

logger = logging.getLogger(__name__)


def _ensure_aware(dt: datetime) -> datetime:
    """Treat naive timestamps (from timestamp-without-timezone columns) as UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class ImportanceScore(BaseModel):
    """Calculated importance score with components"""
    episode_id: str
    base_importance: float
    recency_factor: float
    frequency_factor: float
    popularity_factor: float
    user_rating_factor: float
    final_score: float
    score_date: datetime


class ImportanceScorer:
    """Calculates and updates memory importance scores"""

    def __init__(self, db: Session):
        self.db = db

        # Scoring weights (sum to 1.0). H4 (Brain Alignment): emotion and
        # novelty now carry weight so intense/surprising memories resist the
        # decay-to-floor that made importance flat (avg 0.11). Recency weight
        # is reduced to make room — an emotionally charged memory should stay
        # important even when it's no longer recent.
        self.weights = {
            "base": 0.28,        # Original importance
            "recency": 0.17,     # How recent
            "frequency": 0.15,   # Access frequency
            "popularity": 0.10,  # Cross-reference count
            "user_rating": 0.10, # User explicit rating
            "emotion": 0.10,     # Emotional intensity at encoding
            "novelty": 0.10,     # Novelty (surprise) at encoding
        }

        # Decay parameters - unified 14-day baseline
        # This matches the retrieval-time recency decay for consistency
        # Future: category-based multipliers will adjust per memory type
        self.recency_halflife_days = 14  # Importance halves every 14 days (unified baseline)
        self.frequency_decay_days = 90   # Access frequency window

    def calculate_recency_factor(self, created_at: datetime) -> float:
        """
        Calculate recency decay factor using exponential decay

        Args:
            created_at: When episode was created

        Returns:
            Factor from 0.0 to 1.0 (1.0 = today, decays over time)
        """
        days_ago = (datetime.now(timezone.utc) - _ensure_aware(created_at)).days

        # Exponential decay: score = e^(-λt)
        # Where λ = ln(2) / halflife
        decay_rate = math.log(2) / self.recency_halflife_days
        factor = math.exp(-decay_rate * days_ago)

        return max(0.0, min(1.0, factor))

    def calculate_frequency_factor(self, access_count: int, last_accessed: Optional[datetime]) -> float:
        """
        Calculate frequency factor based on access count and recency

        Args:
            access_count: Number of times accessed
            last_accessed: Last access time

        Returns:
            Factor from 0.0 to 1.0
        """
        if access_count == 0:
            return 0.0

        # Normalize access count (logarithmic scale)
        # More accesses = higher score, but with diminishing returns
        normalized_count = math.log(access_count + 1) / math.log(100)  # Max at ~100 accesses
        count_factor = min(1.0, normalized_count)

        # Apply recency decay to frequency
        if last_accessed:
            days_since_access = (datetime.now(timezone.utc) - _ensure_aware(last_accessed)).days
            recency_weight = max(0.1, 1.0 - (days_since_access / self.frequency_decay_days))
        else:
            recency_weight = 0.5  # Default if no access data

        return count_factor * recency_weight

    async def calculate_popularity_factor(self, episode_id: str) -> float:
        """
        Calculate popularity based on cross-references.
        Currently returns 0.0 — memory_references table not yet created.
        Uses access_count as a proxy instead.
        """
        try:
            query = text("""
                SELECT COALESCE(access_count, 0) as acc
                FROM episode WHERE id = :episode_id
            """)
            result = self.db.execute(query, {"episode_id": episode_id})
            row = result.fetchone()
            if not row or row.acc == 0:
                return 0.0
            # Logarithmic scaling of access count as proxy for popularity
            normalized = math.log(row.acc + 1) / math.log(50)
            return min(1.0, normalized)
        except Exception:
            return 0.0

    def calculate_user_rating_factor(self, user_rating: Optional[float]) -> float:
        """
        Convert user rating to factor

        Args:
            user_rating: User's explicit rating (1-10 scale)

        Returns:
            Factor from 0.0 to 1.0
        """
        if user_rating is None:
            return 0.5  # Neutral default

        # Normalize 1-10 scale to 0-1
        return (user_rating - 1) / 9.0

    def _emotion_novelty_from_meta(self, meta: Any, emotional_tone: Any) -> tuple:
        """Extract (emotional_intensity, novelty) from an episode's stored
        meta/emotion fields. Defaults to neutral (0.0 emotion, 0.5 novelty)."""
        import json as _json
        emotion = None
        novelty = None
        try:
            m = meta if isinstance(meta, dict) else (_json.loads(meta) if meta else {})
            if isinstance(m, dict):
                emotion = m.get("emotional_intensity")
                novelty = m.get("novelty")
        except Exception:
            pass
        if emotion is None and emotional_tone:
            try:
                et = emotional_tone if isinstance(emotional_tone, dict) else _json.loads(emotional_tone)
                if isinstance(et, dict):
                    emotion = et.get("intensity")
            except Exception:
                pass
        return (
            max(0.0, min(1.0, float(emotion))) if emotion is not None else 0.0,
            max(0.0, min(1.0, float(novelty))) if novelty is not None else 0.5,
        )

    async def calculate_importance(
        self,
        episode_id: str,
        base_importance: float,
        created_at: datetime,
        access_count: int,
        last_accessed: Optional[datetime],
        user_rating: Optional[float] = None,
        emotional_intensity: float = 0.0,
        novelty: float = 0.5,
    ) -> ImportanceScore:
        """
        Calculate complete importance score

        Args:
            episode_id: Episode ID
            base_importance: Original importance score
            created_at: Creation timestamp
            access_count: Access count
            last_accessed: Last access timestamp
            user_rating: Optional user rating (1-10)

        Returns:
            ImportanceScore with all components
        """
        # Calculate individual factors
        recency_factor = self.calculate_recency_factor(created_at)
        frequency_factor = self.calculate_frequency_factor(access_count, last_accessed)
        popularity_factor = await self.calculate_popularity_factor(episode_id)
        user_rating_factor = self.calculate_user_rating_factor(user_rating)

        emotion_factor = max(0.0, min(1.0, emotional_intensity))
        novelty_factor = max(0.0, min(1.0, novelty))

        # Weighted combination
        final_score = (
            self.weights["base"] * base_importance +
            self.weights["recency"] * recency_factor +
            self.weights["frequency"] * frequency_factor +
            self.weights["popularity"] * popularity_factor +
            self.weights["user_rating"] * user_rating_factor +
            self.weights["emotion"] * emotion_factor +
            self.weights["novelty"] * novelty_factor
        )

        # Ensure score is in valid range
        final_score = max(0.0, min(1.0, final_score))

        return ImportanceScore(
            episode_id=episode_id,
            base_importance=base_importance,
            recency_factor=recency_factor,
            frequency_factor=frequency_factor,
            popularity_factor=popularity_factor,
            user_rating_factor=user_rating_factor,
            final_score=final_score,
            score_date=datetime.now(timezone.utc)
        )

    async def rescore_episode(self, episode_id: str) -> Optional[float]:
        """
        Rescore a single episode and update in database

        Args:
            episode_id: Episode ID to rescore

        Returns:
            New importance score or None if failed
        """
        try:
            # Get episode data
            query = text("""
                SELECT
                    id,
                    base_importance,
                    importance,
                    created_at,
                    access_count,
                    last_accessed,
                    user_rating,
                    meta,
                    emotional_tone
                FROM episode
                WHERE id = :episode_id
            """)

            result = self.db.execute(query, {"episode_id": episode_id})
            episode = result.fetchone()

            if not episode:
                logger.warning(f"Episode {episode_id} not found")
                return None

            # Use current importance as base if no base_importance
            base_importance = episode.base_importance if episode.base_importance is not None else episode.importance
            emo, nov = self._emotion_novelty_from_meta(episode.meta, episode.emotional_tone)

            # Calculate new score
            score = await self.calculate_importance(
                episode_id=episode.id,
                base_importance=base_importance,
                created_at=episode.created_at,
                access_count=episode.access_count or 0,
                last_accessed=episode.last_accessed,
                user_rating=episode.user_rating,
                emotional_intensity=emo,
                novelty=nov,
            )

            # Update episode
            update_query = text("""
                UPDATE episode
                SET
                    importance = :importance,
                    importance_last_updated = NOW()
                WHERE id = :episode_id
            """)

            self.db.execute(update_query, {
                "episode_id": episode_id,
                "importance": score.final_score
            })

            self.db.commit()

            logger.debug(f"Rescored episode {episode_id}: {episode.importance:.3f} → {score.final_score:.3f}")
            return score.final_score

        except Exception as e:
            logger.error(f"Error rescoring episode {episode_id}: {e}")
            self.db.rollback()
            return None

    async def rescore_all_episodes(
        self,
        user_id: Optional[str] = None,
        batch_size: int = 100,
        max_batches: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Rescore all episodes (or for specific user)

        Args:
            user_id: Optional user ID to filter by
            batch_size: Episodes per batch
            max_batches: Maximum batches to process (None = all)

        Returns:
            Statistics about rescoring
        """
        rescored = 0
        failed = 0
        batches = 0

        try:
            # Count total episodes
            user_filter = "WHERE user_id = :user_id" if user_id else ""
            count_query = text(f"""
                SELECT COUNT(*) as total
                FROM episode
                {user_filter}
            """)

            params = {"user_id": user_id} if user_id else {}
            result = self.db.execute(count_query, params)
            total_episodes = result.fetchone().total

            logger.info(f"🔄 Starting importance rescoring for {total_episodes} episodes")

            # Process in batches
            while True:
                if max_batches and batches >= max_batches:
                    break

                # Get batch of episodes
                batch_query = text(f"""
                    SELECT
                        id,
                        base_importance,
                        importance,
                        created_at,
                        access_count,
                        last_accessed,
                        user_rating,
                        meta,
                        emotional_tone
                    FROM episode
                    {user_filter}
                    ORDER BY id
                    LIMIT :limit
                    OFFSET :offset
                """)

                batch_params = {"limit": batch_size, "offset": batches * batch_size}
                if user_id:
                    batch_params["user_id"] = user_id
                result = self.db.execute(batch_query, batch_params)

                episodes = result.fetchall()

                if not episodes:
                    break

                # Rescore batch
                for episode in episodes:
                    try:
                        base_importance = episode.base_importance if episode.base_importance is not None else episode.importance
                        emo, nov = self._emotion_novelty_from_meta(episode.meta, episode.emotional_tone)

                        score = await self.calculate_importance(
                            episode_id=episode.id,
                            base_importance=base_importance,
                            created_at=episode.created_at,
                            access_count=episode.access_count or 0,
                            last_accessed=episode.last_accessed,
                            user_rating=episode.user_rating,
                            emotional_intensity=emo,
                            novelty=nov,
                        )

                        # Batch update
                        update_query = text("""
                            UPDATE episode
                            SET
                                importance = :importance,
                                importance_last_updated = NOW()
                            WHERE id = :episode_id
                        """)

                        self.db.execute(update_query, {
                            "episode_id": episode.id,
                            "importance": score.final_score
                        })

                        rescored += 1

                    except Exception as e:
                        logger.error(f"Error rescoring episode {episode.id}: {e}")
                        failed += 1

                # Commit batch
                self.db.commit()
                batches += 1

                if batches % 10 == 0:
                    logger.info(f"Progress: {rescored}/{total_episodes} rescored")

            logger.info(f"✅ Rescoring complete: {rescored} success, {failed} failed")

            return {
                "total_episodes": total_episodes,
                "rescored": rescored,
                "failed": failed,
                "batches": batches
            }

        except Exception as e:
            logger.error(f"Error in rescore_all_episodes: {e}")
            self.db.rollback()
            return {
                "error": str(e),
                "rescored": rescored,
                "failed": failed
            }

    async def identify_low_importance_episodes(
        self,
        user_id: str,
        threshold: float = 0.1,
        age_days: int = 180,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Identify low-importance old episodes for consolidation

        Args:
            user_id: User ID
            threshold: Importance threshold (below = low)
            age_days: Minimum age in days
            limit: Max results

        Returns:
            List of low-importance episodes
        """
        try:
            query = text("""
                SELECT
                    id,
                    content,
                    importance,
                    created_at,
                    access_count,
                    topics
                FROM episode
                WHERE user_id = :user_id
                AND importance < :threshold
                AND created_at < NOW() - make_interval(days => :age_days)
                AND consolidated = FALSE
                ORDER BY importance ASC, created_at ASC
                LIMIT :limit
            """)

            result = self.db.execute(query, {
                "user_id": user_id,
                "threshold": threshold,
                "age_days": age_days,
                "limit": limit
            })

            episodes = []
            for row in result.fetchall():
                episodes.append({
                    "id": row.id,
                    "content": row.content[:200],  # Truncated
                    "importance": row.importance,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "access_count": row.access_count,
                    "topics": row.topics
                })

            return episodes

        except Exception as e:
            logger.error(f"Error identifying low-importance episodes: {e}")
            return []


def get_importance_scorer(db: Session) -> ImportanceScorer:
    """Get importance scorer instance"""
    return ImportanceScorer(db)
