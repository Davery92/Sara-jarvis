"""
Health Watchdog Worker

Background service that monitors health metrics and generates proactive insights.

Runs every 5 minutes to:
1. Update rolling baselines (7-day average, stddev)
2. Detect anomalies (HR spike, HRV drop, sleep deficit, multi-day trends)
3. Gather correlation data (food, workouts, conversations)
4. Generate AI insights using gpt-oss:20b
5. Send iOS push notifications for warning/urgent alerts

Usage:
    python -m app.workers.health_watchdog
"""

import asyncio
import logging
import json
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Anomaly detection thresholds
THRESHOLDS = {
    'resting_hr_spike_pct': 0.15,      # +15% above baseline
    'hrv_drop_pct': 0.20,              # -20% below baseline
    'sleep_deficit_hours': 6.0,        # Less than 6 hours
    'multi_day_trend_days': 3,         # 3+ consecutive declining days
    'min_samples_for_baseline': 5,     # Minimum samples to calculate baseline
}

# Alert severity levels
SEVERITY_INFO = 'info'
SEVERITY_CAUTION = 'caution'
SEVERITY_WARNING = 'warning'
SEVERITY_URGENT = 'urgent'


class HealthWatchdog:
    """
    Health monitoring watchdog that runs periodically to detect anomalies
    and generate proactive health insights.
    """

    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.llm_url = settings.llm_primary_url.replace('/v1', '')
        self.analysis_model = "gpt-oss:20b"  # Smaller model for background analysis

    async def run_check(self):
        """Run a single health check cycle."""
        logger.info("Starting health watchdog check...")

        db = self.SessionLocal()
        try:
            # Get all users with recent health data
            users = self._get_active_users(db)
            logger.info(f"Checking health for {len(users)} active users")

            for user_id in users:
                try:
                    await self._check_user_health(db, user_id)
                except Exception as e:
                    logger.error(f"Error checking health for user {user_id}: {e}")

            db.commit()
            logger.info("Health watchdog check completed")

        except Exception as e:
            logger.error(f"Health watchdog error: {e}")
            db.rollback()
        finally:
            db.close()

    def _get_active_users(self, db: Session) -> List[str]:
        """Get users with health data in the last 24 hours."""
        result = db.execute(text("""
            SELECT DISTINCT user_id
            FROM health_metric
            WHERE recorded_at >= NOW() - INTERVAL '24 hours'
        """))
        return [row.user_id for row in result.fetchall()]

    async def _check_user_health(self, db: Session, user_id: str):
        """Check health metrics for a single user."""
        logger.info(f"Checking health for user {user_id}")

        # 1. Update baselines
        await self._update_baselines(db, user_id)

        # 2. Check for anomalies
        anomalies = await self._detect_anomalies(db, user_id)

        if not anomalies:
            logger.debug(f"No anomalies detected for user {user_id}")
            return

        logger.info(f"Found {len(anomalies)} anomalies for user {user_id}")

        # 3. Gather correlation data
        correlations = await self._gather_correlations(db, user_id)

        # 4. Generate AI insight
        insight = await self._generate_insight(db, user_id, anomalies, correlations)

        if insight:
            # 5. Create insight record
            insight_id = await self._save_insight(db, user_id, insight, anomalies)

            # 6. Create alert record
            await self._save_alert(db, user_id, anomalies, insight_id)

            # 7. Send push notification if warning/urgent
            if insight['severity'] in [SEVERITY_WARNING, SEVERITY_URGENT]:
                await self._send_push_notification(db, user_id, insight, insight_id)

    async def _update_baselines(self, db: Session, user_id: str):
        """Update 7-day and 30-day rolling baselines for each metric type."""
        metric_types = ['resting_hr', 'hrv', 'heart_rate', 'sleep_hours', 'steps', 'active_energy', 'weight']
        today = datetime.now().date()

        for metric_type in metric_types:
            for period_days, period_type in [(7, '7_day'), (30, '30_day')]:
                cutoff = datetime.now() - timedelta(days=period_days)

                # Calculate statistics
                stats = db.execute(text("""
                    SELECT
                        AVG(value) as avg_value,
                        STDDEV(value) as std_dev,
                        MIN(value) as min_value,
                        MAX(value) as max_value,
                        COUNT(*) as sample_count
                    FROM health_metric
                    WHERE user_id = :user_id
                      AND metric_type = :metric_type
                      AND recorded_at >= :cutoff
                """), {
                    "user_id": user_id,
                    "metric_type": metric_type,
                    "cutoff": cutoff,
                }).fetchone()

                if not stats or not stats.sample_count or stats.sample_count < THRESHOLDS['min_samples_for_baseline']:
                    continue

                # Upsert baseline (include period_end as required by schema)
                db.execute(text("""
                    INSERT INTO health_baseline
                        (id, user_id, metric_type, period_type, average_value, std_deviation,
                         min_value, max_value, sample_count, calculated_at, period_end)
                    VALUES
                        (:id, :user_id, :metric_type, :period_type, :avg_value, :std_dev,
                         :min_value, :max_value, :sample_count, NOW(), :period_end)
                    ON CONFLICT (user_id, metric_type, period_type)
                    DO UPDATE SET
                        average_value = :avg_value,
                        std_deviation = :std_dev,
                        min_value = :min_value,
                        max_value = :max_value,
                        sample_count = :sample_count,
                        calculated_at = NOW(),
                        period_end = :period_end
                """), {
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "metric_type": metric_type,
                    "period_type": period_type,
                    "avg_value": float(stats.avg_value) if stats.avg_value else None,
                    "std_dev": float(stats.std_dev) if stats.std_dev else None,
                    "min_value": float(stats.min_value) if stats.min_value else None,
                    "max_value": float(stats.max_value) if stats.max_value else None,
                    "sample_count": stats.sample_count,
                    "period_end": today,
                })

        logger.debug(f"Updated baselines for user {user_id}")

    async def _detect_anomalies(self, db: Session, user_id: str) -> List[Dict[str, Any]]:
        """Detect health anomalies based on thresholds."""
        anomalies = []

        # Get baselines
        baselines = {}
        baseline_rows = db.execute(text("""
            SELECT metric_type, average_value, std_deviation
            FROM health_baseline
            WHERE user_id = :user_id AND period_type = '7_day'
        """), {"user_id": user_id}).fetchall()

        for row in baseline_rows:
            baselines[row.metric_type] = {
                'avg': float(row.average_value) if row.average_value else None,
                'std': float(row.std_deviation) if row.std_deviation else None,
            }

        # Get latest values (last 4 hours)
        latest_metrics = db.execute(text("""
            SELECT DISTINCT ON (metric_type)
                metric_type, value, recorded_at
            FROM health_metric
            WHERE user_id = :user_id
              AND recorded_at >= NOW() - INTERVAL '4 hours'
            ORDER BY metric_type, recorded_at DESC
        """), {"user_id": user_id}).fetchall()

        for metric in latest_metrics:
            metric_type = metric.metric_type
            value = float(metric.value)
            baseline = baselines.get(metric_type)

            if not baseline or not baseline['avg']:
                continue

            # Check resting HR spike
            if metric_type == 'resting_hr':
                threshold = baseline['avg'] * (1 + THRESHOLDS['resting_hr_spike_pct'])
                if value > threshold:
                    pct_change = ((value - baseline['avg']) / baseline['avg']) * 100
                    anomalies.append({
                        'type': 'hr_spike',
                        'metric': 'resting_hr',
                        'current_value': value,
                        'baseline': baseline['avg'],
                        'threshold': threshold,
                        'pct_change': round(pct_change, 1),
                        'severity': SEVERITY_WARNING,
                        'message': f"Resting HR elevated: {int(value)} bpm (+{round(pct_change)}% above baseline)",
                    })

            # Check HRV drop
            elif metric_type == 'hrv':
                threshold = baseline['avg'] * (1 - THRESHOLDS['hrv_drop_pct'])
                if value < threshold:
                    pct_change = ((baseline['avg'] - value) / baseline['avg']) * 100
                    anomalies.append({
                        'type': 'hrv_drop',
                        'metric': 'hrv',
                        'current_value': value,
                        'baseline': baseline['avg'],
                        'threshold': threshold,
                        'pct_change': round(pct_change, 1),
                        'severity': SEVERITY_WARNING,
                        'message': f"HRV dropped: {int(value)} ms (-{round(pct_change)}% below baseline)",
                    })

            # Check sleep deficit
            elif metric_type == 'sleep_hours':
                if value < THRESHOLDS['sleep_deficit_hours']:
                    anomalies.append({
                        'type': 'sleep_deficit',
                        'metric': 'sleep_hours',
                        'current_value': value,
                        'baseline': baseline['avg'],
                        'threshold': THRESHOLDS['sleep_deficit_hours'],
                        'severity': SEVERITY_CAUTION,
                        'message': f"Sleep deficit: {round(value, 1)} hours (below {THRESHOLDS['sleep_deficit_hours']}h minimum)",
                    })

        # Check for multi-day decline trend
        multi_day_anomaly = await self._check_multi_day_trend(db, user_id, baselines)
        if multi_day_anomaly:
            anomalies.append(multi_day_anomaly)

        # Check for critical combo (HR spike + HRV drop + poor sleep)
        has_hr_spike = any(a['type'] == 'hr_spike' for a in anomalies)
        has_hrv_drop = any(a['type'] == 'hrv_drop' for a in anomalies)
        has_sleep_deficit = any(a['type'] == 'sleep_deficit' for a in anomalies)

        if has_hr_spike and has_hrv_drop and has_sleep_deficit:
            # Upgrade severity to urgent
            for anomaly in anomalies:
                if anomaly['type'] in ['hr_spike', 'hrv_drop']:
                    anomaly['severity'] = SEVERITY_URGENT
            anomalies.append({
                'type': 'critical_combo',
                'severity': SEVERITY_URGENT,
                'message': "Multiple health indicators affected: elevated HR, low HRV, and sleep deficit",
            })

        return anomalies

    async def _check_multi_day_trend(
        self, db: Session, user_id: str, baselines: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Check for multi-day declining trends across key metrics."""
        trend_days = THRESHOLDS['multi_day_trend_days']
        key_metrics = ['resting_hr', 'hrv', 'sleep_hours']

        declining_metrics = []

        for metric_type in key_metrics:
            # Get daily averages for the last N days
            # Note: INTERVAL value must be embedded directly as PostgreSQL doesn't support parameterized intervals
            interval_days = trend_days + 1
            daily_avgs = db.execute(text(f"""
                SELECT DATE(recorded_at) as day, AVG(value) as avg_value
                FROM health_metric
                WHERE user_id = :user_id
                  AND metric_type = :metric_type
                  AND recorded_at >= NOW() - INTERVAL '{interval_days} days'
                GROUP BY DATE(recorded_at)
                ORDER BY day DESC
                LIMIT :limit
            """), {
                "user_id": user_id,
                "metric_type": metric_type,
                "limit": interval_days,
            }).fetchall()

            if len(daily_avgs) < trend_days:
                continue

            # Check if trending in concerning direction
            values = [float(row.avg_value) for row in daily_avgs]

            # For HR: concerning if increasing
            # For HRV/sleep: concerning if decreasing
            if metric_type == 'resting_hr':
                # Check if each day is higher than the next (older) day
                declining = all(values[i] > values[i + 1] for i in range(len(values) - 1))
            else:
                # Check if each day is lower than the next (older) day
                declining = all(values[i] < values[i + 1] for i in range(len(values) - 1))

            if declining:
                declining_metrics.append(metric_type)

        if len(declining_metrics) >= 2:
            return {
                'type': 'multi_day_decline',
                'metrics': declining_metrics,
                'days': trend_days,
                'severity': SEVERITY_WARNING,
                'message': f"{trend_days}-day declining trend in: {', '.join(declining_metrics)}",
            }

        return None

    async def _gather_correlations(self, db: Session, user_id: str) -> Dict[str, Any]:
        """Gather correlation data from other domains."""
        correlations = {}
        now = datetime.now()
        yesterday = now - timedelta(hours=24)

        # Recent food logs
        food_logs = db.execute(text("""
            SELECT meal_type, calories, protein, carbs, fats, logged_at
            FROM food_log
            WHERE user_id = :user_id
              AND logged_at >= :yesterday
            ORDER BY logged_at DESC
            LIMIT 10
        """), {"user_id": user_id, "yesterday": yesterday}).fetchall()

        if food_logs:
            correlations['recent_foods'] = [{
                'meal_type': f.meal_type,
                'calories': f.calories,
                'protein': f.protein,
                'logged_at': f.logged_at.isoformat() if f.logged_at else None,
            } for f in food_logs]

            # Calculate nutrition summary
            total_calories = sum(f.calories or 0 for f in food_logs)
            total_protein = sum(f.protein or 0 for f in food_logs)
            correlations['nutrition_summary'] = {
                'total_calories': total_calories,
                'total_protein': total_protein,
            }

        # Recent workouts
        workouts = db.execute(text("""
            SELECT title, status, created_at
            FROM workout
            WHERE user_id = :user_id
              AND created_at >= :yesterday
            ORDER BY created_at DESC
            LIMIT 5
        """), {"user_id": user_id, "yesterday": yesterday}).fetchall()

        if workouts:
            correlations['recent_workouts'] = [{
                'title': w.title,
                'status': w.status,
                'created_at': w.created_at.isoformat() if w.created_at else None,
            } for w in workouts]

        # Check for stress signals in recent conversations
        stress_keywords = ['stress', 'anxious', 'worried', 'overwhelmed', 'busy', 'deadline', 'tired', 'exhausted']
        episodes = db.execute(text("""
            SELECT content, created_at
            FROM episode
            WHERE user_id = :user_id
              AND created_at >= :yesterday
              AND role = 'user'
            ORDER BY created_at DESC
            LIMIT 30
        """), {"user_id": user_id, "yesterday": yesterday}).fetchall()

        stress_mentions = 0
        stress_samples = []
        for ep in episodes:
            if ep.content:
                content_lower = ep.content.lower()
                for kw in stress_keywords:
                    if kw in content_lower:
                        stress_mentions += 1
                        if len(stress_samples) < 3:
                            stress_samples.append(ep.content[:100])
                        break

        if stress_mentions > 0:
            correlations['stress_signals'] = {
                'mentions': stress_mentions,
                'messages_checked': len(episodes),
                'samples': stress_samples,
            }

        return correlations

    async def _generate_insight(
        self,
        db: Session,
        user_id: str,
        anomalies: List[Dict[str, Any]],
        correlations: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Generate AI insight using the analysis model."""

        # Check if we've already generated an insight for similar anomalies recently
        recent_insight = db.execute(text("""
            SELECT id FROM health_insight
            WHERE user_id = :user_id
              AND triggered_at >= NOW() - INTERVAL '4 hours'
              AND insight_type = 'anomaly'
            LIMIT 1
        """), {"user_id": user_id}).fetchone()

        if recent_insight:
            logger.debug(f"Skipping insight generation - recent insight exists for user {user_id}")
            return None

        # Build prompt for LLM
        anomaly_summary = "\n".join([f"- {a['message']}" for a in anomalies])

        correlation_summary = ""
        if correlations.get('stress_signals'):
            correlation_summary += f"\n- Stress signals detected in {correlations['stress_signals']['mentions']} recent messages"
        if correlations.get('recent_workouts'):
            correlation_summary += f"\n- {len(correlations['recent_workouts'])} workouts in last 24h"
        if correlations.get('nutrition_summary'):
            ns = correlations['nutrition_summary']
            correlation_summary += f"\n- Yesterday's intake: {ns.get('total_calories', 0)} calories, {ns.get('total_protein', 0)}g protein"

        prompt = f"""You are Sara, a health-focused AI assistant analyzing health metrics for your user.

DETECTED ANOMALIES:
{anomaly_summary}

CONTEXT:
{correlation_summary if correlation_summary else "No additional context available."}

Based on these findings, write a brief, caring health insight for your user.

Guidelines:
- Be concise (2-3 sentences max)
- Be supportive, not alarming
- Suggest one actionable recommendation
- Reference correlations if relevant
- Use first person (addressing the user directly)

Format your response as JSON:
{{
    "title": "Brief title (5-8 words)",
    "content": "Your insight message",
    "recommendation": "One specific suggestion"
}}"""

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.llm_url}/v1/chat/completions",
                    json={
                        "model": self.analysis_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.7,
                        "max_tokens": 300,
                    }
                )
                response.raise_for_status()
                result = response.json()

                content = result['choices'][0]['message']['content']

                # Parse JSON from response
                try:
                    # Strip markdown code blocks if present
                    clean_content = content.strip()
                    if clean_content.startswith('```'):
                        # Remove opening code block (```json or ```)
                        lines = clean_content.split('\n')
                        lines = lines[1:]  # Remove first line with ```
                        clean_content = '\n'.join(lines)
                    if clean_content.endswith('```'):
                        clean_content = clean_content[:-3]
                    clean_content = clean_content.strip()

                    # Try to extract JSON from the response
                    if '{' in clean_content and '}' in clean_content:
                        json_str = clean_content[clean_content.find('{'):clean_content.rfind('}')+1]
                        insight_data = json.loads(json_str)
                    else:
                        # Fallback if LLM didn't return JSON
                        insight_data = {
                            "title": "Health Alert",
                            "content": clean_content,
                            "recommendation": "Consider taking a rest day."
                        }
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse LLM JSON response: {e}")
                    insight_data = {
                        "title": "Health Alert",
                        "content": content,
                        "recommendation": "Consider taking a rest day."
                    }

                # Determine severity from anomalies
                max_severity = SEVERITY_INFO
                severity_order = [SEVERITY_INFO, SEVERITY_CAUTION, SEVERITY_WARNING, SEVERITY_URGENT]
                for anomaly in anomalies:
                    if severity_order.index(anomaly.get('severity', SEVERITY_INFO)) > severity_order.index(max_severity):
                        max_severity = anomaly['severity']

                return {
                    'title': insight_data.get('title', 'Health Update'),
                    'content': f"{insight_data.get('content', '')}\n\n💡 {insight_data.get('recommendation', '')}",
                    'severity': max_severity,
                    'anomalies': anomalies,
                    'correlations': correlations,
                }

        except Exception as e:
            logger.error(f"Error generating insight: {e}")
            # Return basic insight without AI
            return {
                'title': "Health Alert",
                'content': anomaly_summary,
                'severity': SEVERITY_WARNING,
                'anomalies': anomalies,
                'correlations': correlations,
            }

    async def _save_insight(
        self,
        db: Session,
        user_id: str,
        insight: Dict[str, Any],
        anomalies: List[Dict[str, Any]]
    ) -> str:
        """Save insight to database."""
        insight_id = str(uuid.uuid4())

        db.execute(text("""
            INSERT INTO health_insight
                (id, user_id, insight_type, severity, title, content, evidence,
                 related_metrics, correlation_data, triggered_at, expires_at, surfaced_count, notification_sent)
            VALUES
                (:id, :user_id, 'anomaly', :severity, :title, :content, :evidence,
                 :related_metrics, :correlation_data, NOW(), NOW() + INTERVAL '24 hours', 0, false)
        """), {
            "id": insight_id,
            "user_id": user_id,
            "severity": insight['severity'],
            "title": insight['title'],
            "content": insight['content'],
            "evidence": json.dumps(anomalies),
            "related_metrics": json.dumps([a.get('metric') for a in anomalies if a.get('metric')]),
            "correlation_data": json.dumps(insight.get('correlations', {})),
        })

        logger.info(f"Created health insight {insight_id} for user {user_id}: {insight['title']}")
        return insight_id

    async def _save_alert(
        self,
        db: Session,
        user_id: str,
        anomalies: List[Dict[str, Any]],
        insight_id: str
    ):
        """Save alert record for deduplication."""
        # Determine primary alert type
        alert_types = [a['type'] for a in anomalies]
        primary_type = 'critical_combo' if 'critical_combo' in alert_types else alert_types[0]

        max_severity = max(a.get('severity', SEVERITY_INFO) for a in anomalies)
        messages = [a['message'] for a in anomalies if a.get('message')]

        db.execute(text("""
            INSERT INTO health_alert
                (id, user_id, alert_type, severity, message, metric_data, insight_id)
            VALUES
                (:id, :user_id, :alert_type, :severity, :message, :metric_data, :insight_id)
        """), {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "alert_type": primary_type,
            "severity": max_severity,
            "message": "; ".join(messages),
            "metric_data": json.dumps(anomalies),
            "insight_id": insight_id,
        })

    async def _send_push_notification(self, db: Session, user_id: str, insight: Dict[str, Any], insight_id: str):
        """Send iOS push notification via Expo Push Service."""
        # Get user's push tokens from push_token table
        tokens_result = db.execute(text("""
            SELECT token FROM push_token
            WHERE user_id = :user_id AND is_active = true
        """), {"user_id": user_id}).fetchall()

        if not tokens_result:
            logger.debug(f"No active push tokens for user {user_id}")
            return

        # Build notification - clean content for mobile display
        title = f"⚠️ {insight['title']}" if insight['severity'] == SEVERITY_URGENT else f"📊 {insight['title']}"
        # Clean the body: remove emoji, strip excessive whitespace
        body_text = insight['content'][:200]
        body_text = body_text.replace('\n\n💡 ', '\n').replace('💡 ', '')  # Clean up recommendation prefix
        body = body_text.strip()

        # Send to all active tokens
        messages = []
        for row in tokens_result:
            push_token = row.token
            if not push_token.startswith('ExponentPushToken'):
                logger.debug(f"Skipping invalid push token format for user {user_id}")
                continue

            messages.append({
                "to": push_token,
                "title": title,
                "body": body,
                "sound": "default",
                "priority": "high" if insight['severity'] == SEVERITY_URGENT else "normal",
                "categoryId": "HEALTH_ALERT",  # iOS notification category for action buttons
                "data": {
                    "type": "health_alert",
                    "severity": insight['severity'],
                    "insight_id": insight_id,
                    "title": insight['title'],
                    "body": insight['content'],
                },
            })

        if not messages:
            logger.debug(f"No valid push tokens for user {user_id}")
            return

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "https://exp.host/--/api/v2/push/send",
                    json=messages,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    }
                )
                response.raise_for_status()

                # Update alert with notification sent timestamp
                db.execute(text("""
                    UPDATE health_alert
                    SET notification_sent_at = NOW()
                    WHERE insight_id = (
                        SELECT id FROM health_insight
                        WHERE user_id = :user_id
                        ORDER BY triggered_at DESC
                        LIMIT 1
                    )
                """), {"user_id": user_id})

                logger.info(f"Push notification sent to {len(messages)} devices for user {user_id}: {title}")

        except Exception as e:
            logger.error(f"Failed to send push notification: {e}")


async def run_watchdog_loop():
    """Main loop that runs the watchdog every 5 minutes."""
    db_url = str(settings.database_url)
    watchdog = HealthWatchdog(db_url)

    logger.info("Health watchdog started")
    logger.info(f"Using LLM: {watchdog.llm_url}")
    logger.info(f"Analysis model: {watchdog.analysis_model}")

    while True:
        try:
            await watchdog.run_check()
        except Exception as e:
            logger.error(f"Watchdog loop error: {e}")

        # Wait 5 minutes before next check
        await asyncio.sleep(5 * 60)


if __name__ == "__main__":
    asyncio.run(run_watchdog_loop())
