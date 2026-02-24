"""
Reactive Engine — Real-Time Event-Driven Responses

Subscribes to the Redis event bus and reacts to HA events immediately,
replacing some polling-based checks in the heartbeat.

Subscribers:
  - SecuritySubscriber: quiet-hours door/motion → urgent notification
  - ComfortSubscriber: temperature changes → standing order evaluation
  - PresenceSubscriber: motion → room presence + away/return detection
  - AnomalySubscriber: unusual patterns → observation + optional alert

Each subscriber is lightweight and non-blocking. Heavy actions (LLM calls,
complex decisions) are delegated to the heartbeat or Celery tasks.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from zoneinfo import ZoneInfo

from app.services.event_bus import EventBus, Event, EventType, EventSubscriber

logger = logging.getLogger(__name__)

USER_TZ = ZoneInfo("America/New_York")
DAVID_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


class SecuritySubscriber(EventSubscriber):
    """
    Reacts to security-relevant events:
    - Door/window opened during quiet hours → urgent notification
    - Motion detected when David is marked AWAY → alert
    - Lock unlocked at unusual times → notification
    """

    def __init__(self):
        super().__init__("security")
        self.subscribe_to(
            EventType.HOME_DOOR_CHANGED,
            EventType.HOME_ANOMALY_DETECTED,
        )
        # Rate limit: don't spam for repeated door events
        self._last_alert: Dict[str, datetime] = {}
        self._alert_cooldown = timedelta(minutes=10)

    async def handle_event(self, event: Event) -> None:
        entity = event.payload.get("entity_id", "")
        now = datetime.now(USER_TZ)

        # Rate limit per entity
        last = self._last_alert.get(entity)
        if last and (now - last) < self._alert_cooldown:
            return

        if event.event_type == EventType.HOME_DOOR_CHANGED:
            if event.payload.get("opened") and self._is_quiet_hours(now):
                location = event.payload.get('location', entity)
                time_str = now.strftime('%I:%M %p')
                title, message = await self._compose_or_fallback(
                    event_type="door_opened_quiet_hours",
                    event_context={"location": location, "time": time_str},
                    fallback_title="Door opened (quiet hours)",
                    fallback_message=f"{location} opened at {time_str}",
                )
                await self._send_security_alert(
                    title=title,
                    message=message,
                    topic=f"security:door_{entity}_{now.strftime('%Y%m%d')}",
                )
                self._last_alert[entity] = now

        elif event.event_type == EventType.HOME_ANOMALY_DETECTED:
            description = event.payload.get("description", "Unknown anomaly")
            title, message = await self._compose_or_fallback(
                event_type="home_anomaly",
                event_context={"description": description},
                fallback_title="Home anomaly detected",
                fallback_message=description,
            )
            await self._send_security_alert(
                title=title,
                message=message,
                topic=f"security:anomaly_{now.strftime('%Y%m%d_%H')}",
            )
            self._last_alert[entity] = now

    async def _compose_or_fallback(
        self,
        event_type: str,
        event_context: Dict,
        fallback_title: str,
        fallback_message: str,
    ) -> tuple:
        """Use notification composer for Sara-voice text, fall back to hardcoded."""
        try:
            from app.services.notification_composer import compose_reactive_notification
            from app.services.thread_manager import get_open_threads_summary
            from app.services.unified_context import read_snapshot

            snapshot = await read_snapshot(DAVID_USER_ID)
            threads = await get_open_threads_summary(DAVID_USER_ID)
            composed = await compose_reactive_notification(
                event_type=event_type,
                event_context=event_context,
                open_threads=threads,
                snapshot=snapshot,
            )
            return composed["title"], composed["message"]
        except Exception as e:
            logger.debug(f"Notification composer failed, using fallback: {e}")
            return fallback_title, fallback_message

    def _is_quiet_hours(self, now: datetime) -> bool:
        return now.hour >= 23 or now.hour < 5

    async def _send_security_alert(self, title: str, message: str, topic: str):
        """Send via interruptibility-aware pipeline with URGENT urgency."""
        try:
            from app.services.unified_notification import send_notification_with_interruptibility
            await send_notification_with_interruptibility(
                user_id=DAVID_USER_ID,
                title=title,
                message=message,
                urgency="urgent",
                topic=topic,
                category="security",
                source="reactive_engine",
                deliver_by_minutes=30,
            )
            # Record action in agent memory + unified context changes
            try:
                from app.services.context_writer import append_change
                await append_change(DAVID_USER_ID, f"Security alert: {title}")
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Security alert failed: {e}")


class ComfortSubscriber(EventSubscriber):
    """
    Reacts to comfort-related events:
    - Temperature changes → evaluate standing orders for climate control
    - Climate system state changes → log for pattern detection
    """

    def __init__(self):
        super().__init__("comfort")
        self.subscribe_to(EventType.HOME_CLIMATE_CHANGED)
        self._last_check = None
        self._check_cooldown = timedelta(minutes=15)

    async def handle_event(self, event: Event) -> None:
        now = datetime.now(USER_TZ)

        # Ignore unavailable climate entities (removed devices)
        hvac_mode = event.payload.get("hvac_mode")
        if hvac_mode in ("unavailable", "unknown"):
            return

        # Don't evaluate too frequently
        if self._last_check and (now - self._last_check) < self._check_cooldown:
            return

        current_temp = event.payload.get("current_temperature")
        target_temp = event.payload.get("temperature")

        if current_temp is not None:
            self._last_check = now
            # Evaluate standing orders for climate
            try:
                from app.services.standing_order_service import standing_order_service
                await standing_order_service.evaluate_trigger(
                    trigger_type="climate",
                    context={
                        "current_temperature": current_temp,
                        "target_temperature": target_temp,
                        "hvac_mode": hvac_mode,
                        "entity_id": event.payload.get("entity_id"),
                    },
                )
            except ImportError:
                pass  # Standing orders not yet implemented
            except Exception as e:
                logger.debug(f"Standing order eval failed: {e}")


class PresenceSubscriber(EventSubscriber):
    """
    Tracks household occupancy from motion sensors.

    IMPORTANT: Motion sensors can't distinguish between David, Amanda, kids,
    or dogs. We only track "is someone home" (occupancy), NOT "where David is."
    """

    def __init__(self):
        super().__init__("presence")
        self.subscribe_to(EventType.HOME_MOTION_DETECTED)
        self._room_motion: Dict[str, datetime] = {}
        self._home_empty = False
        self._no_motion_threshold = timedelta(minutes=90)  # Longer — pets/family trigger sensors

    async def handle_event(self, event: Event) -> None:
        if not event.payload.get("detected"):
            return

        room = event.payload.get("room", "unknown")
        now = datetime.now(USER_TZ)
        self._room_motion[room] = now

        # If home was previously flagged as empty and we see motion,
        # update occupancy (but don't assume it's David specifically)
        if self._home_empty:
            self._home_empty = False
            logger.info(f"Home occupancy detected (motion in {room})")

            try:
                from app.services.context_writer import update_fields
                await update_fields(DAVID_USER_ID, source="reactive_engine", home_occupied=True)
            except Exception:
                pass

    def check_away_status(self) -> bool:
        """Check if house appears empty (no motion for a long time).
        Can't determine if David specifically is away — only that no one is moving."""
        now = datetime.now(USER_TZ)
        if not self._room_motion:
            return False

        latest = max(self._room_motion.values())
        if (now - latest) > self._no_motion_threshold:
            if not self._home_empty:
                self._home_empty = True
                logger.info(f"House appears empty (no motion for {self._no_motion_threshold})")
            return True
        return False

    def get_current_room(self) -> Optional[str]:
        """Get room with most recent motion. NOTE: could be anyone, not necessarily David."""
        return None  # Don't report room — can't know it's David


class LightSubscriber(EventSubscriber):
    """
    Tracks light state for pattern observation.
    Detects lights left on late at night.
    """

    def __init__(self):
        super().__init__("lights")
        self.subscribe_to(EventType.HOME_LIGHT_CHANGED)
        self._notified_today = set()

    async def handle_event(self, event: Event) -> None:
        now = datetime.now(USER_TZ)
        entity = event.payload.get("entity_id", "")
        to_state = event.payload.get("to_state", "")

        # Late night lights-on check (after midnight, before 5am)
        if to_state == "on" and (now.hour >= 0 and now.hour < 5):
            date_key = f"{entity}_{now.strftime('%Y%m%d')}"
            if date_key not in self._notified_today:
                # Don't notify, just note as observation for heartbeat
                logger.info(f"Light on at {now.strftime('%H:%M')}: {entity}")
                self._notified_today.add(date_key)

        # Clean old entries daily
        if now.hour == 6:
            self._notified_today.clear()


class TimerSubscriber(EventSubscriber):
    """
    Reacts to timer completion events.
    Evaluates standing orders with trigger_type='timer' — enables
    patterns like "turn heater on for 1 hour" (timer + one-shot standing order).
    """

    def __init__(self):
        super().__init__("timer")
        self.subscribe_to(EventType.TIMER_COMPLETED)

    async def handle_event(self, event: Event) -> None:
        timer_title = event.payload.get("timer_title", "")
        timer_id = event.payload.get("timer_id", "")
        duration = event.payload.get("duration_minutes", 0)

        logger.info(f"Timer completed: '{timer_title}' ({duration}m) — evaluating standing orders")

        try:
            from app.services.standing_order_service import standing_order_service
            from app.db.session import SessionLocal
            db = SessionLocal()
            try:
                executed = await standing_order_service.evaluate_trigger(
                    trigger_type="timer",
                    context={
                        "timer_id": timer_id,
                        "timer_title": timer_title,
                        "duration_minutes": duration,
                    },
                    db=db,
                )
                if executed:
                    logger.info(f"Timer trigger executed {len(executed)} standing order(s): "
                                f"{[e['description'] for e in executed]}")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Timer standing order evaluation failed: {e}")


class AgentTaskProgressSubscriber(EventSubscriber):
    """
    Forwards AGENT_TASK_PROGRESS events to WebSocket clients
    via the automation stream broadcast.
    """

    def __init__(self):
        super().__init__("agent_task_progress")
        self.subscribe_to(EventType.AGENT_TASK_PROGRESS)

    async def handle_event(self, event: Event) -> None:
        user_id = event.user_id or DAVID_USER_ID
        try:
            from app.routes.automation import broadcast_automation_event
            await broadcast_automation_event(user_id, {
                "type": "agent_task_progress",
                "data": event.payload,
            })
        except Exception as e:
            logger.debug(f"Failed to broadcast agent task progress: {e}")


class ReactiveEngine:
    """
    Manages event subscribers and connects them to the event bus.

    Usage:
        engine = ReactiveEngine(event_bus)
        await engine.start()
        # ... event bus receives events, subscribers react
        await engine.stop()
    """

    def __init__(self, bus: EventBus):
        self.bus = bus
        self.subscribers: List[EventSubscriber] = []

        # Create subscribers
        self.security = SecuritySubscriber()
        self.comfort = ComfortSubscriber()
        self.presence = PresenceSubscriber()
        self.lights = LightSubscriber()
        self.timer = TimerSubscriber()
        self.agent_task_progress = AgentTaskProgressSubscriber()

        self.subscribers = [
            self.security,
            self.comfort,
            self.presence,
            self.lights,
            self.timer,
            self.agent_task_progress,
        ]

        # Working memory subscriber — updates Redis snapshot on every event
        try:
            from app.services.memory_subscribers import WorkingMemorySubscriber
            self.working_memory = WorkingMemorySubscriber()
            self.subscribers.append(self.working_memory)
        except Exception as e:
            logger.warning(f"WorkingMemorySubscriber failed to init: {e}")

        # Salience subscriber — scores events, logs observations, triggers deliberation
        try:
            from app.services.salience_subscriber import SalienceSubscriber
            self.salience = SalienceSubscriber()
            self.subscribers.append(self.salience)
        except Exception as e:
            logger.warning(f"SalienceSubscriber failed to init: {e}")

    async def start(self):
        """Register all subscribers with the event bus."""
        for sub in self.subscribers:
            self.bus.subscribe(sub)
        logger.info(f"Reactive engine started with {len(self.subscribers)} subscribers")

    async def stop(self):
        """Cleanup."""
        logger.info("Reactive engine stopped")

    def get_status(self) -> Dict[str, Any]:
        """Get current status of all subscribers."""
        return {
            "subscribers": len(self.subscribers),
            "current_room": self.presence.get_current_room(),
            "is_away": self.presence._was_away,
            "security_alerts_today": len(self.security._last_alert),
        }


# Global instance (initialized when event bus connects)
_reactive_engine: Optional[ReactiveEngine] = None


def get_reactive_engine() -> Optional[ReactiveEngine]:
    return _reactive_engine


async def start_reactive_engine(bus: EventBus) -> ReactiveEngine:
    """Initialize and start the reactive engine."""
    global _reactive_engine
    _reactive_engine = ReactiveEngine(bus)
    await _reactive_engine.start()
    return _reactive_engine
