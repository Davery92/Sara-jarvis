"""
Jarvis Inbox Service - Core service for managing proactive notifications

This service handles:
- Creating inbox items from various sources
- Batching and deduplication 
- Nudge policy enforcement
- Quiet hours management
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, time, timedelta
from app.core.timezone import naive_local_now
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc
import uuid
import json
import logging
from enum import Enum

from app.models.jarvis_inbox import JarvisInbox, InboxKind, InboxStatus
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


class NudgePolicy:
    """Manages nudging policy and quiet hours"""
    
    def __init__(self, 
                 window_start: str = "08:00", 
                 window_end: str = "20:00",
                 batch_interval_min: int = 30,
                 max_per_day: int = 8,
                 priority_floor: int = 5):
        self.window_start = time.fromisoformat(window_start)
        self.window_end = time.fromisoformat(window_end)
        self.batch_interval_min = batch_interval_min
        self.max_per_day = max_per_day
        self.priority_floor = priority_floor
    
    def is_quiet_hours(self, dt: datetime = None) -> bool:
        """Check if current time is in quiet hours"""
        if dt is None:
            dt = naive_local_now()
        
        current_time = dt.time()
        
        # Simple case: window doesn't cross midnight
        if self.window_start <= self.window_end:
            return not (self.window_start <= current_time <= self.window_end)
        
        # Complex case: window crosses midnight (e.g., 22:00-06:00)
        return not (current_time >= self.window_start or current_time <= self.window_end)
    
    def should_batch(self, last_batch_time: Optional[datetime]) -> bool:
        """Check if enough time has passed since last batch"""
        if last_batch_time is None:
            return True
        
        elapsed = naive_local_now() - last_batch_time
        return elapsed.total_seconds() >= (self.batch_interval_min * 60)
    
    def daily_count_exceeded(self, db: Session, user_id: int) -> bool:
        """Check if daily nudge limit has been reached"""
        today = naive_local_now().date()
        count = db.query(JarvisInbox).filter(
            and_(
                JarvisInbox.user_id == user_id,
                JarvisInbox.created_at >= today,
                JarvisInbox.created_at < today + timedelta(days=1)
            )
        ).count()
        
        return count >= self.max_per_day


class JarvisInboxService:
    """Main service for managing the Jarvis inbox"""
    
    def __init__(self):
        # Load from environment in production
        self.policy = NudgePolicy()
        self._pending_nudges: List[Dict] = []
        self._last_batch_time: Optional[datetime] = None
    
    def create_inbox_item(self, 
                         db: Session,
                         user_id: int,
                         kind: InboxKind,
                         title: str,
                         body: str = None,
                         source: str = None,
                         payload: Dict[str, Any] = None,
                         priority: int = 5,
                         dedupe_key: str = None,
                         immediate: bool = False) -> Optional[JarvisInbox]:
        """
        Create an inbox item, respecting nudge policy unless immediate=True
        
        Args:
            immediate: If True, bypass batching and quiet hours
        """
        
        # Check daily limit
        if not immediate and self.policy.daily_count_exceeded(db, user_id):
            logger.warning(f"Daily nudge limit exceeded for user {user_id}")
            return None
        
        # Check priority floor
        if not immediate and priority < self.policy.priority_floor:
            logger.debug(f"Item below priority floor: {priority} < {self.policy.priority_floor}")
            return None
        
        # Create nudge object
        nudge = {
            "user_id": user_id,
            "kind": kind,
            "title": title,
            "body": body,
            "source": source,
            "payload": payload or {},
            "priority": priority,
            "dedupe_key": dedupe_key,
            "created_at": naive_local_now()
        }
        
        # Handle immediate items (skip batching)
        if immediate or kind == InboxKind.ALERT:
            return self._create_db_item(db, nudge)
        
        # Add to pending batch
        self._pending_nudges.append(nudge)
        
        # Check if we should flush the batch
        if (self.policy.should_batch(self._last_batch_time) and 
            not self.policy.is_quiet_hours()):
            return self._flush_batch(db, user_id)
        
        return None
    
    def _create_db_item(self, db: Session, nudge: Dict) -> JarvisInbox:
        """Create actual database item from nudge"""
        
        # Check for existing item with same dedupe_key
        if nudge.get("dedupe_key"):
            existing = db.query(JarvisInbox).filter(
                and_(
                    JarvisInbox.user_id == nudge["user_id"],
                    JarvisInbox.dedupe_key == nudge["dedupe_key"],
                    JarvisInbox.status == InboxStatus.NEW
                )
            ).first()
            
            if existing:
                logger.debug(f"Skipping duplicate item: {nudge['dedupe_key']}")
                return existing
        
        # Create new item
        item = JarvisInbox(
            user_id=nudge["user_id"],
            kind=nudge["kind"],
            title=nudge["title"],
            body=nudge["body"],
            source=nudge["source"],
            payload=nudge["payload"],
            priority=nudge["priority"],
            dedupe_key=nudge["dedupe_key"]
        )
        
        db.add(item)
        db.commit()
        db.refresh(item)
        
        logger.info(f"Created inbox item: {item.id} - {item.title}")
        return item
    
    def _flush_batch(self, db: Session, user_id: int) -> Optional[JarvisInbox]:
        """Flush pending nudges as a batched item"""
        
        if not self._pending_nudges:
            return None
        
        # Deduplicate by dedupe_key
        unique_nudges = {}
        for nudge in self._pending_nudges:
            key = nudge.get("dedupe_key") or str(uuid.uuid4())
            if key not in unique_nudges or nudge["priority"] > unique_nudges[key]["priority"]:
                unique_nudges[key] = nudge
        
        nudges = list(unique_nudges.values())
        
        if len(nudges) == 1:
            # Single item - create directly
            item = self._create_db_item(db, nudges[0])
        else:
            # Multiple items - create batched item
            batch_id = str(uuid.uuid4())
            titles = [n["title"] for n in nudges[:3]]  # First 3 titles
            if len(nudges) > 3:
                titles.append(f"and {len(nudges) - 3} more...")
            
            batch_title = " • ".join(titles)
            batch_body = json.dumps([{
                "title": n["title"],
                "body": n["body"],
                "source": n["source"],
                "priority": n["priority"]
            } for n in nudges], indent=2)
            
            item = JarvisInbox(
                user_id=user_id,
                kind=InboxKind.INSIGHT,
                title=batch_title,
                body=batch_body,
                source="batch",
                payload={"batched_items": len(nudges)},
                priority=max(n["priority"] for n in nudges),
                batch_id=batch_id
            )
            
            db.add(item)
            db.commit()
            db.refresh(item)
        
        # Clear batch
        self._pending_nudges.clear()
        self._last_batch_time = naive_local_now()
        
        logger.info(f"Flushed batch: {len(nudges)} items -> inbox item {item.id}")
        return item
    
    def get_inbox_items(self, 
                       db: Session, 
                       user_id: int,
                       status: Optional[InboxStatus] = None,
                       limit: int = 20,
                       offset: int = 0) -> List[JarvisInbox]:
        """Get inbox items with filtering and pagination"""
        
        query = db.query(JarvisInbox).filter(JarvisInbox.user_id == user_id)
        
        if status:
            query = query.filter(JarvisInbox.status == status)
        
        return query.order_by(desc(JarvisInbox.created_at)).offset(offset).limit(limit).all()
    
    def mark_read(self, db: Session, item_id: int, user_id: int) -> bool:
        """Mark an inbox item as read"""
        
        item = db.query(JarvisInbox).filter(
            and_(
                JarvisInbox.id == item_id,
                JarvisInbox.user_id == user_id
            )
        ).first()
        
        if not item:
            return False
        
        item.status = InboxStatus.READ
        item.read_at = naive_local_now()
        db.commit()
        
        return True
    
    def archive(self, db: Session, item_id: int, user_id: int) -> bool:
        """Archive an inbox item"""
        
        item = db.query(JarvisInbox).filter(
            and_(
                JarvisInbox.id == item_id,
                JarvisInbox.user_id == user_id
            )
        ).first()
        
        if not item:
            return False
        
        item.status = InboxStatus.ARCHIVED
        item.archived_at = naive_local_now()
        db.commit()
        
        return True
    
    def get_unread_count(self, db: Session, user_id: int) -> int:
        """Get count of unread inbox items"""
        
        return db.query(JarvisInbox).filter(
            and_(
                JarvisInbox.user_id == user_id,
                JarvisInbox.status == InboxStatus.NEW
            )
        ).count()


# Global service instance
inbox_service = JarvisInboxService()