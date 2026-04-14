"""
ACS State Machine — 4-state machine for autonomous cognition lifecycle.

States:
  AUTONOMOUS   — Agent loop running on VM
  PAUSING      — Graceful interrupt in progress
  CONVERSATIONAL — David is chatting, agent fully stopped
  COOLDOWN     — Buffer after David disengages
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import redis.asyncio as aioredis

from app.core.timezone import now as local_now
from app.services.event_bus import emit_event, EventType

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Redis keys
STATE_KEY = "sara:acs:state:{user_id}"
COOLDOWN_UNTIL_KEY = "sara:acs:cooldown_until:{user_id}"
ACTIVE_SESSION_KEY = "sara:acs:active_session:{user_id}"
NOTES_FOLDER_KEY = "sara:acs:notes_folder_id:{user_id}"
ACS_MODEL_KEY = "sara:acs:model_id:{user_id}"
ACS_COOLDOWN_MINUTES_KEY = "sara:acs:cooldown_minutes:{user_id}"
ACS_MAX_DURATION_KEY = "sara:acs:max_duration_minutes:{user_id}"
CHAT_ACTIVE_KEY = "sara:acs:chat_active:{user_id}"
CHAT_ACTIVE_TTL_SECONDS = 120  # Flag expires after 2 min of no chat messages
# Defaults
DEFAULT_COOLDOWN_MINUTES = 2  # Minimal buffer — Sara runs continuously
DEFAULT_MAX_DURATION_MINUTES = 60
DEFAULT_IDLE_TRIGGER_MINUTES = 30  # Start autonomy after 30 min idle
DEFAULT_MODEL_ID = "Qwen3.5-122B-A10B"


class ACSState:
    AUTONOMOUS = "autonomous"
    PAUSING = "pausing"
    CONVERSATIONAL = "conversational"
    COOLDOWN = "cooldown"


# Valid state transitions
VALID_TRANSITIONS = {
    ACSState.AUTONOMOUS: {ACSState.PAUSING, ACSState.COOLDOWN, ACSState.CONVERSATIONAL},
    ACSState.PAUSING: {ACSState.CONVERSATIONAL, ACSState.COOLDOWN},
    ACSState.CONVERSATIONAL: {ACSState.COOLDOWN, ACSState.AUTONOMOUS},
    ACSState.COOLDOWN: {ACSState.AUTONOMOUS, ACSState.CONVERSATIONAL},
    # Allow starting from no state
    None: {ACSState.AUTONOMOUS, ACSState.CONVERSATIONAL, ACSState.COOLDOWN},
}


async def _get_redis() -> aioredis.Redis:
    return await aioredis.from_url(REDIS_URL, decode_responses=True)


async def _close_redis(r):
    """Compat close for redis.asyncio (aclose in >=5.x, close in older)."""
    if hasattr(r, 'aclose'):
        await r.aclose()
    else:
        await r.close()


async def get_state(user_id: str) -> Optional[str]:
    r = await _get_redis()
    try:
        return await r.get(STATE_KEY.format(user_id=user_id))
    finally:
        await _close_redis(r)


async def set_state(user_id: str, new_state: str, reason: str = "") -> bool:
    """Transition to a new state. Returns True if transition was valid."""
    r = await _get_redis()
    try:
        current = await r.get(STATE_KEY.format(user_id=user_id))

        allowed = VALID_TRANSITIONS.get(current, set())
        if new_state not in allowed:
            logger.warning(
                f"ACS invalid transition: {current} → {new_state} (reason: {reason})"
            )
            return False

        await r.set(STATE_KEY.format(user_id=user_id), new_state)

        logger.info(f"ACS state: {current} → {new_state} (reason: {reason})")

        try:
            await emit_event(
                event_type=EventType.ACS_STATE_CHANGED,
                user_id=user_id,
                payload={
                    "previous_state": current,
                    "new_state": new_state,
                    "reason": reason,
                },
                source="acs_state_machine",
            )
        except Exception as e:
            logger.debug(f"Failed to emit ACS state change event: {e}")

        return True
    finally:
        await _close_redis(r)


async def on_chat_started(user_id: str) -> bool:
    """Called when David starts chatting. Pauses ACS if running."""
    current = await get_state(user_id)

    if current == ACSState.AUTONOMOUS:
        return await set_state(user_id, ACSState.PAUSING, reason="chat_started")
    elif current == ACSState.COOLDOWN:
        return await set_state(user_id, ACSState.CONVERSATIONAL, reason="chat_started")
    elif current == ACSState.PAUSING:
        # Already pausing
        return True

    return False


async def on_chat_ended(user_id: str) -> bool:
    """Called when David stops chatting. Starts cooldown + extracts curiosities."""
    current = await get_state(user_id)
    if current != ACSState.CONVERSATIONAL:
        return False

    cooldown_minutes = await get_cooldown_minutes(user_id)
    r = await _get_redis()
    try:
        until = local_now() + timedelta(minutes=cooldown_minutes)
        await r.set(
            COOLDOWN_UNTIL_KEY.format(user_id=user_id),
            until.isoformat(),
        )
    finally:
        await _close_redis(r)

    result = await set_state(user_id, ACSState.COOLDOWN, reason="chat_ended")

    # Fire-and-forget curiosity extraction from the conversation
    if result:
        try:
            from app.tasks.acs import extract_conversation_curiosities
            extract_conversation_curiosities.apply_async(
                args=[user_id],
                queue="cognitive",
                expires=300,
            )
        except Exception as e:
            logger.debug(f"Failed to queue curiosity extraction: {e}")

    return result


async def signal_chat_active(user_id: str) -> None:
    """Set a short-lived flag indicating David is actively chatting.

    Unlike on_chat_started(), this does NOT pause/stop the ACS session.
    The ACS turn loop checks this flag and adds extra backoff between
    turns to yield LLM capacity to the interactive chat.
    """
    r = await _get_redis()
    try:
        await r.set(
            CHAT_ACTIVE_KEY.format(user_id=user_id),
            "1",
            ex=CHAT_ACTIVE_TTL_SECONDS,
        )
        logger.debug(f"ACS: chat_active flag set for {user_id} (TTL={CHAT_ACTIVE_TTL_SECONDS}s)")
    finally:
        await _close_redis(r)


async def is_chat_active(user_id: str) -> bool:
    """Check if David is actively chatting (recent message within TTL window)."""
    r = await _get_redis()
    try:
        return bool(await r.get(CHAT_ACTIVE_KEY.format(user_id=user_id)))
    finally:
        await _close_redis(r)


async def is_cooldown_expired(user_id: str) -> bool:
    r = await _get_redis()
    try:
        until_str = await r.get(COOLDOWN_UNTIL_KEY.format(user_id=user_id))
        if not until_str:
            return True
        until = datetime.fromisoformat(until_str)
        return local_now() >= until
    finally:
        await _close_redis(r)


async def get_active_session_id(user_id: str) -> Optional[str]:
    r = await _get_redis()
    try:
        return await r.get(ACTIVE_SESSION_KEY.format(user_id=user_id))
    finally:
        await _close_redis(r)


async def set_active_session(user_id: str, session_id: Optional[str]):
    r = await _get_redis()
    try:
        key = ACTIVE_SESSION_KEY.format(user_id=user_id)
        if session_id:
            await r.set(key, session_id)
        else:
            await r.delete(key)
    finally:
        await _close_redis(r)


async def get_notes_folder_id(user_id: str) -> Optional[str]:
    r = await _get_redis()
    try:
        return await r.get(NOTES_FOLDER_KEY.format(user_id=user_id))
    finally:
        await _close_redis(r)


async def set_notes_folder_id(user_id: str, folder_id: str):
    r = await _get_redis()
    try:
        await r.set(NOTES_FOLDER_KEY.format(user_id=user_id), folder_id)
    finally:
        await _close_redis(r)


# ── Settings helpers ──

async def get_model_id(user_id: str) -> str:
    r = await _get_redis()
    try:
        val = await r.get(ACS_MODEL_KEY.format(user_id=user_id))
        return val or DEFAULT_MODEL_ID
    finally:
        await _close_redis(r)


async def set_model_id(user_id: str, model_id: str):
    r = await _get_redis()
    try:
        await r.set(ACS_MODEL_KEY.format(user_id=user_id), model_id)
    finally:
        await _close_redis(r)


async def get_cooldown_minutes(user_id: str) -> int:
    r = await _get_redis()
    try:
        val = await r.get(ACS_COOLDOWN_MINUTES_KEY.format(user_id=user_id))
        return int(val) if val else DEFAULT_COOLDOWN_MINUTES
    finally:
        await _close_redis(r)


async def set_cooldown_minutes(user_id: str, minutes: int):
    r = await _get_redis()
    try:
        await r.set(ACS_COOLDOWN_MINUTES_KEY.format(user_id=user_id), str(minutes))
    finally:
        await _close_redis(r)


async def get_max_duration_minutes(user_id: str) -> int:
    r = await _get_redis()
    try:
        val = await r.get(ACS_MAX_DURATION_KEY.format(user_id=user_id))
        return int(val) if val else DEFAULT_MAX_DURATION_MINUTES
    finally:
        await _close_redis(r)


async def set_max_duration_minutes(user_id: str, minutes: int):
    r = await _get_redis()
    try:
        await r.set(ACS_MAX_DURATION_KEY.format(user_id=user_id), str(minutes))
    finally:
        await _close_redis(r)


async def get_full_status(user_id: str) -> dict:
    """Get complete ACS status for API response."""
    r = await _get_redis()
    try:
        state = await r.get(STATE_KEY.format(user_id=user_id))
        session_id = await r.get(ACTIVE_SESSION_KEY.format(user_id=user_id))
        cooldown_until = await r.get(COOLDOWN_UNTIL_KEY.format(user_id=user_id))
        model_id = await r.get(ACS_MODEL_KEY.format(user_id=user_id))
        cooldown_min = await r.get(ACS_COOLDOWN_MINUTES_KEY.format(user_id=user_id))
        max_dur = await r.get(ACS_MAX_DURATION_KEY.format(user_id=user_id))
        return {
            "state": state or ACSState.CONVERSATIONAL,
            "active_session_id": session_id,
            "cooldown_until": cooldown_until,
            "model_id": model_id or DEFAULT_MODEL_ID,
            "cooldown_minutes": int(cooldown_min) if cooldown_min else DEFAULT_COOLDOWN_MINUTES,
            "max_duration_minutes": int(max_dur) if max_dur else DEFAULT_MAX_DURATION_MINUTES,
        }
    finally:
        await _close_redis(r)
