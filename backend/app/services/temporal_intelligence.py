"""
Temporal Intelligence Engine
Generates weekly, monthly, and quarterly reports with insights
"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta, date, timezone
from pydantic import BaseModel
import json
import logging

logger = logging.getLogger(__name__)


class IntelligenceReport(BaseModel):
    """Intelligence report model"""
    id: Optional[int] = None
    user_id: str
    report_type: str  # weekly, monthly, quarterly
    period_start: date
    period_end: date
    report_data: Dict[str, Any]
    summary: Optional[str] = None
    insights: List[str] = []
    patterns: List[Dict[str, Any]] = []
    recommendations: List[str] = []
    generation_time_ms: Optional[int] = None
    created_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None


class TemporalIntelligenceEngine:
    """Generates periodic intelligence reports"""

    def __init__(self, db: Session, llm_client=None):
        self.db = db
        self.llm_client = llm_client

    async def generate_weekly_report(
        self,
        user_id: str,
        week_start: Optional[date] = None
    ) -> IntelligenceReport:
        """
        Generate weekly intelligence report

        Args:
            user_id: User ID
            week_start: Start of week (Monday), defaults to last Monday

        Returns:
            IntelligenceReport with weekly insights
        """
        start_time = datetime.now(timezone.utc)

        # Calculate period
        if week_start is None:
            today = date.today()
            days_since_monday = today.weekday()
            week_start = today - timedelta(days=days_since_monday + 7)  # Last Monday

        week_end = week_start + timedelta(days=6)  # Sunday

        logger.info(f"📊 Generating weekly report for {user_id}: {week_start} to {week_end}")

        # Aggregate data
        report_data = await self._aggregate_weekly_data(user_id, week_start, week_end)

        # Detect patterns
        patterns = await self._detect_weekly_patterns(user_id, report_data)

        # Generate insights with LLM
        if self.llm_client:
            summary, insights, recommendations = await self._generate_llm_insights(
                user_id, "weekly", report_data, patterns
            )
        else:
            summary, insights, recommendations = self._generate_fallback_insights(
                "weekly", report_data, patterns
            )

        # Calculate generation time
        generation_time_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

        # Create report
        report = IntelligenceReport(
            user_id=user_id,
            report_type="weekly",
            period_start=week_start,
            period_end=week_end,
            report_data=report_data,
            summary=summary,
            insights=insights,
            patterns=patterns,
            recommendations=recommendations,
            generation_time_ms=generation_time_ms
        )

        # Save to database
        await self._save_report(report)

        logger.info(f"✅ Weekly report generated in {generation_time_ms}ms")

        return report

    async def generate_monthly_report(
        self,
        user_id: str,
        month: Optional[date] = None
    ) -> IntelligenceReport:
        """
        Generate monthly intelligence report

        Args:
            user_id: User ID
            month: First day of month, defaults to last month

        Returns:
            IntelligenceReport with monthly insights
        """
        start_time = datetime.now(timezone.utc)

        # Calculate period
        if month is None:
            today = date.today()
            # First day of last month
            month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)

        # Last day of month
        if month.month == 12:
            month_end = month.replace(month=1, year=month.year + 1, day=1) - timedelta(days=1)
        else:
            month_end = month.replace(month=month.month + 1, day=1) - timedelta(days=1)

        logger.info(f"📊 Generating monthly report for {user_id}: {month} to {month_end}")

        # Aggregate data
        report_data = await self._aggregate_monthly_data(user_id, month, month_end)

        # Detect patterns
        patterns = await self._detect_monthly_patterns(user_id, report_data)

        # Generate insights with LLM
        if self.llm_client:
            summary, insights, recommendations = await self._generate_llm_insights(
                user_id, "monthly", report_data, patterns
            )
        else:
            summary, insights, recommendations = self._generate_fallback_insights(
                "monthly", report_data, patterns
            )

        # Calculate generation time
        generation_time_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

        # Create report
        report = IntelligenceReport(
            user_id=user_id,
            report_type="monthly",
            period_start=month,
            period_end=month_end,
            report_data=report_data,
            summary=summary,
            insights=insights,
            patterns=patterns,
            recommendations=recommendations,
            generation_time_ms=generation_time_ms
        )

        # Save to database
        await self._save_report(report)

        logger.info(f"✅ Monthly report generated in {generation_time_ms}ms")

        return report

    async def generate_quarterly_report(
        self,
        user_id: str,
        quarter_start: Optional[date] = None
    ) -> IntelligenceReport:
        """
        Generate quarterly intelligence report

        Args:
            user_id: User ID
            quarter_start: Start of quarter, defaults to last quarter

        Returns:
            IntelligenceReport with quarterly insights
        """
        start_time = datetime.now(timezone.utc)

        # Calculate period
        if quarter_start is None:
            today = date.today()
            # Determine quarter
            current_quarter = (today.month - 1) // 3
            # Last quarter
            if current_quarter == 0:
                quarter_start = date(today.year - 1, 10, 1)  # Q4 of last year
            else:
                quarter_month = (current_quarter - 1) * 3 + 1
                quarter_start = date(today.year, quarter_month, 1)

        # End of quarter (3 months later)
        month = quarter_start.month + 3
        if month > 12:
            quarter_end = date(quarter_start.year + 1, month - 12, 1) - timedelta(days=1)
        else:
            quarter_end = date(quarter_start.year, month, 1) - timedelta(days=1)

        logger.info(f"📊 Generating quarterly report for {user_id}: {quarter_start} to {quarter_end}")

        # Aggregate data
        report_data = await self._aggregate_quarterly_data(user_id, quarter_start, quarter_end)

        # Detect patterns
        patterns = await self._detect_quarterly_patterns(user_id, report_data)

        # Generate insights with LLM
        if self.llm_client:
            summary, insights, recommendations = await self._generate_llm_insights(
                user_id, "quarterly", report_data, patterns
            )
        else:
            summary, insights, recommendations = self._generate_fallback_insights(
                "quarterly", report_data, patterns
            )

        # Calculate generation time
        generation_time_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

        # Create report
        report = IntelligenceReport(
            user_id=user_id,
            report_type="quarterly",
            period_start=quarter_start,
            period_end=quarter_end,
            report_data=report_data,
            summary=summary,
            insights=insights,
            patterns=patterns,
            recommendations=recommendations,
            generation_time_ms=generation_time_ms
        )

        # Save to database
        await self._save_report(report)

        logger.info(f"✅ Quarterly report generated in {generation_time_ms}ms")

        return report

    async def _aggregate_weekly_data(
        self,
        user_id: str,
        start_date: date,
        end_date: date
    ) -> Dict[str, Any]:
        """Aggregate weekly data from all sources"""
        data = {}

        # Workout stats
        workout_query = text("""
            SELECT
                COUNT(*) as workout_count,
                SUM(CAST(meta->>'duration' AS INTEGER)) / 60 as total_minutes,
                AVG(CAST(meta->>'duration' AS INTEGER)) / 60 as avg_duration
            FROM workout_log
            WHERE user_id = :user_id
            AND DATE(logged_at) BETWEEN :start_date AND :end_date
        """)

        result = self.db.execute(workout_query, {
            "user_id": user_id,
            "start_date": start_date,
            "end_date": end_date
        })
        row = result.fetchone()

        data["workouts"] = {
            "count": row.workout_count or 0,
            "total_minutes": row.total_minutes or 0,
            "avg_duration": row.avg_duration or 0
        }

        # Notes created
        notes_query = text("""
            SELECT COUNT(*) as note_count
            FROM note
            WHERE user_id = :user_id
            AND DATE(created_at) BETWEEN :start_date AND :end_date
        """)

        result = self.db.execute(notes_query, {
            "user_id": user_id,
            "start_date": start_date,
            "end_date": end_date
        })
        row = result.fetchone()

        data["notes"] = {
            "count": row.note_count or 0
        }

        # Recovery logs
        recovery_query = text("""
            SELECT
                AVG(sleep_hours) as avg_sleep,
                AVG(hrv) as avg_hrv,
                AVG(soreness_level) as avg_soreness
            FROM daily_recovery_log
            WHERE user_id = :user_id
            AND DATE(logged_at) BETWEEN :start_date AND :end_date
        """)

        result = self.db.execute(recovery_query, {
            "user_id": user_id,
            "start_date": start_date,
            "end_date": end_date
        })
        row = result.fetchone()

        data["recovery"] = {
            "avg_sleep": round(row.avg_sleep, 1) if row.avg_sleep else None,
            "avg_hrv": round(row.avg_hrv, 0) if row.avg_hrv else None,
            "avg_soreness": round(row.avg_soreness, 1) if row.avg_soreness else None
        }

        # Food logs
        food_query = text("""
            SELECT COUNT(*) as meal_count
            FROM food_log
            WHERE user_id = :user_id
            AND DATE(logged_at) BETWEEN :start_date AND :end_date
        """)

        result = self.db.execute(food_query, {
            "user_id": user_id,
            "start_date": start_date,
            "end_date": end_date
        })
        row = result.fetchone()

        data["nutrition"] = {
            "meal_count": row.meal_count or 0
        }

        # Calendar events
        events_query = text("""
            SELECT COUNT(*) as event_count
            FROM calendar_event
            WHERE user_id = :user_id
            AND DATE(starts_at) BETWEEN :start_date AND :end_date
        """)

        result = self.db.execute(events_query, {
            "user_id": user_id,
            "start_date": start_date,
            "end_date": end_date
        })
        row = result.fetchone()

        data["calendar"] = {
            "event_count": row.event_count or 0
        }

        return data

    async def _aggregate_monthly_data(
        self,
        user_id: str,
        start_date: date,
        end_date: date
    ) -> Dict[str, Any]:
        """Aggregate monthly data (same structure as weekly, different timeframe)"""
        return await self._aggregate_weekly_data(user_id, start_date, end_date)

    async def _aggregate_quarterly_data(
        self,
        user_id: str,
        start_date: date,
        end_date: date
    ) -> Dict[str, Any]:
        """Aggregate quarterly data (same structure as weekly, different timeframe)"""
        return await self._aggregate_weekly_data(user_id, start_date, end_date)

    async def _detect_weekly_patterns(
        self,
        user_id: str,
        report_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Detect patterns in weekly data"""
        patterns = []

        # Workout consistency pattern
        workout_count = report_data.get("workouts", {}).get("count", 0)
        if workout_count >= 5:
            patterns.append({
                "type": "workout_consistency",
                "description": f"Strong workout consistency: {workout_count} sessions",
                "severity": "positive"
            })
        elif workout_count <= 2:
            patterns.append({
                "type": "workout_decline",
                "description": f"Low workout frequency: {workout_count} sessions",
                "severity": "warning"
            })

        # Sleep pattern
        avg_sleep = report_data.get("recovery", {}).get("avg_sleep")
        if avg_sleep:
            if avg_sleep >= 8:
                patterns.append({
                    "type": "excellent_sleep",
                    "description": f"Excellent sleep: {avg_sleep}h average",
                    "severity": "positive"
                })
            elif avg_sleep < 6:
                patterns.append({
                    "type": "sleep_deficit",
                    "description": f"Sleep deficit: {avg_sleep}h average",
                    "severity": "warning"
                })

        return patterns

    async def _detect_monthly_patterns(
        self,
        user_id: str,
        report_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Detect patterns in monthly data"""
        return await self._detect_weekly_patterns(user_id, report_data)

    async def _detect_quarterly_patterns(
        self,
        user_id: str,
        report_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Detect patterns in quarterly data"""
        return await self._detect_weekly_patterns(user_id, report_data)

    async def _generate_llm_insights(
        self,
        user_id: str,
        report_type: str,
        report_data: Dict[str, Any],
        patterns: List[Dict[str, Any]]
    ) -> tuple[str, List[str], List[str]]:
        """Generate insights using LLM"""
        try:
            prompt = f"""Analyze this {report_type} data and provide insights:

Data:
{json.dumps(report_data, indent=2)}

Patterns Detected:
{json.dumps(patterns, indent=2)}

Please provide:
1. A brief summary (2-3 sentences)
2. Top 3 key insights
3. Top 3 actionable recommendations

Format as JSON:
{{
  "summary": "...",
  "insights": ["...", "...", "..."],
  "recommendations": ["...", "...", "..."]
}}
"""

            response = await self.llm_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=500
            )

            result = json.loads(response["choices"][0]["message"]["content"])

            return (
                result.get("summary", ""),
                result.get("insights", []),
                result.get("recommendations", [])
            )

        except Exception as e:
            logger.error(f"Error generating LLM insights: {e}")
            return self._generate_fallback_insights(report_type, report_data, patterns)

    def _generate_fallback_insights(
        self,
        report_type: str,
        report_data: Dict[str, Any],
        patterns: List[Dict[str, Any]]
    ) -> tuple[str, List[str], List[str]]:
        """Generate basic insights without LLM"""
        workout_count = report_data.get("workouts", {}).get("count", 0)
        avg_sleep = report_data.get("recovery", {}).get("avg_sleep")

        summary = f"This {report_type} you completed {workout_count} workouts"
        if avg_sleep:
            summary += f" and averaged {avg_sleep}h of sleep"

        insights = []
        recommendations = []

        # Basic insights from patterns
        for pattern in patterns:
            if pattern["severity"] == "positive":
                insights.append(pattern["description"])
            else:
                recommendations.append(f"Address: {pattern['description']}")

        return summary, insights, recommendations

    async def _save_report(self, report: IntelligenceReport) -> int:
        """Save report to database"""
        try:
            insert_query = text("""
                INSERT INTO intelligence_report (
                    user_id, report_type, period_start, period_end,
                    report_data, summary, insights, patterns,
                    recommendations, generation_time_ms
                )
                VALUES (
                    :user_id, :report_type, :period_start, :period_end,
                    :report_data, :summary, :insights, :patterns,
                    :recommendations, :generation_time_ms
                )
                RETURNING id
            """)

            result = self.db.execute(insert_query, {
                "user_id": report.user_id,
                "report_type": report.report_type,
                "period_start": report.period_start,
                "period_end": report.period_end,
                "report_data": json.dumps(report.report_data),
                "summary": report.summary,
                "insights": json.dumps(report.insights),
                "patterns": json.dumps(report.patterns),
                "recommendations": json.dumps(report.recommendations),
                "generation_time_ms": report.generation_time_ms
            })

            self.db.commit()

            report_id = result.fetchone()[0]
            report.id = report_id

            logger.info(f"💾 Report saved with ID {report_id}")

            return report_id

        except Exception as e:
            logger.error(f"Error saving report: {e}")
            self.db.rollback()
            raise

    async def get_report(
        self,
        user_id: str,
        report_type: str,
        period_start: date
    ) -> Optional[IntelligenceReport]:
        """Retrieve existing report"""
        try:
            query = text("""
                SELECT
                    id, user_id, report_type, period_start, period_end,
                    report_data, summary, insights, patterns,
                    recommendations, generation_time_ms, created_at, delivered_at
                FROM intelligence_report
                WHERE user_id = :user_id
                AND report_type = :report_type
                AND period_start = :period_start
            """)

            result = self.db.execute(query, {
                "user_id": user_id,
                "report_type": report_type,
                "period_start": period_start
            })

            row = result.fetchone()

            if not row:
                return None

            return IntelligenceReport(
                id=row.id,
                user_id=row.user_id,
                report_type=row.report_type,
                period_start=row.period_start,
                period_end=row.period_end,
                report_data=json.loads(row.report_data) if isinstance(row.report_data, str) else row.report_data,
                summary=row.summary,
                insights=json.loads(row.insights) if isinstance(row.insights, str) else row.insights,
                patterns=json.loads(row.patterns) if isinstance(row.patterns, str) else row.patterns,
                recommendations=json.loads(row.recommendations) if isinstance(row.recommendations, str) else row.recommendations,
                generation_time_ms=row.generation_time_ms,
                created_at=row.created_at,
                delivered_at=row.delivered_at
            )

        except Exception as e:
            logger.error(f"Error retrieving report: {e}")
            return None


def get_temporal_intelligence(db: Session, llm_client=None) -> TemporalIntelligenceEngine:
    """Get temporal intelligence engine instance"""
    return TemporalIntelligenceEngine(db, llm_client)
