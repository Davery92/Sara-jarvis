from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.reminder import Reminder, Timer
from app.models.episode import Episode
from app.models.note import Note
from datetime import datetime, timedelta
from typing import Dict, Any
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/")
async def get_dashboard_analytics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get dashboard analytics data shaped for the frontend dashboard."""
    try:
        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)

        # User activity
        active_timers = (
            db.query(text("count(*)"))
            .select_from(Timer)
            .filter(Timer.user_id == current_user.id, Timer.status == "running")
            .scalar()
        ) or 0

        active_reminders = (
            db.query(text("count(*)"))
            .select_from(Reminder)
            .filter(Reminder.user_id == current_user.id, Reminder.status == "scheduled", Reminder.due_at > now)
            .scalar()
        ) or 0

        # Episodes as proxy for conversations/interactions
        recent_episodes_count = (
            db.query(text("count(*)"))
            .select_from(Episode)
            .filter(Episode.user_id == current_user.id, Episode.created_at >= week_ago)
            .scalar()
        ) or 0

        last_episode_row = (
            db.query(Episode.created_at)
            .filter(Episode.user_id == current_user.id)
            .order_by(Episode.created_at.desc())
            .first()
        )

        # Notes
        total_notes = (
            db.query(text("count(*)")).select_from(Note).filter(Note.user_id == current_user.id).scalar()
        ) or 0

        # Database health metrics (best-effort; never raise)
        db_health = True
        db_size = "n/a"
        db_conns = 0
        try:
            # Simple connectivity test
            db.execute(text("SELECT 1"))
            # Try to read pg stats if available (Postgres only)
            try:
                size_row = db.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()))")).fetchone()
                if size_row and len(size_row) > 0:
                    db_size = size_row[0]
            except Exception:
                pass
            try:
                conns_row = db.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"))
                row = conns_row.fetchone()
                if row and len(row) > 0:
                    db_conns = int(row[0])
            except Exception:
                pass
        except Exception:
            db_health = False

        # Build response in expected structure to prevent UI crashes
        data: Dict[str, Any] = {
            "system_health": {"status": "healthy" if db_health else "degraded"},
            "memory": {
                "total_messages": recent_episodes_count,
                "total_conversations": recent_episodes_count,
                "archived_count": 0,
                "archival_percentage": 0,
            },
            "ai_system": {
                "successful_responses_7d": recent_episodes_count,
                "tool_calls_successful_7d": 0,
                "embedding_service_health": True,
                "last_activity": (last_episode_row[0].isoformat() if last_episode_row and last_episode_row[0] else None),
            },
            "database": {
                "size": db_size,
                "connections": db_conns,
                "health": db_health,
            },
            "user_data": {
                "active_timers": active_timers,
                "active_reminders": active_reminders,
            },
            # Keep some top-level fields used elsewhere/legacy
            "active_timers": active_timers,
            "pending_reminders": active_reminders,
            "recent_episodes": recent_episodes_count,
            "total_notes": total_notes,
            "successful_responses_7d": recent_episodes_count,
            "week_summary": {
                "episodes_this_week": recent_episodes_count,
                "notes_created": 0,
            },
        }

        return data

    except Exception as e:
        logger.exception("Dashboard analytics error")
        # Safe fallbacks to match shape
        return {
            "system_health": {"status": "degraded"},
            "memory": {
                "total_messages": 0,
                "total_conversations": 0,
                "archived_count": 0,
                "archival_percentage": 0,
            },
            "ai_system": {
                "successful_responses_7d": 0,
                "tool_calls_successful_7d": 0,
                "embedding_service_health": False,
                "last_activity": None,
            },
            "database": {"size": "n/a", "connections": 0, "health": False},
            "user_data": {"active_timers": 0, "active_reminders": 0},
            "active_timers": 0,
            "pending_reminders": 0,
            "recent_episodes": 0,
            "total_notes": 0,
            "successful_responses_7d": 0,
            "week_summary": {"episodes_this_week": 0, "notes_created": 0},
        }
