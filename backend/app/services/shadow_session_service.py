"""
Shadow Session Service
Manages Shadow Mode session lifecycle and state
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.shadow import ShadowSession, ShadowEvent, ShadowNote, ShadowSummary
from app.models.user import User
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


class ShadowSessionService:
    """Manage Shadow Mode work capture sessions"""

    def __init__(self):
        logger.info("🕵️ ShadowSessionService initialized")

    async def start_session(
        self,
        user_id: str,
        duration_minutes: Optional[int] = None,
        device_id: Optional[str] = None,
        context: Optional[str] = None,
        calendar_event_id: Optional[str] = None,
        privacy_mode: bool = False
    ) -> ShadowSession:
        """Start a new Shadow session"""
        db = SessionLocal()
        try:
            # Check for existing active session
            existing = db.query(ShadowSession).filter(
                and_(
                    ShadowSession.user_id == user_id,
                    ShadowSession.status.in_(["active", "paused"])
                )
            ).first()

            if existing:
                logger.warning(f"User {user_id} already has active session {existing.id}")
                raise ValueError(f"Active session already exists. Wrap up session {existing.id} first.")

            # Create new session
            session = ShadowSession(
                user_id=user_id,
                device_id=device_id,
                duration_minutes=duration_minutes,
                context=context,
                calendar_event_id=calendar_event_id,
                privacy_mode=privacy_mode,
                status="active"
            )

            db.add(session)
            db.commit()
            db.refresh(session)

            logger.info(f"🕵️ Started Shadow session {session.id} for user {user_id} (duration: {duration_minutes}min, privacy: {privacy_mode})")
            return session

        finally:
            db.close()

    async def get_session(self, session_id: str) -> Optional[ShadowSession]:
        """Get session by ID"""
        db = SessionLocal()
        try:
            return db.query(ShadowSession).filter(ShadowSession.id == session_id).first()
        finally:
            db.close()

    async def get_active_session(self, user_id: str) -> Optional[ShadowSession]:
        """Get user's current active/paused session"""
        db = SessionLocal()
        try:
            return db.query(ShadowSession).filter(
                and_(
                    ShadowSession.user_id == user_id,
                    ShadowSession.status.in_(["active", "paused"])
                )
            ).first()
        finally:
            db.close()

    async def pause_session(self, session_id: str) -> ShadowSession:
        """Pause an active session"""
        db = SessionLocal()
        try:
            session = db.query(ShadowSession).filter(ShadowSession.id == session_id).first()
            if not session:
                raise ValueError(f"Session {session_id} not found")

            if session.status != "active":
                raise ValueError(f"Can only pause active sessions (current: {session.status})")

            session.status = "paused"
            session.paused_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(session)

            logger.info(f"⏸️ Paused Shadow session {session_id}")
            return session

        finally:
            db.close()

    async def resume_session(self, session_id: str) -> ShadowSession:
        """Resume a paused session"""
        db = SessionLocal()
        try:
            session = db.query(ShadowSession).filter(ShadowSession.id == session_id).first()
            if not session:
                raise ValueError(f"Session {session_id} not found")

            if session.status != "paused":
                raise ValueError(f"Can only resume paused sessions (current: {session.status})")

            session.status = "active"
            session.resumed_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(session)

            logger.info(f"▶️ Resumed Shadow session {session_id}")
            return session

        finally:
            db.close()

    async def wrap_session(self, session_id: str) -> ShadowSession:
        """End a session and prepare for summary generation"""
        db = SessionLocal()
        try:
            session = db.query(ShadowSession).filter(ShadowSession.id == session_id).first()
            if not session:
                raise ValueError(f"Session {session_id} not found")

            if session.status == "wrapped":
                logger.warning(f"Session {session_id} already wrapped")
                return session

            session.status = "wrapped"
            session.ended_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(session)

            logger.info(f"🎁 Wrapped Shadow session {session_id}")
            return session

        finally:
            db.close()

    async def add_event(
        self,
        session_id: str,
        event_type: str,
        app_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        classified_as: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> ShadowEvent:
        """Add a metadata event to the session"""
        db = SessionLocal()
        try:
            # Verify session exists and is active
            session = db.query(ShadowSession).filter(ShadowSession.id == session_id).first()
            if not session:
                raise ValueError(f"Session {session_id} not found")

            if session.status not in ["active", "paused"]:
                raise ValueError(f"Cannot add events to {session.status} session")

            event = ShadowEvent(
                session_id=session_id,
                event_type=event_type,
                app_name=app_name,
                event_metadata=metadata or {},
                classified_as=classified_as,
                tags=tags or []
            )

            db.add(event)
            db.commit()
            db.refresh(event)

            logger.debug(f"📝 Added {event_type} event to session {session_id}")
            return event

        finally:
            db.close()

    async def add_note(
        self,
        session_id: str,
        note_type: str,
        content: str,
        source: str = "chat",
        due_date: Optional[datetime] = None,
        priority: Optional[str] = None
    ) -> ShadowNote:
        """Add a user note to the session"""
        db = SessionLocal()
        try:
            # Verify session exists
            session = db.query(ShadowSession).filter(ShadowSession.id == session_id).first()
            if not session:
                raise ValueError(f"Session {session_id} not found")

            if session.status not in ["active", "paused"]:
                raise ValueError(f"Cannot add notes to {session.status} session")

            note = ShadowNote(
                session_id=session_id,
                note_type=note_type,
                content=content,
                source=source,
                due_date=due_date,
                priority=priority
            )

            db.add(note)
            db.commit()
            db.refresh(note)

            logger.info(f"📌 Added {note_type} note to session {session_id}: {content[:50]}...")
            return note

        finally:
            db.close()

    async def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """Get comprehensive session status"""
        db = SessionLocal()
        try:
            session = db.query(ShadowSession).filter(ShadowSession.id == session_id).first()
            if not session:
                raise ValueError(f"Session {session_id} not found")

            # Count events and notes by type
            events = db.query(ShadowEvent).filter(ShadowEvent.session_id == session_id).all()
            notes = db.query(ShadowNote).filter(ShadowNote.session_id == session_id).all()

            event_types = {}
            for event in events:
                event_types[event.event_type] = event_types.get(event.event_type, 0) + 1

            note_counts = {
                "task": sum(1 for n in notes if n.note_type == "task"),
                "decision": sum(1 for n in notes if n.note_type == "decision"),
                "question": sum(1 for n in notes if n.note_type == "question"),
                "idea": sum(1 for n in notes if n.note_type == "idea"),
                "bookmark": sum(1 for n in notes if n.note_type == "bookmark")
            }

            # Calculate duration
            if session.ended_at:
                duration_seconds = (session.ended_at - session.started_at).total_seconds()
            else:
                duration_seconds = (datetime.now(timezone.utc) - session.started_at).total_seconds()

            # Check if time limit exceeded
            time_remaining = None
            if session.duration_minutes:
                target_end = session.started_at + timedelta(minutes=session.duration_minutes)
                time_remaining = (target_end - datetime.now(timezone.utc)).total_seconds()

            return {
                "session_id": session_id,
                "status": session.status,
                "device_id": session.device_id,
                "privacy_mode": session.privacy_mode,
                "context": session.context,
                "started_at": session.started_at.isoformat(),
                "ended_at": session.ended_at.isoformat() if session.ended_at else None,
                "duration_seconds": int(duration_seconds),
                "duration_minutes_planned": session.duration_minutes,
                "time_remaining_seconds": int(time_remaining) if time_remaining else None,
                "event_count": len(events),
                "event_types": event_types,
                "note_counts": note_counts,
                "total_notes": len(notes)
            }

        finally:
            db.close()

    async def list_recent_sessions(self, user_id: str, limit: int = 10) -> List[ShadowSession]:
        """List user's recent Shadow sessions"""
        db = SessionLocal()
        try:
            return db.query(ShadowSession).filter(
                ShadowSession.user_id == user_id
            ).order_by(ShadowSession.started_at.desc()).limit(limit).all()
        finally:
            db.close()


# Global service instance
shadow_session_service = ShadowSessionService()
