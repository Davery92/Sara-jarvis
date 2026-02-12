"""Presence logging routes."""

import logging
import uuid
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Presence"])


async def log_presence(user_id: str, activity_type: str, platform: str = None, db: Session = None):
    """
    Log a presence/activity event for the user.
    Called from various endpoints to track when the user is active.
    """
    try:
        if db is None:
            from app.db.session import SessionLocal
            db = SessionLocal()
            close_db = True
        else:
            close_db = False

        try:
            db.execute(text("""
                INSERT INTO presence_log (id, user_id, activity_type, platform, created_at)
                VALUES (:id, :user_id, :activity_type, :platform, NOW())
            """), {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "activity_type": activity_type,
                "platform": platform
            })
            db.commit()
            logger.debug(f"Logged presence: {user_id} - {activity_type} ({platform})")
        finally:
            if close_db:
                db.close()

    except Exception as e:
        logger.error(f"Error logging presence: {e}")


@router.post("/api/presence")
async def log_presence_endpoint(
    data: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Log user presence/activity. Call this when app opens, resumes, or on significant actions.
    """
    activity_type = data.get("activity_type", "app_open")
    platform = data.get("platform", "unknown")

    await log_presence(current_user.id, activity_type, platform, db)

    return {"success": True, "message": "Presence logged"}
