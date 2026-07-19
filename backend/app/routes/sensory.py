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
import re
import shlex
import shutil
import subprocess
from datetime import datetime
from typing import Optional, AsyncGenerator, Dict, List
from app.core.timezone import now as local_now
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
import redis

from app.main_simple import get_current_user
from app.db.session import get_db
from sqlalchemy.orm import Session
from app.services.voice.control_plane import update_service_heartbeat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sensory", tags=["sensory"])

# Redis for event pub/sub
import os
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# Service endpoints
JETSON_IP = os.getenv("JETSON_IP", "10.185.1.84")
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
                    "last_seen": local_now().isoformat(),
                    "state": "listening"
                }
            else:
                status["voice_agent"] = {"status": "offline"}
        except Exception as e:
            logger.debug(f"Voice agent check failed: {e}")
            status["voice_agent"] = {"status": "unknown", "error": str(e)}

    return status


@router.get("/events")
async def stream_sensory_events(
    request: Request,
    current_user=Depends(get_current_user),
    _auth_db: Session = Depends(get_db),
):
    """Stream real-time sensory events via SSE."""
    # Release the auth session before streaming (Redis-only stream) so it doesn't
    # sit idle-in-transaction and get killed by Postgres after 5 min.
    try:
        _auth_db.close()
    except Exception:
        pass

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

        last_status_check = local_now()

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
                now = local_now()
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
            "id": f"{local_now().timestamp()}",
            "timestamp": local_now().isoformat(),
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
            "updated_at": local_now().isoformat()
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
    kind: str = "positive"  # "positive" (wake phrase) | "negative" (ambient/hard-negative) — wake-word only


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
DATASET_RECORDING_STATE_KEY = "sensory:dataset_recording_state"

VOICE_DATASET_ROOT = os.getenv("VOICE_DATASET_ROOT", "/tmp/voice_datasets")
WAKE_DATASET_ROOT = os.getenv("WAKE_DATASET_ROOT", f"{VOICE_DATASET_ROOT}/wake_word")
SPEAKER_DATASET_ROOT = os.getenv("SPEAKER_DATASET_ROOT", f"{VOICE_DATASET_ROOT}/speakers")

# Remote dataset mirrors used by training workers.
JETSON_WAKE_DATASET_ROOT = os.getenv(
    "JETSON_WAKE_DATASET_ROOT",
    "/home/david/data/wake-word-datasets",
)
GPU_SPEAKER_DATASET_ROOT = os.getenv(
    "GPU_SPEAKER_DATASET_ROOT",
    "/data/enrollment-samples",
)

IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _normalize_identifier(raw_value: str, field_name: str) -> str:
    value = (raw_value or "").strip().lower()
    if not value:
        raise HTTPException(status_code=400, detail=f"{field_name} is required")
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise HTTPException(
            status_code=400,
            detail=(
                f"{field_name} must use lowercase letters, numbers, underscores, or hyphens "
                "(max 64 chars)"
            ),
        )
    return value


def _dataset_sample_dir(dataset_id: str, family: str, speaker_id: Optional[str] = None, kind: str = "positive") -> str:
    if family == "wake_word":
        # Positive samples stay flat in the dataset dir (unchanged — avoids
        # any migration for datasets recorded before negative support
        # existed); negatives (ambient noise, hard negatives against
        # self-trigger) live in their own subdirectory.
        if kind == "negative":
            return os.path.join(WAKE_DATASET_ROOT, dataset_id, "negative")
        return os.path.join(WAKE_DATASET_ROOT, dataset_id)
    if family == "speakers":
        if not speaker_id:
            raise ValueError("speaker_id is required for speaker dataset samples")
        return os.path.join(SPEAKER_DATASET_ROOT, dataset_id, speaker_id)
    raise ValueError(f"Unsupported dataset family: {family}")


def _list_sample_files(sample_dir: str) -> List[Dict[str, object]]:
    if not os.path.exists(sample_dir):
        return []

    samples: List[Dict[str, object]] = []
    for filename in sorted(os.listdir(sample_dir)):
        if not filename.endswith(".wav"):
            continue
        path = os.path.join(sample_dir, filename)
        samples.append(
            {
                "filename": filename,
                "size_bytes": os.path.getsize(path),
                "created": datetime.fromtimestamp(os.path.getctime(path)).isoformat(),
            }
        )
    return samples


def _parse_json_state(raw_state: Optional[str]) -> Optional[Dict[str, object]]:
    if not raw_state:
        return None
    try:
        parsed = json.loads(raw_state)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


def _is_active_recording(state: Optional[Dict[str, object]]) -> bool:
    if not state:
        return False
    return str(state.get("status") or "").lower() in {"recording", "processing"}


def _clear_sample_dir(sample_dir: str) -> int:
    """Delete only the .wav files directly in sample_dir, then the directory
    itself if it's now empty. NOT a recursive rmtree — wake-word "positive"
    samples live in the same parent directory as the "negative" subfolder,
    and clearing one kind must never take the other down with it."""
    if not os.path.exists(sample_dir):
        return 0
    wav_files = [f for f in os.listdir(sample_dir) if f.endswith(".wav")]
    for filename in wav_files:
        os.remove(os.path.join(sample_dir, filename))
    try:
        os.rmdir(sample_dir)  # only succeeds if now empty (e.g. no negative/ subdir left behind)
    except OSError:
        pass
    return len(wav_files)


async def _run_command(*args: str) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_raw, stderr_raw = await process.communicate()
    return (
        process.returncode,
        stdout_raw.decode("utf-8", errors="replace"),
        stderr_raw.decode("utf-8", errors="replace"),
    )


async def _sync_wake_sample_to_jetson(
    dataset_id: str,
    remote_tmp_file: str,
    filename: str,
    kind: str = "positive",
) -> None:
    remote_dataset_dir = f"{JETSON_WAKE_DATASET_ROOT}/{dataset_id}"
    if kind == "negative":
        remote_dataset_dir += "/negative"
    remote_target_path = f"{remote_dataset_dir}/{filename}"
    command = (
        f"mkdir -p {shlex.quote(remote_dataset_dir)} && "
        f"cp {shlex.quote(remote_tmp_file)} {shlex.quote(remote_target_path)}"
    )
    code, _, stderr = await _run_command(
        "ssh",
        "-o",
        "ConnectTimeout=5",
        JETSON_SSH_TARGET,
        command,
    )
    if code != 0:
        raise RuntimeError(f"wake dataset sync to Jetson failed: {stderr.strip()}")


async def _sync_speaker_sample_to_gpu(
    dataset_id: str,
    speaker_id: str,
    local_file: str,
    filename: str,
) -> None:
    remote_dataset_dir = f"{GPU_SPEAKER_DATASET_ROOT}/{dataset_id}/{speaker_id}"
    remote_target_path = f"{remote_dataset_dir}/{filename}"
    mkdir_command = f"mkdir -p {shlex.quote(remote_dataset_dir)}"
    mkdir_code, _, mkdir_stderr = await _run_command(
        "ssh",
        "-o",
        "ConnectTimeout=5",
        GPU_CLUSTER_SSH_TARGET,
        mkdir_command,
    )
    if mkdir_code != 0:
        raise RuntimeError(f"GPU dataset mkdir failed: {mkdir_stderr.strip()}")

    scp_code, _, scp_stderr = await _run_command(
        "scp",
        "-o",
        "ConnectTimeout=5",
        local_file,
        f"{GPU_CLUSTER_SSH_TARGET}:{remote_target_path}",
    )
    if scp_code != 0:
        raise RuntimeError(f"speaker dataset sync to GPU failed: {scp_stderr.strip()}")


async def _record_dataset_clip_on_jetson(
    *,
    dataset_id: str,
    family: str,
    duration_seconds: int,
    redis_client,
    speaker_id: Optional[str] = None,
    prompt: Optional[str] = None,
    kind: str = "positive",
) -> None:
    sample_dir = _dataset_sample_dir(dataset_id, family, speaker_id=speaker_id, kind=kind)
    os.makedirs(sample_dir, exist_ok=True)

    existing = [f for f in os.listdir(sample_dir) if f.endswith(".wav")]
    sample_num = len(existing)
    timestamp = local_now().strftime("%Y%m%d_%H%M%S")
    file_prefix = f"{family}_{dataset_id}"
    if speaker_id:
        file_prefix += f"_{speaker_id}"
    if kind == "negative":
        file_prefix += "_negative"
    filename = f"{file_prefix}_{sample_num:03d}_{timestamp}.wav"
    local_file = os.path.join(sample_dir, filename)
    remote_tmp_file = f"/tmp/{filename}"

    state: Dict[str, object] = {
        "status": "recording",
        "dataset_id": dataset_id,
        "family": family,
        "speaker_id": speaker_id,
        "duration_seconds": duration_seconds,
        "progress": 5,
        "filename": filename,
        "prompt": prompt,
        "message": f"Recording on Jetson for {duration_seconds}s...",
    }
    redis_client.setex(DATASET_RECORDING_STATE_KEY, 600, json.dumps(state))

    record_command = (
        f"arecord -d {duration_seconds} -f cd -t wav {shlex.quote(remote_tmp_file)}"
    )
    process = await asyncio.create_subprocess_exec(
        "ssh",
        "-o",
        "ConnectTimeout=5",
        JETSON_SSH_TARGET,
        record_command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        for elapsed in range(duration_seconds):
            await asyncio.sleep(1)
            progress = 5 + int(((elapsed + 1) / max(duration_seconds, 1)) * 70)
            state["progress"] = progress
            state["message"] = f"Recording... {max(duration_seconds - elapsed - 1, 0)}s remaining"
            redis_client.setex(DATASET_RECORDING_STATE_KEY, 600, json.dumps(state))

        stdout_raw, stderr_raw = await process.communicate()
        if process.returncode != 0:
            stderr = stderr_raw.decode("utf-8", errors="replace").strip()
            stdout = stdout_raw.decode("utf-8", errors="replace").strip()
            raise RuntimeError(stderr or stdout or "arecord failed on Jetson")

        state["status"] = "processing"
        state["progress"] = 82
        state["message"] = "Transferring recorded clip..."
        redis_client.setex(DATASET_RECORDING_STATE_KEY, 600, json.dumps(state))

        scp_code, _, scp_stderr = await _run_command(
            "scp",
            "-o",
            "ConnectTimeout=5",
            f"{JETSON_SSH_TARGET}:{remote_tmp_file}",
            local_file,
        )
        if scp_code != 0:
            raise RuntimeError(f"Failed to copy clip from Jetson: {scp_stderr.strip()}")

        # Keep datasets where training workers expect them.
        if family == "wake_word":
            await _sync_wake_sample_to_jetson(dataset_id, remote_tmp_file, filename, kind=kind)
        elif family == "speakers" and speaker_id:
            await _sync_speaker_sample_to_gpu(dataset_id, speaker_id, local_file, filename)

        sample_count = len([f for f in os.listdir(sample_dir) if f.endswith(".wav")])
        state["status"] = "complete"
        state["progress"] = 100
        state["sample_count"] = sample_count
        state["message"] = "Recording complete."
        redis_client.setex(DATASET_RECORDING_STATE_KEY, 600, json.dumps(state))
    except Exception as e:
        logger.error(f"Dataset recording failed: {e}")
        state["status"] = "error"
        state["progress"] = 0
        state["message"] = f"Recording failed: {str(e)}"
        redis_client.setex(DATASET_RECORDING_STATE_KEY, 600, json.dumps(state))
    finally:
        await _run_command(
            "ssh",
            "-o",
            "ConnectTimeout=5",
            JETSON_SSH_TARGET,
            f"rm -f {shlex.quote(remote_tmp_file)}",
        )


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


# ==========================================
# DATASET RECORDING FOR WAKE/SPEAKER LABS
# ==========================================

@router.get("/datasets/recording-status")
async def get_dataset_recording_status(current_user=Depends(get_current_user)):
    """Get current dataset recording task status."""
    try:
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        state = _parse_json_state(r.get(DATASET_RECORDING_STATE_KEY))
        if state:
            return state
        return {"status": "idle"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/datasets/{dataset_id}/wake-word/start-recording")
async def start_wake_dataset_recording(
    dataset_id: str,
    request: RecordingRequest,
    current_user=Depends(get_current_user),
):
    """Record one wake-word training clip from Jetson into a dataset."""
    try:
        normalized_dataset_id = _normalize_identifier(dataset_id, "dataset_id")
        duration = max(2, min(int(request.duration_seconds), 60))
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

        active_dataset_state = _parse_json_state(r.get(DATASET_RECORDING_STATE_KEY))
        active_enrollment_state = _parse_json_state(r.get(ENROLLMENT_STATE_KEY))
        if _is_active_recording(active_dataset_state) or _is_active_recording(active_enrollment_state):
            return {"status": "error", "message": "A recording is already in progress"}

        kind = "negative" if request.kind == "negative" else "positive"
        asyncio.create_task(
            _record_dataset_clip_on_jetson(
                dataset_id=normalized_dataset_id,
                family="wake_word",
                duration_seconds=duration,
                redis_client=r,
                prompt=request.prompt,
                kind=kind,
            )
        )
        return {
            "status": "started",
            "dataset_id": normalized_dataset_id,
            "family": "wake_word",
            "kind": kind,
            "duration_seconds": duration,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start wake dataset recording: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/datasets/{dataset_id}/speakers/{speaker_id}/start-recording")
async def start_speaker_dataset_recording(
    dataset_id: str,
    speaker_id: str,
    request: RecordingRequest,
    current_user=Depends(get_current_user),
):
    """Record one speaker training clip from Jetson into a dataset."""
    try:
        normalized_dataset_id = _normalize_identifier(dataset_id, "dataset_id")
        normalized_speaker_id = _normalize_identifier(speaker_id, "speaker_id")
        duration = max(2, min(int(request.duration_seconds), 60))
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

        active_dataset_state = _parse_json_state(r.get(DATASET_RECORDING_STATE_KEY))
        active_enrollment_state = _parse_json_state(r.get(ENROLLMENT_STATE_KEY))
        if _is_active_recording(active_dataset_state) or _is_active_recording(active_enrollment_state):
            return {"status": "error", "message": "A recording is already in progress"}

        asyncio.create_task(
            _record_dataset_clip_on_jetson(
                dataset_id=normalized_dataset_id,
                family="speakers",
                duration_seconds=duration,
                redis_client=r,
                speaker_id=normalized_speaker_id,
                prompt=request.prompt,
            )
        )
        return {
            "status": "started",
            "dataset_id": normalized_dataset_id,
            "family": "speakers",
            "speaker_id": normalized_speaker_id,
            "duration_seconds": duration,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start speaker dataset recording: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/datasets/{dataset_id}/wake-word/samples")
async def get_wake_dataset_samples(
    dataset_id: str,
    kind: str = "positive",
    current_user=Depends(get_current_user),
):
    """List wake-word dataset clips recorded via Jetson. `kind=negative`
    lists the ambient/hard-negative recordings instead of wake phrases."""
    normalized_dataset_id = _normalize_identifier(dataset_id, "dataset_id")
    resolved_kind = "negative" if kind == "negative" else "positive"
    sample_dir = _dataset_sample_dir(normalized_dataset_id, "wake_word", kind=resolved_kind)
    samples = _list_sample_files(sample_dir)
    return {
        "dataset_id": normalized_dataset_id,
        "family": "wake_word",
        "kind": resolved_kind,
        "samples": samples,
        "count": len(samples),
    }


@router.get("/datasets/{dataset_id}/speakers/{speaker_id}/samples")
async def get_speaker_dataset_samples(
    dataset_id: str,
    speaker_id: str,
    current_user=Depends(get_current_user),
):
    """List speaker dataset clips recorded via Jetson."""
    normalized_dataset_id = _normalize_identifier(dataset_id, "dataset_id")
    normalized_speaker_id = _normalize_identifier(speaker_id, "speaker_id")
    sample_dir = _dataset_sample_dir(
        normalized_dataset_id,
        "speakers",
        speaker_id=normalized_speaker_id,
    )
    samples = _list_sample_files(sample_dir)
    return {
        "dataset_id": normalized_dataset_id,
        "family": "speakers",
        "speaker_id": normalized_speaker_id,
        "samples": samples,
        "count": len(samples),
    }


@router.delete("/datasets/{dataset_id}/wake-word/samples")
async def clear_wake_dataset_samples(
    dataset_id: str,
    kind: str = "positive",
    current_user=Depends(get_current_user),
):
    """Clear wake-word samples for one dataset. `kind=negative` clears only
    the ambient/hard-negative recordings, leaving wake-phrase positives (or
    vice versa) untouched."""
    normalized_dataset_id = _normalize_identifier(dataset_id, "dataset_id")
    resolved_kind = "negative" if kind == "negative" else "positive"
    sample_dir = _dataset_sample_dir(normalized_dataset_id, "wake_word", kind=resolved_kind)
    deleted_count = _clear_sample_dir(sample_dir)

    remote_dataset_dir = f"{JETSON_WAKE_DATASET_ROOT}/{normalized_dataset_id}"
    if resolved_kind == "negative":
        remote_dataset_dir += "/negative"
        remote_clear_command = f"rm -rf {shlex.quote(remote_dataset_dir)}"
    else:
        # Positive samples are flat files in the dataset dir — remove only
        # the .wav files, not the directory (the negative/ subdir lives
        # alongside them and must survive a "clear positives" call).
        remote_clear_command = f"find {shlex.quote(remote_dataset_dir)} -maxdepth 1 -name '*.wav' -delete"
    clear_code, _, clear_stderr = await _run_command(
        "ssh",
        "-o",
        "ConnectTimeout=5",
        JETSON_SSH_TARGET,
        remote_clear_command,
    )
    warnings: List[str] = []
    if clear_code != 0:
        warnings.append(f"Jetson mirror clear failed: {clear_stderr.strip()}")

    return {
        "status": "success",
        "dataset_id": normalized_dataset_id,
        "family": "wake_word",
        "kind": resolved_kind,
        "deleted_count": deleted_count,
        "warnings": warnings,
    }


@router.delete("/datasets/{dataset_id}/speakers/{speaker_id}/samples")
async def clear_speaker_dataset_samples(
    dataset_id: str,
    speaker_id: str,
    current_user=Depends(get_current_user),
):
    """Clear speaker samples for one dataset + speaker id."""
    normalized_dataset_id = _normalize_identifier(dataset_id, "dataset_id")
    normalized_speaker_id = _normalize_identifier(speaker_id, "speaker_id")
    sample_dir = _dataset_sample_dir(
        normalized_dataset_id,
        "speakers",
        speaker_id=normalized_speaker_id,
    )
    deleted_count = _clear_sample_dir(sample_dir)

    remote_dataset_dir = (
        f"{GPU_SPEAKER_DATASET_ROOT}/{normalized_dataset_id}/{normalized_speaker_id}"
    )
    clear_code, _, clear_stderr = await _run_command(
        "ssh",
        "-o",
        "ConnectTimeout=5",
        GPU_CLUSTER_SSH_TARGET,
        f"rm -rf {shlex.quote(remote_dataset_dir)}",
    )
    warnings: List[str] = []
    if clear_code != 0:
        warnings.append(f"GPU mirror clear failed: {clear_stderr.strip()}")

    return {
        "status": "success",
        "dataset_id": normalized_dataset_id,
        "family": "speakers",
        "speaker_id": normalized_speaker_id,
        "deleted_count": deleted_count,
        "warnings": warnings,
    }


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
            "started_at": local_now().isoformat(),
            "message": f"Recording... Please speak naturally for {request.duration_seconds} seconds."
        }
        r.setex(ENROLLMENT_STATE_KEY, 300, json.dumps(state))  # 5 min TTL

        # Trigger Jetson to record via SSH
        # The recording script will update Redis with progress
        asyncio.create_task(record_on_jetson(speaker_id, request.duration_seconds, r))

        return {"status": "started", "speaker_id": speaker_id, "duration": request.duration_seconds}

    except Exception as e:
        logger.error(f"Failed to start recording: {e}")
        return {"status": "error", "message": str(e)}


async def record_on_jetson(speaker_id: str, duration: int, redis_client):
    """Background task to trigger Jetson recording."""
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


async def request_jetson_stop() -> bool:
    """Relay a CANCEL_SPEECH request to the Jetson's desktop_bridge control
    channel (B2.6) — same connect-send-disconnect pattern as
    set_voice_listening. Returns True if the message was sent (the Jetson
    doesn't ack this one; the stop takes effect immediately on its side)."""
    try:
        uri = f"ws://{JETSON_IP}:8765"
        async with websockets.connect(uri, close_timeout=5) as ws:
            await ws.send(json.dumps({"type": "request_stop"}))
        return True
    except Exception as e:
        logger.debug(f"Jetson stop relay failed (may simply be offline): {e}")
        return False


async def speak_via_jetson(text: str) -> bool:
    """Relay a proactive spoken one-liner to the Jetson (Desktop Jarvis
    Overhaul D) — same connect-send-disconnect pattern as
    request_jetson_stop(). The Jetson declines to actually speak if it's
    mid-conversation; the caller's own urgency/interruptibility/daily-cap
    gating (see unified_notification.py) is the real gate, this is just
    the relay."""
    try:
        uri = f"ws://{JETSON_IP}:8765"
        async with websockets.connect(uri, close_timeout=5) as ws:
            await ws.send(json.dumps({"type": "speak_proactive", "text": text}))
        return True
    except Exception as e:
        logger.debug(f"Jetson proactive speak relay failed (may simply be offline): {e}")
        return False


@router.post("/voice-agent/stop")
async def stop_voice_agent_speech(
    current_user=Depends(get_current_user)
):
    """Halt any in-progress Jetson TTS playback (CANCEL_SPEECH from any
    surface — desktop hotkey/HUD, webapp/iOS mute)."""
    sent = await request_jetson_stop()
    return {"status": "success" if sent else "unreachable"}


async def relay_media_state(playing: bool) -> bool:
    """Relay a desktop media_state change to the Jetson (B2.4) so it can
    boost wake-word/barge-in sensitivity requirements while music/video is
    playing, instead of treating it as a quiet room."""
    try:
        uri = f"ws://{JETSON_IP}:8765"
        async with websockets.connect(uri, close_timeout=5) as ws:
            await ws.send(json.dumps({"type": "media_state", "playing": playing}))
        return True
    except Exception as e:
        logger.debug(f"Jetson media_state relay failed (may simply be offline): {e}")
        return False


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
    cpu_temperature_c: float = 0
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

        # Bridge Jetson sensory reports into voice-control heartbeat state so
        # the wake sensor card reflects current device health.
        try:
            service_state = (report.service_state or "").strip().lower()
            if service_state in {"offline", "stopped"}:
                wake_status = "offline"
            elif service_state in {"error", "failed"}:
                wake_status = "degraded"
            else:
                wake_status = "healthy"

            update_service_heartbeat(
                "wake-sensor",
                {
                    "status": wake_status,
                    "version": "jetson-health-bridge-v1",
                    "details": {
                        "service_state": report.service_state,
                        "uptime_seconds": report.uptime_seconds,
                        "cpu_percent": report.cpu_percent,
                        "cpu_temp_c": report.cpu_temperature_c,
                        "memory_percent": report.memory_percent,
                        "gpu_temp_c": report.gpu_temperature_c,
                        "gpu_utilization_pct": report.gpu_utilization_pct,
                    },
                },
            )
        except Exception as e:
            logger.warning(f"Wake-sensor heartbeat bridge failed: {e}")

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


class WatchdogPausedEvent(BaseModel):
    reason: str = "unknown"
    source: str = "jetson_voice"


@router.post("/voice/watchdog-paused")
async def report_watchdog_paused(
    event: WatchdogPausedEvent,
    current_user=Depends(get_current_user),
):
    """Jetson conversation watchdog tripped (B2.7 loop breaker) — several
    turns in a row with no verified-David speech, or too many turns too
    fast. Surface it as a desktop toast rather than silently looping."""
    try:
        from app.services.unified_notification import send_notification
        await send_notification(
            user_id=current_user.id,
            title="Voice paused",
            message="I kept hearing audio that didn't sound like you. Tap to resume.",
            priority="normal",
            category="system_health",
            source="jetson_voice_watchdog",
            topic=f"voice_watchdog:{event.reason}",
            cooldown_hours=0.25,
        )
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Watchdog-paused report failed: {e}")
        return {"status": "error", "message": str(e)}
