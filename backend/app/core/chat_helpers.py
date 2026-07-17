"""Chat helper functions extracted from main_simple.py.

Timezone resolution, message overlap detection, and other utilities
used by the chat/stream route.
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional, Any, List
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _is_valid_timezone_name(timezone_name: str) -> bool:
    """Validate an IANA timezone name."""
    if not isinstance(timezone_name, str) or not timezone_name.strip():
        return False
    try:
        ZoneInfo(timezone_name.strip())
        return True
    except Exception:
        return False


def _extract_profile_timezone(profile_data: Any) -> Optional[str]:
    """Extract timezone from user_profile.profile_data variants."""
    if not isinstance(profile_data, dict):
        return None

    candidates = [
        profile_data.get("timezone"),
        profile_data.get("time_zone"),
        profile_data.get("timezone_location"),
    ]

    for value in candidates:
        if isinstance(value, dict):
            value = value.get("value") or value.get("timezone")
        if isinstance(value, str) and value.strip():
            return value.strip()

    return None


def _resolve_user_timezone_for_prompt(db: Session, user_id: str) -> str:
    """
    Resolve per-user timezone for prompt rendering.
    Precedence:
    1) reflection_settings.timezone
    2) user_profile.profile_data timezone fields
    3) TZ env var
    4) America/New_York fallback
    """
    fallback = os.getenv("TZ", "America/New_York")
    if not _is_valid_timezone_name(fallback):
        fallback = "America/New_York"

    if not user_id:
        return fallback

    try:
        tz_row = db.execute(
            text("SELECT timezone FROM reflection_settings WHERE user_id = :uid LIMIT 1"),
            {"uid": user_id},
        ).fetchone()
        reflection_tz = tz_row[0] if tz_row else None
        if isinstance(reflection_tz, str) and _is_valid_timezone_name(reflection_tz):
            return reflection_tz
    except Exception as e:
        logger.debug(f"Prompt timezone reflection_settings lookup failed for {user_id}: {e}")
        try:
            db.rollback()
        except Exception:
            pass

    try:
        profile_row = db.execute(
            text("SELECT profile_data FROM user_profile WHERE user_id = :uid LIMIT 1"),
            {"uid": user_id},
        ).fetchone()
        profile_tz = _extract_profile_timezone(profile_row[0] if profile_row else {})
        if isinstance(profile_tz, str) and _is_valid_timezone_name(profile_tz):
            return profile_tz
    except Exception as e:
        logger.debug(f"Prompt timezone user_profile lookup failed for {user_id}: {e}")
        try:
            db.rollback()
        except Exception:
            pass

    return fallback


def _resolve_prompt_datetime_for_user(db: Session, user_id: str) -> datetime:
    """Get timezone-aware current datetime for this specific user."""
    timezone_name = _resolve_user_timezone_for_prompt(db, user_id)
    try:
        return datetime.now(ZoneInfo(timezone_name))
    except Exception:
        return datetime.now(ZoneInfo("America/New_York"))


def _message_role_content_signature(message: Any) -> tuple[str, str]:
    """Normalize message into a comparable (role, content) signature."""
    if isinstance(message, dict):
        role = str(message.get("role", ""))
        content = message.get("content", "")
    else:
        role = str(getattr(message, "role", ""))
        content = getattr(message, "content", "")

    if isinstance(content, str):
        normalized_content = " ".join(content.split())
    else:
        try:
            normalized_content = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        except Exception:
            normalized_content = str(content)

    return role, normalized_content


def _compute_message_overlap(existing_messages: List[Any], incoming_messages: List[Any]) -> int:
    """
    Find the largest overlap where suffix(existing) == prefix(incoming).
    Used to avoid duplicate history injection.
    """
    if not existing_messages or not incoming_messages:
        return 0

    max_overlap = min(len(existing_messages), len(incoming_messages))
    for overlap_size in range(max_overlap, 0, -1):
        is_match = True
        for i in range(overlap_size):
            existing_sig = _message_role_content_signature(
                existing_messages[len(existing_messages) - overlap_size + i]
            )
            incoming_sig = _message_role_content_signature(incoming_messages[i])
            if existing_sig != incoming_sig:
                is_match = False
                break
        if is_match:
            return overlap_size

    return 0


