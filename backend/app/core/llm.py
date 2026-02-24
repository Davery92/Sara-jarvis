"""
LLM Client with Automatic Failover

Features:
- Primary/fallback endpoint management
- Background health checks every 30 seconds
- Request-level failover with short timeouts
- Auto-recovery when primary comes back
- Logging/metrics for failover events
- Backward compatible with existing LLMClient API
"""
import asyncio
import httpx
import json
import logging
import time
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable

from app.core.config import settings

logger = logging.getLogger(__name__)


def _load_persisted_ai_setting_overrides() -> Dict[str, str]:
    """
    Load persisted AI settings from app_settings.

    Background workers (e.g., Celery) don't run the FastAPI startup hook that
    hydrates runtime globals from the DB, so they can drift back to defaults.
    Reading app_settings here keeps model selection consistent across processes.
    """
    try:
        from sqlalchemy import text
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            rows = db.execute(text("""
                SELECT key, value
                FROM app_settings
                WHERE key IN (
                    'bg_llm_primary_url',
                    'bg_llm_primary_model',
                    'bg_llm_fallback_url',
                    'bg_llm_fallback_model',
                    'bg_llm_request_timeout',
                    'bg_llm_connect_timeout',
                    'bg_llm_num_ctx'
                )
            """)).fetchall()
            return {row[0]: row[1] for row in rows}
        finally:
            db.close()
    except Exception as e:
        logger.debug(f"Could not load persisted AI setting overrides: {e}")
        return {}

# Global callback for token usage logging (set by application)
_token_usage_callback: Optional[Callable] = None


def set_token_usage_callback(callback: Callable):
    """Set the callback function for logging token usage"""
    global _token_usage_callback
    _token_usage_callback = callback


def get_token_usage_callback() -> Optional[Callable]:
    """Get the current token usage callback"""
    return _token_usage_callback


def is_anthropic_provider(base_url: str) -> bool:
    """Check if the base URL is for Anthropic Claude API"""
    return "api.anthropic.com" in base_url


class EndpointState(Enum):
    """State machine for endpoint health"""
    HEALTHY = "healthy"
    CHECKING = "checking"
    UNHEALTHY = "unhealthy"
    RECOVERING = "recovering"


@dataclass
class EndpointStatus:
    """Track status of an LLM endpoint"""
    url: str
    state: EndpointState = EndpointState.HEALTHY
    last_check: Optional[datetime] = None
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    total_requests: int = 0
    total_failures: int = 0
    failover_events: int = 0


class LLMClientWithFailover:
    """
    LLM client with automatic failover between primary and fallback endpoints.

    Maintains backward compatibility with LLMClient API while adding:
    - Background health checks
    - Automatic failover on request failures
    - Auto-recovery when primary comes back
    """

    def __init__(self):
        # Endpoint configuration
        self.primary_url = settings.llm_primary_url
        self.fallback_url = settings.llm_fallback_url
        self.model = settings.openai_model
        self.fallback_model = getattr(settings, 'llm_fallback_model', None) or self.model
        self.api_key = settings.openai_api_key

        # Timeout configuration
        self.request_timeout = settings.llm_request_timeout
        self.health_check_timeout = settings.llm_health_check_timeout
        self.health_check_interval = settings.llm_health_check_interval
        self.recovery_checks_required = settings.llm_recovery_checks_required

        # Endpoint states
        self.primary_status = EndpointStatus(url=self.primary_url)
        self.fallback_status = EndpointStatus(url=self.fallback_url)

        # Health check task
        self._health_check_task: Optional[asyncio.Task] = None
        self._running = False
        self._started = False

        # HTTP clients (lazy initialization)
        self._primary_client: Optional[httpx.AsyncClient] = None
        self._fallback_client: Optional[httpx.AsyncClient] = None

        # For backward compatibility - sync client for non-async contexts
        self.base_url = self.primary_url
        self.headers = self._get_headers(self.primary_url)

    def _get_headers(self, base_url: str, skip_auth_if_empty: bool = False) -> Dict[str, str]:
        """Get appropriate headers based on provider

        Args:
            base_url: The API endpoint URL
            skip_auth_if_empty: If True, skip auth header when api_key is empty/None
                               (useful for local Ollama endpoints that don't need auth)
        """
        if is_anthropic_provider(base_url):
            return {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
        else:
            # Skip auth header for local endpoints when api_key is empty
            if skip_auth_if_empty and not self.api_key:
                return {}
            return {"Authorization": f"Bearer {self.api_key}"}

    async def start(self):
        """Start background health check loop"""
        if self._running:
            return

        self._running = True
        self._started = True

        # Create HTTP clients
        self._primary_client = httpx.AsyncClient(
            base_url=self.primary_url,
            headers=self._get_headers(self.primary_url),
            timeout=self.request_timeout
        )
        self._fallback_client = httpx.AsyncClient(
            base_url=self.fallback_url,
            headers=self._get_headers(self.fallback_url),
            timeout=self.request_timeout
        )

        # Start health check loop
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        logger.info(
            f"LLM failover client started. Primary: {self.primary_url}, "
            f"Fallback: {self.fallback_url}, Health check interval: {self.health_check_interval}s"
        )

    async def stop(self):
        """Stop background health check and close clients"""
        self._running = False

        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        if self._primary_client:
            await self._primary_client.aclose()
        if self._fallback_client:
            await self._fallback_client.aclose()

        logger.info("LLM failover client stopped")

    async def _health_check_loop(self):
        """Background loop for periodic health checks on primary endpoint"""
        while self._running:
            try:
                await self._check_primary_health()
                await asyncio.sleep(self.health_check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check loop error: {e}")
                await asyncio.sleep(self.health_check_interval)

    async def _check_primary_health(self):
        """Check primary endpoint health via /v1/models endpoint"""
        self.primary_status.last_check = datetime.now()
        previous_state = self.primary_status.state

        try:
            # Use a separate client with short timeout for health checks
            async with httpx.AsyncClient(timeout=self.health_check_timeout) as client:
                response = await client.get(
                    f"{self.primary_url}/models",
                    headers=self._get_headers(self.primary_url)
                )
                response.raise_for_status()

            # Success
            self.primary_status.consecutive_failures = 0
            self.primary_status.consecutive_successes += 1
            self.primary_status.last_success = datetime.now()

            # State transition logic
            if self.primary_status.state in (EndpointState.UNHEALTHY, EndpointState.RECOVERING):
                if self.primary_status.consecutive_successes >= self.recovery_checks_required:
                    self.primary_status.state = EndpointState.HEALTHY
                    logger.info(
                        f"Primary endpoint {self.primary_url} recovered after "
                        f"{self.primary_status.consecutive_successes} successful checks"
                    )
                else:
                    self.primary_status.state = EndpointState.RECOVERING
                    logger.debug(
                        f"Primary recovering: {self.primary_status.consecutive_successes}/"
                        f"{self.recovery_checks_required} successful checks"
                    )
            else:
                self.primary_status.state = EndpointState.HEALTHY

        except Exception as e:
            self.primary_status.consecutive_failures += 1
            self.primary_status.consecutive_successes = 0
            self.primary_status.last_failure = datetime.now()

            if self.primary_status.consecutive_failures >= 2:
                if previous_state == EndpointState.HEALTHY:
                    logger.warning(
                        f"Primary endpoint {self.primary_url} marked UNHEALTHY after "
                        f"{self.primary_status.consecutive_failures} failures: {e}"
                    )
                self.primary_status.state = EndpointState.UNHEALTHY
            else:
                self.primary_status.state = EndpointState.CHECKING

    def _get_active_client_and_url(self) -> tuple[httpx.AsyncClient, str]:
        """Get the currently active endpoint based on health status"""
        if self.primary_status.state == EndpointState.HEALTHY:
            return self._primary_client, self.primary_url
        else:
            return self._fallback_client, self.fallback_url

    async def _ensure_started(self):
        """Ensure the client is started before making requests"""
        if not self._started:
            await self.start()

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Send chat completion with automatic failover.

        Strategy:
        1. If primary healthy: try primary first
        2. If primary fails or unhealthy: use fallback
        3. Track metrics for monitoring
        """
        await self._ensure_started()

        # Check if using Anthropic (no failover for Anthropic)
        if is_anthropic_provider(self.primary_url):
            return await self._anthropic_chat_completion(
                messages, tools, tool_choice, temperature, max_tokens
            )

        client, url = self._get_active_client_and_url()
        model_for_url = self.fallback_model if url == self.fallback_url else None
        payload = self._build_payload(messages, tools, tool_choice, temperature, max_tokens, model_override=model_for_url)
        req_timeout = timeout or self.request_timeout

        try:
            # Track request count for the endpoint being used
            if url == self.primary_url:
                self.primary_status.total_requests += 1
            else:
                self.fallback_status.total_requests += 1

            response = await client.post("/chat/completions", json=payload, timeout=req_timeout)
            response.raise_for_status()

            result = response.json()
            logger.debug(f"Chat completion successful via {url}")

            # Track token usage with endpoint context
            self._track_token_usage(result, url)

            return result

        except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.ConnectError) as e:
            logger.warning(f"Request to {url} failed: {e}")

            # Mark primary as potentially unhealthy if it failed
            if url == self.primary_url:
                self.primary_status.consecutive_failures += 1
                self.primary_status.total_failures += 1
                if self.primary_status.consecutive_failures >= 2:
                    self.primary_status.state = EndpointState.UNHEALTHY

            # Try fallback if we were using primary
            if url != self.fallback_url:
                try:
                    logger.info(f"Attempting failover to {self.fallback_url}")
                    self.primary_status.failover_events += 1
                    self.fallback_status.total_requests += 1

                    fallback_payload = self._build_payload(
                        messages, tools, tool_choice, temperature, max_tokens,
                        model_override=self.fallback_model
                    )
                    response = await self._fallback_client.post("/chat/completions", json=fallback_payload, timeout=req_timeout)
                    response.raise_for_status()

                    result = response.json()
                    logger.info(f"Failover to {self.fallback_url} successful")
                    self.fallback_status.last_success = datetime.now()
                    self.fallback_status.consecutive_successes += 1

                    # Track token usage with fallback context
                    self._track_token_usage(result, self.fallback_url)

                    return result

                except Exception as fallback_error:
                    self.fallback_status.total_failures += 1
                    self.fallback_status.consecutive_failures += 1
                    self.fallback_status.last_failure = datetime.now()
                    logger.error(f"Fallback to {self.fallback_url} also failed: {fallback_error}")
                    raise

            raise

    def _build_payload(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]],
        tool_choice: str,
        temperature: float,
        max_tokens: Optional[int],
        model_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build request payload for OpenAI-compatible endpoint"""
        payload = {
            "model": model_override or self.model,
            "messages": messages,
            "temperature": temperature,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        return payload

    def _track_token_usage(self, result: Dict[str, Any], endpoint_url: str = None):
        """Track token usage if callback is set"""
        usage = result.get("usage", {})
        if usage and _token_usage_callback:
            try:
                _token_usage_callback(
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    model=self.model,
                    operation_type="chat"
                )
            except Exception as e:
                logger.error(
                    f"Token usage callback failed: {e}. "
                    f"Usage data: prompt={usage.get('prompt_tokens')}, "
                    f"completion={usage.get('completion_tokens')}, "
                    f"model={self.model}, endpoint={endpoint_url or 'unknown'}",
                    exc_info=True
                )

    async def _anthropic_chat_completion(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """Send chat completion request to Anthropic Claude API and convert response to OpenAI format"""

        # Extract system message if present
        system_content = None
        filtered_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_content = msg.get("content", "")
            else:
                filtered_messages.append(msg)

        # Build Anthropic request payload
        payload = {
            "model": self.model,
            "messages": filtered_messages,
            "temperature": temperature,
            "max_tokens": max_tokens or 4096,
        }

        if system_content:
            payload["system"] = system_content

        # Convert OpenAI tools format to Anthropic format
        if tools:
            anthropic_tools = []
            for tool in tools:
                if tool.get("type") == "function":
                    func = tool.get("function", {})
                    anthropic_tools.append({
                        "name": func.get("name"),
                        "description": func.get("description", ""),
                        "input_schema": func.get("parameters", {"type": "object", "properties": {}})
                    })
            if anthropic_tools:
                payload["tools"] = anthropic_tools
                if tool_choice == "auto":
                    payload["tool_choice"] = {"type": "auto"}
                elif tool_choice == "none":
                    payload["tool_choice"] = {"type": "none"}
                elif tool_choice == "required":
                    payload["tool_choice"] = {"type": "any"}

        try:
            logger.info(f"Sending chat request to Anthropic API at {self.primary_url}")
            response = await self._primary_client.post("/messages", json=payload)
            response.raise_for_status()

            anthropic_result = response.json()
            logger.info("Anthropic chat completion successful")

            # Convert response to OpenAI format
            openai_result = self._convert_anthropic_to_openai(anthropic_result)

            # Track token usage
            usage = anthropic_result.get("usage", {})
            if usage and _token_usage_callback:
                try:
                    _token_usage_callback(
                        prompt_tokens=usage.get("input_tokens", 0),
                        completion_tokens=usage.get("output_tokens", 0),
                        total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                        model=self.model,
                        operation_type="chat"
                    )
                except Exception as e:
                    logger.error(
                        f"Anthropic token usage callback failed: {e}. "
                        f"Usage data: input={usage.get('input_tokens')}, "
                        f"output={usage.get('output_tokens')}, model={self.model}",
                        exc_info=True
                    )

            return openai_result

        except httpx.HTTPError as e:
            logger.error(f"HTTP error in Anthropic chat completion: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in Anthropic chat completion: {e}")
            raise

    def _convert_anthropic_to_openai(self, anthropic_response: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Anthropic API response to OpenAI-compatible format"""

        content_blocks = anthropic_response.get("content", [])
        text_content = ""
        tool_calls = []

        for block in content_blocks:
            if block.get("type") == "text":
                text_content += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id"),
                    "type": "function",
                    "function": {
                        "name": block.get("name"),
                        "arguments": json.dumps(block.get("input", {}))
                    }
                })

        message = {
            "role": "assistant",
            "content": text_content if text_content else None
        }

        if tool_calls:
            message["tool_calls"] = tool_calls

        stop_reason_map = {
            "end_turn": "stop",
            "max_tokens": "length",
            "tool_use": "tool_calls",
            "stop_sequence": "stop"
        }
        finish_reason = stop_reason_map.get(
            anthropic_response.get("stop_reason", "stop"),
            "stop"
        )

        usage = anthropic_response.get("usage", {})
        return {
            "id": anthropic_response.get("id", ""),
            "object": "chat.completion",
            "created": 0,
            "model": anthropic_response.get("model", self.model),
            "choices": [{
                "index": 0,
                "message": message,
                "finish_reason": finish_reason
            }],
            "usage": {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            }
        }

    async def get_embedding(self, text: str, model: Optional[str] = None) -> List[float]:
        """Get embedding for text using embedding endpoint (no failover for embeddings)"""

        # Normalize embedding base to ensure /v1 path is present
        emb_base = (settings.embedding_base_url or "").rstrip("/")
        if not emb_base.endswith("/v1"):
            emb_base = emb_base + "/v1"

        # Local Ollama endpoints don't require auth - skip header if api_key is empty
        embedding_client = httpx.AsyncClient(
            base_url=emb_base,
            headers=self._get_headers(emb_base, skip_auth_if_empty=True),
            timeout=60.0
        )

        payload = {
            "model": model or settings.embedding_model,
            "input": text
        }

        try:
            logger.debug(f"Getting embedding for text: {text[:100]}...")
            response = await embedding_client.post("/embeddings", json=payload)
            response.raise_for_status()

            result = response.json()
            embedding = result["data"][0]["embedding"]
            logger.debug("Embedding generation successful")

            # Track embedding token usage
            usage = result.get("usage", {})
            if usage and _token_usage_callback:
                try:
                    embedding_model = model or settings.embedding_model
                    _token_usage_callback(
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=0,
                        total_tokens=usage.get("total_tokens", usage.get("prompt_tokens", 0)),
                        model=embedding_model,
                        operation_type="embedding"
                    )
                except Exception as e:
                    logger.error(
                        f"Embedding token usage callback failed: {e}. "
                        f"Usage data: prompt={usage.get('prompt_tokens')}, "
                        f"model={model or settings.embedding_model}, endpoint={emb_base}",
                        exc_info=True
                    )

            await embedding_client.aclose()
            return embedding

        except httpx.HTTPError as e:
            logger.error(f"HTTP error in embedding: {e}")
            await embedding_client.aclose()
            raise
        except Exception as e:
            logger.error(f"Unexpected error in embedding: {e}")
            await embedding_client.aclose()
            raise

    async def score_importance(self, content: str) -> float:
        """Score content importance using a small model call"""

        messages = [
            {
                "role": "system",
                "content": "Rate the importance of this content on a scale of 0.0 to 1.0. Consider: personal preferences, important decisions, deadlines, stable facts, and future utility. Respond with only a JSON object: {\"importance\": float}"
            },
            {
                "role": "user",
                "content": content
            }
        ]

        try:
            result = await self.chat_completion(
                messages=messages,
                temperature=0.1,
                max_tokens=50
            )

            response_text = result["choices"][0]["message"]["content"]
            parsed = json.loads(response_text)
            importance = max(0.0, min(1.0, parsed.get("importance", 0.0)))

            logger.debug(f"Importance scored: {importance}")
            return importance

        except Exception as e:
            logger.warning(f"Failed to score importance: {e}, defaulting to 0.1")
            return 0.1

    async def close(self):
        """Close the HTTP clients (alias for stop)"""
        await self.stop()

    def get_status(self) -> Dict[str, Any]:
        """Get current failover status for monitoring"""
        return {
            "primary": {
                "url": self.primary_url,
                "state": self.primary_status.state.value,
                "last_check": self.primary_status.last_check.isoformat() if self.primary_status.last_check else None,
                "last_success": self.primary_status.last_success.isoformat() if self.primary_status.last_success else None,
                "last_failure": self.primary_status.last_failure.isoformat() if self.primary_status.last_failure else None,
                "consecutive_failures": self.primary_status.consecutive_failures,
                "consecutive_successes": self.primary_status.consecutive_successes,
                "total_requests": self.primary_status.total_requests,
                "total_failures": self.primary_status.total_failures,
                "failover_events": self.primary_status.failover_events,
            },
            "fallback": {
                "url": self.fallback_url,
                "state": self.fallback_status.state.value,
                "last_success": self.fallback_status.last_success.isoformat() if self.fallback_status.last_success else None,
                "last_failure": self.fallback_status.last_failure.isoformat() if self.fallback_status.last_failure else None,
                "total_requests": self.fallback_status.total_requests,
                "total_failures": self.fallback_status.total_failures,
                "consecutive_successes": self.fallback_status.consecutive_successes,
                "consecutive_failures": self.fallback_status.consecutive_failures,
            },
            "active_endpoint": self.primary_url if self.primary_status.state == EndpointState.HEALTHY else self.fallback_url,
            "health_check_interval_seconds": self.health_check_interval,
            "request_timeout_seconds": self.request_timeout,
        }


class BackgroundLLMClient:
    """
    Dedicated LLM client for background processing tasks.

    Uses separate settings from the chat model to ensure background services
    (dreaming, memory consolidation, daily briefs, etc.) always use local models
    regardless of what model is selected for interactive chat.

    Features:
    - Simple failover: try primary model, fall back to fallback model
    - Does NOT respect chat model settings
    - Always uses local models configured in bg_llm_* settings
    """

    def __init__(self):
        self._load_config_from_settings()

        # HTTP clients (lazy initialization)
        self._primary_client: Optional[httpx.AsyncClient] = None
        self._fallback_client: Optional[httpx.AsyncClient] = None
        self._started = False
        self._lesson_lock_group = "lesson_generation"
        self._lesson_lock_poll_seconds = 5.0
        self._lesson_lock_log_interval_seconds = 60.0

    def _load_config_from_settings(self):
        """Load current background LLM configuration from runtime settings."""
        # Start from in-memory settings.
        primary_url = settings.bg_llm_primary_url
        primary_model = settings.bg_llm_primary_model
        fallback_url = settings.bg_llm_fallback_url
        fallback_model = settings.bg_llm_fallback_model
        request_timeout = settings.bg_llm_request_timeout
        connect_timeout = settings.bg_llm_connect_timeout
        num_ctx = settings.bg_llm_num_ctx

        # Override from persisted DB settings when available (important for
        # Celery/background processes that don't run FastAPI startup hydration).
        persisted = _load_persisted_ai_setting_overrides()
        if persisted:
            primary_url = persisted.get("bg_llm_primary_url", primary_url)
            primary_model = persisted.get("bg_llm_primary_model", primary_model)
            fallback_url = persisted.get("bg_llm_fallback_url", fallback_url)
            fallback_model = persisted.get("bg_llm_fallback_model", fallback_model)
            request_timeout = persisted.get("bg_llm_request_timeout", request_timeout)
            connect_timeout = persisted.get("bg_llm_connect_timeout", connect_timeout)
            num_ctx = persisted.get("bg_llm_num_ctx", num_ctx)

            # Keep process-local settings object aligned so other code reading
            # from settings sees the same values.
            settings.bg_llm_primary_url = str(primary_url)
            settings.bg_llm_primary_model = str(primary_model)
            settings.bg_llm_fallback_url = str(fallback_url)
            settings.bg_llm_fallback_model = str(fallback_model)
            settings.bg_llm_request_timeout = float(request_timeout)
            settings.bg_llm_connect_timeout = float(connect_timeout)
            settings.bg_llm_num_ctx = int(num_ctx)

        self.primary_url = str(primary_url)
        self.primary_model = str(primary_model)
        self.fallback_url = str(fallback_url)
        self.fallback_model = str(fallback_model)
        self.request_timeout = max(10.0, float(request_timeout))
        self.connect_timeout = max(1.0, float(connect_timeout))
        self.default_num_ctx = max(2048, int(num_ctx))

    async def _ensure_started(self):
        """Initialize HTTP clients if not already started"""
        if self._started:
            return

        request_timeout = httpx.Timeout(self.request_timeout, connect=self.connect_timeout)
        self._primary_client = httpx.AsyncClient(
            base_url=self.primary_url,
            timeout=request_timeout
        )
        self._fallback_client = httpx.AsyncClient(
            base_url=self.fallback_url,
            timeout=request_timeout
        )
        self._started = True
        logger.info(
            f"Background LLM client started. Primary: {self.primary_url} ({self.primary_model}), "
            f"Fallback: {self.fallback_url} ({self.fallback_model}), num_ctx={self.default_num_ctx}, "
            f"timeouts(connect={self.connect_timeout}s, request={self.request_timeout}s)"
        )

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,  # Allow override for specific tasks
        options: Optional[Dict[str, Any]] = None,
        allow_during_lesson_generation: bool = False,
        allow_fallback: bool = True,
        request_timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Send chat completion with simple failover for background tasks.

        Strategy:
        1. Try primary model/endpoint first
        2. On failure, fall back to fallback model/endpoint
        """
        if not allow_during_lesson_generation:
            await self._wait_for_lesson_generation_window()

        await self._ensure_started()
        req_timeout = float(request_timeout) if request_timeout is not None else float(self.request_timeout)
        req_timeout = max(10.0, req_timeout)

        use_model = model or self.primary_model
        payload = {
            "model": use_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        merged_options: Dict[str, Any] = {}
        if options:
            merged_options.update(options)
        if "num_ctx" not in merged_options:
            merged_options["num_ctx"] = self.default_num_ctx
        if merged_options:
            payload["options"] = merged_options

        try:
            logger.debug(f"Background LLM request to {self.primary_url} with model {use_model}")
            result = await self._request_chat_with_compat(
                client=self._primary_client,
                payload=payload,
                endpoint_url=self.primary_url,
                request_timeout=req_timeout,
            )
            logger.debug(f"Background LLM request successful via primary endpoint")
            return result

        except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.ConnectError) as e:
            if not allow_fallback:
                logger.warning(
                    f"Background LLM primary request failed with fallback disabled: {e}"
                )
                raise

            logger.warning(f"Background LLM primary request failed: {e}, trying fallback")

            # Try fallback
            try:
                fallback_model = self.fallback_model if model in (None, self.primary_model) else model
                fallback_payload = {
                    **payload,
                    "model": fallback_model,
                }
                logger.debug(f"Background LLM failover to {self.fallback_url} with model {self.fallback_model}")
                result = await self._request_chat_with_compat(
                    client=self._fallback_client,
                    payload=fallback_payload,
                    endpoint_url=self.fallback_url,
                    request_timeout=req_timeout,
                )
                logger.info(f"Background LLM failover to {self.fallback_url} successful")
                return result
            except Exception as fallback_error:
                logger.error(f"Background LLM fallback also failed: {fallback_error}")
                raise

    async def _request_chat_with_compat(
        self,
        client: httpx.AsyncClient,
        payload: Dict[str, Any],
        endpoint_url: str,
        request_timeout: float,
    ) -> Dict[str, Any]:
        """
        Request chat completion with compatibility fallback.

        Normal path: OpenAI-compatible /chat/completions.
        Compatibility path: if endpoint returns 404, try Ollama /api/chat
        and convert response to OpenAI-like schema expected by callers.
        """
        try:
            response = await client.post("/chat/completions", json=payload, timeout=request_timeout)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response is not None else None
            if status == 404:
                logger.warning(
                    f"Endpoint {endpoint_url} returned 404 for /chat/completions; "
                    "trying Ollama compatibility at /api/chat"
                )
                return await self._ollama_chat_completion(
                    client=client,
                    payload=payload,
                    request_timeout=request_timeout,
                )
            raise

    async def _ollama_chat_completion(
        self,
        client: httpx.AsyncClient,
        payload: Dict[str, Any],
        request_timeout: float,
    ) -> Dict[str, Any]:
        """Call Ollama /api/chat and normalize output to OpenAI schema."""
        options = dict(payload.get("options") or {})
        temperature = payload.get("temperature")
        max_tokens = payload.get("max_tokens")
        if temperature is not None and "temperature" not in options:
            options["temperature"] = temperature
        if max_tokens is not None and "num_predict" not in options:
            options["num_predict"] = max_tokens

        ollama_payload: Dict[str, Any] = {
            "model": payload.get("model"),
            "messages": payload.get("messages", []),
            "stream": False,
        }
        if options:
            ollama_payload["options"] = options

        response = await client.post("/api/chat", json=ollama_payload, timeout=request_timeout)
        response.raise_for_status()
        raw = response.json()

        message = raw.get("message") if isinstance(raw, dict) else {}
        content = ""
        if isinstance(message, dict):
            content = str(message.get("content") or "").strip()
        if not content:
            content = str(raw.get("response") or "").strip() if isinstance(raw, dict) else ""

        prompt_tokens = int(raw.get("prompt_eval_count") or 0) if isinstance(raw, dict) else 0
        completion_tokens = int(raw.get("eval_count") or 0) if isinstance(raw, dict) else 0
        total_tokens = prompt_tokens + completion_tokens

        return {
            "id": str(raw.get("id") or f"ollama-{int(time.time() * 1000)}") if isinstance(raw, dict) else f"ollama-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": str(raw.get("model") or payload.get("model") or "") if isinstance(raw, dict) else str(payload.get("model") or ""),
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
        }

    async def _wait_for_lesson_generation_window(self) -> None:
        """
        Pause background LLM requests while high-context lesson generation is active.

        This prevents periodic background model jobs from competing with
        lesson generation and destabilizing the model process.
        """
        try:
            from app.services.autonomy.coordination import get_coordinator

            coordinator = get_coordinator()
            waited_seconds = 0.0
            next_log_at = 0.0
            while True:
                holder = await coordinator.get_lock_holder(self._lesson_lock_group)
                if not holder:
                    if waited_seconds > 0:
                        logger.info(
                            f"Background LLM resumed after waiting {int(waited_seconds)}s "
                            "for lesson generation lock"
                        )
                    return

                if waited_seconds >= next_log_at:
                    logger.info(
                        "Background LLM paused while lesson generation is active "
                        f"(holder={holder}, waited={int(waited_seconds)}s)"
                    )
                    next_log_at = waited_seconds + self._lesson_lock_log_interval_seconds
                await asyncio.sleep(self._lesson_lock_poll_seconds)
                waited_seconds += self._lesson_lock_poll_seconds
        except Exception as e:
            # Fail-open: if lock coordination is unavailable, avoid breaking
            # all background model traffic.
            logger.debug(f"Lesson-generation pause check unavailable: {e}")

    async def close(self):
        """Close HTTP clients"""
        if self._primary_client:
            await self._primary_client.aclose()
        if self._fallback_client:
            await self._fallback_client.aclose()
        self._primary_client = None
        self._fallback_client = None
        self._started = False
        logger.info("Background LLM client closed")

    async def refresh_config(self):
        """
        Hot-reload client configuration after settings changes.
        Safe to call repeatedly.
        """
        old = (self.primary_url, self.primary_model, self.fallback_url, self.fallback_model)
        self._load_config_from_settings()
        new = (self.primary_url, self.primary_model, self.fallback_url, self.fallback_model)

        # Force client recreation so base URLs/timeouts update immediately.
        await self.close()

        if old != new:
            logger.info(
                "Background LLM config refreshed. "
                f"Primary: {self.primary_url} ({self.primary_model}), "
                f"Fallback: {self.fallback_url} ({self.fallback_model})"
            )

    def get_status(self) -> Dict[str, Any]:
        """Get current configuration status"""
        return {
            "primary_url": self.primary_url,
            "primary_model": self.primary_model,
            "fallback_url": self.fallback_url,
            "fallback_model": self.fallback_model,
            "request_timeout": self.request_timeout,
            "connect_timeout": self.connect_timeout,
            "num_ctx": self.default_num_ctx,
            "started": self._started
        }


# Global background LLM client instance
_background_llm_client: Optional[BackgroundLLMClient] = None


def get_background_llm_client() -> BackgroundLLMClient:
    """Get or create the background LLM client singleton"""
    global _background_llm_client
    if _background_llm_client is None:
        _background_llm_client = BackgroundLLMClient()
    return _background_llm_client


# Global LLM client instance with failover
_llm_client: Optional[LLMClientWithFailover] = None


def get_llm_client() -> LLMClientWithFailover:
    """Get or create the LLM client singleton"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClientWithFailover()
    return _llm_client


# Backward compatibility alias - the global llm_client instance
llm_client = get_llm_client()


# Legacy LLMClient class for backward compatibility
LLMClient = LLMClientWithFailover
