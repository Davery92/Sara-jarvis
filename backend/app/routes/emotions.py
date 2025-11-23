"""
Emotion Analysis API Endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.auth import get_current_user_id
from app.services.emotion_trend_analyzer import get_emotion_trend_analyzer
from typing import Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/emotions/summary")
async def get_emotion_summary(
    days: int = 7,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Get comprehensive emotion summary

    Args:
        days: Number of days to analyze (default: 7)

    Returns:
        Emotion summary with trends, patterns, and insights
    """
    try:
        analyzer = get_emotion_trend_analyzer(db)
        summary = await analyzer.get_emotion_summary(user_id, days)

        return {
            "success": True,
            "data": summary
        }

    except Exception as e:
        logger.error(f"Error getting emotion summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/emotions/trends")
async def get_emotion_trends(
    days: int = 30,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Get daily emotion trends

    Args:
        days: Number of days to analyze (default: 30)

    Returns:
        Daily emotion trend data
    """
    try:
        analyzer = get_emotion_trend_analyzer(db)
        trends = await analyzer.get_daily_trend(user_id, days)

        return {
            "success": True,
            "data": {
                "trends": [t.dict() for t in trends],
                "period_days": days
            }
        }

    except Exception as e:
        logger.error(f"Error getting emotion trends: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/emotions/shifts")
async def get_mood_shifts(
    days: int = 7,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Get detected mood shifts

    Args:
        days: Number of days to analyze (default: 7)

    Returns:
        List of significant mood shifts
    """
    try:
        analyzer = get_emotion_trend_analyzer(db)
        shifts = await analyzer.detect_mood_shifts(user_id, days)

        return {
            "success": True,
            "data": {
                "shifts": shifts,
                "period_days": days
            }
        }

    except Exception as e:
        logger.error(f"Error detecting mood shifts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/emotions/patterns")
async def get_emotion_patterns(
    days: int = 30,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Get detected emotional patterns

    Args:
        days: Number of days to analyze (default: 30)

    Returns:
        List of detected patterns (weekly, daily, trigger-based)
    """
    try:
        analyzer = get_emotion_trend_analyzer(db)
        patterns = await analyzer.detect_patterns(user_id, days)

        return {
            "success": True,
            "data": {
                "patterns": [p.dict() for p in patterns],
                "period_days": days
            }
        }

    except Exception as e:
        logger.error(f"Error detecting patterns: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/emotions/distribution")
async def get_emotion_distribution(
    days: int = 30,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Get emotion distribution (pie chart data)

    Args:
        days: Number of days to analyze (default: 30)

    Returns:
        Emotion distribution counts
    """
    try:
        from sqlalchemy import text
        from datetime import datetime, timedelta

        start_date = datetime.utcnow() - timedelta(days=days)

        query = text("""
            SELECT
                emotion_metadata->>'primary_emotion' as emotion,
                COUNT(*) as count
            FROM episodes
            WHERE user_id = :user_id
            AND emotion_metadata IS NOT NULL
            AND created_at >= :start_date
            GROUP BY emotion_metadata->>'primary_emotion'
            ORDER BY count DESC
        """)

        result = db.execute(query, {
            "user_id": user_id,
            "start_date": start_date
        })

        distribution = [
            {"emotion": row.emotion, "count": row.count}
            for row in result.fetchall()
        ]

        return {
            "success": True,
            "data": {
                "distribution": distribution,
                "period_days": days,
                "total_episodes": sum(d["count"] for d in distribution)
            }
        }

    except Exception as e:
        logger.error(f"Error getting emotion distribution: {e}")
        raise HTTPException(status_code=500, detail=str(e))
