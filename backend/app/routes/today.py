from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.reminder import Reminder, Timer
from app.models.episode import Episode
from datetime import datetime, date
from typing import Dict, Any

router = APIRouter()

@router.get("/")
async def get_today_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get today's summary and schedule"""
    try:
        today = date.today()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())
        
        # Get today's reminders
        todays_reminders = db.query(Reminder).filter(
            Reminder.user_id == current_user.id,
            Reminder.due_at >= today_start,
            Reminder.due_at <= today_end,
            Reminder.status.in_(["scheduled", "pending"])
        ).all()
        
        # Get active timers
        active_timers = db.query(Timer).filter(
            Timer.user_id == current_user.id,
            Timer.status == "running"
        ).all()
        
        # Get today's episodes
        todays_episodes = db.query(Episode).filter(
            Episode.user_id == current_user.id,
            Episode.created_at >= today_start,
            Episode.created_at <= today_end
        ).count()
        
        return {
            "date": today.isoformat(),
            "reminders": [{
                "id": r.id,
                "text": r.text,
                "due_at": r.due_at.isoformat() if r.due_at else None,
                "status": r.status
            } for r in todays_reminders],
            "active_timers": [{
                "id": t.id,
                "label": t.label,
                "ends_at": t.ends_at.isoformat() if t.ends_at else None,
                "status": t.status
            } for t in active_timers],
            "episodes_today": todays_episodes,
            "summary": f"You have {len(todays_reminders)} reminders and {len(active_timers)} active timers today."
        }
        
    except Exception as e:
        return {
            "date": date.today().isoformat(),
            "reminders": [],
            "active_timers": [],
            "episodes_today": 0,
            "summary": "Welcome to your daily summary!"
        }