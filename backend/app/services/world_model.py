"""
World Model (Phase 1)
=====================
Assembles the single live picture of "what is going on right now" that the
conscious tier reasons over and the god-view renders.

Two layers:
  • foreground — the balanced, relevant-now picture (where balance matters)
  • background — the ambient subconscious hum (high-volume, queryable, not pushed)

Read-only / derived. Phase 2 (Tier 0) will feed promoted anomalies into the
foreground; for now foreground active-work/next-event come straight from source
tables and Sara's internal state from working memory.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_FG_FIELDS = [
    "activity_state", "activity_confidence", "interruptibility",
    "hours_since_last_chat", "last_chat_topic", "has_chatted_today",
    "home_occupied", "open_thread_count",
    "sara_focus", "sara_emotional_tone", "sara_emotional_intensity",
    "sara_curiosities", "sara_deliberation_count_today",
    "observation_count", "salience_high_water", "last_heartbeat_watching_for",
]


def _snapshot_to_dict(snap) -> dict:
    for attr in ("model_dump", "dict", "_asdict"):
        fn = getattr(snap, attr, None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                pass
    if hasattr(snap, "__dict__"):
        return dict(snap.__dict__)
    return {}


async def assemble_world_state(user_id: str, db: Session) -> dict:
    """Build the full world model. Each source is independently fault-tolerant."""
    now = datetime.now(timezone.utc)
    fg: dict = {}
    bg: dict = {}

    # ── Sara's internal state + activity, from working memory ──
    try:
        from app.services.working_memory import read_memory
        snap = _snapshot_to_dict(await read_memory(user_id))
        for k in _FG_FIELDS:
            if k in snap:
                fg[k] = snap[k]
    except Exception as e:
        logger.warning(f"[world_model] working memory read failed: {e}")

    # ── Next calendar event (domain: calendar) ──
    # calendar_event.start_time is naive local (ET) — compare/subtract against a
    # naive ET `now`, not the aware UTC `now` used elsewhere in this function.
    fg["next_event"] = None
    try:
        from zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
        row = db.execute(text("""
            SELECT title, start_time FROM calendar_event
            WHERE user_id = :uid AND start_time > :now_et AND COALESCE(is_completed, false) = false
            ORDER BY start_time ASC LIMIT 1
        """), {"uid": user_id, "now_et": now_et}).fetchone()
        if row:
            mins = int((row[1] - now_et).total_seconds() // 60) if row[1] else None
            fg["next_event"] = {"title": row[0], "at": row[1].isoformat() if row[1] else None,
                                "in_minutes": mins}
    except Exception as e:
        logger.warning(f"[world_model] calendar query failed: {e}")

    # ── Active work (domain: work) — recent commits ──
    fg["active_work"] = []
    try:
        rows = db.execute(text("""
            SELECT message, author_name, branch, committed_at
            FROM git_commit
            WHERE committed_at > now() - interval '3 days'
            ORDER BY committed_at DESC LIMIT 6
        """)).fetchall()
        fg["active_work"] = [{
            "summary": (r[0] or "").splitlines()[0][:120],
            "author": r[1], "branch": r[2],
            "at": r[3].isoformat() if r[3] else None,
        } for r in rows]
    except Exception as e:
        logger.warning(f"[world_model] git_commit query failed: {e}")

    # ── FOREGROUND: unhandled important email (domain: comms) ──
    fg["comms_unhandled"] = []
    try:
        rows = db.execute(text("""
            SELECT sender_name, sender_email, subject, received_at
            FROM email
            WHERE user_id=:uid AND is_read=false
              AND (action_required = true OR importance_score >= 0.7)
            ORDER BY received_at ASC LIMIT 5
        """), {"uid": user_id}).fetchall()
        fg["comms_unhandled"] = [{
            "sender": r[0] or r[1], "subject": r[2],
            "age_hours": int((now - r[3]).total_seconds() // 3600) if r[3] else None,
        } for r in rows]
    except Exception as e:
        logger.warning(f"[world_model] comms query failed: {e}")

    # ── FOREGROUND: people (domain: people) — recent + overdue ──
    fg["people_recent"] = []
    fg["people_overdue"] = []
    try:
        rows = db.execute(text("""
            SELECT canonical_name, last_interaction_at, last_interaction_kind
            FROM person WHERE user_id=:uid AND muted = false AND last_interaction_at IS NOT NULL
            ORDER BY last_interaction_at DESC LIMIT 5
        """), {"uid": user_id}).fetchall()
        fg["people_recent"] = [{
            "name": r[0], "kind": r[2],
            "age_hours": int((now - r[1]).total_seconds() // 3600) if r[1] else None,
        } for r in rows]

        rows = db.execute(text("""
            SELECT p.canonical_name, p.last_interaction_at,
                   EXTRACT(EPOCH FROM (now() - p.last_interaction_at)) / 86400.0 AS days_since
            FROM person p
            JOIN signal_baseline sb ON sb.user_id = p.user_id
                AND sb.domain = 'people' AND sb.signal_key = 'cadence.' || p.id
            WHERE p.user_id=:uid AND p.muted = false AND sb.sample_count >= 2
              AND EXTRACT(EPOCH FROM (now() - p.last_interaction_at)) / 3600.0 > 2 * sb.ewma
            ORDER BY days_since DESC LIMIT 5
        """), {"uid": user_id}).fetchall()
        fg["people_overdue"] = [{"name": r[0], "days_since": round(float(r[2]), 1) if r[2] is not None else None}
                                for r in rows]
    except Exception as e:
        logger.warning(f"[world_model] people query failed: {e}")

    # ── BACKGROUND: home ambient (domain: home) ──
    bg["home"] = {"events_24h": 0, "top": []}
    try:
        n = db.execute(text("SELECT count(*) FROM home_activity_log WHERE changed_at > now() - interval '24 hours'")).scalar()
        rows = db.execute(text("""
            SELECT domain, count(*) FROM home_activity_log
            WHERE changed_at > now() - interval '24 hours'
            GROUP BY domain ORDER BY 2 DESC LIMIT 5
        """)).fetchall()
        bg["home"] = {"events_24h": int(n or 0), "top": [{"domain": d, "n": int(c)} for d, c in rows]}
    except Exception as e:
        logger.warning(f"[world_model] home query failed: {e}")

    # ── BACKGROUND: health ambient (domain: health) ──
    bg["health"] = {"metrics_24h": 0, "latest": None}
    try:
        n = db.execute(text("SELECT count(*) FROM health_metric WHERE recorded_at > now() - interval '24 hours' AND user_id = :uid"),
                       {"uid": user_id}).scalar()
        row = db.execute(text("""
            SELECT hrv, heart_rate, sleep_hours, body_weight, log_date
            FROM daily_recovery_log WHERE user_id = :uid
            ORDER BY log_date DESC LIMIT 1
        """), {"uid": user_id}).fetchone()
        latest = None
        if row:
            latest = {"hrv": row[0], "resting_hr": row[1], "sleep_hours": float(row[2]) if row[2] is not None else None,
                      "weight": float(row[3]) if row[3] is not None else None,
                      "date": row[4].isoformat() if row[4] else None}
        bg["health"] = {"metrics_24h": int(n or 0), "latest": latest}
    except Exception as e:
        logger.warning(f"[world_model] health query failed: {e}")

    bg["ambient_event_rate_24h"] = bg.get("home", {}).get("events_24h", 0) + bg.get("health", {}).get("metrics_24h", 0)

    # ── Which domains currently have any signal ──
    domains_present = []
    if fg.get("active_work"): domains_present.append("work")
    if fg.get("next_event"): domains_present.append("calendar")
    if bg.get("home", {}).get("events_24h"): domains_present.append("home")
    if bg.get("health", {}).get("metrics_24h"): domains_present.append("health")
    if fg.get("open_thread_count") or fg.get("comms_unhandled"): domains_present.append("comms")
    if fg.get("people_recent") or fg.get("people_overdue"): domains_present.append("people")

    return {
        "as_of": now.isoformat(),
        "foreground": fg,
        "background": bg,
        "domains_present": domains_present,
    }
