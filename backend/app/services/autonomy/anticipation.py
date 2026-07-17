"""
AnticipationService - Enables Sara to prepare for upcoming events.

Runs morning and evening to prepare for the day ahead or tomorrow.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

from app.core.timezone import now as local_now, today as local_today, start_of_day

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class PreparationType(str, Enum):
    """Types of preparations Sara can make."""
    REMINDER = "reminder"    # Set a reminder for later
    RESEARCH = "research"    # Queue research task
    ALERT = "alert"         # Important item alert
    BRIEF = "brief"         # Daily brief item


@dataclass
class Preparation:
    """A preparation Sara decided to make."""
    prep_type: PreparationType
    title: str
    body: Optional[str] = None
    scheduled_for: Optional[datetime] = None
    priority: float = 0.5
    metadata: Optional[Dict] = None


class AnticipationService:
    """
    Service for Sara's anticipation behavior.

    Enables Sara to:
    - Look ahead at calendar and patterns
    - Prepare for likely needs
    - Set reminders and alerts
    - Generate daily briefs
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def run_morning_anticipation(self) -> List[Preparation]:
        """
        Run morning anticipation - prepare for the day ahead.
        """
        today = local_today()
        tomorrow = today + timedelta(days=1)

        # Get today's calendar events
        events = await self._get_calendar_events(
            start=datetime.combine(today, datetime.min.time()),
            end=datetime.combine(tomorrow, datetime.min.time()),
        )

        # Get any patterns relevant to today
        day_of_week = local_now().strftime("%A")
        patterns = await self._get_day_patterns(day_of_week)

        # Get pending items
        pending = await self._get_pending_items()

        # Generate preparations
        preparations = []

        # For each event, consider if preparation is needed
        for event in events:
            preps = await self._prepare_for_event(event)
            preparations.extend(preps)

        # Apply pattern-based preparations
        for pattern in patterns:
            preps = await self._apply_pattern(pattern)
            preparations.extend(preps)

        # Generate daily brief
        brief = await self._generate_daily_brief(events, pending, patterns)
        if brief:
            preparations.append(brief)

        # Execute preparations
        for prep in preparations:
            await self._execute_preparation(prep)

        return preparations

    async def run_evening_anticipation(self) -> List[Preparation]:
        """
        Run evening anticipation - prepare for tomorrow.
        """
        today = local_today()
        tomorrow = today + timedelta(days=1)
        day_after = today + timedelta(days=2)

        # Get tomorrow's events
        events = await self._get_calendar_events(
            start=datetime.combine(tomorrow, datetime.min.time()),
            end=datetime.combine(day_after, datetime.min.time()),
        )

        # Summarize today
        today_summary = await self._summarize_today()

        # Get pending items
        pending = await self._get_pending_items()

        preparations = []

        # Prepare for tomorrow's events
        for event in events:
            preps = await self._prepare_for_event(event, for_tomorrow=True)
            preparations.extend(preps)

        # Flag any unresolved items
        for item in pending:
            if item.get("priority", 0) > 0.5:
                preparations.append(Preparation(
                    prep_type=PreparationType.ALERT,
                    title=f"Unresolved: {item.get('title', 'item')}",
                    body="This item is still pending",
                    priority=item.get("priority", 0.5),
                    metadata={"item_id": item.get("id")},
                ))

        # Execute preparations
        for prep in preparations:
            await self._execute_preparation(prep)

        return preparations

    async def _get_calendar_events(
        self,
        start: datetime,
        end: datetime,
    ) -> List[Dict]:
        """Get calendar events in a time range."""
        result = await self.db.execute(
            text("""
                SELECT id, title, description, start_time, end_time, location, ios_calendar_name
                FROM calendar_event
                WHERE start_time >= :start AND start_time < :end
                ORDER BY start_time
            """),
            {"start": start, "end": end}
        )

        events = []
        for row in result.fetchall():
            events.append({
                "id": str(row[0]),
                "title": row[1],
                "description": row[2],
                "start_time": row[3],
                "end_time": row[4],
                "location": row[5],
                "calendar_name": row[6],
            })

        return events

    async def _get_day_patterns(self, day_of_week: str) -> List[Dict]:
        """Get patterns relevant to a specific day of week."""
        result = await self.db.execute(
            text("""
                SELECT pattern_id, pattern_type, description, proposed_action
                FROM reflection_patterns
                WHERE status = 'active'
                AND (metadata->>'day_of_week' = :day OR metadata->>'day_of_week' IS NULL)
                ORDER BY confidence DESC
                LIMIT 5
            """),
            {"day": day_of_week}
        )

        patterns = []
        for row in result.fetchall():
            patterns.append({
                "pattern_id": row[0],
                "pattern_type": row[1],
                "description": row[2],
                "proposed_action": row[3],
            })

        return patterns

    async def _get_pending_items(self) -> List[Dict]:
        """Get pending items across the system."""
        items = []

        # Pending reminders
        reminder_result = await self.db.execute(
            text("""
                SELECT id, title, reminder_time
                FROM reminder
                WHERE (is_completed IS NULL OR is_completed = FALSE)
                ORDER BY COALESCE(reminder_time, NOW() + INTERVAL '30 days')
                LIMIT 10
            """)
        )
        for row in reminder_result.fetchall():
            items.append({
                "id": str(row[0]),
                "type": "reminder",
                "title": row[1],
                "due_at": row[2].isoformat() if row[2] else None,
                "priority": 0.5,
            })

        # Pending working memory actions
        action_result = await self.db.execute(
            text("""
                SELECT id, action_type, context, priority
                FROM working_memory_actions
                WHERE status = 'pending'
                ORDER BY priority DESC
                LIMIT 10
            """)
        )
        for row in action_result.fetchall():
            items.append({
                "id": str(row[0]),
                "type": "action",
                "title": row[1],
                "context": row[2],
                "priority": row[3] or 0.5,
            })

        return items

    async def _prepare_for_event(
        self,
        event: Dict,
        for_tomorrow: bool = False,
    ) -> List[Preparation]:
        """
        Generate preparations for a calendar event.

        PHASE 4: Now invokes Sara for intelligent preparation decisions.
        """
        from app.services.autonomy.sara_invocation import get_sara_invocation_service

        start_time = event.get("start_time")
        if not start_time:
            return []

        # Build context for Sara
        time_until = start_time - local_now()
        context = f"""Upcoming event:
- Title: {event['title']}
- Start time: {start_time.strftime('%Y-%m-%d %H:%M')}
- Time until: {time_until}
- Location: {event.get('location', 'Not specified')}
- Description: {event.get('description', 'No description')[:200]}
- Is for tomorrow: {for_tomorrow}"""

        try:
            sara = await get_sara_invocation_service(self.db)
            decision = await sara.invoke_for_decision(
                context=context,
                question="What preparations should I make for this event? Consider reminders, "
                        "travel time, research needs, or materials David might need."
            )

            if decision.should_act and decision.action:
                # Determine preparation type from Sara's reasoning
                prep_type = PreparationType.REMINDER
                if "research" in decision.action.lower():
                    prep_type = PreparationType.RESEARCH
                elif "alert" in decision.action.lower() or "important" in decision.action.lower():
                    prep_type = PreparationType.ALERT

                return [Preparation(
                    prep_type=prep_type,
                    title=event['title'][:50],
                    body=decision.action,
                    scheduled_for=start_time - timedelta(minutes=30) if prep_type == PreparationType.REMINDER else None,
                    priority=decision.priority,
                    metadata={
                        "event_id": event["id"],
                        "reasoning": decision.reasoning,
                        "invocation_id": decision.invocation_id
                    }
                )]

            return []

        except Exception as e:
            logger.warning(f"Sara invocation failed, falling back to rules: {e}")
            return self._fallback_prepare_for_event(event, for_tomorrow, start_time)

    def _fallback_prepare_for_event(
        self,
        event: Dict,
        for_tomorrow: bool,
        start_time: datetime,
    ) -> List[Preparation]:
        """Fallback rule-based preparation if Sara invocation fails."""
        preparations = []

        # Set reminder 30 minutes before
        reminder_time = start_time - timedelta(minutes=30)
        if reminder_time > local_now():
            preparations.append(Preparation(
                prep_type=PreparationType.REMINDER,
                title=f"Upcoming: {event['title']}",
                body=f"Event starts at {start_time.strftime('%H:%M')}",
                scheduled_for=reminder_time,
                priority=0.6,
                metadata={"event_id": event["id"]},
            ))

        # For events with location, maybe prepare travel info
        if event.get("location") and for_tomorrow:
            preparations.append(Preparation(
                prep_type=PreparationType.RESEARCH,
                title=f"Location info: {event['location']}",
                body="Consider travel time and directions",
                priority=0.4,
                metadata={"event_id": event["id"], "location": event["location"]},
            ))

        return preparations

    async def _apply_pattern(self, pattern: Dict) -> List[Preparation]:
        """Apply a detected pattern to generate preparations."""
        preparations = []

        if pattern.get("pattern_type") == "timing_pattern":
            # Add alert for known problematic times
            preparations.append(Preparation(
                prep_type=PreparationType.ALERT,
                title="Pattern reminder",
                body=pattern.get("description", ""),
                priority=0.5,
                metadata={"pattern_id": pattern["pattern_id"]},
            ))

        return preparations

    async def _generate_daily_brief(
        self,
        events: List[Dict],
        pending: List[Dict],
        patterns: List[Dict],
    ) -> Optional[Preparation]:
        """Generate a daily brief summary."""
        if not events and not pending:
            return None

        brief_parts = []

        if events:
            brief_parts.append(f"Today: {len(events)} event(s)")
            for event in events[:3]:
                start_str = event['start_time'].strftime('%H:%M') if event.get('start_time') else "TBD"
                brief_parts.append(f"  - {start_str}: {event['title']}")

        if pending:
            high_priority = [p for p in pending if p.get("priority", 0) > 0.5]
            if high_priority:
                brief_parts.append(f"Pending: {len(high_priority)} high-priority item(s)")

        if not brief_parts:
            return None

        return Preparation(
            prep_type=PreparationType.BRIEF,
            title="Daily Brief",
            body="\n".join(brief_parts),
            priority=0.7,
        )

    async def _summarize_today(self) -> Dict:
        """Generate a summary of today's activity."""
        today_start = start_of_day()

        # Count interactions
        interaction_result = await self.db.execute(
            text("""
                SELECT COUNT(*) FROM episodes
                WHERE created_at >= :today
            """),
            {"today": today_start}
        )
        interaction_count = interaction_result.fetchone()[0] or 0

        # Count completed items
        completed_result = await self.db.execute(
            text("""
                SELECT COUNT(*) FROM action_log
                WHERE created_at >= :today
                AND outcome_status = 'success'
            """),
            {"today": today_start}
        )
        completed_count = completed_result.fetchone()[0] or 0

        return {
            "interactions": interaction_count,
            "completed": completed_count,
        }

    async def _execute_preparation(self, prep: Preparation) -> None:
        """Execute a preparation."""
        logger.info(f"Preparation ({prep.prep_type.value}): {prep.title}")

        if prep.prep_type == PreparationType.REMINDER:
            # Create a reminder
            if prep.scheduled_for:
                import uuid
                await self.db.execute(
                    text("""
                        INSERT INTO reminder (id, user_id, title, description, reminder_time, is_completed)
                        VALUES (:id, :user_id, :title, :description, :reminder_time, FALSE)
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "user_id": "64f37c56-85cb-4590-8de9-adfc17d343ed",
                        "title": prep.title,
                        "description": prep.body,
                        "reminder_time": prep.scheduled_for,
                    }
                )
                await self.db.commit()

        elif prep.prep_type == PreparationType.BRIEF:
            # Store daily brief in working memory
            from app.services.cognitive.working_memory import get_working_memory_service

            try:
                wm_service = get_working_memory_service()
                await wm_service.add_context_segment(
                    user_id="64f37c56-85cb-4590-8de9-adfc17d343ed",
                    content=f"[Daily Brief]\n{prep.body}",
                    source="anticipation",
                    relevance=prep.priority,
                )
            except Exception as e:
                logger.warning(f"Failed to store daily brief: {e}")

        elif prep.prep_type == PreparationType.ALERT:
            # Record alert for proactive service to handle
            await self.db.execute(
                text("""
                    INSERT INTO action_log
                    (user_id, action_type, action_content, context_snapshot)
                    VALUES (:user_id, 'anticipation_alert', :content, :context)
                """),
                {
                    "user_id": "64f37c56-85cb-4590-8de9-adfc17d343ed",
                    "content": f"{prep.title}: {prep.body}",
                    "context": prep.metadata or {},
                }
            )
            await self.db.commit()


# Singleton instance
_anticipation_service: Optional[AnticipationService] = None


async def get_anticipation_service(db: AsyncSession) -> AnticipationService:
    """Get or create AnticipationService instance."""
    global _anticipation_service
    if _anticipation_service is None or _anticipation_service.db != db:
        _anticipation_service = AnticipationService(db)
    return _anticipation_service
