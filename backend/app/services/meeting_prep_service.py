"""
Meeting Preparation Service - Gathers context before calendar events
"""
from typing import List, Dict, Optional
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)


class MeetingPrepService:
    """Prepares contextual information before meetings"""

    def __init__(self, db: Session):
        self.db = db

    async def prepare_for_meeting(self, event_id: str, user_id: str) -> Dict:
        """
        Gather context for an upcoming meeting

        Returns:
            Dictionary with meeting prep information
        """
        try:
            from app.models.calendar_event import CalendarEvent as Event
            from app.models.note import Note
            from app.models.thread import ConversationThread

            # Get the event
            event = self.db.query(Event).filter(
                Event.id == event_id,
                Event.user_id == user_id
            ).first()

            if not event:
                return {"error": "Event not found"}

            # Search for related notes (simple text search)
            related_notes = self.db.query(Note).filter(
                Note.user_id == user_id,
                Note.content.ilike(f"%{event.title}%")
            ).limit(5).all()

            # Search for related threads
            related_threads = self.db.query(ConversationThread).filter(
                ConversationThread.user_id == user_id,
                ConversationThread.title.ilike(f"%{event.title}%")
            ).limit(3).all()

            # Find previous similar meetings
            previous_meetings = self.db.query(Event).filter(
                Event.user_id == user_id,
                Event.id != event_id,
                Event.title.ilike(f"%{event.title[:10]}%"),  # Similar title
                Event.starts_at < event.starts_at
            ).order_by(Event.starts_at.desc()).limit(3).all()

            # Compile brief
            prep_data = {
                "event": {
                    "id": str(event.id),
                    "title": event.title,
                    "starts_at": event.starts_at.isoformat(),
                    "description": event.description,
                    "location": event.location
                },
                "context": {
                    "related_notes": [
                        {
                            "id": str(note.id),
                            "title": note.title,
                            "preview": note.content[:200] if note.content else ""
                        }
                        for note in related_notes
                    ],
                    "related_threads": [
                        {
                            "id": str(thread.id),
                            "title": thread.title,
                            "summary": thread.summary,
                            "last_activity": thread.last_activity.isoformat()
                        }
                        for thread in related_threads
                    ],
                    "previous_meetings": [
                        {
                            "id": str(mtg.id),
                            "title": mtg.title,
                            "date": mtg.starts_at.isoformat()
                        }
                        for mtg in previous_meetings
                    ]
                },
                "prepared_at": datetime.now(timezone.utc).isoformat(),
                "time_until_meeting": str(event.starts_at - datetime.now(timezone.utc))
            }

            logger.info(f"Meeting prep ready for event {event_id}: {len(related_notes)} notes, {len(related_threads)} threads")

            return prep_data

        except Exception as e:
            logger.error(f"Failed to prepare for meeting {event_id}: {e}")
            return {"error": str(e)}

    def should_prepare_meeting(self, event: "Event") -> bool:
        """
        Determine if meeting prep should be triggered

        Typically 15-30 minutes before the event
        """
        now = datetime.now(timezone.utc)
        time_until = event.starts_at - now

        # Prepare if meeting is between 15-30 minutes away
        return timedelta(minutes=15) <= time_until <= timedelta(minutes=30)
