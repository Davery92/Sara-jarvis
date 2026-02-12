"""
Push Notification Service
Sends push notifications via Expo Push for iOS/Android devices.
"""
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from enum import Enum
import httpx

logger = logging.getLogger(__name__)

# David's user ID for push token lookup
DAVID_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


class NotificationPriority(Enum):
    LOW = "default"
    NORMAL = "default"
    HIGH = "high"
    URGENT = "high"


class NotificationService:
    """Service for sending push notifications via Expo"""

    def __init__(self):
        self.enabled = True
        logger.info("📱 NotificationService initialized (Expo Push)")

    async def _get_push_tokens(self, user_id: str) -> List[str]:
        """Get active push tokens for a user from the database"""
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker
        from app.core.config import settings

        engine = create_engine(settings.database_url)
        Session = sessionmaker(bind=engine)
        db = Session()

        try:
            result = db.execute(text("""
                SELECT token FROM push_token
                WHERE user_id = :user_id AND is_active = true
            """), {"user_id": user_id}).fetchall()

            return [row.token for row in result]
        finally:
            db.close()

    async def _send_expo_push(
        self,
        tokens: List[str],
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        priority: str = "default"
    ) -> bool:
        """Send push notification via Expo Push API"""
        if not tokens:
            logger.warning("No push tokens provided")
            return False

        messages = []
        for token in tokens:
            messages.append({
                "to": token,
                "sound": "default",
                "title": title,
                "body": body,
                "data": data or {},
                "priority": priority,
            })

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://exp.host/--/api/v2/push/send",
                    json=messages,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    }
                )
                if response.status_code == 200:
                    logger.info(f"📱 Expo push sent: {title}")
                    return True
                else:
                    logger.error(f"Expo push failed: {response.status_code} - {response.text}")
                    return False
        except Exception as e:
            logger.error(f"Expo push error: {e}")
            return False

    async def send_notification(
        self,
        user_id: str,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        data: Optional[Dict[str, Any]] = None,
        **kwargs  # Accept but ignore legacy NTFY params
    ) -> bool:
        """Send a notification via Expo Push"""
        if not self.enabled:
            logger.debug("Notifications disabled, skipping")
            return True

        tokens = await self._get_push_tokens(user_id)
        if not tokens:
            logger.info(f"📱 No push tokens for user {user_id}")
            return False

        notification_data = data or {}
        notification_data["title"] = title
        notification_data["message"] = message

        return await self._send_expo_push(
            tokens=tokens,
            title=title,
            body=message,
            data=notification_data,
            priority=priority.value
        )

    # ==========================================
    # Main notification interface
    # ==========================================

    async def notify_david(
        self,
        title: str,
        body: str,
        priority: str = "normal",
        category: str = "general",
        url: Optional[str] = None
    ) -> bool:
        """
        Send a notification to David via Expo Push.

        Args:
            title: Notification title
            body: Notification body text
            priority: "low", "normal", "high", or "urgent"
            category: Category for grouping/routing
            url: Optional URL to include

        Returns:
            True if notification was sent successfully
        """
        priority_map = {
            "low": NotificationPriority.LOW,
            "normal": NotificationPriority.NORMAL,
            "high": NotificationPriority.HIGH,
            "urgent": NotificationPriority.URGENT
        }

        notification_data = {
            "type": category,
            "priority": priority,
            "title": title,
            "message": body,
        }
        if url:
            notification_data["url"] = url

        return await self.send_notification(
            user_id=DAVID_USER_ID,
            title=title,
            message=body,
            priority=priority_map.get(priority, NotificationPriority.NORMAL),
            data=notification_data
        )

    async def send_timer_alert(self, user_id: str, timer_label: str, is_overdue: bool = False) -> bool:
        """Send timer completion/overdue alert"""
        if is_overdue:
            title = f"Timer Overdue: {timer_label}"
            message = f"Your timer '{timer_label}' is overdue!"
            priority = NotificationPriority.HIGH
        else:
            title = f"Timer Complete: {timer_label}"
            message = f"Your timer '{timer_label}' has finished!"
            priority = NotificationPriority.NORMAL

        return await self.send_notification(
            user_id=user_id,
            title=title,
            message=message,
            priority=priority,
            data={"type": "timer_complete", "timer_name": timer_label, "is_overdue": is_overdue}
        )

    async def send_reminder_alert(self, user_id: str, reminder_text: str, due_in_minutes: int = 0) -> bool:
        """Send reminder alert"""
        if due_in_minutes <= 0:
            title = "Reminder Due Now"
            message = reminder_text
            priority = NotificationPriority.HIGH
        elif due_in_minutes <= 15:
            title = f"Reminder in {due_in_minutes}m"
            message = reminder_text
            priority = NotificationPriority.NORMAL
        else:
            title = "Upcoming Reminder"
            message = f"In {due_in_minutes} minutes: {reminder_text}"
            priority = NotificationPriority.LOW

        return await self.send_notification(
            user_id=user_id,
            title=title,
            message=message,
            priority=priority,
            data={"type": "reminder", "due_in_minutes": due_in_minutes}
        )

    async def send_wellness_alert(self, user_id: str, wellness_type: str, message: str) -> bool:
        """Send wellness/mood-based alert"""
        wellness_config = {
            "tired": {"title": "Wellness Check - Rest", "priority": NotificationPriority.LOW},
            "stressed": {"title": "Wellness Check - Stress", "priority": NotificationPriority.NORMAL},
            "focused": {"title": "Focus Session", "priority": NotificationPriority.LOW},
            "break": {"title": "Break Suggestion", "priority": NotificationPriority.LOW},
        }

        config = wellness_config.get(wellness_type, {
            "title": "Wellness Check",
            "priority": NotificationPriority.LOW
        })

        return await self.send_notification(
            user_id=user_id,
            title=config["title"],
            message=message,
            priority=config["priority"],
            data={"type": "wellness", "wellness_type": wellness_type}
        )

    async def send_contextual_alert(self, user_id: str, context_type: str, message: str, priority: str = "normal") -> bool:
        """Send general contextual awareness alert"""
        priority_map = {
            "low": NotificationPriority.LOW,
            "normal": NotificationPriority.NORMAL,
            "high": NotificationPriority.HIGH,
            "urgent": NotificationPriority.URGENT
        }

        return await self.send_notification(
            user_id=user_id,
            title=f"Sara: {context_type.title()}",
            message=message,
            priority=priority_map.get(priority, NotificationPriority.NORMAL),
            data={"type": "context", "context_type": context_type}
        )

    # ==========================================
    # Reflection System Notifications
    # ==========================================

    async def notify_new_proposal(self, proposal) -> bool:
        """Notify David of a new prompt proposal requiring review."""
        if hasattr(proposal, 'proposal_id'):
            proposal_id = proposal.proposal_id
            target = proposal.target_agent
            section = proposal.target_prompt_section
            reasoning = proposal.reasoning[:200] if proposal.reasoning else "No reasoning provided"
        else:
            proposal_id = proposal.get('proposal_id', 'unknown')
            target = proposal.get('target_agent', 'unknown')
            section = proposal.get('target_prompt_section', 'unknown')
            reasoning = proposal.get('reasoning', 'No reasoning provided')[:200]

        return await self.notify_david(
            title=f"Sara Proposal #{proposal_id}",
            body=f"Target: {target}/{section}\n\n{reasoning}...",
            priority="normal",
            category="proposal",
            url=f"https://sara.avery.cloud/reflection/proposals/{proposal_id}"
        )

    async def notify_uncertainty(self, uncertainty: Dict[str, Any]) -> bool:
        """Notify David of a flagged uncertainty requiring clarification."""
        question = uncertainty.get('question_for_david', 'Clarification needed')
        context = uncertainty.get('context', '')[:150]

        return await self.notify_david(
            title="Sara Needs Input",
            body=f"{question}\n\nContext: {context}...",
            priority="high",
            category="uncertainty"
        )

    async def notify_karma_alert(
        self,
        agent_id: str,
        dimension: str,
        score: float,
        level: str
    ) -> bool:
        """Notify David of a karma score alert."""
        priority = "urgent" if level == "critical" else "high"

        return await self.notify_david(
            title=f"Karma Alert: {agent_id}",
            body=f"The '{dimension}' dimension is {level} ({score:.1f}/100)",
            priority=priority,
            category="karma"
        )

    async def notify_proactive_action(
        self,
        action_type: str,
        title_text: str,
        body_text: str,
        priority_score: float = 0.5
    ) -> bool:
        """Notify David of a proactive action Sara is considering/taking."""
        if priority_score >= 0.8:
            priority = "high"
        elif priority_score >= 0.6:
            priority = "normal"
        else:
            priority = "low"

        return await self.notify_david(
            title=f"Sara: {title_text}",
            body=f"[{action_type}] {body_text}",
            priority=priority,
            category="proactive"
        )

    def configure(self, enabled: bool = None, **kwargs):
        """Configure the notification service"""
        if enabled is not None:
            self.enabled = enabled
        logger.info(f"Notification service configured: enabled={self.enabled}")


# Global service instance
notification_service = NotificationService()


def get_notification_service() -> NotificationService:
    """Get the global NotificationService instance."""
    return notification_service
