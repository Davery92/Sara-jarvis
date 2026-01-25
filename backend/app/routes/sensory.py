"""
Sensory Monitor API Routes

Real-time monitoring of audio/visual pipeline:
- Voice agent status
- Speaker identification status
- Whisper transcription status
- Camera status
- Event streaming via SSE
"""

import asyncio
import json
import logging
import subprocess
from datetime import datetime
from typing import Optional, AsyncGenerator
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
import redis

from app.main_simple import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sensory", tags=["sensory"])

# Redis for event pub/sub
import os
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# Service endpoints
JETSON_IP = "10.185.1.155"
GPU_CLUSTER_IP = "10.185.1.8"
NEMO_URL = f"http://{GPU_CLUSTER_IP}:8002"
WHISPER_URL = f"http://{GPU_CLUSTER_IP}:8585"


class SensoryStatus(BaseModel):
    voice_agent: dict
    nemo_diarization: dict
    whisper: dict
    camera: Optional[dict] = None


@router.get("/status")
async def get_sensory_status(current_user=Depends(get_current_user)):
    """Get status of all sensory services."""
    status = {
        "voice_agent": {"status": "unknown"},
        "nemo_diarization": {"status": "offline"},
        "whisper": {"status": "offline"},
        "camera": {"status": "inactive"}
    }

    async with httpx.AsyncClient(timeout=3.0) as client:
        # Check NeMo diarization
        try:
            response = await client.get(f"{NEMO_URL}/health")
            if response.status_code == 200:
                data = response.json()
                status["nemo_diarization"] = {
                    "status": data.get("status", "unknown"),
                    "model_loaded": data.get("model_loaded", False),
                    "gpu_available": data.get("gpu_available", False),
                    "backend": data.get("backend", "unknown")
                }
        except Exception as e:
            logger.debug(f"NeMo health check failed: {e}")

        # Check Whisper
        try:
            response = await client.get(f"{WHISPER_URL}/health")
            if response.status_code == 200:
                status["whisper"] = {"status": "healthy"}
        except Exception as e:
            logger.debug(f"Whisper health check failed: {e}")

        # Check Voice Agent on Jetson
        try:
            # Check if process is running via SSH (quick check)
            result = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=2", f"david@{JETSON_IP}",
                 "pgrep -f sara_voice_agent.py"],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                status["voice_agent"] = {
                    "status": "online",
                    "last_seen": datetime.utcnow().isoformat(),
                    "state": "listening"
                }
            else:
                status["voice_agent"] = {"status": "offline"}
        except Exception as e:
            logger.debug(f"Voice agent check failed: {e}")
            status["voice_agent"] = {"status": "unknown", "error": str(e)}

    return status


@router.get("/events")
async def stream_sensory_events(request: Request, current_user=Depends(get_current_user)):
    """Stream real-time sensory events via SSE."""

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events from Redis pub/sub and Jetson logs."""

        # Connect to Redis for events
        try:
            r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            pubsub = r.pubsub()
            pubsub.subscribe("sensory:events")
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            r = None
            pubsub = None

        # Start background task to tail Jetson logs
        log_queue: asyncio.Queue = asyncio.Queue()
        log_task = asyncio.create_task(tail_jetson_logs(log_queue))

        last_status_check = datetime.utcnow()

        try:
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                # Check for Redis events
                if pubsub:
                    message = pubsub.get_message(timeout=0.1)
                    if message and message["type"] == "message":
                        try:
                            data = json.loads(message["data"])
                            yield f"data: {json.dumps({'type': 'audio_event', 'event': data})}\n\n"
                        except json.JSONDecodeError:
                            pass

                # Check for Jetson log lines
                try:
                    while not log_queue.empty():
                        log_line = log_queue.get_nowait()
                        yield f"data: {json.dumps({'type': 'jetson_log', 'log': log_line})}\n\n"
                except asyncio.QueueEmpty:
                    pass

                # Periodic status update (every 10 seconds)
                now = datetime.utcnow()
                if (now - last_status_check).seconds >= 10:
                    last_status_check = now
                    # Could emit status update here if needed

                await asyncio.sleep(0.1)

        finally:
            log_task.cancel()
            if pubsub:
                pubsub.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


async def tail_jetson_logs(queue: asyncio.Queue):
    """Tail the voice agent logs on Jetson and push to queue."""
    try:
        process = await asyncio.create_subprocess_exec(
            "ssh", "-o", "ConnectTimeout=5", f"david@{JETSON_IP}",
            "tail", "-f", "/tmp/voice_agent.log",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        while True:
            line = await process.stdout.readline()
            if not line:
                break

            decoded = line.decode().strip()
            if decoded:
                # Filter out noise (ping/pong messages)
                if "PING" not in decoded and "PONG" not in decoded and "keepalive" not in decoded:
                    await queue.put(decoded)

    except asyncio.CancelledError:
        process.terminate()
    except Exception as e:
        logger.error(f"Failed to tail Jetson logs: {e}")


@router.post("/events/publish")
async def publish_sensory_event(
    event_type: str,
    content: str,
    speaker: Optional[str] = None,
    confidence: Optional[float] = None,
    source: str = "jetson_microphone"
):
    """
    Publish a sensory event (called by Jetson voice agent or GPU cluster).

    This endpoint:
    1. Checks if PC is playing audio (filter speaker output)
    2. Broadcasts to connected monitor clients (real-time UI)
    3. Stores transcriptions in raw buffer for cognitive processing
    """
    try:
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

        # Check if PC is playing audio - if so, this might be speaker output
        playback_state = r.get("sensory:audio_playback")
        is_pc_playing = False
        if playback_state:
            try:
                state = json.loads(playback_state)
                is_pc_playing = state.get("is_playing", False)
            except:
                pass

        event = {
            "id": f"{datetime.utcnow().timestamp()}",
            "timestamp": datetime.utcnow().isoformat(),
            "type": event_type,
            "content": content,
            "speaker": speaker,
            "confidence": confidence,
            "during_playback": is_pc_playing
        }

        # Publish for real-time UI updates (always, for monitoring)
        r.publish("sensory:events", json.dumps(event))

        # If this is a transcription, decide whether to store
        cognitive_queued = False
        if event_type == "transcription" and content:
            if is_pc_playing:
                # PC is playing audio - likely speaker output, skip cognitive processing
                # but still log for the UI with a tag
                logger.debug(f"Skipping transcription during playback: {content[:50]}...")
                event["filtered_reason"] = "pc_audio_playback"
            else:
                # No playback - this is likely real speech, process it
                from app.tasks.input_processing import process_audio_input
                process_audio_input.delay(
                    transcript=content,
                    speaker=speaker,
                    source=source,
                    diarization={"confidence": confidence} if confidence else None
                )
                cognitive_queued = True
                logger.info(f"Audio transcription queued for cognitive processing: {content[:50]}...")

        return {
            "status": "published",
            "event_id": event["id"],
            "cognitive_queued": cognitive_queued,
            "filtered_playback": is_pc_playing
        }

    except Exception as e:
        logger.error(f"Failed to publish event: {e}")
        return {"status": "error", "detail": str(e)}


@router.post("/audio-playback")
async def update_audio_playback(
    is_playing: bool,
    volume_level: float = 0.0,
    applications: Optional[str] = None
):
    """
    Update audio playback state from desktop agent.

    When the PC is playing audio through speakers, the Jetson mic will
    pick it up. This endpoint lets the desktop agent inform us so we can
    filter out speaker audio from transcriptions.
    """
    try:
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

        playback_state = {
            "is_playing": is_playing,
            "volume_level": volume_level,
            "applications": applications.split(",") if applications else [],
            "updated_at": datetime.utcnow().isoformat()
        }

        # Store with 30 second TTL (desktop agent should update every few seconds)
        r.setex("sensory:audio_playback", 30, json.dumps(playback_state))

        logger.debug(f"Audio playback state: {'playing' if is_playing else 'stopped'}")
        return {"status": "updated", "is_playing": is_playing}

    except Exception as e:
        logger.error(f"Failed to update audio playback state: {e}")
        return {"status": "error", "detail": str(e)}


@router.get("/audio-playback")
async def get_audio_playback():
    """Get current audio playback state."""
    try:
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        state = r.get("sensory:audio_playback")

        if state:
            return json.loads(state)
        return {"is_playing": False, "volume_level": 0.0, "applications": [], "updated_at": None}

    except Exception as e:
        return {"is_playing": False, "error": str(e)}


@router.get("/speakers")
async def get_enrolled_speakers(current_user=Depends(get_current_user)):
    """Get list of enrolled speakers from NeMo service."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{NEMO_URL}/speakers")
            if response.status_code == 200:
                return response.json()
            return {"speakers": [], "error": "Failed to fetch speakers"}
    except Exception as e:
        return {"speakers": [], "error": str(e)}


@router.get("/jetson-logs")
async def get_jetson_logs(
    lines: int = 50,
    current_user=Depends(get_current_user)
):
    """Get recent logs from the Jetson voice agent."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=3", "-o", "StrictHostKeyChecking=no",
             f"david@{JETSON_IP}", f"tail -{lines} /tmp/voice_agent.log"],
            capture_output=True,
            timeout=10,
            text=True
        )

        if result.returncode == 0:
            # Filter out noise
            logs = [
                line for line in result.stdout.strip().split('\n')
                if line and 'PING' not in line and 'PONG' not in line and 'keepalive' not in line
            ]
            return {"logs": logs[-lines:], "status": "connected"}
        else:
            return {"logs": [], "status": "error", "error": result.stderr}

    except subprocess.TimeoutExpired:
        return {"logs": [], "status": "timeout"}
    except Exception as e:
        logger.error(f"Failed to get Jetson logs: {e}")
        return {"logs": [], "status": "error", "error": str(e)}


@router.get("/recent-audio")
async def get_recent_audio_events(
    limit: int = 20,
    current_user=Depends(get_current_user)
):
    """Get recent audio processing events from Redis."""
    try:
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

        # Get from raw buffer stream
        events = r.xrevrange("raw_buffer:audio", count=limit)

        return {
            "events": [
                {
                    "id": e[0],
                    "timestamp": e[1].get("timestamp"),
                    "type": "transcription",
                    "content": e[1].get("transcript", ""),
                    "speaker": e[1].get("speaker"),
                    "source": e[1].get("source")
                }
                for e in events
            ]
        }
    except Exception as e:
        logger.error(f"Failed to get recent audio: {e}")
        return {"events": [], "error": str(e)}
