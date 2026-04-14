"""
Day Replay Builder for Sara's Dream Cycle.

Like the human brain replaying the day's events during sleep,
this service aggregates ALL of Sara's data sources into a
comprehensive narrative of what happened during a day.

Data sources include:
- Conversations (episodes)
- Automations executed
- Fitness (workouts, food logs, recovery)
- Calendar events
- Emails analyzed
- Research/learning sessions
- Karma events
- Home automation actions
"""

import logging
import json
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


class DataSource(str, Enum):
    """Data sources included in the replay."""
    EPISODES = "episodes"
    AUTOMATIONS = "automations"
    FITNESS_WORKOUTS = "fitness_workouts"
    FITNESS_FOOD = "fitness_food"
    FITNESS_RECOVERY = "fitness_recovery"
    CALENDAR = "calendar"
    EMAIL = "email"
    RESEARCH = "research"
    LEARNING = "learning"
    TIMERS = "timers"
    REMINDERS = "reminders"


@dataclass
class DayReplayEvent:
    """A single event in the day replay."""
    timestamp: datetime
    source: DataSource
    event_type: str
    summary: str
    details: Dict[str, Any]
    importance: float  # 0-1


@dataclass
class DayReplay:
    """Complete replay of a day's events."""
    user_id: str
    replay_date: date
    events: List[DayReplayEvent]
    summary: Dict[str, Any]
    data_sources_included: List[str]
    total_events: int
    created_at: datetime


class DayReplayBuilder:
    """
    Builds a comprehensive replay of a day's events.

    This is the "memory consolidation" that happens during Sara's dream cycle,
    aggregating all interactions and events into a coherent narrative.
    """

    async def build_replay(
        self,
        db: Session,
        user_id: str,
        replay_date: date
    ) -> DayReplay:
        """
        Build a complete replay of the specified day.

        Args:
            db: Database session
            user_id: User to build replay for
            replay_date: The day to replay

        Returns:
            DayReplay with all events and summary
        """
        logger.info(f"Building day replay for {user_id} on {replay_date}")

        events: List[DayReplayEvent] = []
        sources_included: List[str] = []

        # Calculate date range (start of day to end of day)
        day_start = datetime.combine(replay_date, datetime.min.time())
        day_end = datetime.combine(replay_date, datetime.max.time())

        # Gather events from all sources
        episode_events = await self._get_episode_events(db, user_id, day_start, day_end)
        if episode_events:
            events.extend(episode_events)
            sources_included.append(DataSource.EPISODES.value)

        automation_events = await self._get_automation_events(db, user_id, day_start, day_end)
        if automation_events:
            events.extend(automation_events)
            sources_included.append(DataSource.AUTOMATIONS.value)

        workout_events = await self._get_workout_events(db, user_id, day_start, day_end)
        if workout_events:
            events.extend(workout_events)
            sources_included.append(DataSource.FITNESS_WORKOUTS.value)

        food_events = await self._get_food_events(db, user_id, day_start, day_end)
        if food_events:
            events.extend(food_events)
            sources_included.append(DataSource.FITNESS_FOOD.value)

        recovery_events = await self._get_recovery_events(db, user_id, replay_date)
        if recovery_events:
            events.extend(recovery_events)
            sources_included.append(DataSource.FITNESS_RECOVERY.value)

        calendar_events = await self._get_calendar_events(db, user_id, day_start, day_end)
        if calendar_events:
            events.extend(calendar_events)
            sources_included.append(DataSource.CALENDAR.value)

        email_events = await self._get_email_events(db, user_id, day_start, day_end)
        if email_events:
            events.extend(email_events)
            sources_included.append(DataSource.EMAIL.value)

        research_events = await self._get_research_events(db, user_id, day_start, day_end)
        if research_events:
            events.extend(research_events)
            sources_included.append(DataSource.RESEARCH.value)

        learning_events = await self._get_learning_events(db, user_id, day_start, day_end)
        if learning_events:
            events.extend(learning_events)
            sources_included.append(DataSource.LEARNING.value)

        timer_events = await self._get_timer_events(db, user_id, day_start, day_end)
        if timer_events:
            events.extend(timer_events)
            sources_included.append(DataSource.TIMERS.value)

        reminder_events = await self._get_reminder_events(db, user_id, day_start, day_end)
        if reminder_events:
            events.extend(reminder_events)
            sources_included.append(DataSource.REMINDERS.value)

        # Sort all events chronologically
        events.sort(key=lambda e: e.timestamp)

        # Build summary statistics
        summary = self._build_summary(events, sources_included)

        replay = DayReplay(
            user_id=user_id,
            replay_date=replay_date,
            events=events,
            summary=summary,
            data_sources_included=sources_included,
            total_events=len(events),
            created_at=datetime.utcnow()
        )

        logger.info(
            f"Day replay complete: {len(events)} events from {len(sources_included)} sources"
        )

        return replay

    async def _get_episode_events(
        self,
        db: Session,
        user_id: str,
        day_start: datetime,
        day_end: datetime
    ) -> List[DayReplayEvent]:
        """Get conversation episodes for the day."""
        events = []
        try:
            result = db.execute(
                text("""
                    SELECT id, role, content, importance, conversation_id, created_at
                    FROM episode
                    WHERE user_id = :user_id
                      AND created_at BETWEEN :day_start AND :day_end
                    ORDER BY created_at
                """),
                {"user_id": user_id, "day_start": day_start, "day_end": day_end}
            ).fetchall()

            # Group by conversation for summary
            conversations = {}
            for row in result:
                conv_id = row.conversation_id or "unknown"
                if conv_id not in conversations:
                    conversations[conv_id] = {"messages": [], "start": row.created_at}
                conversations[conv_id]["messages"].append({
                    "role": row.role,
                    "content": row.content[:200] if row.content else "",
                    "importance": row.importance
                })
                conversations[conv_id]["end"] = row.created_at

            for conv_id, conv_data in conversations.items():
                user_messages = [m for m in conv_data["messages"] if m["role"] == "user"]
                events.append(DayReplayEvent(
                    timestamp=conv_data["start"],
                    source=DataSource.EPISODES,
                    event_type="conversation",
                    summary=f"Conversation with {len(conv_data['messages'])} messages",
                    details={
                        "conversation_id": conv_id,
                        "message_count": len(conv_data["messages"]),
                        "user_message_count": len(user_messages),
                        "duration_minutes": (conv_data["end"] - conv_data["start"]).seconds // 60,
                        "sample_topics": [m["content"][:50] for m in user_messages[:3]]
                    },
                    importance=max((m["importance"] or 0.5) for m in conv_data["messages"])
                ))

        except Exception as e:
            logger.warning(f"Failed to get episode events: {e}")

        return events

    async def _get_automation_events(
        self,
        db: Session,
        user_id: str,
        day_start: datetime,
        day_end: datetime
    ) -> List[DayReplayEvent]:
        """Get automation executions for the day."""
        events = []
        try:
            result = db.execute(
                text("""
                    SELECT el.id, el.started_at, el.completed_at, el.result, el.error,
                           at.name, at.description, at.trigger_type, at.action_type
                    FROM automation_execution_log el
                    JOIN automation_task at ON el.automation_id = at.id
                    WHERE at.user_id = :user_id
                      AND el.started_at BETWEEN :day_start AND :day_end
                    ORDER BY el.started_at
                """),
                {"user_id": user_id, "day_start": day_start, "day_end": day_end}
            ).fetchall()

            # Group by automation name to see patterns
            automation_runs = {}
            for row in result:
                name = row.name
                if name not in automation_runs:
                    automation_runs[name] = {
                        "count": 0,
                        "description": row.description,
                        "trigger_type": row.trigger_type,
                        "action_type": row.action_type,
                        "successful": 0,
                        "first_run": row.started_at,
                        "last_run": row.started_at
                    }
                automation_runs[name]["count"] += 1
                automation_runs[name]["last_run"] = row.started_at
                if not row.error:
                    automation_runs[name]["successful"] += 1

            for name, data in automation_runs.items():
                events.append(DayReplayEvent(
                    timestamp=data["first_run"],
                    source=DataSource.AUTOMATIONS,
                    event_type="automation_pattern",
                    summary=f"Automation '{name}' ran {data['count']} times",
                    details={
                        "automation_name": name,
                        "description": data["description"],
                        "trigger_type": data["trigger_type"],
                        "action_type": data["action_type"],
                        "run_count": data["count"],
                        "successful_runs": data["successful"],
                        "first_run": data["first_run"].isoformat(),
                        "last_run": data["last_run"].isoformat()
                    },
                    importance=0.7 if data["count"] > 1 else 0.5
                ))

        except Exception as e:
            logger.warning(f"Failed to get automation events: {e}")

        return events

    async def _get_workout_events(
        self,
        db: Session,
        user_id: str,
        day_start: datetime,
        day_end: datetime
    ) -> List[DayReplayEvent]:
        """Get workout sessions for the day."""
        events = []
        try:
            result = db.execute(
                text("""
                    SELECT id, workout_type, duration_minutes, notes,
                           started_at, completed_at, status
                    FROM workout_session
                    WHERE user_id = :user_id
                      AND session_date = :session_date
                """),
                {"user_id": user_id, "session_date": day_start.date()}
            ).fetchall()

            for row in result:
                if row.status == "completed":
                    events.append(DayReplayEvent(
                        timestamp=row.started_at or day_start,
                        source=DataSource.FITNESS_WORKOUTS,
                        event_type="workout_completed",
                        summary=f"Completed {row.workout_type} workout ({row.duration_minutes} min)",
                        details={
                            "workout_type": row.workout_type,
                            "duration_minutes": row.duration_minutes,
                            "notes": row.notes,
                            "status": row.status
                        },
                        importance=0.8
                    ))

        except Exception as e:
            logger.warning(f"Failed to get workout events: {e}")

        return events

    async def _get_food_events(
        self,
        db: Session,
        user_id: str,
        day_start: datetime,
        day_end: datetime
    ) -> List[DayReplayEvent]:
        """Get food log entries for the day."""
        events = []
        try:
            result = db.execute(
                text("""
                    SELECT id, meal_type, description, calories, protein, carbs, fat,
                           logged_at
                    FROM food_log
                    WHERE user_id = :user_id
                      AND logged_at BETWEEN :day_start AND :day_end
                    ORDER BY logged_at
                """),
                {"user_id": user_id, "day_start": day_start, "day_end": day_end}
            ).fetchall()

            total_calories = 0
            total_protein = 0
            meals_logged = []

            for row in result:
                total_calories += row.calories or 0
                total_protein += row.protein or 0
                meals_logged.append(row.meal_type)

                events.append(DayReplayEvent(
                    timestamp=row.logged_at,
                    source=DataSource.FITNESS_FOOD,
                    event_type="meal_logged",
                    summary=f"{row.meal_type}: {row.description[:50] if row.description else 'Logged'}",
                    details={
                        "meal_type": row.meal_type,
                        "description": row.description,
                        "calories": row.calories,
                        "protein": row.protein,
                        "carbs": row.carbs,
                        "fat": row.fat
                    },
                    importance=0.4
                ))

            # Add daily nutrition summary as high importance event
            if meals_logged:
                events.append(DayReplayEvent(
                    timestamp=day_end,
                    source=DataSource.FITNESS_FOOD,
                    event_type="nutrition_summary",
                    summary=f"Nutrition: {len(meals_logged)} meals, {total_calories} cal, {total_protein}g protein",
                    details={
                        "total_meals": len(meals_logged),
                        "total_calories": total_calories,
                        "total_protein": total_protein,
                        "meals": meals_logged
                    },
                    importance=0.6
                ))

        except Exception as e:
            logger.warning(f"Failed to get food events: {e}")

        return events

    async def _get_recovery_events(
        self,
        db: Session,
        user_id: str,
        replay_date: date
    ) -> List[DayReplayEvent]:
        """Get recovery/health metrics for the day."""
        events = []
        try:
            result = db.execute(
                text("""
                    SELECT hrv, resting_hr, sleep_hours, sleep_quality,
                           soreness_level, stress_level, energy_level,
                           created_at
                    FROM daily_recovery_log
                    WHERE user_id = :user_id
                      AND log_date = :log_date
                """),
                {"user_id": user_id, "log_date": replay_date}
            ).fetchone()

            if result:
                events.append(DayReplayEvent(
                    timestamp=result.created_at or datetime.combine(replay_date, datetime.min.time()),
                    source=DataSource.FITNESS_RECOVERY,
                    event_type="recovery_metrics",
                    summary=f"Recovery: {result.sleep_hours}h sleep, HRV {result.hrv}, energy {result.energy_level}/10",
                    details={
                        "hrv": result.hrv,
                        "resting_hr": result.resting_hr,
                        "sleep_hours": result.sleep_hours,
                        "sleep_quality": result.sleep_quality,
                        "soreness_level": result.soreness_level,
                        "stress_level": result.stress_level,
                        "energy_level": result.energy_level
                    },
                    importance=0.7
                ))

        except Exception as e:
            logger.warning(f"Failed to get recovery events: {e}")

        return events

    async def _get_calendar_events(
        self,
        db: Session,
        user_id: str,
        day_start: datetime,
        day_end: datetime
    ) -> List[DayReplayEvent]:
        """Get calendar events for the day."""
        events = []
        try:
            result = db.execute(
                text("""
                    SELECT id, title, description, location,
                           starts_at, ends_at, event_type
                    FROM event
                    WHERE user_id = :user_id
                      AND starts_at BETWEEN :day_start AND :day_end
                    ORDER BY starts_at
                """),
                {"user_id": user_id, "day_start": day_start, "day_end": day_end}
            ).fetchall()

            for row in result:
                duration = (row.ends_at - row.starts_at).seconds // 60 if row.ends_at else 0
                events.append(DayReplayEvent(
                    timestamp=row.starts_at,
                    source=DataSource.CALENDAR,
                    event_type="calendar_event",
                    summary=f"{row.title} ({duration} min)",
                    details={
                        "title": row.title,
                        "description": row.description,
                        "location": row.location,
                        "duration_minutes": duration,
                        "event_type": row.event_type
                    },
                    importance=0.6
                ))

        except Exception as e:
            logger.warning(f"Failed to get calendar events: {e}")

        return events

    async def _get_email_events(
        self,
        db: Session,
        user_id: str,
        day_start: datetime,
        day_end: datetime
    ) -> List[DayReplayEvent]:
        """Get email activity for the day."""
        events = []
        try:
            result = db.execute(
                text("""
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN importance_score >= 0.7 THEN 1 ELSE 0 END) as high_priority,
                           SUM(CASE WHEN is_read THEN 1 ELSE 0 END) as read_count
                    FROM email
                    WHERE user_id = :user_id
                      AND received_at BETWEEN :day_start AND :day_end
                """),
                {"user_id": user_id, "day_start": day_start, "day_end": day_end}
            ).fetchone()

            if result and result.total > 0:
                events.append(DayReplayEvent(
                    timestamp=day_end,
                    source=DataSource.EMAIL,
                    event_type="email_summary",
                    summary=f"Email: {result.total} received, {result.high_priority} high priority, {result.read_count} read",
                    details={
                        "total_received": result.total,
                        "high_priority": result.high_priority,
                        "read_count": result.read_count
                    },
                    importance=0.5
                ))

        except Exception as e:
            logger.warning(f"Failed to get email events: {e}")

        return events

    async def _get_research_events(
        self,
        db: Session,
        user_id: str,
        day_start: datetime,
        day_end: datetime
    ) -> List[DayReplayEvent]:
        """Get research job completions for the day."""
        events = []
        try:
            # Check for jarvis_task (background research tasks)
            result = db.execute(
                text("""
                    SELECT id, task_type, description, status, result_summary,
                           created_at, completed_at
                    FROM jarvis_task
                    WHERE user_id = :user_id
                      AND created_at BETWEEN :day_start AND :day_end
                    ORDER BY created_at
                """),
                {"user_id": user_id, "day_start": day_start, "day_end": day_end}
            ).fetchall()

            for row in result:
                events.append(DayReplayEvent(
                    timestamp=row.created_at,
                    source=DataSource.RESEARCH,
                    event_type="research_task",
                    summary=f"Research: {row.description[:50]}... ({row.status})",
                    details={
                        "task_type": row.task_type,
                        "description": row.description,
                        "status": row.status,
                        "result_summary": row.result_summary
                    },
                    importance=0.6
                ))

        except Exception as e:
            logger.warning(f"Failed to get research events: {e}")

        return events

    async def _get_learning_events(
        self,
        db: Session,
        user_id: str,
        day_start: datetime,
        day_end: datetime
    ) -> List[DayReplayEvent]:
        """Get learning session activity for the day."""
        events = []
        try:
            result = db.execute(
                text("""
                    SELECT ls.id, ls.session_type, ls.duration_minutes,
                           ls.started_at, ls.ended_at,
                           lt.name as topic_name
                    FROM learning_session ls
                    LEFT JOIN learning_topic lt ON ls.topic_id = lt.id
                    WHERE ls.user_id = :user_id
                      AND ls.started_at BETWEEN :day_start AND :day_end
                    ORDER BY ls.started_at
                """),
                {"user_id": user_id, "day_start": day_start, "day_end": day_end}
            ).fetchall()

            for row in result:
                events.append(DayReplayEvent(
                    timestamp=row.started_at,
                    source=DataSource.LEARNING,
                    event_type="learning_session",
                    summary=f"Learning: {row.topic_name or 'Unknown topic'} ({row.duration_minutes} min, {row.session_type})",
                    details={
                        "topic": row.topic_name,
                        "session_type": row.session_type,
                        "duration_minutes": row.duration_minutes
                    },
                    importance=0.6
                ))

        except Exception as e:
            logger.warning(f"Failed to get learning events: {e}")

        return events

    async def _get_timer_events(
        self,
        db: Session,
        user_id: str,
        day_start: datetime,
        day_end: datetime
    ) -> List[DayReplayEvent]:
        """Get timer usage for the day."""
        events = []
        try:
            result = db.execute(
                text("""
                    SELECT id, title, duration_minutes, start_time, end_time, status
                    FROM timer
                    WHERE user_id = :user_id
                      AND start_time BETWEEN :day_start AND :day_end
                    ORDER BY start_time
                """),
                {"user_id": user_id, "day_start": day_start, "day_end": day_end}
            ).fetchall()

            if result:
                events.append(DayReplayEvent(
                    timestamp=day_end,
                    source=DataSource.TIMERS,
                    event_type="timers_summary",
                    summary=f"Timers: {len(result)} used",
                    details={
                        "timer_count": len(result),
                        "timers": [{"title": r.title, "duration": r.duration_minutes} for r in result]
                    },
                    importance=0.3
                ))

        except Exception as e:
            logger.warning(f"Failed to get timer events: {e}")

        return events

    async def _get_reminder_events(
        self,
        db: Session,
        user_id: str,
        day_start: datetime,
        day_end: datetime
    ) -> List[DayReplayEvent]:
        """Get reminder completions for the day."""
        events = []
        try:
            result = db.execute(
                text("""
                    SELECT id, title, reminder_time, completed, completed_at
                    FROM reminder
                    WHERE user_id = :user_id
                      AND reminder_time BETWEEN :day_start AND :day_end
                    ORDER BY reminder_time
                """),
                {"user_id": user_id, "day_start": day_start, "day_end": day_end}
            ).fetchall()

            completed = [r for r in result if r.completed]

            if result:
                events.append(DayReplayEvent(
                    timestamp=day_end,
                    source=DataSource.REMINDERS,
                    event_type="reminders_summary",
                    summary=f"Reminders: {len(completed)}/{len(result)} completed",
                    details={
                        "total": len(result),
                        "completed": len(completed),
                        "reminders": [{"title": r.title, "completed": r.completed} for r in result]
                    },
                    importance=0.4
                ))

        except Exception as e:
            logger.warning(f"Failed to get reminder events: {e}")

        return events

    def _build_summary(
        self,
        events: List[DayReplayEvent],
        sources: List[str]
    ) -> Dict[str, Any]:
        """Build summary statistics from events."""
        summary = {
            "total_events": len(events),
            "sources_count": len(sources),
            "sources": sources,
            "by_source": {},
            "by_importance": {
                "high": 0,
                "medium": 0,
                "low": 0
            }
        }

        for event in events:
            # Count by source
            source = event.source.value
            if source not in summary["by_source"]:
                summary["by_source"][source] = 0
            summary["by_source"][source] += 1

            # Count by importance
            if event.importance >= 0.7:
                summary["by_importance"]["high"] += 1
            elif event.importance >= 0.4:
                summary["by_importance"]["medium"] += 1
            else:
                summary["by_importance"]["low"] += 1

        return summary

    async def cache_replay(
        self,
        db: Session,
        replay: DayReplay,
        summary_text: Optional[str] = None
    ) -> None:
        """Cache the replay for later use."""
        try:
            # Convert events to serializable format
            events_data = []
            for event in replay.events:
                events_data.append({
                    "timestamp": event.timestamp.isoformat(),
                    "source": event.source.value,
                    "event_type": event.event_type,
                    "summary": event.summary,
                    "details": event.details,
                    "importance": event.importance
                })

            replay_data = {
                "events": events_data,
                "summary": replay.summary
            }

            db.execute(
                text("""
                    INSERT INTO day_replay_cache (
                        user_id, replay_date, replay_data, summary,
                        data_sources, episode_count, automation_count, created_at
                    ) VALUES (
                        :user_id, :replay_date, :replay_data, :summary,
                        :data_sources, :episode_count, :automation_count, NOW()
                    )
                    ON CONFLICT (user_id, replay_date)
                    DO UPDATE SET
                        replay_data = :replay_data,
                        summary = :summary,
                        data_sources = :data_sources,
                        created_at = NOW()
                """),
                {
                    "user_id": replay.user_id,
                    "replay_date": replay.replay_date,
                    "replay_data": json.dumps(replay_data),
                    "summary": summary_text,
                    "data_sources": replay.data_sources_included,
                    "episode_count": replay.summary.get("by_source", {}).get("episodes", 0),
                    "automation_count": replay.summary.get("by_source", {}).get("automations", 0)
                }
            )
            db.commit()

            logger.info(f"Cached day replay for {replay.user_id} on {replay.replay_date}")

        except Exception as e:
            logger.error(f"Failed to cache replay: {e}")
            db.rollback()


# Singleton instance
day_replay_builder = DayReplayBuilder()
