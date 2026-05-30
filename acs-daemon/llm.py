"""OpenAI-compatible LLM client for the daemon.

Talks to the 8081 endpoint (qwen3.6-27b by default). One
chat-completion call per think/reflect turn. JSON-mode would be nicer but
the MLX server's support is inconsistent, so we ask for JSON in the prompt
and parse defensively.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import httpx

logger = logging.getLogger("acs-daemon.llm")


class LLMClient:
    def __init__(self, base_url: str, model: str, timeout_seconds: float = 60.0) -> None:
        self._base = base_url.rstrip("/")
        self._model = model
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=httpx.Timeout(timeout_seconds, connect=10.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 600,
        temperature: float = 0.7,
        enable_thinking: bool = False,
    ) -> Optional[str]:
        """Returns the assistant's text content, or None on failure.

        Qwen 3.x defaults to thinking-mode which dumps chain-of-thought into a
        `reasoning` field and burns most of the token budget before producing
        `content`. We disable thinking via `chat_template_kwargs` (the canonical
        switch on vLLM-style servers) and also fall back to `reasoning` if
        `content` ends up empty.
        """
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
        }
        try:
            r = await self._client.post("/chat/completions", json=body)
        except httpx.HTTPError as e:
            logger.warning("llm network error: %s", e)
            return None
        if r.status_code >= 400:
            logger.warning("llm rejected: %s %s", r.status_code, r.text[:300])
            return None
        try:
            data = r.json()
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, ValueError) as e:
            logger.warning("llm response unparseable: %s | body=%s", e, r.text[:300])
            return None
        # Prefer content; fall back to reasoning if the server dumped CoT there.
        content = (msg.get("content") or "").strip()
        if content:
            return content
        reasoning = (msg.get("reasoning") or "").strip()
        if reasoning:
            logger.debug("llm: empty content, falling back to reasoning field")
            return reasoning
        finish = data["choices"][0].get("finish_reason")
        logger.warning("llm: empty content and reasoning (finish_reason=%s)", finish)
        return None


_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


def parse_json_loose(text: str) -> Optional[dict[str, Any]]:
    """Pull the first {...} block out of arbitrary model output, parse as JSON.

    Models often wrap JSON in markdown fences, prose, or chain-of-thought.
    This grabs the first balanced-looking block and tries to load it.
    Returns None if nothing parses.
    """
    if not text:
        return None
    # Fast path: maybe the whole response is JSON.
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    # Fall back to the first {...} match.
    m = _JSON_BLOCK.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
