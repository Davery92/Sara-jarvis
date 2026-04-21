"""
Event Bus System
Redis pub/sub based event system for reactive features
"""
from typing import Dict, Any, List, Callable, Optional
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime, timezone
import asyncio
import json
import redis.asyncio as redis
import logging
from functools import wraps

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Core event types in Sara"""
    # Workout events
    WORKOUT_LOGGED = "workout.logged"
    WORKOUT_STARTED = "workout.started"
    WORKOUT_COMPLETED = "workout.completed"

    # Food events
    FOOD_LOGGED = "food.logged"
    FOOD_DELETED = "food.deleted"

    # Timer events
    TIMER_STARTED = "timer.started"
    TIMER_COMPLETED = "timer.completed"
    TIMER_CANCELLED = "timer.cancelled"

    # Reminder events
    REMINDER_CREATED = "reminder.created"
    REMINDER_COMPLETED = "reminder.completed"
    REMINDER_CANCELLED = "reminder.cancelled"

    # Note events
    NOTE_CREATED = "note.created"
    NOTE_UPDATED = "note.updated"
    NOTE_DELETED = "note.deleted"

    # Goal events
    GOAL_CREATED = "goal.created"
    GOAL_UPDATED = "goal.updated"
    GOAL_COMPLETED = "goal.completed"
    GOAL_MILESTONE_REACHED = "goal.milestone_reached"
    GOAL_PROGRESS_LOGGED = "goal.progress_logged"

    # Recovery events
    RECOVERY_LOGGED = "recovery.logged"

    # Calendar events
    CALENDAR_EVENT_CREATED = "calendar_event.created"
    CALENDAR_EVENT_UPDATED = "calendar_event.updated"
    CALENDAR_EVENT_DELETED = "calendar_event.deleted"

    # Memory events
    MEMORY_CREATED = "memory.created"
    MEMORY_ACCESSED = "memory.accessed"
    MEMORY_CONSOLIDATED = "memory.consolidated"

    # Health events (for Apple Health integration)
    HEALTH_DATA_SYNCED = "health.data_synced"
    HEALTH_WORKOUT_IMPORTED = "health.workout_imported"
    HEALTH_SLEEP_IMPORTED = "health.sleep_imported"

    # Context events
    CONTEXT_MODE_CHANGED = "context.mode_changed"
    CONTEXT_UPDATED = "context.updated"

    # Briefing events
    BRIEFING_GENERATED = "briefing.generated"
    BRIEFING_DELIVERED = "briefing.delivered"

    # Shadow agent events
    SHADOW_SUGGESTION_CREATED = "shadow.suggestion_created"
    SHADOW_SUGGESTION_ACCEPTED = "shadow.suggestion_accepted"
    SHADOW_SUGGESTION_DISMISSED = "shadow.suggestion_dismissed"

    # Home Assistant events (reactive engine)
    HOME_STATE_CHANGED = "home.state_changed"
    HOME_MOTION_DETECTED = "home.motion_detected"
    HOME_DOOR_CHANGED = "home.door_changed"
    HOME_LIGHT_CHANGED = "home.light_changed"
    HOME_CLIMATE_CHANGED = "home.climate_changed"
    HOME_ANOMALY_DETECTED = "home.anomaly_detected"

    # Activity & presence events
    ACTIVITY_STATE_CHANGED = "activity.state_changed"
    PRESENCE_ROOM_CHANGED = "presence.room_changed"
    INTERRUPTIBILITY_CHANGED = "interruptibility.changed"

    # Chat events
    CHAT_MESSAGE_RECEIVED = "chat.message_received"

    # Agent task events
    AGENT_TASK_PROGRESS = "agent_task.progress"
    AGENT_TASK_COMPLETED = "agent_task.completed"

    # Vision / Sensory events (Jetson)
    FACE_DETECTED = "vision.face_detected"
    DESK_PRESENCE_CHANGED = "vision.desk_presence_changed"
    VOICE_CONVERSATION_STARTED = "voice.conversation_started"
    VOICE_CONVERSATION_ENDED = "voice.conversation_ended"

    # ACS (Autonomous Cognition System) events
    ACS_STATE_CHANGED = "acs.state_changed"
    ACS_SESSION_STARTED = "acs.session_started"
    ACS_SESSION_ENDED = "acs.session_ended"
    ACS_MODE_SELECTED = "acs.mode_selected"
    ACS_INTEREST_CREATED = "acs.interest_created"
    ACS_INTEREST_CONNECTED = "acs.interest_connected"
    ACS_SELF_MODEL_UPDATED = "acs.self_model_updated"

    # System events
    SYSTEM_STARTED = "system.started"
    SYSTEM_SHUTDOWN = "system.shutdown"


class Event(BaseModel):
    """Event model"""
    event_id: str = Field(default_factory=lambda: f"evt_{datetime.now(timezone.utc).timestamp()}")
    event_type: EventType
    user_id: str
    payload: Dict[str, Any] = {}
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "system"  # Source of event (api, scheduled_job, shadow_agent, etc.)
    metadata: Dict[str, Any] = {}

    def to_json(self) -> str:
        """Serialize to JSON"""
        data = self.dict()
        data['timestamp'] = data['timestamp'].isoformat()
        data['event_type'] = data['event_type'].value
        return json.dumps(data)

    @classmethod
    def from_json(cls, json_str: str) -> 'Event':
        """Deserialize from JSON"""
        data = json.loads(json_str)
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        data['event_type'] = EventType(data['event_type'])
        return cls(**data)


class EventSubscriber:
    """Base class for event subscribers"""

    def __init__(self, name: str):
        self.name = name
        self.subscribed_events: List[EventType] = []

    async def handle_event(self, event: Event) -> None:
        """Handle an event - override in subclasses"""
        pass

    def subscribe_to(self, *event_types: EventType):
        """Subscribe to specific event types"""
        self.subscribed_events.extend(event_types)


class EventBus:
    """
    Redis-based event bus for pub/sub messaging
    Enables reactive features like shadow agents, notifications, etc.
    """

    def __init__(self, redis_url: str = None):
        if redis_url is None:
            import os
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None
        self.pubsub: Optional[redis.client.PubSub] = None
        self.subscribers: Dict[EventType, List[EventSubscriber]] = {}
        self.event_handlers: Dict[EventType, List[Callable]] = {}
        self.running = False
        self._listener_task: Optional[asyncio.Task] = None
        self._connect_lock: Optional[asyncio.Lock] = None
        self._connect_lock_loop_id: Optional[int] = None

        # Event replay buffer (in-memory, could be Redis-backed)
        self.replay_buffer: List[Event] = []
        self.replay_buffer_size = 1000  # Keep last 1000 events

    def _get_connect_lock(self) -> asyncio.Lock:
        loop_id = id(asyncio.get_running_loop())
        if self._connect_lock is None or self._connect_lock_loop_id != loop_id:
            self._connect_lock = asyncio.Lock()
            self._connect_lock_loop_id = loop_id
        return self._connect_lock

    async def _ensure_connected(self) -> bool:
        if self.redis_client is not None:
            return True

        lock = self._get_connect_lock()
        async with lock:
            if self.redis_client is not None:
                return True
            try:
                await self.connect()
                return True
            except Exception as e:
                logger.warning(f"Event bus connect failed, event not published: {e}")
                self.redis_client = None
                self.pubsub = None
                return False

    async def connect(self):
        """Connect to Redis"""
        try:
            self.redis_client = await redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            self.pubsub = self.redis_client.pubsub()
            logger.info(f"✅ Event bus connected to Redis: {self.redis_url}")
        except Exception as e:
            logger.error(f"❌ Failed to connect to Redis: {e}")
            raise

    async def disconnect(self):
        """Disconnect from Redis"""
        self.running = False

        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

        if self.pubsub:
            await self.pubsub.close()

        if self.redis_client:
            await self.redis_client.close()

        logger.info("Event bus disconnected")

    async def publish(self, event: Event) -> None:
        """
        Publish an event to the bus

        Args:
            event: Event to publish
        """
        if not await self._ensure_connected():
            return

        try:
            # Publish to Redis channel
            channel = f"sara:events:{event.event_type.value}"
            await self.redis_client.publish(channel, event.to_json())

            # Add to replay buffer
            self.replay_buffer.append(event)
            if len(self.replay_buffer) > self.replay_buffer_size:
                self.replay_buffer.pop(0)

            # Store in Redis for persistence (7 days)
            event_key = f"sara:event_log:{event.event_id}"
            await self.redis_client.setex(
                event_key,
                7 * 24 * 60 * 60,  # 7 days in seconds
                event.to_json()
            )

            logger.debug(f"📤 Published event: {event.event_type.value} (user: {event.user_id})")

        except Exception as e:
            logger.error(f"Failed to publish event: {e}")
            self.redis_client = None
            self.pubsub = None

    def subscribe(self, subscriber: EventSubscriber):
        """
        Subscribe a subscriber to events

        Args:
            subscriber: EventSubscriber instance
        """
        for event_type in subscriber.subscribed_events:
            if event_type not in self.subscribers:
                self.subscribers[event_type] = []
            self.subscribers[event_type].append(subscriber)
            logger.info(f"Subscribed '{subscriber.name}' to {event_type.value}")

    def on(self, event_type: EventType):
        """
        Decorator to register event handlers

        Example:
            @event_bus.on(EventType.WORKOUT_LOGGED)
            async def handle_workout(event: Event):
                print(f"Workout logged: {event.payload}")
        """
        def decorator(func: Callable):
            if event_type not in self.event_handlers:
                self.event_handlers[event_type] = []
            self.event_handlers[event_type].append(func)
            logger.info(f"Registered handler '{func.__name__}' for {event_type.value}")

            @wraps(func)
            async def wrapper(*args, **kwargs):
                return await func(*args, **kwargs)

            return wrapper

        return decorator

    async def start_listening(self):
        """Start listening for events"""
        if not self.pubsub:
            logger.error("PubSub not initialized")
            return

        # Subscribe to all event channels
        channels = [f"sara:events:{et.value}" for et in EventType]
        await self.pubsub.subscribe(*channels)

        self.running = True
        logger.info(f"🎧 Event bus listening on {len(channels)} channels")

        # Start listener task
        self._listener_task = asyncio.create_task(self._listen_loop())

    async def _listen_loop(self):
        """Main event listening loop"""
        try:
            async for message in self.pubsub.listen():
                if message['type'] == 'message':
                    try:
                        # Deserialize event
                        event = Event.from_json(message['data'])

                        # Dispatch to subscribers
                        await self._dispatch_event(event)

                    except Exception as e:
                        logger.error(f"Error processing event: {e}", exc_info=True)

        except asyncio.CancelledError:
            logger.info("Event listener cancelled")
        except Exception as e:
            logger.error(f"Event listener error: {e}", exc_info=True)

    async def _dispatch_event(self, event: Event):
        """Dispatch event to subscribers and handlers"""
        # Dispatch to subscribers
        subscribers = self.subscribers.get(event.event_type, [])
        for subscriber in subscribers:
            try:
                await subscriber.handle_event(event)
            except Exception as e:
                logger.error(f"Subscriber '{subscriber.name}' error: {e}", exc_info=True)

        # Dispatch to handlers
        handlers = self.event_handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                logger.error(f"Handler '{handler.__name__}' error: {e}", exc_info=True)

    async def replay_events(
        self,
        event_types: Optional[List[EventType]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Event]:
        """
        Replay events from buffer or Redis

        Args:
            event_types: Filter by event types
            start_time: Start time filter
            end_time: End time filter
            limit: Max events to return

        Returns:
            List of events
        """
        # Filter from replay buffer (in-memory)
        events = self.replay_buffer

        if event_types:
            events = [e for e in events if e.event_type in event_types]

        if start_time:
            events = [e for e in events if e.timestamp >= start_time]

        if end_time:
            events = [e for e in events if e.timestamp <= end_time]

        # Sort by timestamp (newest first)
        events = sorted(events, key=lambda e: e.timestamp, reverse=True)

        return events[:limit]

    async def get_event_stats(self) -> Dict[str, Any]:
        """Get event bus statistics"""
        stats = {
            "connected": self.redis_client is not None,
            "listening": self.running,
            "subscribers": {
                et.value: len(subs)
                for et, subs in self.subscribers.items()
            },
            "handlers": {
                et.value: len(handlers)
                for et, handlers in self.event_handlers.items()
            },
            "replay_buffer_size": len(self.replay_buffer),
            "total_event_types": len(EventType)
        }
        return stats


# Global event bus instance
event_bus = EventBus()


# Helper function to emit events easily
async def emit_event(
    event_type: EventType,
    user_id: str,
    payload: Dict[str, Any] = None,
    source: str = "api",
    metadata: Dict[str, Any] = None
):
    """
    Helper function to emit an event

    Args:
        event_type: Type of event
        user_id: User ID
        payload: Event data
        source: Event source
        metadata: Additional metadata
    """
    event = Event(
        event_type=event_type,
        user_id=user_id,
        payload=payload or {},
        source=source,
        metadata=metadata or {}
    )

    await event_bus.publish(event)


# Context manager for event bus lifecycle
class EventBusContext:
    """Context manager for event bus"""

    async def __aenter__(self):
        await event_bus.connect()
        await event_bus.start_listening()
        return event_bus

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await event_bus.disconnect()
