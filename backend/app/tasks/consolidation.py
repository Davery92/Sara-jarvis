"""
Consolidation tasks for Sara's cognitive architecture.

The consolidation agent compresses raw inputs into digestible context packets.
It runs every 60 seconds, processing the raw buffer and updating working memory.
"""

import logging
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from uuid import uuid4

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="app.tasks.consolidation.run_consolidation")
def run_consolidation(self) -> Dict[str, Any]:
    """
    Main consolidation sweep task.

    Every 60 seconds:
    1. Query raw buffer for unprocessed entries
    2. Group entries by timestamp proximity
    3. Score relevance and filter
    4. Update working memory with consolidated context
    5. Log discards for reflection auditing
    """
    import redis

    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    r = redis.from_url(redis_url)
    solo_user_id = os.getenv("SOLO_USER_ID", "")

    run_id = str(uuid4())
    run_start = datetime.utcnow()

    result = {
        "run_id": run_id,
        "started_at": run_start.isoformat(),
        "raw_entries_processed": 0,
        "entries_kept": 0,
        "entries_discarded": 0,
        "status": "running"
    }

    try:
        # Get consolidation config
        config = get_consolidation_config(r, solo_user_id)

        # Calculate time window
        window_seconds = config.get("window_seconds", 60)
        window_end = run_start
        window_start = window_end - timedelta(seconds=window_seconds)

        # Get raw buffer entries from all streams
        streams = ["raw_buffer:text", "raw_buffer:screen", "raw_buffer:notification",
                   "raw_buffer:calendar", "raw_buffer:environmental"]

        all_entries = []
        for stream in streams:
            entries = read_stream_entries(r, stream, window_start, window_end)
            all_entries.extend(entries)

        result["raw_entries_processed"] = len(all_entries)

        if not all_entries:
            # Nothing to process
            result["status"] = "completed"
            result["completed_at"] = datetime.utcnow().isoformat()
            mark_consolidation_run(r, run_start)
            return result

        # Group entries by timestamp proximity
        grouping_threshold_ms = config.get("grouping_threshold_ms", 5000)
        groups = group_entries_by_time(all_entries, grouping_threshold_ms)

        # Process each group
        kept_segments = []
        discarded_entries = []

        relevance_threshold = config.get("relevance_threshold", 0.3)
        priority_rules = config.get("priority_rules", [])

        for group in groups:
            # Deduplicate within group
            deduped = deduplicate_entries(group)

            for entry in deduped:
                # Calculate relevance score
                relevance = calculate_relevance(entry, priority_rules, config)

                if relevance >= relevance_threshold:
                    # Keep this entry
                    segment = create_context_segment(entry, relevance)
                    kept_segments.append(segment)
                else:
                    # Discard with reason
                    discarded_entries.append({
                        "entry_id": entry.get("id"),
                        "stream_type": entry.get("stream_type"),
                        "content_preview": str(entry.get("content", ""))[:100],
                        "relevance_score": relevance,
                        "reason": "below_threshold"
                    })

        result["entries_kept"] = len(kept_segments)
        result["entries_discarded"] = len(discarded_entries)

        # Update working memory with kept segments
        if kept_segments:
            update_working_memory_context(r, solo_user_id, kept_segments)

        # Log discards for reflection auditing
        if discarded_entries:
            log_discards(r, run_id, discarded_entries)

        result["status"] = "completed"
        result["completed_at"] = datetime.utcnow().isoformat()

        # Mark last successful run
        mark_consolidation_run(r, run_start)

        logger.info(f"Consolidation run {run_id}: processed={result['raw_entries_processed']}, "
                   f"kept={result['entries_kept']}, discarded={result['entries_discarded']}")

    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
        logger.error(f"Consolidation run {run_id} failed: {e}")

    return result


def get_consolidation_config(r, user_id: str) -> Dict[str, Any]:
    """Get consolidation configuration from Redis or return defaults."""
    config_key = f"consolidation:config:{user_id}"
    config_data = r.get(config_key)

    if config_data:
        return json.loads(config_data)

    # Default configuration
    return {
        "window_seconds": 60,
        "grouping_threshold_ms": 5000,
        "relevance_threshold": 0.3,
        "priority_rules": [
            {"pattern": "source:user_message", "boost": 0.5},
            {"pattern": "source:notification", "boost": 0.3},
            {"pattern": "source:calendar", "boost": 0.4},
            {"pattern": "stream_type:text", "boost": 0.2},
        ],
        "context_modifiers": {
            "sleeping": {"relevance_threshold": 0.7},
            "working": {"relevance_threshold": 0.4}
        }
    }


def read_stream_entries(r, stream: str, start: datetime, end: datetime) -> List[Dict]:
    """Read entries from a Redis stream within the time window."""
    try:
        # Convert datetime to Redis stream ID format (milliseconds)
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)

        # XRANGE to get entries in time window
        entries = r.xrange(stream, min=f"{start_ms}-0", max=f"{end_ms}-9999999999")

        result = []
        for entry_id, data in entries:
            entry = {
                "id": entry_id.decode() if isinstance(entry_id, bytes) else entry_id,
                "stream_type": stream.replace("raw_buffer:", ""),
                "timestamp": datetime.fromtimestamp(int(entry_id.decode().split("-")[0]) / 1000)
                            if isinstance(entry_id, bytes) else datetime.fromtimestamp(int(entry_id.split("-")[0]) / 1000),
            }
            # Decode data fields
            for key, value in data.items():
                k = key.decode() if isinstance(key, bytes) else key
                v = value.decode() if isinstance(value, bytes) else value
                try:
                    entry[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    entry[k] = v
            result.append(entry)

        return result

    except Exception as e:
        logger.warning(f"Error reading stream {stream}: {e}")
        return []


def group_entries_by_time(entries: List[Dict], threshold_ms: int) -> List[List[Dict]]:
    """Group entries that are within threshold_ms of each other."""
    if not entries:
        return []

    # Sort by timestamp
    sorted_entries = sorted(entries, key=lambda e: e.get("timestamp", datetime.min))

    groups = []
    current_group = [sorted_entries[0]]

    for entry in sorted_entries[1:]:
        current_ts = entry.get("timestamp", datetime.min)
        group_ts = current_group[-1].get("timestamp", datetime.min)

        diff_ms = abs((current_ts - group_ts).total_seconds() * 1000)

        if diff_ms <= threshold_ms:
            current_group.append(entry)
        else:
            groups.append(current_group)
            current_group = [entry]

    groups.append(current_group)
    return groups


def deduplicate_entries(entries: List[Dict]) -> List[Dict]:
    """Remove duplicate entries based on content similarity."""
    seen_content = set()
    deduped = []

    for entry in entries:
        content = str(entry.get("content", ""))
        # Simple hash-based dedup
        content_hash = hash(content[:200])  # First 200 chars

        if content_hash not in seen_content:
            seen_content.add(content_hash)
            deduped.append(entry)

    return deduped


def calculate_relevance(entry: Dict, priority_rules: List[Dict], config: Dict) -> float:
    """Calculate relevance score for an entry based on rules."""
    base_score = 0.5  # Start at neutral

    # Apply priority rules
    for rule in priority_rules:
        pattern = rule.get("pattern", "")
        boost = rule.get("boost", 0)

        # Check if pattern matches
        if ":" in pattern:
            key, value = pattern.split(":", 1)
            if str(entry.get(key, "")) == value:
                base_score += boost
        elif pattern in str(entry):
            base_score += boost

    # Apply stream type boosts
    stream_type = entry.get("stream_type", "")
    stream_boosts = {
        "text": 0.1,
        "notification": 0.2,
        "calendar": 0.3,
        "screen": 0.0,
        "environmental": -0.1
    }
    base_score += stream_boosts.get(stream_type, 0)

    # Clamp to 0-1
    return max(0.0, min(1.0, base_score))


def create_context_segment(entry: Dict, relevance: float) -> Dict:
    """Create a context segment from a raw entry."""
    return {
        "type": entry.get("stream_type", "unknown"),
        "timestamp": entry.get("timestamp", datetime.utcnow()).isoformat()
                     if isinstance(entry.get("timestamp"), datetime) else entry.get("timestamp"),
        "content": entry.get("content", ""),
        "relevance_score": relevance,
        "source_raw_id": entry.get("id"),
        "metadata": entry.get("metadata", {})
    }


def update_working_memory_context(r, user_id: str, segments: List[Dict]):
    """Update the current context in working memory."""
    context_key = f"working_memory:{user_id}:context"

    # Get existing context
    existing = r.get(context_key)
    if existing:
        try:
            context = json.loads(existing)
        except json.JSONDecodeError:
            context = {"segments": [], "updated_at": None}
    else:
        context = {"segments": [], "updated_at": None}

    # Add new segments
    context["segments"].extend(segments)

    # Apply capacity limit (keep most recent/relevant)
    max_segments = 50
    if len(context["segments"]) > max_segments:
        # Sort by relevance and keep top segments
        context["segments"] = sorted(
            context["segments"],
            key=lambda s: s.get("relevance_score", 0),
            reverse=True
        )[:max_segments]

    context["updated_at"] = datetime.utcnow().isoformat()

    # Store with 1 hour TTL
    r.setex(context_key, 3600, json.dumps(context))


def log_discards(r, run_id: str, discards: List[Dict]):
    """Log discarded entries for reflection auditing."""
    discard_key = f"consolidation:discards:{run_id}"

    # Store discards with 7 day TTL (for reflection agent)
    r.setex(discard_key, 7 * 24 * 3600, json.dumps(discards))

    # Also add to discard log stream
    for discard in discards:
        r.xadd(
            "consolidation:discard_log",
            {
                "run_id": run_id,
                "entry_id": discard.get("entry_id", ""),
                "stream_type": discard.get("stream_type", ""),
                "reason": discard.get("reason", ""),
                "relevance_score": str(discard.get("relevance_score", 0)),
                "content_preview": discard.get("content_preview", "")[:100]
            },
            maxlen=10000  # Keep last 10k discards
        )


def mark_consolidation_run(r, timestamp: datetime):
    """Mark the last successful consolidation run."""
    r.set("consolidation:last_run", timestamp.isoformat())
