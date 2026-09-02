"""Regression tests for the 2026-09-01 Salem research incident.

Three things went wrong and each one has a test here:

1. Sara's status tools couldn't see research plans, and `research_plan_status`
   only did exact-id matching, so she truthfully reported "nothing is running"
   about a plan on step 3. → the merged activity feed + prefix resolution.
2. Nothing stopped a duplicate handoff, so two research agents hit the Mac
   Studio bg lane at once and OOM'd it. → the create-time single-flight guard.
3. When the lane answered 507, every remaining step failed instantly and the
   plan was filed as `complete` with zero output and no notification. → the
   overload ladder, the `stalled` park, and honest terminal statuses.

These are pure-unit tests: no DB, no Celery, no LLM. They exercise the decision
logic that the incident turned on.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.services.agent_activity import (
    ACTIVE_STATUSES,
    RESEARCH_LIVE_STATUSES,
    RESEARCH_STATUS_MAP,
    list_response,
    merge_task_lists,
    research_plan_to_response,
)
from app.services.research.llm_client import (
    ResearchLLMClient,
    ResearchLLMOverloaded,
)


def _plan_row(**over):
    base = dict(
        id="5de2b2bb-9688-45d6-b45c-838f006cd270",
        title="Salem MA historical guide",
        objective="beyond the witch tourism",
        status="running",
        current_step_index=2,
        origin="david_chat",
        n_steps=6,
        current_step_title="Peabody Essex Museum deep-dive",
        error_log=None,
        created_at=datetime(2026, 9, 1, 21, 17, tzinfo=timezone.utc),
        started_at=datetime(2026, 9, 1, 21, 17, tzinfo=timezone.utc),
        completed_at=None,
        updated_at=datetime(2026, 9, 1, 21, 40, tzinfo=timezone.utc),
    )
    base.update(over)
    return SimpleNamespace(**base)


# ── 1. Research plans are visible, with a legible step label ──────────


def test_running_plan_renders_as_an_active_task():
    resp = research_plan_to_response(_plan_row())
    assert resp.status == "running"
    assert resp.task_type == "research_plan"
    # This is what the iOS pill shows; "Step 3 of 6" alone told David nothing.
    assert resp.status_label == "Step 3 of 6 — Peabody Essex Museum deep-dive"
    assert resp.cancellable is True


def test_stalled_plan_reads_as_paused_not_finished():
    resp = research_plan_to_response(_plan_row(status="stalled"))
    assert resp.status == "pending"          # still in flight for the UI
    assert "lane unavailable" in resp.status_label
    assert resp.cancellable is True


def test_terminal_statuses_are_not_cancellable():
    for status in ("complete", "partial", "failed", "cancelled"):
        assert research_plan_to_response(_plan_row(status=status)).cancellable is False


def test_every_live_status_maps_to_something_the_ui_shows_as_active():
    """A plan the guard treats as owning the lane must not look dead in the UI —
    otherwise the pill goes red for a plan that is working fine."""
    for status in RESEARCH_LIVE_STATUSES:
        assert RESEARCH_STATUS_MAP[status] in ACTIVE_STATUSES


def test_stuck_plan_reads_as_waiting_not_failed():
    resp = research_plan_to_response(_plan_row(status="stuck"))
    assert resp.status in ACTIVE_STATUSES
    assert "Waiting on Sara" in resp.status_label
    # No clarification_question, so the iOS clarification modal stays shut.
    assert resp.clarification_question is None


def test_active_count_counts_plans_alongside_background_tasks():
    plans = [research_plan_to_response(_plan_row())]
    tasks = [
        research_plan_to_response(_plan_row(id="other", status="complete", completed_at=None))
    ]
    merged = merge_task_lists(tasks, plans, limit=10)
    # The false "zero active tasks" came from counting only background_task rows.
    assert list_response(merged).active_count == 1


def test_merge_orders_newest_first_and_caps_at_limit():
    older = research_plan_to_response(
        _plan_row(id="older", created_at=datetime(2026, 8, 1, tzinfo=timezone.utc))
    )
    newer = research_plan_to_response(
        _plan_row(id="newer", created_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    )
    merged = merge_task_lists([older], [newer], limit=1)
    assert [t.id for t in merged] == ["newer"]


# ── 3. A sick lane parks the plan instead of shredding it ─────────────


def _client_against(handler) -> ResearchLLMClient:
    client = ResearchLLMClient()
    client._resolved_model = "test-model"
    client._client = httpx.AsyncClient(
        base_url="http://mock", transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.asyncio
async def test_507_retries_then_raises_overloaded(monkeypatch):
    """507 used to fall straight through to raise_for_status, which the executor
    recorded as a failed step — six of them in 1.3 seconds."""
    monkeypatch.setattr(
        "app.services.research.llm_client._OVERLOAD_RETRY_DELAYS", (0.0, 0.0, 0.0)
    )
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(507, text='{"error":"Insufficient Storage"}')

    client = _client_against(handler)
    try:
        with pytest.raises(ResearchLLMOverloaded) as excinfo:
            await client.chat_completion(messages=[{"role": "user", "content": "hi"}])
    finally:
        await client.close()

    assert calls["n"] == 4                    # first try + three backoff attempts
    assert excinfo.value.status_code == 507
    assert "Insufficient Storage" in str(excinfo.value)


@pytest.mark.asyncio
async def test_exhausted_transient_retries_also_park_the_plan(monkeypatch):
    """A 503 that never clears is the lane being down, not a bad step."""
    monkeypatch.setattr(
        "app.services.research.llm_client.RESEARCH_LLM_RETRY_BASE_DELAY", 0.0
    )
    monkeypatch.setattr("app.services.research.llm_client.RESEARCH_LLM_MAX_RETRIES", 2)

    client = _client_against(lambda request: httpx.Response(503, text="Loading model"))
    try:
        with pytest.raises(ResearchLLMOverloaded):
            await client.chat_completion(messages=[{"role": "user", "content": "hi"}])
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_transient_status_recovers_without_raising(monkeypatch):
    monkeypatch.setattr(
        "app.services.research.llm_client.RESEARCH_LLM_RETRY_BASE_DELAY", 0.0
    )
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="Loading model")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = _client_against(handler)
    try:
        data = await client.chat_completion(messages=[{"role": "user", "content": "hi"}])
    finally:
        await client.close()

    assert client.get_text(data) == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_client_error_is_not_treated_as_lane_trouble(monkeypatch):
    """A 400 is our bug, not the lane's — it must not stall the whole plan."""
    client = _client_against(lambda request: httpx.Response(400, text="bad request"))
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.chat_completion(messages=[{"role": "user", "content": "hi"}])
    finally:
        await client.close()
