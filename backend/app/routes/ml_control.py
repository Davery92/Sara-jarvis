"""
ML Control Plane routes (Desktop Jarvis Overhaul C2).

Generic job-queue + model-registry + event-stream API for the tabular ML
models (interruptibility_v2, notification_value, next_block,
rhythm_forecaster) — same shape as app/routes/voice_control.py, backed by
app/services/ml/control_plane.py so the GPU-cluster ml-worker can claim
jobs and register model versions the same way the voice training workers
already do.
"""
import asyncio
import hmac
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.main_simple import get_current_user
from app.services.ml.control_plane import (
    ML_EVENT_TYPES,
    ML_MODEL_FAMILIES,
    ML_EVENT_PUBSUB_CHANNEL,
    claim_next_job,
    create_training_job,
    get_job,
    get_model_registry,
    get_pipeline_status,
    list_jobs,
    list_ml_events,
    publish_ml_event,
    register_model_version,
    set_active_model_version,
    update_job_status,
    update_service_heartbeat,
)

router = APIRouter(prefix="/api/ml", tags=["ml-control"])

ML_CONTROL_INTERNAL_TOKEN = os.getenv("ML_CONTROL_INTERNAL_TOKEN", os.getenv("VOICE_CONTROL_INTERNAL_TOKEN", ""))
ML_CONTROL_INTERNAL_AUTH_REQUIRED = (
    os.getenv("ML_CONTROL_INTERNAL_AUTH_REQUIRED", "true").strip().lower() == "true"
)
ML_CONTROL_ALLOWED_SERVICES = {
    item.strip()
    for item in os.getenv("ML_CONTROL_ALLOWED_SERVICES", "ml-worker,ml-inference").split(",")
    if item.strip()
}


def _authorize_internal_request(*, service_name: Optional[str], token: Optional[str], expected_service: Optional[str] = None) -> str:
    if not service_name:
        raise HTTPException(status_code=401, detail="Missing X-Internal-Service header")
    if expected_service and service_name != expected_service:
        raise HTTPException(status_code=403, detail=f"X-Internal-Service '{service_name}' cannot operate on '{expected_service}'")
    if ML_CONTROL_ALLOWED_SERVICES and service_name not in ML_CONTROL_ALLOWED_SERVICES:
        raise HTTPException(status_code=403, detail=f"Service '{service_name}' is not in ML_CONTROL_ALLOWED_SERVICES")
    if not ML_CONTROL_INTERNAL_AUTH_REQUIRED:
        return service_name
    configured = ML_CONTROL_INTERNAL_TOKEN.strip()
    if not configured:
        raise HTTPException(status_code=503, detail="ML_CONTROL_INTERNAL_TOKEN is required but not configured")
    provided = (token or "").strip()
    if not provided or not hmac.compare_digest(provided, configured):
        raise HTTPException(status_code=401, detail="Invalid internal token")
    return service_name


class ServiceHeartbeatInput(BaseModel):
    status: str = "healthy"
    version: Optional[str] = None
    latency_ms: Optional[float] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class TrainModelInput(BaseModel):
    model_family: str
    dataset_window_days: int = 90
    notes: Optional[str] = None


class ActivateModelInput(BaseModel):
    version: str


class RegisterModelVersionInput(BaseModel):
    version: str
    status: str = "candidate"
    metrics: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ClaimJobInput(BaseModel):
    job_types: List[str] = Field(default_factory=list)


class JobStatusInput(BaseModel):
    status: str
    notes: Optional[str] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class PublishMLEventInput(BaseModel):
    event_type: str
    source: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    trace_id: Optional[str] = None


@router.get("/contracts")
async def get_ml_contracts(current_user=Depends(get_current_user)):
    return {"event_types": ML_EVENT_TYPES, "model_families": ML_MODEL_FAMILIES, "pipeline": get_pipeline_status()}


@router.get("/pipeline/status")
async def get_ml_pipeline_status(current_user=Depends(get_current_user)):
    return get_pipeline_status()


@router.post("/services/{service_id}/heartbeat")
async def report_ml_service_heartbeat(
    service_id: str,
    heartbeat: ServiceHeartbeatInput,
    x_internal_service: Optional[str] = Header(None, alias="X-Internal-Service"),
    x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token"),
):
    _authorize_internal_request(service_name=x_internal_service, token=x_internal_token, expected_service=service_id)
    return {"status": "ok", "heartbeat": update_service_heartbeat(service_id, heartbeat.dict())}


@router.get("/models")
async def get_ml_models(current_user=Depends(get_current_user)):
    """Versioned model registry for the four tabular model families."""
    return get_model_registry()


@router.post("/models/{model_family}/train")
async def queue_ml_training(model_family: str, payload: TrainModelInput, current_user=Depends(get_current_user)):
    if model_family not in ML_MODEL_FAMILIES:
        raise HTTPException(status_code=400, detail=f"Unknown model family: {model_family}")
    job = create_training_job("train_model", payload.dict(), requested_by=str(current_user.id))
    return {"status": "queued", "job": job}


@router.post("/models/{model_family}/activate")
async def activate_ml_model(model_family: str, payload: ActivateModelInput, current_user=Depends(get_current_user)):
    try:
        registry = set_active_model_version(model_family, payload.version)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "registry": registry}


@router.post("/models/{model_family}/activate-internal")
async def activate_ml_model_internal(
    model_family: str,
    payload: ActivateModelInput,
    x_internal_service: Optional[str] = Header(None, alias="X-Internal-Service"),
    x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token"),
):
    service_name = _authorize_internal_request(service_name=x_internal_service, token=x_internal_token)
    try:
        registry = set_active_model_version(model_family, payload.version)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "registry": registry, "activated_by": service_name}


@router.post("/models/{model_family}/versions")
async def register_ml_model_version(
    model_family: str,
    payload: RegisterModelVersionInput,
    x_internal_service: Optional[str] = Header(None, alias="X-Internal-Service"),
    x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token"),
):
    service_name = _authorize_internal_request(service_name=x_internal_service, token=x_internal_token)
    registry = register_model_version(
        model_family, payload.version, status=payload.status, metrics=payload.metrics,
        metadata=payload.metadata, created_by=service_name,
    )
    return {"status": "ok", "registry": registry, "registered_by": service_name}


@router.get("/jobs")
async def get_ml_jobs(limit: int = 25, current_user=Depends(get_current_user)):
    return {"jobs": list_jobs(max(1, min(limit, 100)))}


@router.get("/jobs/{job_id}")
async def get_ml_job(job_id: str, current_user=Depends(get_current_user)):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs/claim")
async def claim_ml_job(
    payload: ClaimJobInput,
    x_internal_service: Optional[str] = Header(None, alias="X-Internal-Service"),
    x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token"),
):
    service_name = _authorize_internal_request(service_name=x_internal_service, token=x_internal_token)
    job = claim_next_job(service_name, job_types=payload.job_types or None)
    return {"status": "ok", "job": job}


@router.post("/jobs/{job_id}/status")
async def set_ml_job_status(
    job_id: str,
    payload: JobStatusInput,
    x_internal_service: Optional[str] = Header(None, alias="X-Internal-Service"),
    x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token"),
):
    _authorize_internal_request(service_name=x_internal_service, token=x_internal_token)
    job = update_job_status(job_id, payload.status, notes=payload.notes, error=payload.error,
                             result=payload.result, worker_service=x_internal_service)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "ok", "job": job}


@router.post("/events/publish-internal")
async def publish_ml_event_internal(
    payload: PublishMLEventInput,
    x_internal_service: Optional[str] = Header(None, alias="X-Internal-Service"),
    x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token"),
):
    service_name = _authorize_internal_request(service_name=x_internal_service, token=x_internal_token)
    if payload.event_type not in ML_EVENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported event_type '{payload.event_type}'")
    if payload.source != service_name:
        raise HTTPException(status_code=403, detail="source must match X-Internal-Service")
    event = publish_ml_event(event_type=payload.event_type, source=payload.source, payload=payload.payload, trace_id=payload.trace_id)
    return {"status": "published", "event": event}


@router.get("/events/recent")
async def get_recent_ml_events(limit: int = 50, current_user=Depends(get_current_user)):
    return {"events": list_ml_events(limit)}


@router.get("/events/stream")
async def stream_ml_events(request: Request, current_user=Depends(get_current_user)):
    """Stream live ML pipeline events (job/model updates) via SSE."""

    async def event_generator():
        pubsub = None
        try:
            from app.core.redis import get_redis_sync
            client = get_redis_sync()
            pubsub = client.pubsub()
            pubsub.subscribe(ML_EVENT_PUBSUB_CHANNEL)
            while True:
                if await request.is_disconnected():
                    break
                message = pubsub.get_message(timeout=0.2)
                if message and message.get("type") == "message":
                    payload = message.get("data")
                    if payload:
                        yield f"data: {payload}\n\n"
                await asyncio.sleep(0.1)
        finally:
            if pubsub:
                pubsub.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
