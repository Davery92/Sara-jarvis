"""
THE SYSTEM — awareness endpoints (Phase 0 + Phase 1)
====================================================
Read-only "god view" over Sara's existing cognition, plus the unified World Model.

Phase 0 (this file, read-only over existing data):
  GET /api/system/stream    — unified thought feed (sara_journal + agent_run_log)
  GET /api/system/balance   — attention-balance meter (domain distribution of what reached you)
  GET /api/system/world     — current working-memory snapshot (foreground subset)
  GET /api/system/overview  — bundle of the three for a single dashboard fetch

Phase 1 adds the assembled world_state (see app/services/world_model.py) under /world.
Nothing here mutates state.
"""
import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.timezone import now as local_now
from app.db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


def get_current_user_id() -> str:
    return os.getenv("SOLO_USER_ID", "default-user")


# ── Domain mapping: notification/observation categories → life domains ──────
# The balance axis. Keep in sync with app/services/world_model.py DOMAINS.
DOMAINS = ["work", "comms", "calendar", "health", "home", "goals", "people", "learning", "meta"]

_CATEGORY_DOMAIN = [
    # (substring, domain) — first match wins
    ("email", "comms"), ("chat", "comms"), ("checkin", "comms"), ("check_in", "comms"),
    ("message", "comms"), ("thread", "comms"), ("conversation", "comms"),
    ("agent_task", "work"), ("background_task", "work"), ("research", "work"),
    ("task", "work"), ("code", "work"), ("project", "work"), ("pull_request", "work"),
    ("calendar", "calendar"), ("schedule", "calendar"), ("reminder", "calendar"),
    ("wellness", "health"), ("health", "health"), ("recovery", "health"),
    ("fitness", "health"), ("workout", "health"), ("meal", "health"), ("nutrition", "health"),
    ("home", "home"), ("security", "home"), ("environment", "home"), ("comfort", "home"),
    ("learning_review", "learning"), ("learn", "learning"),
    ("goal", "goals"),
    ("person", "people"), ("relationship", "people"), ("people", "people"),
    # everything else (acs_*, general, timer, heartbeat, system_*) → meta
]


def domain_for_category(category: Optional[str]) -> str:
    c = (category or "").lower()
    for sub, dom in _CATEGORY_DOMAIN:
        if sub in c:
            return dom
    return "meta"


# ── World snapshot: which working-memory fields are "foreground" ───────────
_FOREGROUND_FIELDS = [
    "activity_state", "activity_confidence", "interruptibility",
    "hours_since_last_chat", "last_chat_topic", "has_chatted_today",
    "next_event_title", "next_event_minutes_away", "events_today_count",
    "home_occupied", "active_rooms", "weather_condition",
    "active_projects", "open_thread_count", "ripe_thread_topics",
    "sara_focus", "sara_emotional_tone", "sara_emotional_intensity",
    "sara_curiosities", "sara_deliberation_count_today", "sara_last_deliberation_at",
    "observation_count", "salience_high_water",
    "last_heartbeat_at", "last_heartbeat_watching_for",
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
    try:
        from dataclasses import asdict, is_dataclass
        if is_dataclass(snap):
            return asdict(snap)
    except Exception:
        pass
    return {}


@router.get("/world")
async def get_world(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Assembled world model: foreground (relevant-now) + background (ambient hum)."""
    try:
        from app.services.world_model import assemble_world_state
        world = await assemble_world_state(user_id, db)
        return {"foreground": world.get("foreground", {}), "world": world}
    except Exception as e:
        logger.warning(f"[system/world] assembly failed, falling back to working memory: {e}")

    # Fallback: raw working-memory snapshot only
    foreground = {}
    try:
        from app.services.working_memory import read_memory
        d = _snapshot_to_dict(await read_memory(user_id))
        foreground = {k: d.get(k) for k in _FOREGROUND_FIELDS if k in d}
    except Exception as e:
        logger.warning(f"[system/world] working memory read failed: {e}")
    return {"foreground": foreground, "world": None}


@router.get("/stream")
async def get_stream(
    limit: int = Query(40, ge=1, le=200),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Unified thought feed: Sara's journal + agent runs, newest first."""
    items = []

    try:
        rows = db.execute(text("""
            SELECT id::text, entry_type, content, emotional_state, created_at
            FROM sara_journal
            WHERE user_id = :uid
            ORDER BY created_at DESC LIMIT :lim
        """), {"uid": user_id, "lim": limit}).fetchall()
        for r in rows:
            items.append({
                "kind": "journal",
                "id": r[0],
                "subtype": r[1],
                "text": (r[2] or "")[:1200],
                "emotional_state": r[3],
                "at": r[4].isoformat() if r[4] else None,
            })
    except Exception as e:
        logger.warning(f"[system/stream] journal query failed: {e}")

    try:
        rows = db.execute(text("""
            SELECT COALESCE(run_uuid::text, id::text), source, context_summary,
                   actions_taken, notifications_sent, created_at
            FROM agent_run_log
            WHERE user_id = :uid
            ORDER BY created_at DESC LIMIT :lim
        """), {"uid": user_id, "lim": limit}).fetchall()
        for r in rows:
            items.append({
                "kind": "agent_run",
                "id": r[0],
                "subtype": r[1],
                "text": (r[2] or "")[:1200],
                "actions_taken": r[3],
                "notifications_sent": r[4],
                "at": r[5].isoformat() if r[5] else None,
            })
    except Exception as e:
        logger.warning(f"[system/stream] agent_run_log query failed: {e}")

    items.sort(key=lambda x: x["at"] or "", reverse=True)

    # Deliberation writes BOTH a journal row and an agent_run row with identical
    # text — collapse them, preferring the agent_run (it carries actions_taken).
    deduped = []
    seen_prefix = {}
    for it in items:
        key = (it.get("text") or "")[:80]
        if key and key in seen_prefix:
            prev = seen_prefix[key]
            if it["kind"] == "agent_run" and prev["kind"] == "journal":
                deduped[deduped.index(prev)] = it
                seen_prefix[key] = it
            continue
        seen_prefix[key] = it
        deduped.append(it)

    return {"items": deduped[:limit], "count": len(deduped[:limit])}


@router.get("/balance")
async def get_balance(
    hours: int = Query(168, ge=1, le=2160),  # default 7 days
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Attention-balance meter: domain distribution of what actually reached the user."""
    by_domain = {d: 0 for d in DOMAINS}
    by_category = {}
    total = 0
    try:
        rows = db.execute(text("""
            SELECT category, count(*) AS n
            FROM notification_log
            WHERE user_id = :uid AND sent_at > now() - (:hours || ' hours')::interval
            GROUP BY category
        """), {"uid": user_id, "hours": str(hours)}).fetchall()
        for cat, n in rows:
            dom = domain_for_category(cat)
            by_domain[dom] = by_domain.get(dom, 0) + int(n)
            by_category[cat or "uncategorized"] = int(n)
            total += int(n)
    except Exception as e:
        logger.warning(f"[system/balance] notification query failed: {e}")

    # also surface how much COGNITION happened (deliberations etc.) for context
    cognition = {}
    try:
        rows = db.execute(text("""
            SELECT source, count(*) FROM agent_run_log
            WHERE user_id = :uid AND created_at > now() - (:hours || ' hours')::interval
            GROUP BY source
        """), {"uid": user_id, "hours": str(hours)}).fetchall()
        cognition = {src: int(n) for src, n in rows}
    except Exception as e:
        logger.warning(f"[system/balance] cognition query failed: {e}")

    distribution = [
        {"domain": d, "count": by_domain[d],
         "pct": round(100.0 * by_domain[d] / total, 1) if total else 0.0}
        for d in DOMAINS
    ]
    distribution.sort(key=lambda x: x["count"], reverse=True)
    top = distribution[0] if distribution else None
    return {
        "window_hours": hours,
        "total_surfaced": total,
        "distribution": distribution,
        "by_category": by_category,
        "cognition": cognition,
        "skew_warning": bool(top and total and top["pct"] > 50.0),
        "top_domain": top["domain"] if top else None,
    }


@router.get("/promotions")
async def get_promotions(
    limit: int = Query(20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Recent subconscious→conscious promotions (Tier 0 output)."""
    items = []
    try:
        rows = db.execute(text("""
            SELECT created_at, domain, context, signal_key, significance, threshold_at_time,
                   reason, promoted, surfaced_as, description
            FROM promotion_event
            WHERE user_id = :uid AND promoted = true
            ORDER BY created_at DESC LIMIT :lim
        """), {"uid": user_id, "lim": limit}).fetchall()
        for r in rows:
            items.append({
                "at": r[0].isoformat() if r[0] else None, "domain": r[1], "context": r[2],
                "signal": r[3], "significance": round(float(r[4]), 3) if r[4] is not None else None,
                "threshold": round(float(r[5]), 3) if r[5] is not None else None,
                "reason": r[6], "surfaced_as": r[8], "description": r[9],
            })
    except Exception as e:
        logger.warning(f"[system/promotions] query failed: {e}")
    return {"items": items, "count": len(items)}


@router.get("/actions")
async def get_actions(
    limit: int = Query(20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Recent autonomous actions (Phase 4 of PHENOMENAL_ASSISTANT_PLAN.md) —
    what Sara did, why, and whether it can still be undone. Shared table with
    standing_order_service's original 5-min undo (source distinguishes them)."""
    items = []
    try:
        now = local_now()
        rows = db.execute(text("""
            SELECT id, action_type, source, action_config, success, executed_at,
                   undo_available, undo_expires_at, undone, undone_at
            FROM action_ledger
            WHERE user_id = :uid
            ORDER BY executed_at DESC LIMIT :lim
        """), {"uid": user_id, "lim": limit}).fetchall()
        for r in rows:
            config = r[3] if isinstance(r[3], dict) else (json.loads(r[3]) if r[3] else {})
            can_undo = bool(r[6]) and not r[8] and (r[7] is None or r[7] > now)
            items.append({
                "id": r[0], "action_type": r[1], "source": r[2],
                "description": config.get("description") or config.get("entity_id") or r[1],
                "confidence": config.get("confidence"),
                "success": r[4], "at": r[5].isoformat() if r[5] else None,
                "can_undo": can_undo, "undone": bool(r[8]),
                "undone_at": r[9].isoformat() if r[9] else None,
            })
    except Exception as e:
        logger.warning(f"[system/actions] query failed: {e}")
    return {"items": items, "count": len(items)}


class UndoActionIn(BaseModel):
    ledger_id: int


@router.post("/actions/undo")
async def undo_action_endpoint(
    payload: UndoActionIn,
    db: Session = Depends(get_db),
):
    """God-view one-tap undo — same underlying undo_action as the chat tool."""
    from app.services.standing_order_service import standing_order_service
    result = await standing_order_service.undo_action(db, payload.ledger_id)
    return result


@router.get("/overview")
async def get_overview(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Single bundled fetch for the dashboard."""
    world = await get_world(user_id, db)
    balance = await get_balance(168, user_id, db)
    stream = await get_stream(25, user_id, db)
    promotions = await get_promotions(20, user_id, db)
    actions = await get_actions(20, user_id, db)
    return {"world": world, "balance": balance, "stream": stream, "promotions": promotions, "actions": actions}
