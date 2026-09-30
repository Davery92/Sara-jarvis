"""Regression tests for long-running internal-agent model calls."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services import internal_tool_agent as module


def _bare_agent():
    agent = module.InternalToolAgent.__new__(module.InternalToolAgent)
    agent._execution_log = []
    agent._progress_callback = None
    return agent


def test_empty_httpx_timeout_error_keeps_type_and_duration(monkeypatch) -> None:
    monkeypatch.setattr(module, "INTERNAL_AGENT_LLM_TIMEOUT_SECONDS", 1800.0)
    assert module._format_llm_error(httpx.ReadTimeout("")) == "ReadTimeout after 1800s"


@pytest.mark.asyncio
async def test_model_wait_emits_progress_heartbeats(monkeypatch) -> None:
    monkeypatch.setattr(module, "INTERNAL_AGENT_HEARTBEAT_SECONDS", 0.01)
    progress = []
    agent = _bare_agent()

    async def record(message: str) -> None:
        progress.append(message)

    async def slow_call(*args, **kwargs) -> dict:
        await asyncio.sleep(0.025)
        return {"content": "done"}

    agent._progress_callback = record
    agent._call_llm = slow_call

    result = await agent._call_llm_with_heartbeat([], iteration=2)

    assert result == {"content": "done"}
    assert progress
    assert "iteration 3" in progress[0]


@pytest.mark.asyncio
async def test_run_loop_persists_typed_timeout_error(monkeypatch) -> None:
    monkeypatch.setattr(module, "INTERNAL_AGENT_LLM_TIMEOUT_SECONDS", 1800.0)
    agent = _bare_agent()
    agent.max_iterations = 25
    agent._build_fallback_summary = lambda results: ""

    async def timeout(*args, **kwargs) -> dict:
        raise httpx.ReadTimeout("")

    agent._call_llm_with_heartbeat = timeout
    result = await agent._run_loop([
        {"role": "system", "content": "system"},
        {"role": "user", "content": "research this"},
    ])

    assert result["status"] == "failed"
    assert result["error"] == (
        "Internal agent LLM call failed: ReadTimeout after 1800s"
    )
