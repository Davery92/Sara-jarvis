"""
User Settings API Routes
Manage user preferences for vision, screenshots, desktop agent, notification preferences, etc.
"""
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select, text

from app.core.deps import get_current_user
from app.core.config import settings as app_settings
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


class AutonomyFlagsResponse(BaseModel):
    autonomy_traces_enabled: bool
    autonomy_structured_plan: bool
    autonomy_policy_engine: bool
    autonomy_attention_enabled: bool
    autonomy_missions_enabled: bool
    autonomy_policy_candidates_enabled: bool
    automation_admin_configured: bool
    automation_admin_email_count: int
    automation_admin_role_count: int


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


@router.get("/autonomy-flags", response_model=AutonomyFlagsResponse)
async def get_autonomy_flags(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Read-only visibility for autonomy rollout flags and admin gate configuration."""
    admin_emails = [
        email.strip()
        for email in (app_settings.automation_admin_emails or "").split(",")
        if email.strip()
    ]
    admin_role_count = 0
    try:
        row = db.execute(text("""
            SELECT COUNT(*)::int
            FROM app_user_role
            WHERE role IN ('admin', 'owner')
        """)).fetchone()
        admin_role_count = (row[0] if row else 0) or 0
    except Exception:
        # Role table may not exist yet on older deployments.
        admin_role_count = 0

    return AutonomyFlagsResponse(
        autonomy_traces_enabled=app_settings.autonomy_traces_enabled,
        autonomy_structured_plan=app_settings.autonomy_structured_plan,
        autonomy_policy_engine=app_settings.autonomy_policy_engine,
        autonomy_attention_enabled=app_settings.autonomy_attention_enabled,
        autonomy_missions_enabled=app_settings.autonomy_missions_enabled,
        autonomy_policy_candidates_enabled=app_settings.autonomy_policy_candidates_enabled,
        automation_admin_configured=len(admin_emails) > 0 or admin_role_count > 0,
        automation_admin_email_count=len(admin_emails),
        automation_admin_role_count=admin_role_count,
    )



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


# ─── Notification Preferences ────────────────────────────────────


class NotificationPrefItem(BaseModel):
    category: str
    enabled: bool
    custom_ban_phrases: List[str] = []


class NotificationPrefsResponse(BaseModel):
    preferences: List[NotificationPrefItem]


class NotificationPrefsUpdate(BaseModel):
    preferences: List[NotificationPrefItem]


# Default categories seeded if none exist for a user
_DEFAULT_CATEGORIES = [
    ("health", False),
    ("fitness", False),
    ("calendar", True),
    ("email", True),
    ("security", True),
    ("home", True),
    ("general", True),
]


@router.get("/notification-preferences", response_model=NotificationPrefsResponse)
async def get_notification_preferences(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all notification category preferences for the current user."""
    user_id = current_user.id

    try:
        rows = db.execute(text("""
            SELECT category, enabled, custom_ban_phrases
            FROM notification_preference
            WHERE user_id = :user_id
            ORDER BY category
        """), {"user_id": user_id}).fetchall()
    except Exception:
        # Table may not exist yet
        rows = []

    # If no rows, seed defaults
    if not rows:
        for cat, enabled in _DEFAULT_CATEGORIES:
            enabled_str = "TRUE" if enabled else "FALSE"
            try:
                db.execute(text("""
                    INSERT INTO notification_preference (user_id, category, enabled, custom_ban_phrases)
                    VALUES (:user_id, :category, :enabled, '[]'::jsonb)
                    ON CONFLICT (user_id, category) DO NOTHING
                """), {"user_id": user_id, "category": cat, "enabled": enabled})
            except Exception:
                pass
        db.commit()

        try:
            rows = db.execute(text("""
                SELECT category, enabled, custom_ban_phrases
                FROM notification_preference
                WHERE user_id = :user_id
                ORDER BY category
            """), {"user_id": user_id}).fetchall()
        except Exception:
            rows = []

    prefs = []
    for row in rows:
        phrases = row.custom_ban_phrases if isinstance(row.custom_ban_phrases, list) else []
        prefs.append(NotificationPrefItem(
            category=row.category,
            enabled=row.enabled,
            custom_ban_phrases=phrases,
        ))

    return NotificationPrefsResponse(preferences=prefs)


@router.put("/notification-preferences", response_model=NotificationPrefsResponse)
async def update_notification_preferences(
    body: NotificationPrefsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update notification category preferences (toggle categories, add custom ban phrases)."""
    import json
    user_id = current_user.id

    for pref in body.preferences:
        enabled_str = "TRUE" if pref.enabled else "FALSE"
        phrases_json = json.dumps(pref.custom_ban_phrases or [])
        try:
            db.execute(text("""
                INSERT INTO notification_preference (user_id, category, enabled, custom_ban_phrases, updated_at)
                VALUES (:user_id, :category, :enabled, CAST(:phrases AS jsonb), NOW())
                ON CONFLICT (user_id, category)
                DO UPDATE SET enabled = :enabled,
                             custom_ban_phrases = CAST(:phrases AS jsonb),
                             updated_at = NOW()
            """), {
                "user_id": user_id,
                "category": pref.category,
                "enabled": pref.enabled,
                "phrases": phrases_json,
            })
        except Exception as e:
            logger.error(f"Failed to upsert notification_preference: {e}")
            raise HTTPException(status_code=500, detail="Failed to update notification preferences")

    db.commit()

    # Invalidate the in-memory cache so the notification pipeline picks up changes immediately
    try:
        from app.services.unified_notification import invalidate_notification_pref_cache
        invalidate_notification_pref_cache(user_id)
    except Exception:
        pass

    # Return updated preferences
    return await get_notification_preferences(current_user=current_user, db=db)
