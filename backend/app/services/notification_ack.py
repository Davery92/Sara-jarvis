"""Notification acknowledgment in chat — close the loop between channels (Phase 12K).

David comes home to N missed notifications and wants to answer several in ONE chat
message. Chat previously had no idea those notifications existed. This injects the
unacknowledged notifications into chat context and provides the ack tool so a single
reply ("yes to the first two, skip the gym thing") resolves each one, clears the
badge on every surface, and stops any follow-up thread from re-nagging.

notification_log already carries read_at / engaged / response_text / attention_item_id.
The unified badge (compute_badge) counts notifications with read_at IS NULL that aren't
covered by an active attention item, so setting read_at + archiving the linked attention
item clears it on web and iOS alike.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Union

from sqlalchemy import text

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


async def get_unacked_notifications(user_id: str, hours: int = 24, limit: int = 8) -> List[dict]:
    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    async with factory() as db:
        rows = (await db.execute(text("""
            SELECT id, title, message, category, sent_at, topic, attention_item_id
            FROM notification_log
            WHERE user_id = :uid AND sent = TRUE
              AND read_at IS NULL AND dismissed_at IS NULL
              AND sent_at >= NOW() - (:hrs * INTERVAL '1 hour')
            ORDER BY sent_at DESC
            LIMIT :lim
        """), {"uid": user_id, "hrs": hours, "lim": limit})).mappings().all()
    return [dict(r) for r in rows]


async def get_unacked_for_context(user_id: str = DEFAULT_USER_ID) -> Optional[str]:
    """Chat-context block of sent-but-unacknowledged notifications, so Sara can
    understand a reply that references them and recap on a return. None if empty."""
    items = await get_unacked_notifications(user_id)
    if not items:
        return None
    lines = [
        "## Sent but unacknowledged (last 24h)",
        "David may reply to any of these. If it's been a while since you last talked and there "
        "are 2+ here, open with a one-line-each recap, then call acknowledge_notifications with "
        "his answers. A blanket 'saw your messages / all good' acks them all (read, not engaged).",
    ]
    for n in items:
        when = n["sent_at"].strftime("%a %H:%M") if n.get("sent_at") else ""
        msg = (n.get("message") or "")[:120]
        lines.append(f"- [#{n['id']}] ({n.get('category', '?')}, {when}) {n.get('title', '')}: {msg}")
    return "\n".join(lines)


async def acknowledge(user_id: str, ids: Union[List[int], str],
                      responses: Optional[Dict[str, str]] = None) -> dict:
    """Acknowledge notifications. ids = list of ids or "all". responses maps
    id(str)->David's response note (engaged=true only where a note is given)."""
    from app.db.session import get_async_session_factory
    responses = {str(k): v for k, v in (responses or {}).items()}
    factory = get_async_session_factory()
    acked, engaged_count = [], 0
    async with factory() as db:
        if isinstance(ids, str) and ids.strip().lower() == "all":
            rows = (await db.execute(text("""
                SELECT id FROM notification_log
                WHERE user_id = :uid AND sent = TRUE AND read_at IS NULL AND dismissed_at IS NULL
                  AND sent_at >= NOW() - INTERVAL '24 hours'
            """), {"uid": user_id})).all()
            target_ids = [r[0] for r in rows]
        else:
            target_ids = [int(i) for i in ids]

        for nid in target_ids:
            resp = responses.get(str(nid))
            engaged = bool(resp)
            row = (await db.execute(text("""
                UPDATE notification_log
                SET read_at = NOW(), engaged = :eng,
                    response_text = COALESCE(:resp, response_text)
                WHERE id = :id AND user_id = :uid
                RETURNING attention_item_id, topic
            """), {"id": nid, "uid": user_id, "eng": engaged, "resp": resp})).first()
            if not row:
                continue
            acked.append(nid)
            if engaged:
                engaged_count += 1
            attn_id, topic = row[0], row[1]
            # Clear the linked attention item so web Needs-You + iOS badge drop.
            if attn_id:
                await db.execute(text("""
                    UPDATE autonomy_attention_item
                    SET status = 'archived', archived_at = NOW(), updated_at = NOW()
                    WHERE id = :aid AND status IN ('new', 'sent', 'read')
                """), {"aid": attn_id})
            # Route into the follow-up thread so anti-harping state updates.
            if topic and topic.startswith("followup:"):
                await _resolve_followup_thread(db, user_id, topic, engaged, resp)
        await db.commit()

    # Badge after (sync compute).
    badge = None
    try:
        from app.db.base import SessionLocal
        from app.routes.assistant_inbox import compute_badge
        with SessionLocal() as sdb:
            badge = compute_badge(sdb, user_id)
    except Exception:
        pass
    return {"acknowledged": acked, "count": len(acked), "engaged": engaged_count, "badge": badge}


async def _resolve_followup_thread(db, user_id: str, topic: str, engaged: bool, resp: Optional[str]):
    """Resolve the follow-up thread behind a 'followup:<id-prefix>' notification so
    a responded thread stops nagging."""
    try:
        from app.services.thread_manager import resolve_thread, record_david_response
        prefix = topic.split(":", 1)[1]
        row = (await db.execute(text(
            "SELECT id FROM followup_thread WHERE user_id = :uid AND status = 'open' AND id::text LIKE :p LIMIT 1"),
            {"uid": user_id, "p": prefix + "%"})).first()
        if not row:
            return
        tid = row[0]
        if engaged:
            await resolve_thread(tid, db, david_response="positive")
        else:
            # Cleared without a substantive reply — mark read/neutral so it doesn't re-nag.
            await record_david_response(tid, "neutral", db)
    except Exception as e:
        logger.debug(f"followup thread resolve skipped: {e}")
