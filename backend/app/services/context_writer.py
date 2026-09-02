"""
Context Writer — incremental updates to the Unified Context Snapshot.

Every system calls update_fields() to write its slice of reality.
Notable changes are auto-appended to the changes_since_last_chat list
so check-ins and re-entry context know what happened while David was away.
"""

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.timezone import now as local_now

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.unified_context import (
    CHANGES_KEY,
    SNAPSHOT_KEY,
    UnifiedContextSnapshot,
    read_snapshot,
    _get_redis,
)

logger = logging.getLogger(__name__)

# Fields whose changes are auto-appended to the changes list
NOTABLE_FIELDS = {
    "activity_state",
    "mood",
    "home_occupied",
    "next_event_title",
    "next_event_minutes_away",
    "temperature_outside",
    "weather_condition",
    "in_flow_state",
    "current_place",
}


async def update_fields(user_id: str, source: str = "unknown", **kwargs) -> None:
    """
    Atomic partial update of snapshot fields in Redis.
    Only writes the provided fields, bumps version + updated_at.
    Optionally auto-appends to changes list for notable fields.
    """
    if not kwargs:
        return
    try:
        r = await _get_redis()
        key = SNAPSHOT_KEY.format(user_id=user_id)

        # Read current values for change detection on notable fields
        notable_updates = {}
        if any(k in NOTABLE_FIELDS for k in kwargs):
            current_vals = await r.hmget(key, *[k for k in kwargs if k in NOTABLE_FIELDS])
            notable_keys = [k for k in kwargs if k in NOTABLE_FIELDS]
            for i, k in enumerate(notable_keys):
                old_val = current_vals[i] if current_vals[i] else None
                new_val = kwargs[k]
                # Only track if actually changed
                if str(new_val) != str(old_val) and old_val is not None:
                    notable_updates[k] = (old_val, new_val)

        # Serialize values for Redis hash
        updates = {}
        for k, v in kwargs.items():
            if v is None:
                updates[k] = ""
            elif isinstance(v, (list, dict)):
                updates[k] = json.dumps(v)
            elif isinstance(v, bool):
                updates[k] = "1" if v else "0"
            else:
                updates[k] = str(v)

        # Always bump version and updated_at
        updates["updated_at"] = local_now().isoformat()

        # Atomic write
        pipe = r.pipeline()
        pipe.hset(key, mapping=updates)
        pipe.hincrby(key, "version", 1)
        await pipe.execute()

        # Auto-append notable changes
        for field_name, (old, new) in notable_updates.items():
            change = _describe_change(field_name, old, new, source)
            if change:
                await append_change(user_id, change)

        logger.debug(f"[ContextWriter] Updated {len(kwargs)} fields for {user_id} from {source}")
    except Exception as e:
        logger.warning(f"[ContextWriter] Failed to update fields: {e}")


async def append_change(user_id: str, change_description: str) -> None:
    """Add a human-readable change to the list (FIFO, max 50)."""
    try:
        r = await _get_redis()
        key = CHANGES_KEY.format(user_id=user_id)
        timestamp = local_now().strftime("%H:%M")
        entry = f"[{timestamp}] {change_description}"
        pipe = r.pipeline()
        pipe.rpush(key, entry)
        pipe.ltrim(key, -50, -1)  # keep last 50
        await pipe.execute()
        logger.debug(f"[ContextWriter] Appended change: {entry}")
    except Exception as e:
        logger.warning(f"[ContextWriter] Failed to append change: {e}")


async def clear_changes(user_id: str) -> List[str]:
    """
    Read and clear the changes list. Called when David opens chat.
    Returns the changes that were cleared (for injection into context).
    """
    try:
        r = await _get_redis()
        key = CHANGES_KEY.format(user_id=user_id)
        pipe = r.pipeline()
        pipe.lrange(key, 0, -1)
        pipe.delete(key)
        results = await pipe.execute()
        changes = results[0] or []
        if changes:
            logger.info(f"[ContextWriter] Cleared {len(changes)} changes for {user_id}")
        return changes
    except Exception as e:
        logger.warning(f"[ContextWriter] Failed to clear changes: {e}")
        return []


async def rebuild_snapshot(user_id: str, db: Session) -> UnifiedContextSnapshot:
    """
    Full rebuild from DB. Used on Redis restart or first boot.
    Reads from subconscious_state, calendar_event, episode, notification_log, etc.
    """
    snapshot = UnifiedContextSnapshot()
    now = local_now()

    try:
        # ── Subconscious state (body + activity + presence) ──
        sub_row = db.execute(text("""
            SELECT activity_state, activity_confidence, activity_room,
                   interruptibility_score, body_state, body_state_context,
                   has_chatted_today, is_past_bedtime, inferred_mood,
                   inferred_energy_level, in_flow_state
            FROM subconscious_state
            WHERE user_id = :uid
        """), {"uid": user_id}).fetchone()

        if sub_row:
            snapshot.activity_state = sub_row.activity_state or "UNKNOWN"
            snapshot.activity_confidence = sub_row.activity_confidence or 0.5
            snapshot.room = sub_row.activity_room
            snapshot.interruptibility = sub_row.interruptibility_score or 0.5
            snapshot.has_chatted_today = bool(sub_row.has_chatted_today)
            snapshot.is_past_bedtime = bool(sub_row.is_past_bedtime)
            snapshot.mood = sub_row.inferred_mood
            snapshot.energy_level = sub_row.inferred_energy_level
            snapshot.in_flow_state = bool(sub_row.in_flow_state)

            # Parse body state JSON
            if sub_row.body_state:
                try:
                    bs = sub_row.body_state if isinstance(sub_row.body_state, dict) else json.loads(sub_row.body_state)
                    snapshot.alertness = bs.get("alertness", 0.5)
                    snapshot.stress_load = bs.get("stress_load", 0.3)
                    snapshot.blood_sugar = bs.get("blood_sugar", 0.5)
                    snapshot.circadian_phase = bs.get("circadian_phase", "normal")
                except (json.JSONDecodeError, TypeError):
                    pass

        # ── Last chat time ── (episode.created_at is naive-UTC; AT TIME ZONE 'UTC'
        # reattaches tzinfo so the subtraction below doesn't raise on an aware `now`)
        last_chat = db.execute(text("""
            SELECT created_at AT TIME ZONE 'UTC' AS created_at FROM episode
            WHERE user_id = :uid AND role = 'user'
            ORDER BY created_at DESC LIMIT 1
        """), {"uid": user_id}).fetchone()

        if last_chat and last_chat.created_at:
            snapshot.last_chat_at = last_chat.created_at.isoformat()
            delta = (now - last_chat.created_at).total_seconds() / 3600
            snapshot.hours_since_last_chat = round(delta, 1)

        # ── Calendar (next event + today's count) ──
        # calendar_event.start_time is naive local (ET); query and subtract
        # with naive ET or the comparison shifts by the UTC offset (and the
        # aware-naive subtraction raises, silently dropping next_event).
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/New_York")
        now_tz = datetime.now(tz).replace(tzinfo=None)
        today_start = now_tz.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start.replace(hour=23, minute=59, second=59)

        # Follow-up plan §5: an all-day event's midnight `start_time` is a
        # storage artifact, not a time David is due anywhere. Counting minutes
        # to it produced "in 13h" for a day-long trip, and every consumer of
        # next_event_minutes_away treated that as an appointment approaching.
        next_event = db.execute(text("""
            SELECT title, start_time, ios_calendar_name, COALESCE(all_day, FALSE) AS all_day
            FROM calendar_event
            WHERE user_id = :uid AND start_time > :now
            ORDER BY start_time ASC LIMIT 1
        """), {"uid": user_id, "now": now_tz}).fetchone()

        if next_event:
            from app.services.calendar_ownership import classify_event, ownership_prefix
            ownership = classify_event(next_event.title, next_event.ios_calendar_name)
            cal_label = f" [{next_event.ios_calendar_name}]" if next_event.ios_calendar_name else ""
            all_day_label = " (all day)" if next_event.all_day else ""
            snapshot.next_event_title = (
                f"{ownership_prefix(ownership)}{next_event.title}{cal_label}{all_day_label}"
            )
            if next_event.all_day:
                snapshot.next_event_minutes_away = None
            else:
                delta_min = (next_event.start_time - now_tz).total_seconds() / 60
                snapshot.next_event_minutes_away = int(delta_min)

        event_count = db.execute(text("""
            SELECT COUNT(*) FROM calendar_event
            WHERE user_id = :uid AND start_time BETWEEN :s AND :e
        """), {"uid": user_id, "s": today_start, "e": today_end}).scalar()
        snapshot.events_today_count = event_count or 0

        # ── Daily rhythm summary ──
        try:
            from app.services.daily_rhythm import build_rhythm_summary, stated_rhythm_keys
            # Follow-up plan §2: the deliberation whiteboard reads this line, so
            # it gets the same filtering as chat context — a stated life fact
            # wins, and a weak rhythm row says nothing at all.
            snapshot.rhythm_summary = build_rhythm_summary(
                db, user_id, exclude_keys=await stated_rhythm_keys(user_id))
        except Exception as e:
            logger.warning(f"[ContextWriter] rhythm summary gather failed: {e}")

        # ── Agent memory (last heartbeat) ──
        last_hb = db.execute(text("""
            SELECT run_at, handoff_note, watching_for
            FROM agent_run_log
            WHERE user_id = :uid AND source IN ('unified_agent', 'unified_heartbeat', 'deliberation', 'consolidation')
            ORDER BY run_at DESC LIMIT 1
        """), {"uid": user_id}).fetchone()

        if last_hb:
            snapshot.last_heartbeat_at = last_hb.run_at.isoformat() if last_hb.run_at else None
            snapshot.last_heartbeat_handoff = last_hb.handoff_note
            snapshot.last_heartbeat_watching_for = last_hb.watching_for

        # ── Notifications sent today ──
        notif_count = db.execute(text("""
            SELECT COUNT(*) FROM notification_log
            WHERE user_id = :uid AND sent_at >= :today AND sent = TRUE
        """), {"uid": user_id, "today": today_start}).scalar()
        snapshot.notifications_sent_today = notif_count or 0

        # ── Learning reviews — disabled ──

        # ── Comms (top unhandled important emails) ──
        try:
            rows = db.execute(text("""
                SELECT sender_name, sender_email, subject, received_at
                FROM email
                WHERE user_id=:uid AND is_read=false
                  AND (action_required = true OR importance_score >= 0.7)
                ORDER BY received_at ASC LIMIT 2
            """), {"uid": user_id}).fetchall()
            snapshot.comms_unhandled_count = len(rows)
            if rows:
                parts = []
                for r in rows:
                    who = r.sender_name or r.sender_email
                    age_h = (now - r.received_at).total_seconds() / 3600 if r.received_at else 0
                    parts.append(f"{who} — '{r.subject}' ({age_h:.0f}h ago)")
                snapshot.comms_unhandled_top = "; ".join(parts)
        except Exception as e:
            logger.warning(f"[ContextWriter] comms gather failed: {e}")

        # ── Open goals (title + days since progress) ──
        try:
            rows = db.execute(text("""
                SELECT title, last_progress_at FROM sara_goal
                WHERE COALESCE(status,'open') NOT IN ('done','abandoned','archived','completed')
                ORDER BY last_progress_at ASC NULLS FIRST LIMIT 5
            """)).fetchall()
            if rows:
                parts = []
                for r in rows:
                    days = int((now - r.last_progress_at).total_seconds() // 86400) if r.last_progress_at else None
                    parts.append(f"{r.title} ({days}d since progress)" if days is not None else f"{r.title} (no progress logged)")
                snapshot.open_goals_top = "; ".join(parts)
        except Exception as e:
            logger.warning(f"[ContextWriter] goals gather failed: {e}")

        # ── Active projects ──
        try:
            projects = db.execute(text("""
                SELECT name FROM project
                WHERE user_id = :uid AND status = 'active'
                ORDER BY updated_at DESC LIMIT 5
            """), {"uid": user_id}).fetchall()
            snapshot.active_projects = [p.name for p in projects] if projects else []
        except Exception:
            pass

        # Write to Redis
        from app.services.unified_context import write_snapshot
        import asyncio
        await write_snapshot(user_id, snapshot)
        logger.info(f"[ContextWriter] Full snapshot rebuild complete for {user_id}")
        return snapshot

    except Exception as e:
        logger.error(f"[ContextWriter] Snapshot rebuild failed: {e}")
        return snapshot


# Ground-truth plan, Phase 5 §8: a change worth telling David about on re-entry
# is a change to his email, calendar, tasks or threads — or to where he and his
# household actually are. The weather service refreshes on its own schedule and
# fills this buffer with temperature deltas nobody asked for: on 2026-09-02 the
# entire "what happened while you were away" block was ten outside-temperature
# lines. The data is still written to the snapshot; it just isn't news.
_NOISE_CHANGE_RE = re.compile(
    r"^\[?\d{0,2}:?\d{0,2}\]?\s*(outside temperature|weather)\b",
    re.IGNORECASE,
)


def is_meaningful_change(change: str) -> bool:
    """True when a notable-change line is worth showing David on re-entry."""
    return bool((change or "").strip()) and not _NOISE_CHANGE_RE.search(change.strip())


def _describe_change(field_name: str, old_val: Any, new_val: Any, source: str) -> Optional[str]:
    """Generate a human-readable change description."""
    descriptions = {
        "activity_state": lambda o, n: f"Activity changed to {n}",
        "mood": lambda o, n: f"Mood shifted to {n}",
        "home_occupied": lambda o, n: "David left home" if n in ("0", "False", False) else "David arrived home",
        "next_event_title": lambda o, n: f"Next up: {n}" if n else None,
        "temperature_outside": lambda o, n: f"Outside temperature: {n}°F",
        "weather_condition": lambda o, n: f"Weather: {n}",
        "in_flow_state": lambda o, n: "Entered flow state" if n in ("1", "True", True) else "Exited flow state",
        "current_place": lambda o, n: f"David arrived at {n}" if n and n != "unknown" else "David left" + (f" {o}" if o and o != "unknown" else ""),
    }
    formatter = descriptions.get(field_name)
    if formatter:
        return formatter(old_val, new_val)
    return None
