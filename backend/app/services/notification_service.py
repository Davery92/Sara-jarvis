"""
NTFY Notification Service
Sends proactive notifications via NTFY for timers, reminders, and contextual awareness alerts.
"""
import asyncio
import logging
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
from enum import Enum
import urllib.request
import urllib.parse

logger = logging.getLogger(__name__)

class NotificationPriority(Enum):
    LOW = "1"
    NORMAL = "3"  # Default
    HIGH = "4"
    URGENT = "5"

class NotificationService:
    """Service for sending NTFY notifications"""
    
    def __init__(self):
        # Configuration - these should be environment variables in production
        self.ntfy_base_url = "https://ntfy.sh"  # Public NTFY server
        self.default_topic = "sara"  # Default topic
        self.enabled = True  # Can be disabled via config
        
        logger.info("📱 NotificationService initialized")
    
    async def send_notification(
        self,
        user_id: str,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        tags: Optional[List[str]] = None,
        actions: Optional[List[Dict]] = None,
        topic: Optional[str] = None
    ) -> bool:
        """Send a notification via NTFY"""
        
        if not self.enabled:
            logger.debug("Notifications disabled, skipping")
            return True
        
        try:
            # Use user-specific topic or default
            notification_topic = topic or f"{self.default_topic}-{user_id[:8]}"
            url = f"{self.ntfy_base_url}/{notification_topic}"
            
            # Prepare headers (avoid Unicode in headers)
            # Remove emojis from tags for header compatibility
            clean_tags = []
            for tag in (tags or ["sara"]):
                # Remove emoji characters for header
                clean_tag = ''.join(char for char in tag if ord(char) < 128)
                if clean_tag.strip():
                    clean_tags.append(clean_tag.strip())
            
            headers = {
                "Title": title,
                "Priority": priority.value,
                "Tags": ",".join(clean_tags) if clean_tags else "sara"
            }
            
            # Add actions if provided
            if actions:
                # Format actions for NTFY
                action_strings = []
                for action in actions:
                    if action.get("type") == "view":
                        action_strings.append(f"view, {action['label']}, {action['url']}")
                    elif action.get("type") == "http":
                        action_strings.append(f"http, {action['label']}, {action['url']}, method={action.get('method', 'POST')}")
                
                if action_strings:
                    headers["Actions"] = "; ".join(action_strings)
            
            # Send notification using urllib (synchronous)
            # Note: For production, consider using aiohttp or httpx for true async
            import threading
            
            def send_sync():
                try:
                    data = message.encode('utf-8')
                    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
                    
                    with urllib.request.urlopen(req) as response:
                        if response.status == 200:
                            logger.info(f"📱 Notification sent: {title} (priority: {priority.name})")
                            return True
                        else:
                            logger.error(f"❌ Failed to send notification: {response.status}")
                            return False
                except Exception as e:
                    logger.error(f"❌ Sync notification error: {e}")
                    return False
            
            # Run in thread to avoid blocking async loop
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, send_sync)
            return result
                        
        except Exception as e:
            logger.error(f"❌ Notification error: {e}")
            return False
    
    async def send_timer_alert(self, user_id: str, timer_label: str, is_overdue: bool = False) -> bool:
        """Send timer completion/overdue alert"""
        
        if is_overdue:
            title = f"Timer Overdue: {timer_label}"
            message = f"Your timer '{timer_label}' is overdue!"
            priority = NotificationPriority.HIGH
            tags = ["⏰", "overdue"]
        else:
            title = f"Timer Complete: {timer_label}"
            message = f"Your timer '{timer_label}' has finished!"
            priority = NotificationPriority.NORMAL
            tags = ["⏰", "complete"]
        
        # Add action to check all timers
        actions = [
            {
                "type": "view",
                "label": "Check Timers",
                "url": f"https://sara.avery.cloud/chat"  # Direct to chat interface
            }
        ]
        
        return await self.send_notification(
            user_id=user_id,
            title=title,
            message=message,
            priority=priority,
            tags=tags,
            actions=actions
        )
    
    async def send_reminder_alert(self, user_id: str, reminder_text: str, due_in_minutes: int = 0) -> bool:
        """Send reminder alert"""
        
        if due_in_minutes <= 0:
            title = "Reminder Due Now"
            message = reminder_text
            priority = NotificationPriority.HIGH
            tags = ["📅", "due"]
        elif due_in_minutes <= 15:
            title = f"Reminder in {due_in_minutes}m"
            message = reminder_text
            priority = NotificationPriority.NORMAL
            tags = ["📅", "upcoming"]
        else:
            title = f"Upcoming Reminder"
            message = f"In {due_in_minutes} minutes: {reminder_text}"
            priority = NotificationPriority.LOW
            tags = ["📅", "scheduled"]
        
        # Add action to manage reminders
        actions = [
            {
                "type": "view", 
                "label": "Manage Reminders",
                "url": f"https://sara.avery.cloud/chat"
            }
        ]
        
        return await self.send_notification(
            user_id=user_id,
            title=title,
            message=message,
            priority=priority,
            tags=tags,
            actions=actions
        )
    
    async def send_wellness_alert(self, user_id: str, wellness_type: str, message: str) -> bool:
        """Send wellness/mood-based alert"""
        
        wellness_config = {
            "tired": {
                "title": "Wellness Check - Rest",
                "priority": NotificationPriority.LOW,
                "tags": ["😴", "wellness"]
            },
            "stressed": {
                "title": "Wellness Check - Stress",
                "priority": NotificationPriority.NORMAL,
                "tags": ["😰", "wellness"]
            },
            "focused": {
                "title": "Focus Session",
                "priority": NotificationPriority.LOW,
                "tags": ["🎯", "focus"]
            },
            "break": {
                "title": "Break Suggestion",
                "priority": NotificationPriority.LOW,
                "tags": ["☕", "break"]
            }
        }
        
        config = wellness_config.get(wellness_type, {
            "title": "Wellness Check",
            "priority": NotificationPriority.LOW,
            "tags": ["💚", "wellness"]
        })
        
        return await self.send_notification(
            user_id=user_id,
            title=config["title"],
            message=message,
            priority=config["priority"],
            tags=config["tags"]
        )
    
    async def send_priority_alert(self, user_id: str, priority_items: List[Dict]) -> bool:
        """Send alert about high priority items"""
        
        if not priority_items:
            return True
        
        item_count = len(priority_items)
        if item_count == 1:
            title = "High Priority Item"
            message = f"Don't forget: {priority_items[0]['title']}"
        else:
            title = f"{item_count} High Priority Items"
            top_item = priority_items[0]['title']
            message = f"Including: {top_item}" + (f" and {item_count-1} more" if item_count > 1 else "")
        
        return await self.send_notification(
            user_id=user_id,
            title=title,
            message=message,
            priority=NotificationPriority.NORMAL,
            tags=["⚡", "priority"]
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
            title=f"Sara Alert: {context_type.title()}",
            message=message,
            priority=priority_map.get(priority, NotificationPriority.NORMAL),
            tags=["🧠", "context"]
        )
    
    async def send_bulk_notifications(self, notifications: List[Dict]) -> Dict[str, int]:
        """Send multiple notifications efficiently"""
        
        results = {"sent": 0, "failed": 0}
        
        # Send all notifications concurrently
        tasks = []
        for notification in notifications:
            task = self.send_notification(**notification)
            tasks.append(task)
        
        # Wait for all to complete
        if tasks:
            results_list = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results_list:
                if isinstance(result, Exception):
                    results["failed"] += 1
                elif result:
                    results["sent"] += 1
                else:
                    results["failed"] += 1
        
        logger.info(f"📱 Bulk notifications: {results['sent']} sent, {results['failed']} failed")
        return results
    
    def configure(self, ntfy_url: str = None, default_topic: str = None, enabled: bool = None):
        """Configure the notification service"""
        
        if ntfy_url is not None:
            self.ntfy_base_url = ntfy_url
        if default_topic is not None:
            self.default_topic = default_topic
        if enabled is not None:
            self.enabled = enabled
            
        logger.info(f"📱 Notification service configured: enabled={self.enabled}")

# Global service instance
notification_service = NotificationService()