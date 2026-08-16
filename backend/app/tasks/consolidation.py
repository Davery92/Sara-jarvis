"""
Consolidation tasks for Sara's cognitive architecture.

The consolidation agent compresses raw inputs into digestible context packets.
It is EVENT-DRIVEN, not timer-based:
- Monitors for activity (audio, text, etc.)
- Only consolidates after a quiet period following activity
- Never interrupts active conversations
"""

import logging
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from uuid import uuid4

from app.celery_app import celery_app
from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)

# Configuration for activity-based consolidation
QUIET_THRESHOLD_SECONDS = 60  # How long quiet before consolidating
MIN_ACTIVITY_FOR_CONSOLIDATION = 3  # Minimum entries to bother consolidating


@celery_app.task(bind=True, name="app.tasks.consolidation.check_consolidation_trigger")
def check_consolidation_trigger(self) -> Dict[str, Any]:
    """
    Smart consolidation trigger - only consolidates after activity goes quiet.

    Logic:
    1. Check when the last input activity was
    2. Check when consolidation last ran
    3. Only trigger if:
       - There's been activity since last consolidation
       - AND it's been quiet for QUIET_THRESHOLD_SECONDS
       - AND there's enough new content to consolidate
    """
    from app.core.redis import get_redis_sync_bytes

    r = get_redis_sync_bytes()

    try:
        # Get Redis server time for consistency
        redis_time = r.time()
        now_ms = redis_time[0] * 1000 + redis_time[1] // 1000

        # Find the most recent activity across all streams
        streams = ["raw_buffer:text", "raw_buffer:audio", "raw_buffer:screen",
                   "raw_buffer:notification", "raw_buffer:calendar", "raw_buffer:environmental"]

        last_activity_ms = 0
        total_new_entries = 0

        # Get last consolidation time
        last_consolidation = r.get("consolidation:last_activity_ms")
        last_consolidation_ms = int(last_consolidation) if last_consolidation else 0

        for stream in streams:
            try:
                # Get the most recent entry
                latest = r.xrevrange(stream, "+", "-", count=1)
                if latest:
                    entry_id = latest[0][0].decode() if isinstance(latest[0][0], bytes) else latest[0][0]
                    entry_ms = int(entry_id.split("-")[0])
                    if entry_ms > last_activity_ms:
                        last_activity_ms = entry_ms

                    # Count entries since last consolidation
                    if last_consolidation_ms > 0:
                        new_entries = r.xrange(stream, min=f"{last_consolidation_ms}-0", max="+")
                        total_new_entries += len(new_entries)
                    else:
                        # First run - count all recent entries
                        new_entries = r.xrange(stream, min=f"{now_ms - 300000}-0", max="+")  # Last 5 min
                        total_new_entries += len(new_entries)
            except Exception as e:
                logger.debug(f"Error checking stream {stream}: {e}")
                continue

        # Calculate quiet duration
        quiet_duration_ms = now_ms - last_activity_ms if last_activity_ms > 0 else 0
        quiet_duration_seconds = quiet_duration_ms / 1000

        # Determine if we should consolidate
        should_consolidate = (
            last_activity_ms > last_consolidation_ms and  # New activity since last consolidation
            quiet_duration_seconds >= QUIET_THRESHOLD_SECONDS and  # Been quiet long enough
            total_new_entries >= MIN_ACTIVITY_FOR_CONSOLIDATION  # Enough to consolidate
        )

        result = {
            "checked_at": local_now().isoformat(),
            "last_activity_ms": last_activity_ms,
            "last_consolidation_ms": last_consolidation_ms,
            "quiet_duration_seconds": round(quiet_duration_seconds, 1),
            "new_entries": total_new_entries,
            "should_consolidate": should_consolidate,
            "triggered": False
        }

        if should_consolidate:
            logger.info(f"Triggering consolidation: {quiet_duration_seconds:.0f}s quiet, {total_new_entries} new entries")
            # Update last activity marker BEFORE running to prevent double-triggers
            r.set("consolidation:last_activity_ms", str(last_activity_ms))
            # Trigger the actual consolidation
            run_consolidation.delay()
            result["triggered"] = True
        else:
            if total_new_entries > 0 and quiet_duration_seconds < QUIET_THRESHOLD_SECONDS:
                logger.debug(f"Waiting for quiet: {quiet_duration_seconds:.0f}s / {QUIET_THRESHOLD_SECONDS}s needed")

        return result

    except Exception as e:
        logger.error(f"Consolidation trigger check failed: {e}")
        raise  # failures must fail — Celery records FAILURE (Phase 1.3)


@celery_app.task(bind=True, name="app.tasks.consolidation.run_consolidation")
def run_consolidation(self) -> Dict[str, Any]:
    """
    Main consolidation sweep task.

    Called by check_consolidation_trigger when activity goes quiet.
    NOT run on a fixed timer - only after natural pauses in activity.

    1. Query raw buffer for unprocessed entries
    2. Group entries by timestamp proximity
    3. Score relevance and filter
    4. Update working memory with consolidated context
    5. Log discards for reflection auditing
    """
    from app.core.redis import get_redis_sync_bytes

    r = get_redis_sync_bytes()
    solo_user_id = os.getenv("SOLO_USER_ID", "")

    run_id = str(uuid4())
    run_start = local_now()

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

        # Get time window: from last consolidation to now
        # This is set by check_consolidation_trigger when it triggers us
        try:
            redis_time = r.time()
            window_end_ms = redis_time[0] * 1000 + redis_time[1] // 1000
        except Exception:
            window_end_ms = int(run_start.timestamp() * 1000)

        # Get the previous consolidation timestamp
        last_consolidation = r.get("consolidation:previous_activity_ms")
        if last_consolidation:
            window_start_ms = int(last_consolidation)
        else:
            # First run ever - look back 5 minutes
            window_start_ms = window_end_ms - (5 * 60 * 1000)

        # Update previous marker for next run
        current_activity = r.get("consolidation:last_activity_ms")
        if current_activity:
            r.set("consolidation:previous_activity_ms", current_activity)

        logger.info(f"Consolidation window: {window_start_ms} to {window_end_ms} ({(window_end_ms - window_start_ms) / 1000:.0f}s)")

        # Get raw buffer entries from all streams
        streams = ["raw_buffer:text", "raw_buffer:audio", "raw_buffer:screen",
                   "raw_buffer:notification", "raw_buffer:calendar", "raw_buffer:environmental"]

        all_entries = []
        for stream in streams:
            entries = read_stream_entries_ms(r, stream, window_start_ms, window_end_ms)
            all_entries.extend(entries)

        result["raw_entries_processed"] = len(all_entries)

        if not all_entries:
            # Nothing to process
            result["status"] = "completed"
            result["completed_at"] = local_now().isoformat()
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
        result["completed_at"] = local_now().isoformat()

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


def read_stream_entries_ms(r, stream: str, start_ms: int, end_ms: int) -> List[Dict]:
    """Read entries from a Redis stream within the time window (using milliseconds)."""
    try:
        # XRANGE to get entries in time window
        entries = r.xrange(stream, min=f"{start_ms}-0", max=f"{end_ms}-9999999999")

        result = []
        for entry_id, data in entries:
            entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
            timestamp_ms = int(entry_id_str.split("-")[0])
            entry = {
                "id": entry_id_str,
                "stream_type": stream.replace("raw_buffer:", ""),
                "timestamp_ms": timestamp_ms,
                "timestamp": datetime.fromtimestamp(timestamp_ms / 1000),
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

    # Sort by timestamp_ms (extracted from stream ID)
    sorted_entries = sorted(entries, key=lambda e: e.get("timestamp_ms", 0))

    groups = []
    current_group = [sorted_entries[0]]

    for entry in sorted_entries[1:]:
        current_ts = entry.get("timestamp_ms", 0)
        group_ts = current_group[-1].get("timestamp_ms", 0)

        diff_ms = abs(current_ts - group_ts)

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
        "audio": 0.25,  # Spoken context is highly relevant
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
        "timestamp": entry.get("timestamp", local_now()).isoformat()
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

    context["updated_at"] = local_now().isoformat()

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
