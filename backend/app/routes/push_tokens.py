"""Push notification token management routes."""
import logging
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.session import get_db, SessionLocal
from app.core.deps import get_current_user
from app.models.push_token import PushToken

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Push Tokens"])


class PushTokenRequest(BaseModel):
    token: str
    platform: str
    device_name: Optional[str] = None


@router.post("/api/push-tokens")
async def register_push_token(
    request: PushTokenRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Register or update a push notification token for the user's device
    """
    try:
        user_id = current_user.id

        # Check if token already exists
        existing_token = db.query(PushToken).filter(PushToken.token == request.token).first()

        if existing_token:
            # Update existing token
            existing_token.user_id = user_id
            existing_token.platform = request.platform
            existing_token.device_name = request.device_name
            existing_token.is_active = True
            existing_token.updated_at = datetime.now()

            # Keep one active token per named device/platform to prevent stale duplicates.
            if request.device_name:
                db.query(PushToken).filter(
                    PushToken.user_id == user_id,
                    PushToken.platform == request.platform,
                    PushToken.device_name == request.device_name,
                    PushToken.token != request.token,
                    PushToken.is_active == True,
                ).update(
                    {"is_active": False, "updated_at": datetime.now()},
                    synchronize_session=False,
                )
            db.commit()
            logger.info(f"Updated push token for user {user_id}: {request.token[:20]}...")
            return {"success": True, "message": "Push token updated"}
        else:
            # Create new token
            new_token = PushToken(
                user_id=user_id,
                token=request.token,
                platform=request.platform,
                device_name=request.device_name,
                is_active=True,
            )
            db.add(new_token)

            if request.device_name:
                db.query(PushToken).filter(
                    PushToken.user_id == user_id,
                    PushToken.platform == request.platform,
                    PushToken.device_name == request.device_name,
                    PushToken.token != request.token,
                    PushToken.is_active == True,
                ).update(
                    {"is_active": False, "updated_at": datetime.now()},
                    synchronize_session=False,
                )

            db.commit()
            logger.info(f"Registered new push token for user {user_id}: {request.token[:20]}...")
            return {"success": True, "message": "Push token registered"}

    except Exception as e:
        logger.error(f"Error registering push token: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to register push token: {str(e)}")


@router.get("/api/push-tokens")
async def get_push_tokens(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Get all registered push tokens for the current user
    """
    try:
        user_id = current_user.id
        tokens = db.query(PushToken).filter(
            PushToken.user_id == user_id,
            PushToken.is_active == True,
        ).all()

        return [{
            "id": t.id,
            "token": t.token[:20] + "..." if len(t.token) > 20 else t.token,
            "platform": t.platform,
            "device_name": t.device_name,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        } for t in tokens]

    except Exception as e:
        logger.error(f"Error getting push tokens: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get push tokens: {str(e)}")


@router.delete("/api/push-tokens/{token_id}")
async def delete_push_token(
    token_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Deactivate a push token
    """
    try:
        user_id = current_user.id
        token = db.query(PushToken).filter(
            PushToken.id == token_id,
            PushToken.user_id == user_id,
        ).first()

        if not token:
            raise HTTPException(status_code=404, detail="Push token not found")

        token.is_active = False
        db.commit()

        return {"success": True, "message": "Push token deactivated"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting push token: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete push token: {str(e)}")


@router.post("/api/push-notifications/send")
async def send_push_notification(
    data: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Send a push notification to a user's devices (for testing or internal use).
    Uses Expo's push notification service.
    """
    try:
        user_id = data.get("user_id", current_user.id)
        title = data.get("title", "Sara")
        body = data.get("body", "")
        notification_data = data.get("data", {})

        # Get all active tokens for the user
        tokens = db.query(PushToken).filter(
            PushToken.user_id == user_id,
            PushToken.is_active == True,
        ).all()

        if not tokens:
            return {"success": False, "message": "No push tokens found for user"}

        # Prepare messages for Expo push API
        messages = []
        for token in tokens:
            messages.append({
                "to": token.token,
                "sound": "default",
                "title": title,
                "body": body,
                "data": notification_data,
            })

        # Send to Expo push notification service
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://exp.host/--/api/v2/push/send",
                json=messages,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip, deflate",
                    "Content-Type": "application/json",
                },
            )

        result = response.json()
        logger.info(f"Sent push notification to {len(tokens)} devices: {result}")

        return {
            "success": True,
            "devices_notified": len(tokens),
            "result": result,
        }

    except Exception as e:
        logger.error(f"Error sending push notification: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send push notification: {str(e)}")


class NotificationFeedbackRequest(BaseModel):
    action: str  # "read", "engaged", "dismissed"
    response_text: Optional[str] = None


@router.post("/api/notifications/{notification_id}/feedback")
async def notification_feedback(
    notification_id: int,
    request: NotificationFeedbackRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Record user interaction with a notification.
    Actions: read (user saw it), engaged (user clicked/replied), dismissed (user swiped away).
    """
    action = request.action
    if action not in ("read", "engaged", "dismissed"):
        raise HTTPException(status_code=400, detail="action must be 'read', 'engaged', or 'dismissed'")

    try:
        user_id = current_user.id

        # Verify the notification belongs to this user
        row = db.execute(text("""
            SELECT id FROM notification_log
            WHERE id = :id AND user_id = :user_id
        """), {"id": notification_id, "user_id": user_id}).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Notification not found")

        if action == "read":
            db.execute(text("""
                UPDATE notification_log
                SET read_at = COALESCE(read_at, NOW())
                WHERE id = :id
            """), {"id": notification_id})
        elif action == "engaged":
            db.execute(text("""
                UPDATE notification_log
                SET read_at = COALESCE(read_at, NOW()),
                    engaged = TRUE,
                    response_text = COALESCE(:response_text, response_text)
                WHERE id = :id
            """), {"id": notification_id, "response_text": request.response_text})
        elif action == "dismissed":
            db.execute(text("""
                UPDATE notification_log
                SET dismissed_at = COALESCE(dismissed_at, NOW())
                WHERE id = :id
            """), {"id": notification_id})

        db.commit()
        logger.info(f"Notification {notification_id} feedback: {action} by user {user_id}")
        return {"success": True, "notification_id": notification_id, "action": action}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error recording notification feedback: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to record feedback: {str(e)}")


@router.get("/api/notifications/engagement-stats")
async def get_notification_engagement_stats(
    days: int = 7,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Get per-category notification engagement statistics.
    Returns sent, engaged, dismissed, and ignored counts for the last N days.
    """
    try:
        user_id = current_user.id
        window_days = max(1, min(days, 90))

        rows = db.execute(text("""
            SELECT
                category,
                COUNT(*)::int AS sent,
                COUNT(*) FILTER (WHERE engaged = TRUE)::int AS engaged,
                COUNT(*) FILTER (WHERE dismissed_at IS NOT NULL)::int AS dismissed,
                COUNT(*) FILTER (WHERE read_at IS NOT NULL)::int AS read,
                COUNT(*) FILTER (
                    WHERE engaged = FALSE
                      AND dismissed_at IS NULL
                      AND read_at IS NULL
                )::int AS ignored
            FROM notification_log
            WHERE user_id = :user_id
              AND sent = TRUE
              AND sent_at >= NOW() - MAKE_INTERVAL(days => :days)
            GROUP BY category
            ORDER BY sent DESC
        """), {"user_id": user_id, "days": window_days}).fetchall()

        stats = []
        for r in rows:
            sent = r[1]
            engaged = r[2]
            engagement_rate = round(engaged / sent, 2) if sent > 0 else 0.0
            stats.append({
                "category": r[0],
                "sent": sent,
                "engaged": engaged,
                "dismissed": r[3],
                "read": r[4],
                "ignored": r[5],
                "engagement_rate": engagement_rate,
            })

        return {"stats": stats, "window_days": window_days}

    except Exception as e:
        logger.error(f"Error getting engagement stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get engagement stats: {str(e)}")


@router.get("/api/push-tokens/diagnostics")
async def get_push_token_diagnostics(
    hours: int = 1,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Investigate duplicate push behavior for current user.
    Returns:
    - active token inventory
    - duplicate token groups by platform/device_name
    - repeated sent notifications in the requested window
    """
    try:
        window_hours = max(1, min(hours, 24))
        user_id = current_user.id

        tokens = db.query(PushToken).filter(
            PushToken.user_id == user_id,
            PushToken.is_active == True,
        ).order_by(PushToken.platform, PushToken.device_name, PushToken.updated_at.desc()).all()

        token_rows = [{
            "id": t.id,
            "platform": t.platform,
            "device_name": t.device_name,
            "token_preview": t.token[:20] + "..." if len(t.token) > 20 else t.token,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        } for t in tokens]

        grouped: dict[str, int] = {}
        for t in tokens:
            key = f"{t.platform}:{t.device_name or 'unknown'}"
            grouped[key] = grouped.get(key, 0) + 1
        duplicate_token_groups = [
            {"device": key, "active_tokens": count}
            for key, count in grouped.items()
            if count > 1
        ]

        repeated_notifications = []
        repeated_topics = []
        try:
            notif_rows = db.execute(text("""
                SELECT title, message, category, source,
                       COUNT(*)::int AS send_count,
                       MIN(sent_at) AS first_sent_at,
                       MAX(sent_at) AS last_sent_at
                FROM notification_log
                WHERE user_id = :user_id
                  AND sent = TRUE
                  AND sent_at >= NOW() - MAKE_INTERVAL(hours => :hours)
                GROUP BY title, message, category, source
                HAVING COUNT(*) > 1
                ORDER BY send_count DESC, last_sent_at DESC
                LIMIT 50
            """), {"user_id": user_id, "hours": window_hours}).fetchall()
            for r in notif_rows:
                repeated_notifications.append({
                    "title": r[0],
                    "message": r[1],
                    "category": r[2],
                    "source": r[3],
                    "send_count": r[4],
                    "first_sent_at": r[5].isoformat() if r[5] else None,
                    "last_sent_at": r[6].isoformat() if r[6] else None,
                })

            topic_rows = db.execute(text("""
                SELECT topic, category,
                       COUNT(*)::int AS send_count,
                       MIN(sent_at) AS first_sent_at,
                       MAX(sent_at) AS last_sent_at
                FROM notification_log
                WHERE user_id = :user_id
                  AND sent = TRUE
                  AND sent_at >= NOW() - MAKE_INTERVAL(hours => :hours)
                GROUP BY topic, category
                HAVING COUNT(*) > 1
                ORDER BY send_count DESC, last_sent_at DESC
                LIMIT 50
            """), {"user_id": user_id, "hours": window_hours}).fetchall()
            for r in topic_rows:
                repeated_topics.append({
                    "topic": r[0],
                    "category": r[1],
                    "send_count": r[2],
                    "first_sent_at": r[3].isoformat() if r[3] else None,
                    "last_sent_at": r[4].isoformat() if r[4] else None,
                })
        except Exception as e:
            logger.warning(f"Push diagnostics could not query notification_log: {e}")

        return {
            "success": True,
            "window_hours": window_hours,
            "active_token_count": len(token_rows),
            "duplicate_token_groups": duplicate_token_groups,
            "active_tokens": token_rows,
            "repeated_notifications": repeated_notifications,
            "repeated_topics": repeated_topics,
        }
    except Exception as e:
        logger.error(f"Error building push diagnostics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to build diagnostics: {str(e)}")


async def send_push_to_user(
    user_id: str,
    title: str,
    body: str,
    notification_data: dict = None,
    db: Session = None,
):
    """
    Send a push notification through the unified notification pipeline.
    This preserves topic-based dedupe and notification_log observability.
    """
    try:
        # Get a database session if not provided
        if db is None:
            db = SessionLocal()
            close_db = True
        else:
            close_db = False

        try:
            payload = notification_data or {}
            category = str(payload.get("type") or "general").lower()

            dedupe_key = payload.get("topic")
            if not dedupe_key:
                import hashlib
                fingerprint = hashlib.sha256(
                    f"{category}:{title.strip()}:{body.strip()}".lower().encode("utf-8")
                ).hexdigest()[:16]
                dedupe_key = f"{category}:{fingerprint}"

            from app.services.unified_notification import send_notification as unified_send_notification

            result = await unified_send_notification(
                user_id=user_id,
                title=title,
                message=body,
                priority="high",
                topic=dedupe_key,
                category=category,
                source=str(payload.get("source") or "push_tokens_route"),
                cooldown_hours=payload.get("cooldown_hours"),
                db=db,
                _bypass_attention=True,
            )

            if close_db:
                db.commit()

            if result.get("sent"):
                logger.info(f"Sent unified push notification for user {user_id}: {title}")
                return True
            logger.info(
                f"Push notification suppressed for user {user_id}: "
                f"reason={result.get('reason')} topic={result.get('topic')}"
            )
            return False

        finally:
            if close_db:
                db.close()

    except Exception as e:
        logger.error(f"Error sending push notification to user {user_id}: {e}")
        return False
