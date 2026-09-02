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
from decimal import Decimal
from datetime import datetime, date, timezone
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.timezone import (
    USER_TIMEZONE,
    UTC as UTC_TZ,
    start_of_day,
    end_of_day,
    to_naive_utc,
)

logger = logging.getLogger(__name__)


def _json_default(value: Any) -> Any:
    """Coerce the types psycopg hands back from numeric/timestamp columns.

    ``daily_recovery_log`` (hrv, sleep_hours, body_weight) and other NUMERIC
    columns arrive as ``Decimal``, which json.dumps rejects. That raised inside
    cache_replay's try/except and silently dropped every day that had recovery
    data from the cache — found 2026-08-25 while wiring the diary.
    """
    if isinstance(value, Decimal):
        as_float = float(value)
        return int(as_float) if as_float.is_integer() else as_float
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, set):
        return sorted(value)
    return str(value)


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
    HOME = "home"


@dataclass(frozen=True)
class DayBounds:
    """One Eastern calendar day expressed in every storage convention the
    collectors below need — because they do NOT share one.

    Verified against the live schema 2026-08-25:

    * ``aware`` — ``timestamptz`` columns: ``automation_execution_log.started_at``,
      ``email.received_at``, ``learning_session.started_at``,
      ``workout_session.started_at``, ``daily_recovery_log.created_at``,
      ``home_activity_log.changed_at``, ``cardio_log.logged_at``,
      ``sara_journal.created_at``, ``notification_log.sent_at``.
    * ``utc_naive`` — ``timestamp without time zone`` columns holding UTC
      (PG ``now()`` on a UTC session, or aware datetimes coerced on insert):
      ``episode.created_at``, ``background_task.created_at``,
      ``timer.start_time``, ``reminder.reminder_time``, ``note.created_at``.
    * ``et_naive`` — ``timestamp without time zone`` columns holding ET
      wall-clock: ``food_log.logged_at`` (written via ``naive_local_now()``)
      and ``calendar_event.start_time`` (see calendar_prep.py). This is also
      the convention every emitted event timestamp is normalized to, so the
      merged timeline sorts correctly.

    Assuming one convention for all of them is what put an 11 PM chat on the
    wrong day and shuffled the merged event list by 4-5 hours.
    """
    replay_date: date
    aware_start: datetime
    aware_end: datetime
    utc_naive_start: datetime
    utc_naive_end: datetime
    et_naive_start: datetime
    et_naive_end: datetime


def day_bounds(replay_date: date) -> DayBounds:
    """Build every representation of ``replay_date`` as an Eastern calendar day."""
    aware_start = start_of_day(replay_date)
    aware_end = end_of_day(replay_date)
    return DayBounds(
        replay_date=replay_date,
        aware_start=aware_start,
        aware_end=aware_end,
        utc_naive_start=to_naive_utc(aware_start),
        utc_naive_end=to_naive_utc(aware_end),
        et_naive_start=aware_start.replace(tzinfo=None),
        et_naive_end=aware_end.replace(tzinfo=None),
    )


def utc_naive_to_et_naive(dt: Optional[datetime]) -> Optional[datetime]:
    """Reinterpret a naive-UTC column value as naive ET wall-clock."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    return dt.astimezone(USER_TIMEZONE).replace(tzinfo=None)


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

        # ET calendar-day bounds in every storage convention (see DayBounds).
        # This used to be a single naive datetime.combine() pair compared
        # against a mix of timestamptz, naive-UTC and naive-ET columns.
        bounds = day_bounds(replay_date)

        # Gather events from all sources
        episode_events = await self._get_episode_events(db, user_id, bounds)
        if episode_events:
            events.extend(episode_events)
            sources_included.append(DataSource.EPISODES.value)

        automation_events = await self._get_automation_events(db, user_id, bounds)
        if automation_events:
            events.extend(automation_events)
            sources_included.append(DataSource.AUTOMATIONS.value)

        workout_events = await self._get_workout_events(db, user_id, bounds)
        if workout_events:
            events.extend(workout_events)
            sources_included.append(DataSource.FITNESS_WORKOUTS.value)

        food_events = await self._get_food_events(db, user_id, bounds)
        if food_events:
            events.extend(food_events)
            sources_included.append(DataSource.FITNESS_FOOD.value)

        recovery_events = await self._get_recovery_events(db, user_id, bounds)
        if recovery_events:
            events.extend(recovery_events)
            sources_included.append(DataSource.FITNESS_RECOVERY.value)

        calendar_events = await self._get_calendar_events(db, user_id, bounds)
        if calendar_events:
            events.extend(calendar_events)
            sources_included.append(DataSource.CALENDAR.value)

        email_events = await self._get_email_events(db, user_id, bounds)
        if email_events:
            events.extend(email_events)
            sources_included.append(DataSource.EMAIL.value)

        research_events = await self._get_research_events(db, user_id, bounds)
        if research_events:
            events.extend(research_events)
            sources_included.append(DataSource.RESEARCH.value)

        learning_events = await self._get_learning_events(db, user_id, bounds)
        if learning_events:
            events.extend(learning_events)
            sources_included.append(DataSource.LEARNING.value)

        timer_events = await self._get_timer_events(db, user_id, bounds)
        if timer_events:
            events.extend(timer_events)
            sources_included.append(DataSource.TIMERS.value)

        reminder_events = await self._get_reminder_events(db, user_id, bounds)
        if reminder_events:
            events.extend(reminder_events)
            sources_included.append(DataSource.REMINDERS.value)

        home_events = await self._get_home_events(db, bounds)
        if home_events:
            events.extend(home_events)
            sources_included.append(DataSource.HOME.value)

        # Safety net: collectors already emit naive ET (naive-UTC columns are
        # converted at the source via utc_naive_to_et_naive), but timestamptz
        # rows arrive aware. Aware vs naive comparison breaks the sort.
        for event in events:
            if event.timestamp.tzinfo is not None:
                event.timestamp = event.timestamp.astimezone(USER_TIMEZONE).replace(tzinfo=None)

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
            created_at=datetime.now(timezone.utc)
        )

        logger.info(
            f"Day replay complete: {len(events)} events from {len(sources_included)} sources"
        )

        return replay

    async def _get_episode_events(
        self,
        db: Session,
        user_id: str,
        bounds: DayBounds
    ) -> List[DayReplayEvent]:
        """Get conversation episodes for the day. episode.created_at is naive UTC."""
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
                {"user_id": user_id,
                 "day_start": bounds.utc_naive_start, "day_end": bounds.utc_naive_end}
            ).fetchall()

            # Group by conversation for summary
            conversations = {}
            for row in result:
                conv_id = row.conversation_id or "unknown"
                created_at = utc_naive_to_et_naive(row.created_at)
                if conv_id not in conversations:
                    conversations[conv_id] = {"messages": [], "start": created_at}
                conversations[conv_id]["messages"].append({
                    "role": row.role,
                    "content": row.content[:200] if row.content else "",
                    "importance": row.importance
                })
                conversations[conv_id]["end"] = created_at

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
            db.rollback()

        return events

    async def _get_automation_events(
        self,
        db: Session,
        user_id: str,
        bounds: DayBounds
    ) -> List[DayReplayEvent]:
        """Get automation executions for the day. started_at is timestamptz."""
        events = []
        try:
            result = db.execute(
                text("""
                    SELECT el.id, el.started_at, el.completed_at, el.result, el.error_message,
                           at.name, at.description, at.original_intent
                    FROM automation_execution_log el
                    JOIN automation_task at ON el.task_id = at.id
                    WHERE at.user_id = :user_id
                      AND el.started_at BETWEEN :day_start AND :day_end
                    ORDER BY el.started_at
                """),
                {"user_id": user_id,
                 "day_start": bounds.aware_start, "day_end": bounds.aware_end}
            ).fetchall()

            # Group by automation name to see patterns
            automation_runs = {}
            for row in result:
                name = row.name
                if name not in automation_runs:
                    automation_runs[name] = {
                        "count": 0,
                        "description": row.description,
                        "original_intent": row.original_intent,
                        "successful": 0,
                        "first_run": row.started_at,
                        "last_run": row.started_at
                    }
                automation_runs[name]["count"] += 1
                automation_runs[name]["last_run"] = row.started_at
                if not row.error_message:
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
                        "original_intent": data["original_intent"],
                        "run_count": data["count"],
                        "successful_runs": data["successful"],
                        "first_run": data["first_run"].isoformat(),
                        "last_run": data["last_run"].isoformat()
                    },
                    importance=0.7 if data["count"] > 1 else 0.5
                ))

        except Exception as e:
            logger.warning(f"Failed to get automation events: {e}")
            db.rollback()

        return events

    async def _get_workout_events(
        self,
        db: Session,
        user_id: str,
        bounds: DayBounds
    ) -> List[DayReplayEvent]:
        """Get workout sessions for the day. Keyed on session_date (a DATE, already ET)."""
        events = []
        try:
            result = db.execute(
                text("""
                    SELECT ws.id, ws.started_at, ws.completed_at, ws.status,
                           w.title AS workout_title
                    FROM workout_session ws
                    LEFT JOIN workout w ON w.id = ws.template_id
                    WHERE ws.user_id = :user_id
                      AND ws.session_date = :session_date
                """),
                {"user_id": user_id, "session_date": bounds.replay_date}
            ).fetchall()

            for row in result:
                if row.status == "completed":
                    duration = None
                    if row.started_at and row.completed_at:
                        duration = int((row.completed_at - row.started_at).total_seconds() // 60)
                    workout_type = row.workout_title or "workout"
                    events.append(DayReplayEvent(
                        timestamp=row.started_at or bounds.et_naive_start,
                        source=DataSource.FITNESS_WORKOUTS,
                        event_type="workout_completed",
                        summary=f"Completed {workout_type} workout"
                                + (f" ({duration} min)" if duration else ""),
                        details={
                            "workout_type": workout_type,
                            "duration_minutes": duration,
                            "status": row.status
                        },
                        importance=0.8
                    ))

        except Exception as e:
            logger.warning(f"Failed to get workout events: {e}")
            db.rollback()

        return events

    async def _get_food_events(
        self,
        db: Session,
        user_id: str,
        bounds: DayBounds
    ) -> List[DayReplayEvent]:
        """Get food log entries for the day. food_log.logged_at is naive ET wall-clock."""
        events = []
        try:
            result = db.execute(
                text("""
                    SELECT id, meal_type, food_items, notes, calories, protein, carbs, fats,
                           logged_at
                    FROM food_log
                    WHERE user_id = :user_id
                      AND logged_at BETWEEN :day_start AND :day_end
                    ORDER BY logged_at
                """),
                {"user_id": user_id,
                 "day_start": bounds.et_naive_start, "day_end": bounds.et_naive_end}
            ).fetchall()

            total_calories = 0
            total_protein = 0
            meals_logged = []

            for row in result:
                total_calories += row.calories or 0
                total_protein += row.protein or 0
                meals_logged.append(row.meal_type)

                # food_items is JSON (list of items); fall back to free-text notes
                description = row.notes or ""
                if row.food_items:
                    try:
                        items = row.food_items if isinstance(row.food_items, list) else json.loads(row.food_items)
                        names = [i.get("name", str(i)) if isinstance(i, dict) else str(i) for i in items]
                        description = ", ".join(names) or description
                    except (TypeError, ValueError):
                        pass

                events.append(DayReplayEvent(
                    timestamp=row.logged_at,
                    source=DataSource.FITNESS_FOOD,
                    event_type="meal_logged",
                    summary=f"{row.meal_type}: {description[:50] if description else 'Logged'}",
                    details={
                        "meal_type": row.meal_type,
                        "description": description,
                        "calories": row.calories,
                        "protein": row.protein,
                        "carbs": row.carbs,
                        "fat": row.fats
                    },
                    importance=0.4
                ))

            # Add daily nutrition summary as high importance event.
            # Round the running totals: they accumulate floats/Decimals, so
            # raw they render as "186.60000000000002g protein" in the UI.
            if meals_logged:
                total_calories = int(round(float(total_calories)))
                total_protein = int(round(float(total_protein)))
                events.append(DayReplayEvent(
                    timestamp=bounds.et_naive_end,
                    source=DataSource.FITNESS_FOOD,
                    event_type="nutrition_summary",
                    summary=f"Nutrition: {len(meals_logged)} meals, {total_calories:,} cal, {total_protein}g protein",
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
            db.rollback()

        return events

    async def _get_recovery_events(
        self,
        db: Session,
        user_id: str,
        bounds: DayBounds
    ) -> List[DayReplayEvent]:
        """Get recovery/health metrics for the day. Keyed on log_date (a DATE, already ET)."""
        events = []
        try:
            result = db.execute(
                text("""
                    SELECT hrv, heart_rate, sleep_hours, soreness_level,
                           body_weight, created_at
                    FROM daily_recovery_log
                    WHERE user_id = :user_id
                      AND log_date = :log_date
                """),
                {"user_id": user_id, "log_date": bounds.replay_date}
            ).fetchone()

            if result:
                events.append(DayReplayEvent(
                    timestamp=result.created_at or bounds.et_naive_start,
                    source=DataSource.FITNESS_RECOVERY,
                    event_type="recovery_metrics",
                    summary=f"Recovery: {result.sleep_hours}h sleep, HRV {result.hrv}, resting HR {result.heart_rate}",
                    details={
                        "hrv": result.hrv,
                        "resting_hr": result.heart_rate,
                        "sleep_hours": result.sleep_hours,
                        "soreness_level": result.soreness_level,
                        "body_weight": result.body_weight
                    },
                    importance=0.7
                ))

        except Exception as e:
            logger.warning(f"Failed to get recovery events: {e}")
            db.rollback()

        return events

    async def _get_calendar_events(
        self,
        db: Session,
        user_id: str,
        bounds: DayBounds
    ) -> List[DayReplayEvent]:
        """Get calendar events for the day. calendar_event.start_time is naive ET."""
        events = []
        try:
            # calendar_event holds the real calendar (iOS-synced + email-extracted);
            # the legacy `event` table is Sara-created events only.
            result = db.execute(
                text("""
                    SELECT id, title, description, location,
                           start_time, end_time, source, ios_calendar_name,
                           owner, owner_relation
                    FROM calendar_event
                    WHERE user_id = :user_id
                      AND start_time BETWEEN :day_start AND :day_end
                    ORDER BY start_time
                """),
                {"user_id": user_id,
                 "day_start": bounds.et_naive_start, "day_end": bounds.et_naive_end}
            ).fetchall()

            for row in result:
                duration = (row.end_time - row.start_time).seconds // 60 if row.end_time else 0
                owner = row.owner or "self"
                is_self = owner == "self"
                # Annotate non-self events so the journal never narrates someone
                # else's appointment as something David did. Lower importance so
                # they don't crowd out David's actual day.
                if is_self:
                    summary = f"{row.title} ({duration} min)"
                    importance = 0.6
                elif owner == "unknown":
                    summary = f"[owner unclear] {row.title} ({duration} min) — ownership unclear, don't assume it's David's"
                    importance = 0.3
                else:
                    who = "the family" if owner == "family" else owner
                    marker = "[family]" if owner == "family" else f"[{owner}'s]"
                    summary = f"{marker} {row.title} ({duration} min) — {who}'s event, not David's"
                    importance = 0.3
                events.append(DayReplayEvent(
                    timestamp=row.start_time,
                    source=DataSource.CALENDAR,
                    event_type="calendar_event",
                    summary=summary,
                    details={
                        "title": row.title,
                        "description": row.description,
                        "location": row.location,
                        "duration_minutes": duration,
                        "event_source": row.source,
                        "calendar_name": row.ios_calendar_name,
                        "owner": owner,
                        "is_davids": is_self,
                    },
                    importance=importance
                ))

        except Exception as e:
            logger.warning(f"Failed to get calendar events: {e}")
            db.rollback()

        return events

    async def _get_email_events(
        self,
        db: Session,
        user_id: str,
        bounds: DayBounds
    ) -> List[DayReplayEvent]:
        """Get email activity for the day. email.received_at is timestamptz."""
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
                {"user_id": user_id,
                 "day_start": bounds.aware_start, "day_end": bounds.aware_end}
            ).fetchone()

            if result and result.total > 0:
                events.append(DayReplayEvent(
                    timestamp=bounds.et_naive_end,
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
            db.rollback()

        return events

    async def _get_research_events(
        self,
        db: Session,
        user_id: str,
        bounds: DayBounds
    ) -> List[DayReplayEvent]:
        """Get research job completions for the day.

        background_task timestamps are naive UTC (durable-dispatch convention).
        """
        events = []
        try:
            # background_task holds dispatched agent work (research, code, etc.)
            result = db.execute(
                text("""
                    SELECT id, task_type, original_query, status,
                           created_at, completed_at
                    FROM background_task
                    WHERE user_id = :user_id
                      AND created_at BETWEEN :day_start AND :day_end
                    ORDER BY created_at
                """),
                {"user_id": user_id,
                 "day_start": bounds.utc_naive_start, "day_end": bounds.utc_naive_end}
            ).fetchall()

            for row in result:
                query = row.original_query or row.task_type or "task"
                events.append(DayReplayEvent(
                    timestamp=utc_naive_to_et_naive(row.created_at) or bounds.et_naive_start,
                    source=DataSource.RESEARCH,
                    event_type="research_task",
                    summary=f"Agent task: {query[:50]}... ({row.status})",
                    details={
                        "task_type": row.task_type,
                        "description": query,
                        "status": row.status
                    },
                    importance=0.6
                ))

        except Exception as e:
            logger.warning(f"Failed to get research events: {e}")
            db.rollback()

        return events

    async def _get_learning_events(
        self,
        db: Session,
        user_id: str,
        bounds: DayBounds
    ) -> List[DayReplayEvent]:
        """Get learning session activity for the day. started_at is timestamptz."""
        events = []
        try:
            result = db.execute(
                text("""
                    SELECT ls.id, ls.session_type, ls.duration_minutes,
                           ls.started_at, ls.ended_at,
                           lt.title as topic_name
                    FROM learning_session ls
                    LEFT JOIN learning_topic lt ON ls.topic_id = lt.id
                    WHERE ls.user_id = :user_id
                      AND ls.started_at BETWEEN :day_start AND :day_end
                    ORDER BY ls.started_at
                """),
                {"user_id": user_id,
                 "day_start": bounds.aware_start, "day_end": bounds.aware_end}
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
            db.rollback()

        return events

    async def _get_timer_events(
        self,
        db: Session,
        user_id: str,
        bounds: DayBounds
    ) -> List[DayReplayEvent]:
        """Get timer usage for the day. timer.start_time is naive UTC."""
        events = []
        try:
            result = db.execute(
                text("""
                    SELECT id, title, duration_minutes, start_time, end_time, is_completed
                    FROM timer
                    WHERE user_id = :user_id
                      AND start_time BETWEEN :day_start AND :day_end
                    ORDER BY start_time
                """),
                {"user_id": user_id,
                 "day_start": bounds.utc_naive_start, "day_end": bounds.utc_naive_end}
            ).fetchall()

            if result:
                events.append(DayReplayEvent(
                    timestamp=bounds.et_naive_end,
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
            db.rollback()

        return events

    async def _get_reminder_events(
        self,
        db: Session,
        user_id: str,
        bounds: DayBounds
    ) -> List[DayReplayEvent]:
        """Get reminder completions for the day.

        reminder.reminder_time is naive UTC — the create tool coerces an aware
        UTC datetime into the naive column (app/tools/reminders.py).
        """
        events = []
        try:
            result = db.execute(
                text("""
                    SELECT id, title, reminder_time, is_completed
                    FROM reminder
                    WHERE user_id = :user_id
                      AND reminder_time BETWEEN :day_start AND :day_end
                    ORDER BY reminder_time
                """),
                {"user_id": user_id,
                 "day_start": bounds.utc_naive_start, "day_end": bounds.utc_naive_end}
            ).fetchall()

            completed = [r for r in result if r.is_completed]

            if result:
                events.append(DayReplayEvent(
                    timestamp=bounds.et_naive_end,
                    source=DataSource.REMINDERS,
                    event_type="reminders_summary",
                    summary=f"Reminders: {len(completed)}/{len(result)} completed",
                    details={
                        "total": len(result),
                        "completed": len(completed),
                        "reminders": [{"title": r.title, "completed": r.is_completed} for r in result]
                    },
                    importance=0.4
                ))

        except Exception as e:
            logger.warning(f"Failed to get reminder events: {e}")
            db.rollback()

        return events

    async def _get_home_events(
        self,
        db: Session,
        bounds: DayBounds
    ) -> List[DayReplayEvent]:
        """Get Home Assistant activity for the day, summarized per entity
        PER TRANSITION STATE (to_state) — not just "was active this hour".

        One event per (entity, to_state) per day: how often it transitioned
        to that state and at which hours. This is the raw material for
        daily-routine pattern detection, and critically preserves direction
        — "light turns off around 19:00" is a different, actionable fact
        from "light turns on around 06:00", not the same "active" blob.
        `unavailable`/`unknown` are dropped as connectivity noise, not real
        state transitions. home_activity_log is house-wide, not per-user.
        """
        events = []
        try:
            result = db.execute(
                text("""
                    -- changed_at is timestamptz; convert to naive ET so the day
                    -- window, sort order, and hour buckets match every other source
                    SELECT entity_id,
                           MAX(friendly_name) AS friendly_name,
                           MAX(domain) AS domain,
                           to_state,
                           COUNT(*) AS change_count,
                           MIN(changed_at AT TIME ZONE 'America/New_York') AS first_change,
                           MAX(changed_at AT TIME ZONE 'America/New_York') AS last_change,
                           ARRAY_AGG(DISTINCT EXTRACT(HOUR FROM changed_at AT TIME ZONE 'America/New_York')::int) AS active_hours
                    FROM home_activity_log
                    WHERE (changed_at AT TIME ZONE 'America/New_York') BETWEEN :day_start AND :day_end
                          AND to_state NOT IN ('unavailable', 'unknown')
                    GROUP BY entity_id, to_state
                    ORDER BY change_count DESC
                """),
                {"day_start": bounds.et_naive_start, "day_end": bounds.et_naive_end}
            ).fetchall()

            for row in result:
                events.append(DayReplayEvent(
                    timestamp=row.first_change,
                    source=DataSource.HOME,
                    event_type="home_entity_activity",
                    summary=f"{row.friendly_name or row.entity_id} -> {row.to_state}: {row.change_count} changes",
                    details={
                        "entity_id": row.entity_id,
                        "friendly_name": row.friendly_name,
                        "domain": row.domain,
                        "to_state": row.to_state,
                        "change_count": row.change_count,
                        "first_change": row.first_change.isoformat(),
                        "last_change": row.last_change.isoformat(),
                        "active_hours": sorted(row.active_hours or [])
                    },
                    importance=0.5 if row.domain in ("lock", "cover") else 0.4
                ))

        except Exception as e:
            logger.warning(f"Failed to get home events: {e}")
            db.rollback()

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
    ) -> bool:
        """Cache the replay for later use. Returns True if the row was written."""
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
                    "replay_data": json.dumps(replay_data, default=_json_default),
                    "summary": summary_text,
                    "data_sources": replay.data_sources_included,
                    "episode_count": replay.summary.get("by_source", {}).get("episodes", 0),
                    "automation_count": replay.summary.get("by_source", {}).get("automations", 0)
                }
            )
            db.commit()

            logger.info(f"Cached day replay for {replay.user_id} on {replay.replay_date}")
            return True

        except Exception as e:
            logger.error(f"Failed to cache replay: {e}")
            db.rollback()
            return False


# Singleton instance
day_replay_builder = DayReplayBuilder()
