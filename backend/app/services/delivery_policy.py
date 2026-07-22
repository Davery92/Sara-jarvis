"""Unified delivery policy (§3.6) — one brain decides every interruption.

Every David-directed push funnels through ``_send_notification_impl`` in
``unified_notification.py``, so a single consult there is genuinely "one mouth."

v1 scope (the highest-leverage slice): **sleep-gating**. The audit's N1 finding
was a ``system_health`` push at 05:23 AM while the system's own working-memory
had recorded ``availability: sleeping`` — the escalation sweep had no sleep gate
of any kind. Here, David-state (asleep/awake) is *sensed* from real signals:

  1. iPhone Focus sensor (``binary_sensor.david_s_iphone_focus``) — ON overnight
     is the strongest real-time sleep signal (learned: on ~21:47, off ~05:15).
  2. Home quiet — no ``home_activity_log`` events in the last ~20 min.
  3. Learned rhythm — ``daily_rhythm`` bedtime→wake windows bound the night.
  4. Recent interaction — if David just typed to Sara, he is plainly awake.

Non-critical items sent while asleep are HELD (persisted to ``held_notification``)
and flushed as a single digest at sensed wake (``tasks/delivery_flush.py``).
Security-class and ``critical`` priority always deliver — quiet hours never apply
to a lock failure or an acute health anomaly.

Fail-open: any sensing error returns "awake / deliver" and logs. A stuck hold
queue would be its own silent failure, and critical/security already bypass.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Optional, Dict, Any

from sqlalchemy import text

from app.core.timezone import now as local_now, to_naive_utc

logger = logging.getLogger(__name__)

FOCUS_ENTITY = "binary_sensor.david_s_iphone_focus"

# Categories/priorities that must always deliver, even at 4 AM.
_ALWAYS_DELIVER_CATEGORIES = {"security"}
_ALWAYS_DELIVER_PRIORITIES = {"critical"}
# Sources whose whole job is to deliver batched/at-wake content — never hold
# these (they ARE the flush vehicle, or are expected/zero-interruption).
_ALWAYS_DELIVER_SOURCES = {
    "morning_brief", "daily_brief", "evening_digest", "held_flush",
    "delivery_flush",
}

# Fallback night window when rhythm is unknown.
_FALLBACK_BEDTIME = time(22, 0)
_FALLBACK_WAKE = time(6, 30)


@dataclass
class SleepState:
    asleep: bool
    confidence: float
    source: str
    signals: list = field(default_factory=list)
    expected_wake: Optional[datetime] = None  # aware ET


@dataclass
class DeliveryDecision:
    action: str  # "deliver" | "hold" | "drop"
    reason: str
    deliver_after: Optional[datetime] = None  # aware ET
    why_trace: Dict[str, Any] = field(default_factory=dict)


def _time_to_hour(t: time) -> float:
    return t.hour + t.minute / 60.0


def _within_night(hour: float, bed: float, wake: float) -> bool:
    """Night window typically wraps midnight (bed 21.0, wake 6.5)."""
    if bed <= wake:  # degenerate / same-day window
        return bed <= hour < wake
    return hour >= bed or hour < wake


async def _night_window(db, now_et: datetime) -> tuple[float, float]:
    """Return (bedtime_hour, wake_end_hour) in ET decimal hours from daily_rhythm,
    falling back to sensible defaults. Uses the widest reasonable bounds so we
    only *consider* sleep at night — a positive signal is still required."""
    scope = "weekend" if now_et.weekday() >= 5 else "weekday"
    bed_h = _time_to_hour(_FALLBACK_BEDTIME)
    wake_h = _time_to_hour(_FALLBACK_WAKE)
    try:
        row = (await db.execute(text("""
            SELECT rhythm_key, median_time, window_start, window_end
            FROM daily_rhythm
            WHERE user_id = :uid AND rhythm_key IN ('bedtime','wake')
              AND day_scope = :scope
        """), {"uid": _DAVID, "scope": scope})).fetchall()
        by_key = {r[0]: r for r in row}
        if "bedtime" in by_key and by_key["bedtime"][1]:
            bed_h = _time_to_hour(by_key["bedtime"][1])
        if "wake" in by_key and by_key["wake"][3]:
            # window_end of wake = latest he's normally up by
            wake_h = _time_to_hour(by_key["wake"][3])
    except Exception as e:
        logger.debug(f"night_window rhythm lookup failed: {e}")
    return bed_h, wake_h


_DAVID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


async def _latest_focus_on(db) -> Optional[bool]:
    try:
        row = (await db.execute(text("""
            SELECT to_state FROM home_activity_log
            WHERE entity_id = :e
            ORDER BY changed_at DESC LIMIT 1
        """), {"e": FOCUS_ENTITY})).first()
        if not row:
            return None
        return str(row[0]).lower() in ("on", "true", "1")
    except Exception as e:
        logger.debug(f"focus lookup failed: {e}")
        return None


async def _home_quiet(db, minutes: int = 20) -> Optional[bool]:
    """True if no home activity in the last `minutes`. None if table unavailable."""
    try:
        cnt = (await db.execute(text("""
            SELECT COUNT(*) FROM home_activity_log
            WHERE changed_at > NOW() - MAKE_INTERVAL(mins => :m)
        """), {"m": minutes})).scalar()
        return (cnt or 0) == 0
    except Exception as e:
        logger.debug(f"home_quiet lookup failed: {e}")
        return None


async def _minutes_since_interaction(db, user_id: str) -> Optional[float]:
    """Minutes since David last interacted (most recent user-role episode)."""
    try:
        last = (await db.execute(text("""
            SELECT MAX(created_at) FROM episode
            WHERE user_id = :uid AND role = 'user'
        """), {"uid": user_id})).scalar()
        if not last:
            return None
        last = to_naive_utc(last)
        now = to_naive_utc(local_now())
        return (now - last).total_seconds() / 60.0
    except Exception as e:
        logger.debug(f"interaction lookup failed: {e}")
        return None


async def sense_sleep_state(db, user_id: str) -> SleepState:
    """Sense whether David is currently asleep. Fail-open to awake."""
    try:
        now_et = local_now()
        hour = now_et.hour + now_et.minute / 60.0
        bed_h, wake_h = await _night_window(db, now_et)
        in_night = _within_night(hour, bed_h, wake_h)

        # Expected wake = next occurrence of wake_h in ET.
        wake_dt = now_et.replace(hour=int(wake_h), minute=int((wake_h % 1) * 60),
                                 second=0, microsecond=0)
        if wake_dt <= now_et:
            wake_dt = wake_dt + timedelta(days=1)

        if not in_night:
            return SleepState(False, 0.9, "daytime", ["outside_night_window"], wake_dt)

        mins_since = await _minutes_since_interaction(db, user_id)
        if mins_since is not None and mins_since < 20:
            # He just talked to Sara — clearly awake, even at night.
            return SleepState(False, 0.95, "recent_interaction",
                              [f"interaction_{int(mins_since)}m_ago"], wake_dt)

        focus_on = await _latest_focus_on(db)
        quiet = await _home_quiet(db, 20)

        signals = []
        conf = 0.0
        if focus_on is True:
            signals.append("iphone_focus_on")
            conf = max(conf, 0.9)
        if quiet is True:
            signals.append("home_quiet")
            conf = max(conf, 0.6)

        # In the night window with a positive sleep signal → asleep.
        if signals:
            return SleepState(True, conf, "sensed", signals, wake_dt)

        # Night window but no positive signal (focus off, home active, but no
        # recent chat) — ambiguous. Deep-night hours (past bedtime, before a
        # very early hour) default to asleep at low confidence; the shoulder
        # hours default to awake so we don't over-suppress the evening.
        deep_night = _within_night(hour, max(bed_h, 23.0), min(wake_h, 5.0)) \
            if (max(bed_h, 23.0) != min(wake_h, 5.0)) else False
        if deep_night:
            return SleepState(True, 0.5, "night_default", ["deep_night_no_signal"], wake_dt)
        return SleepState(False, 0.4, "night_shoulder", ["no_sleep_signal"], wake_dt)
    except Exception as e:
        logger.warning(f"sense_sleep_state failed (fail-open to awake): {e}")
        return SleepState(False, 0.0, "error", ["sense_error"], None)


async def decide_delivery(
    db, user_id: str, category: str, priority: str, source: str,
) -> DeliveryDecision:
    """Decide whether a push should deliver now, be held until wake, or drop.

    v1 is a sleep gate only; the richer channel/timing matrix (§3.6) layers on
    later. Exemptions (security, critical, brief-flush sources) always deliver.
    """
    cat = (category or "").lower()
    prio = (priority or "").lower()
    src = (source or "").lower()

    if prio in _ALWAYS_DELIVER_PRIORITIES:
        return DeliveryDecision("deliver", "exempt_priority_critical")
    if cat in _ALWAYS_DELIVER_CATEGORIES:
        return DeliveryDecision("deliver", "exempt_category_security")
    if src in _ALWAYS_DELIVER_SOURCES:
        return DeliveryDecision("deliver", "exempt_source_batched")

    sleep = await sense_sleep_state(db, user_id)

    # Shadow-mode ML (§4.2.5): log the notification_value model's opinion next to
    # the heuristic decision so we can watch it before it ever gates anything.
    # It does NOT change the decision yet — promotion to a real gate comes only
    # after the shadow-mode comparison shows it winning.
    ml_opinion = await _notification_value_opinion(db, user_id, category, priority, sleep)

    if sleep.asleep and sleep.confidence >= 0.5:
        return DeliveryDecision(
            action="hold",
            reason=f"asleep:{sleep.source}",
            deliver_after=sleep.expected_wake,
            why_trace={
                "sleep_source": sleep.source,
                "sleep_confidence": round(sleep.confidence, 2),
                "sleep_signals": sleep.signals,
                "category": category,
                "priority": priority,
                "ml_p_valuable": ml_opinion,
            },
        )
    return DeliveryDecision("deliver", f"awake:{sleep.source}",
                            why_trace={"ml_p_valuable": ml_opinion})


async def _notification_value_opinion(db, user_id, category, priority, sleep) -> Optional[float]:
    """Shadow inference: what would the trained model say about this push?"""
    try:
        from app.services.ml.notification_value import predict
        now_et = local_now()
        interrupt = 0.2 if sleep.asleep else 0.7
        result = await predict(db, {
            "hour": now_et.hour,
            "day_of_week": now_et.weekday(),
            "activity_state": "sleeping" if sleep.asleep else "unknown",
            "interruptibility_score": interrupt,
            "category": category,
            "device": None,
        }, user_id=user_id, mode="shadow")
        return round(result[0], 4) if result else None
    except Exception as e:
        logger.debug(f"notification_value shadow opinion skipped: {e}")
        return None


async def hold_notification(
    db, *, user_id: str, title: str, message: str, category: str,
    priority: str, source: str, topic: Optional[str],
    payload: Optional[Dict[str, Any]], decision: DeliveryDecision,
) -> Optional[int]:
    """Persist a held notification. Returns row id (or None on failure)."""
    import json
    try:
        deliver_after = to_naive_utc(decision.deliver_after) if decision.deliver_after else None
        row = (await db.execute(text("""
            INSERT INTO held_notification
              (user_id, title, message, category, priority, source, topic,
               payload, why_trace, held_reason, deliver_after, status)
            VALUES
              (:uid, :title, :msg, :cat, :prio, :src, :topic,
               CAST(:payload AS jsonb), CAST(:why AS jsonb), :reason, :deliver_after, 'held')
            RETURNING id
        """), {
            "uid": user_id, "title": title[:500], "msg": (message or "")[:2000],
            "cat": category, "prio": priority, "src": source, "topic": topic,
            "payload": json.dumps(payload or {}, default=str),
            "why": json.dumps(decision.why_trace or {}, default=str),
            "reason": decision.reason,
            "deliver_after": deliver_after,
        })).first()
        await db.commit()
        hid = row[0] if row else None
        logger.info(
            f"📥 Held notification (asleep) id={hid} category={category} "
            f"title={title[:50]!r} reason={decision.reason}"
        )
        return hid
    except Exception as e:
        logger.warning(f"Failed to persist held notification: {e}")
        try:
            await db.rollback()
        except Exception:
            pass
        return None
