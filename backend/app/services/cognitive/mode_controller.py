"""
Mode Controller for Sara's cognitive architecture.

Manages the ambient/active mode states that control how Sara's
sensory systems process input. Mode affects:
- Screenshot capture frequency (10s active vs 60s ambient)
- Attention level for notifications
- Memory consolidation priority

Uses Redis for low-latency state and pub/sub for mode changes.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from app.core.timezone import now as local_now
from enum import Enum

import redis

logger = logging.getLogger(__name__)


class Mode(str, Enum):
    """Sara's attention modes."""
    AMBIENT = "ambient"  # Background monitoring, low activity
    ACTIVE = "active"    # Direct engagement, high attention


class ModeController:
    """
    Central controller for Sara's attention mode.

    The mode affects how input is processed:
    - AMBIENT: Low-frequency screen captures, relaxed attention
    - ACTIVE: High-frequency captures, focused attention

    Mode transitions:
    - AMBIENT -> ACTIVE: Wake word, explicit engagement, urgent notification
    - ACTIVE -> AMBIENT: Silence timeout, goodbye, extended idle
    """

    # Redis key patterns
    KEY_CURRENT = "mode:{user_id}:current"
    KEY_ENTERED_AT = "mode:{user_id}:entered_at"
    KEY_REASON = "mode:{user_id}:reason"
    KEY_METADATA = "mode:{user_id}:metadata"

    # Pub/sub channel for mode changes
    CHANNEL_MODE = "sara:mode:{user_id}"

    # Timeouts
    ACTIVE_TIMEOUT_SECONDS = 300  # 5 minutes of silence -> ambient
    WAKE_WORD_ACTIVE_DURATION = 60  # Wake word triggers 60s of active mode

    def __init__(self, redis_url: Optional[str] = None):
        """Initialize the mode controller."""
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://redis:6379/0")
        self._redis: Optional[redis.Redis] = None
        self._pubsub: Optional[redis.client.PubSub] = None

    @property
    def redis(self) -> redis.Redis:
        """Lazy initialization of Redis client."""
        if self._redis is None:
            from app.core.redis import get_redis_sync
            self._redis = get_redis_sync()
        return self._redis

    def _key(self, pattern: str, user_id: str) -> str:
        """Format a Redis key with user_id."""
        return pattern.format(user_id=user_id)

    async def get_mode(self, user_id: str) -> Mode:
        """
        Get the current mode for a user.

        Returns AMBIENT if no mode is set.
        """
        try:
            mode_str = self.redis.get(self._key(self.KEY_CURRENT, user_id))
            if mode_str and mode_str in [m.value for m in Mode]:
                return Mode(mode_str)
            return Mode.AMBIENT
        except Exception as e:
            logger.error(f"Failed to get mode: {e}")
            return Mode.AMBIENT

    async def get_mode_info(self, user_id: str) -> Dict[str, Any]:
        """
        Get detailed mode information.

        Returns:
            Dict with mode, entered_at, reason, duration_seconds
        """
        try:
            pipe = self.redis.pipeline()
            pipe.get(self._key(self.KEY_CURRENT, user_id))
            pipe.get(self._key(self.KEY_ENTERED_AT, user_id))
            pipe.get(self._key(self.KEY_REASON, user_id))
            pipe.get(self._key(self.KEY_METADATA, user_id))
            results = pipe.execute()

            mode_str, entered_at_str, reason, metadata_str = results

            mode = Mode(mode_str) if mode_str else Mode.AMBIENT
            entered_at = datetime.fromisoformat(entered_at_str) if entered_at_str else None
            metadata = json.loads(metadata_str) if metadata_str else {}

            duration_seconds = None
            if entered_at:
                duration_seconds = (local_now() - entered_at).total_seconds()

            return {
                "mode": mode.value,
                "entered_at": entered_at.isoformat() if entered_at else None,
                "reason": reason,
                "duration_seconds": duration_seconds,
                "metadata": metadata
            }

        except Exception as e:
            logger.error(f"Failed to get mode info: {e}")
            return {
                "mode": Mode.AMBIENT.value,
                "entered_at": None,
                "reason": None,
                "duration_seconds": None,
                "metadata": {}
            }

    async def set_mode(
        self,
        user_id: str,
        mode: Mode,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None,
        ttl_seconds: Optional[int] = None
    ) -> bool:
        """
        Set the current mode for a user.

        Args:
            user_id: User identifier
            mode: New mode to set
            reason: Why the mode changed (for logging/debugging)
            metadata: Additional context
            ttl_seconds: Auto-expire after this duration (for active mode timeout)

        Returns:
            True if mode changed, False if it was already this mode
        """
        try:
            current_mode = await self.get_mode(user_id)

            # Skip if already in this mode (but update TTL if provided)
            if current_mode == mode:
                if ttl_seconds:
                    self.redis.expire(
                        self._key(self.KEY_CURRENT, user_id),
                        ttl_seconds
                    )
                return False

            now = local_now()

            # Set mode state atomically
            pipe = self.redis.pipeline()
            pipe.set(self._key(self.KEY_CURRENT, user_id), mode.value)
            pipe.set(self._key(self.KEY_ENTERED_AT, user_id), now.isoformat())
            pipe.set(self._key(self.KEY_REASON, user_id), reason)

            if metadata:
                pipe.set(self._key(self.KEY_METADATA, user_id), json.dumps(metadata))

            # Set TTL if specified (e.g., active mode auto-expires)
            if ttl_seconds:
                pipe.expire(self._key(self.KEY_CURRENT, user_id), ttl_seconds)
                pipe.expire(self._key(self.KEY_ENTERED_AT, user_id), ttl_seconds)
                pipe.expire(self._key(self.KEY_REASON, user_id), ttl_seconds)
                if metadata:
                    pipe.expire(self._key(self.KEY_METADATA, user_id), ttl_seconds)

            pipe.execute()

            # Publish mode change event
            await self._publish_mode_change(user_id, mode, reason, metadata)

            logger.info(f"Mode changed: {current_mode.value} -> {mode.value} ({reason})")
            return True

        except Exception as e:
            logger.error(f"Failed to set mode: {e}")
            return False

    async def _publish_mode_change(
        self,
        user_id: str,
        mode: Mode,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Publish mode change to Redis pub/sub channel."""
        try:
            channel = self._key(self.CHANNEL_MODE, user_id)
            message = json.dumps({
                "mode": mode.value,
                "reason": reason,
                "timestamp": local_now().isoformat(),
                "metadata": metadata or {}
            })
            self.redis.publish(channel, message)
            logger.debug(f"Published mode change to {channel}")

        except Exception as e:
            logger.error(f"Failed to publish mode change: {e}")

    # ==================== Mode Transition Handlers ====================

    async def handle_wake_word(self, user_id: str) -> bool:
        """
        Handle wake word detection.

        Transitions to ACTIVE mode with auto-timeout.
        """
        return await self.set_mode(
            user_id=user_id,
            mode=Mode.ACTIVE,
            reason="wake_word",
            ttl_seconds=self.ACTIVE_TIMEOUT_SECONDS
        )

    async def handle_user_engagement(self, user_id: str, source: str = "chat") -> bool:
        """
        Handle explicit user engagement (chat message, voice command).

        Transitions to ACTIVE mode and refreshes timeout.
        """
        return await self.set_mode(
            user_id=user_id,
            mode=Mode.ACTIVE,
            reason=f"user_engagement:{source}",
            ttl_seconds=self.ACTIVE_TIMEOUT_SECONDS
        )

    async def handle_silence_timeout(self, user_id: str) -> bool:
        """
        Handle silence/idle timeout.

        Transitions to AMBIENT mode.
        """
        return await self.set_mode(
            user_id=user_id,
            mode=Mode.AMBIENT,
            reason="silence_timeout"
        )

    async def handle_goodbye(self, user_id: str) -> bool:
        """
        Handle explicit goodbye/end of conversation.

        Transitions to AMBIENT mode.
        """
        return await self.set_mode(
            user_id=user_id,
            mode=Mode.AMBIENT,
            reason="goodbye"
        )

    async def handle_urgent_notification(
        self,
        user_id: str,
        notification_type: str
    ) -> bool:
        """
        Handle urgent notification that requires attention.

        Transitions to ACTIVE mode briefly.
        """
        return await self.set_mode(
            user_id=user_id,
            mode=Mode.ACTIVE,
            reason=f"urgent_notification:{notification_type}",
            metadata={"notification_type": notification_type},
            ttl_seconds=60  # Brief attention window
        )

    # ==================== Mode Subscription ====================

    async def subscribe_mode_changes(self, user_id: str):
        """
        Subscribe to mode changes for a user.

        Yields mode change events as they occur.
        This is an async generator for use in services that need
        to react to mode changes (e.g., screenshot service).
        """
        channel = self._key(self.CHANNEL_MODE, user_id)

        self._pubsub = self.redis.pubsub()
        self._pubsub.subscribe(channel)

        logger.info(f"Subscribed to mode changes on {channel}")

        try:
            for message in self._pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        yield data
                    except json.JSONDecodeError:
                        continue
        finally:
            self._pubsub.unsubscribe(channel)
            self._pubsub.close()

    def get_screenshot_interval(self, mode: Mode) -> int:
        """
        Get the recommended screenshot interval for a mode.

        Args:
            mode: Current attention mode

        Returns:
            Screenshot interval in seconds
        """
        if mode == Mode.ACTIVE:
            return 10  # High frequency during active engagement
        else:
            return 60  # Low frequency during ambient monitoring


# ==================== Singleton Access ====================

_mode_controller: Optional[ModeController] = None


def get_mode_controller() -> ModeController:
    """Get the singleton ModeController instance."""
    global _mode_controller
    if _mode_controller is None:
        _mode_controller = ModeController()
    return _mode_controller
