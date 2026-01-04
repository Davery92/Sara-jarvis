"""
Pattern Correlation Tools

Tools for Sara to query discovered patterns and correlations
across different domains (git, health, food, home, mood).
"""

from typing import Dict, Any, List
from app.tools.base import BaseTool, ToolResult
from app.db.session import get_db
from sqlalchemy.orm import Session
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


class PatternQueryTool(BaseTool):
    """Tool for querying discovered patterns"""

    @property
    def name(self) -> str:
        return "pattern_query"

    @property
    def description(self) -> str:
        return """Query discovered cross-domain patterns and correlations.

Use this to find patterns like:
- "Sleep affects productivity" (health -> git)
- "Late coding impacts HRV" (git -> health)
- "Protein intake correlates with energy" (food -> mood)
- "Home temperature affects sleep" (home -> health)

Returns confirmed patterns with correlation strength and evidence."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Filter by domain: 'git', 'health', 'food', 'home', 'mood', or leave empty for all",
                    "enum": ["git", "health", "food", "home", "mood", ""]
                },
                "include_emerging": {
                    "type": "boolean",
                    "description": "Include emerging (unconfirmed) patterns. Default: false",
                    "default": False
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum patterns to return (default: 5)",
                    "default": 5
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Query patterns from the database"""

        domain = kwargs.get("domain", "")
        include_emerging = kwargs.get("include_emerging", False)
        limit = kwargs.get("limit", 5)

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Build query
            status_filter = "IN ('confirmed', 'emerging')" if include_emerging else "= 'confirmed'"
            domain_filter = ""
            if domain:
                domain_filter = f"AND (metric_a LIKE '{domain}.%' OR metric_b LIKE '{domain}.%')"

            result = db.execute(text(f"""
                SELECT
                    id, title, description, narrative, pattern_category,
                    metric_a, metric_b, correlation_coefficient,
                    confidence, sample_size, p_value,
                    status, temporal_lag_hours,
                    validation_count, invalidation_count,
                    first_detected_at, last_validated_at
                FROM correlation_pattern
                WHERE user_id = :user_id
                  AND status {status_filter}
                  {domain_filter}
                ORDER BY confidence DESC, correlation_coefficient DESC
                LIMIT :limit
            """), {
                "user_id": user_id,
                "limit": limit
            }).fetchall()

            patterns = []
            for row in result:
                patterns.append({
                    "id": str(row.id),
                    "title": row.title,
                    "description": row.description,
                    "narrative": row.narrative,
                    "category": row.pattern_category,
                    "metrics": {
                        "a": row.metric_a,
                        "b": row.metric_b
                    },
                    "correlation": round(row.correlation_coefficient, 3),
                    "confidence": round(row.confidence, 2),
                    "sample_size": row.sample_size,
                    "p_value": round(row.p_value, 4) if row.p_value else None,
                    "status": row.status,
                    "lag_hours": row.temporal_lag_hours,
                    "validations": row.validation_count,
                    "first_detected": row.first_detected_at.isoformat() if row.first_detected_at else None
                })

            if not patterns:
                return ToolResult(
                    success=True,
                    data={"patterns": []},
                    message="No patterns found yet. Patterns are discovered automatically as more data is collected."
                )

            return ToolResult(
                success=True,
                data={
                    "patterns": patterns,
                    "total": len(patterns),
                    "domain_filter": domain or "all"
                },
                message=f"Found {len(patterns)} pattern(s)"
            )

        except Exception as e:
            logger.error(f"Pattern query failed: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to query patterns: {str(e)}"
            )
        finally:
            db.close()


class PatternInsightTool(BaseTool):
    """Tool for getting contextual pattern insights"""

    @property
    def name(self) -> str:
        return "pattern_insights"

    @property
    def description(self) -> str:
        return """Get pattern-based insights relevant to the current context.

Use this when the user asks about:
- Productivity trends or patterns
- Health impacts on work
- Sleep/exercise effects
- Food/nutrition correlations
- Time-of-day patterns

Returns contextually relevant insights from discovered patterns."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "context": {
                    "type": "string",
                    "description": "The context or topic to find relevant patterns for (e.g., 'productivity', 'sleep quality', 'energy levels')"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum insights to return (default: 3)",
                    "default": 3
                }
            },
            "required": ["context"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Get contextual pattern insights"""

        context = kwargs.get("context", "")
        limit = kwargs.get("limit", 3)

        if not context:
            return ToolResult(
                success=False,
                message="Context is required to find relevant patterns"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Map context keywords to domains/metrics
            context_mappings = {
                "productivity": ["git.commit_count", "git.additions", "git.active_hours"],
                "sleep": ["health.sleep_hours", "health.sleep_quality"],
                "energy": ["mood.avg_energy", "health.active_energy"],
                "hrv": ["health.hrv"],
                "heart": ["health.resting_hr", "health.hrv"],
                "exercise": ["health.steps", "health.active_energy"],
                "food": ["food.total_calories", "food.protein_g"],
                "protein": ["food.protein_g"],
                "mood": ["mood.avg_sentiment", "mood.avg_energy"],
                "home": ["home.first_motion_hour", "home.light_events"],
                "work": ["git.commit_count", "git.late_commits"],
                "coding": ["git.commit_count", "git.additions", "git.late_commits"],
            }

            # Find relevant metrics based on context
            relevant_metrics = []
            context_lower = context.lower()
            for keyword, metrics in context_mappings.items():
                if keyword in context_lower:
                    relevant_metrics.extend(metrics)

            # Build query with metric relevance
            if relevant_metrics:
                metric_conditions = " OR ".join([
                    f"metric_a = '{m}' OR metric_b = '{m}'"
                    for m in relevant_metrics
                ])
                metric_filter = f"AND ({metric_conditions})"
            else:
                metric_filter = ""

            result = db.execute(text(f"""
                SELECT
                    id, title, narrative, pattern_category,
                    metric_a, metric_b, correlation_coefficient,
                    confidence, temporal_lag_hours
                FROM correlation_pattern
                WHERE user_id = :user_id
                  AND status = 'confirmed'
                  AND confidence >= 0.6
                  {metric_filter}
                ORDER BY confidence DESC
                LIMIT :limit
            """), {
                "user_id": user_id,
                "limit": limit
            }).fetchall()

            insights = []
            for row in result:
                insights.append({
                    "pattern_id": str(row.id),
                    "title": row.title,
                    "narrative": row.narrative,
                    "category": row.pattern_category,
                    "correlation": round(row.correlation_coefficient, 3),
                    "confidence": round(row.confidence, 2),
                    "lag_hours": row.temporal_lag_hours
                })

            if not insights:
                return ToolResult(
                    success=True,
                    data={"insights": []},
                    message=f"No confirmed patterns found related to '{context}' yet."
                )

            return ToolResult(
                success=True,
                data={
                    "insights": insights,
                    "context": context,
                    "total": len(insights)
                },
                message=f"Found {len(insights)} pattern insight(s) related to '{context}'"
            )

        except Exception as e:
            logger.error(f"Pattern insights failed: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to get pattern insights: {str(e)}"
            )
        finally:
            db.close()


class PatternTimeSeresTool(BaseTool):
    """Tool for getting time series data for pattern visualization"""

    @property
    def name(self) -> str:
        return "pattern_timeseries"

    @property
    def description(self) -> str:
        return """Get time series data for metrics to visualize patterns.

Use this to show trends over time for metrics like:
- health.sleep_hours
- git.commit_count
- food.protein_g
- mood.avg_energy

Returns daily values for the specified metrics."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "metrics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of metrics to retrieve (e.g., ['health.sleep_hours', 'git.commit_count'])"
                },
                "days": {
                    "type": "integer",
                    "description": "Number of days of history (default: 30, max: 90)",
                    "default": 30
                }
            },
            "required": ["metrics"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Get time series data for metrics"""

        metrics = kwargs.get("metrics", [])
        days = min(kwargs.get("days", 30), 90)

        if not metrics:
            return ToolResult(
                success=False,
                message="At least one metric is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            from datetime import date, timedelta
            start_date = date.today() - timedelta(days=days)

            result = db.execute(text("""
                SELECT bin_date, git_metrics, health_metrics, food_metrics,
                       home_metrics, mood_metrics, day_of_week
                FROM temporal_bin
                WHERE user_id = :user_id
                  AND bin_date >= :start_date
                  AND bin_type = 'daily'
                ORDER BY bin_date ASC
            """), {
                "user_id": user_id,
                "start_date": start_date
            }).fetchall()

            # Extract requested metrics from bins
            series = {metric: [] for metric in metrics}

            for row in result:
                bin_date = row.bin_date.isoformat()

                for metric in metrics:
                    domain, field = metric.split('.', 1)

                    # Get the right metrics dict
                    metrics_dict = None
                    if domain == 'git' and row.git_metrics:
                        metrics_dict = row.git_metrics
                    elif domain == 'health' and row.health_metrics:
                        metrics_dict = row.health_metrics
                    elif domain == 'food' and row.food_metrics:
                        metrics_dict = row.food_metrics
                    elif domain == 'home' and row.home_metrics:
                        metrics_dict = row.home_metrics
                    elif domain == 'mood' and row.mood_metrics:
                        metrics_dict = row.mood_metrics

                    value = metrics_dict.get(field) if metrics_dict else None

                    series[metric].append({
                        "date": bin_date,
                        "value": value,
                        "day_of_week": row.day_of_week
                    })

            return ToolResult(
                success=True,
                data={
                    "series": series,
                    "days": days,
                    "data_points": len(result)
                },
                message=f"Retrieved {len(result)} days of data for {len(metrics)} metric(s)"
            )

        except Exception as e:
            logger.error(f"Time series query failed: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to get time series: {str(e)}"
            )
        finally:
            db.close()


class PatternCorrelationTool(BaseTool):
    """Tool for analyzing correlation between two specific metrics"""

    @property
    def name(self) -> str:
        return "pattern_correlation"

    @property
    def description(self) -> str:
        return """Analyze correlation between two specific metrics.

Use this to check if there's a relationship between metrics like:
- "Does my sleep affect my productivity?"
- "Is there a correlation between protein intake and energy?"
- "Does late coding impact my HRV?"

Returns correlation coefficient, significance, and interpretation."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "metric_a": {
                    "type": "string",
                    "description": "First metric (e.g., 'health.sleep_hours')"
                },
                "metric_b": {
                    "type": "string",
                    "description": "Second metric (e.g., 'git.commit_count')"
                },
                "lag_days": {
                    "type": "integer",
                    "description": "Days to offset metric_b (e.g., 1 means 'does A today affect B tomorrow?'). Default: 0",
                    "default": 0
                },
                "days": {
                    "type": "integer",
                    "description": "Days of data to analyze (default: 30)",
                    "default": 30
                }
            },
            "required": ["metric_a", "metric_b"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Analyze correlation between two metrics"""

        metric_a = kwargs.get("metric_a")
        metric_b = kwargs.get("metric_b")
        lag_days = kwargs.get("lag_days", 0)
        days = kwargs.get("days", 30)

        if not metric_a or not metric_b:
            return ToolResult(
                success=False,
                message="Both metric_a and metric_b are required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            from app.services.cross_domain_analyzer import cross_domain_analyzer

            result = await cross_domain_analyzer.analyze_correlation(
                db, user_id, metric_a, metric_b, days, lag_days
            )

            if not result:
                return ToolResult(
                    success=True,
                    data={"insufficient_data": True},
                    message=f"Insufficient data to analyze correlation between {metric_a} and {metric_b}. Need at least 7 days of paired data."
                )

            return ToolResult(
                success=True,
                data={
                    "metric_a": result.metric_a,
                    "metric_b": result.metric_b,
                    "correlation": result.correlation_coefficient,
                    "sample_size": result.sample_size,
                    "p_value": result.p_value,
                    "effect_size": result.effect_size,
                    "lag_days": result.lag_days,
                    "is_significant": result.is_significant,
                    "interpretation": result.interpretation
                },
                message=result.interpretation
            )

        except Exception as e:
            logger.error(f"Correlation analysis failed: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to analyze correlation: {str(e)}"
            )
        finally:
            db.close()


# Export all pattern tools
PATTERN_TOOLS = [
    PatternQueryTool(),
    PatternInsightTool(),
    PatternTimeSeresTool(),
    PatternCorrelationTool(),
]
