"""
Raw Buffer Service for Sara's cognitive architecture.

The raw buffer captures all incoming sensory data with timestamps
for later processing by the consolidation agent.

Uses Redis Streams for efficient append-only storage with TTL.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from app.core.timezone import now as local_now
from dataclasses import dataclass, asdict
from enum import Enum

import redis

logger = logging.getLogger(__name__)


class StreamType(str, Enum):
    """Types of input streams in the raw buffer."""
    TEXT = "text"
    AUDIO = "audio"
    VISUAL = "visual"
    SCREEN = "screen"
    NOTIFICATION = "notification"
    CALENDAR = "calendar"
    ENVIRONMENTAL = "environmental"


@dataclass
class RawBufferEntry:
    """A single entry in the raw buffer."""
    id: str
    stream_type: StreamType
    timestamp: datetime
    content: Any
    source: str
    metadata: Dict[str, Any]
    processed: bool = False


class RawBufferService:
    """
    Service for managing the raw input buffer.

    The raw buffer stores all incoming sensory data with microsecond-precision
    timestamps. Data is retained for 48-72 hours before automatic expiry.

    Uses Redis Streams for:
    - Efficient append-only writes
    - Time-range queries
    - Consumer groups for parallel processing
    - Automatic trimming with MAXLEN
    """

    STREAM_PREFIX = "raw_buffer:"
    DEFAULT_TTL_HOURS = 48
    DEFAULT_MAX_LEN = 50000  # Max entries per stream

    def __init__(self, redis_url: Optional[str] = None):
        """Initialize the raw buffer service."""
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://redis:6379/0")
        self._redis: Optional[redis.Redis] = None

    @property
    def redis(self) -> redis.Redis:
        """Lazy initialization of Redis client."""
        if self._redis is None:
            from app.core.redis import get_redis_sync_bytes
            self._redis = get_redis_sync_bytes()
        return self._redis

    def _stream_key(self, stream_type: StreamType) -> str:
        """Get the Redis stream key for a stream type."""
        return f"{self.STREAM_PREFIX}{stream_type.value}"

    async def add_entry(
        self,
        stream_type: StreamType,
        content: Any,
        source: str,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None
    ) -> str:
        """
        Add an entry to the raw buffer.

        Args:
            stream_type: Type of input stream
            content: The actual content (will be JSON serialized)
            source: Source identifier (e.g., "user_message", "home_assistant")
            metadata: Additional metadata
            timestamp: Optional timestamp (defaults to now)

        Returns:
            The entry ID assigned by Redis
        """
        ts = timestamp or local_now()

        entry_data = {
            "content": json.dumps(content) if not isinstance(content, str) else content,
            "source": source,
            "metadata": json.dumps(metadata or {}),
            "timestamp": ts.isoformat(),
            "processed": "false"
        }

        stream_key = self._stream_key(stream_type)

        # Determine max length based on stream type
        max_len = {
            StreamType.TEXT: 50000,
            StreamType.AUDIO: 10000,
            StreamType.VISUAL: 5000,
            StreamType.SCREEN: 1000,
            StreamType.NOTIFICATION: 10000,
            StreamType.CALENDAR: 5000,
            StreamType.ENVIRONMENTAL: 20000,
        }.get(stream_type, self.DEFAULT_MAX_LEN)

        try:
            entry_id = self.redis.xadd(
                stream_key,
                entry_data,
                maxlen=max_len
            )

            # Decode if bytes
            if isinstance(entry_id, bytes):
                entry_id = entry_id.decode()

            logger.debug(f"Added entry {entry_id} to {stream_key}")
            return entry_id

        except Exception as e:
            logger.error(f"Failed to add entry to {stream_key}: {e}")
            raise

    async def get_entries(
        self,
        stream_type: StreamType,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100,
        unprocessed_only: bool = False
    ) -> List[RawBufferEntry]:
        """
        Get entries from the raw buffer.

        Args:
            stream_type: Type of input stream
            start: Start of time window (defaults to 1 hour ago)
            end: End of time window (defaults to now)
            limit: Maximum entries to return
            unprocessed_only: Only return unprocessed entries

        Returns:
            List of RawBufferEntry objects
        """
        stream_key = self._stream_key(stream_type)

        # Default time window
        end = end or local_now()
        start = start or (end - timedelta(hours=1))

        # Convert to Redis stream ID format
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)

        try:
            raw_entries = self.redis.xrange(
                stream_key,
                min=f"{start_ms}-0",
                max=f"{end_ms}-9999999999",
                count=limit
            )

            entries = []
            for entry_id, data in raw_entries:
                entry = self._parse_entry(entry_id, data, stream_type)

                if unprocessed_only and entry.processed:
                    continue

                entries.append(entry)

            return entries

        except Exception as e:
            logger.error(f"Failed to get entries from {stream_key}: {e}")
            return []

    async def get_all_streams(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit_per_stream: int = 100
    ) -> Dict[StreamType, List[RawBufferEntry]]:
        """
        Get entries from all streams within a time window.

        Args:
            start: Start of time window
            end: End of time window
            limit_per_stream: Maximum entries per stream

        Returns:
            Dict mapping stream types to their entries
        """
        result = {}

        for stream_type in StreamType:
            entries = await self.get_entries(
                stream_type, start, end, limit_per_stream
            )
            if entries:
                result[stream_type] = entries

        return result

    async def mark_processed(
        self,
        stream_type: StreamType,
        entry_ids: List[str]
    ) -> int:
        """
        Mark entries as processed.

        Note: Redis Streams don't support direct updates, so we track
        processing status in a separate set.

        Args:
            stream_type: Type of input stream
            entry_ids: List of entry IDs to mark

        Returns:
            Number of entries marked
        """
        processed_key = f"{self._stream_key(stream_type)}:processed"

        try:
            # Add to processed set
            if entry_ids:
                self.redis.sadd(processed_key, *entry_ids)
                # Set TTL on processed set (same as buffer retention)
                self.redis.expire(processed_key, self.DEFAULT_TTL_HOURS * 3600)

            return len(entry_ids)

        except Exception as e:
            logger.error(f"Failed to mark entries as processed: {e}")
            return 0

    async def get_stream_info(self, stream_type: StreamType) -> Dict[str, Any]:
        """
        Get information about a stream.

        Returns:
            Dict with stream statistics
        """
        stream_key = self._stream_key(stream_type)

        try:
            info = self.redis.xinfo_stream(stream_key)
            return {
                "stream_type": stream_type.value,
                "length": info.get("length", 0),
                "first_entry": info.get("first-entry"),
                "last_entry": info.get("last-entry"),
                "radix_tree_keys": info.get("radix-tree-keys", 0),
                "radix_tree_nodes": info.get("radix-tree-nodes", 0),
            }
        except redis.exceptions.ResponseError:
            # Stream doesn't exist
            return {
                "stream_type": stream_type.value,
                "length": 0,
                "status": "not_created"
            }
        except Exception as e:
            logger.error(f"Failed to get stream info for {stream_key}: {e}")
            return {
                "stream_type": stream_type.value,
                "error": str(e)
            }

    async def get_all_streams_info(self) -> Dict[str, Any]:
        """Get information about all streams."""
        result = {}
        total_entries = 0

        for stream_type in StreamType:
            info = await self.get_stream_info(stream_type)
            result[stream_type.value] = info
            total_entries += info.get("length", 0)

        result["total_entries"] = total_entries
        return result

    async def trim_old_entries(self, max_age_hours: int = None) -> Dict[str, int]:
        """
        Remove entries older than max_age_hours.

        Args:
            max_age_hours: Maximum age in hours (defaults to DEFAULT_TTL_HOURS)

        Returns:
            Dict mapping stream types to number of entries removed
        """
        max_age = max_age_hours or self.DEFAULT_TTL_HOURS
        cutoff_ms = int((local_now() - timedelta(hours=max_age)).timestamp() * 1000)

        result = {}

        for stream_type in StreamType:
            stream_key = self._stream_key(stream_type)

            try:
                # Get current length
                info = self.redis.xinfo_stream(stream_key)
                before_len = info.get("length", 0)

                # Trim old entries
                self.redis.xtrim(stream_key, minid=f"{cutoff_ms}-0")

                # Get new length
                info = self.redis.xinfo_stream(stream_key)
                after_len = info.get("length", 0)

                result[stream_type.value] = before_len - after_len

            except redis.exceptions.ResponseError:
                # Stream doesn't exist
                result[stream_type.value] = 0
            except Exception as e:
                logger.error(f"Failed to trim {stream_key}: {e}")
                result[stream_type.value] = -1

        return result

    def _parse_entry(
        self,
        entry_id: bytes | str,
        data: Dict,
        stream_type: StreamType
    ) -> RawBufferEntry:
        """Parse a Redis stream entry into a RawBufferEntry."""
        # Decode entry ID
        if isinstance(entry_id, bytes):
            entry_id = entry_id.decode()

        # Extract timestamp from entry ID (milliseconds since epoch)
        ts_ms = int(entry_id.split("-")[0])
        timestamp = datetime.fromtimestamp(ts_ms / 1000)

        # Decode data fields
        decoded_data = {}
        for key, value in data.items():
            k = key.decode() if isinstance(key, bytes) else key
            v = value.decode() if isinstance(value, bytes) else value
            decoded_data[k] = v

        # Parse content
        content = decoded_data.get("content", "")
        try:
            content = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            pass

        # Parse metadata
        metadata = decoded_data.get("metadata", "{}")
        try:
            metadata = json.loads(metadata)
        except (json.JSONDecodeError, TypeError):
            metadata = {}

        return RawBufferEntry(
            id=entry_id,
            stream_type=stream_type,
            timestamp=timestamp,
            content=content,
            source=decoded_data.get("source", "unknown"),
            metadata=metadata,
            processed=decoded_data.get("processed", "false").lower() == "true"
        )


# Singleton instance for easy access
_raw_buffer_service: Optional[RawBufferService] = None


def get_raw_buffer_service() -> RawBufferService:
    """Get the singleton RawBufferService instance."""
    global _raw_buffer_service
    if _raw_buffer_service is None:
        _raw_buffer_service = RawBufferService()
    return _raw_buffer_service
