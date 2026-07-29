"""
Follow-up sweep — post-meeting recaps + open-thread follow-ups.

SARA_UNLEASHED Phase A: the old ``run_checkin_sweep`` also ran two template
paths (a deterministic "checkin_builder" ping and an ambient "How's the
afternoon going?" line after a long quiet stretch) with priority force-floored
to ``high`` so they'd bypass the attention queue's normal/low silencing. That
was a second proactivity brain fighting the deliberation engine, and it's why
120 of 140 weekly notifications were empty check-ins (SARA_UNLEASHED_PLAN.md
R1-R3). Both template paths are deleted. The only remaining entry point below
delivers a *ripe thread* — a real payload (a meeting, a commitment, a chat
thread) — never a content-free ping. Occasional contextual check-ins are now
proposed by the deliberation engine itself (deliberation_prompt.py's `checkin`
rule), which routes through the same gate and payload lint as everything else.

Two entry points, both gated hard by interruptibility and anti-nag caps:

- ``scan_ended_meetings()`` — when a real meeting just wrapped, opens a
  ``followup_thread`` ("How'd that meeting go?"). It does NOT notify directly;
  the sweep delivers it once David is interruptible.
- ``run_followup_sweep()`` — runs every ~15 min during waking hours. Delivers
  the single ripest open thread (post-meeting recaps + commitments included),
  if any, and does nothing otherwise.

Everything is reused, not reinvented:
- ``thread_manager``            → anti-harping (max_mentions, drop-on-ignore)
- ``activity_state_machine`` + ``interruptibility`` → never ping during a
  meeting, deep-focus work, exercise, wind-down, or sleep
- ``unified_notification.send_notification`` → dedup, cooldown, push delivery,
  and (now) the learned buzz decision — priority is no longer floored here.

Topics are namespaced so the existing per-category caps do the right thing:
post-meeting/thread follow-ups use ``followup:`` so a timely meeting recap is
never swallowed by an earlier item.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)


def _is_transient_db_error(exc: Exception) -> bool:
    """True for self-recovering DB/connection blips (pooled connection closed
    under a celery asyncio.run() loop, server-side idle drop, timeouts). These
    heal on the next run and must not be escalated to David as a malfunction."""
    transient_names = {
        "InterfaceError", "OperationalError", "DisconnectionError",
        "TimeoutError", "ConnectionDoesNotExistError", "ConnectionResetError",
    }
    seen = set()
    cur = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if type(cur).__name__ in transient_names:
            return True
        msg = str(cur).lower()
        if ("the underlying connection is closed" in msg
                or "connection is closed" in msg
                or "connection was closed" in msg
                or "event loop is closed" in msg):
            return True
        cur = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)
    return False


# ── Tunables ──────────────────────────────────────────────────────────────
CHECKIN_START_HOUR = 8           # 8am
CHECKIN_END_HOUR = 21            # stop after 9pm (hour < 21)
MIN_INTERRUPTIBILITY = 0.5       # below this, stay quiet
# Activity states where a check-in would be an intrusion. ActivityState.value
# is lowercase (e.g. "in_meeting").
QUIET_STATES = {"sleeping", "focused_work", "in_meeting", "exercising", "winding_down"}
DAILY_CHECKIN_CAP = 5            # hard ceiling across ambient + follow-ups
AMBIENT_GAP_HOURS = 5.0          # only ping "just because" after a long quiet stretch

# Post-meeting
MEETING_MIN_MINUTES = 15         # ignore sub-15-min blips
MEETING_LOOKBACK_MIN = 25        # catch meetings that ended within this window
MEETING_FOLLOWUP_DELAY_MIN = 8   # let David breathe before following up
MEETING_FOLLOWUP_WINDOW_HRS = 3  # follow-up is stale after this


def _in_waking_hours() -> bool:
    return CHECKIN_START_HOUR <= local_now().hour < CHECKIN_END_HOUR


def _interruptible() -> tuple[bool, str, float]:
    """Return (ok, state_value, score)."""
    try:
        from app.services.activity_state_machine import activity_state_machine
        from app.services.interruptibility import compute_interruptibility

        snap = activity_state_machine.current
        state = (snap.state.value or "unknown").lower()
        score = compute_interruptibility(snap).score
        ok = state not in QUIET_STATES and score >= MIN_INTERRUPTIBILITY
        return ok, state, score
    except Exception as e:
        logger.debug(f"[checkin] interruptibility check failed: {e}")
        return False, "unknown", 0.0


async def _checkins_sent_today(db, user_id: str) -> int:
    """Count check-in/follow-up notifications actually sent so far today (ET)."""
    res = await db.execute(text("""
        SELECT COUNT(*) FROM notification_log
        WHERE user_id = :uid
          AND sent = TRUE
          AND category IN ('checkin', 'followup')
          AND sent_at >= (date_trunc('day', NOW() AT TIME ZONE 'America/New_York')
                          AT TIME ZONE 'America/New_York')
    """), {"uid": user_id})
    return int(res.scalar() or 0)


async def _send(user_id: str, *, title: str, message: str, category: str,
                topic: str, priority: str = "normal", stimulus_key: str | None = None) -> dict:
    from app.services.unified_notification import send_notification
    # No priority floor here (SARA_UNLEASHED Phase A.3): whether this actually
    # buzzes the phone is decided once, centrally, by
    # unified_notification.route_through_attention_queue's learned buzz
    # decision (trailing engagement + interruptibility). A caller inflating
    # priority to defeat that routing is exactly the bug this phase removes.
    return await send_notification(
        user_id=user_id,
        title=title,
        message=message,
        priority=priority,
        topic=topic,
        category=category,
        source="proactive_checkin",
        extra_push_data={"target": "chat"},
        payload={
            "prediction_grade": "novel",
            "stimulus_key": stimulus_key or topic,
            "generator": "proactive_checkins",
        },
    )


async def _dual_write_candidate(user_id: str, t: dict, message: str, topic: str) -> None:
    """Mind V2 rewire plan Workstream B.2 — feed the say_candidate queue
    with the same real thread content the legacy send above already
    delivers. Legacy send is untouched; this is additive only, wrapped so
    a candidate-queue failure never breaks the legacy send."""
    try:
        from datetime import timedelta as _timedelta
        from app.services.say_candidate import create_candidate
        from app.db.session import get_async_session_factory

        valid_until = t.get("follow_up_before") or (local_now() + _timedelta(hours=24))
        factory = get_async_session_factory()
        async with factory() as db:
            await create_candidate(
                db, user_id=user_id,
                source="proactive_checkin", kind="followup", summary=message,
                evidence=[{"thread_id": t["id"], "topic": topic}],
                topic_entities=[topic],
                value_guess=t.get("priority"),
                valid_until=valid_until,
                dedupe_key=topic,
            )
    except Exception as e:
        logger.warning(f"[say_candidate] proactive_checkin dual-write failed: {e}")


async def run_followup_sweep(user_id: str) -> dict:
    """Deliver the single ripest open thread (meeting recap or commitment), if
    any. No template or ambient pings — those are gone (Phase A.1). Safe to
    call often; a no-op most of the time by design."""
    if not _in_waking_hours():
        return {"skipped": "outside_hours"}

    ok, state, score = _interruptible()
    if not ok:
        return {"skipped": "not_interruptible", "state": state, "score": round(score, 2)}

    from app.db.session import get_async_session_factory
    from app.services.thread_manager import get_open_threads, record_mention
    factory = get_async_session_factory()

    # Transient asyncpg/pool blips (connection closed under the celery
    # asyncio.run() loop, server-side idle drop) used to bubble up as a task
    # FAILURE and get escalated to David as "my check-ins failed N× today". They
    # self-recover on the next 15-min run, so they are noise, not a malfunction he
    # should act on: catch them, log, and skip this cycle quietly.
    try:
        # ── Reads in a SHORT session, released BEFORE the slow notification send
        #    so we never hold a pooled connection across network I/O (that idle
        #    window is where the connection was dying). ──
        async with factory() as db:
            sent_today = await _checkins_sent_today(db, user_id)
            if sent_today >= DAILY_CHECKIN_CAP:
                return {"skipped": "daily_cap", "sent_today": sent_today}

            # Ripe thread follow-up (post-meeting recaps + commitments) — the only
            # remaining path. Always payload-carrying: a thread always names a
            # concrete meeting, commitment, or topic.
            threads = await get_open_threads(user_id, db)
            if not threads:
                return {"skipped": "nothing_to_say", "state": state}

            t = threads[0]
            stimulus_key = f"followup:{t['id']}"
            try:
                from app.services.habituation import should_generate
                if not await should_generate(db, "proactive_checkins", stimulus_key):
                    return {"skipped": "habituated", "stimulus_key": stimulus_key}
            except Exception as e:
                logger.debug(f"[checkin] habituation check skipped: {e}")

        message = (t.get("suggested_followup") or "").strip() or f"Wanted to follow up on {t['topic']}."
        topic = f"followup:{t['id'][:12]}"
        res = await _send(
            user_id,
            title="Hey David",
            message=message,
            category="followup",
            topic=topic,
            priority="normal",
            stimulus_key=stimulus_key,
        )
        await _dual_write_candidate(user_id, t, message, topic)
        # Record the mention in a fresh short session (connection was never held
        # across the send above).
        if res.get("sent"):
            async with factory() as db2:
                await record_mention(t["id"], db2)
                await db2.commit()
        return {"sent": bool(res.get("sent")), "kind": "thread",
                "meeting": t.get("category") == "meeting", "reason": res.get("reason")}
    except Exception as e:
        if _is_transient_db_error(e):
            logger.warning(f"[checkin] transient DB blip, skipping this cycle: {e}")
            return {"skipped": "transient_db_error", "error": type(e).__name__}
        raise


# Back-compat alias — anything importing the old name keeps working.
run_checkin_sweep = run_followup_sweep


async def scan_ended_meetings(user_id: str) -> dict:
    """Open a one-shot follow-up thread for any real meeting that just ended."""
    from app.db.session import get_async_session_factory

    # calendar_event times are stored NAIVE in local (ET) wall-clock, so compare
    # against a naive-ET "now". Thread timing uses UTC to match NOW() elsewhere.
    now_local = local_now().replace(tzinfo=None)
    now_utc = datetime.now(timezone.utc)

    factory = get_async_session_factory()
    created = 0
    async with factory() as db:
        rows = (await db.execute(text("""
            SELECT id, title, start_time, end_time, attendees
            FROM calendar_event
            WHERE user_id = :uid
              AND all_day = FALSE
              AND end_time <= :now_local
              AND end_time >= :now_local - MAKE_INTERVAL(mins => :lookback)
              AND EXTRACT(EPOCH FROM (end_time - start_time)) >= :min_secs
            ORDER BY end_time DESC
            LIMIT 10
        """), {
            "uid": user_id,
            "now_local": now_local,
            "lookback": MEETING_LOOKBACK_MIN,
            "min_secs": MEETING_MIN_MINUTES * 60,
        })).fetchall()

        if not rows:
            return {"scanned": 0, "created": 0}

        from app.services.thread_manager import create_thread
        from app.services.person_service import bump_meeting_attendees

        for ev in rows:
            title = (ev.title or "your meeting").strip()

            # Dedup: skip if we already opened a follow-up for this event recently.
            # This same check gates the D.5 attendee bump below — the scan runs
            # every 10 min with a 25-min lookback, so a single meeting can appear
            # across 2-3 scan cycles; without this gate the bump (and
            # interaction_count) would fire multiple times for one meeting.
            exists = (await db.execute(text("""
                SELECT 1 FROM followup_thread
                WHERE user_id = :uid
                  AND source = 'meeting'
                  AND original_context LIKE :evkey
                  AND opened_at >= NOW() - INTERVAL '1 day'
                LIMIT 1
            """), {"uid": user_id, "evkey": f"%event:{ev.id}%"})).fetchone()
            if exists:
                continue

            # SARA_UNLEASHED Phase D.5: bump attendees now that the meeting has
            # genuinely concluded — link_attendees_to_people (calendar sync
            # time) only bumps if the event was already in the past AT SYNC
            # TIME, which most real meetings aren't (they sync before they
            # happen). This is the hook that actually fires for a normal
            # "meeting happened today" case.
            try:
                if ev.attendees:
                    await bump_meeting_attendees(db, user_id, ev.attendees)
            except Exception as e:
                logger.debug(f"Meeting attendee bump failed for event {ev.id}: {e}")

            await create_thread(
                user_id=user_id,
                topic=title,
                category="meeting",
                follow_up_after=now_utc + timedelta(minutes=MEETING_FOLLOWUP_DELAY_MIN),
                follow_up_before=now_utc + timedelta(hours=MEETING_FOLLOWUP_WINDOW_HRS),
                max_mentions=1,
                original_context=f"Meeting '{title}' just wrapped up. event:{ev.id}",
                suggested_followup=f"How'd {title} go?",
                priority=0.7,
                db=db,
                source="meeting",
            )
            created += 1

        if created:
            await db.commit()
        return {"scanned": len(rows), "created": created}
