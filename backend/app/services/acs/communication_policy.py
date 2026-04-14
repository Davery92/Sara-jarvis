"""Communication gating for ACS outbound items."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy import text


_WHITESPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^a-z0-9\s]")

HIGH_SIGNAL_REASONS = {"blocked", "artifact_complete", "needs_attention"}


def _normalize(text_value: str) -> str:
    text_value = (text_value or "").lower()
    text_value = _NON_WORD_RE.sub(" ", text_value)
    return _WHITESPACE_RE.sub(" ", text_value).strip()


def _build_dedupe_key(title: str, content: str, category: str) -> str:
    normalized = " | ".join((
        _normalize(category),
        _normalize(title),
        " ".join(_normalize(content).split()[:48]),
    ))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


async def _insert_item(
    db,
    *,
    user_id: str,
    session_id: Optional[str],
    title: str,
    content: str,
    category: str,
    priority: float,
    dedupe_key: str,
    delivery_status: str,
    shared_reason: str,
    suppression_reason: Optional[str] = None,
    merged_into_id: Optional[str] = None,
):
    item_id = str(uuid.uuid4())
    auto_hidden = delivery_status in ("suppressed", "merged")
    await db.execute(text("""
        INSERT INTO acs_show_david_buffer (
            id, user_id, session_id, title, content, category, priority,
            dedupe_key, delivery_status, suppression_reason, merged_into_id,
            shared_reason, shown, shown_at, created_at
        )
        VALUES (
            :id, :uid, :sid, :title, :content, :category, :priority,
            :dedupe_key, :delivery_status, :suppression_reason, :merged_into_id,
            :shared_reason, :shown, :shown_at,
            NOW()
        )
    """), {
        "id": item_id,
        "uid": user_id,
        "sid": session_id,
        "title": title[:500],
        "content": content[:8000],
        "category": category[:100],
        "priority": priority,
        "dedupe_key": dedupe_key,
        "delivery_status": delivery_status,
        "suppression_reason": suppression_reason,
        "merged_into_id": merged_into_id,
        "shared_reason": shared_reason[:100],
        "shown": auto_hidden,
        "shown_at": datetime.now(timezone.utc) if auto_hidden else None,
    })
    return item_id


async def queue_show_david(
    db,
    *,
    user_id: str,
    session_id: Optional[str],
    title: str,
    content: str,
    category: str = "insight",
    priority: float = 0.5,
    shared_reason: str = "interesting_discovery",
) -> dict:
    """Queue a show-David item while suppressing low-value repeats."""
    title = (title or "").strip()
    content = (content or "").strip()
    category = (category or "insight").strip()
    shared_reason = (shared_reason or "interesting_discovery").strip()

    if not title or not content:
        item_id = await _insert_item(
            db,
            user_id=user_id,
            session_id=session_id,
            title=title or "Untitled",
            content=content or "(empty)",
            category=category,
            priority=priority,
            dedupe_key="",
            delivery_status="suppressed",
            shared_reason=shared_reason,
            suppression_reason="empty_payload",
        )
        return {"id": item_id, "status": "suppressed", "reason": "empty_payload"}

    dedupe_key = _build_dedupe_key(title, content, category)
    normalized_payload = f"{_normalize(title)} {_normalize(content)}".strip()

    recent = await db.execute(text("""
        SELECT id, title, content, category, delivery_status
        FROM acs_show_david_buffer
        WHERE user_id = :uid
          AND created_at > NOW() - INTERVAL '72 hours'
          AND delivery_status IN ('queued', 'delivered')
        ORDER BY created_at DESC
        LIMIT 20
    """), {"uid": user_id})

    for row in recent.fetchall():
        existing_id, existing_title, existing_content, existing_category, existing_status = row
        existing_key = _build_dedupe_key(existing_title or "", existing_content or "", existing_category or "")
        existing_payload = f"{_normalize(existing_title or '')} {_normalize(existing_content or '')}".strip()

        if existing_key == dedupe_key:
            if len(content) > len(existing_content or ""):
                await db.execute(text("""
                    UPDATE acs_show_david_buffer
                    SET title = :title,
                        content = :content,
                        priority = GREATEST(priority, :priority)
                    WHERE id = :id
                """), {"title": title[:500], "content": content[:8000], "priority": priority, "id": existing_id})
            item_id = await _insert_item(
                db,
                user_id=user_id,
                session_id=session_id,
                title=title,
                content=content,
                category=category,
                priority=priority,
                dedupe_key=dedupe_key,
                delivery_status="merged",
                shared_reason=shared_reason,
                suppression_reason="duplicate_recent_share",
                merged_into_id=existing_id,
            )
            return {"id": item_id, "status": "merged", "reason": "duplicate_recent_share", "merged_into_id": existing_id}

        if existing_status == "queued" and _similarity(existing_payload, normalized_payload) >= 0.92:
            item_id = await _insert_item(
                db,
                user_id=user_id,
                session_id=session_id,
                title=title,
                content=content,
                category=category,
                priority=priority,
                dedupe_key=dedupe_key,
                delivery_status="suppressed",
                shared_reason=shared_reason,
                suppression_reason="similar_recent_share",
                merged_into_id=existing_id,
            )
            return {"id": item_id, "status": "suppressed", "reason": "similar_recent_share", "merged_into_id": existing_id}

    if session_id and shared_reason not in HIGH_SIGNAL_REASONS:
        count_result = await db.execute(text("""
            SELECT COUNT(*)
            FROM acs_show_david_buffer
            WHERE session_id = :sid
              AND delivery_status = 'queued'
        """), {"sid": session_id})
        session_count = count_result.scalar() or 0
        if session_count >= 1:
            item_id = await _insert_item(
                db,
                user_id=user_id,
                session_id=session_id,
                title=title,
                content=content,
                category=category,
                priority=priority,
                dedupe_key=dedupe_key,
                delivery_status="suppressed",
                shared_reason=shared_reason,
                suppression_reason="session_share_cap",
            )
            return {"id": item_id, "status": "suppressed", "reason": "session_share_cap"}

    item_id = await _insert_item(
        db,
        user_id=user_id,
        session_id=session_id,
        title=title,
        content=content,
        category=category,
        priority=priority,
        dedupe_key=dedupe_key,
        delivery_status="queued",
        shared_reason=shared_reason,
    )
    return {"id": item_id, "status": "queued", "reason": "queued"}


async def get_session_delivery_stats(db, session_id: str) -> tuple[int, int]:
    result = await db.execute(text("""
        SELECT delivery_status, COUNT(*)
        FROM acs_show_david_buffer
        WHERE session_id = :sid
        GROUP BY delivery_status
    """), {"sid": session_id})
    delivered_like = 0
    suppressed_like = 0
    for status, count in result.fetchall():
        if status in ("queued", "delivered"):
            delivered_like += count
        elif status in ("suppressed", "merged"):
            suppressed_like += count
    return delivered_like, suppressed_like


async def mark_session_items_delivered(db, session_id: str):
    await db.execute(text("""
        UPDATE acs_show_david_buffer
        SET delivery_status = 'delivered',
            shown = TRUE,
            shown_at = NOW()
        WHERE session_id = :sid
          AND delivery_status = 'queued'
    """), {"sid": session_id})
