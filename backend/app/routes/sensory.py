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
JETSON_IP = os.getenv("JETSON_IP", "10.185.1.155")
JETSON_SSH_USER = os.getenv("JETSON_SSH_USER", "david")
JETSON_SSH_TARGET = f"{JETSON_SSH_USER}@{JETSON_IP}"

GPU_CLUSTER_IP = os.getenv("GPU_CLUSTER_IP", "10.185.1.8")
GPU_CLUSTER_SSH_USER = os.getenv("GPU_CLUSTER_SSH_USER", "david")
GPU_CLUSTER_SSH_TARGET = f"{GPU_CLUSTER_SSH_USER}@{GPU_CLUSTER_IP}"

NEMO_URL = os.getenv("NEMO_URL", f"http://{GPU_CLUSTER_IP}:8002")
WHISPER_URL = os.getenv("WHISPER_URL", f"http://{GPU_CLUSTER_IP}:8585")


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
                ["ssh", "-o", "ConnectTimeout=2", JETSON_SSH_TARGET,
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
            "ssh", "-o", "ConnectTimeout=5", JETSON_SSH_TARGET,
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
             JETSON_SSH_TARGET, f"tail -{lines} /tmp/voice_agent.log"],
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


# ==========================================
# SPEAKER ENROLLMENT MANAGEMENT
# ==========================================

class RecordingRequest(BaseModel):
    duration_seconds: int = 10  # How long to record
    prompt: Optional[str] = None  # What the user should say


class EnrollmentStatus(BaseModel):
    status: str  # 'idle', 'recording', 'processing', 'complete', 'error'
    speaker_id: Optional[str] = None
    progress: Optional[float] = None  # 0-100
    samples_collected: int = 0
    samples_needed: int = 3
    message: Optional[str] = None


# Store recording state in Redis
ENROLLMENT_STATE_KEY = "sensory:enrollment_state"
ENROLLMENT_SAMPLES_DIR = "/tmp/enrollment_samples"


@router.get("/speakers/enrollment-status")
async def get_enrollment_status(current_user=Depends(get_current_user)):
    """Get current enrollment recording status."""
    try:
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        state = r.get(ENROLLMENT_STATE_KEY)

        if state:
            return json.loads(state)
        return EnrollmentStatus(status="idle").dict()
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/speakers/{speaker_id}/start-recording")
async def start_speaker_recording(
    speaker_id: str,
    request: RecordingRequest,
    current_user=Depends(get_current_user)
):
    """
    Start recording audio on Jetson for speaker enrollment.

    The Jetson will record for the specified duration and save the audio file.
    Poll /speakers/enrollment-status for progress.
    """
    try:
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

        # Check if already recording
        current_state = r.get(ENROLLMENT_STATE_KEY)
        if current_state:
            state = json.loads(current_state)
            if state.get("status") == "recording":
                return {"status": "error", "message": "Already recording"}

        # Initialize enrollment state
        state = {
            "status": "recording",
            "speaker_id": speaker_id,
            "progress": 0,
            "samples_collected": 0,
            "samples_needed": 3,
            "duration_seconds": request.duration_seconds,
            "started_at": datetime.utcnow().isoformat(),
            "message": f"Recording... Please speak naturally for {request.duration_seconds} seconds."
        }
        r.setex(ENROLLMENT_STATE_KEY, 300, json.dumps(state))  # 5 min TTL

        # Trigger Jetson to record via SSH
        # The recording script will update Redis with progress
        import asyncio
        asyncio.create_task(record_on_jetson(speaker_id, request.duration_seconds, r))

        return {"status": "started", "speaker_id": speaker_id, "duration": request.duration_seconds}

    except Exception as e:
        logger.error(f"Failed to start recording: {e}")
        return {"status": "error", "message": str(e)}


async def record_on_jetson(speaker_id: str, duration: int, redis_client):
    """Background task to trigger Jetson recording."""
    import shutil

    try:
        # Create local directory for samples
        sample_dir = f"{ENROLLMENT_SAMPLES_DIR}/{speaker_id}"
        os.makedirs(sample_dir, exist_ok=True)

        # Count existing samples
        existing = len([f for f in os.listdir(sample_dir) if f.endswith('.wav')]) if os.path.exists(sample_dir) else 0
        sample_num = existing

        # Update state
        state = {
            "status": "recording",
            "speaker_id": speaker_id,
            "progress": 10,
            "samples_collected": existing,
            "samples_needed": 3,
            "message": f"Recording sample {sample_num + 1}..."
        }
        redis_client.setex(ENROLLMENT_STATE_KEY, 300, json.dumps(state))

        # SSH to Jetson and record using arecord
        output_file = f"/tmp/enrollment_{speaker_id}_{sample_num}.wav"

        process = await asyncio.create_subprocess_exec(
            "ssh", "-o", "ConnectTimeout=5", JETSON_SSH_TARGET,
            f"arecord -d {duration} -f cd -t wav {output_file}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Wait for recording with progress updates
        for i in range(duration):
            await asyncio.sleep(1)
            progress = 10 + int((i / duration) * 70)
            state["progress"] = progress
            state["message"] = f"Recording... {duration - i - 1}s remaining"
            redis_client.setex(ENROLLMENT_STATE_KEY, 300, json.dumps(state))

        await process.wait()

        # Copy file from Jetson
        state["status"] = "processing"
        state["progress"] = 85
        state["message"] = "Transferring audio..."
        redis_client.setex(ENROLLMENT_STATE_KEY, 300, json.dumps(state))

        local_file = f"{sample_dir}/sample_{sample_num}.wav"
        scp_process = await asyncio.create_subprocess_exec(
            "scp", f"{JETSON_SSH_TARGET}:{output_file}", local_file,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await scp_process.wait()

        # Clean up on Jetson
        await asyncio.create_subprocess_exec(
            "ssh", JETSON_SSH_TARGET, f"rm -f {output_file}"
        )

        # Update final state
        samples_now = len([f for f in os.listdir(sample_dir) if f.endswith('.wav')])
        state["status"] = "complete"
        state["progress"] = 100
        state["samples_collected"] = samples_now
        state["message"] = f"Sample {sample_num + 1} recorded. {3 - samples_now} more needed." if samples_now < 3 else "All samples collected! Ready to enroll."
        redis_client.setex(ENROLLMENT_STATE_KEY, 300, json.dumps(state))

        logger.info(f"Recording complete for {speaker_id}, sample {sample_num}")

    except Exception as e:
        logger.error(f"Recording failed: {e}")
        state = {
            "status": "error",
            "speaker_id": speaker_id,
            "progress": 0,
            "message": f"Recording failed: {str(e)}"
        }
        redis_client.setex(ENROLLMENT_STATE_KEY, 300, json.dumps(state))


@router.post("/speakers/{speaker_id}/enroll")
async def enroll_speaker(
    speaker_id: str,
    display_name: Optional[str] = None,
    current_user=Depends(get_current_user)
):
    """
    Enroll a speaker using collected audio samples.

    Must have at least 1 sample (3 recommended) in the samples directory.
    """
    try:
        sample_dir = f"{ENROLLMENT_SAMPLES_DIR}/{speaker_id}"

        if not os.path.exists(sample_dir):
            return {"status": "error", "message": "No samples found. Record samples first."}

        samples = [f for f in os.listdir(sample_dir) if f.endswith('.wav')]
        if len(samples) == 0:
            return {"status": "error", "message": "No audio samples found."}

        # Copy samples to GPU cluster
        gpu_sample_dir = f"/home/david/data/speakers/{speaker_id}_samples"

        # Create directory on GPU cluster
        mkdir_result = subprocess.run(
            ["ssh", GPU_CLUSTER_SSH_TARGET, f"mkdir -p {gpu_sample_dir}"],
            capture_output=True,
            timeout=10
        )

        # Copy all samples
        audio_paths = []
        for sample in samples:
            local_path = f"{sample_dir}/{sample}"
            remote_path = f"{gpu_sample_dir}/{sample}"

            scp_result = subprocess.run(
                ["scp", local_path, f"{GPU_CLUSTER_SSH_TARGET}:{remote_path}"],
                capture_output=True,
                timeout=30
            )

            if scp_result.returncode == 0:
                # Path inside NeMo container
                audio_paths.append(f"/data/speakers/{speaker_id}_samples/{sample}")

        if len(audio_paths) == 0:
            return {"status": "error", "message": "Failed to transfer samples to GPU cluster."}

        # Call NeMo enrollment API
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{NEMO_URL}/enroll",
                json={
                    "speaker_id": speaker_id,
                    "audio_paths": audio_paths
                }
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Speaker {speaker_id} enrolled successfully")

                # Clear enrollment state
                r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
                r.delete(ENROLLMENT_STATE_KEY)

                return {
                    "status": "success",
                    "speaker_id": speaker_id,
                    "display_name": display_name or speaker_id,
                    "num_samples": len(audio_paths)
                }
            else:
                return {"status": "error", "message": f"NeMo enrollment failed: {response.text}"}

    except Exception as e:
        logger.error(f"Enrollment failed: {e}")
        return {"status": "error", "message": str(e)}


@router.delete("/speakers/{speaker_id}")
async def delete_speaker(
    speaker_id: str,
    current_user=Depends(get_current_user)
):
    """Delete an enrolled speaker."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.delete(f"{NEMO_URL}/speakers/{speaker_id}")

            if response.status_code == 200:
                # Also clean up local samples
                sample_dir = f"{ENROLLMENT_SAMPLES_DIR}/{speaker_id}"
                if os.path.exists(sample_dir):
                    import shutil
                    shutil.rmtree(sample_dir)

                # Clean up on GPU cluster
                subprocess.run(
                    ["ssh", GPU_CLUSTER_SSH_TARGET,
                     f"rm -rf /home/david/data/speakers/{speaker_id}_samples /home/david/data/speakers/{speaker_id}.json"],
                    capture_output=True,
                    timeout=10
                )

                return {"status": "success", "message": f"Speaker {speaker_id} deleted"}
            else:
                return {"status": "error", "message": f"Failed to delete: {response.text}"}

    except Exception as e:
        logger.error(f"Delete speaker failed: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/speakers/{speaker_id}/clear-samples")
async def clear_speaker_samples(
    speaker_id: str,
    current_user=Depends(get_current_user)
):
    """Clear recorded samples for a speaker (to start over)."""
    try:
        sample_dir = f"{ENROLLMENT_SAMPLES_DIR}/{speaker_id}"
        if os.path.exists(sample_dir):
            import shutil
            shutil.rmtree(sample_dir)
            os.makedirs(sample_dir)

        # Reset enrollment state
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        state = {
            "status": "idle",
            "speaker_id": speaker_id,
            "samples_collected": 0,
            "samples_needed": 3,
            "message": "Samples cleared. Ready to record."
        }
        r.setex(ENROLLMENT_STATE_KEY, 60, json.dumps(state))

        return {"status": "success", "message": "Samples cleared"}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/speakers/{speaker_id}/samples")
async def get_speaker_samples(
    speaker_id: str,
    current_user=Depends(get_current_user)
):
    """Get info about collected samples for a speaker."""
    try:
        sample_dir = f"{ENROLLMENT_SAMPLES_DIR}/{speaker_id}"

        if not os.path.exists(sample_dir):
            return {"samples": [], "count": 0}

        samples = []
        for f in sorted(os.listdir(sample_dir)):
            if f.endswith('.wav'):
                path = os.path.join(sample_dir, f)
                samples.append({
                    "filename": f,
                    "size_bytes": os.path.getsize(path),
                    "created": datetime.fromtimestamp(os.path.getctime(path)).isoformat()
                })

        return {"samples": samples, "count": len(samples)}

    except Exception as e:
        return {"samples": [], "count": 0, "error": str(e)}


# WebSocket connection to Jetson for wake word control
import websockets

@router.post("/voice-agent/listening")
async def set_voice_listening(
    request: Request,
    current_user=Depends(get_current_user)
):
    """Enable or disable wake word listening on the Jetson voice agent."""
    try:
        body = await request.json()
        enabled = body.get("enabled", True)

        # Connect to Jetson voice agent WebSocket
        uri = f"ws://{JETSON_IP}:8765"

        async with websockets.connect(uri, close_timeout=5) as ws:
            # Send command
            await ws.send(json.dumps({
                "type": "set_listening",
                "enabled": enabled
            }))

            # Wait for confirmation
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=2.0)
                data = json.loads(response)
                if data.get("type") == "listening_status":
                    return {
                        "status": "success",
                        "listening_enabled": data.get("enabled", enabled)
                    }
            except asyncio.TimeoutError:
                pass

            return {
                "status": "success",
                "listening_enabled": enabled
            }

    except Exception as e:
        logger.error(f"Failed to set voice listening: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/voice-agent/listening")
async def get_voice_listening(current_user=Depends(get_current_user)):
    """Get current wake word listening status from Jetson voice agent."""
    try:
        uri = f"ws://{JETSON_IP}:8765"

        async with websockets.connect(uri, close_timeout=5) as ws:
            # Request status
            await ws.send(json.dumps({"type": "get_status"}))

            try:
                response = await asyncio.wait_for(ws.recv(), timeout=2.0)
                data = json.loads(response)
                if data.get("type") == "listening_status":
                    return {
                        "status": "success",
                        "listening_enabled": data.get("enabled", True)
                    }
            except asyncio.TimeoutError:
                pass

            return {"status": "unknown", "listening_enabled": True}

    except Exception as e:
        logger.error(f"Failed to get voice listening status: {e}")
        return {"status": "error", "listening_enabled": True}


# ── Jetson Health & Sensory Events (new voice+vision system) ──

class JetsonHealthReport(BaseModel):
    uptime_seconds: float = 0
    cpu_percent: float = 0
    memory_percent: float = 0
    memory_used_mb: int = 0
    gpu_available: bool = False
    gpu_temperature_c: int = 0
    gpu_memory_total_mb: int = 0
    gpu_memory_used_mb: int = 0
    gpu_memory_free_mb: int = 0
    gpu_utilization_pct: int = 0
    service_state: str = "unknown"


class FaceDetectedEvent(BaseModel):
    is_david: bool = False
    confidence: float = 0.0
    similarity: float = 0.0
    source: str = "jetson_obsbot"
    timestamp: Optional[float] = None


class PresenceChangedEvent(BaseModel):
    state: str  # "present", "absent", "unknown"
    reason: str = ""
    source: str = "jetson_obsbot"
    timestamp: Optional[float] = None


class ConversationStartEvent(BaseModel):
    source: str = "jetson_voice"
    timestamp: Optional[float] = None


class ConversationEndEvent(BaseModel):
    turns: int = 0
    duration_seconds: float = 0.0
    summary: str = ""
    source: str = "jetson_voice"
    timestamp: Optional[float] = None


@router.post("/jetson/health")
async def report_jetson_health(
    report: JetsonHealthReport,
    current_user=Depends(get_current_user),
):
    """Receive Jetson health report — store in Redis with 60s TTL."""
    try:
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        r.setex("sara:jetson:health", 60, json.dumps(report.dict()))
        r.setex("sara:jetson:online", 90, "1")

        # Update unified context
        try:
            from app.services.unified_context import read_snapshot, write_snapshot
            snapshot = await read_snapshot(current_user.id)
            snapshot.jetson_online = True
            await write_snapshot(current_user.id, snapshot)
        except Exception as e:
            logger.debug(f"Couldn't update unified context: {e}")

        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Jetson health report failed: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/jetson/health")
async def get_jetson_health(current_user=Depends(get_current_user)):
    """Get latest Jetson health report from Redis."""
    try:
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        data = r.get("sara:jetson:health")
        online = r.get("sara:jetson:online")
        if data:
            health = json.loads(data)
            health["online"] = online == "1"
            return health
        return {"online": False, "service_state": "no_report"}
    except Exception as e:
        return {"online": False, "error": str(e)}


@router.post("/vision/face-detected")
async def report_face_detected(
    event: FaceDetectedEvent,
    current_user=Depends(get_current_user),
):
    """Report face detection from Jetson vision system."""
    try:
        from app.services.event_bus import emit_event, EventType
        from app.services.activity_state_machine import activity_state_machine, ActivitySignal

        # Emit event bus event
        await emit_event(
            EventType.FACE_DETECTED,
            user_id=current_user.id,
            payload={
                "is_david": event.is_david,
                "confidence": event.confidence,
                "similarity": event.similarity,
            },
            source=event.source,
        )

        # Feed activity state machine
        if event.is_david:
            activity_state_machine.process_signal(ActivitySignal(
                signal_type="face",
                source=event.source,
                value="david_detected",
                metadata={"is_david": True, "confidence": event.confidence},
            ))

        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Face detected report failed: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/vision/presence-changed")
async def report_presence_changed(
    event: PresenceChangedEvent,
    current_user=Depends(get_current_user),
):
    """Report desk presence change from Jetson vision system."""
    try:
        from app.services.event_bus import emit_event, EventType
        from app.services.activity_state_machine import activity_state_machine, ActivitySignal

        # Emit event bus event
        await emit_event(
            EventType.DESK_PRESENCE_CHANGED,
            user_id=current_user.id,
            payload={"state": event.state, "reason": event.reason},
            source=event.source,
        )

        # Feed activity state machine
        activity_state_machine.process_signal(ActivitySignal(
            signal_type="desk_presence",
            source=event.source,
            value=event.state,
            metadata={"reason": event.reason},
        ))

        # Update unified context
        try:
            from app.services.unified_context import read_snapshot, write_snapshot
            snapshot = await read_snapshot(current_user.id)
            snapshot.desk_presence = (event.state == "present")
            await write_snapshot(current_user.id, snapshot)
        except Exception as e:
            logger.debug(f"Couldn't update unified context: {e}")

        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Presence changed report failed: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/voice/conversation-started")
async def report_conversation_started(
    event: ConversationStartEvent,
    current_user=Depends(get_current_user),
):
    """Report voice conversation start from Jetson."""
    try:
        from app.services.event_bus import emit_event, EventType

        await emit_event(
            EventType.VOICE_CONVERSATION_STARTED,
            user_id=current_user.id,
            payload={"source": event.source},
            source=event.source,
        )

        # Update unified context
        try:
            from app.services.unified_context import read_snapshot, write_snapshot
            snapshot = await read_snapshot(current_user.id)
            snapshot.voice_conversation_active = True
            await write_snapshot(current_user.id, snapshot)
        except Exception as e:
            logger.debug(f"Couldn't update unified context: {e}")

        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Conversation start report failed: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/voice/conversation-ended")
async def report_conversation_ended(
    event: ConversationEndEvent,
    current_user=Depends(get_current_user),
):
    """Report voice conversation end from Jetson."""
    try:
        from app.services.event_bus import emit_event, EventType

        await emit_event(
            EventType.VOICE_CONVERSATION_ENDED,
            user_id=current_user.id,
            payload={
                "turns": event.turns,
                "duration_seconds": event.duration_seconds,
                "summary": event.summary,
            },
            source=event.source,
        )

        # Update unified context
        try:
            from app.services.unified_context import read_snapshot, write_snapshot
            snapshot = await read_snapshot(current_user.id)
            snapshot.voice_conversation_active = False
            await write_snapshot(current_user.id, snapshot)
        except Exception as e:
            logger.debug(f"Couldn't update unified context: {e}")

        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Conversation end report failed: {e}")
        return {"status": "error", "message": str(e)}
