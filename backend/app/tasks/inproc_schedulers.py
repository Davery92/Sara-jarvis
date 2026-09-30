"""
Celery wrappers for what used to be in-process background schedulers in
main_simple.py and the daily_brief module:

* daily_brief.scheduler.DailyBriefScheduler  → 4 tasks (consolidate, context update, archive, weekly synthesis)
* nightly_dream_service.start_dream_scheduler → 1 task (nightly dream cycle, 2 AM)
* main_simple.NotificationScheduler          → 1 task (5s timer/reminder pre-dispatch)

These all live in `scheduled_job` so they can be edited from the settings UI.
"""
import asyncio
import logging
from datetime import datetime, timezone as dt_tz, timedelta
from typing import Any, List, Tuple

import pytz
import sqlalchemy as sa

from app.celery_app import celery_app

logger = logging.getLogger(__name__)
EASTERN = pytz.timezone("America/New_York")


def _run_async(coro):
    """Helper: run an async coroutine from a sync Celery task body."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── daily_brief scheduler tasks ────────────────────────────────────
def _all_brief_user_ids() -> List[str]:
    from pathlib import Path
    briefs_dir = Path("/home/david/jarvis/data/briefs")
    if not briefs_dir.exists():
        return []
    return [p.name for p in briefs_dir.iterdir() if p.is_dir()]


@celery_app.task(name="app.tasks.inproc_schedulers.daily_brief_consolidate", queue="cognitive")
def daily_brief_consolidate():
    """Hourly day-layer consolidation. Skips outside 8 AM–11 PM Eastern."""
    now_et = datetime.now(EASTERN)
    if not (8 <= now_et.hour < 23):
        logger.debug("daily_brief_consolidate: outside active hours, skipping")
        return {"skipped": "inactive_hours"}

    from app.services.daily_brief.day_layer import day_layer

    async def _run():
        ran = 0
        for user_id in _all_brief_user_ids():
            try:
                if day_layer.needs_consolidation(user_id):
                    await day_layer.consolidate(user_id)
                    ran += 1
            except Exception as e:
                logger.error("daily_brief consolidate failed for %s: %s", user_id[:8], e)
        return {"users_consolidated": ran}

    return _run_async(_run())


@celery_app.task(name="app.tasks.inproc_schedulers.daily_brief_context_update", queue="cognitive")
def daily_brief_context_update():
    """Daily 11 PM context-layer update."""
    from app.services.daily_brief.day_layer import day_layer
    from app.services.daily_brief.context_layer import context_layer

    async def _run():
        updated = 0
        for user_id in _all_brief_user_ids():
            try:
                day_content = day_layer.read(user_id)
                if day_content:
                    await context_layer.daily_update(user_id, day_content)
                    updated += 1
            except Exception as e:
                logger.error("daily_brief context update failed for %s: %s", user_id[:8], e)
        return {"users_updated": updated}

    return _run_async(_run())


@celery_app.task(name="app.tasks.inproc_schedulers.daily_brief_archive", queue="maintenance")
def daily_brief_archive():
    """Midnight day-layer archival."""
    from app.services.daily_brief.day_layer import day_layer
    from app.services.daily_brief.archiver import archiver

    async def _run():
        archived = 0
        for user_id in _all_brief_user_ids():
            try:
                content = day_layer.read(user_id)
                if content:
                    await archiver.archive_day_layer(user_id, content)
                    day_layer.clear(user_id)
                    archived += 1
            except Exception as e:
                logger.error("daily_brief archive failed for %s: %s", user_id[:8], e)
        return {"users_archived": archived}

    return _run_async(_run())


@celery_app.task(name="app.tasks.inproc_schedulers.daily_brief_weekly_synthesis", queue="cognitive")
def daily_brief_weekly_synthesis():
    """Sunday 3 AM weekly stable-layer synthesis."""
    from app.db.base import SessionLocal
    from app.services.daily_brief.stable_layer import stable_layer

    async def _run():
        synthesized = 0
        for user_id in _all_brief_user_ids():
            db = SessionLocal()
            try:
                await stable_layer.weekly_synthesis(user_id, db)
                synthesized += 1
            except Exception as e:
                logger.error("weekly synthesis failed for %s: %s", user_id[:8], e)
            finally:
                db.close()
        return {"users_synthesized": synthesized}

    return _run_async(_run())


# ── Nightly dream cycle ────────────────────────────────────────────
@celery_app.task(name="app.tasks.inproc_schedulers.nightly_dream_cycle", queue="cognitive")
def nightly_dream_cycle():
    """Nightly memory consolidation 'dream' cycle. Cron-scheduled at 2 AM ET."""
    from app.services.nightly_dream_service import nightly_dream_service

    async def _run():
        # _run_nightly_dream_cycle is a no-op if already dreaming.
        await nightly_dream_service._run_nightly_dream_cycle()
        return {"ok": True}

    return _run_async(_run())


# R06 remainder (Sara repair plan 2026-09-25): how far past due an
# occurrence can be and still get a real push. The plan's own caution —
# "avoid flooding David with historical reminders at first deployment...
# define catch-up/expiry policy before enabling it" — means catch-up must
# be BOUNDED, not "select everything ever missed." Anything overdue by
# more than this is marked 'missed' (an explicit, visible, honest outcome)
# rather than either silently dropped (the old behavior) or pushed as a
# surprise hours/days late.
REMINDER_TIMER_CATCHUP_MAX_AGE = timedelta(hours=2)

# Round 4 (2026-09-27 review remediation): "stop sending up to 20 seconds
# early." The old REMINDER_TIMER_LOOKAHEAD fired the moment `due_at`
# entered a 20-second-wide FUTURE window, i.e. up to 20s before the actual
# due instant. This task runs every 5 seconds (alembic 051's own schedule
# row: `interval`, 5s) — a due item is caught within 5 seconds of actually
# becoming due with no lookahead at all, so there is no reason to fire
# early. Selection is now `due_at <= now` — nothing before its own instant.
REMINDER_TIMER_LOOKAHEAD = timedelta(seconds=0)

# Round 4: a claim that is taken but never resolved (the worker crashed,
# or the process was killed, between claiming and recording an outcome)
# becomes reclaimable once its claim is this old — generous relative to
# how long a single push dispatch actually takes, so a legitimate slow
# send is never reclaimed out from under itself, while a genuine crash is
# recovered within one or two beats of this task (5s each).
CLAIM_EXPIRY = timedelta(seconds=90)

# Round 4: bounded retries for a dispatch attempt that fails (the push
# provider errors, a transient network failure) — after this many failed
# attempts, the occurrence is marked `failed_permanent` (terminal) rather
# than retried forever.
MAX_DELIVERY_ATTEMPTS = 3


# ── Notification pre-dispatch (timers + reminders) ─────────────────
@celery_app.task(name="app.tasks.inproc_schedulers.notification_predispatch", queue="critical")
def notification_predispatch():
    """
    Find due, not-yet-resolved timers/reminders and dispatch their push
    notifications. Replaces main_simple.NotificationScheduler's 5s loop.

    R06 remainder (2026-09-25 repair plan, "no overdue catch-up in that
    path"): the original selection was `now <= due_at <= now+20s` — an
    occurrence whose due time slipped into the past (a missed beat, a
    worker restart, a slow prior run) became permanently unselectable the
    instant `due_at < now`, with no record it was ever due at all. This
    selects everything due (`due_at <= now`, no forward lookahead — see
    round 4's REMINDER_TIMER_LOOKAHEAD note) that has not reached a
    TERMINAL delivery outcome yet, which naturally includes overdue items
    — bounded by REMINDER_TIMER_CATCHUP_MAX_AGE so a long outage produces
    one clearly-marked 'missed' outcome per item instead of a flood of
    stale pushes arriving together.

    Round 4 fix (review finding 1 — "R06 marks delivery successful before
    sending"): claiming an occurrence and recording its delivery OUTCOME
    are now two SEPARATE writes. `_claim_for_dispatch` only marks the
    occurrence `claimed` (in flight) — it does NOT set `notified_at` or
    `delivery_status='sent'`. The actual outcome (`sent`, or a
    bounded-retry `failed`/terminal `failed_permanent`) is written by
    `_record_delivery_outcome` only AFTER the real dispatch attempt
    returns. A crash between claiming and recording leaves the occurrence
    in `claimed` state with no terminal `notified_at` — the NEXT run's own
    selection query (below) reclaims it once its claim is older than
    CLAIM_EXPIRY, which is the outcome-reconciliation mechanism: no
    separate sweep process, the normal 5-second poll IS the reconciler.

    A failed dispatch is retried up to MAX_DELIVERY_ATTEMPTS times before
    being marked permanently failed — bounded, not infinite. The claim's
    own WHERE clause re-checks the occurrence is still active/not-
    completed at CLAIM time (not only at the earlier SELECT), so a
    cancellation or reschedule made between selection and claim is caught
    before a stale claim can dispatch a push for something the user
    already cancelled.
    """
    from app.db.base import SessionLocal
    from app.models.reminder import Timer, Reminder

    async def _run():
        now = datetime.now(dt_tz.utc)
        cutoff = now + REMINDER_TIMER_LOOKAHEAD
        catchup_floor = now - REMINDER_TIMER_CATCHUP_MAX_AGE
        claim_expiry_cutoff = now - CLAIM_EXPIRY
        sent = 0
        missed = 0
        with SessionLocal() as db:
            # Timers: due (or overdue, within the catch-up window), and
            # either never attempted, a reclaimable expired claim, or a
            # failed attempt with retries remaining.
            timers = db.query(Timer).filter(
                Timer.is_active.is_(True),
                Timer.notified_at.is_(None),
                sa.or_(
                    Timer.delivery_status.is_(None),
                    sa.and_(Timer.delivery_status == "claimed", Timer.claimed_at < claim_expiry_cutoff),
                    sa.and_(Timer.delivery_status == "failed", Timer.delivery_attempts < MAX_DELIVERY_ATTEMPTS),
                ),
            ).all()
            for t in timers:
                end = t.end_time
                if end.tzinfo is None:
                    end = end.replace(tzinfo=dt_tz.utc)
                if end > cutoff:
                    continue  # not due yet
                if end < catchup_floor:
                    _mark_missed(db, "timer", t.id)
                    missed += 1
                    continue
                if not _claim_for_dispatch(db, "timer", t.id, is_active_column=True):
                    continue  # lost the claim race to another run, or was cancelled
                try:
                    await _dispatch_timer(t)
                    _record_delivery_outcome(db, "timer", t.id, success=True)
                    sent += 1
                except Exception as e:
                    logger.error("timer dispatch failed for %s: %s", t.id, e)
                    _record_delivery_outcome(db, "timer", t.id, success=False, error=str(e))

            # Reminders: same policy.
            reminders = db.query(Reminder).filter(
                Reminder.is_completed.is_(False),
                Reminder.notified_at.is_(None),
                sa.or_(
                    Reminder.delivery_status.is_(None),
                    sa.and_(Reminder.delivery_status == "claimed", Reminder.claimed_at < claim_expiry_cutoff),
                    sa.and_(Reminder.delivery_status == "failed", Reminder.delivery_attempts < MAX_DELIVERY_ATTEMPTS),
                ),
            ).all()
            for r in reminders:
                rt = r.reminder_time
                if rt.tzinfo is None:
                    rt = rt.replace(tzinfo=dt_tz.utc)
                if rt > cutoff:
                    continue  # not due yet
                if rt < catchup_floor:
                    _mark_missed(db, "reminder", r.id)
                    missed += 1
                    continue
                if not _claim_for_dispatch(db, "reminder", r.id, is_active_column=False):
                    continue
                try:
                    await _dispatch_reminder(r)
                    _record_delivery_outcome(db, "reminder", r.id, success=True)
                    sent += 1
                except Exception as e:
                    logger.error("reminder dispatch failed for %s: %s", r.id, e)
                    _record_delivery_outcome(db, "reminder", r.id, success=False, error=str(e))

        if missed:
            logger.warning(
                "notification_predispatch: %d occurrence(s) fell outside the "
                "%s catch-up window and were marked missed, not pushed",
                missed, REMINDER_TIMER_CATCHUP_MAX_AGE,
            )
        return {"sent": sent, "missed": missed}

    return _run_async(_run())


def _claim_for_dispatch(db, table: str, row_id: str, is_active_column: bool) -> bool:
    """Atomically claim one occurrence for a dispatch ATTEMPT — sets ONLY
    `delivery_status='claimed'` + `claimed_at`. Deliberately does NOT set
    `notified_at` or record any outcome: this is round 4's fix for review
    finding 1 ("marks delivery successful before sending") — claiming and
    the real outcome are separate writes, so a crash between them leaves
    a reclaimable `claimed` row, never a false `sent`.

    The WHERE clause re-checks cancellation/completion state AT CLAIM
    TIME (`is_active = TRUE` for timers, `is_completed = FALSE` for
    reminders) — not only at the earlier SELECT — so a cancel/reschedule
    that happened in the gap between selection and claim is caught here.
    Also re-checks the same not-yet-resolved / reclaimable-claim /
    retry-eligible conditions as the selection query, so two overlapping
    runs can never both claim the same occurrence. Commits immediately so
    the claim is durable before the push side-effect runs. Returns False
    if another run already claimed it, or it was cancelled in the gap.
    """
    from sqlalchemy import text as sa_text
    active_clause = "is_active = TRUE" if is_active_column else "is_completed = FALSE"
    result = db.execute(sa_text(f"""
        UPDATE {table}
        SET delivery_status = 'claimed', claimed_at = NOW()
        WHERE id = :id
          AND {active_clause}
          AND notified_at IS NULL
          AND (
                delivery_status IS NULL
                OR (delivery_status = 'claimed' AND claimed_at < :claim_expiry_cutoff)
                OR (delivery_status = 'failed' AND delivery_attempts < :max_attempts)
              )
    """), {
        "id": row_id,
        "claim_expiry_cutoff": datetime.now(dt_tz.utc) - CLAIM_EXPIRY,
        "max_attempts": MAX_DELIVERY_ATTEMPTS,
    })
    db.commit()
    return result.rowcount > 0


def _record_delivery_outcome(db, table: str, row_id: str, success: bool, error: str = "") -> None:
    """Record the REAL outcome of a dispatch attempt that has actually
    happened — the only place `notified_at` is set to a terminal value
    (success), alongside bounded-retry failure tracking. Only transitions
    a row currently `claimed` (idempotent against a lost race — if
    something else already resolved it, this is a no-op)."""
    from sqlalchemy import text as sa_text
    if success:
        db.execute(sa_text(f"""
            UPDATE {table} SET delivery_status = 'sent', notified_at = NOW()
            WHERE id = :id AND delivery_status = 'claimed'
        """), {"id": row_id})
    else:
        row = db.execute(sa_text(f"""
            SELECT delivery_attempts FROM {table} WHERE id = :id
        """), {"id": row_id}).mappings().first()
        attempts = (row["delivery_attempts"] if row else 0) + 1
        if attempts >= MAX_DELIVERY_ATTEMPTS:
            db.execute(sa_text(f"""
                UPDATE {table}
                SET delivery_status = 'failed_permanent', notified_at = NOW(),
                    delivery_attempts = :attempts, last_error = :error
                WHERE id = :id AND delivery_status = 'claimed'
            """), {"id": row_id, "attempts": attempts, "error": (error or "")[:2000]})
        else:
            db.execute(sa_text(f"""
                UPDATE {table}
                SET delivery_status = 'failed', delivery_attempts = :attempts, last_error = :error
                WHERE id = :id AND delivery_status = 'claimed'
            """), {"id": row_id, "attempts": attempts, "error": (error or "")[:2000]})
    db.commit()


def _mark_missed(db, table: str, row_id: str) -> None:
    """Explicitly record an occurrence that fell outside the bounded
    catch-up window — visible and honest, per the plan's caution against
    both silently dropping overdue items and silently flooding a
    reconnecting client with a stale backlog. Terminal — never reclaimed
    or retried further, regardless of what state it was in before
    (claimed, failed, or never attempted)."""
    from sqlalchemy import text as sa_text
    db.execute(sa_text(f"""
        UPDATE {table} SET notified_at = NOW(), delivery_status = 'missed'
        WHERE id = :id AND notified_at IS NULL
    """), {"id": row_id})
    db.commit()


async def _dispatch_timer(timer):
    from app.routes.push_tokens import send_push_to_user
    await send_push_to_user(
        user_id=timer.user_id,
        title=f"Timer: {timer.title or 'Timer'}",
        body=f"Your {timer.duration_minutes}min timer is done!",
        notification_data={
            "type": "timer_complete",
            "timer_id": timer.id,
            "timer_name": timer.title or "Timer",
        },
    )


async def _dispatch_reminder(reminder):
    from app.routes.push_tokens import send_push_to_user
    await send_push_to_user(
        user_id=reminder.user_id,
        title=f"Reminder: {reminder.title or 'Reminder'}",
        # R06 (Sara repair plan 2026-09-25, evidence
        # REMINDER_DISPATCH_CRASH_NO_DESCRIPTION): Reminder has no `content`
        # column — this fallback raised AttributeError and crashed dispatch
        # for any reminder with an empty description, i.e. most of them.
        body=reminder.description or reminder.title or "Time for your reminder",
        notification_data={
            "type": "reminder",
            "reminder_id": reminder.id,
            "event_id": getattr(reminder, "event_id", None),
        },
    )


# ── Calendar reminder top-up ───────────────────────────────────────
@celery_app.task(name="app.tasks.inproc_schedulers.calendar_reminder_topup", queue="cognitive")
def calendar_reminder_topup():
    """Daily top-up of reminders for recurring calendar events.

    Extends the rolling 30-day window so recurring events past the initial
    expansion keep getting push notifications.
    """
    from app.db.base import SessionLocal
    from app.services.calendar_reminders import topup_all_recurring

    with SessionLocal() as db:
        try:
            created = topup_all_recurring(db)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error("calendar_reminder_topup failed: %s", e)
            return {"created": 0, "error": str(e)}
    return {"created": created}
