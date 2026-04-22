"""
Attention Queue Service (Phase 2 — Cortana Evolution).

Persistent proactive inbox for non-urgent items. When the policy engine
defers an action, or when a notification is low-priority, it goes here
instead of being pushed immediately.

Dedup: partial unique index on (user_id, dedupe_key) WHERE status IN ('new','sent').
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

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

    async def _resolve_note_context(
        self,
        db,
        *,
        user_id: str,
        title: str,
        payload: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, str]]:
        note_id = str((payload or {}).get("note_id") or "").strip()
        note_row = None

        if note_id:
            note_row = await _exec(db, text("""
                SELECT id::text, title, content
                FROM note
                WHERE id = :note_id AND user_id = :user_id
                LIMIT 1
            """), {"note_id": note_id, "user_id": user_id})
            note_row = note_row.fetchone()

        if not note_row and title.startswith("Sara's Daily Report"):
            note_row = await _exec(db, text("""
                SELECT id::text, title, content
                FROM note
                WHERE user_id = :user_id AND title = :title
                ORDER BY created_at DESC
                LIMIT 1
            """), {"user_id": user_id, "title": title})
            note_row = note_row.fetchone()

        if not note_row:
            return None

        preview = (note_row[2] or "").strip()
        if len(preview) > 1800:
            preview = preview[:1800].rstrip() + "…"

        return {
            "note_id": note_row[0],
            "title": note_row[1] or title,
            "preview": preview,
        }

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

        On successful insert, also broadcasts a real-time SHOW_NOTIFICATION
        command to any connected desktop devices so the user is notified
        without polling the webapp. Best-effort — failures are swallowed.
        """
        new_item_id: Optional[str] = None
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
                new_item_id = row[0]
            elif dedupe_key:
                # Dedup conflict — find existing item
                existing = await _exec(db, text("""
                    SELECT id::text FROM autonomy_attention_item
                    WHERE user_id = :user_id AND dedupe_key = :dedupe_key
                      AND status IN ('new', 'sent')
                    LIMIT 1
                """), {"user_id": user_id, "dedupe_key": dedupe_key})
                existing_row = existing.fetchone()
                return existing_row[0] if existing_row else None
            else:
                return None
        except Exception as e:
            logger.error(f"Failed to create attention item: {e}")
            return None

        # Best-effort live broadcast to connected desktop devices
        if new_item_id:
            try:
                await self._broadcast_new_item(
                    user_id=user_id,
                    item_id=new_item_id,
                    title=title,
                    body=body or "",
                    category=category,
                    priority=priority,
                    source=source,
                )
            except Exception as e:
                logger.debug(f"Desktop broadcast for attention item {new_item_id} skipped: {e}")
        return new_item_id

    async def _broadcast_new_item(
        self,
        user_id: str,
        item_id: str,
        title: str,
        body: str,
        category: str,
        priority: str,
        source: str,
    ) -> None:
        """Push a SHOW_NOTIFICATION command to any connected user devices."""
        from app.services.command_router import command_router

        device_ids = command_router.get_connected_devices(user_id)
        if not device_ids:
            return

        message = {
            "type": "command",
            "command": "show_notification",
            "payload": {
                "title": title,
                "message": body,
                "priority": priority,
                "category": category,
                "source": source,
                "attention_item_id": item_id,
            },
            "source_device": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        sent = await command_router.broadcast_to_user(user_id, message)
        if sent:
            logger.info(
                f"Attention item {item_id} broadcast to {sent} desktop device(s) "
                f"(category={category}, priority={priority})"
            )

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
            conditions.append("status NOT IN ('archived', 'dropped', 'completed')")

        where = " AND ".join(conditions)

        try:
            result = await _exec(db, text(f"""
                SELECT id::text, title, body, category, priority, source, status,
                       dedupe_key, payload, created_at, updated_at, read_at, archived_at,
                       completed_at
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
                    "completed_at": r[13].isoformat() if r[13] else None,
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

    async def get_item(self, db, item_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch a single attention item."""
        try:
            conditions = ["id = CAST(:id AS uuid)"]
            params: Dict[str, Any] = {"id": item_id}
            if user_id:
                conditions.append("user_id = :user_id")
                params["user_id"] = user_id

            where = " AND ".join(conditions)
            result = await _exec(db, text(f"""
                SELECT id::text, user_id, title, body, category, priority, source, status,
                       dedupe_key, payload, created_at, updated_at, read_at, archived_at,
                       completed_at
                FROM autonomy_attention_item
                WHERE {where}
                LIMIT 1
            """), params)
            row = result.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "user_id": row[1],
                "title": row[2],
                "body": row[3],
                "category": row[4],
                "priority": row[5],
                "source": row[6],
                "status": row[7],
                "dedupe_key": row[8],
                "payload": row[9] or {},
                "created_at": row[10].isoformat() if row[10] else None,
                "updated_at": row[11].isoformat() if row[11] else None,
                "read_at": row[12].isoformat() if row[12] else None,
                "archived_at": row[13].isoformat() if row[13] else None,
                "completed_at": row[14].isoformat() if row[14] else None,
            }
        except Exception as e:
            logger.error(f"Failed to fetch attention item {item_id}: {e}")
            return None

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

    async def mark_engaged(self, db, item_id: str, user_id: Optional[str] = None) -> bool:
        """Mark an item as engaged (read + interacted)."""
        try:
            conditions = ["id = :id", "status NOT IN ('archived', 'dropped')"]
            params: Dict[str, Any] = {"id": item_id}
            if user_id:
                conditions.append("user_id = :user_id")
                params["user_id"] = user_id
            where = " AND ".join(conditions)
            await _exec(db, text(f"""
                UPDATE autonomy_attention_item
                SET status = CASE WHEN status IN ('new', 'sent') THEN 'read' ELSE status END,
                    read_at = COALESCE(read_at, NOW()),
                    updated_at = NOW()
                WHERE {where}
            """), params)
            await self._propagate_feedback(db, item_id, action="engaged")
            return True
        except Exception as e:
            logger.error(f"Failed to mark attention item engaged: {e}")
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

    async def run_action(
        self,
        db,
        item_id: str,
        action_id: str,
        user_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a payload-defined action for an attention item."""
        item = await self.get_item(db=db, item_id=item_id, user_id=user_id)
        if not item:
            return {"success": False, "error": "not_found"}

        payload = item.get("payload") or {}
        actions = payload.get("actions") if isinstance(payload, dict) else None
        if not isinstance(actions, list) or not actions:
            return {"success": False, "error": "no_actions"}

        action = next(
            (a for a in actions if str(a.get("id", "")).strip() == action_id),
            None,
        )
        if not isinstance(action, dict):
            return {"success": False, "error": "action_not_found"}

        kind = str(action.get("kind", "")).strip().lower()
        params = params or {}

        if kind == "archive":
            success = await self.mark_archived(db=db, item_id=item_id, user_id=user_id)
            await self._log_action(db, item_id, action_id, kind, "Archived")
            return {"success": success, "action_id": action_id, "kind": kind}

        if kind in ("mark_read", "read"):
            success = await self.mark_read(db=db, item_id=item_id, user_id=user_id)
            await self._log_action(db, item_id, action_id, "mark_read", "Marked read")
            return {"success": success, "action_id": action_id, "kind": "mark_read"}

        if kind == "snooze":
            minutes_raw = action.get("minutes", 10)
            try:
                minutes = int(minutes_raw)
            except (TypeError, ValueError):
                minutes = 10
            minutes = max(1, min(minutes, 24 * 60))

            due_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
            reminder_title = str(
                action.get("reminder_title")
                or f"Follow up: {item.get('title') or 'attention item'}"
            )[:255]
            reminder_description = str(
                action.get("description")
                or item.get("body")
                or ""
            )

            from app.models.reminder import Reminder

            reminder = Reminder(
                user_id=item["user_id"],
                title=reminder_title,
                description=reminder_description,
                reminder_time=due_at,
                is_completed=False,
            )
            db.add(reminder)
            if hasattr(db, "flush"):
                flush_result = db.flush()
                if hasattr(flush_result, "__await__"):
                    await flush_result

            await self.mark_engaged(db=db, item_id=item_id, user_id=user_id)
            await self._log_action(db, item_id, action_id, kind, f"Snoozed {minutes}m")
            return {
                "success": True,
                "action_id": action_id,
                "kind": kind,
                "reminder": {
                    "id": reminder.id,
                    "title": reminder.title,
                    "reminder_time": due_at.isoformat(),
                    "minutes": minutes,
                },
            }

        if kind == "add_reminder":
            # User-specified time from params, or fallback to action-defined default
            reminder_time_str = params.get("reminder_time")
            if reminder_time_str:
                try:
                    due_at = datetime.fromisoformat(reminder_time_str.replace("Z", "+00:00"))
                    if due_at.tzinfo is None:
                        due_at = due_at.replace(tzinfo=timezone.utc)
                except (ValueError, AttributeError):
                    due_at = datetime.now(timezone.utc) + timedelta(minutes=60)
            else:
                default_minutes = int(action.get("default_minutes", 60))
                due_at = datetime.now(timezone.utc) + timedelta(minutes=default_minutes)

            reminder_title = str(
                params.get("title")
                or action.get("reminder_title")
                or f"Follow up: {item.get('title') or 'attention item'}"
            )[:255]

            from app.models.reminder import Reminder

            reminder = Reminder(
                user_id=item["user_id"],
                title=reminder_title,
                description=item.get("body") or "",
                reminder_time=due_at,
                is_completed=False,
            )
            db.add(reminder)
            if hasattr(db, "flush"):
                flush_result = db.flush()
                if hasattr(flush_result, "__await__"):
                    await flush_result

            await self.mark_engaged(db=db, item_id=item_id, user_id=user_id)
            await self._log_action(db, item_id, action_id, kind, f"Reminder set for {due_at.isoformat()}")
            return {
                "success": True,
                "action_id": action_id,
                "kind": kind,
                "reminder": {
                    "id": reminder.id,
                    "title": reminder.title,
                    "reminder_time": due_at.isoformat(),
                },
            }

        if kind == "add_calendar":
            start_time_str = params.get("start_time")
            if not start_time_str:
                return {"success": False, "error": "start_time_required"}
            try:
                start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                return {"success": False, "error": "invalid_start_time"}

            end_time_str = params.get("end_time")
            if end_time_str:
                try:
                    end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    end_time = start_time + timedelta(hours=1)
            else:
                end_time = start_time + timedelta(hours=1)

            event_title = str(
                params.get("title")
                or item.get("title")
                or "Calendar event"
            )[:255]

            from app.models.calendar_event import CalendarEvent
            import uuid as uuid_mod

            event = CalendarEvent(
                id=str(uuid_mod.uuid4()),
                user_id=item["user_id"],
                title=event_title,
                description=item.get("body") or "",
                start_time=start_time,
                end_time=end_time,
                source="attention_inbox",
            )
            db.add(event)
            if hasattr(db, "flush"):
                flush_result = db.flush()
                if hasattr(flush_result, "__await__"):
                    await flush_result

            await self.mark_engaged(db=db, item_id=item_id, user_id=user_id)
            await self._log_action(db, item_id, action_id, kind, f"Calendar event at {start_time.isoformat()}")
            return {
                "success": True,
                "action_id": action_id,
                "kind": kind,
                "calendar_event": {
                    "id": event.id,
                    "title": event.title,
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                },
            }

        if kind == "complete":
            success = await self.mark_completed(db=db, item_id=item_id, user_id=user_id)
            await self._log_action(db, item_id, action_id, kind, "Completed")
            return {"success": success, "action_id": action_id, "kind": kind, "status": "completed"}

        if kind == "open_url":
            url = str(action.get("url") or params.get("url") or "")
            await self.mark_engaged(db=db, item_id=item_id, user_id=user_id)
            await self._log_action(db, item_id, action_id, kind, f"Opened URL")
            return {
                "success": True,
                "action_id": action_id,
                "kind": kind,
                "directive": {
                    "type": "open_url",
                    "url": url,
                },
            }

        if kind == "navigate":
            await self.mark_engaged(db=db, item_id=item_id, user_id=user_id)
            await self._log_action(db, item_id, action_id, kind, f"Navigate to {action.get('target')}")
            return {
                "success": True,
                "action_id": action_id,
                "kind": kind,
                "directive": {
                    "type": "navigate",
                    "target": str(action.get("target") or "inbox"),
                },
            }

        if kind == "chat":
            await self.mark_engaged(db=db, item_id=item_id, user_id=user_id)
            prompt = str(action.get("prompt") or f"Help me with: {item.get('title', 'this')}")
            note_context = await self._resolve_note_context(
                db,
                user_id=user_id,
                title=str(item.get("title") or ""),
                payload=payload if isinstance(payload, dict) else None,
            )
            await self._log_action(db, item_id, action_id, kind, "Started chat")
            directive: Dict[str, Any] = {
                "type": "chat",
                "prompt": prompt,
                "title": str(item.get("title") or ""),
            }
            if note_context:
                directive["note_id"] = note_context["note_id"]
                directive["note_title"] = note_context["title"]
                directive["note_preview"] = note_context["preview"]
            return {
                "success": True,
                "action_id": action_id,
                "kind": kind,
                "directive": directive,
            }

        if kind == "hitl_reply":
            # Opens the inline reply UI or a contextual chat — frontend handles this
            await self.mark_engaged(db=db, item_id=item_id, user_id=user_id)
            await self._log_action(db, item_id, action_id, kind, "Opening reply")
            request_payload = payload if isinstance(payload, dict) else {}
            return {
                "success": True,
                "action_id": action_id,
                "kind": kind,
                "directive": {
                    "type": "hitl_reply",
                    "item_id": item_id,
                    "question": request_payload.get("question", ""),
                    "context": request_payload.get("context", ""),
                    "request_id": request_payload.get("request_id", ""),
                },
            }

        if kind == "acs_skip":
            # User chose to skip — push a skip message to Redis and complete the item
            request_id = payload.get("request_id", "") if isinstance(payload, dict) else ""
            if request_id:
                import os
                import redis.asyncio as aioredis
                redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
                try:
                    r = await aioredis.from_url(redis_url, decode_responses=True)
                    response_key = f"sara:acs:hitl_response:{request_id}"
                    await r.lpush(response_key, json.dumps({
                        "message": "[David chose to skip this request]",
                        "skipped": True,
                    }))
                    await r.expire(response_key, 3600)
                    if hasattr(r, "aclose"):
                        await r.aclose()
                    else:
                        await r.close()
                except Exception as e:
                    logger.warning(f"acs_skip: failed to push skip to Redis: {e}")

            await self.mark_completed(db=db, item_id=item_id, user_id=user_id)
            await self._log_action(db, item_id, action_id, kind, "Skipped by David")
            return {
                "success": True,
                "action_id": action_id,
                "kind": kind,
                "status": "completed",
            }

        return {"success": False, "error": "unsupported_action_kind", "kind": kind}

    async def mark_completed(self, db, item_id: str, user_id: Optional[str] = None) -> bool:
        """Mark an item as completed."""
        try:
            conditions = ["id = CAST(:id AS uuid)", "status NOT IN ('archived', 'dropped', 'completed')"]
            params: Dict[str, Any] = {"id": item_id}
            if user_id:
                conditions.append("user_id = :user_id")
                params["user_id"] = user_id
            where = " AND ".join(conditions)
            await _exec(db, text(f"""
                UPDATE autonomy_attention_item
                SET status = 'completed', completed_at = NOW(), updated_at = NOW()
                WHERE {where}
            """), params)
            await self._propagate_feedback(db, item_id, action="engaged")
            return True
        except Exception as e:
            logger.error(f"Failed to mark attention item completed: {e}")
            return False

    async def _log_action(self, db, item_id: str, action_id: str, kind: str, summary: str) -> None:
        """Append an entry to the item's action_history JSONB array."""
        try:
            entry = json.dumps({
                "action_id": action_id,
                "kind": kind,
                "summary": summary,
                "at": datetime.now(timezone.utc).isoformat(),
            })
            await _exec(db, text("""
                UPDATE autonomy_attention_item
                SET action_history = COALESCE(action_history, '[]'::jsonb) || :entry::jsonb,
                    updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
            """), {"id": item_id, "entry": entry})
        except Exception as e:
            logger.debug(f"Failed to log action on attention item {item_id}: {e}")

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
                WHERE user_id = :user_id AND status NOT IN ('archived', 'dropped', 'completed')
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
