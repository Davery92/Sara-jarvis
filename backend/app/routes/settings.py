"""
User Settings API Routes
Manage user preferences for vision, screenshots, desktop agent, etc.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.user_settings import UserSettings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class VisionSettingsUpdate(BaseModel):
    """Update vision model settings"""
    vision_model: Optional[str] = None
    vision_endpoint: Optional[str] = None


class ScreenshotSettingsUpdate(BaseModel):
    """Update screenshot settings"""
    screenshot_enabled: Optional[bool] = None
    screenshot_interval_seconds: Optional[int] = None
    screenshot_blur_sensitive: Optional[bool] = None


class DesktopAgentSettingsUpdate(BaseModel):
    """Update desktop agent settings"""
    wake_word_enabled: Optional[bool] = None
    activity_tracking_enabled: Optional[bool] = None
    cross_device_commands_enabled: Optional[bool] = None


class AllSettingsUpdate(BaseModel):
    """Update all settings at once"""
    vision_model: Optional[str] = None
    vision_endpoint: Optional[str] = None
    screenshot_enabled: Optional[bool] = None
    screenshot_interval_seconds: Optional[int] = None
    screenshot_blur_sensitive: Optional[bool] = None
    wake_word_enabled: Optional[bool] = None
    activity_tracking_enabled: Optional[bool] = None
    cross_device_commands_enabled: Optional[bool] = None
    preferences: Optional[dict] = None


def get_or_create_settings(db: Session, user_id: str) -> UserSettings:
    """Get user settings, creating default if not exists."""
    stmt = select(UserSettings).where(UserSettings.user_id == user_id)
    settings = db.execute(stmt).scalar_one_or_none()

    if not settings:
        import uuid
        settings = UserSettings(
            id=str(uuid.uuid4()),
            user_id=user_id
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)

    return settings


@router.get("")
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all user settings."""
    user_id = current_user.id
    settings = get_or_create_settings(db, user_id)
    return settings.to_dict()


@router.put("")
async def update_settings(
    updates: AllSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update user settings."""
    user_id = current_user.id
    settings = get_or_create_settings(db, user_id)

    # Update only provided fields
    update_data = updates.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if hasattr(settings, key):
            setattr(settings, key, value)

    db.commit()
    db.refresh(settings)

    logger.info(f"Settings updated for user {user_id}")
    return settings.to_dict()


@router.get("/vision")
async def get_vision_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get vision model settings."""
    user_id = current_user.id
    settings = get_or_create_settings(db, user_id)
    return {
        "vision_model": settings.vision_model,
        "vision_endpoint": settings.vision_endpoint
    }


@router.put("/vision")
async def update_vision_settings(
    updates: VisionSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update vision model settings."""
    user_id = current_user.id
    settings = get_or_create_settings(db, user_id)

    if updates.vision_model is not None:
        settings.vision_model = updates.vision_model
    if updates.vision_endpoint is not None:
        settings.vision_endpoint = updates.vision_endpoint

    db.commit()
    db.refresh(settings)

    logger.info(f"Vision settings updated for user {user_id}: model={settings.vision_model}")
    return {
        "vision_model": settings.vision_model,
        "vision_endpoint": settings.vision_endpoint
    }


@router.get("/screenshot")
async def get_screenshot_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get screenshot settings."""
    user_id = current_user.id
    settings = get_or_create_settings(db, user_id)
    return {
        "screenshot_enabled": settings.screenshot_enabled,
        "screenshot_interval_seconds": settings.screenshot_interval_seconds,
        "screenshot_blur_sensitive": settings.screenshot_blur_sensitive
    }


@router.put("/screenshot")
async def update_screenshot_settings(
    updates: ScreenshotSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update screenshot settings."""
    user_id = current_user.id
    settings = get_or_create_settings(db, user_id)

    if updates.screenshot_enabled is not None:
        settings.screenshot_enabled = updates.screenshot_enabled
    if updates.screenshot_interval_seconds is not None:
        settings.screenshot_interval_seconds = updates.screenshot_interval_seconds
    if updates.screenshot_blur_sensitive is not None:
        settings.screenshot_blur_sensitive = updates.screenshot_blur_sensitive

    db.commit()
    db.refresh(settings)

    return {
        "screenshot_enabled": settings.screenshot_enabled,
        "screenshot_interval_seconds": settings.screenshot_interval_seconds,
        "screenshot_blur_sensitive": settings.screenshot_blur_sensitive
    }


@router.get("/desktop-agent")
async def get_desktop_agent_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get desktop agent settings."""
    user_id = current_user.id
    settings = get_or_create_settings(db, user_id)
    return {
        "wake_word_enabled": settings.wake_word_enabled,
        "activity_tracking_enabled": settings.activity_tracking_enabled,
        "cross_device_commands_enabled": settings.cross_device_commands_enabled
    }


@router.put("/desktop-agent")
async def update_desktop_agent_settings(
    updates: DesktopAgentSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update desktop agent settings."""
    user_id = current_user.id
    settings = get_or_create_settings(db, user_id)

    if updates.wake_word_enabled is not None:
        settings.wake_word_enabled = updates.wake_word_enabled
    if updates.activity_tracking_enabled is not None:
        settings.activity_tracking_enabled = updates.activity_tracking_enabled
    if updates.cross_device_commands_enabled is not None:
        settings.cross_device_commands_enabled = updates.cross_device_commands_enabled

    db.commit()
    db.refresh(settings)

    return {
        "wake_word_enabled": settings.wake_word_enabled,
        "activity_tracking_enabled": settings.activity_tracking_enabled,
        "cross_device_commands_enabled": settings.cross_device_commands_enabled
    }
