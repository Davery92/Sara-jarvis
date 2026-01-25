"""
ProactiveService - Enables Sara to take proactive action.

Periodically reviews context and considers if action would be helpful,
without being prompted by the user.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ProactiveActionType(str, Enum):
    """Types of proactive actions Sara can take."""
    NOTIFY = "notify"        # Alert David to something
    REMEMBER = "remember"    # Store an observation
    PREPARE = "prepare"      # Get ready for something
    NONE = "none"           # No action needed


@dataclass
class ProactiveAction:
    """A proactive action Sara decided to take."""
    action_type: ProactiveActionType
    title: Optional[str] = None
    body: Optional[str] = None
    priority: float = 0.5
    metadata: Optional[Dict] = None


@dataclass
class UserState:
    """Inferred state of the user."""
    inferred_activity: str
    availability: str  # available, busy, away, sleeping, dnd
    last_interaction: Optional[datetime]
    location: Optional[str] = None
    time_of_day: str = "day"


class ProactiveService:
    """
    Service for Sara's proactive behavior.

    Enables Sara to:
    - Review current context periodically
    - Decide if action would be helpful
    - Take appropriate proactive actions
    - Track action outcomes for karma feedback
    """

    # Thresholds for notification frequency
    MAX_NOTIFICATIONS_PER_HOUR = 3
    HIGH_PRIORITY_THRESHOLD = 0.7

    def __init__(self, db: AsyncSession):
        self.db = db

    async def run_proactive_check(self) -> List[ProactiveAction]:
        """
        Run a proactive check cycle.

        Reviews current context and decides what, if anything, to do.
        """
        # Get current state
        user_state = await self.infer_user_state()
        working_memory = await self._get_working_memory_snapshot()
        karma_context = await self._get_karma_context()
        pending_items = await self._get_pending_items()

        # Build context for decision
        context = {
            "user_state": user_state,
            "working_memory": working_memory,
            "karma": karma_context,
            "pending_items": pending_items,
            "time": datetime.utcnow(),
        }

        # Decide on actions
        actions = await self._decide_actions(context)

        # Filter based on notification limits
        actions = await self._apply_notification_limits(actions)

        # Execute actions
        for action in actions:
            await self._execute_action(action, context)

        return actions

    async def infer_user_state(self) -> UserState:
        """Infer the user's current state from available signals."""
        now = datetime.utcnow()
        hour = now.hour

        # Determine time of day
        if 6 <= hour < 12:
            time_of_day = "morning"
        elif 12 <= hour < 17:
            time_of_day = "afternoon"
        elif 17 <= hour < 21:
            time_of_day = "evening"
        else:
            time_of_day = "night"

        # Get last interaction
        last_interaction_result = await self.db.execute(
            text("""
                SELECT MAX(created_at) FROM episode
                WHERE created_at > NOW() - INTERVAL '24 hours'
            """)
        )
        last_interaction = last_interaction_result.fetchone()[0]

        # Infer availability based on time and recency
        if hour >= 23 or hour < 7:
            availability = "sleeping"
        elif last_interaction and (now - last_interaction).total_seconds() < 300:
            availability = "available"
        elif last_interaction and (now - last_interaction).total_seconds() < 1800:
            availability = "busy"
        else:
            availability = "away"

        # Infer activity
        if availability == "sleeping":
            activity = "resting"
        elif availability == "available":
            activity = "interacting with Sara"
        else:
            activity = "unknown"

        return UserState(
            inferred_activity=activity,
            availability=availability,
            last_interaction=last_interaction,
            time_of_day=time_of_day,
        )

    async def _get_working_memory_snapshot(self) -> Dict[str, Any]:
        """Get current working memory state."""
        from app.services.cognitive.working_memory import get_working_memory_service

        try:
            wm_service = get_working_memory_service()
            # Get snapshot for the default user - in production would use actual user
            snapshot = await wm_service.get_snapshot("64f37c56-85cb-4590-8de9-adfc17c343ed")
            return {
                "context_count": len(snapshot.current_context),
                "pending_actions": len(snapshot.pending_actions),
                "active_threads": len(snapshot.active_threads),
            }
        except Exception as e:
            logger.warning(f"Failed to get working memory: {e}")
            return {}

    async def _get_karma_context(self) -> Dict[str, Any]:
        """Get current karma state."""
        from app.services.karma import get_karma_service

        try:
            karma_service = await get_karma_service(self.db)
            sara_karma = await karma_service.get_agent_karma("sara")
            if sara_karma:
                return {
                    "composite_score": sara_karma.composite_score,
                    "threshold": sara_karma.overall_threshold.value,
                    "proactivity_score": next(
                        (d.current_score for d in sara_karma.dimensions
                         if d.dimension_name == "proactivity"),
                        50.0
                    )
                }
        except Exception as e:
            logger.warning(f"Failed to get karma: {e}")

        return {"composite_score": 50, "threshold": "neutral", "proactivity_score": 50}

    async def _get_pending_items(self) -> List[Dict]:
        """Get pending items that might need attention."""
        items = []

        # Check for pending reminders
        reminder_result = await self.db.execute(
            text("""
                SELECT id, title, reminder_time
                FROM reminder
                WHERE (is_completed IS NULL OR is_completed = FALSE)
                AND reminder_time BETWEEN NOW() AND NOW() + INTERVAL '1 hour'
                ORDER BY reminder_time
                LIMIT 5
            """)
        )
        for row in reminder_result.fetchall():
            items.append({
                "type": "reminder",
                "id": str(row[0]),
                "title": row[1],
                "due_at": row[2].isoformat() if row[2] else None,
            })

        # Check for upcoming calendar events
        calendar_result = await self.db.execute(
            text("""
                SELECT id, title, start_time
                FROM calendar_event
                WHERE start_time BETWEEN NOW() AND NOW() + INTERVAL '2 hours'
                ORDER BY start_time
                LIMIT 5
            """)
        )
        for row in calendar_result.fetchall():
            items.append({
                "type": "calendar",
                "id": str(row[0]),
                "title": row[1],
                "start_time": row[2].isoformat() if row[2] else None,
            })

        return items

    async def _decide_actions(self, context: Dict) -> List[ProactiveAction]:
        """
        Decide what proactive actions to take based on context.

        PHASE 4: Now invokes Sara for decision making instead of hard-coded rules.
        """
        from app.services.autonomy.sara_invocation import get_sara_invocation_service

        user_state = context["user_state"]
        pending_items = context["pending_items"]
        karma = context["karma"]

        # Don't be proactive when user is sleeping (unless urgent)
        if user_state.availability == "sleeping":
            return []

        # If no pending items, nothing to decide
        if not pending_items:
            return []

        # Build context summary for Sara
        context_summary = f"""Current situation:
- User availability: {user_state.availability}
- Time of day: {user_state.time_of_day}
- Last interaction: {user_state.last_interaction.isoformat() if user_state.last_interaction else 'unknown'}
- Proactivity karma: {karma.get('proactivity_score', 50):.1f}/100

Pending items:
"""
        for item in pending_items:
            if item["type"] == "reminder":
                context_summary += f"- Reminder: {item['title']} (due: {item.get('due_at', 'soon')})\n"
            elif item["type"] == "calendar":
                context_summary += f"- Event: {item['title']} (starts: {item.get('start_time', 'soon')})\n"

        # Invoke Sara for decision
        try:
            sara = await get_sara_invocation_service(self.db)
            decision = await sara.invoke_for_decision(
                context=context_summary,
                question="Should I proactively notify David about any of these items? "
                        "If yes, which ones and why? Be selective - only notify if truly helpful."
            )

            if decision.should_act and decision.action:
                # Parse Sara's response into action(s)
                return [ProactiveAction(
                    action_type=ProactiveActionType.NOTIFY,
                    title=decision.action[:50],
                    body=decision.action,
                    priority=decision.priority,
                    metadata={
                        "reasoning": decision.reasoning,
                        "invocation_id": decision.invocation_id,
                        "confidence": decision.confidence
                    }
                )]

            return []

        except Exception as e:
            logger.warning(f"Sara invocation failed, falling back to rules: {e}")
            # Fallback to rule-based behavior if Sara invocation fails
            return self._fallback_decide_actions(context)

    def _fallback_decide_actions(self, context: Dict) -> List[ProactiveAction]:
        """Fallback rule-based decision making if Sara invocation fails."""
        actions = []
        pending_items = context["pending_items"]
        karma = context["karma"]

        for item in pending_items:
            if item["type"] == "reminder":
                priority = 0.6
                actions.append(ProactiveAction(
                    action_type=ProactiveActionType.NOTIFY,
                    title=f"Upcoming: {item['title']}",
                    body="Reminder due soon",
                    priority=priority,
                    metadata={"item_id": item["id"], "item_type": "reminder"},
                ))
            elif item["type"] == "calendar":
                priority = 0.5
                actions.append(ProactiveAction(
                    action_type=ProactiveActionType.NOTIFY,
                    title=f"Coming up: {item['title']}",
                    body="Event starting soon",
                    priority=priority,
                    metadata={"item_id": item["id"], "item_type": "calendar"},
                ))

        # If proactivity karma is low, be more conservative
        if karma.get("proactivity_score", 50) < 35:
            actions = [a for a in actions if a.priority >= self.HIGH_PRIORITY_THRESHOLD]

        return actions

    async def _apply_notification_limits(
        self,
        actions: List[ProactiveAction],
    ) -> List[ProactiveAction]:
        """Apply limits on notification frequency."""
        # Get recent notification count
        recent_result = await self.db.execute(
            text("""
                SELECT COUNT(*) FROM action_log
                WHERE action_type = 'proactive_notification'
                AND created_at > NOW() - INTERVAL '1 hour'
            """)
        )
        recent_count = recent_result.fetchone()[0] or 0

        if recent_count >= self.MAX_NOTIFICATIONS_PER_HOUR:
            # Only allow high-priority notifications
            return [a for a in actions
                    if a.action_type == ProactiveActionType.NOTIFY
                    and a.priority >= self.HIGH_PRIORITY_THRESHOLD]

        return actions

    async def _execute_action(
        self,
        action: ProactiveAction,
        context: Dict,
    ) -> None:
        """Execute a proactive action."""
        if action.action_type == ProactiveActionType.NONE:
            return

        if action.action_type == ProactiveActionType.NOTIFY:
            await self._handle_notification(action, context)

        elif action.action_type == ProactiveActionType.REMEMBER:
            await self._handle_remember(action, context)

        elif action.action_type == ProactiveActionType.PREPARE:
            await self._handle_prepare(action, context)

    async def _handle_notification(
        self,
        action: ProactiveAction,
        context: Dict,
    ) -> None:
        """Handle a proactive notification."""
        # Record the action for outcome tracking
        await self.db.execute(
            text("""
                INSERT INTO action_log
                (user_id, action_type, action_content, context_snapshot)
                VALUES (:user_id, 'proactive_notification', :content, :context)
            """),
            {
                "user_id": "64f37c56-85cb-4590-8de9-adfc17c343ed",
                "content": f"{action.title}: {action.body}",
                "context": {
                    "priority": action.priority,
                    "user_availability": context["user_state"].availability,
                    "metadata": action.metadata,
                },
            }
        )
        await self.db.commit()

        logger.info(f"Proactive notification: {action.title}")

        # Send actual notification via notification service
        try:
            from app.services.notification_service import get_notification_service
            notification_service = get_notification_service()
            await notification_service.notify_proactive_action(
                action_type=action.action_type.value,
                title_text=action.title,
                body_text=action.body,
                priority_score=action.priority
            )
        except Exception as e:
            logger.warning(f"Failed to send proactive notification: {e}")

    async def _handle_remember(
        self,
        action: ProactiveAction,
        context: Dict,
    ) -> None:
        """Handle storing a proactive observation."""
        from app.services.reflection.scratchpad import get_reflection_scratchpad, ObservationType

        try:
            scratchpad = await get_reflection_scratchpad(self.db)
            await scratchpad.add_observation(
                observation_type=ObservationType.PATTERN_DETECTED,
                subject_agent="sara",
                summary=f"Proactive observation: {action.title}",
                details={"body": action.body, "metadata": action.metadata},
                confidence=0.6,
            )
        except Exception as e:
            logger.warning(f"Failed to record proactive observation: {e}")

    async def _handle_prepare(
        self,
        action: ProactiveAction,
        context: Dict,
    ) -> None:
        """Handle proactive preparation."""
        # Store preparation in working memory
        from app.services.cognitive.working_memory import get_working_memory_service

        try:
            wm_service = get_working_memory_service()
            await wm_service.add_pending_action(
                user_id="64f37c56-85cb-4590-8de9-adfc17c343ed",
                action_type="preparation",
                context=f"{action.title}: {action.body}",
                priority=action.priority,
            )
        except Exception as e:
            logger.warning(f"Failed to add preparation: {e}")


# Singleton instance
_proactive_service: Optional[ProactiveService] = None


async def get_proactive_service(db: AsyncSession) -> ProactiveService:
    """Get or create ProactiveService instance."""
    global _proactive_service
    if _proactive_service is None or _proactive_service.db != db:
        _proactive_service = ProactiveService(db)
    return _proactive_service
