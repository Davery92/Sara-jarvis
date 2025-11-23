"""
Example Event Subscriber
Demonstrates how to subscribe to events
"""
from app.services.event_bus import EventSubscriber, Event, EventType
import logging

logger = logging.getLogger(__name__)


class WorkoutLoggingSubscriber(EventSubscriber):
    """Example subscriber that listens to workout events"""

    def __init__(self):
        super().__init__(name="WorkoutLoggingSubscriber")
        # Subscribe to workout-related events
        self.subscribe_to(
            EventType.WORKOUT_LOGGED,
            EventType.WORKOUT_STARTED,
            EventType.WORKOUT_COMPLETED
        )

    async def handle_event(self, event: Event):
        """Handle workout events"""
        if event.event_type == EventType.WORKOUT_LOGGED:
            logger.info(f"💪 Workout logged by user {event.user_id}: {event.payload}")
            # Could trigger: update weekly stats, check streak, send encouragement

        elif event.event_type == EventType.WORKOUT_STARTED:
            logger.info(f"🏃 Workout started by user {event.user_id}")
            # Could trigger: start timer, show motivation message

        elif event.event_type == EventType.WORKOUT_COMPLETED:
            logger.info(f"✅ Workout completed by user {event.user_id}")
            # Could trigger: celebration, update progress, suggest recovery


class FoodLoggingSubscriber(EventSubscriber):
    """Example subscriber for nutrition events"""

    def __init__(self):
        super().__init__(name="FoodLoggingSubscriber")
        self.subscribe_to(EventType.FOOD_LOGGED)

    async def handle_event(self, event: Event):
        """Handle food logging events"""
        if event.event_type == EventType.FOOD_LOGGED:
            logger.info(f"🍽️ Food logged by user {event.user_id}: {event.payload}")
            # Could trigger: update daily macros, check nutrition goals, suggest adjustments


class GoalProgressSubscriber(EventSubscriber):
    """Subscriber that tracks goal progress"""

    def __init__(self):
        super().__init__(name="GoalProgressSubscriber")
        self.subscribe_to(
            EventType.GOAL_PROGRESS_LOGGED,
            EventType.GOAL_MILESTONE_REACHED,
            EventType.GOAL_COMPLETED
        )

    async def handle_event(self, event: Event):
        """Handle goal-related events"""
        if event.event_type == EventType.GOAL_PROGRESS_LOGGED:
            logger.info(f"📊 Goal progress updated for user {event.user_id}")
            # Could trigger: check if milestone reached, send encouragement

        elif event.event_type == EventType.GOAL_MILESTONE_REACHED:
            logger.info(f"🎯 Milestone reached by user {event.user_id}: {event.payload}")
            # Could trigger: celebration notification, update UI, suggest next milestone

        elif event.event_type == EventType.GOAL_COMPLETED:
            logger.info(f"🏆 Goal completed by user {event.user_id}: {event.payload}")
            # Could trigger: major celebration, suggest new goal, generate summary


# Initialize subscribers
workout_subscriber = WorkoutLoggingSubscriber()
food_subscriber = FoodLoggingSubscriber()
goal_subscriber = GoalProgressSubscriber()


def register_all_subscribers(event_bus):
    """Register all subscribers with the event bus"""
    event_bus.subscribe(workout_subscriber)
    event_bus.subscribe(food_subscriber)
    event_bus.subscribe(goal_subscriber)
    logger.info("✅ All example subscribers registered")
