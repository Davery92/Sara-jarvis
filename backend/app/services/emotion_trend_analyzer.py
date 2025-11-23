"""
Emotion Trend Analyzer
Analyzes emotional patterns over time
"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)


class EmotionTrendPoint(BaseModel):
    """A single point in emotion trend"""
    date: str
    avg_sentiment: float
    primary_emotion: str
    intensity: float
    episode_count: int


class EmotionPattern(BaseModel):
    """Detected emotion pattern"""
    pattern_type: str  # daily, weekly, trigger-based
    description: str
    confidence: float
    evidence: List[str]


class EmotionTrendAnalyzer:
    """Analyzes emotional patterns and trends"""

    def __init__(self, db: Session):
        self.db = db

    async def get_daily_trend(
        self,
        user_id: str,
        days: int = 30
    ) -> List[EmotionTrendPoint]:
        """
        Get daily emotion trend

        Args:
            user_id: User ID
            days: Number of days to analyze

        Returns:
            List of daily trend points
        """
        try:
            start_date = datetime.utcnow() - timedelta(days=days)

            query = text("""
                SELECT
                    DATE(created_at) as date,
                    AVG((emotion_metadata->>'sentiment')::float) as avg_sentiment,
                    MODE() WITHIN GROUP (ORDER BY emotion_metadata->>'primary_emotion') as primary_emotion,
                    AVG((emotion_metadata->>'intensity')::float) as avg_intensity,
                    COUNT(*) as episode_count
                FROM episodes
                WHERE user_id = :user_id
                AND emotion_metadata IS NOT NULL
                AND created_at >= :start_date
                GROUP BY DATE(created_at)
                ORDER BY date
            """)

            result = self.db.execute(query, {
                "user_id": user_id,
                "start_date": start_date
            })

            trends = []
            for row in result.fetchall():
                trends.append(EmotionTrendPoint(
                    date=row.date.isoformat(),
                    avg_sentiment=round(row.avg_sentiment, 2) if row.avg_sentiment else 0.0,
                    primary_emotion=row.primary_emotion or "neutral",
                    intensity=round(row.avg_intensity, 2) if row.avg_intensity else 0.0,
                    episode_count=row.episode_count
                ))

            return trends

        except Exception as e:
            logger.error(f"Error getting daily trend: {e}")
            return []

    async def detect_mood_shifts(
        self,
        user_id: str,
        days: int = 7
    ) -> List[Dict[str, Any]]:
        """
        Detect significant mood shifts

        Args:
            user_id: User ID
            days: Number of days to analyze

        Returns:
            List of detected mood shifts
        """
        try:
            # Get hourly sentiment averages
            start_date = datetime.utcnow() - timedelta(days=days)

            query = text("""
                SELECT
                    DATE_TRUNC('hour', created_at) as hour,
                    AVG((emotion_metadata->>'sentiment')::float) as avg_sentiment,
                    emotion_metadata->>'primary_emotion' as emotion
                FROM episodes
                WHERE user_id = :user_id
                AND emotion_metadata IS NOT NULL
                AND created_at >= :start_date
                GROUP BY DATE_TRUNC('hour', created_at), emotion_metadata->>'primary_emotion'
                ORDER BY hour
            """)

            result = self.db.execute(query, {
                "user_id": user_id,
                "start_date": start_date
            })

            rows = result.fetchall()

            # Detect shifts (> 0.5 sentiment change within 2 hours)
            shifts = []
            for i in range(1, len(rows)):
                prev = rows[i - 1]
                curr = rows[i]

                if prev.avg_sentiment is not None and curr.avg_sentiment is not None:
                    sentiment_change = curr.avg_sentiment - prev.avg_sentiment

                    if abs(sentiment_change) >= 0.5:
                        shifts.append({
                            "timestamp": curr.hour.isoformat(),
                            "from_emotion": prev.emotion,
                            "to_emotion": curr.emotion,
                            "sentiment_change": round(sentiment_change, 2),
                            "shift_type": "positive" if sentiment_change > 0 else "negative"
                        })

            return shifts

        except Exception as e:
            logger.error(f"Error detecting mood shifts: {e}")
            return []

    async def detect_patterns(
        self,
        user_id: str,
        days: int = 30
    ) -> List[EmotionPattern]:
        """
        Detect recurring emotional patterns

        Args:
            user_id: User ID
            days: Number of days to analyze

        Returns:
            List of detected patterns
        """
        patterns = []

        try:
            # Pattern 1: Day of week patterns
            dow_pattern = await self._detect_day_of_week_pattern(user_id, days)
            if dow_pattern:
                patterns.append(dow_pattern)

            # Pattern 2: Time of day patterns
            tod_pattern = await self._detect_time_of_day_pattern(user_id, days)
            if tod_pattern:
                patterns.append(tod_pattern)

            # Pattern 3: Consecutive negative days
            negative_streak = await self._detect_negative_streaks(user_id, days)
            if negative_streak:
                patterns.append(negative_streak)

        except Exception as e:
            logger.error(f"Error detecting patterns: {e}")

        return patterns

    async def _detect_day_of_week_pattern(
        self,
        user_id: str,
        days: int
    ) -> Optional[EmotionPattern]:
        """Detect if certain days of week have consistent emotions"""
        try:
            start_date = datetime.utcnow() - timedelta(days=days)

            query = text("""
                SELECT
                    EXTRACT(DOW FROM created_at) as day_of_week,
                    AVG((emotion_metadata->>'sentiment')::float) as avg_sentiment,
                    COUNT(*) as count
                FROM episodes
                WHERE user_id = :user_id
                AND emotion_metadata IS NOT NULL
                AND created_at >= :start_date
                GROUP BY EXTRACT(DOW FROM created_at)
                HAVING COUNT(*) >= 3
            """)

            result = self.db.execute(query, {
                "user_id": user_id,
                "start_date": start_date
            })

            rows = result.fetchall()
            day_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

            # Find most positive and most negative days
            if len(rows) >= 4:  # Need at least 4 days of data
                best_day = max(rows, key=lambda r: r.avg_sentiment)
                worst_day = min(rows, key=lambda r: r.avg_sentiment)

                if abs(best_day.avg_sentiment - worst_day.avg_sentiment) >= 0.3:
                    return EmotionPattern(
                        pattern_type="weekly",
                        description=f"Your mood tends to be better on {day_names[int(best_day.day_of_week)]}s and lower on {day_names[int(worst_day.day_of_week)]}s",
                        confidence=0.7,
                        evidence=[
                            f"{day_names[int(best_day.day_of_week)]}: avg sentiment {round(best_day.avg_sentiment, 2)}",
                            f"{day_names[int(worst_day.day_of_week)]}: avg sentiment {round(worst_day.avg_sentiment, 2)}"
                        ]
                    )

        except Exception as e:
            logger.error(f"Error detecting day pattern: {e}")

        return None

    async def _detect_time_of_day_pattern(
        self,
        user_id: str,
        days: int
    ) -> Optional[EmotionPattern]:
        """Detect if certain times of day have consistent emotions"""
        try:
            start_date = datetime.utcnow() - timedelta(days=days)

            query = text("""
                SELECT
                    EXTRACT(HOUR FROM created_at) as hour,
                    AVG((emotion_metadata->>'sentiment')::float) as avg_sentiment,
                    COUNT(*) as count
                FROM episodes
                WHERE user_id = :user_id
                AND emotion_metadata IS NOT NULL
                AND created_at >= :start_date
                GROUP BY EXTRACT(HOUR FROM created_at)
                HAVING COUNT(*) >= 3
            """)

            result = self.db.execute(query, {
                "user_id": user_id,
                "start_date": start_date
            })

            rows = result.fetchall()

            if len(rows) >= 6:  # Need coverage across the day
                # Group into morning (5-11), afternoon (12-16), evening (17-21), night (22-4)
                morning = [r for r in rows if 5 <= r.hour <= 11]
                afternoon = [r for r in rows if 12 <= r.hour <= 16]
                evening = [r for r in rows if 17 <= r.hour <= 21]

                if morning and afternoon and evening:
                    morning_avg = sum(r.avg_sentiment for r in morning) / len(morning)
                    afternoon_avg = sum(r.avg_sentiment for r in afternoon) / len(afternoon)
                    evening_avg = sum(r.avg_sentiment for r in evening) / len(evening)

                    times = [
                        ("morning", morning_avg),
                        ("afternoon", afternoon_avg),
                        ("evening", evening_avg)
                    ]

                    best_time = max(times, key=lambda t: t[1])
                    worst_time = min(times, key=lambda t: t[1])

                    if abs(best_time[1] - worst_time[1]) >= 0.3:
                        return EmotionPattern(
                            pattern_type="daily",
                            description=f"Your mood tends to peak in the {best_time[0]} and dip in the {worst_time[0]}",
                            confidence=0.7,
                            evidence=[
                                f"{best_time[0]}: avg sentiment {round(best_time[1], 2)}",
                                f"{worst_time[0]}: avg sentiment {round(worst_time[1], 2)}"
                            ]
                        )

        except Exception as e:
            logger.error(f"Error detecting time pattern: {e}")

        return None

    async def _detect_negative_streaks(
        self,
        user_id: str,
        days: int
    ) -> Optional[EmotionPattern]:
        """Detect consecutive days of negative sentiment"""
        try:
            trends = await self.get_daily_trend(user_id, days)

            # Find longest negative streak (sentiment < -0.2)
            current_streak = 0
            max_streak = 0
            streak_start = None

            for trend in trends:
                if trend.avg_sentiment < -0.2:
                    if current_streak == 0:
                        streak_start = trend.date
                    current_streak += 1
                    max_streak = max(max_streak, current_streak)
                else:
                    current_streak = 0

            if max_streak >= 3:
                return EmotionPattern(
                    pattern_type="trigger-based",
                    description=f"Detected a {max_streak}-day period of lower mood recently",
                    confidence=0.8,
                    evidence=[
                        f"Consecutive negative days: {max_streak}",
                        f"Started around: {streak_start}" if streak_start else ""
                    ]
                )

        except Exception as e:
            logger.error(f"Error detecting negative streaks: {e}")

        return None

    async def get_emotion_summary(
        self,
        user_id: str,
        days: int = 7
    ) -> Dict[str, Any]:
        """
        Get comprehensive emotion summary

        Args:
            user_id: User ID
            days: Number of days to analyze

        Returns:
            Emotion summary with trends, patterns, and insights
        """
        try:
            # Get daily trends
            trends = await self.get_daily_trend(user_id, days)

            # Get mood shifts
            shifts = await self.detect_mood_shifts(user_id, days)

            # Detect patterns
            patterns = await self.detect_patterns(user_id, days)

            # Calculate overall metrics
            if trends:
                avg_sentiment = sum(t.avg_sentiment for t in trends) / len(trends)
                emotion_counts = {}
                for t in trends:
                    emotion_counts[t.primary_emotion] = emotion_counts.get(t.primary_emotion, 0) + 1

                dominant_emotion = max(emotion_counts.items(), key=lambda x: x[1])[0]

                # Determine trend direction
                if len(trends) >= 3:
                    recent_avg = sum(t.avg_sentiment for t in trends[-3:]) / 3
                    older_avg = sum(t.avg_sentiment for t in trends[:3]) / 3

                    if recent_avg > older_avg + 0.1:
                        trend_direction = "improving"
                    elif recent_avg < older_avg - 0.1:
                        trend_direction = "declining"
                    else:
                        trend_direction = "stable"
                else:
                    trend_direction = "insufficient_data"
            else:
                avg_sentiment = 0.0
                dominant_emotion = "neutral"
                trend_direction = "no_data"
                emotion_counts = {}

            return {
                "period_days": days,
                "avg_sentiment": round(avg_sentiment, 2),
                "dominant_emotion": dominant_emotion,
                "trend_direction": trend_direction,
                "emotion_distribution": emotion_counts,
                "daily_trends": [t.dict() for t in trends],
                "mood_shifts": shifts,
                "patterns": [p.dict() for p in patterns],
                "total_episodes": sum(t.episode_count for t in trends) if trends else 0
            }

        except Exception as e:
            logger.error(f"Error generating emotion summary: {e}")
            return {
                "error": str(e),
                "period_days": days
            }


def get_emotion_trend_analyzer(db: Session) -> EmotionTrendAnalyzer:
    """Get emotion trend analyzer instance"""
    return EmotionTrendAnalyzer(db)
