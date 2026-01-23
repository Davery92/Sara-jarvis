"""
Input processing tasks for Sara's cognitive architecture.

These tasks handle incoming sensory data from various sources:
- Text: User messages, notifications, system events
- Screen: Periodic screenshots and analysis
- Audio: Voice input and ambient sound (requires GPU cluster)
- Visual: Camera feed and scene analysis (requires Jetson/GPU)
- Environmental: Home Assistant and sensor data
"""

import logging
import json
import os
from datetime import datetime
from typing import Dict, Any, Optional

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="app.tasks.input_processing.process_text_input")
def process_text_input(
    self,
    content: str,
    source: str,
    metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Process incoming text input and add to raw buffer.

    Sources: user_message, notification, calendar_event, system_event
    """
    import redis

    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    r = redis.from_url(redis_url)

    timestamp = datetime.utcnow()
    entry_data = {
        "content": content,
        "source": source,
        "metadata": json.dumps(metadata or {}),
        "timestamp": timestamp.isoformat()
    }

    try:
        # Add to raw buffer stream
        entry_id = r.xadd(
            "raw_buffer:text",
            entry_data,
            maxlen=50000  # Keep max 50k entries
        )

        logger.debug(f"Added text input to raw buffer: {entry_id}")

        return {
            "status": "success",
            "entry_id": entry_id.decode() if isinstance(entry_id, bytes) else entry_id,
            "stream": "raw_buffer:text",
            "timestamp": timestamp.isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to process text input: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@celery_app.task(bind=True, name="app.tasks.input_processing.process_notification")
def process_notification(
    self,
    title: str,
    body: str,
    app_name: str,
    metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Process incoming notification and add to raw buffer.
    """
    import redis

    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    r = redis.from_url(redis_url)

    timestamp = datetime.utcnow()
    entry_data = {
        "content": json.dumps({
            "title": title,
            "body": body,
            "app": app_name
        }),
        "source": "notification",
        "app_name": app_name,
        "metadata": json.dumps(metadata or {}),
        "timestamp": timestamp.isoformat()
    }

    try:
        entry_id = r.xadd(
            "raw_buffer:notification",
            entry_data,
            maxlen=10000
        )

        return {
            "status": "success",
            "entry_id": entry_id.decode() if isinstance(entry_id, bytes) else entry_id,
            "stream": "raw_buffer:notification",
            "timestamp": timestamp.isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to process notification: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task(bind=True, name="app.tasks.input_processing.process_calendar_event")
def process_calendar_event(
    self,
    event_id: str,
    title: str,
    start_time: str,
    end_time: Optional[str] = None,
    description: Optional[str] = None,
    event_type: str = "event"
) -> Dict[str, Any]:
    """
    Process calendar event and add to raw buffer.
    """
    import redis

    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    r = redis.from_url(redis_url)

    timestamp = datetime.utcnow()
    entry_data = {
        "content": json.dumps({
            "event_id": event_id,
            "title": title,
            "start_time": start_time,
            "end_time": end_time,
            "description": description,
            "type": event_type
        }),
        "source": "calendar",
        "event_id": event_id,
        "timestamp": timestamp.isoformat()
    }

    try:
        entry_id = r.xadd(
            "raw_buffer:calendar",
            entry_data,
            maxlen=5000
        )

        return {
            "status": "success",
            "entry_id": entry_id.decode() if isinstance(entry_id, bytes) else entry_id,
            "stream": "raw_buffer:calendar",
            "timestamp": timestamp.isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to process calendar event: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task(bind=True, name="app.tasks.input_processing.process_environmental")
def process_environmental(
    self,
    entity_id: str,
    old_state: str,
    new_state: str,
    attributes: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Process environmental/Home Assistant state change.
    """
    import redis

    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    r = redis.from_url(redis_url)

    timestamp = datetime.utcnow()
    entry_data = {
        "content": json.dumps({
            "entity_id": entity_id,
            "old_state": old_state,
            "new_state": new_state,
            "change": f"{old_state} -> {new_state}"
        }),
        "source": "home_assistant",
        "entity_id": entity_id,
        "attributes": json.dumps(attributes or {}),
        "timestamp": timestamp.isoformat()
    }

    try:
        entry_id = r.xadd(
            "raw_buffer:environmental",
            entry_data,
            maxlen=20000
        )

        return {
            "status": "success",
            "entry_id": entry_id.decode() if isinstance(entry_id, bytes) else entry_id,
            "stream": "raw_buffer:environmental",
            "timestamp": timestamp.isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to process environmental event: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task(bind=True, name="app.tasks.input_processing.process_screen_capture")
def process_screen_capture(
    self,
    screenshot_path: str,
    active_app: Optional[str] = None
) -> Dict[str, Any]:
    """
    Process screen capture and add analysis to raw buffer.

    This task captures the screen, optionally runs VLLM analysis,
    and stores the result in the raw buffer.

    For now, this is a placeholder - actual screen capture requires
    additional setup (running on a machine with display access).
    """
    import redis

    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    r = redis.from_url(redis_url)

    timestamp = datetime.utcnow()

    # TODO: Implement actual screen capture and VLLM analysis
    # This would involve:
    # 1. Capturing screenshot
    # 2. Sending to VLLM for analysis
    # 3. Extracting: active_app, content_summary, ocr_text

    entry_data = {
        "content": json.dumps({
            "active_app": active_app or "unknown",
            "content_summary": "Screen capture not yet implemented",
            "ocr_text": ""
        }),
        "source": "screen_capture",
        "screenshot_ref": screenshot_path,
        "timestamp": timestamp.isoformat()
    }

    try:
        entry_id = r.xadd(
            "raw_buffer:screen",
            entry_data,
            maxlen=1000  # Keep fewer screen captures
        )

        return {
            "status": "success",
            "entry_id": entry_id.decode() if isinstance(entry_id, bytes) else entry_id,
            "stream": "raw_buffer:screen",
            "timestamp": timestamp.isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to process screen capture: {e}")
        return {"status": "error", "error": str(e)}


# ============================================
# Audio/Visual Processing (Future - GPU Cluster)
# ============================================

@celery_app.task(bind=True, name="app.tasks.input_processing.process_audio_input")
def process_audio_input(
    self,
    audio_path: str,
    duration_seconds: float
) -> Dict[str, Any]:
    """
    Process audio input through Whisper transcription.

    Requires GPU cluster (david@10.185.1.8) for efficient processing.
    This is a placeholder for Phase 1c/1d implementation.
    """
    # TODO: Implement when GPU cluster integration is ready
    # Steps:
    # 1. Upload audio to GPU cluster or stream
    # 2. Run Whisper transcription
    # 3. Run speaker diarization
    # 4. Tag speakers
    # 5. Store result in raw_buffer:audio

    return {
        "status": "not_implemented",
        "message": "Audio processing requires GPU cluster integration"
    }


@celery_app.task(bind=True, name="app.tasks.input_processing.process_visual_input")
def process_visual_input(
    self,
    frame_path: str,
    camera_id: str = "default"
) -> Dict[str, Any]:
    """
    Process visual input through YOLO object detection.

    Requires Jetson (david@10.185.1.155) or GPU cluster for processing.
    This is a placeholder for Phase 1c/1d implementation.
    """
    # TODO: Implement when Jetson/GPU integration is ready
    # Steps:
    # 1. Run YOLO object detection
    # 2. Run posture detection
    # 3. Periodic VLLM scene analysis
    # 4. Store result in raw_buffer:visual

    return {
        "status": "not_implemented",
        "message": "Visual processing requires Jetson/GPU integration"
    }
