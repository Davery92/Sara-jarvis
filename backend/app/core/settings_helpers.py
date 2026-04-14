"""User settings helpers extracted from main_simple.py."""

from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from app.core.app_state import get_app_state

_DEFAULT_USER_SETTINGS = {
    "theme": "dark",
    "notifications_enabled": True,
    "reminder_notifications": True,
    "email_notifications": False,
    "default_reminder_time": 540,
    "language": "en",
    "timezone": "America/New_York",
}


def get_or_create_user_settings_row(db: Session, user_id: str):
    from app.models.user_settings import UserSettings as UserSettingsModel

    settings_row = db.query(UserSettingsModel).filter(
        UserSettingsModel.user_id == str(user_id)
    ).first()
    if settings_row:
        return settings_row

    settings_row = UserSettingsModel(user_id=str(user_id), preferences={})
    db.add(settings_row)
    db.commit()
    db.refresh(settings_row)
    return settings_row


def merged_user_settings(preferences: Optional[dict]) -> dict:
    merged = dict(_DEFAULT_USER_SETTINGS)
    if isinstance(preferences, dict):
        merged.update(preferences)
    merged["assistant_name"] = get_app_state().assistant_name
    return merged
