"""
Health Status Tools for Sara

Provides Sara with access to health data during conversations.

Tool capabilities:
- Get current health summary (metrics, baselines, status)
- Get trend analysis for specific metrics
- List recent workouts (HealthKit-tracked + app-logged strength sessions)
"""

import logging
from datetime import datetime, timedelta
from app.core.timezone import naive_utc_now
from typing import Optional, Dict, Any

from sqlalchemy import text

from app.tools.base import BaseTool, ToolResult
from app.services.health_insight_service import health_insight_service
from app.db.session import get_db

logger = logging.getLogger(__name__)


class HealthStatusTool(BaseTool):
    """Get current health status with metrics, baselines, and alerts."""

    name = "health_status"
    description = (
        "Get the user's current health status including latest metrics and any active alerts. "
        "Available metrics include: resting HR, HRV (incl. morning), sleep duration + stage breakdown "
        "(deep/REM/core/awake minutes), weight, body temp, SpO2, respiratory rate, VO2 max, "
        "walking HR average, 1-minute heart-rate recovery, daily steps, active energy, "
        "stand minutes, exercise minutes, flights climbed, mindful minutes. "
        "Use this when the user asks about their health, recovery, sleep, fitness metrics, "
        "or when health context would be helpful."
    )
    parameters = {
        "type": "object",
        "properties": {
            "include_trends": {
                "type": "boolean",
                "description": "Include 7-day trend analysis for key metrics",
                "default": False
            },
            "include_insights": {
                "type": "boolean",
                "description": "Include recent AI-generated health insights",
                "default": True
            }
        },
        "required": []
    }

    async def execute(
        self,
        user_id: str,
        include_trends: bool = False,
        include_insights: bool = True
    ) -> ToolResult:
        """Execute health status lookup."""
        try:
            db = next(get_db())
            try:
                result = await self._get_health_status(
                    user_id=user_id,
                    db=db,
                    include_trends=include_trends,
                    include_insights=include_insights
                )
                return ToolResult(success=True, message=result)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error in health_status tool: {e}")
            return ToolResult(success=False, message=f"Error getting health status: {str(e)}")

    async def _get_health_status(
        self,
        user_id: str,
        db,
        include_trends: bool = False,
        include_insights: bool = True
    ) -> str:
        """Get current health status with metrics and alerts."""

        # Get health summary
        summary = await health_insight_service.get_health_summary(user_id, db)

        if not summary or not summary.get('metrics'):
            return "No recent health data available. The user may need to sync their health data from the iOS app."

        result_parts = ["## Current Health Status\n"]

        # Format metrics
        metrics = summary.get('metrics', {})
        metric_display = {
            'resting_hr': ('Resting Heart Rate', 'bpm'),
            'hrv': ('Heart Rate Variability', 'ms'),
            'sleep_hours': ('Sleep Duration', 'hours'),
            'weight': ('Weight', 'kg'),
            'steps': ('Steps Today', 'steps'),
            'active_energy': ('Active Calories', 'kcal'),
            'heart_rate': ('Heart Rate', 'bpm'),
        }

        result_parts.append("### Latest Metrics")
        for metric_type, data in metrics.items():
            if data.get('current_value') is None:
                continue

            display_name, unit = metric_display.get(metric_type, (metric_type.title(), ''))
            value = data['current_value']
            baseline = data.get('baseline')
            status = data.get('status', 'normal')

            # Format value
            if metric_type in ['resting_hr', 'hrv', 'steps', 'heart_rate']:
                value_str = f"{int(value)}"
            else:
                value_str = f"{value:.1f}"

            # Status and comparison
            status_note = ""
            if status == 'above_normal':
                status_note = " (above normal)"
            elif status == 'below_normal':
                status_note = " (below normal)"

            baseline_note = ""
            if baseline:
                if metric_type in ['resting_hr', 'hrv', 'steps', 'heart_rate']:
                    baseline_str = f"{int(baseline)}"
                else:
                    baseline_str = f"{baseline:.1f}"
                baseline_note = f", 7-day baseline: {baseline_str} {unit}"

            result_parts.append(f"- **{display_name}**: {value_str} {unit}{status_note}{baseline_note}")

        # Add alerts
        alerts = summary.get('recent_alerts', [])
        if alerts:
            result_parts.append("\n### Recent Alerts")
            for alert in alerts[:5]:
                severity = alert.get('severity', 'info')
                message = alert.get('message', 'Alert')
                result_parts.append(f"- [{severity.upper()}] {message}")

        # Add insights if requested
        if include_insights:
            context = await health_insight_service.get_relevant_health_context(user_id, db)
            if context and "Health Insights" in context:
                # Extract just the insights section
                insights_start = context.find("### Health Insights")
                if insights_start >= 0:
                    result_parts.append("\n" + context[insights_start:])

        # Add trend summaries if requested
        if include_trends:
            result_parts.append("\n### 7-Day Trends")
            for metric_type in ['resting_hr', 'hrv', 'sleep_hours']:
                trend = await health_insight_service.get_trend_analysis(user_id, db, metric_type, 7)
                if trend and trend.get('trend'):
                    display_name = metric_display.get(metric_type, (metric_type.title(), ''))[0]
                    result_parts.append(f"- {display_name}: {trend['trend']}")

        return "\n".join(result_parts)


class HealthTrendTool(BaseTool):
    """Get detailed trend analysis for a specific health metric."""

    name = "health_trend"
    description = "Get detailed trend analysis for a specific health metric over time. Use this when the user asks about trends in a specific metric (e.g., 'how has my HRV been this week?', 'show my heart rate trend')."
    parameters = {
        "type": "object",
        "properties": {
            "metric_type": {
                "type": "string",
                "description": "The metric to analyze",
                "enum": ["resting_hr", "hrv", "sleep_hours", "weight", "steps", "active_energy", "heart_rate"]
            },
            "days": {
                "type": "integer",
                "description": "Number of days to analyze (default 7, max 30)",
                "default": 7,
                "minimum": 1,
                "maximum": 30
            }
        },
        "required": ["metric_type"]
    }

    async def execute(
        self,
        user_id: str,
        metric_type: str,
        days: int = 7
    ) -> ToolResult:
        """Execute health trend analysis."""
        try:
            db = next(get_db())
            try:
                result = await self._get_health_trend(
                    user_id=user_id,
                    db=db,
                    metric_type=metric_type,
                    days=min(days, 30)
                )
                return ToolResult(success=True, message=result)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error in health_trend tool: {e}")
            return ToolResult(success=False, message=f"Error getting health trend: {str(e)}")

    async def _get_health_trend(
        self,
        user_id: str,
        db,
        metric_type: str,
        days: int = 7
    ) -> str:
        """Get detailed trend analysis for a specific metric."""

        metric_display = {
            'resting_hr': 'Resting Heart Rate',
            'hrv': 'Heart Rate Variability',
            'hrv_morning': 'Morning HRV',
            'sleep_hours': 'Sleep Duration',
            'sleep_deep_min': 'Deep Sleep',
            'sleep_rem_min': 'REM Sleep',
            'sleep_core_min': 'Core Sleep',
            'sleep_awake_min': 'Awake During Sleep',
            'weight': 'Weight',
            'steps': 'Daily Steps',
            'active_energy': 'Active Calories',
            'heart_rate': 'Heart Rate',
            'spo2': 'Blood Oxygen',
            'respiratory_rate': 'Respiratory Rate',
            'body_temp': 'Body Temperature',
            'vo2_max': 'VO2 Max',
            'walking_hr_avg': 'Walking Heart Rate',
            'hr_recovery_1min': '1-Min HR Recovery',
            'stand_minutes': 'Stand Minutes',
            'exercise_minutes': 'Exercise Minutes',
            'flights_climbed': 'Flights Climbed',
            'mindful_minutes': 'Mindful Minutes',
        }

        display_name = metric_display.get(metric_type, metric_type.title())

        trend = await health_insight_service.get_trend_analysis(user_id, db, metric_type, days)

        if not trend or not trend.get('daily_data'):
            return f"No {display_name} data available for the last {days} days."

        result_parts = [f"## {display_name} Trend ({days} Days)\n"]

        # Overall summary
        overall_avg = trend.get('overall_avg')
        trend_direction = trend.get('trend', 'stable')

        if overall_avg:
            if metric_type in ['resting_hr', 'hrv', 'steps', 'heart_rate']:
                avg_str = f"{int(overall_avg)}"
            else:
                avg_str = f"{overall_avg:.1f}"
            result_parts.append(f"**Average**: {avg_str}")

        trend_emoji = {
            'increasing': '📈',
            'decreasing': '📉',
            'stable': '➡️'
        }
        result_parts.append(f"**Trend**: {trend_emoji.get(trend_direction, '')} {trend_direction.title()}\n")

        # Daily breakdown
        result_parts.append("### Daily Values")
        daily_data = trend.get('daily_data', [])
        for day_data in daily_data[-7:]:  # Show last 7 days max
            day = day_data.get('day', 'Unknown')
            avg_value = day_data.get('avg_value')
            if avg_value:
                if metric_type in ['resting_hr', 'hrv', 'steps', 'heart_rate']:
                    value_str = f"{int(avg_value)}"
                else:
                    value_str = f"{avg_value:.1f}"
                result_parts.append(f"- {day}: {value_str}")

        # Add interpretation
        result_parts.append("\n### Interpretation")
        if trend_direction == 'increasing':
            if metric_type == 'resting_hr':
                result_parts.append("Rising resting heart rate may indicate stress, poor recovery, or illness. Consider taking it easier.")
            elif metric_type == 'hrv':
                result_parts.append("Increasing HRV is a positive sign - it suggests improving recovery and resilience.")
            elif metric_type == 'sleep_hours':
                result_parts.append("Getting more sleep - good job prioritizing rest!")
            elif metric_type == 'weight':
                result_parts.append("Weight is trending up. This may be intentional (muscle gain) or worth monitoring.")
            elif metric_type == 'steps':
                result_parts.append("Great job increasing your daily activity!")
        elif trend_direction == 'decreasing':
            if metric_type == 'resting_hr':
                result_parts.append("Declining resting heart rate is generally positive - it indicates good cardiovascular adaptation.")
            elif metric_type == 'hrv':
                result_parts.append("Decreasing HRV may signal accumulated stress or fatigue. Consider prioritizing recovery.")
            elif metric_type == 'sleep_hours':
                result_parts.append("Sleep duration is declining. Try to prioritize getting adequate rest.")
            elif metric_type == 'weight':
                result_parts.append("Weight is trending down. Monitor to ensure it's intentional and healthy.")
            elif metric_type == 'steps':
                result_parts.append("Daily activity has decreased. Try to find opportunities to move more.")
        else:
            result_parts.append(f"Your {display_name.lower()} has been relatively stable.")

        return "\n".join(result_parts)


# Apple HealthKit HKWorkoutActivityType numeric → human label.
# (iOS lib emits the numeric enum value as a string; we humanize here.)
HK_ACTIVITY_TYPE_NAMES: Dict[str, str] = {
    "1": "American Football", "2": "Archery", "3": "Australian Football",
    "4": "Badminton", "5": "Baseball", "6": "Basketball", "7": "Bowling",
    "8": "Boxing", "9": "Climbing", "10": "Cricket", "11": "Cross Training",
    "12": "Curling", "13": "Cycling", "14": "Dance", "15": "Dance",
    "16": "Elliptical", "17": "Equestrian", "18": "Fencing", "19": "Fishing",
    "20": "Strength Training", "21": "Golf", "22": "Gymnastics", "23": "Handball",
    "24": "Hiking", "25": "Hockey", "26": "Hunting", "27": "Lacrosse",
    "28": "Martial Arts", "29": "Mind & Body", "30": "Cardio",
    "31": "Paddle Sports", "32": "Play", "33": "Recovery", "34": "Racquetball",
    "35": "Rowing", "36": "Rugby", "37": "Running", "38": "Sailing",
    "39": "Skating", "40": "Snow Sports", "41": "Soccer", "42": "Softball",
    "43": "Squash", "44": "Stair Climbing", "45": "Surfing", "46": "Swimming",
    "47": "Table Tennis", "48": "Tennis", "49": "Track & Field",
    "50": "Strength Training", "51": "Volleyball", "52": "Walking",
    "53": "Water Fitness", "54": "Water Polo", "55": "Water Sports",
    "56": "Wrestling", "57": "Yoga", "58": "Barre", "59": "Core Training",
    "60": "Cross-Country Skiing", "61": "Downhill Skiing", "62": "Flexibility",
    "63": "HIIT", "64": "Jump Rope", "65": "Kickboxing", "66": "Pilates",
    "67": "Snowboarding", "68": "Stairs", "69": "Step Training",
    "70": "Wheelchair Walk", "71": "Wheelchair Run", "72": "Tai Chi",
    "73": "Mixed Cardio", "74": "Hand Cycling", "75": "Disc Sports",
    "76": "Fitness Gaming", "77": "Cardio Dance", "78": "Social Dance",
    "79": "Pickleball", "80": "Cooldown", "82": "Swim-Bike-Run",
    "83": "Transition", "84": "Underwater Diving", "3000": "Other",
}


def _humanize_activity_type(raw: Optional[str]) -> str:
    if not raw:
        return "workout"
    s = str(raw).strip()
    if s in HK_ACTIVITY_TYPE_NAMES:
        return HK_ACTIVITY_TYPE_NAMES[s]
    # Already a string label (e.g., "Walking") — return as-is, just title-cased.
    return s.replace("_", " ").title() if s.replace("_", "").isalpha() else s


class WorkoutHistoryTool(BaseTool):
    """List recent workouts from both HealthKit (Watch-tracked) and app-logged strength sessions."""

    name = "workout_history"
    description = (
        "Get a unified list of the user's recent workouts. Includes HealthKit-tracked "
        "workouts (outdoor walks, runs, cycling, yoga, etc. from Apple Watch) and "
        "app-logged strength sessions. Use when the user asks about their recent workouts, "
        "training, exercise, runs, walks, or fitness activity history."
    )
    parameters = {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "How many days back to include (default 14, max 90).",
                "default": 14,
            },
            "activity_filter": {
                "type": "string",
                "description": (
                    "Optional substring filter on activity type or workout title "
                    "(e.g. 'walk', 'run', 'strength'). Leave empty for all activities."
                ),
            },
        },
        "required": [],
    }

    async def execute(
        self,
        user_id: str,
        days: int = 14,
        activity_filter: Optional[str] = None,
    ) -> ToolResult:
        try:
            days = max(1, min(int(days or 14), 90))
            db = next(get_db())
            try:
                msg = await self._get_workout_history(user_id, db, days, activity_filter)
                return ToolResult(success=True, message=msg)
            finally:
                db.close()
        except Exception as e:
            logger.exception(f"Error in workout_history tool: {e}")
            return ToolResult(success=False, message=f"Error getting workout history: {e}")

    async def _get_workout_history(
        self,
        user_id: str,
        db,
        days: int,
        activity_filter: Optional[str],
    ) -> str:
        cutoff = naive_utc_now() - timedelta(days=days)
        af = (activity_filter or "").lower().strip()

        # HealthKit-tracked workouts (Apple Watch / Health app)
        ext_query = text("""
            SELECT id, activity_type, started_at, ended_at, duration_seconds,
                   total_energy_kcal, total_distance_m,
                   avg_heart_rate, max_heart_rate
            FROM external_workout
            WHERE user_id = :user_id AND started_at >= :cutoff
            ORDER BY started_at DESC
            LIMIT 100
        """)
        ext_rows = db.execute(ext_query, {"user_id": user_id, "cutoff": cutoff}).fetchall()

        # App-logged strength sessions (workout_sessions joined with the workout title)
        strength_query = text("""
            SELECT ws.id, ws.started_at, ws.completed_at, ws.session_state,
                   w.title AS workout_title,
                   COALESCE((
                       SELECT COUNT(*)
                       FROM workout_log wl
                       WHERE wl.session_id = ws.id
                         AND COALESCE(wl.skipped, false) = false
                   ), 0) AS sets_completed,
                   COALESCE((
                       SELECT SUM(wl.reps)
                       FROM workout_log wl
                       WHERE wl.session_id = ws.id
                         AND COALESCE(wl.skipped, false) = false
                   ), 0) AS total_reps,
                   COALESCE((
                       SELECT MAX(wl.rpe)
                       FROM workout_log wl
                       WHERE wl.session_id = ws.id
                   ), NULL) AS max_rpe
            FROM workout_sessions ws
            JOIN workout w ON w.id = ws.workout_id
            WHERE ws.user_id = :user_id
              AND ws.started_at >= :cutoff
              AND ws.session_state = 'completed'
            ORDER BY ws.started_at DESC
            LIMIT 100
        """)
        # `workout_sessions` was an empty duplicate dropped in migration 118 (real
        # sessions live in active_workout_session) — this always returned []. Guard
        # against the dropped table so the health tool doesn't crash; repoint later.
        if db.execute(text("SELECT to_regclass('public.workout_sessions')")).scalar():
            strength_rows = db.execute(strength_query, {"user_id": user_id, "cutoff": cutoff}).fetchall()
        else:
            strength_rows = []

        # Normalize into a single time-sorted list
        items = []
        for r in ext_rows:
            human_label = _humanize_activity_type(r.activity_type)
            if af and af not in human_label.lower() and af not in (r.activity_type or "").lower():
                continue
            duration_min = round((r.duration_seconds or 0) / 60)
            distance_km = (float(r.total_distance_m) / 1000) if r.total_distance_m else None
            kcal = int(r.total_energy_kcal) if r.total_energy_kcal else None
            items.append({
                "kind": "external",
                "when": r.started_at,
                "label": human_label,
                "duration_min": duration_min,
                "distance_km": distance_km,
                "kcal": kcal,
                "avg_hr": r.avg_heart_rate,
                "max_hr": r.max_heart_rate,
            })

        for r in strength_rows:
            label = (r.workout_title or "strength").lower()
            if af and af not in label:
                continue
            started = r.started_at
            completed = r.completed_at
            duration_min = None
            if started and completed:
                duration_min = max(0, round((completed - started).total_seconds() / 60))
            items.append({
                "kind": "strength",
                "when": started,
                "label": r.workout_title or "Strength session",
                "duration_min": duration_min,
                "sets": r.sets_completed,
                "reps": r.total_reps,
                "max_rpe": r.max_rpe,
            })

        # Sort newest first; drop entries with no timestamp
        items = [i for i in items if i["when"] is not None]
        items.sort(key=lambda i: i["when"], reverse=True)

        if not items:
            scope = f"the last {days} days"
            if af:
                scope += f" matching '{activity_filter}'"
            return f"No workouts found for {scope}."

        # Compose markdown
        lines = [f"## Workouts — last {days} days"]
        ext_count = sum(1 for i in items if i["kind"] == "external")
        strength_count = sum(1 for i in items if i["kind"] == "strength")
        lines.append(
            f"_{ext_count} HealthKit-tracked · {strength_count} strength sessions · "
            f"{len(items)} total_\n"
        )

        for it in items[:30]:  # cap output for prompt budget
            when_str = it["when"].strftime("%a %b %-d, %-I:%M %p") if it["when"] else "—"
            if it["kind"] == "external":
                bits = [f"⌛ {it['duration_min']} min" if it.get("duration_min") else None]
                if it.get("distance_km"):
                    bits.append(f"📏 {it['distance_km']:.2f} km")
                if it.get("kcal"):
                    bits.append(f"🔥 {it['kcal']} kcal")
                if it.get("avg_hr"):
                    bits.append(f"💓 {it['avg_hr']} avg / {it['max_hr']} max bpm")
                detail = " · ".join(b for b in bits if b)
                lines.append(f"- **{when_str}** — {it['label']} _(Watch)_  \n  {detail}")
            else:
                bits = [f"⌛ {it['duration_min']} min" if it.get("duration_min") else None]
                if it.get("sets"):
                    bits.append(f"{it['sets']} sets / {it.get('reps') or 0} reps")
                if it.get("max_rpe") is not None:
                    bits.append(f"max RPE {it['max_rpe']}")
                detail = " · ".join(b for b in bits if b)
                lines.append(f"- **{when_str}** — {it['label']} _(strength)_  \n  {detail}")

        return "\n".join(lines)


# Export tools for registry
HEALTH_TOOLS = [
    HealthStatusTool(),
    HealthTrendTool(),
    WorkoutHistoryTool(),
]
