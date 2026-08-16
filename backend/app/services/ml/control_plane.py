"""
ML Control Plane (Desktop Jarvis Overhaul C2).

Same Redis-backed job-queue/model-registry/event-stream pattern as
app/services/voice/control_plane.py — generalized for the tabular ML model
families (interruptibility_v2, notification_value, next_block,
rhythm_forecaster) rather than in-place renaming that module (which stays
untouched so the voice families keep working unmodified).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import redis

ML_REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

ML_MODEL_REGISTRY_KEY = "ml:control:model_registry"
ML_JOBS_HASH_KEY = "ml:control:jobs"
ML_JOBS_LIST_KEY = "ml:control:jobs:recent"
ML_JOB_CLAIMS_HASH_KEY = "ml:control:jobs:claims"
ML_EVENT_STREAM_KEY = "ml:events"
ML_EVENT_PUBSUB_CHANNEL = "ml:events:pubsub"
ML_HEARTBEAT_KEY_PREFIX = "ml:heartbeat:"

ML_EVENT_MAXLEN = int(os.getenv("ML_EVENT_STREAM_MAXLEN", "20000"))
ML_JOB_MAXLEN = int(os.getenv("ML_JOB_RECENT_MAXLEN", "300"))
ML_HEARTBEAT_TTL_SECONDS = int(os.getenv("ML_HEARTBEAT_TTL_SECONDS", "90"))
ML_TERMINAL_JOB_STATES = {"completed", "failed", "canceled", "cancelled"}

ML_MODEL_FAMILIES: List[str] = [
    "interruptibility_v2",
    "notification_value",
    "next_block",
    "rhythm_forecaster",
]

ML_SERVICES: List[Dict[str, str]] = [
    {"id": "ml-worker", "name": "GPU ML Training Worker"},
    {"id": "ml-inference", "name": "Backend Inference Service"},
]

ML_EVENT_TYPES: List[str] = [
    "job.queued",
    "job.updated",
    "model.registered",
    "model.activated",
    "prediction.logged",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _redis() -> redis.Redis:
    from app.core.redis import get_redis_sync
    return get_redis_sync()


def _load_json(key: str) -> Optional[Dict[str, Any]]:
    raw = _redis().get(key)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except (TypeError, json.JSONDecodeError):
        return None
    return None


def _save_json(key: str, payload: Dict[str, Any]) -> None:
    _redis().set(key, json.dumps(payload))


def _default_model_registry() -> Dict[str, Any]:
    now = _now_iso()
    return {
        family: {"active_version": None, "versions": []}
        for family in ML_MODEL_FAMILIES
    } | {"updated_at": now}


def get_model_registry() -> Dict[str, Any]:
    registry = _load_json(ML_MODEL_REGISTRY_KEY)
    if registry:
        return registry
    defaults = _default_model_registry()
    _save_json(ML_MODEL_REGISTRY_KEY, defaults)
    return defaults


def _save_model_registry(registry: Dict[str, Any]) -> Dict[str, Any]:
    _save_json(ML_MODEL_REGISTRY_KEY, registry)
    return registry


def set_active_model_version(model_family: str, version: str) -> Dict[str, Any]:
    registry = get_model_registry()
    family = registry.get(model_family)
    if not isinstance(family, dict):
        raise ValueError(f"Unknown model family: {model_family}")

    versions = family.get("versions", [])
    target = next((item for item in versions if item.get("version") == version), None)
    if target is None:
        raise ValueError(f"Version '{version}' not found in family '{model_family}'")

    for item in versions:
        item["status"] = "inactive"
    target["status"] = "active"
    family["active_version"] = version
    family["updated_at"] = _now_iso()
    registry = _save_model_registry(registry)

    publish_ml_event(event_type="model.activated", source="ml-control", payload={
        "model_family": model_family, "version": version,
    })
    return registry


def register_model_version(
    model_family: str,
    version: str,
    *,
    status: str = "candidate",
    metrics: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    created_by: Optional[str] = None,
) -> Dict[str, Any]:
    registry = get_model_registry()
    family = registry.setdefault(model_family, {"active_version": None, "versions": []})

    versions = family.setdefault("versions", [])
    now = _now_iso()
    target = next((item for item in versions if item.get("version") == version), None)

    if target is None:
        target = {
            "version": version,
            "status": status,
            "created_at": now,
            "metrics": metrics or {},
            "metadata": metadata or {},
            "created_by": created_by,
        }
        versions.append(target)
    else:
        target["status"] = status
        target["metrics"] = metrics or target.get("metrics", {})
        target["metadata"] = metadata or target.get("metadata", {})
        if created_by:
            target["created_by"] = created_by
        target.setdefault("created_at", now)

    if status == "active":
        for item in versions:
            item["status"] = "inactive"
        target["status"] = "active"
        family["active_version"] = version

    family["updated_at"] = now
    registry = _save_model_registry(registry)

    publish_ml_event(event_type="model.registered", source="ml-control", payload={
        "model_family": model_family, "version": version, "status": status,
    })
    return registry


def create_training_job(job_type: str, payload: Dict[str, Any], requested_by: str) -> Dict[str, Any]:
    job_id = str(uuid4())
    now = _now_iso()
    job = {
        "job_id": job_id,
        "job_type": job_type,
        "status": "queued",
        "payload": payload,
        "requested_by": requested_by,
        "created_at": now,
        "updated_at": now,
        "notes": None,
        "error": None,
        "result": None,
    }

    r = _redis()
    r.hset(ML_JOBS_HASH_KEY, job_id, json.dumps(job))
    r.lpush(ML_JOBS_LIST_KEY, job_id)
    r.ltrim(ML_JOBS_LIST_KEY, 0, ML_JOB_MAXLEN - 1)

    publish_ml_event(event_type="job.queued", source="ml-control", payload={
        "job_id": job_id, "job_type": job_type, "status": "queued",
    })
    return job


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    raw = _redis().hget(ML_JOBS_HASH_KEY, job_id)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except (TypeError, json.JSONDecodeError):
        return None
    return None


def list_jobs(limit: int = 25) -> List[Dict[str, Any]]:
    job_ids = _redis().lrange(ML_JOBS_LIST_KEY, 0, max(limit - 1, 0))
    jobs: List[Dict[str, Any]] = []
    for job_id in job_ids:
        job = get_job(job_id)
        if job:
            jobs.append(job)
    return jobs


def claim_next_job(worker_service: str, *, job_types: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    allowed_types = {item.strip() for item in (job_types or []) if isinstance(item, str) and item.strip()}

    r = _redis()
    job_ids = r.lrange(ML_JOBS_LIST_KEY, 0, ML_JOB_MAXLEN - 1)
    for job_id in reversed(job_ids):
        if r.hsetnx(ML_JOB_CLAIMS_HASH_KEY, job_id, worker_service) != 1:
            continue

        keep_claim = False
        try:
            job = get_job(job_id)
            if not job or job.get("status") != "queued":
                continue
            if allowed_types and job.get("job_type") not in allowed_types:
                continue

            now = _now_iso()
            job["status"] = "running"
            job["claimed_by"] = worker_service
            job["started_at"] = job.get("started_at") or now
            job["updated_at"] = now
            r.hset(ML_JOBS_HASH_KEY, job_id, json.dumps(job))
            keep_claim = True

            publish_ml_event(event_type="job.updated", source="ml-control", payload={
                "job_id": job_id, "status": "running", "claimed_by": worker_service,
                "job_type": job.get("job_type"),
            })
            return job
        finally:
            if not keep_claim:
                r.hdel(ML_JOB_CLAIMS_HASH_KEY, job_id)

    return None


def update_job_status(
    job_id: str,
    status: str,
    *,
    notes: Optional[str] = None,
    error: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
    worker_service: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    job = get_job(job_id)
    if not job:
        return None

    r = _redis()
    job["status"] = status
    job["updated_at"] = _now_iso()
    if worker_service:
        job["claimed_by"] = job.get("claimed_by") or worker_service
    if notes is not None:
        job["notes"] = notes
    if error is not None:
        job["error"] = error
    if result is not None:
        job["result"] = result

    r.hset(ML_JOBS_HASH_KEY, job_id, json.dumps(job))
    if status in ML_TERMINAL_JOB_STATES:
        r.hdel(ML_JOB_CLAIMS_HASH_KEY, job_id)

    publish_ml_event(event_type="job.updated", source="ml-control", payload={
        "job_id": job_id, "status": status, "notes": notes, "error": error,
        "claimed_by": job.get("claimed_by"),
    })
    return job


def update_service_heartbeat(service_id: str, heartbeat: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "service_id": service_id,
        "status": heartbeat.get("status", "healthy"),
        "version": heartbeat.get("version"),
        "latency_ms": heartbeat.get("latency_ms"),
        "details": heartbeat.get("details") or {},
        "reported_at": _now_iso(),
    }
    _redis().setex(f"{ML_HEARTBEAT_KEY_PREFIX}{service_id}", ML_HEARTBEAT_TTL_SECONDS, json.dumps(payload))
    return payload


def get_pipeline_status() -> Dict[str, Any]:
    r = _redis()
    services = []
    for service in ML_SERVICES:
        service_id = service["id"]
        raw = r.get(f"{ML_HEARTBEAT_KEY_PREFIX}{service_id}")
        try:
            payload = json.loads(raw) if raw else {}
        except (TypeError, json.JSONDecodeError):
            payload = {}
        services.append({
            "id": service_id,
            "name": service["name"],
            "status": payload.get("status", "offline"),
            "version": payload.get("version"),
            "latency_ms": payload.get("latency_ms"),
            "last_reported_at": payload.get("reported_at"),
            "details": payload.get("details") or {},
        })

    return {
        "generated_at": _now_iso(),
        "services": services,
        "model_families": ML_MODEL_FAMILIES,
        "event_stream": {
            "stream_key": ML_EVENT_STREAM_KEY,
            "pubsub_channel": ML_EVENT_PUBSUB_CHANNEL,
            "maxlen": ML_EVENT_MAXLEN,
        },
        "event_types": ML_EVENT_TYPES,
    }


def publish_ml_event(*, event_type: str, source: str, payload: Dict[str, Any], trace_id: Optional[str] = None) -> Dict[str, Any]:
    now = _now_iso()
    event_id = str(uuid4())
    full_event = {
        "event_id": event_id,
        "event_type": event_type,
        "source": source,
        "payload": payload,
        "trace_id": trace_id or event_id,
        "timestamp": now,
    }

    r = _redis()
    stream_payload = {
        "event_id": full_event["event_id"],
        "event_type": full_event["event_type"],
        "source": full_event["source"],
        "trace_id": full_event["trace_id"],
        "timestamp": full_event["timestamp"],
        "payload": json.dumps(payload),
    }
    stream_id = r.xadd(ML_EVENT_STREAM_KEY, stream_payload, maxlen=ML_EVENT_MAXLEN)
    r.publish(ML_EVENT_PUBSUB_CHANNEL, json.dumps(full_event))
    full_event["stream_id"] = stream_id.decode() if isinstance(stream_id, bytes) else stream_id
    return full_event


def list_ml_events(limit: int = 50) -> List[Dict[str, Any]]:
    capped = max(1, min(limit, 500))
    rows = _redis().xrevrange(ML_EVENT_STREAM_KEY, count=capped)
    events: List[Dict[str, Any]] = []
    for stream_id, payload in rows:
        raw_payload = payload.get("payload")
        try:
            parsed_payload = json.loads(raw_payload) if raw_payload else {}
        except (TypeError, json.JSONDecodeError):
            parsed_payload = raw_payload
        events.append({
            "stream_id": stream_id,
            "event_id": payload.get("event_id"),
            "event_type": payload.get("event_type"),
            "source": payload.get("source"),
            "trace_id": payload.get("trace_id"),
            "timestamp": payload.get("timestamp"),
            "payload": parsed_payload,
        })
    return events
