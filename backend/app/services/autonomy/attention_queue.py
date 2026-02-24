"""
Attention Queue Service (Phase 2 — Cortana Evolution).

Persistent proactive inbox for non-urgent items. When the policy engine
defers an action, or when a notification is low-priority, it goes here
instead of being pushed immediately.

Dedup: partial unique index on (user_id, dedupe_key) WHERE status IN ('new','sent').
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text

logger = logging.getLogger(__name__)


async def _exec(db, stmt, params=None):
    """Execute SQL with either a sync or async session."""
    result = db.execute(stmt, params) if params else db.execute(stmt)
    if hasattr(result, '__await__'):
        result = await result
    return result


class AttentionQueueService:
    """CRUD + delivery logic for the attention queue."""

    async def create_item(
        self,
        db,
        user_id: str,
        title: str,
        body: Optional[str] = None,
        category: str = "general",
        priority: str = "normal",
        source: str = "unified_agent",
        dedupe_key: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Create an attention item with dedup.

        Returns item ID on success, or existing item ID on dedup conflict.
        """
        try:
            result = await _exec(db, text("""
                INSERT INTO autonomy_attention_item
                (user_id, title, body, category, priority, source, dedupe_key, payload)
                VALUES (:user_id, :title, :body, :category, :priority, :source,
                        :dedupe_key, CAST(:payload AS jsonb))
                ON CONFLICT (user_id, dedupe_key)
                    WHERE dedupe_key IS NOT NULL AND status IN ('new', 'sent')
                DO NOTHING
                RETURNING id::text
            """), {
                "user_id": user_id,
                "title": title,
                "body": body,
                "category": category,
                "priority": priority,
                "source": source,
                "dedupe_key": dedupe_key,
                "payload": json.dumps(payload or {}, default=str),
            })
            row = result.fetchone()
            if row:
                return row[0]

            # Dedup conflict — find existing item
            if dedupe_key:
                existing = await _exec(db, text("""
                    SELECT id::text FROM autonomy_attention_item
                    WHERE user_id = :user_id AND dedupe_key = :dedupe_key
                      AND status IN ('new', 'sent')
                    LIMIT 1
                """), {"user_id": user_id, "dedupe_key": dedupe_key})
                existing_row = existing.fetchone()
                return existing_row[0] if existing_row else None
            return None
        except Exception as e:
            logger.error(f"Failed to create attention item: {e}")
            return None

    async def list_items(
        self,
        db,
        user_id: str,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List attention items, newest first."""
        conditions = ["user_id = :user_id"]
        params: Dict[str, Any] = {"user_id": user_id, "limit": limit, "offset": offset}

        if status:
            conditions.append("status = :status")
            params["status"] = status
        else:
            conditions.append("status NOT IN ('archived', 'dropped')")

        where = " AND ".join(conditions)

        try:
            result = await _exec(db, text(f"""
                SELECT id::text, title, body, category, priority, source, status,
                       dedupe_key, payload, created_at, updated_at, read_at, archived_at
                FROM autonomy_attention_item
                WHERE {where}
                ORDER BY
                    CASE priority
                        WHEN 'critical' THEN 0
                        WHEN 'urgent' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'normal' THEN 3
                        WHEN 'low' THEN 4
                    END,
                    created_at DESC
                LIMIT :limit OFFSET :offset
            """), params)
            return [
                {
                    "id": r[0], "title": r[1], "body": r[2], "category": r[3],
                    "priority": r[4], "source": r[5], "status": r[6],
                    "dedupe_key": r[7], "payload": r[8],
                    "created_at": r[9].isoformat() if r[9] else None,
                    "updated_at": r[10].isoformat() if r[10] else None,
                    "read_at": r[11].isoformat() if r[11] else None,
                    "archived_at": r[12].isoformat() if r[12] else None,
                }
                for r in result.fetchall()
            ]
        except Exception as e:
            logger.error(f"Failed to list attention items: {e}")
            return []

    async def count_by_status(
        self,
        db,
        user_id: str,
    ) -> Dict[str, int]:
        """Count items by status."""
        try:
            result = await _exec(db, text("""
                SELECT status, COUNT(*) as count
                FROM autonomy_attention_item
                WHERE user_id = :user_id
                GROUP BY status
            """), {"user_id": user_id})
            return {r[0]: r[1] for r in result.fetchall()}
        except Exception as e:
            logger.error(f"Failed to count attention items: {e}")
            return {}

    async def mark_read(self, db, item_id: str, user_id: Optional[str] = None) -> bool:
        """Mark an item as read. Scoped by user_id when provided."""
        try:
            conditions = ["id = :id", "status IN ('new', 'sent')"]
            params: Dict[str, Any] = {"id": item_id}
            if user_id:
                conditions.append("user_id = :user_id")
                params["user_id"] = user_id
            where = " AND ".join(conditions)
            await _exec(db, text(f"""
                UPDATE autonomy_attention_item
                SET status = 'read', read_at = NOW(), updated_at = NOW()
                WHERE {where}
            """), params)
            # Propagate read feedback to linked notification_log entries
            await self._propagate_feedback(db, item_id, action="read")
            return True
        except Exception as e:
            logger.error(f"Failed to mark attention item read: {e}")
            return False

    async def mark_archived(self, db, item_id: str, user_id: Optional[str] = None) -> bool:
        """Archive an item. Scoped by user_id when provided."""
        try:
            conditions = ["id = :id", "status NOT IN ('archived', 'dropped')"]
            params: Dict[str, Any] = {"id": item_id}
            if user_id:
                conditions.append("user_id = :user_id")
                params["user_id"] = user_id
            where = " AND ".join(conditions)
            await _exec(db, text(f"""
                UPDATE autonomy_attention_item
                SET status = 'archived', archived_at = NOW(), updated_at = NOW()
                WHERE {where}
            """), params)
            # Propagate dismissed feedback to linked notification_log entries
            await self._propagate_feedback(db, item_id, action="dismissed")
            return True
        except Exception as e:
            logger.error(f"Failed to archive attention item: {e}")
            return False

    async def _propagate_feedback(self, db, item_id: str, action: str) -> None:
        """Propagate attention item feedback to linked notification_log entries."""
        try:
            if action == "read":
                await _exec(db, text("""
                    UPDATE notification_log
                    SET read_at = COALESCE(read_at, NOW())
                    WHERE attention_item_id = CAST(:item_id AS uuid)
                      AND read_at IS NULL
                """), {"item_id": item_id})
            elif action == "engaged":
                await _exec(db, text("""
                    UPDATE notification_log
                    SET read_at = COALESCE(read_at, NOW()),
                        engaged = TRUE
                    WHERE attention_item_id = CAST(:item_id AS uuid)
                """), {"item_id": item_id})
            elif action == "dismissed":
                await _exec(db, text("""
                    UPDATE notification_log
                    SET dismissed_at = COALESCE(dismissed_at, NOW())
                    WHERE attention_item_id = CAST(:item_id AS uuid)
                      AND dismissed_at IS NULL
                      AND engaged = FALSE
                """), {"item_id": item_id})
        except Exception as e:
            logger.debug(f"Failed to propagate feedback to notification_log: {e}")

    async def archive_all(self, db, user_id: str) -> int:
        """Archive all active items for a user."""
        try:
            result = await _exec(db, text("""
                UPDATE autonomy_attention_item
                SET status = 'archived', archived_at = NOW(), updated_at = NOW()
                WHERE user_id = :user_id AND status NOT IN ('archived', 'dropped')
            """), {"user_id": user_id})
            return result.rowcount
        except Exception as e:
            logger.error(f"Failed to archive all attention items: {e}")
            return 0

    async def flush_urgent(
        self,
        db,
        user_id: str,
    ) -> List[Dict[str, Any]]:
        """Get urgent/high priority items that should trigger push notifications."""
        try:
            result = await _exec(db, text("""
                SELECT id::text, title, body, category, priority, source, payload
                FROM autonomy_attention_item
                WHERE user_id = :user_id
                  AND status = 'new'
                  AND priority IN ('urgent', 'high', 'critical')
                ORDER BY created_at
            """), {"user_id": user_id})
            items = []
            for r in result.fetchall():
                items.append({
                    "id": r[0], "title": r[1], "body": r[2],
                    "category": r[3], "priority": r[4], "source": r[5],
                    "payload": r[6],
                })
            # Mark as sent
            if items:
                ids = [i["id"] for i in items]
                await _exec(db, text("""
                    UPDATE autonomy_attention_item
                    SET status = 'sent', updated_at = NOW()
                    WHERE id = ANY(CAST(:ids AS uuid[]))
                """), {"ids": ids})
            return items
        except Exception as e:
            logger.error(f"Failed to flush urgent items: {e}")
            return []


# Module-level singleton
attention_queue = AttentionQueueService()
