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

    async def publish_event(self, event: VoiceEvent) -> Dict[str, Any]:
        assert self._client is not None, "Client not started"
        url = f"{self.config.backend_url}/api/voice-control/events/publish-internal"
        response = await self._client.post(url, json=event.to_payload(), headers=self._headers)
        response.raise_for_status()
        return response.json()

