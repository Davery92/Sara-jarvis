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
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

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

    timestamp = datetime.now(timezone.utc)
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

    timestamp = datetime.now(timezone.utc)
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

    timestamp = datetime.now(timezone.utc)
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

    timestamp = datetime.now(timezone.utc)
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
    active_app: Optional[str] = None,
    image_base64: Optional[str] = None,
    analyze: bool = True
) -> Dict[str, Any]:
    """
    Process screen capture and add analysis to raw buffer.

    Args:
        screenshot_path: Path or reference to screenshot file
        active_app: Name of the currently active application
        image_base64: Base64-encoded image data for VLLM analysis
        analyze: Whether to run VLLM analysis on the screenshot

    Returns analysis result stored in raw buffer.
    """
    import redis
    import asyncio

    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    r = redis.from_url(redis_url)

    timestamp = datetime.now(timezone.utc)

    content_summary = ""
    ocr_text = ""

    # Run VLLM analysis if image data provided and analysis requested
    if image_base64 and analyze:
        try:
            analysis_result = asyncio.get_event_loop().run_until_complete(
                _analyze_screen_capture(image_base64, active_app)
            )
        except RuntimeError:
            analysis_result = asyncio.run(
                _analyze_screen_capture(image_base64, active_app)
            )

        content_summary = analysis_result.get("summary", "")
        ocr_text = analysis_result.get("ocr_text", "")

    entry_data = {
        "content": json.dumps({
            "active_app": active_app or "unknown",
            "content_summary": content_summary,
            "ocr_text": ocr_text
        }),
        "source": "screen_capture",
        "screenshot_ref": screenshot_path or "",
        "analyzed": str(bool(image_base64 and analyze)),
        "timestamp": timestamp.isoformat()
    }

    try:
        entry_id = r.xadd(
            "raw_buffer:screen",
            entry_data,
            maxlen=1000  # Keep fewer screen captures
        )

        logger.debug(f"Added screen capture to raw buffer: {entry_id}")

        return {
            "status": "success",
            "entry_id": entry_id.decode() if isinstance(entry_id, bytes) else entry_id,
            "stream": "raw_buffer:screen",
            "content_summary": content_summary,
            "timestamp": timestamp.isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to process screen capture: {e}")
        return {"status": "error", "error": str(e)}


async def _analyze_screen_capture(image_base64: str, active_app: Optional[str] = None) -> Dict[str, str]:
    """
    Analyze screen capture using VLLM (Ollama vision model).

    Returns dict with summary and OCR text.
    """
    import httpx

    vision_endpoint = os.getenv("VISION_ENDPOINT", "http://10.185.1.8:11434")
    vision_model = os.getenv("VISION_MODEL", "qwen3-vl:latest")

    prompt = f"""Analyze this screenshot and provide:
1. A brief summary of what's visible on screen (1-2 sentences)
2. Any visible text (OCR)
{f'Context: The active application is {active_app}' if active_app else ''}

Format your response as:
SUMMARY: <your summary>
TEXT: <any visible text>"""

    request_body = {
        "model": vision_model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [image_base64]
            }
        ],
        "stream": False
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{vision_endpoint}/api/chat",
                json=request_body
            )
            response.raise_for_status()
            result = response.json()

            response_text = result.get("message", {}).get("content", "")

            # Parse the response
            summary = ""
            ocr_text = ""

            if "SUMMARY:" in response_text:
                parts = response_text.split("SUMMARY:", 1)
                if len(parts) > 1:
                    remaining = parts[1]
                    if "TEXT:" in remaining:
                        summary_text, text_part = remaining.split("TEXT:", 1)
                        summary = summary_text.strip()
                        ocr_text = text_part.strip()
                    else:
                        summary = remaining.strip()
            else:
                # Fallback: use the whole response as summary
                summary = response_text[:500]

            return {
                "summary": summary,
                "ocr_text": ocr_text
            }

    except Exception as e:
        logger.warning(f"VLLM screen analysis failed: {e}")
        return {
            "summary": f"Analysis unavailable: {str(e)[:100]}",
            "ocr_text": ""
        }


# ============================================
# Audio/Visual Processing
# ============================================

async def _process_audio_with_riva(audio_path: str, source: str) -> Dict[str, Any]:
    """
    Process audio file with Riva ASR and NeMo diarization.

    Returns:
        Dict with transcript, speaker info, diarization results
    """
    from app.services.audio.riva_client import get_riva_client
    from app.services.audio.diarization_service import get_diarization_service

    try:
        # Step 1: Transcribe with Riva
        riva_client = await get_riva_client()
        transcript_result = await riva_client.transcribe_file(audio_path)

        # Step 2: Diarize with NeMo
        diarization_service = await get_diarization_service()
        diarization_result = await diarization_service.diarize(audio_path)

        # Step 3: Determine primary speaker
        primary_speaker = "unknown"
        if diarization_result.david_detected:
            primary_speaker = "david"
        elif diarization_result.speaker_labels:
            primary_speaker = diarization_result.speaker_labels[0]

        # Step 4: Combine transcript with diarization
        # Align words with speaker segments
        segments_with_text = []
        for seg in diarization_result.segments:
            seg_words = []
            for word in transcript_result.words:
                word_mid = (word.start_time + word.end_time) / 2
                if seg.start_time <= word_mid <= seg.end_time:
                    seg_words.append(word.word)

            segments_with_text.append({
                "start_time": seg.start_time,
                "end_time": seg.end_time,
                "speaker_id": seg.speaker_id,
                "confidence": seg.confidence,
                "text": " ".join(seg_words)
            })

        return {
            "status": "success",
            "transcript": transcript_result.text,
            "speaker": primary_speaker,
            "duration": transcript_result.duration,
            "confidence": transcript_result.confidence,
            "david_detected": diarization_result.david_detected,
            "diarization": {
                "num_speakers": diarization_result.num_speakers,
                "speaker_labels": diarization_result.speaker_labels,
                "segments": segments_with_text
            }
        }

    except Exception as e:
        logger.error(f"Riva/NeMo processing failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@celery_app.task(bind=True, name="app.tasks.input_processing.process_audio_input")
def process_audio_input(
    self,
    audio_path: Optional[str] = None,
    duration_seconds: float = 0.0,
    transcript: Optional[str] = None,
    speaker: Optional[str] = None,
    diarization: Optional[Dict] = None,
    source: str = "microphone"
) -> Dict[str, Any]:
    """
    Process audio input and store in raw buffer.

    Can accept either:
    1. Pre-transcribed text (transcript parameter) - current mode
    2. Audio file path for Riva transcription (Phase 0)

    Args:
        audio_path: Path to audio file (for future Riva processing)
        duration_seconds: Duration of the audio
        transcript: Pre-transcribed text (from Whisper, Jetson, etc.)
        speaker: Identified speaker (e.g., "david", "unknown")
        diarization: Speaker diarization data with segments
        source: Audio source (microphone, desktop_agent, phone)

    Returns result stored in raw buffer.
    """
    import redis

    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    r = redis.from_url(redis_url)

    timestamp = datetime.now(timezone.utc)

    # If transcript provided, use it directly
    # Otherwise, this is a placeholder for Riva (Phase 0)
    if transcript:
        entry_data = {
            "content": json.dumps({
                "transcript": transcript,
                "speaker": speaker or "unknown",
                "duration": duration_seconds,
                "diarization": diarization or {}
            }),
            "source": source,
            "speaker": speaker or "unknown",
            "audio_ref": audio_path or "",
            "duration": str(duration_seconds),
            "timestamp": timestamp.isoformat()
        }

        try:
            entry_id = r.xadd(
                "raw_buffer:audio",
                entry_data,
                maxlen=10000
            )

            logger.debug(f"Added audio transcript to raw buffer: {entry_id}")

            return {
                "status": "success",
                "entry_id": entry_id.decode() if isinstance(entry_id, bytes) else entry_id,
                "stream": "raw_buffer:audio",
                "speaker": speaker or "unknown",
                "transcript_length": len(transcript),
                "timestamp": timestamp.isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to process audio input: {e}")
            return {"status": "error", "error": str(e)}

    elif audio_path:
        # Process with Riva ASR + NeMo diarization
        logger.info(f"Processing audio file with Riva/NeMo: {audio_path}")

        try:
            result = asyncio.get_event_loop().run_until_complete(
                _process_audio_with_riva(audio_path, source)
            )
        except RuntimeError:
            result = asyncio.run(_process_audio_with_riva(audio_path, source))

        if result.get("status") == "success":
            entry_data = {
                "content": json.dumps({
                    "transcript": result.get("transcript", ""),
                    "speaker": result.get("speaker", "unknown"),
                    "duration": result.get("duration", duration_seconds),
                    "diarization": result.get("diarization", {}),
                    "confidence": result.get("confidence", 0.0)
                }),
                "source": source,
                "speaker": result.get("speaker", "unknown"),
                "audio_ref": audio_path,
                "duration": str(result.get("duration", duration_seconds)),
                "timestamp": timestamp.isoformat()
            }

            try:
                entry_id = r.xadd(
                    "raw_buffer:audio",
                    entry_data,
                    maxlen=10000
                )

                return {
                    "status": "success",
                    "entry_id": entry_id.decode() if isinstance(entry_id, bytes) else entry_id,
                    "stream": "raw_buffer:audio",
                    "transcript_length": len(result.get("transcript", "")),
                    "speaker": result.get("speaker", "unknown"),
                    "david_detected": result.get("david_detected", False),
                    "timestamp": timestamp.isoformat()
                }

            except Exception as e:
                logger.error(f"Failed to store processed audio: {e}")
                return {"status": "error", "error": str(e)}
        else:
            # Riva/NeMo processing failed - store as pending
            logger.warning(f"Riva/NeMo processing failed, storing as pending: {result.get('error')}")
            entry_data = {
                "content": json.dumps({
                    "transcript": "[Processing failed - pending retry]",
                    "audio_path": audio_path,
                    "duration": duration_seconds,
                    "status": "pending_retry",
                    "error": result.get("error", "unknown")
                }),
                "source": source,
                "audio_ref": audio_path,
                "duration": str(duration_seconds),
                "status": "pending_retry",
                "timestamp": timestamp.isoformat()
            }

            try:
                entry_id = r.xadd(
                    "raw_buffer:audio",
                    entry_data,
                    maxlen=10000
                )

                return {
                    "status": "pending",
                    "entry_id": entry_id.decode() if isinstance(entry_id, bytes) else entry_id,
                    "stream": "raw_buffer:audio",
                    "message": "Audio processing failed, queued for retry",
                    "error": result.get("error"),
                    "timestamp": timestamp.isoformat()
                }

            except Exception as e:
                logger.error(f"Failed to queue audio: {e}")
                return {"status": "error", "error": str(e)}

    return {
        "status": "error",
        "message": "Either transcript or audio_path must be provided"
    }


@celery_app.task(bind=True, name="app.tasks.input_processing.process_visual_input")
def process_visual_input(
    self,
    frame_path: Optional[str] = None,
    camera_id: str = "default",
    frame_base64: Optional[str] = None,
    detected_objects: Optional[List[Dict]] = None,
    scene_description: Optional[str] = None,
    detected_persons: Optional[List[Dict]] = None,
    analyze: bool = False
) -> Dict[str, Any]:
    """
    Process visual input (camera frame) and store in raw buffer.

    Can accept either:
    1. Pre-analyzed data (detected_objects, scene_description) - current mode
    2. Raw frame for YOLO/VLLM analysis (Phase 0)

    Args:
        frame_path: Path to frame image file
        camera_id: Camera identifier
        frame_base64: Base64-encoded frame data for analysis
        detected_objects: Pre-detected objects from YOLO
        scene_description: Pre-analyzed scene description
        detected_persons: Detected persons with posture data
        analyze: Whether to run VLLM scene analysis

    Returns result stored in raw buffer.
    """
    import redis
    import asyncio

    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    r = redis.from_url(redis_url)

    timestamp = datetime.now(timezone.utc)

    # Use pre-analyzed data if provided
    if detected_objects is not None or scene_description is not None:
        entry_data = {
            "content": json.dumps({
                "objects": detected_objects or [],
                "scene": scene_description or "",
                "persons": detected_persons or [],
                "camera_id": camera_id
            }),
            "source": "visual",
            "camera_id": camera_id,
            "frame_ref": frame_path or "",
            "timestamp": timestamp.isoformat()
        }

        try:
            entry_id = r.xadd(
                "raw_buffer:visual",
                entry_data,
                maxlen=5000
            )

            logger.debug(f"Added visual data to raw buffer: {entry_id}")

            return {
                "status": "success",
                "entry_id": entry_id.decode() if isinstance(entry_id, bytes) else entry_id,
                "stream": "raw_buffer:visual",
                "object_count": len(detected_objects or []),
                "person_count": len(detected_persons or []),
                "timestamp": timestamp.isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to process visual input: {e}")
            return {"status": "error", "error": str(e)}

    # If frame data provided and analysis requested, run VLLM scene analysis
    elif frame_base64 and analyze:
        try:
            analysis_result = asyncio.get_event_loop().run_until_complete(
                _analyze_visual_frame(frame_base64, camera_id)
            )
        except RuntimeError:
            analysis_result = asyncio.run(
                _analyze_visual_frame(frame_base64, camera_id)
            )

        entry_data = {
            "content": json.dumps({
                "objects": analysis_result.get("objects", []),
                "scene": analysis_result.get("scene", ""),
                "persons": analysis_result.get("persons", []),
                "camera_id": camera_id
            }),
            "source": "visual",
            "camera_id": camera_id,
            "frame_ref": frame_path or "",
            "analyzed": "true",
            "timestamp": timestamp.isoformat()
        }

        try:
            entry_id = r.xadd(
                "raw_buffer:visual",
                entry_data,
                maxlen=5000
            )

            return {
                "status": "success",
                "entry_id": entry_id.decode() if isinstance(entry_id, bytes) else entry_id,
                "stream": "raw_buffer:visual",
                "scene": analysis_result.get("scene", ""),
                "timestamp": timestamp.isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to process visual input: {e}")
            return {"status": "error", "error": str(e)}

    # Store frame reference for future YOLO processing (Phase 0)
    elif frame_path:
        entry_data = {
            "content": json.dumps({
                "frame_path": frame_path,
                "camera_id": camera_id,
                "status": "pending_yolo"
            }),
            "source": "visual",
            "camera_id": camera_id,
            "frame_ref": frame_path,
            "status": "pending_yolo",
            "timestamp": timestamp.isoformat()
        }

        try:
            entry_id = r.xadd(
                "raw_buffer:visual",
                entry_data,
                maxlen=5000
            )

            return {
                "status": "pending",
                "entry_id": entry_id.decode() if isinstance(entry_id, bytes) else entry_id,
                "stream": "raw_buffer:visual",
                "message": "Frame stored, pending YOLO analysis (Phase 0)",
                "timestamp": timestamp.isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to store visual frame: {e}")
            return {"status": "error", "error": str(e)}

    return {
        "status": "error",
        "message": "No valid input provided (need frame_path, frame_base64+analyze, or detected_objects)"
    }


async def _analyze_visual_frame(frame_base64: str, camera_id: str) -> Dict[str, Any]:
    """
    Analyze a camera frame using VLLM (Ollama vision model).

    Returns dict with scene description and detected items.
    """
    import httpx

    vision_endpoint = os.getenv("VISION_ENDPOINT", "http://10.185.1.8:11434")
    vision_model = os.getenv("VISION_MODEL", "qwen3-vl:latest")

    prompt = f"""Analyze this camera frame from camera '{camera_id}' and describe:
1. What's happening in the scene (1-2 sentences)
2. Any people visible and what they're doing
3. Notable objects in the frame

Be concise. Format as:
SCENE: <description>
PERSONS: <people and activities, or "none">
OBJECTS: <notable objects>"""

    request_body = {
        "model": vision_model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [frame_base64]
            }
        ],
        "stream": False
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{vision_endpoint}/api/chat",
                json=request_body
            )
            response.raise_for_status()
            result = response.json()

            response_text = result.get("message", {}).get("content", "")

            # Parse the response
            scene = ""
            persons = []
            objects = []

            lines = response_text.split("\n")
            for line in lines:
                if line.startswith("SCENE:"):
                    scene = line[6:].strip()
                elif line.startswith("PERSONS:"):
                    persons_text = line[8:].strip()
                    if persons_text.lower() != "none":
                        persons = [{"description": persons_text}]
                elif line.startswith("OBJECTS:"):
                    objects_text = line[8:].strip()
                    objects = [{"name": obj.strip()} for obj in objects_text.split(",") if obj.strip()]

            return {
                "scene": scene or response_text[:200],
                "persons": persons,
                "objects": objects
            }

    except Exception as e:
        logger.warning(f"VLLM visual analysis failed: {e}")
        return {
            "scene": f"Analysis unavailable: {str(e)[:100]}",
            "persons": [],
            "objects": []
        }
