"""
Memory Subscribers — event-driven updates to Sara's working memory.

WorkingMemorySubscriber:
    Subscribes to all event types, updates working memory fields on each event.
    Cheap, no DB queries — just translates event payloads into field updates.

DerivedSignalRefresher:
    Periodic (every 5 min via Celery) for signals that need DB access:
    body state, activity state, habit status, calendar lookahead, learning reviews.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app.services.event_bus import Event, EventType, EventSubscriber
from app.services.working_memory import update_memory

logger = logging.getLogger(__name__)

DAVID_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"
USER_TZ = ZoneInfo("America/New_York")


class WorkingMemorySubscriber(EventSubscriber):
    """
    Subscribes to all relevant events and translates them into
    working memory field updates. Each handler is a single
    update_memory() call — cheap, no DB queries.
    """

    def __init__(self):
        super().__init__("working_memory")
        self.subscribe_to(
            # Home
            EventType.HOME_STATE_CHANGED,
            EventType.HOME_MOTION_DETECTED,
            EventType.HOME_DOOR_CHANGED,
            EventType.HOME_LIGHT_CHANGED,
            EventType.HOME_CLIMATE_CHANGED,
            EventType.HOME_ANOMALY_DETECTED,
            # Activity & presence
            EventType.ACTIVITY_STATE_CHANGED,
            EventType.PRESENCE_ROOM_CHANGED,
            EventType.INTERRUPTIBILITY_CHANGED,
            # Chat
            EventType.CHAT_MESSAGE_RECEIVED,
            # Food & health
            EventType.FOOD_LOGGED,
            EventType.FOOD_DELETED,
            EventType.HEALTH_DATA_SYNCED,
            EventType.RECOVERY_LOGGED,
            # Timer & reminders
            EventType.TIMER_STARTED,
            EventType.TIMER_COMPLETED,
            EventType.TIMER_CANCELLED,
            EventType.REMINDER_CREATED,
            EventType.REMINDER_COMPLETED,
            # Calendar
            EventType.CALENDAR_EVENT_CREATED,
            EventType.CALENDAR_EVENT_UPDATED,
            EventType.CALENDAR_EVENT_DELETED,
            # Notes
            EventType.NOTE_CREATED,
            EventType.NOTE_UPDATED,
            # Workout
            EventType.WORKOUT_LOGGED,
            EventType.WORKOUT_COMPLETED,
            # Context
            EventType.CONTEXT_UPDATED,
        )

    async def handle_event(self, event: Event) -> None:
        try:
            handler = _EVENT_HANDLERS.get(event.event_type)
            if handler:
                await handler(event)
            else:
                logger.debug(f"[WorkingMemory] No handler for {event.event_type.value}")
        except Exception as e:
            logger.warning(f"[WorkingMemory] Handler failed for {event.event_type.value}: {e}")


# ── Event handlers ──────────────────────────────────────────────

async def _handle_activity_state_changed(event: Event):
    payload = event.payload
    await update_memory(
        event.user_id,
        source="activity_state",
        activity_state=payload.get("state", "UNKNOWN"),
        activity_confidence=payload.get("confidence", 0.5),
        room=payload.get("room"),
    )
    await _resurface_snoozed_items(event.user_id, payload.get("state", "UNKNOWN"))


async def _resurface_snoozed_items(user_id: str, new_state: str) -> None:
    """SARA_UNLEASHED Phase T.4: 'Not now' items come back at the NEXT
    context change, not on a fixed timer and not as a duplicate. Flips
    status back to 'sent' only for items snoozed from a DIFFERENT context
    than the one David just entered — snoozing during 'focused' and
    immediately re-checking while still 'focused' must not instantly
    resurface the same item."""
    try:
        from sqlalchemy import text as _text
        from app.services.subconscious import resolve_context
        from app.db.session import get_async_session_factory

        current_context = resolve_context(new_state)
        factory = get_async_session_factory()
        async with factory() as db:
            result = await db.execute(_text("""
                UPDATE outbox_item
                SET status = 'sent', updated_at = NOW()
                WHERE user_id = :uid
                  AND status = 'snoozed'
                  AND COALESCE(payload->>'snoozed_from_context', '') != :ctx
            """), {"uid": user_id, "ctx": current_context})
            await db.commit()
            if result.rowcount:
                logger.info(f"Resurfaced {result.rowcount} snoozed attention item(s) on context change -> {current_context}")
    except Exception as e:
        logger.debug(f"Snoozed-item resurface check failed: {e}")


async def _handle_interruptibility_changed(event: Event):
    await update_memory(
        event.user_id,
        source="interruptibility",
        interruptibility=event.payload.get("score", 0.5),
    )


async def _handle_presence_room_changed(event: Event):
    await update_memory(
        event.user_id,
        source="presence",
        room=event.payload.get("room"),
    )


async def _handle_chat_message(event: Event):
    now = datetime.now(USER_TZ)
    topic = event.payload.get("topic")
    fields = {
        "last_chat_at": now.isoformat(),
        "hours_since_last_chat": 0.0,
        "has_chatted_today": True,
    }
    if topic:
        fields["last_chat_topic"] = topic
    await update_memory(event.user_id, source="chat", **fields)


async def _handle_food_logged(event: Event):
    # A logged meal is contact with the app even without a heartbeat (Siri /
    # chat-tool logging), so bump last_app_activity_at too.
    now = datetime.now(USER_TZ)
    await update_memory(
        event.user_id,
        source="food",
        hours_since_last_meal=0.0,
        last_meal_type=event.payload.get("meal_type", "meal"),
        last_app_activity_at=now.isoformat(),
        hours_since_app_activity=0.0,
    )


async def _handle_food_deleted(event: Event):
    pass  # DerivedSignalRefresher will recalculate next cycle


async def _handle_home_climate(event: Event):
    payload = event.payload
    fields = {}
    temp = payload.get("temperature")
    if temp is not None:
        if "outside" in payload.get("entity_id", ""):
            fields["temperature_outside"] = temp
        else:
            fields["temperature_inside"] = temp
    if fields:
        await update_memory(event.user_id, source="climate", **fields)


async def _handle_home_motion(event: Event):
    room = event.payload.get("room") or event.payload.get("entity_id", "")
    if room:
        await update_memory(
            event.user_id,
            source="motion",
            home_occupied=True,
        )


async def _handle_home_door(event: Event):
    pass  # Handled by salience subscriber for security; no state field to update


async def _handle_home_light(event: Event):
    pass  # Informational, tracked by salience subscriber


async def _handle_home_state(event: Event):
    """Generic HA state change — extract occupancy if available."""
    payload = event.payload
    entity = payload.get("entity_id", "")

    # Track weather if it's a weather entity
    if "weather" in entity:
        condition = payload.get("to_state")
        if condition:
            await update_memory(event.user_id, source="ha", weather_condition=condition)


async def _handle_timer_completed(event: Event):
    pass  # Informational, tracked by salience subscriber


async def _handle_reminder_completed(event: Event):
    pass  # Could update schedule; handled by DerivedSignalRefresher


async def _handle_calendar_event(event: Event):
    """Calendar event created/updated — refresh next event if relevant."""
    payload = event.payload
    start_time_str = payload.get("start_time")
    title = payload.get("title")
    if start_time_str and title:
        try:
            start = datetime.fromisoformat(start_time_str)
            if start.tzinfo is None:
                start = start.replace(tzinfo=USER_TZ)
            now = datetime.now(USER_TZ)
            minutes_away = int((start - now).total_seconds() / 60)
            if 0 < minutes_away < 1440:  # within 24 hours
                await update_memory(
                    event.user_id,
                    source="calendar",
                    next_event_title=title,
                    next_event_minutes_away=minutes_away,
                )
        except (ValueError, TypeError):
            pass


async def _handle_note_event(event: Event):
    """Note created/updated — track recent notes."""
    title = event.payload.get("title", "untitled")
    await update_memory(
        event.user_id,
        source="notes",
        recent_notes_summary=f"Note edited: {title[:50]}",
    )


async def _handle_workout(event: Event):
    # Logging/finishing a workout is app activity even without a heartbeat.
    now = datetime.now(USER_TZ)
    await update_memory(
        event.user_id,
        source="workout",
        last_app_activity_at=now.isoformat(),
        hours_since_app_activity=0.0,
    )


async def _handle_health_synced(event: Event):
    pass  # DerivedSignalRefresher handles body state


async def _handle_context_updated(event: Event):
    pass  # Already in Redis via context_writer


# Handler dispatch table
_EVENT_HANDLERS = {
    EventType.ACTIVITY_STATE_CHANGED: _handle_activity_state_changed,
    EventType.INTERRUPTIBILITY_CHANGED: _handle_interruptibility_changed,
    EventType.PRESENCE_ROOM_CHANGED: _handle_presence_room_changed,
    EventType.CHAT_MESSAGE_RECEIVED: _handle_chat_message,
    EventType.FOOD_LOGGED: _handle_food_logged,
    EventType.FOOD_DELETED: _handle_food_deleted,
    EventType.HOME_CLIMATE_CHANGED: _handle_home_climate,
    EventType.HOME_MOTION_DETECTED: _handle_home_motion,
    EventType.HOME_DOOR_CHANGED: _handle_home_door,
    EventType.HOME_LIGHT_CHANGED: _handle_home_light,
    EventType.HOME_STATE_CHANGED: _handle_home_state,
    EventType.HOME_ANOMALY_DETECTED: _handle_home_state,
    EventType.TIMER_STARTED: _handle_timer_completed,
    EventType.TIMER_COMPLETED: _handle_timer_completed,
    EventType.TIMER_CANCELLED: _handle_timer_completed,
    EventType.REMINDER_CREATED: _handle_reminder_completed,
    EventType.REMINDER_COMPLETED: _handle_reminder_completed,
    EventType.CALENDAR_EVENT_CREATED: _handle_calendar_event,
    EventType.CALENDAR_EVENT_UPDATED: _handle_calendar_event,
    EventType.CALENDAR_EVENT_DELETED: _handle_calendar_event,
    EventType.NOTE_CREATED: _handle_note_event,
    EventType.NOTE_UPDATED: _handle_note_event,
    EventType.WORKOUT_LOGGED: _handle_workout,
    EventType.WORKOUT_COMPLETED: _handle_workout,
    EventType.HEALTH_DATA_SYNCED: _handle_health_synced,
    EventType.RECOVERY_LOGGED: _handle_health_synced,
    EventType.CONTEXT_UPDATED: _handle_context_updated,
}


# ── DerivedSignalRefresher ────────────────────────────────────────

async def refresh_derived_signals(user_id: str = DAVID_USER_ID) -> dict:
    """
    Periodic refresh of signals that require DB queries.
    Called by Celery task every 5 minutes.
    Returns dict of what was updated for logging.
    """
    import os
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text

    database_url = os.getenv("DATABASE_URL", "")
    if database_url.startswith("postgresql://"):
        async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    elif database_url.startswith("postgresql+psycopg://"):
        async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    else:
        async_url = database_url

    updated = {}

    # 1. Body state estimation (needs sync DB session — service uses sync execute)
    try:
        import os as _os
        from sqlalchemy import create_engine as _ce
        from sqlalchemy.orm import sessionmaker as _sm, Session as _S

        _db_url = _os.getenv("DATABASE_URL", "")
        # Ensure sync psycopg driver
        if "+asyncpg" in _db_url:
            _db_url = _db_url.replace("+asyncpg", "+psycopg")
        elif "+psycopg" not in _db_url and "postgresql://" in _db_url:
            _db_url = _db_url.replace("postgresql://", "postgresql+psycopg://")

        _eng = _ce(_db_url, echo=False)
        _sess = _sm(_eng, class_=_S, expire_on_commit=False)
        try:
            _db = _sess()
            try:
                from app.services.body_state_service import body_state_service
                estimate = await body_state_service.estimate_body_state(
                    db=_db, user_id=user_id
                )
                if estimate:
                    await update_memory(
                        user_id,
                        source="derived_refresh",
                        alertness=estimate.alertness,
                        stress_load=estimate.stress_load,
                        blood_sugar=estimate.blood_sugar,
                        circadian_phase=estimate.circadian_phase,
                    )
                    updated["body_state"] = True
            finally:
                _db.close()
        finally:
            _eng.dispose()
    except Exception as e:
        logger.warning(f"[DerivedRefresh] Body state failed: {e}")

    # 1b. Rhythm deviations — reuses the same sync session pattern as body
    # state. Emits a CONTEXT_UPDATED event (modest salience, see salience.py)
    # only the first time a given rhythm_key deviates today — anti-nag guard.
    try:
        import os as _os2
        from sqlalchemy import create_engine as _ce2
        from sqlalchemy.orm import sessionmaker as _sm2, Session as _S2

        _db_url2 = _os2.getenv("DATABASE_URL", "")
        if "+asyncpg" in _db_url2:
            _db_url2 = _db_url2.replace("+asyncpg", "+psycopg")
        elif "+psycopg" not in _db_url2 and "postgresql://" in _db_url2:
            _db_url2 = _db_url2.replace("postgresql://", "postgresql+psycopg://")

        _eng2 = _ce2(_db_url2, echo=False)
        _sess2 = _sm2(_eng2, class_=_S2, expire_on_commit=False)
        try:
            _db2 = _sess2()
            try:
                from app.services.daily_rhythm import get_off_rhythm_flags
                from app.services.working_memory import read_memory

                memory = await read_memory(user_id)
                flags = get_off_rhythm_flags(_db2, user_id, current_place_type=memory.current_place_type)

                if flags:
                    from app.services.unified_context import _get_redis
                    from app.services.event_bus import emit_event, EventType
                    from app.core.timezone import today as local_today

                    r = await _get_redis()
                    today_str = local_today().isoformat()
                    for flag in flags:
                        dedup_key = f"sara:rhythm_deviation_emitted:{user_id}:{flag['key']}:{today_str}"
                        newly_set = await r.set(dedup_key, "1", ex=60 * 60 * 30, nx=True)
                        if newly_set:  # NX SET returns truthy only the first time today for this key
                            await emit_event(
                                EventType.CONTEXT_UPDATED,
                                user_id,
                                payload={"rhythm_deviation": True, "key": flag["key"], "message": flag["message"]},
                                source="daily_rhythm",
                            )
                    updated["rhythm_deviation"] = [f["key"] for f in flags]
            finally:
                _db2.close()
        finally:
            _eng2.dispose()
    except Exception as e:
        logger.warning(f"[DerivedRefresh] Rhythm deviation failed: {e}")

    # 2. Activity state recomputation (in-memory singleton, no DB)
    try:
        from app.services.activity_state_machine import activity_state_machine
        snapshot = activity_state_machine.current
        if snapshot:
            await update_memory(
                user_id,
                source="derived_refresh",
                activity_state=snapshot.state.value if hasattr(snapshot.state, 'value') else str(snapshot.state),
                activity_confidence=snapshot.confidence,
            )
            updated["activity_state"] = True
    except Exception as e:
        logger.warning(f"[DerivedRefresh] Activity state failed: {e}")

    # 2b. App-presence reaper + freshness (Redis-only, no DB). Flips app_active
    # off when all client TTLs expire and recomputes hours_since_app_activity.
    try:
        from app.routes.presence import reap_app_presence
        app_result = await reap_app_presence(user_id)
        if app_result:
            updated["app_presence"] = app_result
    except Exception as e:
        logger.warning(f"[DerivedRefresh] App presence reaper failed: {e}")

    # DB-dependent signals — each in its own session to prevent cascade failures
    try:
        engine = create_async_engine(async_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # 3. Hours since last chat
        try:
            async with async_session() as db:
                result = await db.execute(text("""
                    SELECT MAX(created_at) as last_chat
                    FROM episode WHERE user_id = :uid AND role = 'user'
                """), {"uid": user_id})
                row = result.fetchone()
                if row and row.last_chat:
                    last_chat = row.last_chat if row.last_chat.tzinfo else row.last_chat.replace(tzinfo=timezone.utc)
                    delta_hours = (datetime.now(timezone.utc) - last_chat).total_seconds() / 3600
                    now_tz = datetime.now(USER_TZ)
                    last_chat_local = last_chat.astimezone(USER_TZ)
                    await update_memory(
                        user_id,
                        source="derived_refresh",
                        last_chat_at=last_chat_local.isoformat(),
                        hours_since_last_chat=round(delta_hours, 1),
                        has_chatted_today=(last_chat_local.date() == now_tz.date()),
                    )
                    updated["hours_since_last_chat"] = round(delta_hours, 1)
        except Exception as e:
            logger.warning(f"[DerivedRefresh] Last chat failed: {e}")

        # 4. Hours since last meal
        try:
            async with async_session() as db:
                result = await db.execute(text("""
                    SELECT meal_type, logged_at FROM food_log
                    WHERE user_id = :uid ORDER BY logged_at DESC LIMIT 1
                """), {"uid": user_id})
                row = result.fetchone()
                if row and row.logged_at:
                    logged_at = row.logged_at if row.logged_at.tzinfo else row.logged_at.replace(tzinfo=timezone.utc)
                    delta_hours = (datetime.now(timezone.utc) - logged_at).total_seconds() / 3600
                    await update_memory(
                        user_id,
                        source="derived_refresh",
                        hours_since_last_meal=round(delta_hours, 1),
                        last_meal_type=row.meal_type,
                    )
                    updated["hours_since_last_meal"] = round(delta_hours, 1)
        except Exception as e:
            logger.warning(f"[DerivedRefresh] Last meal failed: {e}")

        # 5. Habit status — removed (SARA_UNLEASHED Phase U.3). The `habits`
        # vertical (6 tables, 5 UI components) was dead: zero live rows,
        # unreachable from any nav/palette entry. Habits are now modeled as
        # recurring commitment threads instead of a separate behavior system.
        # `today_habit_status` stays in working memory as a harmless unset
        # field — downstream readers already guard on it being falsy.

        # 6. Learning reviews due — disabled (not actively used)
        # Kept the field in working memory but no longer counted/surfaced.

        # 7. Calendar lookahead
        try:
            async with async_session() as db:
                now_tz = datetime.now(USER_TZ)
                # Strip timezone for naive DB columns
                now_naive = now_tz.replace(tzinfo=None)
                today_end = now_naive.replace(hour=23, minute=59, second=59)

                result = await db.execute(text("""
                    SELECT title, start_time FROM calendar_event
                    WHERE user_id = :uid AND start_time > :now AND start_time <= :end
                    ORDER BY start_time ASC LIMIT 1
                """), {"uid": user_id, "now": now_naive, "end": today_end})
                row = result.fetchone()
                if row:
                    start_time = row.start_time
                    if start_time.tzinfo is None:
                        start_time = start_time.replace(tzinfo=USER_TZ)
                    minutes_away = int((start_time - now_tz).total_seconds() / 60)
                    await update_memory(
                        user_id,
                        source="derived_refresh",
                        next_event_title=row.title,
                        next_event_minutes_away=max(0, minutes_away),
                    )
                    updated["next_event"] = row.title
                else:
                    # Explicitly clear stale event context once event has passed.
                    await update_memory(
                        user_id,
                        source="derived_refresh",
                        next_event_title=None,
                        next_event_minutes_away=None,
                    )
                    updated["next_event"] = None

                # Today's event count
                today_start = now_naive.replace(hour=0, minute=0, second=0, microsecond=0)
                count_result = await db.execute(text("""
                    SELECT COUNT(*) FROM calendar_event
                    WHERE user_id = :uid AND start_time BETWEEN :s AND :e
                """), {"uid": user_id, "s": today_start, "e": today_end})
                event_count = count_result.scalar() or 0
                await update_memory(
                    user_id,
                    source="derived_refresh",
                    events_today_count=event_count,
                )
        except Exception as e:
            logger.warning(f"[DerivedRefresh] Calendar failed: {e}")

        # 8. Notification count today
        try:
            async with async_session() as db:
                now_tz = datetime.now(USER_TZ)
                today_start = now_tz.replace(hour=0, minute=0, second=0, microsecond=0)
                result = await db.execute(text("""
                    SELECT COUNT(*) FROM notification_log
                    WHERE user_id = :uid AND sent_at >= :today AND sent = TRUE
                """), {"uid": user_id, "today": today_start})
                count = result.scalar() or 0
                await update_memory(
                    user_id,
                    source="derived_refresh",
                    notifications_sent_today=count,
                )
                updated["notifications_today"] = count
        except Exception as e:
            logger.warning(f"[DerivedRefresh] Notification count failed: {e}")

        # 9. Clear stale handoff/watch text when no active work remains
        try:
            from app.services.observation_log import get_observation_count
            from app.services.working_memory import read_memory

            async with async_session() as db:
                mission_result = await db.execute(text("""
                    SELECT COUNT(*) FROM autonomy_mission
                    WHERE user_id = :uid
                      AND state IN ('pending', 'running', 'awaiting_confirm')
                """), {"uid": user_id})
                active_missions = mission_result.scalar() or 0

            pending_observations = await get_observation_count(user_id)
            memory = await read_memory(user_id)
            no_active_work = active_missions == 0 and pending_observations == 0
            stale_watch_present = bool(memory.last_heartbeat_watching_for or memory.last_heartbeat_handoff)
            stale_focus_present = bool(memory.sara_focus or memory.sara_curiosities)

            if no_active_work and (stale_watch_present or stale_focus_present):
                await update_memory(
                    user_id,
                    source="derived_refresh",
                    last_heartbeat_watching_for=None,
                    last_heartbeat_handoff=None,
                    sara_focus=None,
                    sara_curiosities=None,
                )
                updated["watch_cleanup"] = True
        except Exception as e:
            logger.warning(f"[DerivedRefresh] Watch cleanup failed: {e}")

        # 10. Reset daily deliberation count at midnight
        try:
            now_tz = datetime.now(USER_TZ)
            if now_tz.hour == 0 and now_tz.minute < 6:  # within first 5-min window after midnight
                await update_memory(
                    user_id,
                    source="derived_refresh",
                    sara_deliberation_count_today=0,
                )
                updated["reset_deliberation_count"] = True
        except Exception:
            pass

        # 11. Emotional state decay — naturally decay Sara's emotions toward attentive baseline
        try:
            from app.services.working_memory import read_memory
            from app.services.emotional_state import decay_emotional_state, BASELINE_TONE

            memory = await read_memory(user_id)
            current_tone = memory.sara_emotional_tone
            current_intensity = memory.sara_emotional_intensity if memory.sara_emotional_intensity else 0.3

            if current_tone and current_tone != BASELINE_TONE and current_intensity > 0.35:
                # Calculate hours since last deliberation
                hours_since = 0.083  # default ~5 min (one refresh cycle)
                if memory.sara_last_deliberation_at:
                    try:
                        last_dt = datetime.fromisoformat(memory.sara_last_deliberation_at)
                        if last_dt.tzinfo is None:
                            last_dt = last_dt.replace(tzinfo=timezone.utc)
                        hours_since = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
                    except Exception:
                        pass

                decayed = decay_emotional_state(current_tone, current_intensity, hours_since)
                if decayed.intensity != current_intensity or decayed.tone != current_tone:
                    await update_memory(
                        user_id,
                        source="derived_refresh",
                        sara_emotional_tone=decayed.tone,
                        sara_emotional_intensity=decayed.intensity,
                    )
                    updated["emotional_decay"] = f"{current_tone}({current_intensity:.2f}) -> {decayed.tone}({decayed.intensity:.2f})"
        except Exception as e:
            logger.warning(f"[DerivedRefresh] Emotional decay failed: {e}")

        await engine.dispose()

    except Exception as e:
        logger.error(f"[DerivedRefresh] Engine creation failed: {e}")

    logger.info(f"[DerivedRefresh] Updated: {list(updated.keys())}")
    return updated


class MemoryAccessSubscriber(EventSubscriber):
    """
    Boosts rating_boost and recall_relevance_ema for episodes injected into chat context.
    Creates a positive feedback loop: frequently-useful memories surface more often.
    """

    BOOST_INCREMENT = 0.05  # Per citation
    EMA_ALPHA = 0.15  # EMA smoothing factor (higher = more responsive)

    def __init__(self):
        super().__init__("memory_access_boost")
        self.subscribe_to(EventType.MEMORY_ACCESSED)

    async def handle_event(self, event: Event) -> None:
        episode_ids = event.payload.get("episode_ids", [])
        if not episode_ids:
            return

        try:
            import os
            from sqlalchemy import create_engine, text
            from sqlalchemy.orm import sessionmaker, Session

            db_url = os.getenv("DATABASE_URL", "")
            if "+asyncpg" in db_url:
                db_url = db_url.replace("+asyncpg", "+psycopg")
            elif "+psycopg" not in db_url and "postgresql://" in db_url:
                db_url = db_url.replace("postgresql://", "postgresql+psycopg://")

            engine = create_engine(db_url, echo=False)
            _Session = sessionmaker(engine, class_=Session, expire_on_commit=False)
            db = _Session()
            try:
                # Boost rating_boost and nudge recall_relevance_ema toward 1.0 (positive signal)
                db.execute(text("""
                    UPDATE episode
                    SET rating_boost = LEAST(COALESCE(rating_boost, 0) + :boost, 1.0),
                        recall_relevance_ema = COALESCE(recall_relevance_ema, 0.5) * (1 - :alpha) + 1.0 * :alpha
                    WHERE id = ANY(:ids)
                """), {"boost": self.BOOST_INCREMENT, "alpha": self.EMA_ALPHA, "ids": episode_ids})
                db.commit()
                logger.info(f"[MemoryAccess] Boosted {len(episode_ids)} cited episodes (rating +{self.BOOST_INCREMENT}, EMA → 1.0)")
            finally:
                db.close()
                engine.dispose()
        except Exception as e:
            logger.warning(f"[MemoryAccess] Rating boost failed: {e}")
