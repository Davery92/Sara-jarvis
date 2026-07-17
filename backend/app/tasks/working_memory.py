"""
Working memory tasks for Sara's cognitive architecture.

Working memory is Sara's conscious scratchpad - what she's actively aware of.
These tasks manage refresh, cleanup, and capacity enforcement.
"""

import logging
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from zoneinfo import ZoneInfo

from app.celery_app import celery_app
from app.core.config import settings
from app.core.timezone import now as local_now
from app.db.base import SessionLocal
from app.models.profile import ReflectionSettings, UserProfile

logger = logging.getLogger(__name__)

_timezone_cache: Dict[str, Dict[str, Any]] = {}
_timezone_cache_ttl = timedelta(minutes=10)


def _is_valid_timezone(timezone_name: str) -> bool:
    try:
        ZoneInfo(timezone_name)
        return True
    except Exception:
        return False


def _extract_profile_timezone(profile_data: Dict[str, Any]) -> Optional[str]:
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


def resolve_user_timezone(user_id: str) -> str:
    """
    Resolve timezone with precedence:
    1) reflection_settings.timezone
    2) user_profile.profile_data timezone fields
    3) global settings.timezone
    """
    fallback = settings.timezone if _is_valid_timezone(settings.timezone) else "UTC"
    if not user_id:
        return fallback

    now = local_now()
    cached = _timezone_cache.get(user_id)
    if cached:
        fetched_at = cached.get("fetched_at")
        if isinstance(fetched_at, datetime) and (now - fetched_at) < _timezone_cache_ttl:
            tz = cached.get("timezone")
            if isinstance(tz, str) and _is_valid_timezone(tz):
                return tz

    timezone_name = fallback
    db = SessionLocal()
    try:
        reflection_tz = db.query(ReflectionSettings.timezone).filter(
            ReflectionSettings.user_id == user_id
        ).scalar()
        if isinstance(reflection_tz, str) and _is_valid_timezone(reflection_tz):
            timezone_name = reflection_tz
        else:
            profile_row = db.query(UserProfile.profile_data).filter(
                UserProfile.user_id == user_id
            ).first()
            if profile_row:
                profile_timezone = _extract_profile_timezone(profile_row[0] or {})
                if profile_timezone and _is_valid_timezone(profile_timezone):
                    timezone_name = profile_timezone
    except Exception as e:
        logger.debug(f"Failed to resolve timezone for user {user_id}: {e}")
    finally:
        db.close()

    _timezone_cache[user_id] = {"timezone": timezone_name, "fetched_at": now}
    return timezone_name


@celery_app.task(bind=True, name="app.tasks.working_memory.refresh_context")
def refresh_context(self) -> Dict[str, Any]:
    """
    Refresh working memory with latest consolidated context.
    Runs every 60 seconds.
    """
    import redis

    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    r = redis.from_url(redis_url)
    solo_user_id = os.getenv("SOLO_USER_ID", "")

    result = {
        "timestamp": local_now().isoformat(),
        "status": "running",
        "context_segments": 0,
        "user_state_updated": False
    }

    try:
        # Get current context from consolidation
        context_key = f"working_memory:{solo_user_id}:context"
        context_data = r.get(context_key)

        if context_data:
            context = json.loads(context_data)
            result["context_segments"] = len(context.get("segments", []))

        # Update user state inference
        user_state = infer_user_state(r, solo_user_id)
        user_state_key = f"working_memory:{solo_user_id}:user_state"
        r.setex(user_state_key, 3600, json.dumps(user_state))
        result["user_state_updated"] = True
        result["user_state"] = user_state

        # Update system state
        system_state = get_system_state(r)
        system_state_key = f"working_memory:{solo_user_id}:system_state"
        r.setex(system_state_key, 3600, json.dumps(system_state))

        # Apply capacity limits across all working memory
        apply_capacity_limits(r, solo_user_id)

        result["status"] = "completed"

    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
        logger.error(f"Working memory refresh failed: {e}")

    return result


@celery_app.task(bind=True, name="app.tasks.working_memory.cleanup_expired")
def cleanup_expired(self) -> Dict[str, Any]:
    """
    Clean up expired entries from raw buffer and working memory.
    Enforces TTL on all ephemeral data.
    """
    import redis

    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    r = redis.from_url(redis_url)

    result = {
        "timestamp": local_now().isoformat(),
        "streams_trimmed": {},
        "total_entries_removed": 0
    }

    try:
        # Trim raw buffer streams (keep 48 hours)
        max_age_ms = 48 * 60 * 60 * 1000  # 48 hours in milliseconds
        cutoff_ms = int((local_now().timestamp() * 1000) - max_age_ms)

        streams = ["raw_buffer:text", "raw_buffer:screen", "raw_buffer:notification",
                   "raw_buffer:calendar", "raw_buffer:environmental"]

        for stream in streams:
            try:
                # Get stream info
                info = r.xinfo_stream(stream)
                before_len = info.get("length", 0)

                # Trim entries older than cutoff
                # XTRIM with MINID removes entries with ID less than specified
                r.xtrim(stream, minid=f"{cutoff_ms}-0")

                info_after = r.xinfo_stream(stream)
                after_len = info_after.get("length", 0)

                removed = before_len - after_len
                result["streams_trimmed"][stream] = {
                    "before": before_len,
                    "after": after_len,
                    "removed": removed
                }
                result["total_entries_removed"] += removed

            except redis.exceptions.ResponseError:
                # Stream doesn't exist
                result["streams_trimmed"][stream] = {"status": "not_exists"}

        # Trim consolidation discard log (keep 7 days worth)
        try:
            max_discard_age_ms = 7 * 24 * 60 * 60 * 1000
            discard_cutoff_ms = int((local_now().timestamp() * 1000) - max_discard_age_ms)
            r.xtrim("consolidation:discard_log", minid=f"{discard_cutoff_ms}-0")
        except redis.exceptions.ResponseError:
            pass

        result["status"] = "completed"
        logger.info(f"Cleanup completed: {result['total_entries_removed']} entries removed")

    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
        logger.error(f"Cleanup failed: {e}")

    return result


def infer_user_state(r, user_id: str) -> Dict[str, Any]:
    """
    Infer the user's current state from available signals.
    """
    from app.core.timezone import now as local_now
    now = local_now()

    # Default state
    state = {
        "inferred_activity": "unknown",
        "availability": "unknown",
        "location": "unknown",
        "last_interaction": None,
        "confidence": 0.5,
        "inferred_at": now.isoformat()
    }

    try:
        # Check last interaction time
        last_interaction_key = f"user:{user_id}:last_interaction"
        last_interaction = r.get(last_interaction_key)

        if last_interaction:
            last_time = datetime.fromisoformat(last_interaction.decode())
            state["last_interaction"] = last_time.isoformat()

            # Infer availability from recency
            time_since = now - last_time

            if time_since < timedelta(minutes=5):
                state["availability"] = "active"
                state["confidence"] = 0.9
            elif time_since < timedelta(minutes=30):
                state["availability"] = "available"
                state["confidence"] = 0.7
            elif time_since < timedelta(hours=2):
                state["availability"] = "away"
                state["confidence"] = 0.6
            else:
                state["availability"] = "inactive"
                state["confidence"] = 0.5

        # Check time of day for activity inference using per-user timezone.
        try:
            user_timezone = resolve_user_timezone(user_id)
            local_hour = datetime.now(ZoneInfo(user_timezone)).hour
            state["timezone"] = user_timezone
        except Exception:
            user_timezone = settings.timezone if _is_valid_timezone(settings.timezone) else "UTC"
            local_hour = now.hour
            state["timezone"] = user_timezone

        if 0 <= local_hour < 6:
            state["inferred_activity"] = "sleeping"
            state["availability"] = "sleeping"
        elif 6 <= local_hour < 9:
            state["inferred_activity"] = "morning_routine"
        elif 9 <= local_hour < 17:
            state["inferred_activity"] = "working"
        elif 17 <= local_hour < 22:
            state["inferred_activity"] = "evening"
        else:
            state["inferred_activity"] = "winding_down"

        # Check for any calendar events (from raw buffer)
        # This would indicate specific activities
        try:
            calendar_entries = r.xrevrange("raw_buffer:calendar", count=5)
            if calendar_entries:
                # Most recent calendar event might indicate current activity
                for entry_id, data in calendar_entries:
                    content = data.get(b"content", b"").decode()
                    if "meeting" in content.lower():
                        state["inferred_activity"] = "in_meeting"
                        state["availability"] = "busy"
                        break
        except Exception:
            pass

    except Exception as e:
        logger.warning(f"Error inferring user state: {e}")

    return state


def get_system_state(r) -> Dict[str, Any]:
    """
    Get current system state for working memory.
    """
    state = {
        "last_consolidation": None,
        "buffer_health": "unknown",
        "active_workers": [],
        "updated_at": local_now().isoformat()
    }

    try:
        # Get last consolidation time
        last_run = r.get("consolidation:last_run")
        if last_run:
            state["last_consolidation"] = last_run.decode()

            # Check if consolidation is keeping up
            last_time = datetime.fromisoformat(last_run.decode())
            age = local_now() - last_time

            if age < timedelta(minutes=2):
                state["buffer_health"] = "healthy"
            elif age < timedelta(minutes=5):
                state["buffer_health"] = "lagging"
            else:
                state["buffer_health"] = "stale"
        else:
            state["buffer_health"] = "not_started"

        # Get health status
        health_data = r.get("system:health_status")
        if health_data:
            health = json.loads(health_data)
            state["overall_health"] = health.get("overall_status", "unknown")

    except Exception as e:
        logger.warning(f"Error getting system state: {e}")

    return state


def apply_capacity_limits(r, user_id: str):
    """
    Apply capacity limits to working memory structures.
    Evicts low-priority items when limits exceeded.
    """
    limits = {
        "context_segments": 50,
        "active_threads": 10,
        "pending_actions": 20
    }

    try:
        # Check context segments
        context_key = f"working_memory:{user_id}:context"
        context_data = r.get(context_key)

        if context_data:
            context = json.loads(context_data)
            segments = context.get("segments", [])

            if len(segments) > limits["context_segments"]:
                # Sort by relevance and keep top segments
                sorted_segments = sorted(
                    segments,
                    key=lambda s: s.get("relevance_score", 0),
                    reverse=True
                )
                context["segments"] = sorted_segments[:limits["context_segments"]]
                r.setex(context_key, 3600, json.dumps(context))

        # Check active threads
        threads_key = f"working_memory:{user_id}:threads"
        threads_count = r.zcard(threads_key)

        if threads_count > limits["active_threads"]:
            # Remove oldest threads
            excess = threads_count - limits["active_threads"]
            r.zpopmin(threads_key, excess)

        # Check pending actions
        actions_key = f"working_memory:{user_id}:actions"
        actions_count = r.zcard(actions_key)

        if actions_count > limits["pending_actions"]:
            # Remove lowest priority actions
            excess = actions_count - limits["pending_actions"]
            r.zpopmin(actions_key, excess)

    except Exception as e:
        logger.warning(f"Error applying capacity limits: {e}")
