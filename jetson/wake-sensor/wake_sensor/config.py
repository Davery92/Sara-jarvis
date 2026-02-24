"""Wake sensor runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass
import os


def _as_bool(value: str, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class WakeSensorConfig:
    backend_url: str
    internal_service: str
    internal_token: str
    simulate: bool
    log_level: str

    keyword: str
    wake_threshold: float
    vad_threshold: float
    silence_ms: int

    heartbeat_interval_seconds: int
    simulation_interval_seconds: int
    ambient_sample_interval_seconds: int
    config_sync_interval_seconds: int
    training_enabled: bool
    training_poll_interval_seconds: int
    auto_activate_trained_model: bool

    @classmethod
    def from_env(cls) -> "WakeSensorConfig":
        return cls(
            backend_url=os.getenv("SARA_BACKEND_URL", "http://10.185.1.180:8000").rstrip("/"),
            internal_service=os.getenv("VOICE_INTERNAL_SERVICE", "wake-sensor"),
            internal_token=os.getenv("VOICE_CONTROL_INTERNAL_TOKEN", ""),
            simulate=_as_bool(os.getenv("WAKE_SENSOR_SIMULATE", "true"), True),
            log_level=os.getenv("WAKE_SENSOR_LOG_LEVEL", "INFO"),
            keyword=os.getenv("WAKE_SENSOR_KEYWORD", "hey sara"),
            wake_threshold=float(os.getenv("WAKE_SENSOR_WAKE_THRESHOLD", "0.58")),
            vad_threshold=float(os.getenv("WAKE_SENSOR_VAD_THRESHOLD", "0.50")),
            silence_ms=int(os.getenv("WAKE_SENSOR_SILENCE_MS", "650")),
            heartbeat_interval_seconds=int(os.getenv("WAKE_SENSOR_HEARTBEAT_INTERVAL_SECONDS", "15")),
            simulation_interval_seconds=int(os.getenv("WAKE_SENSOR_SIMULATION_INTERVAL_SECONDS", "20")),
            ambient_sample_interval_seconds=int(os.getenv("WAKE_SENSOR_AMBIENT_SAMPLE_INTERVAL_SECONDS", "120")),
            config_sync_interval_seconds=int(os.getenv("WAKE_SENSOR_CONFIG_SYNC_INTERVAL_SECONDS", "30")),
            training_enabled=_as_bool(os.getenv("WAKE_SENSOR_TRAINING_ENABLED", "true"), True),
            training_poll_interval_seconds=int(os.getenv("WAKE_SENSOR_TRAINING_POLL_INTERVAL_SECONDS", "6")),
            auto_activate_trained_model=_as_bool(
                os.getenv("WAKE_SENSOR_AUTO_ACTIVATE_TRAINED_MODEL", "false"),
                False,
            ),
        )
