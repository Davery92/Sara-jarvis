"""
Dedicated LLM client for the research executor agent.

Talks to Qwen3.5-27B running on 10.185.1.8:8686 via OpenAI-compatible API.
Separate from BackgroundLLMClient to avoid contention with Sara's ACS sessions.
"""

import logging
from typing import Dict, List, Optional, Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RESEARCH_LLM_URL = settings.research_llm_url
RESEARCH_LLM_MODEL = settings.research_llm_model
RESEARCH_LLM_TIMEOUT = settings.research_llm_timeout
RESEARCH_LLM_MAX_TOKENS = settings.research_llm_max_tokens


class ResearchLLMClient:
    """Async HTTP client for the dedicated research LLM."""

    def __init__(
        self,
        base_url: str = RESEARCH_LLM_URL,
        model: str = RESEARCH_LLM_MODEL,
        timeout: float = RESEARCH_LLM_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
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

    async def health_check(self) -> bool:
        """Check if the research LLM is reachable."""
        try:
            client = await self._get_client()
            resp = await client.get("/v1/models", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = RESEARCH_LLM_MAX_TOKENS,
    ) -> Dict[str, Any]:
        """
        Call the research LLM with OpenAI-compatible chat completions.

        Returns the full response dict (OpenAI format).
        """
        client = await self._get_client()

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            resp = await client.post("/chat/completions", json=payload)
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
