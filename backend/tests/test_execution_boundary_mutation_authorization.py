"""Execution-boundary MUTATION authorization (Sara repair plan R01,
SARA_REPAIR_PLAN_2026_09_25.md / evidence
J11_trial1_TURN3_UNAUTHORIZED_STANDING_ORDER_FROM_HYPOTHETICAL).

Reproduces the confirmed mechanism directly: three different code paths put
tool schemas into `SimpleLLMClient._active_tools` for a turn (the retrieval +
`gate_mutating_tools` path, a "work mode" category path, and a legacy
category-classifier fallback used when PRESENCE_TOOL_DIET is off), and only
the first of them ever checks the human's message for action evidence before
adding a MUTATING tool. `execute_tool`'s pre-existing check only asked
whether a name was in `_active_tools` at all ("offered-menu checking") — it
never asked whether anything in the turn's own message authorized a mutation,
so a tool that reached `_active_tools` via an ungated path executed
unconditionally.

Turn 3 of J11: "I'm thinking about turning on the porch light when I get
back." — explicitly hypothetical/musing, `has_action_intent` on this exact
string is False (verified directly) — and yet a real, persistent
`standing_order` was created and never asked about again. This test
reproduces that shape directly against `execute_tool` (with `_active_tools`
seeded exactly like the ungated legacy/work-mode/fast-worker paths do — no
`gate_mutating_tools` call in between) and proves the new execution-boundary
check refuses it before the registry tool ever runs.
"""

import json

import pytest

from app import main_simple as ms
from app.tools.base import ToolResult

J11_HYPOTHETICAL_MESSAGE = "I'm thinking about turning on the porch light when I get back."


def make_client():
    client = ms.SimpleLLMClient()

    async def _noop(*a, **kw):
        return None

    client.emit_event = _noop
    client.emit_activity = _noop
    return client


def _tool_call(name, call_id="c1", args="{}"):
    return {"id": call_id, "function": {"name": name, "arguments": args}}


class TestMutationExecutionBoundary:
    @pytest.mark.asyncio
    async def test_hypothetical_message_refuses_standing_order_create_even_when_offered(
        self, monkeypatch,
    ):
        """The J11 repro: tool present in `_active_tools` (simulating an
        ungated selection path), turn message carries no action evidence.
        Must refuse WITHOUT ever reaching the registry — proven by making
        the registry call raise if invoked at all."""
        client = make_client()
        client._active_tools = [{"type": "function", "function": {"name": "standing_order_create"}}]
        client._turn_message_for_mutation_gate = J11_HYPOTHETICAL_MESSAGE
        client._last_turn_mutating_tools_for_boundary = []

        async def _must_not_run(*a, **kw):
            raise AssertionError("standing_order_create reached the registry — authorization boundary did not hold")

        monkeypatch.setattr(ms.tool_registry, "execute_tool", _must_not_run)

        result = await client.execute_tool(_tool_call("standing_order_create"), user_id="user-a")
        payload = json.loads(result["content"])
        assert payload["success"] is False
        assert "did not run" in payload["message"].lower()

    @pytest.mark.asyncio
    async def test_explicit_request_still_executes(self, monkeypatch):
        """The fix must not become a blanket write-freeze: a message that
        genuinely evidences the request still reaches the registry."""
        client = make_client()
        client._active_tools = [{"type": "function", "function": {"name": "standing_order_create"}}]
        client._turn_message_for_mutation_gate = (
            "Create a standing order to turn on the porch light every time I arrive home."
        )
        client._last_turn_mutating_tools_for_boundary = []

        called = {}

        async def _fake_execute(name, user_id, parameters, context=None):
            called["name"] = name
            return ToolResult(success=True, message="ok", data={"id": 1})

        monkeypatch.setattr(ms.tool_registry, "execute_tool", _fake_execute)

        result = await client.execute_tool(_tool_call("standing_order_create"), user_id="user-a")
        payload = json.loads(result["content"])
        assert called.get("name") == "standing_order_create"
        assert payload["success"] is True

    @pytest.mark.asyncio
    async def test_scoped_continuation_still_executes(self, monkeypatch):
        """A short confirmation ("yes") after THIS session actually ran the
        same mutating tool last turn must still be honored — the boundary
        check must not regress the legitimate continuation path."""
        client = make_client()
        client._active_tools = [{"type": "function", "function": {"name": "standing_order_create"}}]
        client._turn_message_for_mutation_gate = "yes"
        client._last_turn_mutating_tools_for_boundary = ["standing_order_create"]

        async def _fake_execute(name, user_id, parameters, context=None):
            return ToolResult(success=True, message="ok", data={"id": 1})

        monkeypatch.setattr(ms.tool_registry, "execute_tool", _fake_execute)

        result = await client.execute_tool(_tool_call("standing_order_create"), user_id="user-a")
        payload = json.loads(result["content"])
        assert payload["success"] is True

    @pytest.mark.asyncio
    async def test_unrelated_later_message_does_not_ride_on_a_stale_continuation(self, monkeypatch):
        """A generic later message must not benefit from a recent write,
        however recent — only a message that reads as confirming/continuing
        that SPECIFIC action does."""
        client = make_client()
        client._active_tools = [{"type": "function", "function": {"name": "standing_order_create"}}]
        client._turn_message_for_mutation_gate = "okay what else is going on today"
        client._last_turn_mutating_tools_for_boundary = ["standing_order_create"]

        async def _must_not_run(*a, **kw):
            raise AssertionError("standing_order_create reached the registry on an unrelated message")

        monkeypatch.setattr(ms.tool_registry, "execute_tool", _must_not_run)

        result = await client.execute_tool(_tool_call("standing_order_create"), user_id="user-a")
        payload = json.loads(result["content"])
        assert payload["success"] is False

    @pytest.mark.asyncio
    async def test_read_only_tool_is_unaffected_by_hypothetical_phrasing(self, monkeypatch):
        """The boundary check only constrains MUTATING tools — a read tool
        offered this turn still runs regardless of message phrasing."""
        client = make_client()
        client._active_tools = [{"type": "function", "function": {"name": "standing_order_list"}}]
        client._turn_message_for_mutation_gate = J11_HYPOTHETICAL_MESSAGE
        client._last_turn_mutating_tools_for_boundary = []

        async def _fake_execute(name, user_id, parameters, context=None):
            return ToolResult(success=True, message="ok", data=[])

        monkeypatch.setattr(ms.tool_registry, "execute_tool", _fake_execute)

        result = await client.execute_tool(_tool_call("standing_order_list"), user_id="user-a")
        payload = json.loads(result["content"])
        assert payload["success"] is True

    @pytest.mark.asyncio
    async def test_always_allowed_exception_bypasses_the_message_check(self, monkeypatch):
        client = make_client()
        client._active_tools = [{"type": "function", "function": {"name": "acknowledge_notifications"}}]
        client._turn_message_for_mutation_gate = "hi"
        client._last_turn_mutating_tools_for_boundary = []

        async def _fake_execute(name, user_id, parameters, context=None):
            return ToolResult(success=True, message="ok", data=None)

        monkeypatch.setattr(ms.tool_registry, "execute_tool", _fake_execute)

        result = await client.execute_tool(_tool_call("acknowledge_notifications"), user_id="user-a")
        payload = json.loads(result["content"])
        assert payload["success"] is True

    @pytest.mark.asyncio
    async def test_ungated_fast_worker_style_seeding_is_covered(self, monkeypatch):
        """Simulates the pi_dashboard_voice_fast fast-worker path (never
        calls gate_mutating_tools at all — tools come straight from category
        lookup): with the turn message set the same way that call site now
        sets it, a hypothetical message must still be refused."""
        client = make_client()
        client._active_tools = [{"type": "function", "function": {"name": "standing_order_create"}}]
        # Mirrors the fix at the pi_dashboard_voice_fast call site.
        client._turn_message_for_mutation_gate = J11_HYPOTHETICAL_MESSAGE
        client._last_turn_mutating_tools_for_boundary = []

        async def _must_not_run(*a, **kw):
            raise AssertionError("reached the registry from a simulated ungated fast-worker path")

        monkeypatch.setattr(ms.tool_registry, "execute_tool", _must_not_run)

        result = await client.execute_tool(_tool_call("standing_order_create"), user_id="user-a")
        payload = json.loads(result["content"])
        assert payload["success"] is False


class TestRecurringScopeAuthorization:
    """R01 review remediation: real, one-time action intent must not be
    enough on its own to authorize standing_order_create — only
    has_action_intent was checked before, and "turn the porch light on
    now" genuinely evidences a one-time action without evidencing anything
    recurring."""

    @pytest.mark.asyncio
    async def test_real_one_time_action_intent_is_not_enough_for_a_standing_order(self, monkeypatch):
        client = make_client()
        client._active_tools = [{"type": "function", "function": {"name": "standing_order_create"}}]
        # Real action intent ("set") — NOT hypothetical, unlike J11 — but
        # no recurring/standing language at all.
        client._turn_message_for_mutation_gate = "Set the porch light on when I get home tonight."
        client._last_turn_mutating_tools_for_boundary = []

        async def _must_not_run(*a, **kw):
            raise AssertionError("standing_order_create reached the registry from a one-time request")

        monkeypatch.setattr(ms.tool_registry, "execute_tool", _must_not_run)

        result = await client.execute_tool(_tool_call("standing_order_create"), user_id="user-a")
        payload = json.loads(result["content"])
        assert payload["success"] is False
        assert "recurring" in payload["message"].lower() or "one-time" in payload["message"].lower()

    @pytest.mark.asyncio
    async def test_recurring_language_authorizes_the_standing_order(self, monkeypatch):
        client = make_client()
        client._active_tools = [{"type": "function", "function": {"name": "standing_order_create"}}]
        client._turn_message_for_mutation_gate = "Set the porch light on every time I get home."
        client._last_turn_mutating_tools_for_boundary = []

        async def _fake_execute(name, user_id, parameters, context=None):
            return ToolResult(success=True, message="ok", data={"id": 1})

        monkeypatch.setattr(ms.tool_registry, "execute_tool", _fake_execute)

        result = await client.execute_tool(_tool_call("standing_order_create"), user_id="user-a")
        payload = json.loads(result["content"])
        assert payload["success"] is True

    @pytest.mark.asyncio
    async def test_a_one_time_home_control_tool_is_unaffected_by_the_recurring_check(self, monkeypatch):
        """The recurring-scope requirement is scoped ONLY to
        standing-order-establishing tools — an ordinary one-time
        home-control action with real action intent must still work."""
        client = make_client()
        client._active_tools = [{"type": "function", "function": {"name": "home_light_control"}}]
        client._turn_message_for_mutation_gate = "Set the porch light on now."
        client._last_turn_mutating_tools_for_boundary = []

        async def _fake_execute(name, user_id, parameters, context=None):
            return ToolResult(success=True, message="ok", data=None)

        monkeypatch.setattr(ms.tool_registry, "execute_tool", _fake_execute)

        result = await client.execute_tool(_tool_call("home_light_control"), user_id="user-a")
        payload = json.loads(result["content"])
        assert payload["success"] is True

    @pytest.mark.asyncio
    async def test_a_confirmation_continuation_is_not_re_blocked_for_missing_recurring_language(self, monkeypatch):
        """A bare "yes" confirming a standing-order proposal from an
        earlier turn (already established as recurring in THAT turn) must
        not be refused here just because "yes" itself carries no recurring
        language — the recurring-scope check only applies on the direct
        action-intent path, not the continuation path."""
        client = make_client()
        client._active_tools = [{"type": "function", "function": {"name": "standing_order_create"}}]
        client._turn_message_for_mutation_gate = "yes"
        client._last_turn_mutating_tools_for_boundary = ["standing_order_create"]

        async def _fake_execute(name, user_id, parameters, context=None):
            return ToolResult(success=True, message="ok", data={"id": 1})

        monkeypatch.setattr(ms.tool_registry, "execute_tool", _fake_execute)

        result = await client.execute_tool(_tool_call("standing_order_create"), user_id="user-a")
        payload = json.loads(result["content"])
        assert payload["success"] is True
