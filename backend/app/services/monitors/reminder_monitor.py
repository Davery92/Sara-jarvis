"""
Reminder Monitor

Detects overdue reminders (non-fitness) and creates actionable inbox items.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
import logging

from sqlalchemy.orm import Session

from app.models.jarvis_inbox import InboxKind
from app.models.reminder import Reminder
from app.services.jarvis_inbox_service import inbox_service

logger = logging.getLogger(__name__)


class ReminderMonitor:
    """Monitor overdue reminders and surface them in the inbox."""

    def __init__(self):
        self.enabled = True
        self.lookback_hours = 24
        self.max_items = 10

    async def run_checks(self, db: Session, user_id: str) -> Dict[str, Any]:
        if not self.enabled:
            return {"status": "disabled", "issues_found": 0}

        now = datetime.now(timezone.utc)
        lookback_start = now - timedelta(hours=self.lookback_hours)

        reminders = db.query(Reminder).filter(
            Reminder.user_id == user_id,
            Reminder.is_completed == False,
            Reminder.reminder_time <= now,
            Reminder.reminder_time >= lookback_start,
        ).order_by(Reminder.reminder_time.asc()).limit(self.max_items).all()

        if not reminders:
            return {"status": "completed", "issues_found": 0, "issues": []}

        issues: List[Dict[str, Any]] = []
        for reminder in reminders:
            due_at = self._to_utc(reminder.reminder_time)
            overdue_minutes = max(0, int((now - due_at).total_seconds() // 60))
            severity = "high" if overdue_minutes >= 60 else "medium"
            issues.append({
                "type": "overdue_reminder",
                "severity": severity,
                "reminder_id": reminder.id,
                "title": reminder.title,
                "description": reminder.description,
                "due_at": due_at.isoformat(),
                "overdue_minutes": overdue_minutes,
            })

        await self._create_reminder_inbox_item(db, user_id, issues, now)
        logger.info(f"Reminder monitor found {len(issues)} overdue reminders for user {user_id}")

        return {
            "status": "completed",
            "issues_found": len(issues),
            "issues": issues,
            "checks_run": ["overdue_reminders"],
        }

    async def _create_reminder_inbox_item(
        self,
        db: Session,
        user_id: str,
        issues: List[Dict[str, Any]],
        now: datetime,
    ) -> None:
        high_count = sum(1 for i in issues if i.get("severity") == "high")
        priority = 8 if high_count else 6

        title = f"Reminders: {len(issues)} overdue"
        body_lines = ["These reminders are overdue:"]
        for issue in issues[:5]:
            body_lines.append(
                f"- {issue['title']} ({issue['overdue_minutes']} min overdue)"
            )
        if len(issues) > 5:
            body_lines.append(f"... and {len(issues) - 5} more")

        inbox_service.create_inbox_item(
            db=db,
            user_id=user_id,
            kind=InboxKind.REMINDER,
            title=title,
            body="\n".join(body_lines),
            source="reminder_monitor",
            payload={"issues": issues, "high_severity": high_count},
            priority=priority,
            dedupe_key=f"reminder_overdue_{now.strftime('%Y%m%d_%H')}",
        )

    @staticmethod
    def _to_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)


reminder_monitor = ReminderMonitor()
