"""
Dedicated LLM client for the research executor agent.

Talks to Qwen3.5-27B running on 10.185.1.8:8686 via OpenAI-compatible API.
Separate from BackgroundLLMClient to avoid contention with Sara's ACS sessions.
"""

import logging
from typing import Dict, List, Optional, Any

import asyncio
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RESEARCH_LLM_URL = settings.research_llm_url
RESEARCH_LLM_MODEL = settings.research_llm_model
RESEARCH_LLM_TIMEOUT = settings.research_llm_timeout
RESEARCH_LLM_MAX_TOKENS = settings.research_llm_max_tokens

# Statuses worth retrying: 503 is llama-server still loading the model, 502/504 are
# a proxy in front of it, 429 is slot contention on the 2-slot bg lane.
_TRANSIENT_STATUS = {429, 502, 503, 504}
RESEARCH_LLM_MAX_RETRIES = 5
RESEARCH_LLM_RETRY_BASE_DELAY = 5.0  # 5s, 10s, 20s, 40s, 80s -> ~2.5 min of cover

# Any other 5xx — 507 Insufficient Storage above all — means the lane could not
# allocate its KV cache: it is out of memory, not momentarily busy. Hammering it
# makes that worse, so these get a slow ladder, and when it doesn't clear the
# caller gets a typed exception it can park the whole plan on. Without this a
# 507 fell straight through to raise_for_status, the step was marked failed, the
# loop advanced, and six steps burned in 1.3 seconds (2026-09-01).
_OVERLOAD_RETRY_DELAYS = (30.0, 120.0, 300.0)


class ResearchLLMOverloaded(Exception):
    """The research lane is unavailable after its full retry ladder.

    Callers should stall the plan (resumable) rather than fail its steps.
    """

    def __init__(self, status_code: int, body: str = ""):
        self.status_code = status_code
        self.body = body or ""
        super().__init__(
            f"research LLM lane unavailable: HTTP {status_code}: {self.body[:300]}"
        )


class ResearchLLMClient:
    """Async HTTP client for the dedicated research LLM."""

    def __init__(
        self,
        base_url: str = RESEARCH_LLM_URL,
        model: Optional[str] = None,
        timeout: float = RESEARCH_LLM_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        # If no model passed, discover at first call via /v1/models. The configured
        # default is only a fallback for when discovery fails.
        self._explicit_model = model
        self._fallback_model = RESEARCH_LLM_MODEL
        self._resolved_model: Optional[str] = model
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                headers={"Content-Type": "application/json"},
            )
        return self._client

    async def _resolve_model(self) -> str:
        """Return the actual model loaded at the endpoint, with caching."""
        if self._resolved_model:
            return self._resolved_model
        try:
            client = await self._get_client()
            resp = await client.get("/models", timeout=5.0)
            resp.raise_for_status()
            data = resp.json()
            models = data.get("data") or data.get("models") or []
            if models:
                first = models[0]
                if isinstance(first, dict):
                    self._resolved_model = first.get("id") or first.get("name") or self._fallback_model
                elif isinstance(first, str):
                    self._resolved_model = first
                else:
                    self._resolved_model = self._fallback_model
                logger.info("Research LLM resolved to model: %s", self._resolved_model)
                return self._resolved_model
        except Exception as e:
            logger.warning("Research LLM model discovery failed (%s); using fallback %s", e, self._fallback_model)
        self._resolved_model = self._fallback_model
        return self._resolved_model

    @property
    def model(self) -> str:
        """Backwards-compatible property; may return fallback before first resolve."""
        return self._resolved_model or self._fallback_model

    async def health_check(self) -> bool:
        """Check if the research LLM is reachable."""
        try:
            client = await self._get_client()
            resp = await client.get("/models", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = RESEARCH_LLM_MAX_TOKENS,
        tool_choice: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Call the research LLM with OpenAI-compatible chat completions.

        Returns the full response dict (OpenAI format).
        """
        client = await self._get_client()
        model = await self._resolve_model()

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # Qwen defaults to thinking mode, which spends the whole max_tokens
            # budget on `reasoning_content` and returns an EMPTY `content`
            # (finish_reason "length"). Every research step silently produced
            # nothing until this was set. Verified against :8081 — without it
            # "Say OK." returns content='' ; with it, content='OK.' in 3 tokens.
            "chat_template_kwargs": {"enable_thinking": False},
        }

        if tools:
            payload["tools"] = tools
            # Callers can force a specific tool (used to make the agent file its
            # findings on the final turn instead of losing the whole step).
            payload["tool_choice"] = tool_choice or "auto"

        # Transient-failure retry. A llama-server restart answers 503
        # {"message":"Loading model"} for the ~2 min it takes to mmap the weights;
        # without this every step of every queued plan fails instantly and the whole
        # research backlog is destroyed in under a second (observed 2026-08-19).
        resp = None
        transient_attempt = 0
        overload_attempt = 0
        while True:
            try:
                resp = await client.post("/chat/completions", json=payload)
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
                if transient_attempt >= RESEARCH_LLM_MAX_RETRIES:
                    raise
                delay = RESEARCH_LLM_RETRY_BASE_DELAY * (2 ** transient_attempt)
                transient_attempt += 1
                logger.warning(
                    "Research LLM %s — retrying in %.0fs (attempt %d/%d)",
                    type(e).__name__, delay, transient_attempt, RESEARCH_LLM_MAX_RETRIES,
                )
                await asyncio.sleep(delay)
                continue

            status = resp.status_code
            if status in _TRANSIENT_STATUS:
                if transient_attempt < RESEARCH_LLM_MAX_RETRIES:
                    delay = RESEARCH_LLM_RETRY_BASE_DELAY * (2 ** transient_attempt)
                    transient_attempt += 1
                    logger.warning(
                        "Research LLM %d (%s) — retrying in %.0fs (attempt %d/%d)",
                        status, resp.text[:120], delay,
                        transient_attempt, RESEARCH_LLM_MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise ResearchLLMOverloaded(status, resp.text[:400])

            if status >= 500:
                if overload_attempt < len(_OVERLOAD_RETRY_DELAYS):
                    delay = _OVERLOAD_RETRY_DELAYS[overload_attempt]
                    overload_attempt += 1
                    logger.warning(
                        "Research LLM %d (%s) — lane may be out of memory; backing off "
                        "%.0fs (attempt %d/%d)",
                        status, resp.text[:200], delay,
                        overload_attempt, len(_OVERLOAD_RETRY_DELAYS),
                    )
                    await asyncio.sleep(delay)
                    continue
                raise ResearchLLMOverloaded(status, resp.text[:400])

            break

        try:
            resp.raise_for_status()
            data = resp.json()

            # Log token usage
            usage = data.get("usage", {})
            if usage:
                logger.debug(
                    "Research LLM tokens: prompt=%d completion=%d",
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", 0),
                )

            return data

        except httpx.HTTPStatusError as e:
            logger.error("Research LLM HTTP error %d: %s", e.response.status_code, e.response.text[:500])
            raise
        except httpx.ConnectError:
            logger.error("Research LLM unreachable at %s", self.base_url)
            raise
        except Exception as e:
            logger.error("Research LLM unexpected error: %s", e)
            raise

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def get_token_usage(self, response: Dict[str, Any]) -> Dict[str, int]:
        """Extract token usage from a response."""
        usage = response.get("usage", {})
        return {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

    def get_message(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Extract the assistant message from a response."""
        return response["choices"][0]["message"]

    def get_tool_calls(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract tool calls from a response, if any."""
        msg = self.get_message(response)
        return msg.get("tool_calls", [])

    def get_text(self, response: Dict[str, Any]) -> str:
        """Extract text content from a response."""
        msg = self.get_message(response)
        return msg.get("content", "") or ""
