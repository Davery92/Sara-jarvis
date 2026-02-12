"""Push notification token management routes."""
import logging
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

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


async def send_push_to_user(
    user_id: str,
    title: str,
    body: str,
    notification_data: dict = None,
    db: Session = None,
):
    """
    Send a push notification to all of a user's registered devices via Expo.
    Returns True if at least one device was notified, False otherwise.
    """
    try:
        # Get a database session if not provided
        if db is None:
            db = SessionLocal()
            close_db = True
        else:
            close_db = False

        try:
            # Get all active tokens for the user
            tokens = db.query(PushToken).filter(
                PushToken.user_id == user_id,
                PushToken.is_active == True,
            ).all()

            if not tokens:
                logger.info(f"No push tokens found for user {user_id}")
                return False

            # Prepare messages for Expo push API
            messages = []
            for token in tokens:
                messages.append({
                    "to": token.token,
                    "sound": "default",
                    "title": title,
                    "body": body,
                    "data": notification_data or {},
                    "priority": "high",
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
            logger.info(f"Sent push notification to {len(tokens)} devices for user {user_id}: {title}")
            return True

        finally:
            if close_db:
                db.close()

    except Exception as e:
        logger.error(f"Error sending push notification to user {user_id}: {e}")
        return False
