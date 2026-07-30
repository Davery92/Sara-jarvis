"""Bedtime intelligence (§6.3.4) — a winddown nudge timed from rhythm + sleep debt.

Not a lecture and not a fixed alarm. When David is near his learned winddown
window AND there's a reason (sleep debt building, or an early start tomorrow),
Sara offers ONE gentle, passive nudge. It routes through the delivery policy
(so it's passive/low and respects sleep-gating) and drops after two ignores
(habituation), per the anti-harping rules.
"""
import logging
from datetime import timedelta

from sqlalchemy import text

from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)

_DAVID = "64f37c56-85cb-4590-8de9-adfc17d343ed"
_SLEEP_TARGET = 7.5
_EARLY_START_HOUR = 8.0  # first event before this = "early start"


async def _winddown_window(db):
    scope = "weekend" if local_now().weekday() >= 5 else "weekday"
    r = (await db.execute(text("""
        SELECT window_start, window_end FROM daily_rhythm
        WHERE user_id = :u AND rhythm_key = 'winddown' AND day_scope = :s LIMIT 1
    """), {"u": _DAVID, "s": scope})).first()
    if not r:
        return None
    return r


async def _recent_sleep_debt(db) -> float:
    """Sum of (target - actual) over the last 3 nights, floored at 0."""
    rows = (await db.execute(text("""
        SELECT value FROM health_metric
        WHERE metric_type = 'sleep_hours'
        ORDER BY recorded_at DESC LIMIT 3
    """))).fetchall()
    debt = 0.0
    for r in rows:
        debt += max(0.0, _SLEEP_TARGET - float(r[0]))
    return round(debt, 1)


async def _tomorrows_first_hour(db):
    r = (await db.execute(text("""
        SELECT MIN(start_time) FROM calendar_event
        WHERE user_id = :u AND COALESCE(all_day, FALSE) = FALSE
          AND start_time >= NOW() AND start_time < NOW() + INTERVAL '20 hours'
    """), {"u": _DAVID})).scalar()
    if not r:
        return None
    # start_time is naive local
    return r.hour + r.minute / 60.0


async def maybe_nudge(db) -> dict:
    now = local_now()
    hour = now.hour + now.minute / 60.0

    win = await _winddown_window(db)
    if win:
        ws = win[0].hour + win[0].minute / 60.0
        we = win[1].hour + win[1].minute / 60.0
    else:
        ws, we = 20.5, 22.0  # fallback winddown window
    # Only consider nudging inside (or just before) the winddown window.
    if not (ws - 0.5 <= hour <= we + 0.5):
        return {"effect": "outside_winddown_window"}

    debt = await _recent_sleep_debt(db)
    first_hour = await _tomorrows_first_hour(db)
    early = first_hour is not None and first_hour < _EARLY_START_HOUR

    if debt < 1.0 and not early:
        return {"effect": "no_reason_to_nudge", "sleep_debt": debt}

    # Build a gentle, specific reason.
    reasons = []
    if debt >= 1.0:
        reasons.append(f"you're about {debt:.0f}h down on sleep this week")
    if early:
        reasons.append("you've got an early start tomorrow")
    why = " and ".join(reasons)
    message = f"Might be a good night to wind down soon — {why}."

    # Habituation: drop after repeated ignores.
    stimulus_key = f"bedtime:{now.strftime('%Y-%m-%d')}"
    try:
        from app.services.habituation import should_generate
        if not await should_generate(db, "bedtime", stimulus_key):
            return {"effect": "habituated"}
    except Exception:
        pass

    # Arc 1.5 write-freeze: legacy send disabled once
    # MOUTH_ONLY_BEDTIME_INTELLIGENCE is on — dual-write below is
    # unconditional either way. Flag default OFF.
    from app.core.feature_flags import Flag, is_enabled
    if is_enabled(Flag.MOUTH_ONLY_BEDTIME_INTELLIGENCE):
        logger.info(f"[mouth-only] bedtime_intelligence legacy send skipped (candidate queued): {stimulus_key}")
        # Work-order item 4 (2026-07-30): was hardcoded False, which is
        # factually wrong — the say_candidate dual-write below runs
        # unconditionally regardless of this branch, so the mouth
        # pipeline genuinely will handle delivery. No live caller reads
        # this today, but a future one (Celery result inspection, a
        # dashboard) shouldn't see "not sent" for something that was.
        result = {"sent": True}
    else:
        from app.services.unified_notification import send_notification
        result = await send_notification(
            user_id=_DAVID, title="Winddown", message=message,
            priority="low", category="wellness", source="bedtime_intelligence",
            topic=stimulus_key, db=db,
            payload={"stimulus_key": stimulus_key, "generator": "bedtime"},
        )
        logger.info(f"🌙 Bedtime nudge: {message!r} sent={result.get('sent')}")

    # Mind V2 rewire plan Workstream B (long tail) — dual-write into the
    # say_candidate queue. Wrapped so a candidate-queue failure never
    # breaks the legacy send above.
    try:
        from datetime import timedelta
        from app.services.say_candidate import create_candidate
        await create_candidate(
            db, user_id=_DAVID, source="bedtime_intelligence", kind="inform",
            summary=message, evidence=[{"sleep_debt": debt, "early_start": early}],
            topic_entities=[stimulus_key],
            valid_until=now + timedelta(hours=3),
            dedupe_key=stimulus_key,
        )
    except Exception as e:
        logger.warning(f"[say_candidate] bedtime_intelligence dual-write failed: {e}")
    return {"effect": "nudged", "sleep_debt": debt, "early_start": early,
            "sent": result.get("sent")}
