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
        (SELECT COUNT(*) FROM outbox_item a
          WHERE a.user_id = :user_id AND a.status IN ('new', 'sent'))
      + (SELECT COUNT(*) FROM background_task t
          WHERE t.user_id = :user_id AND t.status = 'needs_clarification')
      + (SELECT COUNT(*) FROM notification_log n
          WHERE n.user_id = :user_id AND n.sent = TRUE
            AND n.read_at IS NULL AND n.dismissed_at IS NULL
            AND n.sent_at >= NOW() - INTERVAL '7 days'
            AND (n.outbox_item_id IS NULL OR NOT EXISTS (
                SELECT 1 FROM outbox_item a2
                WHERE a2.id = n.outbox_item_id
                  AND a2.status IN ('new', 'sent', 'read')
            )))
"""


def compute_badge(db: Session, user_id: str) -> int:
    """Single source of truth for the inbox badge number."""
    try:
        row = db.execute(text(BADGE_SQL), {"user_id": user_id}).fetchone()
        from app.services.outbox_usage import record_read
        record_read("compute_badge")
        return int(row[0]) if row else 0
    except Exception as e:
        logger.error(f"Badge computation failed: {e}")
        return 0


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def build_unified_inbox(
    db: Session, user_id: str, fyi_days: int = 7, limit: int = 50
) -> Dict[str, Any]:
    """Server-side merge of everything Sara surfaces, as a plain dict.

    Extracted from the route so /chat/stream can inject the exact same inbox
    the badge counts (P3 punch-list fix) — the button is a deterministic
    "load these items" gesture, not a question Sara has to answer from a
    partial context slice.
    """
    needs_you: List[Dict[str, Any]] = []
    fyi: List[Dict[str, Any]] = []

    # ── Needs you: active attention items ────────────────────────────────
    attention_rows = db.execute(text(f"""
        SELECT id::text, title, body, category, priority, source, status,
               payload, created_at, read_at
        FROM outbox_item
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
               outbox_item_id::text AS attention_item_id
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

    from app.services.outbox_usage import record_read
    record_read("build_unified_inbox")

    return {
        "needs_you": needs_you,
        "fyi": fyi,
        "counts": {
            "needs_you": len(needs_you),
            "fyi_unread": sum(1 for i in fyi if i["unread"]),
            "badge": compute_badge(db, user_id),
        },
    }


def _age(iso: Optional[str]) -> str:
    """Compact human age from an ISO timestamp, ET-aware, no naive math."""
    if not iso:
        return ""
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        secs = (datetime.now(timezone.utc) - dt).total_seconds()
        if secs < 3600:
            return f"{int(secs // 60)}m ago"
        if secs < 86400:
            return f"{int(secs // 3600)}h ago"
        return f"{int(secs // 86400)}d ago"
    except Exception:
        return ""


# Map each inbox kind to the ref-tag Sara should cite and the action she has.
_KIND_TAG = {
    "attention": "attention",
    "task_clarification": "clarification task",
    "notification": "notification",
    "capture": "capture",
    "task": "task",
}


def format_inbox_for_chat(data: Dict[str, Any], max_lines: int = 15) -> str:
    """Compact numbered digest of the unified inbox for deterministic chat injection.

    Needs-You first, then unread FYI. Each line carries kind + ref id so Sara can
    act on the right item (ack notifications, engage attention items, answer
    clarifications). Already-read FYI rows are skipped.
    """
    needs = data.get("needs_you") or []
    fyi = [i for i in (data.get("fyi") or []) if i.get("unread")]
    if not needs and not fyi:
        return ""

    def _tag(item: Dict[str, Any]) -> str:
        kind = item.get("kind", "")
        label = _KIND_TAG.get(kind, kind)
        return f"[{label} #{item.get('ref_id')}]"

    lines: List[str] = []
    n = 0
    for item in needs:
        if n >= max_lines:
            break
        n += 1
        body = (item.get("body") or "").strip().replace("\n", " ")
        if len(body) > 140:
            body = body[:137] + "…"
        age = _age(item.get("created_at"))
        head = f"{n}. {_tag(item)} {item.get('title') or '(untitled)'}"
        if age:
            head += f" — {age}"
        lines.append(head + (f"\n   {body}" if body else ""))

    fyi_started = False
    for item in fyi:
        if n >= max_lines:
            break
        n += 1
        if not fyi_started:
            fyi_started = True
        body = (item.get("body") or "").strip().replace("\n", " ")
        if len(body) > 140:
            body = body[:137] + "…"
        age = _age(item.get("created_at"))
        head = f"{n}. {_tag(item)} {item.get('title') or '(untitled)'}"
        if age:
            head += f" — {age}"
        lines.append(head + (f"\n   {body}" if body else ""))

    total = len(needs) + len(fyi)
    extra = total - n
    header = (
        "## David's inbox — he pressed the inbox button; these are the exact items waiting\n"
        "Walk him through EVERY item below (do not summarize or drop any), Needs-You before FYI.\n"
        "When he tells you what to do with them, call the `clear_inbox_items` tool ONCE with one "
        "entry per item he addressed — this is what actually drops the badge. Each entry needs the "
        "item's `kind` and `id` exactly as tagged below, a `disposition` ('engaged' = he acted "
        "on/answered it, 'dismissed' = not relevant), and `response` (what he said; REQUIRED to "
        "answer a `clarification`, which resumes the blocked task). Ref tags → kind: "
        "`[notification #N]`→notification, `[attention <id>]`→attention, "
        "`[clarification task <id>]`→clarification, `[capture <id>]`→capture.\n"
        "Do NOT claim anything is cleared unless the clear_inbox_items call succeeded this turn, "
        "and only clear items he actually addressed — leave the rest.\n"
    )
    body_txt = "\n".join(lines)
    if extra > 0:
        body_txt += f"\n(+{extra} more not shown)"
    return header + "\n" + body_txt


@router.get("/unified")
async def get_unified_inbox(
    fyi_days: int = Query(7, ge=1, le=30),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return build_unified_inbox(db, str(current_user.id), fyi_days=fyi_days, limit=limit)


@router.get("/badge")
async def get_inbox_badge(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Lightweight badge count for the tab bar."""
    return {"badge": compute_badge(db, str(current_user.id))}
