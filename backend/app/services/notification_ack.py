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
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = get_owner_id()


# A six-hour window, not 24. The block is replayed verbatim into every chat turn,
# so a stale item is not a reminder — it is Sara raising a settled matter again
# unprompted. On 2026-09-01 a push about a meeting that had already happened rode
# in the unacknowledged block on every turn from 17:02 to 20:08, with its time
# rendered in UTC, because phone reads never set read_at.
UNACKED_WINDOW_HOURS = 6


async def get_unacked_notifications(user_id: str, hours: int = UNACKED_WINDOW_HOURS,
                                    limit: int = 8) -> List[dict]:
    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    async with factory() as db:
        rows = (await db.execute(text("""
            SELECT n.id, n.title, n.message, n.category, n.sent_at, n.topic,
                   n.outbox_item_id AS attention_item_id
            FROM notification_log n
            WHERE n.user_id = :uid AND n.sent = TRUE
              AND n.read_at IS NULL AND n.dismissed_at IS NULL
              AND n.sent_at >= NOW() - (:hrs * INTERVAL '1 hour')
              -- Nothing whose subject is already settled. A notification about a
              -- resolved thread is not unfinished business, it is noise.
              AND NOT EXISTS (
                    SELECT 1 FROM world_thread t
                     WHERE t.user_id = n.user_id
                       AND t.status IN ('resolved','cancelled','expired')
                       AND n.topic IS NOT NULL
                       AND n.topic = 'entity:' || t.id
              )
            ORDER BY n.sent_at DESC
            LIMIT :lim
        """), {"uid": user_id, "hrs": hours, "lim": limit})).mappings().all()
    return [dict(r) for r in rows]


async def get_unacked_for_context(user_id: str = DEFAULT_USER_ID) -> Optional[str]:
    """Chat-context block of sent-but-unacknowledged notifications, so Sara can
    understand a reply that references them and recap on a return. None if empty.

    Titles only. The full body was being replayed on every turn — 120 characters
    of a stale message is 120 characters of Sara re-raising it.
    """
    items = await get_unacked_notifications(user_id)
    if not items:
        return None
    from app.core.timezone import render_when

    lines = [
        f"## Sent but unacknowledged (last {UNACKED_WINDOW_HOURS}h)",
        "David may reply to any of these. If it's been a while since you last talked and there "
        "are 2+ here, open with a one-line-each recap, then call acknowledge_notifications with "
        "his answers. A blanket 'saw your messages / all good' acks them all (read, not engaged).",
    ]
    for n in items:
        when = render_when(n.get("sent_at"), source_convention="utc")
        lines.append(f"- [#{n['id']}] ({n.get('category', '?')}, {when}) {n.get('title', '')}")
    return "\n".join(lines)


async def acknowledge(user_id: str, ids: Union[List[int], str],
                      responses: Optional[Dict[str, str]] = None) -> dict:
    """Acknowledge notifications. ids = list of ids or "all". responses maps
    id(str)->David's response note (engaged=true only where a note is given)."""
    from app.db.session import get_async_session_factory
    responses = {str(k): v for k, v in (responses or {}).items()}
    factory = get_async_session_factory()
    acked, engaged_count = [], 0
    acked_topics: List[str] = []
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
                RETURNING outbox_item_id, topic
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
                    UPDATE outbox_item
                    SET status = 'archived', archived_at = NOW(), updated_at = NOW()
                    WHERE id = :aid AND status IN ('new', 'sent', 'read')
                """), {"aid": attn_id})
            # Route into the follow-up thread so anti-harping state updates.
            if topic and topic.startswith("followup:"):
                await _resolve_followup_thread(db, user_id, topic, engaged, resp)
            if topic:
                acked_topics.append(topic)
        await db.commit()

    # Invariant 3: acknowledging a push closes the thing it was about. Before
    # this, David could clear every notification about a thread and the thread
    # itself stayed open, so the next deliberation cycle simply sent it again.
    for topic in acked_topics:
        try:
            from app.services.thread_resolution import resolve_threads_for_topic
            await resolve_threads_for_topic(user_id, topic)
        except Exception as e:
            logger.debug(f"topic thread resolve skipped for {topic}: {e}")

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


async def resolve_inbox_items(user_id: str, items: List[dict]) -> dict:
    """Clear ANY inbox kind from one chat reply (P3 follow-up fix).

    The badge counts unread attention items + task clarifications + unread
    notifications; the digest lists all of them. acknowledge() only touched
    notifications, so a reply addressing attention items left the badge up and
    David had to clear them by hand. This routes each item to its real
    resolution path by kind:

      - notification  → same read/engaged/linked-attention/followup path as acknowledge()
      - attention     → mark_engaged (he acted on it) or mark_archived (dismissed)
      - clarification → resume the background task with his answer (or dismiss)
      - capture       → mark the shared_content row read

    `items` is a list of {kind, id, disposition?, response?}. disposition is
    "engaged"/"done"/"answered" (acted on) vs "dismissed"/"skip" (not relevant);
    default is engaged. Returns per-kind counts + the recomputed badge.
    """
    from app.db.session import get_async_session_factory
    from app.services.autonomy.attention_queue import attention_queue

    counts = {"notification": 0, "attention": 0, "clarification": 0, "capture": 0, "failed": 0}
    # Batch notifications through the existing acknowledge() path (handles
    # linked attention items + followup threads).
    notif_ids: List[int] = []
    notif_resp: Dict[str, str] = {}
    others: List[dict] = []
    for it in items or []:
        kind = (it.get("kind") or "").strip().lower()
        rid = it.get("id")
        if kind in ("notification", "notif"):
            try:
                nid = int(rid)
                notif_ids.append(nid)
                if it.get("response"):
                    notif_resp[str(nid)] = str(it["response"])
            except (TypeError, ValueError):
                counts["failed"] += 1
        else:
            others.append(it)

    if notif_ids:
        r = await acknowledge(user_id, notif_ids, notif_resp or None)
        counts["notification"] = r.get("count", 0)

    factory = get_async_session_factory()
    async with factory() as db:
        for it in others:
            kind = (it.get("kind") or "").strip().lower()
            rid = str(it.get("id") or "").strip()
            disp = (it.get("disposition") or "engaged").strip().lower()
            resp = it.get("response")
            dismissed = disp in ("dismissed", "skip", "skipped", "ignore", "not_relevant")
            if not rid:
                counts["failed"] += 1
                continue
            try:
                if kind == "attention":
                    ok = (await attention_queue.mark_archived(db, rid, user_id)
                          if dismissed else
                          await attention_queue.mark_engaged(db, rid, user_id))
                    counts["attention"] += 1 if ok else 0
                    if not ok:
                        counts["failed"] += 1
                elif kind in ("clarification", "task_clarification", "task"):
                    if dismissed or not resp:
                        # No answer to give (or explicitly skipped) → cancel the
                        # blocked task so it stops counting, rather than leaving
                        # it stuck forever.
                        await db.execute(text("""
                            UPDATE background_task SET status = 'cancelled', updated_at = NOW()
                            WHERE id = CAST(:id AS uuid) AND user_id = :uid
                              AND status = 'needs_clarification'
                        """), {"id": rid, "uid": user_id})
                        counts["clarification"] += 1
                    else:
                        # resume_task uses a sync Session and runs the agent
                        # resumption inline (same as the agent_dispatch tool).
                        from app.db.base import SessionLocal
                        from app.services.agent_dispatch import agent_dispatch_service
                        sdb = SessionLocal()
                        try:
                            await agent_dispatch_service.resume_task(
                                db=sdb, task_id=rid, user_id=user_id, instruction=str(resp))
                        finally:
                            sdb.close()
                        counts["clarification"] += 1
                elif kind == "capture":
                    await db.execute(text("""
                        UPDATE shared_content SET status = 'read'
                        WHERE id = CAST(:id AS uuid) AND user_id = :uid AND status = 'unread'
                    """), {"id": rid, "uid": user_id})
                    counts["capture"] += 1
                else:
                    counts["failed"] += 1
            except Exception as e:
                logger.warning(f"resolve_inbox_items: {kind} {rid} failed: {e}")
                counts["failed"] += 1
        await db.commit()

    # Recompute the badge after all mutations.
    badge = None
    try:
        from app.db.base import SessionLocal
        from app.routes.assistant_inbox import compute_badge
        with SessionLocal() as sdb:
            badge = compute_badge(sdb, user_id)
    except Exception:
        pass
    total = counts["notification"] + counts["attention"] + counts["clarification"] + counts["capture"]
    return {"counts": counts, "cleared": total, "badge": badge}


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
