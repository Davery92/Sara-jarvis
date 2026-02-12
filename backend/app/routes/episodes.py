"""Episode and memory management routes.

Extracted from main_simple.py: memory/episodes CRUD, episode ratings,
memory search (GET and POST), dream insights, and find-by-content.
"""
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from sqlalchemy import text
from typing import List, Optional

from app.db.session import get_db
from app.db.base import SessionLocal
from app.core.deps import get_current_user
from app.core.timezone import format_iso_utc
from app.models.user import User
from app.models.episode import Episode
from app.models.episode_rating import EpisodeRating
from app.models.dream import DreamInsight

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Memory Management endpoints  (/memory/episodes)
# ---------------------------------------------------------------------------

@router.get("/memory/episodes")
async def get_episodes(
    page: int = 1,
    per_page: int = 20,
    min_importance: float = None,
    max_importance: float = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get episodes with pagination and filtering"""
    try:
        # Build base query
        query = db.query(Episode).filter(Episode.user_id == current_user.id)

        # Apply importance filters
        if min_importance is not None:
            query = query.filter(Episode.importance >= min_importance)
        if max_importance is not None:
            query = query.filter(Episode.importance <= max_importance)

        # Get total count
        total = query.count()

        # Apply pagination and ordering
        episodes = (
            query.order_by(Episode.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        # Format episodes for frontend
        episode_data = []
        for episode in episodes:
            episode_data.append(
                {
                    "id": episode.id,
                    "source": episode.source or "chat",
                    "role": episode.role,
                    "content": episode.content,
                    "importance": episode.importance,
                    "meta": {
                        "memory_type": getattr(episode, "memory_type", None),
                        "topics": getattr(episode, "topics", None),
                        "emotional_tone": getattr(episode, "emotional_tone", None),
                        "context_tags": getattr(episode, "context_tags", None),
                        "access_count": getattr(episode, "access_count", None),
                    },
                    "created_at": format_iso_utc(episode.created_at),
                }
            )

        return {
            "episodes": episode_data,
            "total": total,
            "page": page,
            "per_page": per_page,
        }
    except Exception as e:
        logger.error(f"Error retrieving episodes: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve episodes")


@router.delete("/memory/episodes/{episode_id}")
async def delete_episode(
    episode_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a specific episode"""
    try:
        # Find the episode
        episode = (
            db.query(Episode)
            .filter(Episode.id == episode_id, Episode.user_id == current_user.id)
            .first()
        )

        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")

        # Delete the episode
        db.delete(episode)
        db.commit()

        logger.info(f"Deleted episode {episode_id} for user {current_user.id}")
        return {"message": "Episode deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting episode {episode_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete episode")


@router.patch("/memory/episodes/{episode_id}")
async def update_episode(
    episode_id: str,
    importance: float,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update episode importance"""
    try:
        # Validate importance value
        if not (0.0 <= importance <= 1.0):
            raise HTTPException(
                status_code=400, detail="Importance must be between 0.0 and 1.0"
            )

        # Find the episode
        episode = (
            db.query(Episode)
            .filter(Episode.id == episode_id, Episode.user_id == current_user.id)
            .first()
        )

        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")

        # Update the importance
        episode.importance = importance
        episode.updated_at = func.now()
        db.commit()

        logger.info(
            f"Updated episode {episode_id} importance to {importance} for user {current_user.id}"
        )
        return {"message": "Episode importance updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating episode {episode_id}: {e}")
        db.rollback()
        raise HTTPException(
            status_code=500, detail="Failed to update episode importance"
        )


# ---------------------------------------------------------------------------
# Episode search (POST /memory/search)
# ---------------------------------------------------------------------------

@router.post("/memory/search")
async def search_episodes(
    search_request: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Search episodes with POST request body"""
    try:
        query = search_request.get("query", "")
        scopes = search_request.get("scopes", ["episodes"])
        limit = search_request.get("limit", 50)

        if not query.strip():
            return {"results": []}

        # Search episodes by content using LIKE for now (could be enhanced with vector search)
        episodes = (
            db.query(Episode)
            .filter(
                Episode.user_id == current_user.id,
                Episode.content.ilike(f"%{query}%"),
            )
            .order_by(Episode.created_at.desc())
            .limit(limit)
            .all()
        )

        # Format results for frontend
        results = []
        for episode in episodes:
            results.append(
                {
                    "text": episode.content,
                    "metadata": {
                        "episode_id": episode.id,
                        "id": episode.id,
                        "importance": episode.importance,
                        "role": episode.role,
                        "source": episode.source or "chat",
                        "timestamp": format_iso_utc(episode.created_at),
                        "memory_type": getattr(episode, "memory_type", None),
                        "topics": getattr(episode, "topics", None),
                        "emotional_tone": getattr(episode, "emotional_tone", None),
                        "context_tags": getattr(episode, "context_tags", None),
                    },
                }
            )

        return {"results": results}

    except Exception as e:
        logger.error(f"Error searching episodes: {e}")
        raise HTTPException(status_code=500, detail="Failed to search episodes")


# ---------------------------------------------------------------------------
# Episode Rating endpoints  (/api/episodes/...)
# ---------------------------------------------------------------------------

@router.post("/api/episodes/{episode_id}/rate")
async def rate_episode(
    episode_id: str,
    rating_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Rate an episode (1-5 stars)"""
    try:
        from app.services.rating_service import get_rating_service
        from app.services.rating_events import get_rating_publisher
        from app.core.config import settings

        rating = rating_data.get("rating")
        if not rating or not (1 <= rating <= 5):
            raise HTTPException(
                status_code=400, detail="Rating must be between 1 and 5"
            )

        # Get rating service
        rating_service = get_rating_service(db, redis_url=settings.redis_url)

        # Rate the episode
        result = await rating_service.rate_episode(
            episode_id=episode_id, user_id=current_user.id, rating=rating
        )

        # Publish event for real-time updates
        publisher = get_rating_publisher(redis_url=settings.redis_url)
        await publisher.publish_episode_rated(
            episode_id=episode_id,
            user_id=current_user.id,
            rating=rating,
            net_score=result["rating_sum"],
            rating_count=result["rating_count"],
            average_rating=result["average_rating"],
        )

        # Dispatch karma recording asynchronously via Celery
        try:
            from app.tasks.karma import record_rating_to_karma
            record_rating_to_karma.delay(episode_id, rating, str(current_user.id))
        except Exception as karma_err:
            logger.warning(f"Failed to dispatch karma task for rating: {karma_err}")

        return {"success": True, "message": "Episode rated successfully", "rating": result}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error rating episode {episode_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to rate episode")


@router.get("/api/episodes/{episode_id}/rating")
async def get_episode_rating(
    episode_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get rating data for an episode"""
    try:
        from app.services.rating_service import get_rating_service
        from app.core.config import settings

        rating_service = get_rating_service(db, redis_url=settings.redis_url)
        rating_data = await rating_service.get_episode_rating(episode_id)

        if not rating_data:
            return {"rated": False}

        # Also get user's specific rating
        user_rating = await rating_service.get_user_rating(current_user.id, episode_id)
        rating_data["user_rating"] = user_rating
        rating_data["rated"] = True

        return rating_data

    except Exception as e:
        logger.error(f"Error getting rating for episode {episode_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get episode rating")


@router.delete("/api/episodes/{episode_id}/rating")
async def delete_episode_rating(
    episode_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete user's rating for an episode"""
    try:
        from app.services.rating_service import get_rating_service
        from app.core.config import settings

        rating_service = get_rating_service(db, redis_url=settings.redis_url)
        success = await rating_service.delete_rating(episode_id, current_user.id)

        if not success:
            raise HTTPException(status_code=404, detail="Rating not found")

        return {"success": True, "message": "Rating deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting rating for episode {episode_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete rating")


@router.get("/api/rating/stats")
async def get_rating_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get rating system statistics"""
    try:
        from app.services.rating_service import get_rating_service
        from app.core.config import settings

        rating_service = get_rating_service(db, redis_url=settings.redis_url)
        stats = await rating_service.get_rating_stats()

        return stats

    except Exception as e:
        logger.error(f"Error getting rating stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get rating stats")


@router.post("/api/episodes/find-by-content")
async def find_episodes_by_content(
    request: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Find episode IDs by conversation_id and content (for rating UI)"""
    try:
        conversation_id = request.get("conversation_id")
        messages = request.get("messages", [])  # [{role, content}]

        if not conversation_id or not messages:
            return {"episodes": []}

        # Find episodes matching the conversation and content
        result_episodes = []
        for msg in messages:
            episode = (
                db.query(Episode)
                .filter(
                    Episode.conversation_id == conversation_id,
                    Episode.user_id == current_user.id,
                    Episode.role == msg["role"],
                    Episode.content == msg["content"],
                )
                .first()
            )

            if episode:
                result_episodes.append(
                    {
                        "role": episode.role,
                        "content": episode.content[:100],  # Preview
                        "episode_id": episode.id,
                    }
                )
            else:
                result_episodes.append(
                    {
                        "role": msg["role"],
                        "content": msg["content"][:100],
                        "episode_id": None,
                    }
                )

        return {"episodes": result_episodes}

    except Exception as e:
        logger.error(f"Error finding episodes by content: {e}")
        raise HTTPException(status_code=500, detail="Failed to find episodes")


# ---------------------------------------------------------------------------
# Memory search (GET /memory/search)  — uses llm_client from main_simple
# ---------------------------------------------------------------------------

@router.get("/memory/search")
async def search_memory(
    query: str,
    limit: int = 10,
    current_user: User = Depends(get_current_user),
):
    """Search through conversation memory"""
    if not query.strip():
        return {"results": []}

    try:
        # Import llm_client lazily to avoid circular imports
        from app.main_simple import llm_client

        # Use the existing search_memory_tool method
        search_results = await llm_client.search_memory_tool(query, current_user.id)

        return {"query": query, "results": search_results}

    except Exception as e:
        logger.error(f"Memory search error: {e}")
        raise HTTPException(
            status_code=500, detail=f"Memory search failed: {str(e)}"
        )


# ---------------------------------------------------------------------------
# Dream Insights  (/memory/insights)
# ---------------------------------------------------------------------------

@router.get("/memory/insights")
async def get_dream_insights(
    limit: int = 10,
    insight_type: str = None,
    current_user: User = Depends(get_current_user),
):
    """Get AI-generated insights from background dreaming/consolidation"""
    try:
        db = SessionLocal()
        try:
            query_filter = [DreamInsight.user_id == current_user.id]

            if insight_type:
                query_filter.append(DreamInsight.insight_type == insight_type)

            insights = (
                db.query(DreamInsight)
                .filter(*query_filter)
                .order_by(DreamInsight.dream_date.desc())
                .limit(limit)
                .all()
            )

            insights_data = []
            for insight in insights:
                insight_dict = {
                    "id": insight.id,
                    "type": insight.insight_type,
                    "title": insight.title,
                    "content": insight.content,
                    "confidence": insight.confidence,
                    "dream_date": insight.dream_date.isoformat(),
                    "surfaced_at": (
                        insight.surfaced_at.isoformat() if insight.surfaced_at else None
                    ),
                    "user_feedback": insight.user_feedback,
                    "related_episodes": (
                        json.loads(insight.related_episodes)
                        if insight.related_episodes
                        else []
                    ),
                }
                insights_data.append(insight_dict)

            return {"insights": insights_data, "total": len(insights_data)}
        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error fetching dream insights: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch insights")


@router.patch("/memory/insights/{insight_id}/feedback")
async def update_insight_feedback(
    insight_id: str,
    feedback: str,
    current_user: User = Depends(get_current_user),
):
    """Update user feedback on a dream insight"""
    try:
        db = SessionLocal()
        try:
            insight = (
                db.query(DreamInsight)
                .filter(
                    DreamInsight.id == insight_id,
                    DreamInsight.user_id == current_user.id,
                )
                .first()
            )

            if not insight:
                raise HTTPException(status_code=404, detail="Insight not found")

            insight.user_feedback = feedback
            insight.surfaced_at = datetime.now(timezone.utc)
            db.commit()

            return {"status": "updated", "feedback": feedback}
        finally:
            db.close()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating insight feedback: {e}")
        raise HTTPException(status_code=500, detail="Failed to update feedback")
