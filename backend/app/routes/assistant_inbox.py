"""
Unified assistant inbox — one server-side merge of everything Sara surfaces.

Replaces the iOS client stitching together six feeds (attention queue,
background tasks, missions, notifications, captures, ACS snapshot) with
inconsistent windows and duplicate items. Two pivots:

- needs_you: things blocked on David — active attention items (including
  HITL questions) and task clarifications.
- fyi: informational stream — notifications, running/recent tasks, unread
  captures. Notifications linked to an active attention item are dropped
  (the attention card is the actionable copy).

The badge formula lives here (compute_badge) and is shared with
/api/notifications/unread-count and the push badge so every number the user
sees means the same thing: unread attention + clarifications + unread
unlinked notifications.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assistant-inbox", tags=["Assistant Inbox"])

ACTIVE_ATTENTION = "('new', 'sent', 'read')"

# One number, one meaning: unread attention + task clarifications + unread
# notifications not represented by an active attention item. Notifications
# only count within the FYI window (7 days) — there is a years-deep backlog
# of never-marked-read rows that would otherwise pin the badge in the
# hundreds forever.
BADGE_SQL = """
    SELECT
        (SELECT COUNT(*) FROM autonomy_attention_item a
          WHERE a.user_id = :user_id AND a.status IN ('new', 'sent'))
      + (SELECT COUNT(*) FROM background_task t
          WHERE t.user_id = :user_id AND t.status = 'needs_clarification')
      + (SELECT COUNT(*) FROM notification_log n
          WHERE n.user_id = :user_id AND n.sent = TRUE
            AND n.read_at IS NULL AND n.dismissed_at IS NULL
            AND n.sent_at >= NOW() - INTERVAL '7 days'
            AND (n.attention_item_id IS NULL OR NOT EXISTS (
                SELECT 1 FROM autonomy_attention_item a2
                WHERE a2.id = n.attention_item_id
                  AND a2.status IN ('new', 'sent', 'read')
            )))
"""


def compute_badge(db: Session, user_id: str) -> int:
    """Single source of truth for the inbox badge number."""
    try:
        row = db.execute(text(BADGE_SQL), {"user_id": user_id}).fetchone()
        return int(row[0]) if row else 0
    except Exception as e:
        logger.error(f"Badge computation failed: {e}")
        return 0


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


@router.get("/unified")
async def get_unified_inbox(
    fyi_days: int = Query(7, ge=1, le=30),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user_id = str(current_user.id)
    needs_you: List[Dict[str, Any]] = []
    fyi: List[Dict[str, Any]] = []

    # ── Needs you: active attention items ────────────────────────────────
    attention_rows = db.execute(text(f"""
        SELECT id::text, title, body, category, priority, source, status,
               payload, created_at, read_at
        FROM autonomy_attention_item
        WHERE user_id = :user_id AND status IN {ACTIVE_ATTENTION}
        ORDER BY
            CASE priority
                WHEN 'critical' THEN 0 WHEN 'urgent' THEN 1 WHEN 'high' THEN 2
                WHEN 'normal' THEN 3 ELSE 4
            END,
            created_at DESC
        LIMIT :limit
    """), {"user_id": user_id, "limit": limit}).fetchall()

    active_attention_ids = set()
    for r in attention_rows:
        active_attention_ids.add(r.id)
        payload = r.payload or {}
        is_hitl = payload.get("type") == "human_input_request"
        actions = [{"id": "reply", "label": "Reply"}] if is_hitl else [
            {"id": a.get("id"), "label": a.get("label") or a.get("id")}
            for a in (payload.get("actions") or [])
            if isinstance(a, dict) and a.get("id")
        ]
        needs_you.append({
            "id": f"attention:{r.id}",
            "kind": "attention",
            "ref_id": r.id,
            "title": r.title,
            "body": r.body,
            "priority": r.priority or "normal",
            "source": r.source or "Sara",
            "status": r.status,
            "unread": r.status in ("new", "sent"),
            "created_at": _iso(r.created_at),
            "is_hitl": is_hitl,
            "actions": actions,
            "payload": {"note_id": payload.get("note_id")} if payload.get("note_id") else {},
        })

    # ── Needs you: task clarifications ────────────────────────────────────
    clarification_rows = db.execute(text("""
        SELECT id::text, original_query, clarification_question, created_at
        FROM background_task
        WHERE user_id = :user_id AND status = 'needs_clarification'
        ORDER BY created_at DESC
        LIMIT 20
    """), {"user_id": user_id}).fetchall()
    for r in clarification_rows:
        needs_you.append({
            "id": f"task:{r.id}",
            "kind": "task_clarification",
            "ref_id": r.id,
            "title": r.original_query,
            "body": r.clarification_question or "Sara needs more input before continuing.",
            "priority": "high",
            "source": "Background task",
            "status": "needs_clarification",
            "unread": True,
            "created_at": _iso(r.created_at),
            "is_hitl": False,
            "actions": [{"id": "answer_in_chat", "label": "Answer in chat"}],
            "payload": {},
        })

    # ── FYI: notifications (deduped against active attention) ────────────
    notification_rows = db.execute(text("""
        SELECT CAST(id AS VARCHAR) AS id, title, message, category,
               COALESCE(priority, 'normal') AS priority, source, topic,
               sent_at, read_at, dismissed_at, engaged,
               attention_item_id::text AS attention_item_id
        FROM notification_log
        WHERE user_id = :user_id AND sent = TRUE
          AND sent_at >= NOW() - MAKE_INTERVAL(days => :days)
        ORDER BY sent_at DESC
        LIMIT :limit
    """), {"user_id": user_id, "days": fyi_days, "limit": limit}).fetchall()
    for r in notification_rows:
        if r.attention_item_id and r.attention_item_id in active_attention_ids:
            continue  # actionable copy already in needs_you
        fyi.append({
            "id": f"notification:{r.id}",
            "kind": "notification",
            "ref_id": r.id,
            "title": r.title,
            "body": r.message,
            "priority": r.priority,
            "source": r.source or r.category or "Notification",
            "status": "read" if (r.read_at or r.engaged or r.dismissed_at) else "unread",
            "unread": not (r.read_at or r.engaged or r.dismissed_at),
            "created_at": _iso(r.sent_at),
            "is_hitl": False,
            "actions": [],
            "payload": {"category": r.category, "topic": r.topic},
        })

    # ── FYI: running tasks + recently finished ────────────────────────────
    task_rows = db.execute(text("""
        SELECT id::text, original_query, status, error_message, result_note_id,
               created_at, completed_at
        FROM background_task
        WHERE user_id = :user_id
          AND (
            status IN ('pending', 'running')
            OR (status IN ('completed', 'failed')
                AND COALESCE(completed_at, created_at) >= NOW() - INTERVAL '48 hours')
          )
        ORDER BY COALESCE(completed_at, created_at) DESC
        LIMIT 20
    """), {"user_id": user_id}).fetchall()
    for r in task_rows:
        running = r.status in ("pending", "running")
        fyi.append({
            "id": f"task:{r.id}",
            "kind": "task",
            "ref_id": r.id,
            "title": r.original_query,
            "body": r.error_message if r.status == "failed" else None,
            "priority": "normal",
            "source": "Background task",
            "status": "running" if running else r.status,
            "unread": False,
            "created_at": _iso(r.completed_at or r.created_at),
            "is_hitl": False,
            "actions": (
                [{"id": "open_note", "label": "Open result"}] if r.result_note_id else []
            ),
            "payload": {"note_id": r.result_note_id} if r.result_note_id else {},
        })

    # ── FYI: unread captures ──────────────────────────────────────────────
    capture_rows = db.execute(text("""
        SELECT id::text, title, description, original_url, status, shared_at
        FROM shared_content
        WHERE user_id = :user_id
          AND status = 'unread'
          AND shared_at >= NOW() - MAKE_INTERVAL(days => :days)
        ORDER BY shared_at DESC
        LIMIT 20
    """), {"user_id": user_id, "days": fyi_days}).fetchall()
    for r in capture_rows:
        fyi.append({
            "id": f"capture:{r.id}",
            "kind": "capture",
            "ref_id": r.id,
            "title": r.title or "Captured item",
            "body": r.description or r.original_url,
            "priority": "low",
            "source": "Capture",
            "status": r.status,
            "unread": True,
            "created_at": _iso(r.shared_at),
            "is_hitl": False,
            "actions": [],
            "payload": {"url": r.original_url},
        })

    fyi.sort(key=lambda i: i["created_at"] or "", reverse=True)
    fyi = fyi[:limit]

    return {
        "needs_you": needs_you,
        "fyi": fyi,
        "counts": {
            "needs_you": len(needs_you),
            "fyi_unread": sum(1 for i in fyi if i["unread"]),
            "badge": compute_badge(db, user_id),
        },
    }


@router.get("/badge")
async def get_inbox_badge(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Lightweight badge count for the tab bar."""
    return {"badge": compute_badge(db, str(current_user.id))}
