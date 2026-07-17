"""
Notification tools — let Sara answer "what's the notification?" in chat.

The app icon badge is the unread count from notification_log; these tools
read the same table so chat answers always match what the badge/Notifications
screen show. Also covers "what did you send me today", "anything I missed?".
"""

import logging
from typing import Dict, Any

from sqlalchemy import text

from app.tools.base import BaseTool, ToolResult
from app.core.timezone import to_local, format_datetime

logger = logging.getLogger(__name__)


class GetRecentNotificationsTool(BaseTool):
    """Read recent / unread notifications from notification_log"""

    @property
    def name(self) -> str:
        return "get_recent_notifications"

    @property
    def description(self) -> str:
        return """Look up the notifications Sara has sent the user — what's unread,
    what the app icon badge number refers to, and recent notification history.
    Use this when the user asks things like "what's the notification?",
    "why is there a badge on the app?", "what did you send me?",
    "did I miss anything?", or wants their notifications summarized or explained."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "unread_only": {
                    "type": "boolean",
                    "description": "Only return unread notifications (what the badge counts). Default true — set false for full recent history.",
                    "default": True
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum notifications to return (default: 10)",
                    "default": 10
                },
                "mark_read": {
                    "type": "boolean",
                    "description": "Mark the returned notifications as read (clears them from the badge count). Use when the user has clearly seen them now.",
                    "default": False
                }
            },
            "required": []
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        unread_only = kwargs.get("unread_only", True)
        limit = max(1, min(int(kwargs.get("limit", 10) or 10), 50))
        mark_read = kwargs.get("mark_read", False)

        try:
            from app.db.session import SessionLocal

            db = SessionLocal()
            try:
                unread_filter = "AND read_at IS NULL AND dismissed_at IS NULL" if unread_only else ""
                rows = db.execute(text(f"""
                    SELECT id, title, message, category, COALESCE(priority, 'normal') AS priority,
                           source, sent_at, read_at
                    FROM notification_log
                    WHERE user_id = :user_id AND sent = TRUE {unread_filter}
                    ORDER BY sent_at DESC
                    LIMIT :limit
                """), {"user_id": str(user_id), "limit": limit}).fetchall()

                unread_count = db.execute(text("""
                    SELECT COUNT(*) FROM notification_log
                    WHERE user_id = :user_id AND sent = TRUE
                      AND read_at IS NULL AND dismissed_at IS NULL
                """), {"user_id": str(user_id)}).scalar() or 0

                notifications = []
                for r in rows:
                    notifications.append({
                        "id": r.id,
                        "title": r.title,
                        "message": r.message,
                        "category": r.category,
                        "priority": r.priority,
                        "source": r.source,
                        "sent_at": format_datetime(to_local(r.sent_at)) if r.sent_at else None,
                        "read": r.read_at is not None,
                    })

                if mark_read and notifications:
                    db.execute(text("""
                        UPDATE notification_log
                        SET read_at = COALESCE(read_at, NOW())
                        WHERE user_id = :user_id AND id = ANY(:ids)
                    """), {"user_id": str(user_id), "ids": [n["id"] for n in notifications]})
                    db.commit()
                    unread_count = max(0, unread_count - sum(1 for n in notifications if not n["read"]))

                if not notifications:
                    msg = (
                        "No unread notifications — the badge should be clear."
                        if unread_only else "No notifications found."
                    )
                    return ToolResult(success=True, message=msg, data={"notifications": [], "unread_count": unread_count})

                return ToolResult(
                    success=True,
                    message=f"{len(notifications)} notification(s) ({unread_count} unread total — that's the app badge number)",
                    data={"notifications": notifications, "unread_count": unread_count},
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"get_recent_notifications failed: {e}", exc_info=True)
            return ToolResult(success=False, message=f"Couldn't read notifications: {e}")


NOTIFICATION_TOOLS = [GetRecentNotificationsTool()]
