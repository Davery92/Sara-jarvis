"""
Health Status Tools for Sara

Provides Sara with access to health data during conversations.

Tool capabilities:
- Get current health summary (metrics, baselines, status)
- Get trend analysis for specific metrics
"""

import logging
from typing import Optional, Dict, Any

from app.tools.base import BaseTool, ToolResult
from app.services.health_insight_service import health_insight_service
from app.db.session import get_db

logger = logging.getLogger(__name__)


class HealthStatusTool(BaseTool):
    """Get current health status with metrics, baselines, and alerts."""

    name = "health_status"
    description = "Get the user's current health status including latest metrics (resting HR, HRV, sleep, weight, steps), baselines, and any active alerts. Use this when the user asks about their health, recovery, fitness metrics, or when health context would be helpful."
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
            'sleep_hours': 'Sleep Duration',
            'weight': 'Weight',
            'steps': 'Daily Steps',
            'active_energy': 'Active Calories',
            'heart_rate': 'Heart Rate',
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


# Export tools for registry
HEALTH_TOOLS = [
    HealthStatusTool(),
    HealthTrendTool(),
]
