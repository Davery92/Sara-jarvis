"""
Redis Pub/Sub event system for real-time rating updates.

Publishes rating events to Redis channels for WebSocket broadcasting and
other real-time subscribers.
"""

import redis.asyncio as redis
import json
from typing import Dict, Any, Optional, Callable, Awaitable
from datetime import datetime
import logging
import asyncio

logger = logging.getLogger(__name__)


# Channel names
CHANNEL_EPISODE_RATED = "sara:episode:rated"
CHANNEL_RATING_UPDATED = "sara:rating:updated"
CHANNEL_RATING_SYNCED = "sara:rating:synced"


class RatingEventPublisher:
    """Publishes rating events to Redis Pub/Sub channels."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        """
        Initialize publisher.

        Args:
            redis_url: Redis connection URL
        """
        self.redis_url = redis_url
        self._client: Optional[redis.Redis] = None

    @property
    def client(self) -> redis.Redis:
        """Get Redis client (lazy initialization)."""
        if not self._client:
            self._client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
        return self._client

    async def close(self):
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None

    async def publish_episode_rated(
        self,
        episode_id: str,
        user_id: str,
        rating: int,
        net_score: int,
        rating_count: int,
        average_rating: float,
        session_id: Optional[str] = None
    ) -> int:
        """
        Publish an episode_rated event.

        Args:
            episode_id: Episode UUID
            user_id: User UUID
            rating: New rating value (1-5)
            net_score: Current net score
            rating_count: Total rating count
            average_rating: Average rating
            session_id: Optional session ID

        Returns:
            Number of subscribers that received the message
        """
        event = {
            "type": "episode_rated",
            "episode_id": episode_id,
            "user_id": user_id,
            "rating": rating,
            "net_score": net_score,
            "rating_count": rating_count,
            "average_rating": average_rating,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if session_id:
            event["session_id"] = session_id

        try:
            subscribers = await self.client.publish(
                CHANNEL_EPISODE_RATED,
                json.dumps(event)
            )
            logger.info(f"Published episode_rated event for {episode_id} to {subscribers} subscribers")
            return subscribers
        except Exception as e:
            logger.error(f"Failed to publish episode_rated event: {e}")
            return 0

    async def publish_rating_updated(
        self,
        episode_id: str,
        user_id: str,
        old_rating: Optional[int],
        new_rating: int,
        net_score: int
    ) -> int:
        """
        Publish a rating_updated event (when user changes their rating).

        Args:
            episode_id: Episode UUID
            user_id: User UUID
            old_rating: Previous rating value (or None if first rating)
            new_rating: New rating value (1-5)
            net_score: Updated net score

        Returns:
            Number of subscribers that received the message
        """
        event = {
            "type": "rating_updated",
            "episode_id": episode_id,
            "user_id": user_id,
            "old_rating": old_rating,
            "new_rating": new_rating,
            "net_score": net_score,
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            subscribers = await self.client.publish(
                CHANNEL_RATING_UPDATED,
                json.dumps(event)
            )
            logger.debug(f"Published rating_updated event for {episode_id}")
            return subscribers
        except Exception as e:
            logger.error(f"Failed to publish rating_updated event: {e}")
            return 0

    async def publish_rating_synced(
        self,
        episode_ids: list[str],
        success_count: int,
        error_count: int
    ) -> int:
        """
        Publish a rating_synced event (after nightly consolidation).

        Args:
            episode_ids: List of synced episode IDs
            success_count: Number of successful syncs
            error_count: Number of failed syncs

        Returns:
            Number of subscribers that received the message
        """
        event = {
            "type": "rating_synced",
            "episode_ids": episode_ids,
            "success_count": success_count,
            "error_count": error_count,
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            subscribers = await self.client.publish(
                CHANNEL_RATING_SYNCED,
                json.dumps(event)
            )
            logger.info(f"Published rating_synced event ({success_count} synced, {error_count} errors)")
            return subscribers
        except Exception as e:
            logger.error(f"Failed to publish rating_synced event: {e}")
            return 0


class RatingEventSubscriber:
    """Subscribes to rating events from Redis Pub/Sub channels."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        """
        Initialize subscriber.

        Args:
            redis_url: Redis connection URL
        """
        self.redis_url = redis_url
        self._client: Optional[redis.Redis] = None
        self._pubsub: Optional[redis.client.PubSub] = None
        self._handlers: Dict[str, Callable[[Dict[str, Any]], Awaitable[None]]] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None

    @property
    def client(self) -> redis.Redis:
        """Get Redis client (lazy initialization)."""
        if not self._client:
            self._client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
        return self._client

    async def close(self):
        """Close Redis connection and stop subscriber."""
        await self.stop()
        if self._pubsub:
            await self._pubsub.close()
            self._pubsub = None
        if self._client:
            await self._client.close()
            self._client = None

    def register_handler(
        self,
        channel: str,
        handler: Callable[[Dict[str, Any]], Awaitable[None]]
    ):
        """
        Register a handler function for a channel.

        Args:
            channel: Channel name (e.g., CHANNEL_EPISODE_RATED)
            handler: Async function to handle events: async def handler(event: Dict)
        """
        self._handlers[channel] = handler
        logger.info(f"Registered handler for channel: {channel}")

    async def subscribe(self, channels: list[str]):
        """
        Subscribe to one or more channels.

        Args:
            channels: List of channel names to subscribe to
        """
        if not self._pubsub:
            self._pubsub = self.client.pubsub()

        await self._pubsub.subscribe(*channels)
        logger.info(f"Subscribed to channels: {channels}")

    async def start(self):
        """Start listening for messages (non-blocking)."""
        if self._running:
            logger.warning("Subscriber already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._listen())
        logger.info("Rating event subscriber started")

    async def stop(self):
        """Stop listening for messages."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Rating event subscriber stopped")

    async def _listen(self):
        """Internal message listening loop."""
        if not self._pubsub:
            logger.error("Cannot listen: not subscribed to any channels")
            return

        logger.info("Starting to listen for rating events...")

        try:
            async for message in self._pubsub.listen():
                if not self._running:
                    break

                if message["type"] != "message":
                    continue

                channel = message["channel"]
                data = message["data"]

                # Parse JSON event
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse event from {channel}: {data}")
                    continue

                # Call registered handler
                handler = self._handlers.get(channel)
                if handler:
                    try:
                        await handler(event)
                    except Exception as e:
                        logger.error(f"Handler error for {channel}: {e}", exc_info=True)
                else:
                    logger.debug(f"No handler registered for channel: {channel}")

        except asyncio.CancelledError:
            logger.info("Rating event listener cancelled")
        except Exception as e:
            logger.error(f"Error in rating event listener: {e}", exc_info=True)
            self._running = False


# Global instances
_publisher: Optional[RatingEventPublisher] = None
_subscriber: Optional[RatingEventSubscriber] = None


def get_rating_publisher(redis_url: str = "redis://localhost:6379/0") -> RatingEventPublisher:
    """Get or create global RatingEventPublisher instance."""
    global _publisher
    if _publisher is None:
        _publisher = RatingEventPublisher(redis_url)
    return _publisher


def get_rating_subscriber(redis_url: str = "redis://localhost:6379/0") -> RatingEventSubscriber:
    """Get or create global RatingEventSubscriber instance."""
    global _subscriber
    if _subscriber is None:
        _subscriber = RatingEventSubscriber(redis_url)
    return _subscriber
