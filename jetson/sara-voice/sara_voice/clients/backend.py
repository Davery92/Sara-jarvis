"""Sara backend HTTP client.

Handles authentication (JWT cookies) and voice chat interactions.
Streams SSE responses from the backend.
"""

import asyncio
import json
import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)


class BackendClient:
    """HTTP client for Sara backend API."""

    def __init__(self, config: dict):
        backend_cfg = config.get("backend", {})
        self._base_url = backend_cfg.get("base_url", "http://10.185.1.180:8000")
        self._voice_endpoint = backend_cfg.get("voice_chat_endpoint", "/api/pi-dashboard/voice/chat")
        self._device_bootstrap_endpoint = backend_cfg.get(
            "device_bootstrap_endpoint",
            "/api/devices/bootstrap",
        )
        self._device_name = backend_cfg.get("device_name", "jetson-voice")
        self._device_type = backend_cfg.get("device_type", "jetson_voice")
        self._use_device_token_auth = bool(backend_cfg.get("use_device_token_auth", True))

        auth_cfg = backend_cfg.get("auth", {})
        self._username = auth_cfg.get("username") or os.environ.get("SARA_USERNAME", "")
        self._password = auth_cfg.get("password") or os.environ.get("SARA_PASSWORD", "")

        self._client: httpx.AsyncClient | None = None
        self._authenticated = False
        self._access_token: str | None = None
        self._device_token: str | None = (
            backend_cfg.get("device_token")
            or os.environ.get("SARA_DEVICE_TOKEN")
            or None
        )
        self._auth_lock = asyncio.Lock()
        self._device_token_lock = asyncio.Lock()
        self._last_auth_attempt = 0.0
        self._min_auth_interval_seconds = 1.0

    @staticmethod
    def _retry_after_seconds(response: httpx.Response | None) -> float:
        """Parse Retry-After header when available."""
        if response is None:
            return 0.0
        value = response.headers.get("retry-after")
        if not value:
            return 0.0
        try:
            return float(value)
        except Exception:
            return 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with cookie persistence."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(60.0, connect=10.0),
                follow_redirects=True,
            )
        return self._client

    def _auth_headers(self, extra: dict | None = None) -> dict:
        """Build request headers including bearer auth when available."""
        headers = {}
        if self._device_token:
            headers["X-Device-Token"] = self._device_token
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        if extra:
            headers.update(extra)
        return headers

    async def _ensure_device_token(self, force: bool = False) -> bool:
        """Ensure we have a pi-dashboard device token for voice endpoints."""
        if not self._use_device_token_auth:
            return False
        if self._device_token and not force:
            return True
        if not self._username:
            return False

        async with self._device_token_lock:
            if self._device_token and not force:
                return True

            client = await self._get_client()
            try:
                response = await client.post(
                    self._device_bootstrap_endpoint,
                    json={
                        "email": self._username,
                        "device_name": self._device_name,
                        "device_type": self._device_type,
                    },
                )
                response.raise_for_status()
                token = response.json().get("device_token")
                if not token:
                    return False
                self._device_token = token
                logger.info("Device token ready for pi-dashboard voice auth")
                return True
            except Exception as e:
                logger.warning("Failed to bootstrap device token: %s", e)
                return False

    async def authenticate(self, force: bool = False) -> bool:
        """Authenticate with Sara backend and store JWT cookie."""
        if self._authenticated and not force:
            return True

        if not self._username or not self._password:
            logger.error("No credentials provided. Set SARA_USERNAME and SARA_PASSWORD env vars.")
            return False

        async with self._auth_lock:
            if self._authenticated and not force:
                return True

            now = time.monotonic()
            if not force and (now - self._last_auth_attempt) < self._min_auth_interval_seconds:
                return self._authenticated
            self._last_auth_attempt = now

            client = await self._get_client()
            try:
                response = await client.post(
                    "/auth/login",
                    json={"email": self._username, "password": self._password},
                )

                if response.status_code == 429:
                    retry_after = self._retry_after_seconds(response)
                    if retry_after > 0:
                        logger.warning("Authentication rate-limited (retry-after=%ss)", retry_after)
                    else:
                        logger.warning("Authentication rate-limited (429)")
                    self._authenticated = False
                    return False

                response.raise_for_status()
                token = None
                try:
                    token = response.json().get("access_token")
                except Exception:
                    token = None
                self._access_token = token
                self._authenticated = True
                logger.info("Authenticated with Sara backend")
                return True
            except httpx.HTTPStatusError as e:
                self._authenticated = False
                self._access_token = None
                logger.error("Authentication failed: %s", e)
                return False
            except Exception as e:
                self._authenticated = False
                self._access_token = None
                logger.error("Authentication failed: %s", e)
                return False

    async def voice_chat(self, transcript: str, conversation_id: str | None = None):
        """Send voice transcript and stream SSE response.

        Yields response text chunks as they arrive.
        """
        # Prefer device-token auth for pi-dashboard endpoints.
        has_device_token = await self._ensure_device_token()
        if not has_device_token and not await self.authenticate():
            logger.error("Skipping voice chat; no valid auth available")
            return

        client = await self._get_client()

        payload = {
            "message": transcript,
            "source": "voice",
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id

        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                async with client.stream(
                    "POST",
                    self._voice_endpoint,
                    json=payload,
                    headers=self._auth_headers({"Accept": "text/event-stream"}),
                ) as response:
                    if response.status_code == 401 and attempt + 1 < max_attempts:
                        logger.warning("Voice chat auth expired; refreshing auth")
                        if await self._ensure_device_token(force=True):
                            continue
                        self._authenticated = False
                        self._access_token = None
                        if await self.authenticate(force=True):
                            continue
                        logger.error("Re-authentication failed; aborting voice chat")
                        return

                    if response.status_code == 429:
                        retry_after = self._retry_after_seconds(response)
                        if retry_after > 0:
                            logger.warning("Voice chat rate-limited (retry-after=%ss)", retry_after)
                        else:
                            logger.warning("Voice chat rate-limited (429)")
                        return

                    response.raise_for_status()
                    buffer = ""
                    saw_text_chunk = False

                    async for chunk in response.aiter_text():
                        buffer += chunk
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()

                            if not line:
                                continue

                            if line.startswith("data: "):
                                data = line[6:]
                                if data == "[DONE]":
                                    return

                                try:
                                    parsed = json.loads(data)
                                    event_type = parsed.get("type")

                                    # Pi-dashboard voice SSE protocol:
                                    # - text_chunk: incremental content
                                    # - final_response: full final content
                                    # - done: completion marker
                                    if event_type == "text_chunk":
                                        text = parsed.get("content", "")
                                        if text:
                                            saw_text_chunk = True
                                            yield text
                                        continue

                                    if event_type == "final_response":
                                        text = parsed.get("content", "")
                                        # Avoid double-emitting full response when chunks already streamed.
                                        if text and not saw_text_chunk:
                                            yield text
                                        continue

                                    if event_type == "done":
                                        return

                                    # Generic OpenAI/other SSE payloads.
                                    text = parsed.get("text", "")
                                    if text:
                                        yield text
                                        continue

                                    if event_type is None:
                                        content = parsed.get("content", "")
                                        if content:
                                            yield content
                                except json.JSONDecodeError:
                                    # Plain text chunk
                                    if data:
                                        yield data
                    return
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401 and attempt + 1 < max_attempts:
                    logger.warning("Voice chat HTTP 401; retrying after auth refresh")
                    if await self._ensure_device_token(force=True):
                        continue
                    self._authenticated = False
                    self._access_token = None
                    if await self.authenticate(force=True):
                        continue
                    logger.error("Re-authentication failed; aborting voice chat")
                    return
                if e.response.status_code == 429:
                    retry_after = self._retry_after_seconds(e.response)
                    if retry_after > 0:
                        logger.warning("Voice chat HTTP 429 (retry-after=%ss)", retry_after)
                    else:
                        logger.warning("Voice chat HTTP 429")
                    return
                logger.error("Voice chat HTTP error: %s", e)
                raise
            except Exception as e:
                logger.error("Voice chat error: %s", e)
                raise

    async def send_event(self, endpoint: str, data: dict) -> bool:
        """Send a generic event to a backend endpoint."""
        # Best effort: some endpoints are open; others need bearer/device auth.
        await self._ensure_device_token()
        if not self._authenticated:
            await self.authenticate()

        client = await self._get_client()
        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                response = await client.post(
                    endpoint,
                    json=data,
                    headers=self._auth_headers(),
                )
                if response.status_code == 401 and attempt + 1 < max_attempts:
                    logger.warning("Event auth expired for %s; re-authenticating", endpoint)
                    self._authenticated = False
                    self._access_token = None
                    if await self.authenticate(force=True):
                        continue
                    return False
                response.raise_for_status()
                return True
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401 and attempt + 1 < max_attempts:
                    logger.warning("Event HTTP 401 for %s; retrying", endpoint)
                    self._authenticated = False
                    self._access_token = None
                    if await self.authenticate(force=True):
                        continue
                    return False
                logger.error("Failed to send event to %s: %s", endpoint, e)
                return False
            except Exception as e:
                logger.error("Failed to send event to %s: %s", endpoint, e)
                return False
        return False

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._authenticated = False
        self._access_token = None

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated
