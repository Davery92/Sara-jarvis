"""Direct calls to the real chat-lane model endpoint.

Deliberately bypasses `SimpleLLMClient`/`chat_stream` (both write episodes,
memory, and other production state) -- this is the "direct-model study" arm:
real model generation, isolated from any database or write path. See
sampling.py for why the payload fields mirror `_apply_local_qwen_chat_sampling`
verbatim.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

PRIMARY_URL = os.getenv("OPENAI_BASE_URL", "http://100.104.68.115:8082/v1").rstrip("/")
MODEL_ID = os.getenv("OPENAI_MODEL", "qwen3.8-27b")
API_KEY = os.getenv("OPENAI_API_KEY", "dummy")
REQUEST_TIMEOUT_S = 180.0


@dataclass
class ModelCallResult:
    content: str
    tool_calls: List[dict] = field(default_factory=list)
    finish_reason: Optional[str] = None
    usage: Optional[dict] = None
    elapsed_s: float = 0.0
    raw: Optional[dict] = None
    error: Optional[str] = None


async def call_model(
    messages: List[Dict[str, Any]],
    *,
    tools: Optional[List[dict]] = None,
    sampling_fields: Dict[str, Any],
    max_tokens: int = 4096,
    timeout_s: float = REQUEST_TIMEOUT_S,
) -> ModelCallResult:
    payload: Dict[str, Any] = {
        "model": MODEL_ID,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
    payload.update(sampling_fields)

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(f"{PRIMARY_URL}/chat/completions", json=payload, headers=headers)
        elapsed = time.monotonic() - t0
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:  # noqa: BLE001 -- surfaced as a recorded failure, never retried silently
        return ModelCallResult(content="", elapsed_s=time.monotonic() - t0, error=f"{type(e).__name__}: {e}")

    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content") or ""
    tool_calls = message.get("tool_calls") or []
    finish_reason = choice.get("finish_reason")
    usage = data.get("usage")
    return ModelCallResult(
        content=content, tool_calls=tool_calls, finish_reason=finish_reason,
        usage=usage, elapsed_s=elapsed, raw=data,
    )


def to_plain_messages(chat_messages: List[Any]) -> List[Dict[str, Any]]:
    """ChatMessage (pydantic) / SimpleNamespace -> plain OpenAI-shape dicts."""
    out = []
    for m in chat_messages:
        role = getattr(m, "role", None) if not isinstance(m, dict) else m.get("role")
        content = getattr(m, "content", None) if not isinstance(m, dict) else m.get("content")
        entry: Dict[str, Any] = {"role": role, "content": content}
        extra_keys = ("tool_calls", "tool_call_id", "name")
        for k in extra_keys:
            v = getattr(m, k, None) if not isinstance(m, dict) else m.get(k)
            if v is not None:
                entry[k] = v
        out.append(entry)
    return out
