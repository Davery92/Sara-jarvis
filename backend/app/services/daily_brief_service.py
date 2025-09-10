"""
Daily Brief Service - Generates and caches daily briefings

This service creates personalized daily briefings by aggregating:
- High priority reminders and tasks
- Calendar events and conflicts
- Carry-over items from yesterday
- Dream highlights and insights
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func
import json
import logging
from enum import Enum

from app.models.daily_brief import DailyBrief
from app.models.jarvis_inbox import JarvisInbox, InboxKind
from app.db.session import SessionLocal

# Import models from main_simple since that's where they're actually defined
try:
    from app.main_simple import Reminder, Event as CalendarEvent
except ImportError:
    # Fallback to separate model files if main_simple import fails
    from app.models.reminder import Reminder
    from app.models.calendar import Event as CalendarEvent

logger = logging.getLogger(__name__)


class BriefSection:
    """A section in the daily brief"""
    
    def __init__(self, id: str, title: str, items: List[Dict[str, Any]] = None):
        self.id = id
        self.title = title
        self.items = items or []
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "items": self.items
        }


class DailyBriefService:
    """Service for generating and managing daily briefs"""
    
    def __init__(self):
        self.cache_duration_hours = 1  # Brief is cached for 1 hour
    
    async def generate_brief(self, db: Session, user_id: str, target_date: date = None) -> DailyBrief:
        """
        Generate a comprehensive daily brief
        
        Args:
            target_date: Date to generate brief for (defaults to today)
        """
        if target_date is None:
            target_date = date.today()
        
        start_time = datetime.now()
        
        # Check for existing cached brief
        existing = db.query(DailyBrief).filter(
            and_(
                DailyBrief.user_id == user_id,
                DailyBrief.brief_date == target_date
            )
        ).first()
        
        if existing and self._is_cache_valid(existing):
            logger.debug(f"Returning cached brief for {target_date}")
            return existing
        
        # Generate new brief
        sections = []
        
        # 1. Top Priorities Section
        priorities_section = await self._build_priorities_section(db, user_id, target_date)
        if priorities_section.items:
            sections.append(priorities_section.to_dict())
        
        # 2. Calendar Overview Section
        calendar_section = await self._build_calendar_section(db, user_id, target_date)
        if calendar_section.items:
            sections.append(calendar_section.to_dict())
        
        # 3. Carry-over Tasks Section
        carryover_section = await self._build_carryover_section(db, user_id, target_date)
        if carryover_section.items:
            sections.append(carryover_section.to_dict())
        
        # 4. Dream Highlights Section
        dream_section = await self._build_dream_section(db, user_id, target_date)
        if dream_section.items:
            sections.append(dream_section.to_dict())
        
        # 5. Suggested Focus Section
        focus_section = await self._build_focus_section(db, user_id, target_date)
        if focus_section.items:
            sections.append(focus_section.to_dict())
        
        # Calculate generation metrics
        generation_time = datetime.now() - start_time
        
        # Count content sources
        calendar_count = len(calendar_section.items)
        reminders_count = len(priorities_section.items)
        insights_count = len(dream_section.items)
        
        # Create or update brief
        if existing:
            existing.sections = sections
            existing.generated_at = datetime.now()
            existing.generation_duration_ms = int(generation_time.total_seconds() * 1000)
            existing.calendar_events_count = calendar_count
            existing.reminders_count = reminders_count
            existing.insights_count = insights_count
            brief = existing
        else:
            brief = DailyBrief(
                user_id=user_id,
                brief_date=target_date,
                sections=sections,
                generation_duration_ms=int(generation_time.total_seconds() * 1000),
                calendar_events_count=calendar_count,
                reminders_count=reminders_count,
                insights_count=insights_count
            )
            db.add(brief)
        
        db.commit()
        db.refresh(brief)
        
        logger.info(f"Generated daily brief for {target_date}: {len(sections)} sections, "
                   f"{brief.total_items} items in {generation_time.total_seconds():.2f}s")
        
        return brief
    
    async def _build_priorities_section(self, db: Session, user_id: str, target_date: date) -> BriefSection:
        """Build top priorities section from high-priority reminders"""
        
        section = BriefSection("priorities", "🎯 Top Priorities")
        
        # Get reminders for today and overdue (using actual model fields)
        today_start = datetime.combine(target_date, datetime.min.time())
        today_end = datetime.combine(target_date, datetime.max.time())
        
        reminders = db.query(Reminder).filter(
            and_(
                Reminder.user_id == user_id,
                Reminder.reminder_time <= today_end,  # Use reminder_time field
                Reminder.is_completed == False  # Use is_completed field
            )
        ).order_by(Reminder.reminder_time).limit(3).all()
        
        for reminder in reminders:
            due_date = reminder.reminder_time.date()
            days_overdue = (target_date - due_date).days
            overdue_text = f" (overdue {days_overdue}d)" if days_overdue > 0 else ""
            
            section.items.append({
                "id": f"reminder_{reminder.id}",
                "title": reminder.title,  # Use title field
                "subtitle": f"Due {due_date}{overdue_text}",
                "type": "reminder",
                "source_id": str(reminder.id),
                "action": "complete_reminder",
                "due_date": reminder.reminder_time.isoformat()
            })
        
        return section
    
    async def _build_calendar_section(self, db: Session, user_id: str, target_date: date) -> BriefSection:
        """Build calendar overview section"""
        
        section = BriefSection("calendar", "📅 Calendar Overview")
        
        # Get today's events
        start_of_day = datetime.combine(target_date, datetime.min.time())
        end_of_day = datetime.combine(target_date, datetime.max.time())
        
        events = db.query(CalendarEvent).filter(
            and_(
                CalendarEvent.user_id == user_id,
                CalendarEvent.starts_at >= start_of_day,  # Use starts_at field
                CalendarEvent.starts_at <= end_of_day
            )
        ).order_by(CalendarEvent.starts_at).all()
        
        if not events:
            section.items.append({
                "title": "No scheduled events today",
                "subtitle": "Perfect day for focused work",
                "type": "info"
            })
        else:
            # First event
            first_event = events[0]
            section.items.append({
                "id": f"event_{first_event.id}",
                "title": f"First: {first_event.title}",
                "subtitle": f"at {first_event.starts_at.strftime('%I:%M %p')}",
                "type": "calendar_event",
                "source_id": str(first_event.id),
                "start_time": first_event.starts_at.isoformat()
            })
            
            # Check for conflicts or tight scheduling
            conflicts = self._detect_calendar_conflicts(events)
            if conflicts:
                section.items.append({
                    "title": f"⚠️ {len(conflicts)} scheduling conflict(s)",
                    "subtitle": "Review calendar for overlaps",
                    "type": "warning",
                    "conflicts": conflicts
                })
        
        return section
    
    async def _build_carryover_section(self, db: Session, user_id: str, target_date: date) -> BriefSection:
        """Build carry-over tasks section"""
        
        section = BriefSection("carryover", "📝 Carry-over Items")
        
        yesterday = target_date - timedelta(days=1)
        
        # Find incomplete reminders from yesterday
        yesterday_start = datetime.combine(yesterday, datetime.min.time())
        yesterday_end = datetime.combine(yesterday, datetime.max.time())
        
        overdue_reminders = db.query(Reminder).filter(
            and_(
                Reminder.user_id == user_id,
                Reminder.reminder_time >= yesterday_start,
                Reminder.reminder_time <= yesterday_end,
                Reminder.is_completed == False
            )
        ).order_by(Reminder.reminder_time).limit(2).all()
        
        for reminder in overdue_reminders:
            section.items.append({
                "id": f"carryover_reminder_{reminder.id}",
                "title": reminder.title,
                "subtitle": f"From {yesterday.strftime('%B %d')}",
                "type": "carryover_reminder",
                "source_id": str(reminder.id),
                "action": "reschedule_or_complete"
            })
        
        return section
    
    async def _build_dream_section(self, db: Session, user_id: str, target_date: date) -> BriefSection:
        """Build dream highlights section (placeholder for Phase 2)"""
        
        section = BriefSection("dreams", "💭 Overnight Insights")
        
        # TODO: In Phase 2, this will pull from the dream consolidation pipeline
        # For now, look for recent high-priority inbox items from 'dream' source
        
        dream_items = db.query(JarvisInbox).filter(
            and_(
                JarvisInbox.user_id == user_id,
                JarvisInbox.source == "dream",
                JarvisInbox.created_at >= target_date - timedelta(days=1),
                JarvisInbox.priority >= 7
            )
        ).order_by(desc(JarvisInbox.priority)).limit(2).all()
        
        for item in dream_items:
            section.items.append({
                "id": f"dream_{item.id}",
                "title": item.title,
                "subtitle": "From overnight processing",
                "type": "insight",
                "source_id": item.id,
                "action": "view_insight"
            })
        
        # Fallback placeholder
        if not section.items:
            section.items.append({
                "title": "Memory consolidation complete",
                "subtitle": "No significant insights from overnight processing",
                "type": "info"
            })
        
        return section
    
    async def _build_focus_section(self, db: Session, user_id: str, target_date: date) -> BriefSection:
        """Build suggested focus section"""
        
        section = BriefSection("focus", "🎯 Suggested Focus")
        
        # TODO: This will become more intelligent in later phases
        # For now, suggest based on patterns
        
        # Check if it's a Monday (weekly planning)
        if target_date.weekday() == 0:  # Monday
            section.items.append({
                "title": "Weekly Planning",
                "subtitle": "Review goals and plan the week ahead",
                "type": "suggestion",
                "action": "weekly_review"
            })
        
        # Check for upcoming deadlines
        deadline_start = datetime.combine(target_date + timedelta(days=1), datetime.min.time())
        deadline_end = datetime.combine(target_date + timedelta(days=3), datetime.max.time())
        
        upcoming_deadlines = db.query(Reminder).filter(
            and_(
                Reminder.user_id == user_id,
                Reminder.reminder_time >= deadline_start,
                Reminder.reminder_time <= deadline_end,
                Reminder.is_completed == False
            )
        ).count()
        
        if upcoming_deadlines > 0:
            section.items.append({
                "title": f"Prepare for {upcoming_deadlines} upcoming deadline(s)",
                "subtitle": "Review tasks due in the next 3 days",
                "type": "suggestion",
                "action": "review_deadlines"
            })
        
        return section
    
    def _detect_calendar_conflicts(self, events: List[CalendarEvent]) -> List[Dict[str, Any]]:
        """Detect scheduling conflicts in calendar events"""
        
        conflicts = []
        
        for i, event1 in enumerate(events):
            for j, event2 in enumerate(events[i+1:], i+1):
                # Check for overlap
                if (event1.starts_at < event2.ends_at and 
                    event2.starts_at < event1.ends_at):
                    
                    conflicts.append({
                        "event1": {
                            "id": str(event1.id),
                            "title": event1.title,
                            "time": event1.starts_at.strftime('%I:%M %p')
                        },
                        "event2": {
                            "id": str(event2.id),
                            "title": event2.title,
                            "time": event2.starts_at.strftime('%I:%M %p')
                        },
                        "overlap_duration": min(event1.ends_at, event2.ends_at) - max(event1.starts_at, event2.starts_at)
                    })
        
        return conflicts
    
    def _is_cache_valid(self, brief: DailyBrief) -> bool:
        """Check if cached brief is still valid"""
        
        if not brief.generated_at:
            return False
        
        age = datetime.now() - brief.generated_at
        return age.total_seconds() < (self.cache_duration_hours * 3600)
    
    def mark_viewed(self, db: Session, brief_id: str, user_id: str) -> bool:
        """Mark a brief as viewed by the user"""
        
        brief = db.query(DailyBrief).filter(
            and_(
                DailyBrief.id == brief_id,
                DailyBrief.user_id == user_id
            )
        ).first()
        
        if not brief:
            return False
        
        brief.viewed_at = datetime.now()
        db.commit()
        
        return True
    
    def pin_item(self, db: Session, brief_id: str, user_id: str, item_id: str) -> bool:
        """Pin a brief item as a reminder"""
        
        brief = db.query(DailyBrief).filter(
            and_(
                DailyBrief.id == brief_id,
                DailyBrief.user_id == user_id
            )
        ).first()
        
        if not brief:
            return False
        
        if not brief.pinned_items:
            brief.pinned_items = []
        
        if item_id not in brief.pinned_items:
            brief.pinned_items = brief.pinned_items + [item_id]
            db.commit()
        
        return True


# Global service instance
daily_brief_service = DailyBriefService()