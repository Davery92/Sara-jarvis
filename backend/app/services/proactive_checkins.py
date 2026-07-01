"""
Proactive check-ins — occasional "how's it going" pings + post-meeting follow-ups.

Two entry points, both gated hard by interruptibility and anti-nag caps:

- ``scan_ended_meetings()`` — when a real meeting just wrapped, opens a
  ``followup_thread`` ("How'd that meeting go?"). It does NOT notify directly;
  the sweep delivers it once David is interruptible.
- ``run_checkin_sweep()`` — runs every ~15 min during waking hours. Delivers, in
  priority order: a ripe thread follow-up (post-meeting included), a contextual
  template check-in, or an occasional ambient ping after a long quiet stretch.

Everything is reused, not reinvented:
- ``thread_manager``            → anti-harping (max_mentions, drop-on-ignore)
- ``checkin_builder``           → deterministic check-in templates
- ``unified_context``           → the context snapshot
- ``activity_state_machine`` + ``interruptibility`` → never ping during a
  meeting, deep-focus work, exercise, wind-down, or sleep
- ``unified_notification.send_notification`` → dedup, cooldown, push delivery

Topics are namespaced so the existing per-category caps do the right thing:
ambient pings use ``checkin:`` (capped to ~1 per 6h by the pipeline), while
post-meeting follow-ups use ``followup:`` so a timely meeting recap is never
swallowed by an earlier ambient ping.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)

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
                topic: str, priority: str = "high") -> dict:
    from app.services.unified_notification import send_notification
    # Check-ins are interruptibility-gated upstream (waking hours + interruptibility
    # + daily cap), so by the time we get here this is an intentional ping that must
    # actually buzz the phone. route_through_attention_queue only pushes for
    # high/urgent/critical — normal/low become SILENT inbox items (no push, no
    # notification_log row). That's why proactive check-ins showed up in the inbox
    # but never delivered a push. Floor to high so the item is created AND pushed.
    if priority in ("low", "normal"):
        priority = "high"
    return await send_notification(
        user_id=user_id,
        title=title,
        message=message,
        priority=priority,
        topic=topic,
        category=category,
        source="proactive_checkin",
        extra_push_data={"target": "chat"},
    )


def _ambient_line() -> str:
    h = local_now().hour
    if h < 12:
        return "Morning — how's the day shaping up so far?"
    if h < 17:
        return "How's the afternoon going?"
    return "How's your evening going?"


async def run_checkin_sweep(user_id: str) -> dict:
    """Deliver at most one check-in if the moment is right. Safe to call often."""
    if not _in_waking_hours():
        return {"skipped": "outside_hours"}

    ok, state, score = _interruptible()
    if not ok:
        return {"skipped": "not_interruptible", "state": state, "score": round(score, 2)}

    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    async with factory() as db:
        sent_today = await _checkins_sent_today(db, user_id)
        if sent_today >= DAILY_CHECKIN_CAP:
            return {"skipped": "daily_cap", "sent_today": sent_today}

        # 1) Ripe thread follow-up (post-meeting recaps + chat threads) — most personal.
        from app.services.thread_manager import get_open_threads, record_mention
        threads = await get_open_threads(user_id, db)
        if threads:
            t = threads[0]
            message = (t.get("suggested_followup") or "").strip() or "Wanted to follow up on that."
            res = await _send(
                user_id,
                title="Hey David",
                message=message,
                category="followup",
                topic=f"followup:{t['id'][:12]}",
                priority="normal",
            )
            if res.get("sent"):
                await record_mention(t["id"], db)
                await db.commit()
            return {"sent": bool(res.get("sent")), "kind": "thread",
                    "meeting": t.get("category") == "meeting", "reason": res.get("reason")}

        # 2) Contextual check-in from deterministic templates.
        from app.services.unified_context import read_snapshot
        from app.services.checkin_builder import build_checkin
        snap = await read_snapshot(user_id)

        checkin = build_checkin(snap, changes=[], open_threads=None)
        if checkin:
            res = await _send(
                user_id,
                title=checkin.get("title", "Checking in"),
                message=checkin["message"],
                category="checkin",
                topic="checkin",
                priority=checkin.get("priority", "normal"),
            )
            return {"sent": bool(res.get("sent")), "kind": "contextual", "reason": res.get("reason")}

        # 3) Occasional ambient ping — only after a genuinely long quiet stretch.
        if (snap.hours_since_last_chat or 0) >= AMBIENT_GAP_HOURS:
            res = await _send(
                user_id,
                title="Checking in",
                message=_ambient_line(),
                category="checkin",
                topic="checkin",
                priority="normal",
            )
            return {"sent": bool(res.get("sent")), "kind": "ambient", "reason": res.get("reason")}

        return {"skipped": "nothing_to_say", "state": state}


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
            SELECT id, title, start_time, end_time
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

        for ev in rows:
            title = (ev.title or "your meeting").strip()
            # Dedup: skip if we already opened a follow-up for this event recently.
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
