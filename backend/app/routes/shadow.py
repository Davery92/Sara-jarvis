"""
Shadow Mode API Routes
Time-boxed work capture with intelligent summaries
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from app.models.user import User
from app.services.shadow_session_service import shadow_session_service
from app.services.shadow_summary_generator import shadow_summary_generator
from app.services.shadow_classifier import shadow_classifier
from app.db.session import get_db, SessionLocal
from app.models.shadow import ShadowSession, ShadowNote, ShadowSummary
from app.models.note import Note
from app.models.reminder import Reminder
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# ===== Pydantic Models =====

class SessionStartRequest(BaseModel):
    duration_minutes: Optional[int] = None
    device_id: Optional[str] = None
    context: Optional[str] = None
    calendar_event_id: Optional[str] = None
    privacy_mode: bool = False


class SessionStartResponse(BaseModel):
    session_id: str
    status: str
    started_at: datetime
    duration_minutes: Optional[int]
    device_id: Optional[str]
    privacy_mode: bool
    message: str


class NoteAddRequest(BaseModel):
    note_type: str  # task, decision, question, idea, bookmark
    content: str
    due_date: Optional[datetime] = None
    priority: Optional[str] = None


class EventAddRequest(BaseModel):
    event_type: str  # browser, editor, terminal, fs, calendar, presence
    app_name: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class SessionStatusResponse(BaseModel):
    session_id: str
    status: str
    device_id: Optional[str]
    privacy_mode: bool
    context: Optional[str]
    started_at: str
    ended_at: Optional[str]
    duration_seconds: int
    duration_minutes_planned: Optional[int]
    time_remaining_seconds: Optional[int]
    event_count: int
    event_types: Dict[str, int]
    note_counts: Dict[str, int]
    total_notes: int


class SummaryCommitRequest(BaseModel):
    decisions: List[str]
    tasks: List[Dict[str, Any]]
    questions: List[str]
    ideas: List[str]
    refs: List[Dict[str, str]]


# ===== Helper Functions =====

def get_current_user():
    """Mock auth - TODO: integrate with actual auth"""
    # For MVP, return a test user ID
    # This should be replaced with actual JWT auth
    from app.db.session import SessionLocal
    from app.models.user import User
    db = SessionLocal()
    try:
        user = db.query(User).first()
        if not user:
            raise HTTPException(status_code=401, detail="No users found")
        return user
    finally:
        db.close()


# ===== API Endpoints =====

@router.post("/start", response_model=SessionStartResponse)
async def start_shadow_session(
    request: SessionStartRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Start a new Shadow Mode session

    Example:
    POST /shadow/start
    {
        "duration_minutes": 25,
        "context": "deep work on authentication",
        "privacy_mode": false
    }
    """
    try:
        session = await shadow_session_service.start_session(
            user_id=current_user.id,
            duration_minutes=request.duration_minutes,
            device_id=request.device_id,
            context=request.context,
            calendar_event_id=request.calendar_event_id,
            privacy_mode=request.privacy_mode
        )

        duration_text = f"{request.duration_minutes} minutes" if request.duration_minutes else "unlimited time"
        device_text = f" on {request.device_id}" if request.device_id else ""
        privacy_text = " (privacy mode enabled)" if request.privacy_mode else ""

        message = f"🕵️ Shadow session started{device_text} for {duration_text}{privacy_text}"

        return SessionStartResponse(
            session_id=session.id,
            status=session.status,
            started_at=session.started_at,
            duration_minutes=session.duration_minutes,
            device_id=session.device_id,
            privacy_mode=session.privacy_mode,
            message=message
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error starting Shadow session: {e}")
        raise HTTPException(status_code=500, detail="Failed to start Shadow session")


@router.post("/{session_id}/note", status_code=status.HTTP_201_CREATED)
async def add_note_to_session(
    session_id: str,
    request: NoteAddRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Add a user note to active session

    Example:
    POST /shadow/{session_id}/note
    {
        "note_type": "task",
        "content": "Finish documentation by Friday",
        "due_date": "2025-10-10T17:00:00Z"
    }
    """
    try:
        note = await shadow_session_service.add_note(
            session_id=session_id,
            note_type=request.note_type,
            content=request.content,
            source="chat",
            due_date=request.due_date,
            priority=request.priority
        )

        return {
            "note_id": note.id,
            "session_id": session_id,
            "note_type": note.note_type,
            "content": note.content,
            "timestamp": note.timestamp.isoformat(),
            "message": f"📌 Added {note.note_type}: {note.content[:50]}"
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error adding note: {e}")
        raise HTTPException(status_code=500, detail="Failed to add note")


@router.post("/{session_id}/event", status_code=status.HTTP_201_CREATED)
async def add_event_to_session(
    session_id: str,
    request: EventAddRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Add a metadata event to session (from desktop agent)

    Example:
    POST /shadow/{session_id}/event
    {
        "event_type": "browser",
        "app_name": "Chrome",
        "metadata": {
            "title": "Python asyncio documentation",
            "url": "https://docs.python.org/3/library/asyncio.html"
        }
    }
    """
    try:
        # Classify event
        classified_as = shadow_classifier.classify_event(
            request.event_type,
            request.metadata or {}
        )

        tags = shadow_classifier.extract_tags(
            str(request.metadata),
            request.event_type
        )

        event = await shadow_session_service.add_event(
            session_id=session_id,
            event_type=request.event_type,
            app_name=request.app_name,
            metadata=request.metadata,
            classified_as=classified_as,
            tags=tags
        )

        return {
            "event_id": event.id,
            "session_id": session_id,
            "event_type": event.event_type,
            "classified_as": event.classified_as,
            "tags": event.tags,
            "timestamp": event.timestamp.isoformat()
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error adding event: {e}")
        raise HTTPException(status_code=500, detail="Failed to add event")


@router.get("/agent/status")
async def get_agent_status(current_user: User = Depends(get_current_user)):
    """Get status of connected Shadow agents based on recent activity"""
    from sqlalchemy import select, func
    from app.models.shadow import ShadowEvent

    db = SessionLocal()
    try:
        # Get recent events grouped by app_name to detect active agents
        # Events from the last 2 minutes indicate an agent is actively monitoring
        two_minutes_ago = datetime.utcnow() - timedelta(minutes=2)

        # Query for recent events to determine agent activity
        stmt = (
            select(
                ShadowEvent.app_name,
                ShadowEvent.event_type,
                func.max(ShadowEvent.timestamp).label('last_seen'),
                func.count(ShadowEvent.id).label('event_count')
            )
            .join(ShadowSession, ShadowEvent.session_id == ShadowSession.id)
            .where(ShadowSession.user_id == current_user.id)
            .where(ShadowEvent.timestamp >= two_minutes_ago)
            .group_by(ShadowEvent.app_name, ShadowEvent.event_type)
        )

        result = db.execute(stmt).all()

        # Determine if we have active browser or editor monitoring
        browser_agent_active = any(r.event_type == 'browser' for r in result)
        editor_agent_active = any(r.event_type == 'editor' for r in result)

        agents = []

        if browser_agent_active or editor_agent_active:
            # Agent is connected if we've seen events recently
            latest = max((r.last_seen for r in result), default=None)
            agents.append({
                "platform": "windows" if any('chrome' in r.app_name.lower() or 'edge' in r.app_name.lower() for r in result if r.app_name) else "unknown",
                "status": "online",
                "last_seen": latest.isoformat() if latest else None,
                "monitoring": {
                    "browser": browser_agent_active,
                    "editor": editor_agent_active
                },
                "event_count": sum(r.event_count for r in result)
            })

        return {
            "agents": agents,
            "total_active": len(agents),
            "last_check": datetime.utcnow().isoformat()
        }

    finally:
        db.close()


@router.get("/{session_id}/summary")
async def get_session_summary(
    session_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get session summary (tasks, decisions, questions, ideas)"""
    from app.models.shadow import ShadowSummary

    db = SessionLocal()
    try:
        summary = db.query(ShadowSummary).filter(
            ShadowSummary.session_id == session_id
        ).first()

        if not summary:
            raise HTTPException(status_code=404, detail="Summary not found for this session")

        return {
            "session_id": summary.session_id,
            "tasks": summary.tasks or [],
            "decisions": summary.decisions or [],
            "questions": summary.questions or [],
            "ideas": summary.ideas or [],
            "refs": summary.refs or []
        }
    finally:
        db.close()


@router.get("/{session_id}/status", response_model=SessionStatusResponse)
async def get_session_status(
    session_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get current session status and statistics"""
    try:
        status_data = await shadow_session_service.get_session_status(session_id)
        return SessionStatusResponse(**status_data)

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting session status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get session status")


@router.post("/{session_id}/pause")
async def pause_session(
    session_id: str,
    current_user: User = Depends(get_current_user)
):
    """Pause an active session"""
    try:
        session = await shadow_session_service.pause_session(session_id)
        return {
            "session_id": session.id,
            "status": session.status,
            "paused_at": session.paused_at.isoformat(),
            "message": "⏸️ Shadow session paused"
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error pausing session: {e}")
        raise HTTPException(status_code=500, detail="Failed to pause session")


@router.post("/{session_id}/resume")
async def resume_session(
    session_id: str,
    current_user: User = Depends(get_current_user)
):
    """Resume a paused session"""
    try:
        session = await shadow_session_service.resume_session(session_id)
        return {
            "session_id": session.id,
            "status": session.status,
            "resumed_at": session.resumed_at.isoformat(),
            "message": "▶️ Shadow session resumed"
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error resuming session: {e}")
        raise HTTPException(status_code=500, detail="Failed to resume session")


@router.post("/{session_id}/wrap")
async def wrap_session(
    session_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Wrap up session and generate summary
    This ends the session and triggers summary generation
    """
    try:
        # Wrap the session
        session = await shadow_session_service.wrap_session(session_id)

        # Generate summary
        summary = await shadow_summary_generator.generate_summary(session_id)

        return {
            "session_id": session.id,
            "status": session.status,
            "ended_at": session.ended_at.isoformat(),
            "summary": {
                "decisions": summary.decisions,
                "tasks": summary.tasks,
                "questions": summary.questions,
                "ideas": summary.ideas,
                "references": summary.refs,
                "timeline": summary.timeline,
                "changeset": summary.changeset,
                "full_text": summary.full_text
            },
            "message": "🎁 Shadow session wrapped and summary generated"
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error wrapping session: {e}")
        raise HTTPException(status_code=500, detail="Failed to wrap session")


@router.post("/{session_id}/commit")
async def commit_summary(
    session_id: str,
    request: SummaryCommitRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Commit edited summary to notes, reminders, and knowledge graph
    This is called after user reviews and edits the summary
    """
    try:
        db = SessionLocal()

        # Get session and summary
        session = db.query(ShadowSession).filter(ShadowSession.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        summary = db.query(ShadowSummary).filter(ShadowSummary.session_id == session_id).first()
        if not summary:
            raise HTTPException(status_code=404, detail="Summary not found")

        # Update summary with edited content
        summary.decisions = request.decisions
        summary.tasks = request.tasks
        summary.questions = request.questions
        summary.ideas = request.ideas
        summary.refs = request.refs

        # Create note with full summary
        note_content = f"# Shadow Session Summary\n\n"
        note_content += f"**Date:** {session.started_at.strftime('%Y-%m-%d %H:%M')}\n"
        if session.context:
            note_content += f"**Context:** {session.context}\n"
        note_content += f"\n"

        if request.decisions:
            note_content += f"## Decisions\n"
            for decision in request.decisions:
                note_content += f"- {decision}\n"
            note_content += f"\n"

        if request.tasks:
            note_content += f"## Tasks\n"
            for task in request.tasks:
                note_content += f"- {task.get('content', task)}\n"
            note_content += f"\n"

        if request.questions:
            note_content += f"## Questions\n"
            for question in request.questions:
                note_content += f"- {question}\n"
            note_content += f"\n"

        if request.ideas:
            note_content += f"## Ideas\n"
            for idea in request.ideas:
                note_content += f"- {idea}\n"
            note_content += f"\n"

        # Create note
        note = Note(
            user_id=current_user.id,
            title=f"Shadow: {session.context or 'Work Session'}",
            content=note_content
        )
        db.add(note)
        db.flush()

        # Create reminders for tasks with due dates
        reminders_created = []
        for task in request.tasks:
            if isinstance(task, dict) and task.get("due"):
                reminder = Reminder(
                    user_id=current_user.id,
                    text=task.get("content", str(task)),
                    due_at=datetime.fromisoformat(task["due"].replace("Z", "+00:00")),
                    status="scheduled"
                )
                db.add(reminder)
                reminders_created.append(reminder.text)

        # Mark summary as committed
        summary.committed = True
        summary.committed_note_id = note.id

        # Update session status
        session.status = "committed"

        db.commit()

        logger.info(f"✅ Committed Shadow session {session_id} to note {note.id} with {len(reminders_created)} reminders")

        return {
            "session_id": session_id,
            "status": "committed",
            "note_id": note.id,
            "reminders_created": len(reminders_created),
            "message": f"✅ Summary committed: {len(request.tasks)} tasks, {len(request.decisions)} decisions saved"
        }

    except Exception as e:
        logger.error(f"Error committing summary: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to commit summary")
    finally:
        db.close()


@router.get("/active")
async def get_active_session(current_user: User = Depends(get_current_user)):
    """Get user's current active or paused session"""
    try:
        session = await shadow_session_service.get_active_session(current_user.id)

        if not session:
            return {"active_session": None}

        status_data = await shadow_session_service.get_session_status(session.id)
        return {"active_session": status_data}

    except Exception as e:
        logger.error(f"Error getting active session: {e}")
        raise HTTPException(status_code=500, detail="Failed to get active session")


@router.get("/recent")
async def list_recent_sessions(
    limit: int = 10,
    current_user: User = Depends(get_current_user)
):
    """List user's recent Shadow sessions"""
    try:
        sessions = await shadow_session_service.list_recent_sessions(current_user.id, limit)

        return {
            "sessions": [
                {
                    "session_id": s.id,
                    "status": s.status,
                    "context": s.context,
                    "started_at": s.started_at.isoformat(),
                    "ended_at": s.ended_at.isoformat() if s.ended_at else None,
                    "duration_minutes": s.duration_minutes
                }
                for s in sessions
            ]
        }

    except Exception as e:
        logger.error(f"Error listing recent sessions: {e}")
        raise HTTPException(status_code=500, detail="Failed to list recent sessions")


# ===== Agent Download Endpoints =====

@router.get("/agent/download/windows")
async def download_windows_agent():
    """Download Windows PowerShell installer"""
    from fastapi.responses import FileResponse
    import os

    agent_file = "/home/david/jarvis/shadow-agent/install.ps1"

    if not os.path.exists(agent_file):
        raise HTTPException(status_code=404, detail="Windows installer not found")

    return FileResponse(
        path=agent_file,
        filename="sara-shadow-agent-install.ps1",
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename=sara-shadow-agent-install.ps1"
        }
    )


@router.get("/agent/download/macos")
async def download_macos_agent():
    """Download macOS/Linux bash installer"""
    from fastapi.responses import FileResponse
    import os

    agent_file = "/home/david/jarvis/shadow-agent/install.sh"

    if not os.path.exists(agent_file):
        raise HTTPException(status_code=404, detail="macOS installer not found")

    return FileResponse(
        path=agent_file,
        filename="sara-shadow-agent-install.sh",
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename=sara-shadow-agent-install.sh"
        }
    )


@router.get("/agent/info")
async def get_agent_info():
    """Get agent installation information"""
    return {
        "platforms": {
            "windows": {
                "name": "Windows Agent",
                "installer": "sara-shadow-agent-install.ps1",
                "download_url": "/shadow/agent/download/windows",
                "install_command": "powershell -ExecutionPolicy Bypass -File sara-shadow-agent-install.ps1",
                "requirements": ["Windows 10/11", "PowerShell", "Administrator access"],
                "features": ["Browser tracking (Chrome, Firefox, Edge, Brave, Opera)", "VS Code file tracking", "Auto-start on login"]
            },
            "macos": {
                "name": "macOS/Linux Agent",
                "installer": "sara-shadow-agent-install.sh",
                "download_url": "/shadow/agent/download/macos",
                "install_command": "bash sara-shadow-agent-install.sh [API_URL]",
                "requirements": ["macOS 10.14+ or Linux", "Python 3.8+", "Bash shell"],
                "features": ["Browser tracking (Chrome, Safari, Firefox, Brave, Edge)", "VS Code file tracking", "Auto-start via LaunchAgent/systemd"]
            }
        },
        "api_url": "http://10.185.1.180:8000",
        "documentation": "https://github.com/your-repo/shadow-agent"
    }
