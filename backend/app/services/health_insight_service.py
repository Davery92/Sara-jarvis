"""
Health Insight Service

Provides health context for Sara's conversations and manages health insights.
Similar to insight_injection.py but specialized for health data.
"""

import logging
import json
from datetime import datetime, timedelta
from app.core.timezone import naive_local_now
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)


class HealthInsightService:
    """
    Service for surfacing health insights during conversations.

    Provides:
    - Relevant health context for current conversation
    - Health summary for tools
    - Baseline comparisons
    - Recent alerts and trends
    """

    async def get_relevant_health_context(
        self,
        user_id: str,
        db: Session,
        conversation_text: Optional[str] = None
    ) -> Optional[str]:
        """
        Get health context relevant to current conversation.

        If conversation_text mentions health-related topics (tired, sleep, stressed, etc.),
        return relevant health insights and recent data.
        """
        try:
            # Check for health-related keywords in conversation
            health_keywords = [
                'tired', 'exhausted', 'fatigue', 'energy', 'sleep', 'sleeping',
                'stressed', 'stress', 'anxious', 'heart', 'hrv', 'recovery',
                'workout', 'exercise', 'weight', 'health', 'sick', 'ill'
            ]

            if conversation_text:
                text_lower = conversation_text.lower()
                has_health_mention = any(kw in text_lower for kw in health_keywords)
                if not has_health_mention:
                    return None

            # Get recent health summary
            summary = await self.get_health_summary(user_id, db)

            if not summary or not summary.get('metrics'):
                return None

            # Build context string
            context_parts = ["## Recent Health Data"]

            metrics = summary.get('metrics', {})
            for metric_type, data in metrics.items():
                if data.get('current_value'):
                    status = data.get('status', 'normal')
                    status_emoji = {
                        'above_normal': '⬆️',
                        'below_normal': '⬇️',
                        'normal': '✓'
                    }.get(status, '')

                    context_parts.append(
                        f"- {metric_type.replace('_', ' ').title()}: {data['current_value']} {status_emoji}"
                    )
                    if data.get('baseline'):
                        context_parts.append(f"  (7-day avg: {data['baseline']})")

            # Add recent alerts if any
            alerts = summary.get('recent_alerts', [])
            if alerts:
                context_parts.append("\n### Recent Alerts")
                for alert in alerts[:3]:
                    context_parts.append(f"- [{alert['severity']}] {alert['message']}")

            # Add unsurfaced insights if any
            insights = await self._get_unsurfaced_insights(user_id, db, limit=2)
            if insights:
                context_parts.append("\n### Health Insights")
                for insight in insights:
                    context_parts.append(f"- {insight['title']}: {insight['content']}")

            if len(context_parts) == 1:  # Only header
                return None

            return "\n".join(context_parts)

        except Exception as e:
            logger.error(f"Error getting health context: {e}")
            return None

    async def get_health_summary(
        self,
        user_id: str,
        db: Session
    ) -> Dict[str, Any]:
        """
        Get current health summary including latest metrics, baselines, and status.
        """
        try:
            # Get latest value for each metric type (last 24 hours)
            latest_metrics = db.execute(text("""
                SELECT DISTINCT ON (metric_type)
                    metric_type, value, recorded_at
                FROM health_metric
                WHERE user_id = :user_id
                  AND recorded_at >= NOW() - INTERVAL '24 hours'
                ORDER BY metric_type, recorded_at DESC
            """), {"user_id": user_id}).fetchall()

            # Get 7-day baselines
            baselines = db.execute(text("""
                SELECT metric_type, average_value, std_deviation
                FROM health_baseline
                WHERE user_id = :user_id AND period_type = '7_day'
            """), {"user_id": user_id}).fetchall()

            baseline_map = {b.metric_type: b for b in baselines}

            # Build summary
            metrics = {}
            for metric in latest_metrics:
                baseline = baseline_map.get(metric.metric_type)
                status = "normal"

                if baseline and baseline.average_value and baseline.std_deviation:
                    diff = float(metric.value) - float(baseline.average_value)
                    threshold = float(baseline.std_deviation) * 1.5
                    if diff > threshold:
                        status = "above_normal"
                    elif diff < -threshold:
                        status = "below_normal"

                metrics[metric.metric_type] = {
                    "current_value": float(metric.value),
                    "recorded_at": metric.recorded_at.isoformat() if metric.recorded_at else None,
                    "baseline": float(baseline.average_value) if baseline and baseline.average_value else None,
                    "status": status,
                }

            # Get recent alerts
            alerts = db.execute(text("""
                SELECT alert_type, severity, message, created_at
                FROM health_alert
                WHERE user_id = :user_id
                  AND created_at >= NOW() - INTERVAL '24 hours'
                ORDER BY created_at DESC
                LIMIT 5
            """), {"user_id": user_id}).fetchall()

            recent_alerts = [{
                "alert_type": a.alert_type,
                "severity": a.severity,
                "message": a.message,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            } for a in alerts]

            return {
                "metrics": metrics,
                "recent_alerts": recent_alerts,
                "has_alerts": len(recent_alerts) > 0,
                "last_updated": local_now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error getting health summary: {e}")
            return {}

    async def _get_unsurfaced_insights(
        self,
        user_id: str,
        db: Session,
        limit: int = 3
    ) -> List[Dict[str, Any]]:
        """Get recent unsurfaced health insights."""
        try:
            result = db.execute(text("""
                SELECT id, insight_type, severity, title, content
                FROM health_insight
                WHERE user_id = :user_id
                  AND surfaced_count = 0
                  AND (expires_at IS NULL OR expires_at > NOW())
                ORDER BY
                    CASE severity
                        WHEN 'urgent' THEN 1
                        WHEN 'warning' THEN 2
                        WHEN 'caution' THEN 3
                        ELSE 4
                    END,
                    triggered_at DESC
                LIMIT :limit
            """), {"user_id": user_id, "limit": limit})

            return [{
                "id": row.id,
                "insight_type": row.insight_type,
                "severity": row.severity,
                "title": row.title,
                "content": row.content,
            } for row in result.fetchall()]

        except Exception as e:
            logger.error(f"Error getting unsurfaced insights: {e}")
            return []

    async def get_trend_analysis(
        self,
        user_id: str,
        db: Session,
        metric_type: str,
        days: int = 7
    ) -> Dict[str, Any]:
        """
        Analyze trend for a specific metric over the given number of days.
        """
        try:
            cutoff = naive_local_now() - timedelta(days=days)

            # Get daily averages
            result = db.execute(text("""
                SELECT
                    DATE(recorded_at) as day,
                    AVG(value) as avg_value,
                    MIN(value) as min_value,
                    MAX(value) as max_value,
                    COUNT(*) as sample_count
                FROM health_metric
                WHERE user_id = :user_id
                  AND metric_type = :metric_type
                  AND recorded_at >= :cutoff
                GROUP BY DATE(recorded_at)
                ORDER BY day
            """), {
                "user_id": user_id,
                "metric_type": metric_type,
                "cutoff": cutoff,
            })

            daily_data = []
            values = []
            for row in result.fetchall():
                daily_data.append({
                    "day": row.day.isoformat() if row.day else None,
                    "avg_value": float(row.avg_value) if row.avg_value else None,
                    "min_value": float(row.min_value) if row.min_value else None,
                    "max_value": float(row.max_value) if row.max_value else None,
                    "sample_count": row.sample_count,
                })
                if row.avg_value:
                    values.append(float(row.avg_value))

            # Calculate trend direction
            trend = "stable"
            if len(values) >= 3:
                first_half = sum(values[:len(values)//2]) / (len(values)//2)
                second_half = sum(values[len(values)//2:]) / (len(values) - len(values)//2)

                pct_change = ((second_half - first_half) / first_half * 100) if first_half else 0

                if pct_change > 10:
                    trend = "increasing"
                elif pct_change < -10:
                    trend = "decreasing"

            return {
                "metric_type": metric_type,
                "days": days,
                "daily_data": daily_data,
                "trend": trend,
                "overall_avg": sum(values) / len(values) if values else None,
            }

        except Exception as e:
            logger.error(f"Error analyzing trend: {e}")
            return {}

    async def check_for_correlations(
        self,
        user_id: str,
        db: Session,
        anomaly_time: datetime
    ) -> Dict[str, Any]:
        """
        Check for potential correlations with other data around an anomaly time.

        Looks at:
        - Recent food logs
        - Recent workouts
        - Conversation patterns (stress signals)
        """
        try:
            correlations = {}

            # Time windows
            before = anomaly_time - timedelta(hours=24)
            after = anomaly_time + timedelta(hours=6)

            # Recent food logs
            food_logs = db.execute(text("""
                SELECT meal_type, calories, protein, carbs, fats, logged_at
                FROM food_log
                WHERE user_id = :user_id
                  AND logged_at BETWEEN :before AND :after
                ORDER BY logged_at DESC
                LIMIT 10
            """), {"user_id": user_id, "before": before, "after": after}).fetchall()

            if food_logs:
                correlations["recent_foods"] = [{
                    "meal_type": f.meal_type,
                    "calories": f.calories,
                    "protein": f.protein,
                    "logged_at": f.logged_at.isoformat() if f.logged_at else None,
                } for f in food_logs]

            # Recent workouts
            workouts = db.execute(text("""
                SELECT title, status, created_at
                FROM workout
                WHERE user_id = :user_id
                  AND created_at BETWEEN :before AND :after
                ORDER BY created_at DESC
                LIMIT 5
            """), {"user_id": user_id, "before": before, "after": after}).fetchall()

            if workouts:
                correlations["recent_workouts"] = [{
                    "title": w.title,
                    "status": w.status,
                    "created_at": w.created_at.isoformat() if w.created_at else None,
                } for w in workouts]

            # Check for stress signals in recent conversations
            stress_keywords = ['stress', 'anxious', 'worried', 'overwhelmed', 'busy', 'deadline']
            episodes = db.execute(text("""
                SELECT content, created_at
                FROM episode
                WHERE user_id = :user_id
                  AND created_at BETWEEN :before AND :after
                  AND interaction_type = 'user_message'
                ORDER BY created_at DESC
                LIMIT 20
            """), {"user_id": user_id, "before": before, "after": after}).fetchall()

            stress_mentions = 0
            for ep in episodes:
                if ep.content:
                    content_lower = ep.content.lower()
                    if any(kw in content_lower for kw in stress_keywords):
                        stress_mentions += 1

            if stress_mentions > 0:
                correlations["stress_signals"] = {
                    "mentions": stress_mentions,
                    "messages_checked": len(episodes),
                }

            return correlations

        except Exception as e:
            logger.error(f"Error checking correlations: {e}")
            return {}


# Singleton instance
health_insight_service = HealthInsightService()
