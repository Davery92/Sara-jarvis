"""Client for Sara voice control-plane endpoints."""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from .config import WakeSensorConfig
from .contracts import VoiceEvent


class VoiceControlClient:
    def __init__(self, config: WakeSensorConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=8.0)

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "X-Internal-Service": self.config.internal_service,
            "X-Internal-Token": self.config.internal_token,
        }

    async def report_heartbeat(
        self,
        *,
        status: str = "healthy",
        latency_ms: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        assert self._client is not None, "Client not started"
        url = f"{self.config.backend_url}/api/voice-control/services/{self.config.internal_service}/heartbeat"
        payload = {
            "status": status,
            "version": "scaffold-v1",
            "latency_ms": latency_ms,
            "details": details or {},
        }
        response = await self._client.post(url, json=payload, headers=self._headers)
        response.raise_for_status()
        return response.json()

    async def get_config(self) -> Dict[str, Any]:
        assert self._client is not None, "Client not started"
        url = f"{self.config.backend_url}/api/voice-control/config/internal"
        response = await self._client.get(url, headers=self._headers)
        response.raise_for_status()
        payload = response.json()
        config = payload.get("config")
        return config if isinstance(config, dict) else {}

    async def publish_event(self, event: VoiceEvent) -> Dict[str, Any]:
        assert self._client is not None, "Client not started"
        url = f"{self.config.backend_url}/api/voice-control/events/publish-internal"
        response = await self._client.post(url, json=event.to_payload(), headers=self._headers)
        response.raise_for_status()
        return response.json()

    async def claim_job(self, job_types: Optional[list[str]] = None) -> Optional[Dict[str, Any]]:
        assert self._client is not None, "Client not started"
        url = f"{self.config.backend_url}/api/voice-control/jobs/claim"
        response = await self._client.post(
            url,
            json={"job_types": job_types or []},
            headers=self._headers,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("job")

    async def update_job_status(
        self,
        job_id: str,
        *,
        status: str,
        notes: Optional[str] = None,
        error: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        assert self._client is not None, "Client not started"
        url = f"{self.config.backend_url}/api/voice-control/jobs/{job_id}/status"
        response = await self._client.post(
            url,
            json={
                "status": status,
                "notes": notes,
                "error": error,
                "result": result,
            },
            headers=self._headers,
        )
        response.raise_for_status()
        return response.json()

    async def register_model_version(
        self,
        *,
        model_family: str,
        version: str,
        status: str = "candidate",
        metrics: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        assert self._client is not None, "Client not started"
        url = f"{self.config.backend_url}/api/voice-control/models/{model_family}/versions"
        response = await self._client.post(
            url,
            json={
                "version": version,
                "status": status,
                "metrics": metrics or {},
                "metadata": metadata or {},
            },
            headers=self._headers,
        )
        response.raise_for_status()
        return response.json()

    async def activate_model_version(self, *, model_family: str, version: str) -> Dict[str, Any]:
        assert self._client is not None, "Client not started"
        url = f"{self.config.backend_url}/api/voice-control/models/{model_family}/activate-internal"
        response = await self._client.post(
            url,
            json={"version": version},
            headers=self._headers,
        )
        response.raise_for_status()
        return response.json()
