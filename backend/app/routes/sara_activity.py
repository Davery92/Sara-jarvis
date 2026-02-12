"""
Sara Activity Timeline Endpoint

Returns a unified timeline of Sara's autonomous activity:
- Agent run logs (heartbeat runs, actions taken)
- Notification logs (what was sent, deduped)
- Journal entries (inner monologue)
"""

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.session import get_db
from app.core.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sara-activity"])


@router.get("/api/sara/activity")
async def get_activity(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    hours: int = Query(24, ge=1, le=168, description="Hours of history to return"),
    limit: int = Query(50, ge=1, le=200),
    activity_type: str = Query(None, description="Filter by type: heartbeat, notification, journal")
):
    """
    Get unified timeline of Sara's autonomous activity.
    Merges agent_run_log, notification_log, and sara_journal into a single timeline.
    """
    user_id = str(current_user.id)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    activities = []

    try:
        # 1. Agent run logs (heartbeat runs)
        if not activity_type or activity_type == "heartbeat":
            runs = db.execute(text("""
                SELECT id, source, context_summary, actions_taken,
                       observations, watching_for, run_duration_ms, created_at
                FROM agent_run_log
                WHERE user_id = :uid AND created_at >= :since
                ORDER BY created_at DESC
                LIMIT :lim
            """), {"uid": user_id, "since": since, "lim": limit}).fetchall()

            for run in runs:
                activities.append({
                    "id": str(run.id),
                    "timestamp": run.created_at.isoformat() if run.created_at else None,
                    "type": "heartbeat",
                    "agent_type": run.source,
                    "summary": (run.context_summary or "")[:300],
                    "details": {
                        "actions": run.actions_taken,
                        "observations": run.observations,
                        "watching_for": run.watching_for,
                        "duration_ms": run.run_duration_ms,
                    }
                })

        # 2. Notification logs
        if not activity_type or activity_type == "notification":
            notifications = db.execute(text("""
                SELECT id, topic, category, title, message, priority,
                       source, sent, dedup_blocked, created_at
                FROM notification_log
                WHERE user_id = :uid AND created_at >= :since
                ORDER BY created_at DESC
                LIMIT :lim
            """), {"uid": user_id, "since": since, "lim": limit}).fetchall()

            for notif in notifications:
                activities.append({
                    "id": str(notif.id),
                    "timestamp": notif.created_at.isoformat() if notif.created_at else None,
                    "type": "notification",
                    "summary": f"{'Sent' if notif.sent else 'Deduped'}: {notif.title or notif.topic}",
                    "details": {
                        "topic": notif.topic,
                        "category": notif.category,
                        "title": notif.title,
                        "message": notif.message,
                        "priority": notif.priority,
                        "source": notif.source,
                        "sent": notif.sent,
                        "dedup_blocked": notif.dedup_blocked,
                    }
                })

        # 3. Journal entries (inner monologue)
        if not activity_type or activity_type == "journal":
            entries = db.execute(text("""
                SELECT id, content, emotional_state, entry_type,
                       observations, watching_for, created_at
                FROM sara_journal
                WHERE user_id = :uid AND created_at >= :since
                ORDER BY created_at DESC
                LIMIT :lim
            """), {"uid": user_id, "since": since, "lim": limit}).fetchall()

            for entry in entries:
                activities.append({
                    "id": str(entry.id),
                    "timestamp": entry.created_at.isoformat() if entry.created_at else None,
                    "type": "journal",
                    "summary": (entry.content or "")[:200],
                    "details": {
                        "emotional_state": entry.emotional_state,
                        "entry_type": entry.entry_type,
                        "observations": entry.observations,
                        "watching_for": entry.watching_for,
                        "full_content": entry.content,
                    }
                })

        # Sort by timestamp descending
        activities.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        # Apply final limit
        activities = activities[:limit]

    except Exception as e:
        logger.error(f"Sara activity endpoint error: {e}")
        return {"activities": [], "total": 0, "period_hours": hours, "error": str(e)}

    return {
        "activities": activities,
        "total": len(activities),
        "period_hours": hours
    }
