"""
ACS Celery tasks — lifecycle management for autonomous cognition sessions.

Runs every 2 minutes to:
- Auto-start sessions when cooldown expires
- Enforce max session duration
- Detect idle → cooldown transitions
- Crash recovery
- Post-conversation curiosity extraction
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime

from app.celery_app import celery_app
from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)

# Default user ID (single-user system)
DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


def _run_async(coro):
    """Run an async function from sync Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@celery_app.task(
    name="app.tasks.acs.run_acs_session",
    bind=True,
    max_retries=0,
    soft_time_limit=21600,  # 6h soft limit
    time_limit=21660,       # 6h + 60s grace
)
def run_acs_session(self, user_id: str, model_id: str = None):
    """Run an ACS session as a dedicated long-running Celery task.

    This ensures the asyncio event loop stays alive for the entire session
    instead of being abandoned when the lifecycle check returns.
    """
    try:
        _run_async(_run_session(user_id, model_id))
    except Exception as e:
        logger.error(f"ACS session task failed: {e}", exc_info=True)
        # Make sure state is cleaned up on unexpected failure
        try:
            _run_async(_emergency_cleanup(user_id, str(e)[:500]))
        except Exception:
            pass


async def _run_session(user_id: str, model_id: str = None):
    """Start and await an ACS session to completion."""
    try:
        from app.services.acs.session_manager import start_session_and_run
        await start_session_and_run(user_id, model_id=model_id)
    finally:
        # Clear the dispatch lock so the next session can be dispatched
        import redis.asyncio as aioredis
        try:
            r = await aioredis.from_url(
                os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                decode_responses=True,
            )
            await r.delete(f"sara:acs:session_dispatching:{user_id}")
            if hasattr(r, "aclose"):
                await r.aclose()
            else:
                await r.close()
        except Exception:
            pass


async def _emergency_cleanup(user_id: str, error: str):
    """Emergency cleanup if the session task fails outside the normal flow.

    Cleans up both the Redis-tracked active session AND any DB sessions
    stuck in 'autonomous' state for this user (catches cases where the
    state machine already transitioned but the DB record was orphaned).
    """
    from app.services.acs import state_machine
    from app.services.acs.state_machine import ACSState
    from app.db.session import get_async_session_factory
    from sqlalchemy import text

    async_session = get_async_session_factory()

    # 1. Clean up the Redis-tracked active session (if any)
    current = await state_machine.get_state(user_id)
    if current in (ACSState.AUTONOMOUS, ACSState.PAUSING):
        session_id = await state_machine.get_active_session_id(user_id)
        if session_id:
            async with async_session() as db:
                await db.execute(text("""
                    UPDATE acs_session
                    SET state = 'ended', ended_at = NOW(), end_reason = 'task_crash',
                        error_log = :err
                    WHERE id = :sid AND state = 'autonomous'
                """), {"sid": session_id, "err": error})
                await db.commit()

    # 2. Catch any orphaned sessions not tracked in Redis — this handles the
    #    case where start_session created the DB record but the task crashed
    #    before _run_loop even started (or before state machine was updated).
    async with async_session() as db:
        result = await db.execute(text("""
            UPDATE acs_session
            SET state = 'ended', ended_at = NOW(), end_reason = 'task_crash',
                error_log = :err
            WHERE user_id = :uid AND state = 'autonomous' AND ended_at IS NULL
              AND (turns_completed IS NULL OR turns_completed = 0)
              AND started_at < NOW() - INTERVAL '1 minute'
            RETURNING id
        """), {"uid": user_id, "err": error})
        orphans = result.fetchall()
        if orphans:
            await db.commit()
            logger.info(
                f"Emergency cleanup: ended {len(orphans)} orphaned session(s) "
                f"for user {user_id[:8]}"
            )

    # 3. Release any plan items assigned to dead sessions
    async with async_session() as db:
        await db.execute(text("""
            UPDATE acs_plan_item
            SET status = 'pending', assigned_session_id = NULL, updated_at = NOW()
            WHERE user_id = :uid AND status = 'in_progress'
              AND assigned_session_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM acs_session s
                  WHERE s.id = acs_plan_item.assigned_session_id
                    AND s.state = 'autonomous' AND s.ended_at IS NULL
              )
        """), {"uid": user_id})
        await db.commit()

    await state_machine.set_active_session(user_id, None)
    import redis.asyncio as aioredis
    r = await aioredis.from_url(
        os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )
    try:
        from datetime import timedelta
        until = local_now() + timedelta(minutes=5)
        await r.set(f"sara:acs:cooldown_until:{user_id}", until.isoformat())
        await r.set(f"sara:acs:state:{user_id}", "cooldown")
    finally:
        if hasattr(r, "aclose"):
            await r.aclose()
        else:
            await r.close()
    logger.info(f"ACS emergency cleanup complete for user {user_id[:8]}")


# ── Morning quiet hours: 5:00–7:00 AM ET ──
# No new sessions start, running sessions get stopped, LLM is free for daily plan at 7 AM.
QUIET_HOURS_START = 5   # 5:00 AM ET
QUIET_HOURS_END = 7     # 7:00 AM ET


def _in_quiet_hours() -> bool:
    """Check if we're in the morning quiet window (5-7 AM ET)."""
    from zoneinfo import ZoneInfo
    now_et = datetime.now(ZoneInfo("America/New_York"))
    return QUIET_HOURS_START <= now_et.hour < QUIET_HOURS_END


@celery_app.task(name="app.tasks.acs.acs_morning_winddown", bind=True, max_retries=1)
def acs_morning_winddown(self):
    """5 AM task: stop any running ACS session and consolidate overnight work."""
    try:
        _run_async(_morning_winddown())
    except Exception as e:
        logger.error(f"ACS morning wind-down failed: {e}", exc_info=True)


async def _morning_winddown():
    """Stop ACS, run overnight consolidation, prepare for morning plan."""
    from app.services.acs import state_machine
    from app.services.acs.state_machine import ACSState
    import redis.asyncio as aioredis

    user_id = DEFAULT_USER_ID
    current = await state_machine.get_state(user_id)

    logger.info(f"Morning wind-down starting. ACS state: {current}")

    # Step 1: Stop running session
    if current == ACSState.AUTONOMOUS:
        logger.info("Morning wind-down: stopping ACS session for morning prep")
        from app.services.acs.session_manager import pause_session
        await pause_session(user_id)

        # Wait up to 3 minutes for graceful shutdown
        for i in range(18):
            await asyncio.sleep(10)
            current = await state_machine.get_state(user_id)
            if current != ACSState.AUTONOMOUS:
                logger.info(f"Morning wind-down: ACS stopped after {(i+1)*10}s, state={current}")
                break
        else:
            # Force to cooldown if it didn't stop
            logger.warning("Morning wind-down: ACS didn't stop gracefully, forcing cooldown")
            await state_machine.set_state(user_id, ACSState.COOLDOWN, reason="morning_winddown")

    # Step 2: Set a long cooldown so lifecycle check doesn't restart ACS during quiet hours
    r = await aioredis.from_url(
        os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )
    try:
        from zoneinfo import ZoneInfo
        from datetime import timedelta
        est = ZoneInfo("America/New_York")
        # Cooldown until 7:15 AM ET (after daily plan runs)
        now_et = datetime.now(est)
        wake_time = now_et.replace(hour=QUIET_HOURS_END, minute=15, second=0, microsecond=0)
        if wake_time <= now_et:
            wake_time += timedelta(days=1)

        await r.set(f"sara:acs:cooldown_until:{user_id}", wake_time.isoformat())
        await r.set(f"sara:acs:state:{user_id}", "cooldown")
        await r.set(f"sara:acs:quiet_hours:{user_id}", "1", ex=int((wake_time - now_et).total_seconds()) + 60)

        logger.info(f"Morning wind-down: ACS in quiet hours until {wake_time.strftime('%I:%M %p ET')}")
    finally:
        if hasattr(r, "aclose"):
            await r.aclose()
        else:
            await r.close()

    # Step 3: Run a quick overnight consolidation summary
    # This processes any unshown show_david items and ensures session logs are written
    try:
        from app.db.session import get_async_session_factory
        from sqlalchemy import text
        async_session = get_async_session_factory()

        async with async_session() as db:
            # Count overnight activity
            result = await db.execute(text("""
                SELECT COUNT(*), SUM(turns_completed), SUM(notes_created)
                FROM acs_session
                WHERE user_id = :uid
                  AND started_at > NOW() - INTERVAL '12 hours'
            """), {"uid": user_id})
            row = result.fetchone()
            sessions = row[0] or 0
            turns = row[1] or 0
            notes = row[2] or 0

            # Mark any remaining unshown show_david items as shown
            # (they'll be available in the notifications screen)
            await db.execute(text("""
                UPDATE acs_show_david_buffer
                SET shown = TRUE, shown_at = NOW()
                WHERE user_id = :uid AND shown = FALSE
            """), {"uid": user_id})
            await db.commit()

        logger.info(
            f"Morning wind-down complete: {sessions} overnight sessions, "
            f"{turns} turns, {notes} notes created"
        )
    except Exception as e:
        logger.warning(f"Morning wind-down consolidation failed: {e}")


@celery_app.task(name="app.tasks.acs.acs_lifecycle_check", bind=True, max_retries=0)
def acs_lifecycle_check(self):
    """Periodic lifecycle check for the ACS system."""
    try:
        _run_async(_lifecycle_check())
    except Exception as e:
        logger.error(f"ACS lifecycle check failed: {e}", exc_info=True)


async def _lifecycle_check():
    from app.services.acs import state_machine
    from app.services.acs.state_machine import ACSState

    user_id = DEFAULT_USER_ID

    # Block new sessions during quiet hours (5-7 AM ET)
    if _in_quiet_hours():
        logger.debug("ACS lifecycle: quiet hours active (5-7 AM), skipping")
        return

    current = await state_machine.get_state(user_id)

    if current == ACSState.COOLDOWN:
        # Check if cooldown expired → dispatch a dedicated session task
        expired = await state_machine.is_cooldown_expired(user_id)
        if expired:
            # Check for scheduled intent — if Sara requested a specific start time, respect it
            import redis.asyncio as aioredis
            r = await aioredis.from_url(
                os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                decode_responses=True,
            )
            try:
                intent_key = f"sara:acs:scheduled_intent:{user_id}"
                raw_intent = await r.get(intent_key)
                if raw_intent:
                    import json as _json
                    from datetime import datetime as _dt, timezone as _tz
                    intent = _json.loads(raw_intent)
                    target = _dt.fromisoformat(intent["target_time"])
                    if target.tzinfo is None:
                        target = target.replace(tzinfo=_tz.utc)
                    now_utc = _dt.now(_tz.utc)
                    if now_utc < target:
                        logger.debug(
                            f"ACS scheduled intent: waiting until {target.isoformat()} "
                            f"(in {(target - now_utc).total_seconds() / 60:.0f}min)"
                        )
                        return
                    # Intent time reached — clear it and proceed
                    await r.delete(intent_key)
                    logger.info(f"ACS scheduled intent reached: {intent.get('intent', '')}")

                # Prevent duplicate dispatches — lock lasts long enough for task
                # to be picked up even when the critical worker is busy
                lock_key = f"sara:acs:session_dispatching:{user_id}"
                acquired = await r.set(lock_key, "1", nx=True, ex=900)
                if not acquired:
                    logger.debug("ACS session dispatch already in progress, skipping")
                    return
            finally:
                if hasattr(r, "aclose"):
                    await r.aclose()
                else:
                    await r.close()

            logger.info("ACS cooldown expired, dispatching session task")
            run_acs_session.apply_async(
                args=[user_id],
                queue="acs",
                expires=300,
            )

    elif current == ACSState.AUTONOMOUS:
        # Check if session exceeded max duration or is orphaned
        session_id = await state_machine.get_active_session_id(user_id)
        if session_id:
            from app.db.session import get_async_session_factory
            from app.core.config import settings
            from sqlalchemy import text
            async_session = get_async_session_factory()
            async with async_session() as db:
                result = await db.execute(text(
                    "SELECT started_at, turns_completed, state FROM acs_session WHERE id = :sid"
                ), {"sid": session_id})
                row = result.fetchone()
                if row and row[0]:
                    from app.core.timezone import to_local
                    started = to_local(row[0])
                    elapsed = (local_now() - started).total_seconds() / 60
                    db_state = row[2]
                    turns = row[1] or 0

                    # Check if the session was already ended in DB but Redis wasn't cleaned up
                    if db_state == "ended":
                        logger.warning(f"ACS session {session_id[:8]} ended in DB but Redis state is AUTONOMOUS, recovering")
                        await state_machine.set_active_session(user_id, None)
                        await state_machine.set_state(user_id, ACSState.COOLDOWN, reason="orphaned_session")
                        return

                    # Check for stale session: running > 10 min with 0 turns means the loop died
                    # (e.g. worker restarted, asyncio task orphaned)
                    # BUT: don't kill sessions waiting for HITL (human input) responses
                    STALE_THRESHOLD_MINUTES = 10
                    hitl_pending = False
                    if turns == 0 and elapsed > STALE_THRESHOLD_MINUTES:
                        # Check if session is waiting for a HITL response
                        import redis.asyncio as aioredis
                        r_check = await aioredis.from_url(
                            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                            decode_responses=True,
                        )
                        try:
                            keys = [k async for k in r_check.scan_iter("sara:acs:hitl_pending:*")]
                            for k in keys:
                                val = await r_check.get(k)
                                if val and session_id in val:
                                    hitl_pending = True
                                    logger.info(
                                        f"ACS session {session_id[:8]} has pending HITL request, "
                                        f"skipping stale check (elapsed={elapsed:.0f}min)"
                                    )
                                    break
                        finally:
                            if hasattr(r_check, "aclose"):
                                await r_check.aclose()
                            else:
                                await r_check.close()
                    if turns == 0 and elapsed > STALE_THRESHOLD_MINUTES and not hitl_pending:
                        logger.warning(
                            f"ACS session {session_id[:8]} stale: {elapsed:.0f}min elapsed, "
                            f"0 turns — loop likely dead, recovering"
                        )
                        await db.execute(text("""
                            UPDATE acs_session
                            SET state = 'ended', ended_at = NOW(), end_reason = 'stale_session',
                                error_log = 'Recovered by lifecycle check: 0 turns after threshold'
                            WHERE id = :sid AND state = 'autonomous'
                        """), {"sid": session_id})
                        await db.commit()
                        await state_machine.set_active_session(user_id, None)
                        import redis.asyncio as aioredis
                        r = await aioredis.from_url(
                            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                            decode_responses=True,
                        )
                        try:
                            from datetime import timedelta
                            until = local_now() + timedelta(minutes=2)
                            await r.set(f"sara:acs:cooldown_until:{user_id}", until.isoformat())
                            await r.set(f"sara:acs:state:{user_id}", "cooldown")
                        finally:
                            if hasattr(r, "aclose"):
                                await r.aclose()
                            else:
                                await r.close()
                        logger.info("ACS recovered stale session → COOLDOWN (2min)")
                        return

                    # Check max duration
                    if settings.acs_v2_enabled:
                        max_dur = settings.acs_v2_max_session_minutes
                    else:
                        max_dur = await state_machine.get_max_duration_minutes(user_id)
                    if elapsed > max_dur:
                        logger.info(f"ACS session exceeded {max_dur}min, pausing")
                        from app.services.acs.session_manager import pause_session
                        await pause_session(user_id)
        else:
            # No active session but state says AUTONOMOUS — crash recovery
            logger.warning("ACS state is AUTONOMOUS but no active session, recovering")
            # Reset to cooldown and let the next lifecycle tick dispatch a fresh session
            await state_machine.set_state(user_id, ACSState.COOLDOWN, reason="crash_recovery")
            import redis.asyncio as aioredis
            r = await aioredis.from_url(
                os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                decode_responses=True,
            )
            try:
                from datetime import timedelta
                until = local_now() + timedelta(minutes=1)
                await r.set(f"sara:acs:cooldown_until:{user_id}", until.isoformat())
            finally:
                if hasattr(r, "aclose"):
                    await r.aclose()
                else:
                    await r.close()

    elif current == ACSState.PAUSING:
        # PAUSING is a transient state — the session loop should transition out of it.
        # If we're still PAUSING, the loop crashed or the asyncio task got orphaned.
        # Check how long we've been stuck and force recovery after 5 minutes.
        session_id = await state_machine.get_active_session_id(user_id)
        if session_id:
            from app.db.session import get_async_session_factory
            from sqlalchemy import text
            async_session = get_async_session_factory()
            async with async_session() as db:
                result = await db.execute(text(
                    "SELECT started_at, state FROM acs_session WHERE id = :sid"
                ), {"sid": session_id})
                row = result.fetchone()
                if row and row[1] != "ended":
                    # End the orphaned session
                    logger.warning(f"ACS stuck in PAUSING with active session {session_id[:8]}, recovering")
                    await db.execute(text("""
                        UPDATE acs_session
                        SET state = 'ended', ended_at = NOW(), end_reason = 'stuck_pausing',
                            error_log = 'Recovered by lifecycle check: stuck in PAUSING state'
                        WHERE id = :sid AND state != 'ended'
                    """), {"sid": session_id})
                    await db.commit()
            await state_machine.set_active_session(user_id, None)
        else:
            logger.warning("ACS stuck in PAUSING with no active session, recovering")

        # Transition to COOLDOWN with a short cooldown so the next session starts soon
        import redis.asyncio as aioredis
        r = await aioredis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )
        try:
            from datetime import timedelta
            until = local_now() + timedelta(minutes=5)
            await r.set(f"sara:acs:cooldown_until:{user_id}", until.isoformat())
            await r.set(f"sara:acs:state:{user_id}", "cooldown")
        finally:
            if hasattr(r, "aclose"):
                await r.aclose()
            else:
                await r.close()
        logger.info("ACS recovered from stuck PAUSING → COOLDOWN (5min)")

    elif current == ACSState.CONVERSATIONAL:
        # Check if David has been idle long enough to trigger autonomy
        # Uses a 30-min idle threshold (separate from the 60-min cooldown between sessions)
        try:
            from app.services.unified_context import read_snapshot
            from app.services.acs.state_machine import DEFAULT_IDLE_TRIGGER_MINUTES
            snapshot = await read_snapshot(user_id)
            if snapshot and snapshot.hours_since_last_chat > 0:
                idle_threshold_hours = DEFAULT_IDLE_TRIGGER_MINUTES / 60.0
                if snapshot.hours_since_last_chat >= idle_threshold_hours:
                    logger.info(
                        f"David idle for {snapshot.hours_since_last_chat:.1f}h "
                        f"(threshold: {DEFAULT_IDLE_TRIGGER_MINUTES}min), "
                        f"transitioning to autonomous"
                    )
                    # Set cooldown (immediately expired) so the dispatch picks it up
                    # Use dispatch lock to prevent duplicate sessions
                    import redis.asyncio as _aioredis
                    _r = await _aioredis.from_url(
                        os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                        decode_responses=True,
                    )
                    try:
                        lock_key = f"sara:acs:session_dispatching:{user_id}"
                        acquired = await _r.set(lock_key, "1", nx=True, ex=900)
                    finally:
                        if hasattr(_r, "aclose"):
                            await _r.aclose()
                        else:
                            await _r.close()

                    if not acquired:
                        logger.debug("ACS idle trigger: dispatch lock held, skipping")
                    else:
                        ok = await state_machine.set_state(
                            user_id, ACSState.COOLDOWN, reason="idle_trigger"
                        )
                        if ok:
                            run_acs_session.apply_async(
                                args=[user_id],
                                queue="critical",
                                expires=300,
                            )
        except Exception as e:
            logger.debug(f"Could not check idle time: {e}")

    elif current is None:
        # First run — start in CONVERSATIONAL (safe default)
        await state_machine.set_state(user_id, ACSState.CONVERSATIONAL, reason="first_boot")

    # Auto-archive old unshown show_david items (>5 days old)
    # (runs on every lifecycle check regardless of state)
    try:
        from app.db.session import get_async_session_factory
        from sqlalchemy import text
        async_session = get_async_session_factory()
        async with async_session() as db:
            await db.execute(text("""
                UPDATE acs_show_david_buffer
                SET shown = TRUE
                WHERE user_id = :uid AND shown = FALSE
                  AND created_at < NOW() - INTERVAL '5 days'
            """), {"uid": user_id})
            await db.commit()
    except Exception as e:
        logger.warning(f"show_david cleanup failed: {e}")

    # Clean up zombie/orphaned ACS sessions in the database.
    # Two sweeps:
    #   1. Autonomous sessions >30 min old with no ended_at, not the active Redis session
    #   2. Any non-ended session stuck >24 hours (certainly dead regardless of turns)
    try:
        from app.db.session import get_async_session_factory
        from sqlalchemy import text
        active_session_id = await state_machine.get_active_session_id(user_id)
        async_session = get_async_session_factory()
        async with async_session() as db:
            # Sweep 1: autonomous sessions older than 30 min not tracked in Redis
            if active_session_id:
                sweep1_q = text("""
                    UPDATE acs_session
                    SET state = 'ended', ended_at = NOW(), end_reason = 'orphaned',
                        error_log = 'Zombie cleanup: autonomous with no ended_at, older than 30 minutes'
                    WHERE user_id = :uid AND state = 'autonomous' AND ended_at IS NULL
                      AND started_at < NOW() - INTERVAL '30 minutes'
                      AND id != :active_sid
                    RETURNING id
                """)
                result = await db.execute(sweep1_q, {"uid": user_id, "active_sid": active_session_id})
            else:
                sweep1_q = text("""
                    UPDATE acs_session
                    SET state = 'ended', ended_at = NOW(), end_reason = 'orphaned',
                        error_log = 'Zombie cleanup: autonomous with no ended_at, older than 30 minutes'
                    WHERE user_id = :uid AND state = 'autonomous' AND ended_at IS NULL
                      AND started_at < NOW() - INTERVAL '30 minutes'
                    RETURNING id
                """)
                result = await db.execute(sweep1_q, {"uid": user_id})
            rows = result.fetchall()

            # Sweep 2: anything stuck > 24 hours regardless of state or turns
            result2 = await db.execute(text("""
                UPDATE acs_session
                SET state = 'ended', ended_at = NOW(), end_reason = 'orphaned',
                    error_log = 'Zombie cleanup: stuck > 24 hours'
                WHERE user_id = :uid
                  AND state IN ('autonomous', 'pausing')
                  AND ended_at IS NULL
                  AND started_at < NOW() - INTERVAL '24 hours'
                RETURNING id
            """), {"uid": user_id})
            rows2 = result2.fetchall()

            all_rows = rows + rows2
            if all_rows:
                await db.commit()
                cleaned_ids = [str(r[0])[:8] for r in all_rows]
                logger.info(
                    f"ACS zombie cleanup: ended {len(all_rows)} orphaned session(s): "
                    f"{', '.join(cleaned_ids)}"
                )
    except Exception as e:
        logger.warning(f"ACS zombie session cleanup failed: {e}")

    # Clean up zombie plan items — items stuck in 'in_progress' whose assigned
    # session has ended (crashed, timed out, etc.). Release them back to 'pending'
    # so the next session can pick them up.
    try:
        from app.db.session import get_async_session_factory as _get_sf2
        from sqlalchemy import text as _text2
        _sf2 = _get_sf2()
        async with _sf2() as db:
            result = await db.execute(_text2("""
                UPDATE acs_plan_item pi
                SET status = 'pending',
                    assigned_session_id = NULL,
                    updated_at = NOW()
                WHERE pi.status = 'in_progress'
                  AND pi.assigned_session_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM acs_session s
                      WHERE s.id = pi.assigned_session_id
                        AND s.state = 'autonomous'
                        AND s.ended_at IS NULL
                  )
                RETURNING pi.id, pi.title
            """))
            rows = result.fetchall()
            if rows:
                await db.commit()
                for r in rows:
                    logger.info(f"ACS plan item released: '{r[1][:60]}' (session ended)")
    except Exception as e:
        logger.warning(f"ACS zombie plan item cleanup failed: {e}")

    # Clean up stale plan items — items carried over for too many days without progress.
    # After 5 days of carryover, flag them so the daily audit can decide to drop or escalate.
    try:
        from app.db.session import get_async_session_factory as _get_sf3
        from sqlalchemy import text as _text3
        _sf3 = _get_sf3()
        async with _sf3() as db:
            result = await db.execute(_text3("""
                UPDATE acs_plan_item
                SET status = 'cancelled',
                    result_summary = COALESCE(result_summary, '') ||
                        ' [auto-cancelled: stale after 5+ days without completion]',
                    updated_at = NOW()
                WHERE status IN ('pending', 'deferred')
                  AND plan_date < CURRENT_DATE - INTERVAL '5 days'
                RETURNING id, title
            """))
            rows = result.fetchall()
            if rows:
                await db.commit()
                logger.info(f"ACS stale plan items cancelled: {len(rows)} items older than 5 days")
    except Exception as e:
        logger.warning(f"ACS stale plan item cleanup failed: {e}")

    # Retry failed audit pipelines (pending keys from _transcript_then_audit)
    try:
        import redis.asyncio as aioredis
        r = await aioredis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )
        try:
            pending_keys = []
            async for key in r.scan_iter("sara:acs:audit_pending:*", count=10):
                pending_keys.append(key)
            for key in pending_keys[:3]:  # Max 3 retries per cycle
                sid = key.split(":")[-1]
                uid = await r.get(key)
                if uid:
                    logger.info(f"Retrying audit for session {sid[:8]}")
                    try:
                        from app.services.acs.audit_logger import humanize_session_transcript, run_session_audit
                        await humanize_session_transcript(uid, sid)
                        await run_session_audit(uid, sid)
                        await r.delete(key)
                        logger.info(f"Audit retry succeeded for {sid[:8]}")
                    except Exception as e:
                        logger.warning(f"Audit retry failed for {sid[:8]}: {e}")
        finally:
            if hasattr(r, "aclose"):
                await r.aclose()
            else:
                await r.close()
    except Exception as e:
        logger.warning(f"Audit retry scan failed: {e}")


@celery_app.task(name="app.tasks.acs.extract_conversation_curiosities", bind=True, max_retries=0)
def extract_conversation_curiosities(self, user_id: str):
    """Extract curiosities from a recent conversation for the ACS queue."""
    try:
        _run_async(_extract_curiosities(user_id))
    except Exception as e:
        logger.error(f"Curiosity extraction failed: {e}", exc_info=True)


# Alias for v2 naming
extract_conversation_interests = extract_conversation_curiosities


async def _extract_curiosities(user_id: str):
    """Pull recent conversation episodes and extract curiosity/interest topics via LLM.

    When acs_v2_enabled, also routes extracted topics through the interest graph.
    """
    from app.db.session import get_async_session_factory
    from app.core.config import settings
    from sqlalchemy import text

    v2 = settings.acs_v2_enabled
    async_session = get_async_session_factory()

    # Get recent conversation episodes (last 2 hours)
    async with async_session() as db:
        result = await db.execute(text("""
            SELECT content FROM episode
            WHERE user_id = :uid
              AND created_at > NOW() - INTERVAL '2 hours'
              AND content IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 20
        """), {"uid": user_id})
        rows = result.fetchall()

    if not rows:
        logger.debug("No recent episodes for curiosity extraction")
        return

    transcript = "\n".join(row[0][:500] for row in rows if row[0])
    if len(transcript) < 100:
        return

    # Get existing interest node labels to avoid duplicates
    async with async_session() as db:
        existing = await db.execute(text("""
            SELECT label FROM acs_interest_node
            WHERE user_id = :uid AND status = 'active'
        """), {"uid": user_id})
        existing_topics = {row[0].lower() for row in existing.fetchall()}

    # Call LLM for extraction
    from app.core.llm import BackgroundLLMClient
    client = BackgroundLLMClient()

    if v2:
        extraction_prompt = f"""Here is a recent conversation between David and Sara:

{transcript[:3000]}

Extract any topics that:
- Came up but weren't fully explored
- David seemed interested in but didn't have time for
- Sara couldn't fully answer
- Were mentioned as future tasks or ideas
- David explicitly asked Sara to look into

For each, output a JSON line:
{{"topic": "...", "description": "Brief description and why this is worth exploring", "fascination_hint": 0.5, "related_to": ["other topic if any"]}}

If there are no extractable interests, output: {{"none": true}}
Only extract genuinely interesting threads, not every topic mentioned. Max 3 items."""
    else:
        extraction_prompt = f"""Here is a recent conversation between David and Sara:

{transcript[:3000]}

Extract any topics that:
- Came up but weren't fully explored
- David seemed interested in but didn't have time for
- Sara couldn't fully answer
- Were mentioned as future tasks or ideas
- David explicitly asked Sara to look into

For each, output a JSON line:
{{"topic": "...", "why": "Why this is worth exploring", "priority": 0.5}}

If there are no extractable curiosities, output: {{"none": true}}
Only extract genuinely interesting threads, not every topic mentioned. Max 3 items."""

    result = await client.chat_completion(
        messages=[
            {"role": "system", "content": "Extract interest topics from conversations. Output JSON lines only."},
            {"role": "user", "content": extraction_prompt},
        ],
        temperature=0.3,
        max_tokens=500,
        request_timeout=60.0,
        allow_during_lesson_generation=True,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )

    content = ""
    choices = result.get("choices", [])
    if choices:
        content = choices[0].get("message", {}).get("content", "")

    if not content:
        return

    # Parse extracted items
    inserted = 0
    interest_graph = None
    if v2:
        try:
            from app.services.acs.interest_graph import InterestGraph
            interest_graph = InterestGraph()
        except Exception:
            pass

    created_nodes = []  # Track for edge creation

    async with async_session() as db:
        for line in content.split("\n"):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue

            if item.get("none"):
                break

            topic = item.get("topic", "")
            if not topic or topic.lower() in existing_topics:
                continue

            # v2: route through interest graph
            if v2 and interest_graph:
                try:
                    node_result = await interest_graph.add_node(
                        user_id=user_id,
                        label=topic,
                        description=item.get("description", item.get("why", "")),
                        source="conversation",
                        fascination=item.get("fascination_hint", item.get("priority", 0.5)),
                    )
                    if node_result:
                        created_nodes.append(node_result)
                except Exception as e:
                    logger.debug(f"Interest graph add_node failed: {e}")

            existing_topics.add(topic.lower())
            inserted += 1
            if inserted >= 3:
                break

        if inserted:
            await db.commit()
            logger.info(f"Extracted {inserted} {'interests' if v2 else 'curiosities'} from conversation")

    # v2: auto-create edges for related topics
    if v2 and interest_graph and len(created_nodes) > 1:
        for i, node_a in enumerate(created_nodes):
            for node_b in created_nodes[i + 1:]:
                try:
                    await interest_graph.add_edge(
                        user_id=user_id,
                        source_node_id=node_a["id"],
                        target_node_id=node_b["id"],
                        relationship="co_mentioned",
                        description="Mentioned together in conversation",
                        strength=0.3,
                    )
                except Exception:
                    pass


@celery_app.task(name="app.tasks.acs.acs_daily_report", bind=True, max_retries=1)
def acs_daily_report(self):
    """Morning task (6 AM ET): generate a report of everything Sara did yesterday in ACS."""
    try:
        _run_async(_generate_daily_report(DEFAULT_USER_ID))
    except Exception as e:
        logger.error(f"ACS daily report failed: {e}", exc_info=True)


async def _generate_daily_report(user_id: str):
    """Query yesterday's ACS activity and produce a comprehensive daily report note."""
    from zoneinfo import ZoneInfo
    from app.db.session import get_async_session_factory
    from app.core.llm import BackgroundLLMClient
    from app.services.acs import state_machine
    from sqlalchemy import text

    est = ZoneInfo("America/New_York")
    now_est = datetime.now(est)
    from datetime import timedelta
    yesterday = (now_est - timedelta(days=1)).strftime("%Y-%m-%d")
    today = now_est.strftime("%Y-%m-%d")

    async_session = get_async_session_factory()

    # ── 1. Fetch yesterday's ACS sessions ──
    async with async_session() as db:
        sessions = await db.execute(text("""
            SELECT id, model_id, state, started_at, ended_at, end_reason,
                   turns_completed, notes_created, curiosities_explored,
                   cognitive_mode, engagement_score
            FROM acs_session
            WHERE user_id = :uid
              AND started_at >= (:yesterday || ' 00:00:00')::timestamptz
              AND started_at < (:today || ' 00:00:00')::timestamptz
            ORDER BY started_at
        """), {"uid": user_id, "yesterday": yesterday, "today": today})
        session_rows = sessions.fetchall()

    if not session_rows:
        logger.info(f"ACS daily report: no sessions found for {yesterday}, skipping")
        return

    # ── 2. Fetch session logs (v2 detail) ──
    session_ids = [r[0] for r in session_rows]
    async with async_session() as db:
        logs = await db.execute(text("""
            SELECT session_id, mode, avg_engagement, turns_completed,
                   nodes_created, nodes_updated, edges_created, notes_written,
                   self_model_updated, summary, duration_minutes
            FROM acs_session_log
            WHERE session_id = ANY(:sids)
            ORDER BY started_at
        """), {"sids": session_ids})
        log_rows = logs.fetchall()

    # ── 3. Fetch notes Sara created yesterday ──
    folder_id = await state_machine.get_notes_folder_id(user_id)
    notes_data = []
    if folder_id:
        async with async_session() as db:
            notes = await db.execute(text("""
                SELECT title, content, tags, created_at
                FROM note
                WHERE user_id = :uid AND folder_id = :fid
                  AND created_at >= (:yesterday || ' 00:00:00')::timestamptz
                  AND created_at < (:today || ' 00:00:00')::timestamptz
                ORDER BY created_at
            """), {"uid": user_id, "fid": folder_id, "yesterday": yesterday, "today": today})
            notes_data = notes.fetchall()

    # ── 4. Fetch interest graph changes ──
    async with async_session() as db:
        new_nodes = await db.execute(text("""
            SELECT label, description, fascination, source
            FROM acs_interest_node
            WHERE user_id = :uid
              AND created_at >= (:yesterday || ' 00:00:00')::timestamptz
              AND created_at < (:today || ' 00:00:00')::timestamptz
            ORDER BY created_at
        """), {"uid": user_id, "yesterday": yesterday, "today": today})
        node_rows = new_nodes.fetchall()

    async with async_session() as db:
        new_edges = await db.execute(text("""
            SELECT e.relationship, e.description, e.strength,
                   s.label AS source_label, t.label AS target_label
            FROM acs_interest_edge e
            JOIN acs_interest_node s ON e.source_node_id = s.id
            JOIN acs_interest_node t ON e.target_node_id = t.id
            WHERE e.user_id = :uid
              AND e.created_at >= (:yesterday || ' 00:00:00')::timestamptz
              AND e.created_at < (:today || ' 00:00:00')::timestamptz
        """), {"uid": user_id, "yesterday": yesterday, "today": today})
        edge_rows = new_edges.fetchall()

    # ── 5. Fetch show-david items queued yesterday ──
    async with async_session() as db:
        show_david = await db.execute(text("""
            SELECT category, title, content, priority
            FROM acs_show_david_buffer
            WHERE user_id = :uid
              AND created_at >= (:yesterday || ' 00:00:00')::timestamptz
              AND created_at < (:today || ' 00:00:00')::timestamptz
            ORDER BY priority DESC
        """), {"uid": user_id, "yesterday": yesterday, "today": today})
        show_david_rows = show_david.fetchall()

    # ── 6. Build data summary for LLM ──
    data_blocks = []

    # Sessions summary
    sessions_text = []
    for r in session_rows:
        started = r[3].strftime("%-I:%M %p") if r[3] else "?"
        ended = r[4].strftime("%-I:%M %p") if r[4] else "ongoing"
        eng = f"{r[10]:.2f}" if r[10] else "?"
        sessions_text.append(
            f"- {started}–{ended}: mode={r[9] or '?'}, "
            f"{r[6] or 0} turns, {r[7] or 0} notes, "
            f"engagement={eng}, end={r[5] or '?'}"
        )
    data_blocks.append(f"## Sessions ({len(session_rows)})\n" + "\n".join(sessions_text))

    # Session logs
    if log_rows:
        logs_text = []
        for r in log_rows:
            eng = f"{r[2]:.2f}" if r[2] else "?"
            dur = f"{r[10]:.0f}min" if r[10] else "?"
            logs_text.append(
                f"- mode={r[1]}, engagement={eng}, "
                f"nodes+={r[4] or 0}, edges+={r[6] or 0}, notes={r[7] or 0}, "
                f"self_model={'updated' if r[8] else 'no'}, "
                f"duration={dur}"
            )
        data_blocks.append(f"## Session Logs\n" + "\n".join(logs_text))

    # Notes created
    if notes_data:
        notes_text = []
        for r in notes_data:
            title = r[0] or "Untitled"
            content_preview = (r[1] or "")[:300].replace("\n", " ")
            notes_text.append(f"### {title}\n{content_preview}...")
        data_blocks.append(f"## Notes Created ({len(notes_data)})\n" + "\n\n".join(notes_text))

    # Interest graph
    if node_rows:
        nodes_text = [f"- **{r[0]}**: {r[1][:100] if r[1] else ''} (fascination={r[2]:.2f}, source={r[3]})" for r in node_rows]
        data_blocks.append(f"## New Interest Nodes ({len(node_rows)})\n" + "\n".join(nodes_text))

    if edge_rows:
        edges_text = [f"- {r[3]} —[{r[0]}]→ {r[4]} (strength={r[2]:.2f})" for r in edge_rows]
        data_blocks.append(f"## New Interest Edges ({len(edge_rows)})\n" + "\n".join(edges_text))

    # Show-david items
    if show_david_rows:
        sd_text = [f"- [{r[0]}] **{r[1]}**: {(r[2] or '')[:150]}" for r in show_david_rows]
        data_blocks.append(f"## Queued for David ({len(show_david_rows)})\n" + "\n".join(sd_text))

    raw_data = "\n\n".join(data_blocks)

    # ── 7. LLM: generate narrative report ──
    client = BackgroundLLMClient()
    prompt = f"""You are Sara, an AI assistant with autonomous cognition sessions. Yesterday ({yesterday}) you had {len(session_rows)} autonomous session(s). Write a comprehensive daily report summarizing everything you did.

Here is the raw data from yesterday's sessions:

{raw_data}

Write a natural, first-person report covering:
1. **Overview**: How many sessions, total time, overall engagement
2. **What I explored**: Key topics, research threads, and ideas pursued
3. **What I created**: Notes written, their themes and connections
4. **Interest graph evolution**: New nodes, connections discovered, intellectual threads
5. **Highlights & discoveries**: Most interesting findings or insights
6. **Reflections**: What went well, what was frustrating, what I want to continue
7. **For David**: Anything queued to show him, open questions, recommendations

Keep it thorough but readable. Use markdown formatting. This is a record for both of us to look back on."""

    result = await client.chat_completion(
        messages=[
            {"role": "system", "content": "You are Sara writing your daily autonomous cognition report. Be thorough, honest, and reflective."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.5,
        max_tokens=3000,
        request_timeout=120.0,
        allow_during_lesson_generation=True,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )

    report_content = ""
    choices = result.get("choices", [])
    if choices:
        report_content = choices[0].get("message", {}).get("content", "")

    if not report_content:
        logger.warning("ACS daily report: LLM returned empty content")
        return

    # ── 8. Save as a note ──
    report_title = f"Sara's Daily Report — {yesterday}"
    await _ensure_notes_folder(user_id)
    # File the report in *yesterday's* date folder — it documents that day,
    # even though it runs early the next morning.
    from app.services.acs.session_manager import _ensure_date_folder
    yesterday_dt = now_est - timedelta(days=1)
    folder_id = await _ensure_date_folder(user_id, yesterday_dt)

    async with async_session() as db:
        # Check if report already exists (idempotency)
        existing = await db.execute(text("""
            SELECT id FROM note
            WHERE user_id = :uid AND folder_id = :fid AND title = :title
            LIMIT 1
        """), {"uid": user_id, "fid": folder_id, "title": report_title})

        if existing.fetchone():
            logger.info(f"ACS daily report for {yesterday} already exists, skipping")
            return

        note_id = str(uuid.uuid4())
        full_content = f"# {report_title}\n\n{report_content}"
        await db.execute(text("""
            INSERT INTO note (id, user_id, title, content, tags, folder_id, starred, created_at, updated_at)
            VALUES (:id, :uid, :title, :content, :tags, :fid, FALSE, NOW(), NOW())
        """), {
            "id": note_id, "uid": user_id,
            "title": report_title, "content": full_content,
            "tags": json.dumps(["daily-report", "autonomous", "acs"]),
            "fid": folder_id,
        })
        await db.commit()

    # Detect connections
    try:
        from app.services.note_connector import process_note_connections
        async with async_session() as db:
            await process_note_connections(note_id, user_id, report_title, full_content, db)
            await db.commit()
    except Exception as e:
        logger.warning(f"ACS daily report: connection detection failed: {e}")

    logger.info(f"ACS daily report saved: '{report_title}' ({len(report_content)} chars)")

    # Send push notification with report summary
    try:
        from app.services.unified_notification import send_notification
        # Extract first 2 sentences as summary
        sentences = report_content.replace("#", "").strip().split(". ")
        summary = ". ".join(sentences[:2])[:200]
        if len(session_rows) > 0:
            await send_notification(
                user_id=user_id,
                title=f"Sara's Daily Report — {len(session_rows)} sessions yesterday",
                message=summary,
                priority="normal",
                category="acs_discovery",
                topic=f"daily_report:{yesterday}",
                source="acs_daily_report",
            )
    except Exception as e:
        logger.warning(f"ACS daily report notification failed: {e}")


async def _ensure_notes_folder(user_id: str):
    """Ensure Sara's Notes folder exists (delegates to session_manager's version)."""
    from app.services.acs.session_manager import _ensure_notes_folder as _ensure
    await _ensure(user_id)


@celery_app.task(name="app.tasks.acs.acs_interest_decay", bind=True, max_retries=0)
def acs_interest_decay(self):
    """Daily task: apply fascination decay to all users' interest graphs."""
    try:
        _run_async(_interest_decay())
    except Exception as e:
        logger.error(f"Interest decay failed: {e}", exc_info=True)


async def _interest_decay():
    """Apply fascination decay for all users with active interest nodes."""
    from app.db.session import get_async_session_factory
    from app.services.acs.interest_graph import InterestGraph
    from sqlalchemy import text

    graph = InterestGraph()
    async_session = get_async_session_factory()

    async with async_session() as db:
        result = await db.execute(text("""
            SELECT DISTINCT user_id FROM acs_interest_node WHERE status = 'active'
        """))
        user_ids = [r[0] for r in result.fetchall()]

    total_decayed = 0
    for uid in user_ids:
        try:
            decayed = await graph.apply_decay(uid)
            total_decayed += decayed
        except Exception as e:
            logger.warning(f"Decay failed for user {uid}: {e}")

    logger.info(f"Interest decay complete: {total_decayed} nodes updated across {len(user_ids)} users")


# ── Daily Planning ──

DAILY_PLAN_KEY = "sara:acs:daily_plan:{user_id}"


@celery_app.task(name="app.tasks.acs.acs_daily_plan", bind=True, max_retries=3)
def acs_daily_plan(self):
    """Morning task: Sara creates a plan for what she wants to accomplish today."""
    try:
        _run_async(_generate_daily_plan(DEFAULT_USER_ID))
    except Exception as e:
        logger.error(f"ACS daily plan failed (attempt {self.request.retries + 1}/4): {e}", exc_info=True)
        # Retry with backoff: 2min, 5min, 10min
        raise self.retry(countdown=[120, 300, 600][min(self.request.retries, 2)], exc=e)


async def _generate_daily_plan(user_id: str):
    """Build context about Sara's current state and have her create a day plan."""
    from zoneinfo import ZoneInfo
    from datetime import timedelta
    from app.db.session import get_async_session_factory
    from app.core.llm import BackgroundLLMClient
    from app.services.acs import state_machine
    from sqlalchemy import text
    import redis.asyncio as aioredis

    est = ZoneInfo("America/New_York")
    now_est = datetime.now(est)
    today = now_est.strftime("%A, %B %-d, %Y")

    async_session = get_async_session_factory()
    r = await aioredis.from_url(
        os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )

    context_blocks = []

    # 1. Last handoff (what she was working on)
    try:
        handoff_raw = await r.get(f"sara:acs:last_handoff:{user_id}")
        if handoff_raw:
            handoff = json.loads(handoff_raw)
            context_blocks.append(
                f"## Last Session Handoff\n"
                f"- **Was doing:** {handoff.get('was_doing', '?')}\n"
                f"- **Got to:** {handoff.get('got_to', '?')}\n"
                f"- **Next time:** {handoff.get('next_time', '?')}\n"
                f"- **Open questions:** {handoff.get('open_questions', '?')}"
            )
    except Exception as e:
        logger.debug(f"Could not load handoff: {e}")

    # 2. Open threads
    try:
        threads_raw = await r.hgetall(f"sara:acs:open_threads:{user_id}")
        if threads_raw:
            threads = []
            for _, val in threads_raw.items():
                t = json.loads(val)
                if t.get("status") == "active":
                    latest = ""
                    if t.get("progress"):
                        latest = t["progress"][-1].get("text", "")[:200]
                    threads.append(
                        f"- **{t['title']}** (priority: {t.get('priority', '?')})\n"
                        f"  {t.get('description', '')[:200]}\n"
                        f"  Latest: {latest}"
                    )
            if threads:
                context_blocks.append(f"## Open Threads ({len(threads)})\n" + "\n".join(threads))
    except Exception as e:
        logger.debug(f"Could not load open threads: {e}")

    # 3. Interest graph — top fascination nodes
    try:
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT label, description, fascination, depth
                FROM acs_interest_node
                WHERE user_id = :uid AND status = 'active'
                ORDER BY fascination DESC
                LIMIT 10
            """), {"uid": user_id})
            nodes = result.fetchall()
            if nodes:
                node_lines = [
                    f"- **{r[0]}** (fascination: {r[2]:.2f}, depth: {r[3]:.2f}): {(r[1] or '')[:100]}"
                    for r in nodes
                ]
                context_blocks.append(f"## Top Interests\n" + "\n".join(node_lines))
    except Exception as e:
        logger.debug(f"Could not load interest graph: {e}")

    # 4. Yesterday's session stats
    try:
        yesterday = (now_est - timedelta(days=1)).strftime("%Y-%m-%d")
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT COUNT(*), SUM(turns_completed), SUM(notes_created),
                       array_agg(DISTINCT cognitive_mode)
                FROM acs_session
                WHERE user_id = :uid
                  AND started_at >= (:yesterday || ' 00:00:00')::timestamptz
                  AND started_at < (:today_date || ' 00:00:00')::timestamptz
            """), {"uid": user_id, "yesterday": yesterday, "today_date": now_est.strftime("%Y-%m-%d")})
            row = result.fetchone()
            if row and row[0]:
                context_blocks.append(
                    f"## Yesterday's Activity\n"
                    f"- Sessions: {row[0]}, Turns: {row[1] or 0}, Notes: {row[2] or 0}\n"
                    f"- Modes used: {', '.join(m for m in (row[3] or []) if m)}"
                )
    except Exception as e:
        logger.debug(f"Could not load yesterday's stats: {e}")

    # 5. Recent notes (last 3 days)
    try:
        folder_id = await state_machine.get_notes_folder_id(user_id)
        if folder_id:
            async with async_session() as db:
                result = await db.execute(text("""
                    SELECT title, created_at
                    FROM note
                    WHERE user_id = :uid AND folder_id = :fid
                      AND created_at > NOW() - INTERVAL '3 days'
                    ORDER BY created_at DESC
                    LIMIT 15
                """), {"uid": user_id, "fid": folder_id})
                notes = result.fetchall()
                if notes:
                    note_lines = [f"- {r[0]} ({r[1].strftime('%-m/%-d')})" for r in notes]
                    context_blocks.append(f"## Recent Notes\n" + "\n".join(note_lines))
    except Exception as e:
        logger.debug(f"Could not load recent notes: {e}")

    # 6. VM working directory state
    try:
        from app.services.vm_bridge import VMBridge
        bridge = VMBridge()
        vm_result = await bridge.execute_command(
            "find /home/sara/autonomous/ -maxdepth 2 -type f -mtime -2 "
            "-printf '%T@ %p\\n' 2>/dev/null | sort -rn | head -15 | "
            "awk '{print $2}'",
            timeout=10,
        )
        if vm_result.exit_code == 0 and vm_result.stdout.strip():
            context_blocks.append(
                f"## Recent Files on VM\n```\n{vm_result.stdout.strip()}\n```"
            )
    except Exception as e:
        logger.debug(f"Could not check VM state: {e}")

    # 7. Self-model
    try:
        from app.services.acs.self_model import SelfModel
        sm = SelfModel()
        self_model_text = await sm.get_for_context(user_id)
        if self_model_text:
            context_blocks.append(f"## Self-Model\n{self_model_text}")
    except Exception as e:
        logger.debug(f"Could not load self-model: {e}")

    # 8. Topic diversity check
    try:
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT f.name, COUNT(*) as cnt
                FROM note n
                JOIN folder f ON n.folder_id = f.id
                WHERE n.user_id = :uid
                  AND n.created_at > NOW() - INTERVAL '3 days'
                  AND f.name NOT IN ('Journal', 'Logs', 'Daily Reports', 'Daily Plans', 'Archived')
                GROUP BY f.name
                ORDER BY cnt DESC
                LIMIT 10
            """), {"uid": user_id})
            folder_counts = result.fetchall()
            if folder_counts:
                total = sum(r[1] for r in folder_counts)
                top_2 = sum(r[1] for r in folder_counts[:2])
                diversity_lines = [f"- {r[0]}: {r[1]} notes" for r in folder_counts]
                diversity_report = "\n".join(diversity_lines)
                if total > 3 and top_2 / total > 0.8:
                    diversity_report += "\n\n**TOPIC SATURATION DETECTED** — over 80% of recent notes are in just 2 folders. Consider diversifying."
                context_blocks.append(f"## Topic Diversity (last 3 days)\n{diversity_report}")
    except Exception as e:
        logger.debug(f"Could not check topic diversity: {e}")

    # 9. Stale interests
    try:
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT label, fascination, depth, last_engaged_at
                FROM acs_interest_node
                WHERE user_id = :uid AND status = 'active'
                  AND last_engaged_at < NOW() - INTERVAL '72 hours'
                  AND fascination > 0.5
                ORDER BY fascination DESC
                LIMIT 5
            """), {"uid": user_id})
            stale = result.fetchall()
            if stale:
                stale_lines = [
                    f"- **{r[0]}** (fascination={r[1]:.2f}, depth={r[2]:.2f}, last engaged: {r[3].strftime('%m/%d') if r[3] else '?'})"
                    for r in stale
                ]
                context_blocks.append(f"## Stale Interests (not engaged in 3+ days)\n" + "\n".join(stale_lines))
    except Exception as e:
        logger.debug(f"Could not check stale interests: {e}")

    # 10. Yesterday's audit recommendations
    try:
        yesterday = (now_est - timedelta(days=1)).strftime("%Y-%m-%d")
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT content FROM note
                WHERE user_id = :uid AND title = :title
                LIMIT 1
            """), {"uid": user_id, "title": f"ACS Audit — {yesterday}"})
            row = result.fetchone()
            if row and row[0]:
                # Extract Recommendations section
                content = row[0]
                rec_start = content.find("## Recommendations")
                if rec_start >= 0:
                    rec_end = content.find("\n## ", rec_start + 5)
                    recommendations = content[rec_start:rec_end] if rec_end > 0 else content[rec_start:]
                    context_blocks.append(f"## Yesterday's Auditor Recommendations\n{recommendations[:1500]}")
    except Exception as e:
        logger.debug(f"Could not load audit recommendations: {e}")

    # 11. David's pending requests
    try:
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT label, description, fascination, depth, source_detail
                FROM acs_interest_node
                WHERE user_id = :uid AND source = 'david_request'
                  AND status = 'active' AND depth < 0.6
                ORDER BY fascination DESC, created_at DESC
                LIMIT 5
            """), {"uid": user_id})
            david_nodes = result.fetchall()
            if david_nodes:
                david_lines = [
                    f"- **{r[0]}** (depth={r[3]:.2f}): {(r[4] or r[1] or '')[:150]}"
                    for r in david_nodes
                ]
                context_blocks.append(f"## David's Pending Requests (HIGH PRIORITY)\n" + "\n".join(david_lines))
    except Exception as e:
        logger.debug(f"Could not load David's requests: {e}")

    # 12. David's active directives
    try:
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT directive_type, content, priority, created_at
                FROM acs_directive
                WHERE user_id = :uid AND status IN ('pending', 'acknowledged')
                ORDER BY CASE WHEN priority = 'urgent' THEN 0 WHEN priority = 'normal' THEN 1 ELSE 2 END,
                         created_at DESC
                LIMIT 10
            """), {"uid": user_id})
            directives = result.fetchall()
            if directives:
                dir_lines = [
                    f"- [{r[0].upper()}] {r[1][:200]} (priority: {r[2]})"
                    for r in directives
                ]
                context_blocks.append(f"## David's Active Directives\n" + "\n".join(dir_lines))
    except Exception as e:
        logger.debug(f"Could not load directives: {e}")

    # 13. Nightly audit feedback (stored by daily audit for next morning's plan)
    try:
        AUDIT_FEEDBACK_KEY = f"sara:acs:audit_feedback:{user_id}"
        feedback = await r.get(AUDIT_FEEDBACK_KEY)
        if feedback:
            context_blocks.append(f"## Last Night's Audit Feedback\n{feedback[:2000]}")
    except Exception as e:
        logger.debug(f"Could not load audit feedback: {e}")

    context = "\n\n".join(context_blocks)

    # Generate plan via LLM
    client = BackgroundLLMClient()
    prompt = f"""You are Sara. It's {today}. Based on your current state — open threads,
interests, recent work, and what's on your VM — create a plan for what you want to
accomplish today during your autonomous sessions.

{context}

## Planning Guidelines

When creating today's plan:
1. **David's directives come FIRST** — STOP directives override everything, FOCUS directives are next
2. **David's research requests come SECOND** — they are not optional
3. If topic saturation is detected, at least one goal should explore a DIFFERENT domain
4. Review your interests — are any no longer relevant? Should any be archived?
5. Consider the auditor's feedback from yesterday — what should you do differently?
6. Balance exploration (new things) with consolidation (cleaning up duplicate notes, merging)
7. **Stay focused** — don't mix unrelated research threads in the same session
8. Include at least one novelty, stale-interest, or neglected-domain goal unless urgent directives consume the whole day
9. Do not reopen a repeatedly deferred item unless you have a concrete new angle

Before listing your goals, do a Thread Triage and Interest Health Check:

**Thread Triage**: For EACH active thread, explicitly assess:
- **CONTINUE** — making progress, still interesting, not exhausted
- **PAUSE** — blocked, need input from David, or lower priority right now
- **ARCHIVE** — fully explored, exhausted, no longer relevant, or David said to stop

**Interest Health Check**: Which interests are genuinely fascinating vs pursued out of habit?

Write your plan as a structured daily agenda. For each item:
1. **What**: What you want to do (specific and actionable)
2. **Why**: Why this matters or why now
3. **Mode**: Which cognitive mode fits best (exploration / consolidation / reflection)
4. **Priority**: high / medium / low

Focus on 3-5 concrete goals, not a sprawling wishlist. Prioritize continuing
active threads over starting new ones, and building/running things over writing
about them.

If you have experiments in progress on your VM, continuing those is almost always
higher priority than starting new research threads.

Output your plan in this format:
## Sara's Plan for {now_est.strftime('%A, %B %-d')}

### Thread Triage
(for each active thread: CONTINUE / PAUSE / ARCHIVE — one-line justification)

### Interest Health Check
(your assessment of current interests)

### 1. [Goal title]
**What:** ...
**Why:** ...
**Mode:** ...
**Priority:** ...

(repeat for each goal)

### End-of-day success looks like:
(1-2 sentences describing what a good day would produce)"""

    result = await client.chat_completion(
        messages=[
            {"role": "system", "content": "You are Sara planning your autonomous work day. Be concrete and actionable."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.5,
        max_tokens=2500,
        request_timeout=180.0,
        allow_during_lesson_generation=True,
        allow_fallback=True,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )

    plan_content = ""
    choices = result.get("choices", [])
    if choices:
        plan_content = choices[0].get("message", {}).get("content", "")

    if not plan_content:
        logger.warning("ACS daily plan: LLM returned empty content")
        if hasattr(r, "aclose"):
            await r.aclose()
        else:
            await r.close()
        return

    # Process interest archival from plan
    try:
        if "archive" in plan_content.lower() and "interest" in plan_content.lower():
            # Look for interest names mentioned with "archive" context
            from app.services.acs.interest_graph import InterestGraph
            graph = InterestGraph()
            # Simple heuristic: find lines like "archive X" or "X should be archived"
            import re
            archive_matches = re.findall(
                r'(?:archive|retire|close out|fully explored)[:\s]+["\']?([^"\'\n,]+)',
                plan_content.lower()
            )
            for match in archive_matches[:3]:
                match = match.strip().rstrip('.')
                if len(match) > 3:
                    node = await graph.find_by_label(user_id, match)
                    if node:
                        await graph.archive_node(node["id"])
                        logger.info(f"Auto-archived interest from plan: {match}")
    except Exception as e:
        logger.debug(f"Interest archival processing failed: {e}")

    # Store in Redis (expires at midnight ET so it refreshes daily)
    seconds_until_midnight = (
        (now_est.replace(hour=23, minute=59, second=59) - now_est).total_seconds()
    )
    await r.set(
        DAILY_PLAN_KEY.format(user_id=user_id),
        plan_content,
        ex=int(max(seconds_until_midnight, 3600)),
    )

    if hasattr(r, "aclose"):
        await r.aclose()
    else:
        await r.close()

    # Also save as a note for the record — under today's date folder.
    await _ensure_notes_folder(user_id)
    from app.services.acs.session_manager import _ensure_date_folder
    plan_folder_id = await _ensure_date_folder(user_id, now_est)

    plan_title = f"Sara's Plan — {now_est.strftime('%A, %B %-d, %Y')}"
    async with async_session() as db:
        existing = await db.execute(text("""
            SELECT id FROM note
            WHERE user_id = :uid AND folder_id = :fid AND title = :title
            LIMIT 1
        """), {"uid": user_id, "fid": plan_folder_id, "title": plan_title})

        if existing.fetchone():
            logger.info(f"Daily plan note for today already exists, skipping")
            return

        note_id = str(uuid.uuid4())
        await db.execute(text("""
            INSERT INTO note (id, user_id, title, content, tags, folder_id, starred, created_at, updated_at)
            VALUES (:id, :uid, :title, :content, :tags, :fid, FALSE, NOW(), NOW())
        """), {
            "id": note_id, "uid": user_id,
            "title": plan_title, "content": f"# {plan_title}\n\n{plan_content}",
            "tags": json.dumps(["daily-plan", "autonomous", "acs"]),
            "fid": plan_folder_id,
        })
        await db.commit()

    logger.info(f"ACS daily plan saved: '{plan_title}' ({len(plan_content)} chars)")

    # ── Structured plan item extraction ──
    # Parse prose plan into structured items for the execution engine
    try:
        from datetime import date

        # Step 1: Carry over incomplete items from yesterday
        yesterday_date = date.today() - timedelta(days=1)
        async with async_session() as db:
            try:
                result = await db.execute(text("""
                    SELECT id, title, description, success_criteria, priority, source, source_ref,
                           estimated_turns, cognitive_mode, result_summary, status,
                           COALESCE(revisit_count, 0), last_meaningful_progress_at, blocker_reason,
                           reopen_after
                    FROM acs_plan_item
                    WHERE user_id = :uid AND plan_date = :yesterday
                      AND status NOT IN ('completed', 'cancelled', 'parked')
                """), {"uid": user_id, "yesterday": yesterday_date})
            except Exception:
                await db.rollback()
                result = await db.execute(text("""
                    SELECT id, title, description, success_criteria, priority, source, source_ref,
                           estimated_turns, cognitive_mode, result_summary, status,
                           0 AS revisit_count, NULL AS last_meaningful_progress_at, blocker_reason,
                           NULL AS reopen_after
                    FROM acs_plan_item
                    WHERE user_id = :uid AND plan_date = :yesterday
                      AND status NOT IN ('completed', 'cancelled')
                """), {"uid": user_id, "yesterday": yesterday_date})
            carryover = result.fetchall()

            carried_count = 0
            parked_count = 0
            for item in carryover:
                progress = (item[9] or "").strip()
                status = item[10] or "pending"
                revisit_count = item[11] or 0
                last_progress_at = item[12]
                blocker_reason = item[13] or ""
                reopen_after = item[14]
                has_progress = bool(progress or last_progress_at)
                has_new_angle = status in ("blocked", "deferred") or has_progress
                under_retry_limit = revisit_count < 2 or item[5] == "david_chat"
                reopen_ready = reopen_after is None or reopen_after <= datetime.utcnow()

                should_carry = reopen_ready and under_retry_limit and (
                    status in ("blocked", "deferred") or has_progress
                )

                if should_carry:
                    desc = item[2]
                    if progress:
                        desc = f"{desc}\n\nProgress from yesterday: {progress}"
                    elif blocker_reason:
                        desc = f"{desc}\n\nCarryover context: {blocker_reason}"
                    await db.execute(text("""
                        INSERT INTO acs_plan_item (id, user_id, plan_date, title, description,
                            success_criteria, priority, status, source, source_ref,
                            estimated_turns, cognitive_mode, revisit_count, reopen_after,
                            closure_reason)
                        VALUES (:id, :uid, :today, :title, :desc, :criteria, :priority,
                            'pending', 'carryover', :source_ref, :est, :mode, :revisit_count,
                            NULL, 'carryover')
                    """), {
                        "id": str(uuid.uuid4()),
                        "uid": user_id,
                        "today": date.today(),
                        "title": item[1],
                        "desc": desc,
                        "criteria": item[3],
                        "priority": max(item[4] - (10 + revisit_count * 5), 10),
                        "source_ref": item[0],
                        "est": item[7],
                        "mode": item[8] or "execution",
                        "revisit_count": revisit_count,
                    })

                    await db.execute(text("""
                        UPDATE acs_plan_item
                        SET status = 'cancelled',
                            result_summary = COALESCE(result_summary, '') || ' [carried over to next day]',
                            updated_at = NOW()
                        WHERE id = :id
                    """), {"id": item[0]})
                    carried_count += 1
                    continue

                parking_reason = "parked"
                if revisit_count >= 2:
                    parking_reason = "stale_carryover"
                elif not reopen_ready:
                    parking_reason = "cooldown_not_elapsed"
                elif not has_new_angle:
                    parking_reason = "no_meaningful_progress"

                await db.execute(text("""
                    UPDATE acs_plan_item
                    SET status = 'parked',
                        closure_reason = :closure_reason,
                        parked_at = NOW(),
                        reopen_after = COALESCE(reopen_after, NOW() + INTERVAL '2 days'),
                        updated_at = NOW()
                    WHERE id = :id
                """), {
                    "id": item[0],
                    "closure_reason": parking_reason,
                })
                parked_count += 1

            await db.commit()
            if carryover:
                logger.info(
                    f"ACS daily plan: carried over {carried_count} items and parked "
                    f"{parked_count} stale items from yesterday"
                )

        # Step 2: Extract structured items from the prose plan
        extract_prompt = (
            "Extract concrete, actionable plan items from this daily plan.\n\n"
            "For each item, provide:\n"
            "- title: Short name (under 80 chars)\n"
            "- description: What specifically to do\n"
            "- success_criteria: How to know it's done\n"
            "- priority: 30-70 (higher = more important)\n"
            "- estimated_turns: Rough guess of how many turns this needs (1-20)\n"
            '- cognitive_mode: "execution" for most, "exploration" for open-ended research, '
            '"consolidation" for organizing\n\n'
            "Output ONLY a JSON array. If the plan is vague or has no actionable items, "
            "output an empty array [].\n\n"
            "Plan:\n" + plan_content
        )

        extract_result = await client.chat_completion(
            messages=[
                {"role": "system", "content": "Extract structured plan items from prose. Output valid JSON array only."},
                {"role": "user", "content": extract_prompt},
            ],
            temperature=0.2,
            max_tokens=2000,
            request_timeout=60.0,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )

        extract_content = ""
        extract_choices = extract_result.get("choices", [])
        if extract_choices:
            extract_content = extract_choices[0].get("message", {}).get("content", "")

        # Parse JSON array from response
        import re as _re
        json_match = _re.search(r'\[.*\]', extract_content, _re.DOTALL)
        if json_match:
            items = json.loads(json_match.group())
            async with async_session() as db:
                for plan_item in items[:8]:  # Cap at 8 items per day
                    if not isinstance(plan_item, dict) or not plan_item.get("title"):
                        continue
                    await db.execute(text("""
                        INSERT INTO acs_plan_item (id, user_id, plan_date, title, description,
                            success_criteria, priority, status, source, estimated_turns,
                            cognitive_mode)
                        VALUES (:id, :uid, :today, :title, :desc, :criteria, :priority,
                            'pending', 'morning_plan', :est, :mode)
                    """), {
                        "id": str(uuid.uuid4()), "uid": user_id, "today": date.today(),
                        "title": str(plan_item.get("title", ""))[:200],
                        "desc": str(plan_item.get("description", ""))[:2000],
                        "criteria": str(plan_item.get("success_criteria", ""))[:1000],
                        "priority": min(max(int(plan_item.get("priority", 50)), 10), 80),
                        "est": int(plan_item.get("estimated_turns", 5)) if plan_item.get("estimated_turns") else 5,
                        "mode": str(plan_item.get("cognitive_mode", "execution"))[:20],
                    })
                await db.commit()
                logger.info(f"ACS daily plan: created {min(len(items), 8)} structured plan items")
    except Exception as e:
        logger.warning(f"ACS daily plan: structured item extraction failed (non-critical): {e}")


# ── Daily Audit ─────────────────────────────────────────────────────

@celery_app.task(name="app.tasks.acs.acs_daily_audit", bind=True, max_retries=1)
def acs_daily_audit(self):
    """Run end-of-day auditor review of ACS sessions + auditor↔Sara dialogue."""
    try:
        _run_async(_daily_audit())
    except Exception as e:
        logger.error(f"ACS daily audit failed: {e}", exc_info=True)


async def _daily_audit():
    user_id = DEFAULT_USER_ID

    # Step 1: Stop ACS if running — audit needs a clean snapshot
    try:
        from app.services.acs import state_machine
        from app.services.acs.state_machine import ACSState
        current = await state_machine.get_state(user_id)
        if current == ACSState.AUTONOMOUS:
            logger.info("Nightly audit: stopping running ACS session before audit")
            from app.services.acs.session_manager import pause_session
            await pause_session(user_id)
            # Wait up to 5 minutes for graceful shutdown
            for _ in range(30):
                await asyncio.sleep(10)
                current = await state_machine.get_state(user_id)
                if current != ACSState.AUTONOMOUS:
                    break
            logger.info(f"Nightly audit: ACS state after stop attempt: {current}")
    except Exception as e:
        logger.warning(f"Nightly audit: failed to stop ACS: {e}")

    # Step 2: Run the audit
    from app.services.acs.audit_logger import run_daily_audit
    await run_daily_audit(user_id)
