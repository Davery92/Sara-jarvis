"""
Voice Control Plane Routes

API layer for the modular voice-system rollout:
- Pipeline status and service heartbeat reporting
- Versioned voice model registry controls
- Async training job queueing and status tracking
- Structured voice event publishing for observability/replay
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import redis

from app.main_simple import get_current_user
from app.services.voice.control_plane import (
    VOICE_EVENT_TYPES,
    VOICE_EVENT_PUBSUB_CHANNEL,
    VOICE_REDIS_URL,
    create_training_job,
    get_job,
    get_model_registry,
    get_pipeline_status,
    get_voice_config,
    list_voice_events,
    list_jobs,
    patch_voice_config,
    publish_voice_event,
    set_active_model_version,
    update_job_status,
    update_service_heartbeat,
)

router = APIRouter(prefix="/api/voice-control", tags=["voice-control"])


class ServiceHeartbeatInput(BaseModel):
    status: str = "healthy"
    version: Optional[str] = None
    latency_ms: Optional[float] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class VoiceConfigPatchInput(BaseModel):
    wake_word: Optional[Dict[str, Any]] = None
    vad: Optional[Dict[str, Any]] = None
    ambient: Optional[Dict[str, Any]] = None
    routing: Optional[Dict[str, Any]] = None


class WakeWordTrainInput(BaseModel):
    target_phrase: str = "hey sara"
    dataset_id: Optional[str] = None
    notes: Optional[str] = None


class SpeakerTrainInput(BaseModel):
    speaker_ids: List[str] = Field(default_factory=list)
    dataset_id: Optional[str] = None
    notes: Optional[str] = None


class ActivateModelInput(BaseModel):
    version: str


class JobStatusInput(BaseModel):
    status: str
    notes: Optional[str] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class PublishVoiceEventInput(BaseModel):
    event_type: str
    source: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    trace_id: Optional[str] = None


class DemoSimulationInput(BaseModel):
    user_text: str = "Hey Sara, give me a quick system summary."
    sara_text: str = "I am online and monitoring the office stack."
    speaker_id: str = "david"
    include_error: bool = False


@router.get("/contracts")
async def get_voice_contracts(current_user=Depends(get_current_user)):
    """Expose canonical contract names for frontend and service alignment."""
    return {
        "event_types": VOICE_EVENT_TYPES,
        "pipeline": get_pipeline_status(),
    }


@router.get("/pipeline/status")
async def get_voice_pipeline_status(current_user=Depends(get_current_user)):
    """Get live voice pipeline status based on per-service heartbeats."""
    return get_pipeline_status()


@router.post("/services/{service_id}/heartbeat")
async def report_service_heartbeat(
    service_id: str,
    heartbeat: ServiceHeartbeatInput,
    x_internal_service: Optional[str] = Header(None, alias="X-Internal-Service"),
):
    """
    Report service heartbeat for voice pipeline components.

    This endpoint is intentionally service-to-service and does not require
    user auth. Prefer calling from internal network/services only.
    """
    if x_internal_service is None:
        # Keep this permissive during migration, but signal missing header.
        # A tighter auth policy can be enforced once all services are migrated.
        pass

    return {
        "status": "ok",
        "heartbeat": update_service_heartbeat(service_id, heartbeat.dict()),
    }


@router.get("/config")
async def get_voice_control_config(current_user=Depends(get_current_user)):
    """Get voice pipeline configuration currently active in control plane."""
    return get_voice_config()


@router.put("/config")
async def update_voice_control_config(
    patch: VoiceConfigPatchInput,
    current_user=Depends(get_current_user),
):
    """Patch voice pipeline config (wake word/VAD/ambient/routing)."""
    patch_data = {
        k: v for k, v in patch.dict(exclude_none=True).items() if v is not None
    }
    if not patch_data:
        raise HTTPException(status_code=400, detail="No config fields supplied")
    return patch_voice_config(patch_data)


@router.get("/models")
async def get_voice_models(current_user=Depends(get_current_user)):
    """Get versioned model registry for wake word and speakers."""
    return get_model_registry()


@router.post("/models/{model_family}/activate")
async def activate_voice_model(
    model_family: str,
    payload: ActivateModelInput,
    current_user=Depends(get_current_user),
):
    """Set active version for a model family."""
    try:
        registry = set_active_model_version(model_family, payload.version)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "registry": registry}


@router.post("/models/wake-word/train")
async def queue_wake_word_training(
    payload: WakeWordTrainInput,
    current_user=Depends(get_current_user),
):
    """Queue a wake-word training job."""
    job = create_training_job(
        "train_wake_word",
        payload.dict(),
        requested_by=str(current_user.id),
    )
    return {"status": "queued", "job": job}


@router.post("/models/speakers/train")
async def queue_speaker_training(
    payload: SpeakerTrainInput,
    current_user=Depends(get_current_user),
):
    """Queue a speaker retraining/enrollment job."""
    job = create_training_job(
        "train_speakers",
        payload.dict(),
        requested_by=str(current_user.id),
    )
    return {"status": "queued", "job": job}


@router.get("/jobs")
async def get_voice_jobs(limit: int = 25, current_user=Depends(get_current_user)):
    """List recent voice control-plane jobs."""
    capped = max(1, min(limit, 100))
    return {"jobs": list_jobs(capped)}


@router.get("/jobs/{job_id}")
async def get_voice_job(job_id: str, current_user=Depends(get_current_user)):
    """Get one voice control-plane job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/status")
async def set_voice_job_status(
    job_id: str,
    payload: JobStatusInput,
    x_internal_service: Optional[str] = Header(None, alias="X-Internal-Service"),
):
    """
    Update a job status.

    Designed for worker services reporting progress/completion.
    """
    if x_internal_service is None:
        pass

    job = update_job_status(
        job_id,
        payload.status,
        notes=payload.notes,
        error=payload.error,
        result=payload.result,
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "ok", "job": job}


@router.post("/events/publish")
async def publish_event(
    payload: PublishVoiceEventInput,
    current_user=Depends(get_current_user),
):
    """Publish one structured voice event into stream + pub/sub."""
    if payload.event_type not in VOICE_EVENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported event_type '{payload.event_type}'",
        )

    event = publish_voice_event(
        event_type=payload.event_type,
        source=payload.source,
        payload=payload.payload,
        trace_id=payload.trace_id,
    )
    return {"status": "published", "event": event}


@router.get("/events/recent")
async def get_recent_voice_events(
    limit: int = 50,
    current_user=Depends(get_current_user),
):
    """Get newest voice events from the control-plane stream."""
    return {"events": list_voice_events(limit=limit)}


@router.get("/events/stream")
async def stream_voice_events(
    request: Request,
    current_user=Depends(get_current_user),
):
    """Stream live voice events from Redis pub/sub via SSE."""

    async def event_generator():
        pubsub = None
        try:
            client = redis.Redis.from_url(VOICE_REDIS_URL, decode_responses=True)
            pubsub = client.pubsub()
            pubsub.subscribe(VOICE_EVENT_PUBSUB_CHANNEL)

            while True:
                if await request.is_disconnected():
                    break

                message = pubsub.get_message(timeout=0.2)
                if message and message.get("type") == "message":
                    payload = message.get("data")
                    if payload:
                        # payload is already a JSON string.
                        yield f"data: {payload}\n\n"

                await asyncio.sleep(0.1)
        finally:
            if pubsub:
                pubsub.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/demo/simulate-turn")
async def simulate_voice_turn(
    payload: DemoSimulationInput,
    current_user=Depends(get_current_user),
):
    """
    Emit a synthetic voice turn for remote testing without hardware.
    """
    simulated_services = {
        "wake-sensor": {"status": "healthy", "latency_ms": 32},
        "speech-asr": {"status": "healthy", "latency_ms": 410},
        "speaker-diarization": {"status": "healthy", "latency_ms": 620},
        "speaker-registry": {"status": "healthy", "latency_ms": 45},
        "voice-orchestrator": {"status": "healthy", "latency_ms": 260},
        "tts-router": {"status": "healthy", "latency_ms": 380},
        "playback-agent": {"status": "healthy", "latency_ms": 40},
    }
    for service_id, details in simulated_services.items():
        update_service_heartbeat(
            service_id,
            {
                "status": details["status"],
                "version": "sim-v1",
                "latency_ms": details["latency_ms"],
                "details": {"simulated": True},
            },
        )

    published = []
    published.append(
        publish_voice_event(
            event_type="wake.detected",
            source="wake-sensor",
            payload={"keyword": "hey sara", "confidence": 0.93},
        )
    )

    trace_id = published[0]["trace_id"]

    published.extend(
        [
            publish_voice_event(
                event_type="utterance.started",
                source="wake-sensor",
                trace_id=trace_id,
                payload={"speaker_id": payload.speaker_id},
            ),
            publish_voice_event(
                event_type="utterance.ended",
                source="wake-sensor",
                trace_id=trace_id,
                payload={"duration_ms": 1940},
            ),
            publish_voice_event(
                event_type="asr.final",
                source="speech-asr",
                trace_id=trace_id,
                payload={"text": payload.user_text, "confidence": 0.91},
            ),
            publish_voice_event(
                event_type="diarization.final",
                source="speaker-diarization",
                trace_id=trace_id,
                payload={"speaker_id": payload.speaker_id, "confidence": 0.87},
            ),
            publish_voice_event(
                event_type="speaker.verified",
                source="speaker-registry",
                trace_id=trace_id,
                payload={"speaker_id": payload.speaker_id, "verified": True},
            ),
            publish_voice_event(
                event_type="sara.response.delta",
                source="voice-orchestrator",
                trace_id=trace_id,
                payload={"text": payload.sara_text[: max(1, len(payload.sara_text) // 2)]},
            ),
            publish_voice_event(
                event_type="sara.response.final",
                source="voice-orchestrator",
                trace_id=trace_id,
                payload={"text": payload.sara_text},
            ),
            publish_voice_event(
                event_type="tts.chunk",
                source="tts-router",
                trace_id=trace_id,
                payload={"chunk_index": 0, "size_bytes": 12288},
            ),
            publish_voice_event(
                event_type="playback.state",
                source="playback-agent",
                trace_id=trace_id,
                payload={"state": "playing"},
            ),
            publish_voice_event(
                event_type="playback.state",
                source="playback-agent",
                trace_id=trace_id,
                payload={"state": "idle"},
            ),
        ]
    )

    if payload.include_error:
        published.append(
            publish_voice_event(
                event_type="pipeline.error",
                source="speech-asr",
                trace_id=trace_id,
                payload={"message": "Synthetic ASR timeout for UI testing"},
            )
        )

    return {"status": "ok", "trace_id": trace_id, "events": published}
