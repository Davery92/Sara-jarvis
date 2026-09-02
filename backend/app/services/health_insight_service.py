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


# One logical metric, more than one metric_type in the table. The raw `hrv`
# stream went dark on 2026-05-05 (gotcha_apple_health_watch_streams_dark) and
# every HRV reading since arrives as `hrv_morning` — which is why a chat asking
# for HRV found nothing while a real 54 sat in the table. readiness_engine.py,
# body_state_service.py and progressive_overload.py all already prefer
# hrv_morning with an `hrv` fallback; the chat/tool path never got the memo, so
# it reported an absence that wasn't real and the model filled it in.
# Order matters: first entry with data wins.
METRIC_ALIASES = {
    "hrv": ["hrv_morning", "hrv"],
}


def alias_chain(metric_type: str) -> List[str]:
    """Every metric_type that can satisfy a request for `metric_type`."""
    return METRIC_ALIASES.get(metric_type, [metric_type])


def render_recorded_at(recorded_at: Optional[str]) -> str:
    """Render a metric's own `recorded_at` as local wall-clock — "today 06:12",
    "yesterday 22:40", "Aug 24 07:03". Never returns an empty string: a health
    number with no date attached is exactly the shape that gets mistaken for a
    current reading, so an unknown timestamp says so out loud."""
    if not recorded_at:
        return "at an unknown time"
    try:
        from app.core.timezone import to_local, is_today, is_yesterday
        dt = datetime.fromisoformat(str(recorded_at).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return "at an unknown time"
    local_dt = to_local(dt)
    if is_today(dt):
        return f"today {local_dt.strftime('%H:%M')}"
    if is_yesterday(dt):
        return f"yesterday {local_dt.strftime('%H:%M')}"
    return local_dt.strftime("%b %-d %H:%M")


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
                # `is not None`, not truthiness: 0 steps and a 0-hour sleep are
                # real readings, and dropping them turns "he didn't move today"
                # into "no data" (D7).
                if data.get('current_value') is not None:
                    status = data.get('status', 'normal')
                    status_emoji = {
                        'above_normal': '⬆️',
                        'below_normal': '⬇️',
                        'normal': '✓'
                    }.get(status, '')

                    context_parts.append(
                        f"- {metric_type.replace('_', ' ').title()}: {data['current_value']} "
                        f"{status_emoji} (recorded {render_recorded_at(data.get('recorded_at'))})"
                    )
                    if data.get('baseline') is not None:
                        context_parts.append(f"  (7-day avg: {data['baseline']})")

            # State the gaps. This block is ambient context the model reads as
            # evidence; a metric that simply isn't mentioned reads as "nothing
            # notable" rather than "unknown", and that's what it interpolates.
            absent = [
                m.replace('_', ' ').title() for m in ('resting_hr', 'hrv', 'sleep_hours')
                if metrics.get(m, {}).get('current_value') is None
            ]
            if absent:
                context_parts.append(
                    f"- Not recorded in the last 24h: {', '.join(absent)} — "
                    "state this as missing if asked; never estimate it."
                )

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

            # Fill a logical metric from whichever stream actually carries it,
            # so "no HRV reading" is only ever said when there genuinely is none.
            for canonical, chain in METRIC_ALIASES.items():
                if metrics.get(canonical, {}).get("current_value") is not None:
                    continue
                for alt in chain:
                    if metrics.get(alt, {}).get("current_value") is not None:
                        metrics[canonical] = {**metrics[alt], "aliased_from": alt}
                        break

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
            # `recorded_at` is timestamptz and the DB session runs in UTC, so
            # both the window and the day-bucketing have to be pinned to ET
            # explicitly: a naive-ET cutoff bound against a timestamptz column
            # is silently read as UTC, and a bare DATE() buckets a 9 PM ET
            # reading onto the following day (D5/D14).
            from app.core.timezone import local_day_bounds
            cutoff = local_day_bounds(local_now().date() - timedelta(days=days - 1))[0]

            # Get daily averages
            result = db.execute(text("""
                SELECT
                    DATE(recorded_at AT TIME ZONE 'America/New_York') as day,
                    AVG(value) as avg_value,
                    MIN(value) as min_value,
                    MAX(value) as max_value,
                    COUNT(*) as sample_count
                FROM health_metric
                WHERE user_id = :user_id
                  AND metric_type = ANY(:metric_types)
                  AND recorded_at >= :cutoff
                GROUP BY DATE(recorded_at AT TIME ZONE 'America/New_York')
                ORDER BY day
            """), {
                "user_id": user_id,
                "metric_types": alias_chain(metric_type),
                "cutoff": cutoff,
            })

            # SQL GROUP BY DATE only returns days that HAVE rows, so a gap day
            # silently vanishes and a 7-day request comes back as a tidy 3-day
            # series — which reads as continuous. Fill the calendar so an absent
            # day is an explicit {"value": None} the caller has to render, the
            # same shape patterns.py:378-382 already produces (D12).
            by_day = {}
            for row in result.fetchall():
                if not row.day:
                    continue
                by_day[row.day] = {
                    "day": row.day.isoformat(),
                    "avg_value": float(row.avg_value) if row.avg_value is not None else None,
                    "min_value": float(row.min_value) if row.min_value is not None else None,
                    "max_value": float(row.max_value) if row.max_value is not None else None,
                    "sample_count": row.sample_count,
                }

            daily_data = []
            values = []
            end_day = local_now().date()
            for offset in range(days - 1, -1, -1):
                day = end_day - timedelta(days=offset)
                entry = by_day.get(day) or {
                    "day": day.isoformat(),
                    "avg_value": None,
                    "min_value": None,
                    "max_value": None,
                    "sample_count": 0,
                }
                daily_data.append(entry)
                if entry["avg_value"] is not None:
                    values.append(entry["avg_value"])

            missing_days = [d["day"] for d in daily_data if d["avg_value"] is None]

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
                "days_with_data": len(values),
                "missing_days": missing_days,
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
