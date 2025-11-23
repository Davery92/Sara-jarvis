"""
Daily Briefing Service
Morning and evening briefings with personalized insights
"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, date, time as dt_time, timedelta
from pydantic import BaseModel
import json
import logging

logger = logging.getLogger(__name__)


class DailyBriefing(BaseModel):
    """Daily briefing model"""
    id: Optional[int] = None
    user_id: str
    briefing_type: str  # morning, evening
    briefing_date: date
    content: str  # Markdown-formatted
    data: Dict[str, Any] = {}
    delivered: bool = False
    delivered_at: Optional[datetime] = None
    delivery_method: Optional[str] = None
    read: bool = False
    read_at: Optional[datetime] = None
    generation_time_ms: Optional[int] = None
    created_at: Optional[datetime] = None


class BriefingSettings(BaseModel):
    """User briefing settings"""
    id: Optional[int] = None
    user_id: str
    morning_enabled: bool = True
    morning_time: dt_time = dt_time(7, 0)
    evening_enabled: bool = True
    evening_time: dt_time = dt_time(21, 0)
    delivery_methods: List[str] = ["push"]
    include_weather: bool = False
    include_calendar: bool = True
    include_goals: bool = True
    include_suggestions: bool = True
    updated_at: Optional[datetime] = None


class DailyBriefingService:
    """Generates and delivers daily briefings"""

    def __init__(self, db: Session, llm_client=None):
        self.db = db
        self.llm_client = llm_client

    async def generate_morning_briefing(
        self,
        user_id: str,
        briefing_date: Optional[date] = None
    ) -> DailyBriefing:
        """
        Generate morning briefing

        Includes:
        - Recovery status (sleep, HRV, soreness)
        - Today's schedule
        - Active goals
        - Weather (optional)
        - Nutrition reminders
        - Workout recommendation
        """
        start_time = datetime.utcnow()

        if briefing_date is None:
            briefing_date = date.today()

        logger.info(f"🌅 Generating morning briefing for {user_id} on {briefing_date}")

        # Get settings
        settings = await self._get_settings(user_id)

        # Gather data
        data = {}

        # Recovery status
        recovery = await self._get_recovery_status(user_id)
        if recovery:
            data["recovery"] = recovery

        # Today's schedule
        if settings.include_calendar:
            schedule = await self._get_today_schedule(user_id, briefing_date)
            data["schedule"] = schedule

        # Active goals
        if settings.include_goals:
            goals = await self._get_active_goals(user_id)
            data["goals"] = goals

        # Proactive suggestions
        if settings.include_suggestions:
            suggestions = await self._get_active_suggestions(user_id)
            data["suggestions"] = suggestions

        # Weather (if enabled)
        if settings.include_weather:
            # Placeholder - would integrate with weather API
            data["weather"] = {"condition": "sunny", "temp": 72}

        # Workout recommendation
        workout_rec = await self._get_workout_recommendation(user_id)
        if workout_rec:
            data["workout_recommendation"] = workout_rec

        # Generate markdown content
        content = await self._format_morning_briefing(user_id, data)

        # Calculate generation time
        generation_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        # Create briefing
        briefing = DailyBriefing(
            user_id=user_id,
            briefing_type="morning",
            briefing_date=briefing_date,
            content=content,
            data=data,
            generation_time_ms=generation_time_ms
        )

        # Save to database
        await self._save_briefing(briefing)

        logger.info(f"✅ Morning briefing generated in {generation_time_ms}ms")

        return briefing

    async def generate_evening_briefing(
        self,
        user_id: str,
        briefing_date: Optional[date] = None
    ) -> DailyBriefing:
        """
        Generate evening briefing

        Includes:
        - Today's accomplishments
        - Tomorrow's prep
        - Insights and patterns
        - Reflection prompt
        """
        start_time = datetime.utcnow()

        if briefing_date is None:
            briefing_date = date.today()

        logger.info(f"🌙 Generating evening briefing for {user_id} on {briefing_date}")

        # Get settings
        settings = await self._get_settings(user_id)

        # Gather data
        data = {}

        # Today's accomplishments
        accomplishments = await self._get_today_accomplishments(user_id, briefing_date)
        data["accomplishments"] = accomplishments

        # Tomorrow's schedule
        if settings.include_calendar:
            tomorrow = briefing_date + timedelta(days=1)
            tomorrow_schedule = await self._get_today_schedule(user_id, tomorrow)
            data["tomorrow_schedule"] = tomorrow_schedule

        # Insights and patterns
        insights = await self._get_recent_insights(user_id)
        data["insights"] = insights

        # Goal progress
        if settings.include_goals:
            goal_progress = await self._get_goal_progress_summary(user_id)
            data["goal_progress"] = goal_progress

        # Generate markdown content
        content = await self._format_evening_briefing(user_id, data)

        # Calculate generation time
        generation_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        # Create briefing
        briefing = DailyBriefing(
            user_id=user_id,
            briefing_type="evening",
            briefing_date=briefing_date,
            content=content,
            data=data,
            generation_time_ms=generation_time_ms
        )

        # Save to database
        await self._save_briefing(briefing)

        logger.info(f"✅ Evening briefing generated in {generation_time_ms}ms")

        return briefing

    async def _get_recovery_status(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get latest recovery data"""
        try:
            query = text("""
                SELECT
                    sleep_hours, hrv, heart_rate, soreness_level,
                    body_weight, notes
                FROM daily_recovery_log
                WHERE user_id = :user_id
                ORDER BY logged_at DESC
                LIMIT 1
            """)

            result = self.db.execute(query, {"user_id": user_id})
            row = result.fetchone()

            if not row:
                return None

            return {
                "sleep_hours": row.sleep_hours,
                "hrv": row.hrv,
                "heart_rate": row.heart_rate,
                "soreness_level": row.soreness_level,
                "body_weight": row.body_weight,
                "notes": row.notes
            }

        except Exception as e:
            logger.error(f"Error getting recovery status: {e}")
            return None

    async def _get_today_schedule(self, user_id: str, target_date: date) -> List[Dict[str, Any]]:
        """Get calendar events for specific date"""
        try:
            query = text("""
                SELECT
                    id, title, description, starts_at, ends_at, location
                FROM calendar_event
                WHERE user_id = :user_id
                AND DATE(starts_at) = :target_date
                ORDER BY starts_at
            """)

            result = self.db.execute(query, {
                "user_id": user_id,
                "target_date": target_date
            })

            events = []
            for row in result.fetchall():
                events.append({
                    "id": row.id,
                    "title": row.title,
                    "description": row.description,
                    "starts_at": row.starts_at.isoformat() if row.starts_at else None,
                    "ends_at": row.ends_at.isoformat() if row.ends_at else None,
                    "location": row.location
                })

            return events

        except Exception as e:
            logger.error(f"Error getting schedule: {e}")
            return []

    async def _get_active_goals(self, user_id: str) -> List[Dict[str, Any]]:
        """Get active goals with progress"""
        try:
            query = text("""
                SELECT
                    id, title, goal_type, target_value, current_value,
                    unit, target_date, priority
                FROM goal
                WHERE user_id = :user_id
                AND status = 'active'
                ORDER BY priority DESC
                LIMIT 5
            """)

            result = self.db.execute(query, {"user_id": user_id})

            goals = []
            for row in result.fetchall():
                percentage = None
                if row.target_value and row.target_value > 0:
                    current = row.current_value or 0
                    percentage = min(100, (current / row.target_value) * 100)

                goals.append({
                    "id": row.id,
                    "title": row.title,
                    "goal_type": row.goal_type,
                    "target_value": row.target_value,
                    "current_value": row.current_value,
                    "unit": row.unit,
                    "target_date": row.target_date.isoformat() if row.target_date else None,
                    "percentage": round(percentage, 1) if percentage else None
                })

            return goals

        except Exception as e:
            logger.error(f"Error getting active goals: {e}")
            return []

    async def _get_active_suggestions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get active proactive suggestions"""
        try:
            query = text("""
                SELECT
                    id, suggestion_type, title, description, priority
                FROM proactive_suggestion
                WHERE user_id = :user_id
                AND status = 'pending'
                AND (expires_at IS NULL OR expires_at > NOW())
                ORDER BY priority DESC
                LIMIT 3
            """)

            result = self.db.execute(query, {"user_id": user_id})

            suggestions = []
            for row in result.fetchall():
                suggestions.append({
                    "id": row.id,
                    "type": row.suggestion_type,
                    "title": row.title,
                    "description": row.description
                })

            return suggestions

        except Exception as e:
            logger.error(f"Error getting suggestions: {e}")
            return []

    async def _get_workout_recommendation(self, user_id: str) -> Optional[str]:
        """Get workout recommendation based on recovery and schedule"""
        try:
            # Check recovery status
            recovery = await self._get_recovery_status(user_id)
            if not recovery:
                return None

            hrv = recovery.get("hrv")
            soreness = recovery.get("soreness_level")
            sleep = recovery.get("sleep_hours")

            # Simple recommendation logic
            if sleep and sleep < 6:
                return "Light recovery work recommended (low sleep)"
            elif soreness and soreness >= 7:
                return "Active recovery or rest day (high soreness)"
            elif hrv and hrv < 50:
                return "Low-intensity workout (low HRV)"
            else:
                return "You're recovered - ready for training!"

        except Exception as e:
            logger.error(f"Error getting workout recommendation: {e}")
            return None

    async def _get_today_accomplishments(
        self,
        user_id: str,
        target_date: date
    ) -> Dict[str, Any]:
        """Get today's accomplishments"""
        try:
            accomplishments = {}

            # Workouts completed
            workout_query = text("""
                SELECT COUNT(*) as count
                FROM workout_log
                WHERE user_id = :user_id
                AND DATE(logged_at) = :target_date
            """)
            result = self.db.execute(workout_query, {
                "user_id": user_id,
                "target_date": target_date
            })
            row = result.fetchone()
            accomplishments["workouts"] = row.count if row else 0

            # Meals logged
            meal_query = text("""
                SELECT COUNT(*) as count
                FROM food_log
                WHERE user_id = :user_id
                AND DATE(logged_at) = :target_date
            """)
            result = self.db.execute(meal_query, {
                "user_id": user_id,
                "target_date": target_date
            })
            row = result.fetchone()
            accomplishments["meals"] = row.count if row else 0

            # Notes created
            note_query = text("""
                SELECT COUNT(*) as count
                FROM note
                WHERE user_id = :user_id
                AND DATE(created_at) = :target_date
            """)
            result = self.db.execute(note_query, {
                "user_id": user_id,
                "target_date": target_date
            })
            row = result.fetchone()
            accomplishments["notes"] = row.count if row else 0

            return accomplishments

        except Exception as e:
            logger.error(f"Error getting accomplishments: {e}")
            return {}

    async def _get_recent_insights(self, user_id: str) -> List[str]:
        """Get recent insights from reports"""
        try:
            query = text("""
                SELECT insights
                FROM intelligence_report
                WHERE user_id = :user_id
                AND report_type = 'weekly'
                ORDER BY period_start DESC
                LIMIT 1
            """)

            result = self.db.execute(query, {"user_id": user_id})
            row = result.fetchone()

            if not row:
                return []

            insights = json.loads(row.insights) if isinstance(row.insights, str) else row.insights
            return insights[:3]  # Top 3 insights

        except Exception as e:
            logger.error(f"Error getting insights: {e}")
            return []

    async def _get_goal_progress_summary(self, user_id: str) -> List[Dict[str, Any]]:
        """Get goal progress for today"""
        try:
            query = text("""
                SELECT
                    g.title,
                    COUNT(gp.id) as progress_count
                FROM goal g
                LEFT JOIN goal_progress gp ON g.id = gp.goal_id
                    AND DATE(gp.logged_at) = CURRENT_DATE
                WHERE g.user_id = :user_id
                AND g.status = 'active'
                GROUP BY g.id, g.title
                HAVING COUNT(gp.id) > 0
            """)

            result = self.db.execute(query, {"user_id": user_id})

            progress = []
            for row in result.fetchall():
                progress.append({
                    "goal": row.title,
                    "updates": row.progress_count
                })

            return progress

        except Exception as e:
            logger.error(f"Error getting goal progress: {e}")
            return []

    async def _format_morning_briefing(
        self,
        user_id: str,
        data: Dict[str, Any]
    ) -> str:
        """Format morning briefing as markdown"""
        lines = ["# 🌅 Good Morning!", ""]

        # Recovery section
        recovery = data.get("recovery")
        if recovery:
            lines.append("## 💪 Recovery Status")
            if recovery.get("sleep_hours"):
                lines.append(f"- Sleep: {recovery['sleep_hours']}h")
            if recovery.get("hrv"):
                lines.append(f"- HRV: {recovery['hrv']}")
            if recovery.get("soreness_level"):
                lines.append(f"- Soreness: {recovery['soreness_level']}/10")
            lines.append("")

        # Workout recommendation
        workout_rec = data.get("workout_recommendation")
        if workout_rec:
            lines.append(f"**Today's Training:** {workout_rec}")
            lines.append("")

        # Schedule
        schedule = data.get("schedule", [])
        if schedule:
            lines.append("## 📅 Today's Schedule")
            for event in schedule:
                start = datetime.fromisoformat(event["starts_at"])
                lines.append(f"- {start.strftime('%I:%M %p')}: {event['title']}")
            lines.append("")

        # Goals
        goals = data.get("goals", [])
        if goals:
            lines.append("## 🎯 Active Goals")
            for goal in goals[:3]:
                if goal.get("percentage"):
                    lines.append(f"- {goal['title']}: {goal['percentage']}%")
                else:
                    lines.append(f"- {goal['title']}")
            lines.append("")

        # Suggestions
        suggestions = data.get("suggestions", [])
        if suggestions:
            lines.append("## 💡 Suggestions")
            for suggestion in suggestions:
                lines.append(f"- {suggestion['title']}")
            lines.append("")

        lines.append("Have a great day! 🚀")

        return "\n".join(lines)

    async def _format_evening_briefing(
        self,
        user_id: str,
        data: Dict[str, Any]
    ) -> str:
        """Format evening briefing as markdown"""
        lines = ["# 🌙 Evening Recap", ""]

        # Accomplishments
        accomplishments = data.get("accomplishments", {})
        if accomplishments:
            lines.append("## ✅ Today's Accomplishments")
            if accomplishments.get("workouts", 0) > 0:
                lines.append(f"- {accomplishments['workouts']} workout(s) completed")
            if accomplishments.get("meals", 0) > 0:
                lines.append(f"- {accomplishments['meals']} meal(s) logged")
            if accomplishments.get("notes", 0) > 0:
                lines.append(f"- {accomplishments['notes']} note(s) created")
            lines.append("")

        # Goal progress
        goal_progress = data.get("goal_progress", [])
        if goal_progress:
            lines.append("## 🎯 Goal Progress")
            for progress in goal_progress:
                lines.append(f"- {progress['goal']}: {progress['updates']} update(s)")
            lines.append("")

        # Insights
        insights = data.get("insights", [])
        if insights:
            lines.append("## 💭 Insights")
            for insight in insights:
                lines.append(f"- {insight}")
            lines.append("")

        # Tomorrow's prep
        tomorrow_schedule = data.get("tomorrow_schedule", [])
        if tomorrow_schedule:
            lines.append("## 📅 Tomorrow's Preview")
            for event in tomorrow_schedule[:3]:
                start = datetime.fromisoformat(event["starts_at"])
                lines.append(f"- {start.strftime('%I:%M %p')}: {event['title']}")
            lines.append("")

        lines.append("## 🤔 Reflection")
        lines.append("What's one thing you're grateful for today?")
        lines.append("")
        lines.append("Rest well! 😴")

        return "\n".join(lines)

    async def _save_briefing(self, briefing: DailyBriefing) -> int:
        """Save briefing to database"""
        try:
            query = text("""
                INSERT INTO daily_briefing (
                    user_id, briefing_type, briefing_date,
                    content, data, generation_time_ms
                )
                VALUES (
                    :user_id, :briefing_type, :briefing_date,
                    :content, :data, :generation_time_ms
                )
                ON CONFLICT (user_id, briefing_date, briefing_type)
                DO UPDATE SET
                    content = EXCLUDED.content,
                    data = EXCLUDED.data,
                    generation_time_ms = EXCLUDED.generation_time_ms
                RETURNING id
            """)

            result = self.db.execute(query, {
                "user_id": briefing.user_id,
                "briefing_type": briefing.briefing_type,
                "briefing_date": briefing.briefing_date,
                "content": briefing.content,
                "data": json.dumps(briefing.data),
                "generation_time_ms": briefing.generation_time_ms
            })

            self.db.commit()

            briefing_id = result.fetchone()[0]
            briefing.id = briefing_id

            logger.info(f"💾 Briefing saved: {briefing_id}")

            return briefing_id

        except Exception as e:
            logger.error(f"Error saving briefing: {e}")
            self.db.rollback()
            raise

    async def _get_settings(self, user_id: str) -> BriefingSettings:
        """Get user briefing settings"""
        try:
            query = text("""
                SELECT
                    id, user_id, morning_enabled, morning_time,
                    evening_enabled, evening_time, delivery_methods,
                    include_weather, include_calendar, include_goals,
                    include_suggestions, updated_at
                FROM briefing_settings
                WHERE user_id = :user_id
            """)

            result = self.db.execute(query, {"user_id": user_id})
            row = result.fetchone()

            if row:
                delivery_methods = json.loads(row.delivery_methods) if isinstance(row.delivery_methods, str) else row.delivery_methods

                return BriefingSettings(
                    id=row.id,
                    user_id=row.user_id,
                    morning_enabled=row.morning_enabled,
                    morning_time=row.morning_time,
                    evening_enabled=row.evening_enabled,
                    evening_time=row.evening_time,
                    delivery_methods=delivery_methods,
                    include_weather=row.include_weather,
                    include_calendar=row.include_calendar,
                    include_goals=row.include_goals,
                    include_suggestions=row.include_suggestions,
                    updated_at=row.updated_at
                )
            else:
                # Return defaults
                return BriefingSettings(user_id=user_id)

        except Exception as e:
            logger.error(f"Error getting settings: {e}")
            return BriefingSettings(user_id=user_id)

    async def mark_as_delivered(
        self,
        briefing_id: int,
        delivery_method: str
    ) -> bool:
        """Mark briefing as delivered"""
        try:
            query = text("""
                UPDATE daily_briefing
                SET
                    delivered = true,
                    delivered_at = NOW(),
                    delivery_method = :delivery_method
                WHERE id = :briefing_id
            """)

            self.db.execute(query, {
                "briefing_id": briefing_id,
                "delivery_method": delivery_method
            })
            self.db.commit()

            return True

        except Exception as e:
            logger.error(f"Error marking as delivered: {e}")
            self.db.rollback()
            return False


def get_daily_briefing_service(db: Session, llm_client=None) -> DailyBriefingService:
    """Get daily briefing service instance"""
    return DailyBriefingService(db, llm_client)
