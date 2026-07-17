"""
Temporal Bin Service

Aggregates data from all domains (git, health, food, home, mood) into unified
temporal bins for cross-domain pattern analysis.

Usage:
    from app.services.temporal_bin_service import temporal_bin_service

    # Aggregate today's data
    await temporal_bin_service.aggregate_daily_bin(user_id, date.today())

    # Get time series for analysis
    series = await temporal_bin_service.get_time_series(
        user_id,
        metrics=['health.sleep_hours', 'git.commit_count'],
        days=30
    )
"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, List, Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _to_float(value):
    """Convert Decimal or other numeric types to float for JSON serialization."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


class TemporalBinService:
    """
    Aggregates multi-domain data into unified temporal bins.

    Supported domains:
    - git: commit_count, additions, deletions, files_changed, active_hours, late_commits
    - health: sleep_hours, resting_hr, hrv, steps, active_energy
    - food: total_calories, protein_g, carbs_g, fats_g, meal_count, first_meal_hour
    - home: light_events, motion_events, first_motion_hour, climate_changes
    - mood: message_count, avg_sentiment, primary_emotion, energy_level
    """

    async def aggregate_daily_bin(self, db: Session, user_id: str, bin_date: date) -> Dict[str, Any]:
        """
        Aggregate all domain data for a single day into a temporal bin.
        Creates or updates the bin record.

        Returns the aggregated metrics dict.
        """
        logger.info(f"📊 Aggregating daily bin for user {user_id} on {bin_date}")

        # Gather metrics from each domain
        git_metrics = await self._aggregate_git_metrics(db, user_id, bin_date)
        health_metrics = await self._aggregate_health_metrics(db, user_id, bin_date)
        food_metrics = await self._aggregate_food_metrics(db, user_id, bin_date)
        home_metrics = await self._aggregate_home_metrics(db, user_id, bin_date)
        mood_metrics = await self._aggregate_mood_metrics(db, user_id, bin_date)
        calendar_metrics = await self._aggregate_calendar_metrics(db, user_id, bin_date)

        # Calculate day context
        day_of_week = bin_date.weekday()  # 0=Monday in Python
        # Convert to Sunday=0 format for consistency
        day_of_week_sunday = (day_of_week + 1) % 7
        is_weekend = day_of_week >= 5  # Saturday or Sunday

        # Upsert the bin - use -1 for bin_hour on daily bins since NULL doesn't trigger ON CONFLICT
        import json

        # First try to update existing
        update_result = db.execute(text("""
            UPDATE temporal_bin SET
                git_metrics = :git_metrics,
                health_metrics = :health_metrics,
                food_metrics = :food_metrics,
                home_metrics = :home_metrics,
                mood_metrics = :mood_metrics,
                calendar_metrics = :calendar_metrics,
                day_of_week = :day_of_week,
                is_weekend = :is_weekend,
                updated_at = NOW()
            WHERE user_id = :user_id
              AND bin_date = :bin_date
              AND bin_type = 'daily'
        """), {
            "user_id": user_id,
            "bin_date": bin_date,
            "git_metrics": json.dumps(git_metrics) if git_metrics else None,
            "health_metrics": json.dumps(health_metrics) if health_metrics else None,
            "food_metrics": json.dumps(food_metrics) if food_metrics else None,
            "home_metrics": json.dumps(home_metrics) if home_metrics else None,
            "mood_metrics": json.dumps(mood_metrics) if mood_metrics else None,
            "calendar_metrics": json.dumps(calendar_metrics) if calendar_metrics else None,
            "day_of_week": day_of_week_sunday,
            "is_weekend": is_weekend,
        })

        # If no rows updated, insert new
        if update_result.rowcount == 0:
            db.execute(text("""
                INSERT INTO temporal_bin
                    (id, user_id, bin_date, bin_hour, bin_type,
                     git_metrics, health_metrics, food_metrics, home_metrics, mood_metrics,
                     calendar_metrics,
                     day_of_week, is_weekend, updated_at)
                VALUES
                    (:id, :user_id, :bin_date, -1, 'daily',
                     :git_metrics, :health_metrics, :food_metrics, :home_metrics, :mood_metrics,
                     :calendar_metrics,
                     :day_of_week, :is_weekend, NOW())
            """), {
                "id": str(uuid4()),
                "user_id": user_id,
                "bin_date": bin_date,
                "git_metrics": json.dumps(git_metrics) if git_metrics else None,
                "health_metrics": json.dumps(health_metrics) if health_metrics else None,
                "food_metrics": json.dumps(food_metrics) if food_metrics else None,
                "home_metrics": json.dumps(home_metrics) if home_metrics else None,
                "mood_metrics": json.dumps(mood_metrics) if mood_metrics else None,
                "calendar_metrics": json.dumps(calendar_metrics) if calendar_metrics else None,
                "day_of_week": day_of_week_sunday,
                "is_weekend": is_weekend,
            })

        db.commit()

        result = {
            "bin_date": bin_date.isoformat(),
            "git": git_metrics,
            "health": health_metrics,
            "food": food_metrics,
            "home": home_metrics,
            "mood": mood_metrics,
            "calendar": calendar_metrics,
            "day_of_week": day_of_week_sunday,
            "is_weekend": is_weekend,
        }

        logger.info(f"✅ Aggregated daily bin: git={bool(git_metrics)}, health={bool(health_metrics)}, "
                   f"food={bool(food_metrics)}, home={bool(home_metrics)}, mood={bool(mood_metrics)}, "
                   f"calendar={bool(calendar_metrics)}")

        return result

    async def _aggregate_git_metrics(self, db: Session, user_id: str, bin_date: date) -> Optional[Dict]:
        """Aggregate git commit metrics for the day."""
        try:
            # files_changed is JSONB (array of filenames), so use jsonb_array_length
            result = db.execute(text("""
                SELECT
                    COUNT(*) as commit_count,
                    COALESCE(SUM(additions), 0) as additions,
                    COALESCE(SUM(deletions), 0) as deletions,
                    COALESCE(SUM(COALESCE(jsonb_array_length(files_changed), 0)), 0) as files_changed_count,
                    array_agg(DISTINCT EXTRACT(HOUR FROM committed_at)::int)
                        FILTER (WHERE committed_at IS NOT NULL) as active_hours,
                    COUNT(*) FILTER (WHERE EXTRACT(HOUR FROM committed_at) >= 22
                                     OR EXTRACT(HOUR FROM committed_at) < 6) as late_commits
                FROM git_commit gc
                JOIN dev_project dp ON gc.project_id = dp.id
                WHERE dp.user_id = :user_id
                  AND gc.committed_at::date = :bin_date
            """), {"user_id": user_id, "bin_date": bin_date}).fetchone()

            if result and result.commit_count > 0:
                return {
                    "commit_count": int(result.commit_count),
                    "additions": int(_to_float(result.additions) or 0),
                    "deletions": int(_to_float(result.deletions) or 0),
                    "files_changed": int(_to_float(result.files_changed_count) or 0),
                    "active_hours": sorted([h for h in (result.active_hours or []) if h is not None]),
                    "late_commits": int(result.late_commits or 0),
                }
        except Exception as e:
            logger.warning(f"Git metrics aggregation failed: {e}")
            db.rollback()  # Reset transaction so subsequent queries work
        return None

    async def _aggregate_health_metrics(self, db: Session, user_id: str, bin_date: date) -> Optional[Dict]:
        """Aggregate health metrics for the day."""
        try:
            result = db.execute(text("""
                SELECT
                    metric_type,
                    AVG(value) as avg_value,
                    MAX(value) as max_value,
                    MIN(value) as min_value
                FROM health_metric
                WHERE user_id = :user_id
                  AND recorded_at::date = :bin_date
                GROUP BY metric_type
            """), {"user_id": user_id, "bin_date": bin_date}).fetchall()

            if result:
                metrics = {}
                for row in result:
                    metric_type = row.metric_type
                    # Use appropriate aggregation per metric type
                    if metric_type in ['sleep_hours', 'weight']:
                        metrics[metric_type] = round(_to_float(row.avg_value), 2)
                    elif metric_type in ['steps', 'active_energy']:
                        # For cumulative metrics, we want the max (total for day)
                        metrics[metric_type] = round(_to_float(row.max_value), 0)
                    else:
                        # For HR, HRV, etc., use average
                        metrics[metric_type] = round(_to_float(row.avg_value), 2)

                if metrics:
                    return metrics
        except Exception as e:
            logger.warning(f"Health metrics aggregation failed: {e}")
            db.rollback()
        return None

    async def _aggregate_food_metrics(self, db: Session, user_id: str, bin_date: date) -> Optional[Dict]:
        """Aggregate food log metrics for the day."""
        try:
            result = db.execute(text("""
                SELECT
                    COUNT(*) as meal_count,
                    COALESCE(SUM(calories), 0) as total_calories,
                    COALESCE(SUM(protein), 0) as protein_g,
                    COALESCE(SUM(carbs), 0) as carbs_g,
                    COALESCE(SUM(fats), 0) as fats_g,
                    MIN(EXTRACT(HOUR FROM logged_at)::int) as first_meal_hour,
                    MAX(EXTRACT(HOUR FROM logged_at)::int) as last_meal_hour
                FROM food_log
                WHERE user_id = :user_id
                  AND logged_at::date = :bin_date
            """), {"user_id": user_id, "bin_date": bin_date}).fetchone()

            if result and result.meal_count > 0:
                return {
                    "meal_count": result.meal_count,
                    "total_calories": round(_to_float(result.total_calories), 0),
                    "protein_g": round(_to_float(result.protein_g), 1),
                    "carbs_g": round(_to_float(result.carbs_g), 1),
                    "fats_g": round(_to_float(result.fats_g), 1),
                    "first_meal_hour": result.first_meal_hour,
                    "last_meal_hour": result.last_meal_hour,
                }
        except Exception as e:
            logger.warning(f"Food metrics aggregation failed: {e}")
            db.rollback()
        return None

    async def _aggregate_home_metrics(self, db: Session, user_id: str, bin_date: date) -> Optional[Dict]:
        """Aggregate Home Assistant activity metrics for the day."""
        try:
            # Note: home_activity_log doesn't have user_id, it's system-wide
            # For now, aggregate all home activity
            result = db.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE domain = 'light') as light_events,
                    COUNT(*) FILTER (WHERE domain = 'switch') as switch_events,
                    COUNT(*) FILTER (WHERE domain = 'binary_sensor'
                                     AND entity_id LIKE '%motion%') as motion_events,
                    COUNT(*) FILTER (WHERE domain = 'climate') as climate_events,
                    MIN(EXTRACT(HOUR FROM changed_at)::int)
                        FILTER (WHERE domain = 'binary_sensor'
                                AND entity_id LIKE '%motion%'
                                AND to_state = 'on') as first_motion_hour,
                    MAX(EXTRACT(HOUR FROM changed_at)::int)
                        FILTER (WHERE domain = 'binary_sensor'
                                AND entity_id LIKE '%motion%'
                                AND to_state = 'on') as last_motion_hour,
                    array_agg(DISTINCT domain) as domains_active
                FROM home_activity_log
                WHERE changed_at::date = :bin_date
            """), {"bin_date": bin_date}).fetchone()

            if result and (result.light_events > 0 or result.motion_events > 0):
                return {
                    "light_events": result.light_events or 0,
                    "switch_events": result.switch_events or 0,
                    "motion_events": result.motion_events or 0,
                    "climate_events": result.climate_events or 0,
                    "first_motion_hour": result.first_motion_hour,
                    "last_motion_hour": result.last_motion_hour,
                    "domains_active": [d for d in (result.domains_active or []) if d],
                }
        except Exception as e:
            logger.warning(f"Home metrics aggregation failed: {e}")
            db.rollback()
        return None

    async def _aggregate_mood_metrics(self, db: Session, user_id: str, bin_date: date) -> Optional[Dict]:
        """Aggregate mood/conversation metrics for the day."""
        try:
            result = db.execute(text("""
                SELECT
                    COUNT(*) as message_count,
                    AVG((emotion_metadata->>'sentiment')::float)
                        FILTER (WHERE emotion_metadata->>'sentiment' IS NOT NULL) as avg_sentiment,
                    MODE() WITHIN GROUP (ORDER BY emotion_metadata->>'primary_emotion')
                        FILTER (WHERE emotion_metadata->>'primary_emotion' IS NOT NULL) as primary_emotion
                FROM episode
                WHERE user_id = :user_id
                  AND created_at::date = :bin_date
                  AND role = 'user'
            """), {"user_id": user_id, "bin_date": bin_date}).fetchone()

            # Also get energy level from subconscious log if available
            energy_result = db.execute(text("""
                SELECT AVG((state_snapshot->>'inferred_energy_level')::float) as avg_energy
                FROM subconscious_log
                WHERE user_id = :user_id
                  AND snapshot_at::date = :bin_date
                  AND state_snapshot->>'inferred_energy_level' IS NOT NULL
            """), {"user_id": user_id, "bin_date": bin_date}).fetchone()

            if result and result.message_count > 0:
                metrics = {
                    "message_count": result.message_count,
                    "avg_sentiment": round(_to_float(result.avg_sentiment), 3) if result.avg_sentiment else None,
                    "primary_emotion": result.primary_emotion,
                }
                if energy_result and energy_result.avg_energy:
                    metrics["avg_energy"] = round(_to_float(energy_result.avg_energy), 2)
                return metrics
        except Exception as e:
            logger.warning(f"Mood metrics aggregation failed: {e}")
            db.rollback()
        return None

    async def _aggregate_calendar_metrics(self, db: Session, user_id: str, bin_date: date) -> Optional[Dict]:
        """Aggregate calendar event metrics for the day."""
        try:
            from app.services.calendar_intelligence import classify_event

            result = db.execute(text("""
                SELECT title, start_time, end_time, all_day
                FROM calendar_event
                WHERE user_id = :user_id
                  AND start_time::date = :bin_date
                  AND is_completed = FALSE
            """), {"user_id": user_id, "bin_date": bin_date}).fetchall()

            if not result:
                return None

            event_count = len(result)
            categories = {}
            total_hours = 0.0
            evening_events = 0

            for row in result:
                # Classify
                classification = classify_event(row[0])
                cat = classification["category"]
                categories[cat] = categories.get(cat, 0) + 1

                # Duration
                if row[1] and row[2] and not row[3]:
                    duration = (row[2] - row[1]).total_seconds() / 3600
                    total_hours += duration

                # Evening events (after 5 PM)
                if row[1] and row[1].hour >= 17:
                    evening_events += 1

            return {
                "event_count": event_count,
                "scheduled_hours": round(total_hours, 1),
                "evening_events": evening_events,
                "categories": categories,
            }
        except Exception as e:
            logger.warning(f"Calendar metrics aggregation failed: {e}")
            db.rollback()
        return None

    async def backfill_bins(self, db: Session, user_id: str, days: int = 30) -> Dict[str, int]:
        """
        Backfill temporal bins for the last N days.

        Returns count of bins created/updated.
        """
        logger.info(f"📊 Backfilling {days} days of temporal bins for user {user_id}")

        created = 0
        updated = 0
        today = date.today()

        for i in range(days):
            bin_date = today - timedelta(days=i)
            try:
                # Check if bin exists (bin_hour = -1 for daily bins)
                existing = db.execute(text("""
                    SELECT id FROM temporal_bin
                    WHERE user_id = :user_id
                      AND bin_date = :bin_date
                      AND bin_type = 'daily'
                      AND (bin_hour = -1 OR bin_hour IS NULL)
                """), {"user_id": user_id, "bin_date": bin_date}).fetchone()

                await self.aggregate_daily_bin(db, user_id, bin_date)

                if existing:
                    updated += 1
                else:
                    created += 1

            except Exception as e:
                logger.error(f"Failed to backfill bin for {bin_date}: {e}")

        logger.info(f"✅ Backfill complete: {created} created, {updated} updated")
        return {"created": created, "updated": updated}

    async def get_time_series(
        self,
        db: Session,
        user_id: str,
        metrics: List[str],
        days: int = 30
    ) -> Dict[str, List[Dict]]:
        """
        Get time series data for specified metrics.

        Args:
            metrics: List of metric paths like 'health.sleep_hours', 'git.commit_count'
            days: Number of days to fetch

        Returns:
            Dict with metric names as keys and list of {date, value} as values
        """
        start_date = date.today() - timedelta(days=days)

        result = db.execute(text("""
            SELECT bin_date, git_metrics, health_metrics, food_metrics,
                   home_metrics, mood_metrics, day_of_week, is_weekend
            FROM temporal_bin
            WHERE user_id = :user_id
              AND bin_date >= :start_date
              AND bin_type = 'daily'
              AND (bin_hour = -1 OR bin_hour IS NULL)
            ORDER BY bin_date ASC
        """), {"user_id": user_id, "start_date": start_date}).fetchall()

        series = {metric: [] for metric in metrics}

        for row in result:
            for metric in metrics:
                domain, metric_name = metric.split('.', 1)

                # Get the appropriate metrics dict
                metrics_dict = None
                if domain == 'git':
                    metrics_dict = row.git_metrics
                elif domain == 'health':
                    metrics_dict = row.health_metrics
                elif domain == 'food':
                    metrics_dict = row.food_metrics
                elif domain == 'home':
                    metrics_dict = row.home_metrics
                elif domain == 'mood':
                    metrics_dict = row.mood_metrics

                value = None
                if metrics_dict and metric_name in metrics_dict:
                    value = metrics_dict[metric_name]

                series[metric].append({
                    "date": row.bin_date.isoformat(),
                    "value": value,
                    "day_of_week": row.day_of_week,
                    "is_weekend": row.is_weekend,
                })

        return series

    async def get_correlation_data(
        self,
        db: Session,
        user_id: str,
        metric_a: str,
        metric_b: str,
        days: int = 30,
        lag_days: int = 0
    ) -> List[Dict]:
        """
        Get paired data points for correlation analysis.

        Args:
            metric_a: First metric path (e.g., 'health.sleep_hours')
            metric_b: Second metric path (e.g., 'git.commit_count')
            days: Number of days to analyze
            lag_days: Offset for metric_b (positive = metric_b is from later date)

        Returns:
            List of {date, value_a, value_b} where both values are present
        """
        series = await self.get_time_series(db, user_id, [metric_a, metric_b], days + lag_days)

        series_a = {item['date']: item['value'] for item in series[metric_a]}
        series_b = {item['date']: item['value'] for item in series[metric_b]}

        paired_data = []

        for item_a in series[metric_a]:
            date_a = item_a['date']
            value_a = item_a['value']

            if value_a is None:
                continue

            # Calculate the date for metric_b based on lag
            date_obj = date.fromisoformat(date_a)
            date_b = (date_obj + timedelta(days=lag_days)).isoformat()

            value_b = series_b.get(date_b)

            if value_b is not None:
                paired_data.append({
                    "date_a": date_a,
                    "date_b": date_b,
                    "value_a": value_a,
                    "value_b": value_b,
                })

        return paired_data


# Singleton instance
temporal_bin_service = TemporalBinService()
