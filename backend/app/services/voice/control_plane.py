"""
Voice Control Plane

Contract-first storage and state helpers for the modular voice stack.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import redis

VOICE_REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

VOICE_CONFIG_KEY = "voice:control:config"
VOICE_MODEL_REGISTRY_KEY = "voice:control:model_registry"
VOICE_JOBS_HASH_KEY = "voice:control:jobs"
VOICE_JOBS_LIST_KEY = "voice:control:jobs:recent"
VOICE_EVENT_STREAM_KEY = "voice:events"
VOICE_EVENT_PUBSUB_CHANNEL = "voice:events:pubsub"
VOICE_HEARTBEAT_KEY_PREFIX = "voice:heartbeat:"

VOICE_EVENT_MAXLEN = int(os.getenv("VOICE_EVENT_STREAM_MAXLEN", "50000"))
VOICE_JOB_MAXLEN = int(os.getenv("VOICE_JOB_RECENT_MAXLEN", "300"))
VOICE_HEARTBEAT_TTL_SECONDS = int(os.getenv("VOICE_HEARTBEAT_TTL_SECONDS", "90"))

# Canonical event contract names for the voice pipeline.
VOICE_EVENT_TYPES: List[str] = [
    "job.queued",
    "job.updated",
    "wake.detected",
    "utterance.started",
    "utterance.ended",
    "asr.partial",
    "asr.final",
    "diarization.final",
    "speaker.verified",
    "sara.request.started",
    "sara.response.delta",
    "sara.response.final",
    "tts.chunk",
    "tts.final",
    "playback.state",
    "pipeline.error",
]

VOICE_SERVICES: List[Dict[str, str]] = [
    {"id": "wake-sensor", "name": "Jetson Wake Sensor"},
    {"id": "speech-asr", "name": "GPU ASR"},
    {"id": "speaker-diarization", "name": "GPU Speaker Diarization"},
    {"id": "speaker-registry", "name": "Speaker Registry"},
    {"id": "voice-orchestrator", "name": "Voice Orchestrator"},
    {"id": "tts-router", "name": "Windows TTS Router"},
    {"id": "playback-agent", "name": "Windows Playback Agent"},
]

VOICE_SLO_MS = {
    "wake_to_capture_start": 350,
    "utterance_end_to_asr_final": 1200,
    "asr_final_to_sara_first_token": 1800,
    "sara_first_token_to_first_audio": 800,
    "utterance_end_to_first_audio": 3200,
}


def _now_iso() -> str:
    """UTC ISO timestamp with explicit Z suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _redis() -> redis.Redis:
    return redis.from_url(VOICE_REDIS_URL, decode_responses=True)


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


def _deep_merge(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _default_voice_config() -> Dict[str, Any]:
    return {
        "wake_word": {
            "enabled": True,
            "keyword": "hey sara",
            "threshold": 0.58,
            "cooldown_ms": 1200,
            "model_version": "hey_sara_v1",
        },
        "vad": {
            "enabled": True,
            "speech_threshold": 0.50,
            "silence_duration_ms": 650,
            "max_utterance_ms": 12000,
        },
        "ambient": {
            "enabled": True,
            "sample_interval_seconds": 120,
            "noise_floor_db": -52.0,
            "auto_adjust_wake_threshold": True,
            "auto_adjust_vad": True,
            "last_calibrated_at": None,
        },
        "routing": {
            "asr_provider": "faster-whisper",
            "diarization_provider": "nemo",
            "tts_provider": "kokoro",
            "orchestrator_provider": "sara-backend",
        },
        "updated_at": _now_iso(),
    }


def _default_model_registry() -> Dict[str, Any]:
    now = _now_iso()
    return {
        "wake_word": {
            "active_version": "hey_sara_v1",
            "versions": [
                {
                    "version": "hey_sara_v1",
                    "status": "active",
                    "created_at": now,
                    "metrics": {},
                }
            ],
        },
        "speakers": {
            "active_version": "speaker_profiles_v1",
            "versions": [
                {
                    "version": "speaker_profiles_v1",
                    "status": "active",
                    "created_at": now,
                    "metrics": {},
                }
            ],
        },
    }


def get_voice_config() -> Dict[str, Any]:
    config = _load_json(VOICE_CONFIG_KEY)
    if config:
        return config
    defaults = _default_voice_config()
    _save_json(VOICE_CONFIG_KEY, defaults)
    return defaults


def patch_voice_config(patch: Dict[str, Any]) -> Dict[str, Any]:
    current = get_voice_config()
    merged = _deep_merge(current, patch)
    merged["updated_at"] = _now_iso()
    _save_json(VOICE_CONFIG_KEY, merged)
    return merged


def get_model_registry() -> Dict[str, Any]:
    registry = _load_json(VOICE_MODEL_REGISTRY_KEY)
    if registry:
        return registry
    defaults = _default_model_registry()
    _save_json(VOICE_MODEL_REGISTRY_KEY, defaults)
    return defaults


def _save_model_registry(registry: Dict[str, Any]) -> Dict[str, Any]:
    _save_json(VOICE_MODEL_REGISTRY_KEY, registry)
    return registry


def set_active_model_version(model_family: str, version: str) -> Dict[str, Any]:
    registry = get_model_registry()
    family = registry.get(model_family)
    if not isinstance(family, dict):
        raise ValueError(f"Unknown model family: {model_family}")

    versions = family.get("versions", [])
    target = None
    for item in versions:
        if item.get("version") == version:
            target = item
            break

    if target is None:
        raise ValueError(f"Version '{version}' not found in family '{model_family}'")

    for item in versions:
        item["status"] = "inactive"
    target["status"] = "active"
    family["active_version"] = version
    family["updated_at"] = _now_iso()
    return _save_model_registry(registry)


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
    r.hset(VOICE_JOBS_HASH_KEY, job_id, json.dumps(job))
    r.lpush(VOICE_JOBS_LIST_KEY, job_id)
    r.ltrim(VOICE_JOBS_LIST_KEY, 0, VOICE_JOB_MAXLEN - 1)

    publish_voice_event(
        event_type="job.queued",
        source="voice-control",
        payload={
            "job_id": job_id,
            "job_type": job_type,
            "status": "queued",
        },
    )
    return job


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    raw = _redis().hget(VOICE_JOBS_HASH_KEY, job_id)
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
    job_ids = _redis().lrange(VOICE_JOBS_LIST_KEY, 0, max(limit - 1, 0))
    jobs: List[Dict[str, Any]] = []
    for job_id in job_ids:
        job = get_job(job_id)
        if job:
            jobs.append(job)
    return jobs


def update_job_status(
    job_id: str,
    status: str,
    *,
    notes: Optional[str] = None,
    error: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    job = get_job(job_id)
    if not job:
        return None

    job["status"] = status
    job["updated_at"] = _now_iso()
    if notes is not None:
        job["notes"] = notes
    if error is not None:
        job["error"] = error
    if result is not None:
        job["result"] = result

    _redis().hset(VOICE_JOBS_HASH_KEY, job_id, json.dumps(job))
    publish_voice_event(
        event_type="job.updated",
        source="voice-control",
        payload={
            "job_id": job_id,
            "status": status,
            "notes": notes,
            "error": error,
        },
    )
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
    _redis().setex(
        f"{VOICE_HEARTBEAT_KEY_PREFIX}{service_id}",
        VOICE_HEARTBEAT_TTL_SECONDS,
        json.dumps(payload),
    )
    return payload


def get_pipeline_status() -> Dict[str, Any]:
    r = _redis()
    services = []
    for service in VOICE_SERVICES:
        service_id = service["id"]
        raw = r.get(f"{VOICE_HEARTBEAT_KEY_PREFIX}{service_id}")
        if raw:
            try:
                payload = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                payload = {}
        else:
            payload = {}

        services.append(
            {
                "id": service_id,
                "name": service["name"],
                "status": payload.get("status", "offline"),
                "version": payload.get("version"),
                "latency_ms": payload.get("latency_ms"),
                "last_reported_at": payload.get("reported_at"),
                "details": payload.get("details") or {},
            }
        )

    return {
        "generated_at": _now_iso(),
        "services": services,
        "slo_ms": VOICE_SLO_MS,
        "event_stream": {
            "stream_key": VOICE_EVENT_STREAM_KEY,
            "pubsub_channel": VOICE_EVENT_PUBSUB_CHANNEL,
            "maxlen": VOICE_EVENT_MAXLEN,
        },
        "event_types": VOICE_EVENT_TYPES,
    }


def publish_voice_event(
    *,
    event_type: str,
    source: str,
    payload: Dict[str, Any],
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
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
    stream_id = r.xadd(VOICE_EVENT_STREAM_KEY, stream_payload, maxlen=VOICE_EVENT_MAXLEN)
    r.publish(VOICE_EVENT_PUBSUB_CHANNEL, json.dumps(full_event))
    full_event["stream_id"] = stream_id.decode() if isinstance(stream_id, bytes) else stream_id
    return full_event


def list_voice_events(limit: int = 50) -> List[Dict[str, Any]]:
    """
    List recent events from the voice event stream.

    Returns newest-first ordering (matches Redis XREVRANGE behavior).
    """
    capped = max(1, min(limit, 500))
    rows = _redis().xrevrange(VOICE_EVENT_STREAM_KEY, count=capped)
    events: List[Dict[str, Any]] = []

    for stream_id, payload in rows:
        raw_payload = payload.get("payload")
        parsed_payload: Any
        try:
            parsed_payload = json.loads(raw_payload) if raw_payload else {}
        except (TypeError, json.JSONDecodeError):
            parsed_payload = raw_payload

        events.append(
            {
                "stream_id": stream_id,
                "event_id": payload.get("event_id"),
                "event_type": payload.get("event_type"),
                "source": payload.get("source"),
                "trace_id": payload.get("trace_id"),
                "timestamp": payload.get("timestamp"),
                "payload": parsed_payload,
            }
        )

    return events
