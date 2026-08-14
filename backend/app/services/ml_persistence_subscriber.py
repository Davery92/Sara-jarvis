"""Durable persistence for events the ML feature store needs (C1).

DESKTOP_FOCUS_SPAN and VOICE_CONVERSATION_ENDED already flow through the
event bus for salience scoring / working memory, but neither was ever
written to a table — the feature store (feature_store.py) needs real
per-app time-on-task and voice-interaction history, not just a transient
pub/sub pass-through.
"""
import logging
from datetime import datetime, timezone

from app.services.event_bus import Event, EventType, EventSubscriber

logger = logging.getLogger(__name__)


def _parse_ts(value) -> "datetime | None":
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


class MLPersistenceSubscriber(EventSubscriber):
    """Writes DESKTOP_FOCUS_SPAN and VOICE_CONVERSATION_ENDED events to
    durable tables (desktop_focus_span, voice_interaction_log)."""

    def __init__(self):
        super().__init__("ml_persistence")
        self.subscribe_to(
            EventType.DESKTOP_FOCUS_SPAN,
            EventType.VOICE_CONVERSATION_STARTED,
            EventType.VOICE_CONVERSATION_ENDED,
        )
        self._active_voice_start: dict = {}  # user_id -> started_at

    async def handle_event(self, event: Event) -> None:
        try:
            if event.event_type == EventType.DESKTOP_FOCUS_SPAN:
                await self._persist_focus_span(event)
                await self._maybe_prompt_morning_brief(event)
            elif event.event_type == EventType.VOICE_CONVERSATION_STARTED:
                self._active_voice_start[event.user_id] = event.timestamp
            elif event.event_type == EventType.VOICE_CONVERSATION_ENDED:
                await self._persist_voice_interaction(event)
        except Exception as e:
            logger.warning(f"ML persistence subscriber failed on {event.event_type}: {e}")

    async def _maybe_prompt_morning_brief(self, event: Event) -> None:
        """D: one-time HUD prompt on the first desktop activity of the day,
        if it happens before David has seen the morning brief. Uses a
        Redis "already prompted today" flag rather than true read-tracking
        (morning_brief has no seen/read column) — same tell-once pattern as
        task_result_delivery's _already_delivered."""
        from app.core.timezone import now as local_now

        now = local_now()
        if now.hour >= 11:
            return  # not a "just sat down this morning" moment anymore

        try:
            from app.core.redis import get_redis

            redis_client = await get_redis()
            prompt_key = f"sara:morning_brief_prompted:{event.user_id}:{now.date().isoformat()}"
            already_prompted = await redis_client.get(prompt_key)
            if already_prompted:
                return

            from app.db.base import SessionLocal
            from sqlalchemy import text

            def _brief_exists():
                with SessionLocal() as db:
                    row = db.execute(text(
                        "SELECT id FROM morning_brief WHERE user_id = :uid AND brief_date = :d"
                    ), {"uid": event.user_id, "d": now.date()}).fetchone()
                    return row is not None

            import asyncio
            if not await asyncio.to_thread(_brief_exists):
                return

            await redis_client.set(prompt_key, "1", ex=86400)

            from app.services.unified_notification import send_notification
            await send_notification(
                user_id=event.user_id,
                title="Morning brief is ready",
                message="Your morning brief is ready whenever you want it.",
                category="checkin",
                topic=f"morning_brief_prompt:{now.date().isoformat()}",
                source="ml_persistence_subscriber",
                priority="normal",
                overlay={"kind": "brief", "payload": {}},
            )
        except Exception as e:
            logger.debug(f"morning brief prompt skipped: {e}")

    async def _persist_focus_span(self, event: Event) -> None:
        from app.db.session import get_async_session_factory
        from app.models.ml import DesktopFocusSpan

        payload = event.payload
        session_factory = get_async_session_factory()
        async with session_factory() as db:
            db.add(DesktopFocusSpan(
                user_id=event.user_id,
                device_id=payload.get("device_id"),
                app=payload.get("app"),
                window=payload.get("window"),
                domain=payload.get("domain"),
                derived_state=payload.get("derived_state"),
                start_ts=_parse_ts(payload.get("start_ts")),
                end_ts=_parse_ts(payload.get("end_ts")),
                duration_seconds=int(payload.get("duration_seconds") or 0),
                keyboard_events=int(payload.get("keyboard_events") or 0),
                mouse_events=int(payload.get("mouse_events") or 0),
            ))
            await db.commit()

    async def _persist_voice_interaction(self, event: Event) -> None:
        from app.db.session import get_async_session_factory
        from app.models.ml import VoiceInteractionLog

        payload = event.payload
        started_at = self._active_voice_start.pop(event.user_id, None) or event.timestamp
        session_factory = get_async_session_factory()
        async with session_factory() as db:
            db.add(VoiceInteractionLog(
                user_id=event.user_id,
                started_at=started_at,
                ended_at=event.timestamp,
                turns=int(payload.get("turns") or 0),
                duration_seconds=payload.get("duration_seconds"),
                summary=payload.get("summary"),
                source=event.source or "jetson_voice",
            ))
            await db.commit()
