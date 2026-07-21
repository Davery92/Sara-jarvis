"""
Episode Emotion Integration
Helper to integrate sentiment analysis into episode creation
"""
from typing import Dict, Any, Optional
from app.services.sentiment_analyzer import get_sentiment_analyzer, EmotionMetadata
import logging

logger = logging.getLogger(__name__)


async def analyze_and_format_emotion(
    content: str,
    llm_client=None
) -> Dict[str, Any]:
    """
    Analyze emotion and format for storage in emotion_metadata column

    Args:
        content: Text content to analyze
        llm_client: Optional LLM client for enhanced analysis

    Returns:
        Dictionary suitable for JSON storage in emotion_metadata column
    """
    try:
        analyzer = get_sentiment_analyzer(llm_client)
        emotion: EmotionMetadata = await analyzer.analyze_text(content)

        # Format for database storage
        emotion_data = {
            "sentiment": emotion.sentiment,
            "primary_emotion": emotion.primary_emotion,
            "intensity": emotion.intensity,
            "secondary_emotions": emotion.secondary_emotions,
            "confidence": emotion.confidence,
            "analysis_method": emotion.analysis_method,
            "analyzed_at": "now()"  # Will be replaced by DB function
        }

        return emotion_data

    except Exception as e:
        logger.error(f"Error analyzing emotion: {e}")
        # Return neutral fallback
        return {
            "sentiment": 0.0,
            "primary_emotion": "neutral",
            "intensity": 0.0,
            "secondary_emotions": [],
            "confidence": 0.0,
            "analysis_method": "error",
            "error": str(e)
        }


def emotion_metadata_to_legacy_format(emotion_metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert new emotion_metadata format to legacy emotional_tone format
    For backward compatibility with existing code

    Args:
        emotion_metadata: New emotion metadata format

    Returns:
        Legacy emotional_tone format
    """
    return {
        "primary_emotion": emotion_metadata.get("primary_emotion", "neutral"),
        "sentiment_score": emotion_metadata.get("sentiment", 0.0),
        "intensity": emotion_metadata.get("intensity", 0.0),
        "confidence": emotion_metadata.get("confidence", 0.0)
    }


def legacy_to_emotion_metadata(emotional_tone: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert legacy emotional_tone format to new emotion_metadata format
    For migrating existing episodes

    Args:
        emotional_tone: Legacy format

    Returns:
        New emotion_metadata format
    """
    return {
        "sentiment": emotional_tone.get("sentiment_score", 0.0),
        "primary_emotion": emotional_tone.get("primary_emotion", "neutral"),
        "intensity": emotional_tone.get("intensity", 0.0),
        "secondary_emotions": [],
        "confidence": emotional_tone.get("confidence", 0.5),
        "analysis_method": "legacy_migration"
    }


# Emotion-aware episode retrieval boosting
def calculate_emotion_boost(
    query_emotion: Optional[str],
    episode_emotion: Dict[str, Any],
    user_current_mood: Optional[str] = None
) -> float:
    """
    Calculate relevance boost based on emotional context

    Args:
        query_emotion: Detected emotion in query
        episode_emotion: Episode's emotion metadata
        user_current_mood: User's current mood state

    Returns:
        Boost multiplier (1.0 = no boost, >1.0 = boost, <1.0 = penalty)
    """
    if not episode_emotion:
        return 1.0

    boost = 1.0
    episode_primary = episode_emotion.get("primary_emotion", "neutral")

    # Boost memories with similar emotion to query
    if query_emotion and query_emotion == episode_primary:
        boost *= 1.2

    # If user is feeling negative, boost positive memories slightly
    if user_current_mood:
        user_sentiment = _emotion_to_sentiment(user_current_mood)
        episode_sentiment = episode_emotion.get("sentiment", 0.0)

        if user_sentiment < -0.3 and episode_sentiment > 0.3:
            # User is negative, boost positive memories
            boost *= 1.15
        elif user_sentiment > 0.3 and episode_sentiment > 0.3:
            # User is positive, boost positive memories more
            boost *= 1.1

    return boost


def _emotion_to_sentiment(emotion: str) -> float:
    """Map emotion to approximate sentiment score"""
    emotion_sentiments = {
        "joy": 0.8,
        "excitement": 0.7,
        "contentment": 0.5,
        "neutral": 0.0,
        "sadness": -0.6,
        "anger": -0.7,
        "fear": -0.5,
        "disgust": -0.6,
        "surprise": 0.2
    }
    return emotion_sentiments.get(emotion.lower(), 0.0)


# Migration helper
async def migrate_existing_episodes_to_emotion_metadata(db, limit: int = 100):
    """
    Migrate existing episodes to use new emotion_metadata column

    Args:
        db: Database session
        limit: Number of episodes to migrate per batch

    Returns:
        Number of episodes migrated
    """
    from sqlalchemy import text
    import json

    try:
        # Find episodes with emotional_tone but no emotion_metadata
        query = text("""
            SELECT id, emotional_tone
            FROM episode
            WHERE emotional_tone IS NOT NULL
            AND emotion_metadata IS NULL
            LIMIT :limit
        """)

        result = db.execute(query, {"limit": limit})
        episodes = result.fetchall()

        migrated = 0

        for episode in episodes:
            try:
                # Parse legacy emotional_tone
                emotional_tone = json.loads(episode.emotional_tone) if isinstance(episode.emotional_tone, str) else episode.emotional_tone

                # Convert to new format
                emotion_metadata = legacy_to_emotion_metadata(emotional_tone)

                # Update episode
                update_query = text("""
                    UPDATE episodes
                    SET emotion_metadata = :emotion_metadata
                    WHERE id = :episode_id
                """)

                db.execute(update_query, {
                    "episode_id": episode.id,
                    "emotion_metadata": json.dumps(emotion_metadata)
                })

                migrated += 1

            except Exception as e:
                logger.error(f"Error migrating episode {episode.id}: {e}")
                continue

        db.commit()
        logger.info(f"✅ Migrated {migrated} episodes to emotion_metadata format")
        return migrated

    except Exception as e:
        logger.error(f"Error in migration: {e}")
        db.rollback()
        return 0
