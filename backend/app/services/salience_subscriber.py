"""
Salience Subscriber — scores events, logs observations, triggers deliberation.

Sits on the event bus alongside WorkingMemorySubscriber. For each event:
1. Score salience using SalienceScorer
2. If salience >= 0.3, log as observation
3. Check if accumulated salience warrants deliberation
4. If yes, dispatch deliberation via Celery task
"""

import logging
from datetime import datetime

from app.services.event_bus import Event, EventType, EventSubscriber

logger = logging.getLogger(__name__)

DAVID_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"
OBSERVATION_FLOOR = 0.3


class SalienceSubscriber(EventSubscriber):
    """
    Scores every event for salience, logs interesting ones as observations,
    and triggers deliberation when accumulated salience is high enough.
    """

    def __init__(self):
        super().__init__("salience")
        # Subscribe to event types worth scoring
        self.subscribe_to(
            # Security
            EventType.HOME_DOOR_CHANGED,
            EventType.HOME_ANOMALY_DETECTED,
            EventType.HOME_MOTION_DETECTED,
            # Home
            EventType.HOME_CLIMATE_CHANGED,
            EventType.HOME_LIGHT_CHANGED,
            EventType.HOME_STATE_CHANGED,
            # Activity
            EventType.ACTIVITY_STATE_CHANGED,
            EventType.DESKTOP_FOCUS_SPAN,
            EventType.DESKTOP_ACTIVITY_STATE,
            EventType.DESKTOP_SCREEN_CONTENT,
            # Location
            EventType.LOCATION_PLACE_ENTERED,
            EventType.LOCATION_PLACE_EXITED,
            # Chat
            EventType.CHAT_MESSAGE_RECEIVED,
            # Food & health
            EventType.FOOD_LOGGED,
            EventType.HEALTH_DATA_SYNCED,
            EventType.WORKOUT_LOGGED,
            EventType.WORKOUT_COMPLETED,
            # Timer & reminders
            EventType.TIMER_COMPLETED,
            EventType.REMINDER_CREATED,
            EventType.REMINDER_COMPLETED,
            # Calendar
            EventType.CALENDAR_EVENT_CREATED,
            EventType.CALENDAR_EVENT_UPDATED,
            # Notes
            EventType.NOTE_CREATED,
            EventType.NOTE_UPDATED,
            # Goals
            EventType.GOAL_MILESTONE_REACHED,
            EventType.GOAL_COMPLETED,
            EventType.GOAL_PROGRESS_LOGGED,
        )

    async def handle_event(self, event: Event) -> None:
        try:
            from app.services.salience import salience_scorer
            from app.services.working_memory import read_memory
            from app.services.observation_log import log_observation

            user_id = event.user_id or DAVID_USER_ID
            memory = await read_memory(user_id)

            # Score the event
            salience = await salience_scorer.score_event(event, memory)

            # Only log as observation if above floor
            if salience >= OBSERVATION_FLOOR:
                description = salience_scorer.describe_event(event)
                category = salience_scorer.categorize_event(event)
                await log_observation(
                    user_id=user_id,
                    description=description,
                    salience=salience,
                    source=event.source,
                    category=category,
                )

                # Check if we should trigger deliberation
                if await salience_scorer.should_deliberate(user_id):
                    await _trigger_deliberation(user_id)

        except Exception as e:
            logger.warning(f"[SalienceSubscriber] Failed to score {event.event_type.value}: {e}")


async def _trigger_deliberation(user_id: str) -> None:
    """Dispatch deliberation via Celery task."""
    try:
        from app.celery_app import celery_app
        celery_app.send_task(
            "app.tasks.autonomy.trigger_deliberation",
            kwargs={"user_id": user_id},
            queue="cognitive",
        )
        logger.info(f"[SalienceSubscriber] Triggered deliberation for {user_id}")
    except Exception as e:
        logger.warning(f"[SalienceSubscriber] Failed to trigger deliberation: {e}")
