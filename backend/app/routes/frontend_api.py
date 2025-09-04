from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.reminder import Reminder, Timer
from app.models.note import Note
from sqlalchemy import desc
from datetime import datetime, timezone
from typing import List, Dict, Any

router = APIRouter()

@router.post("/sprite/telemetry")
async def sprite_telemetry():
    """Accept sprite telemetry pings (no-op)."""
    # Intentionally do nothing; helps keep client console clean.
    return {"status": "ok"}

@router.get("/timers")
async def get_timers_simple(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get timers in simple array format for frontend"""
    try:
        timers = db.query(Timer).filter(
            Timer.user_id == current_user.id
        ).order_by(Timer.created_at.desc()).all()
        
        return [{
            "id": timer.id,
            "label": timer.label or "Timer",
            "ends_at": timer.ends_at.isoformat() if timer.ends_at else None,
            "end_time": timer.ends_at.isoformat() if timer.ends_at else None,  # Alternative field name
            "status": timer.status,
            "is_active": timer.status == "running",
            "title": timer.label or "Timer"
        } for timer in timers]
        
    except Exception as e:
        return []

@router.get("/reminders")
async def get_reminders_simple(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get reminders in simple array format for frontend"""
    try:
        reminders = db.query(Reminder).filter(
            Reminder.user_id == current_user.id
        ).order_by(Reminder.due_at).all()
        
        return [{
            "id": reminder.id,
            "text": reminder.text,
            "title": reminder.text,  # Alternative field name
            "due_at": reminder.due_at.isoformat() if reminder.due_at else None,
            "reminder_time": reminder.due_at.isoformat() if reminder.due_at else None,  # Alternative field name
            "status": reminder.status,
            "created_at": reminder.created_at.isoformat() if reminder.created_at else None
        } for reminder in reminders]
        
    except Exception as e:
        return []

@router.get("/notes")  
async def get_notes_simple(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get notes in simple array format for frontend"""
    try:
        notes = db.query(Note).filter(
            Note.user_id == current_user.id
        ).order_by(desc(Note.updated_at)).limit(50).all()
        
        return [{
            "id": note.id,
            "title": note.title or "Untitled",
            "content": note.content,
            "created_at": note.created_at.isoformat() if note.created_at else None,
            "updated_at": note.updated_at.isoformat() if note.updated_at else None,
            "folder_id": note.folder_id
        } for note in notes]
        
    except Exception as e:
        return []
