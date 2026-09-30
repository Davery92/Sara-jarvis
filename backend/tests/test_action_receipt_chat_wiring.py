"""R03 review remediation round 4 (2026-09-27): durable, application-
controlled operation identity, atomic claim-before-mutation, and explicit
non-terminal state — replacing round 3's post-hoc, tool-call-id-keyed
`record_chat_tool_action`.

Round 3 wrote a receipt AFTER the mutation already ran, keyed only by the
model's own per-call `tool_call_id` — an id the inference server reassigns
fresh on every model turn, so it does NOT survive a client retry/reconnect
that reprocesses the SAME logical user message into a NEW model turn (a
different tool_call_id for what is semantically the same operation).
Review finding 4: "deduplicating receipt rows does not prevent duplicate
EFFECTS" — a naive post-hoc dedup only stops a second identical LOG ROW,
not a second EXECUTION of the mutation itself.

Round 4 claims a durable operation slot (keyed by the CLIENT's own
`client_message_id` — already used elsewhere in this codebase for
idempotency — plus tool name and arguments) BEFORE the mutation runs, in
`status='running'` (the plan's own vocabulary). Only the winner of that
atomic claim executes the tool; a loser relays the existing operation's
outcome (or refuses concurrently, for a still-fresh in-flight claim)
INSTEAD of re-running the mutation. `finalize_operation` records the real
outcome afterward. A claim that's never resolved (a crash) is reclaimable
after `RUNNING_CLAIM_EXPIRY_SECONDS` — the same "the next poll naturally
reconciles it" pattern used for reminder/timer delivery (R06 remainder).

Full same-transaction atomicity between a tool's OWN database write and
this receipt is still NOT implemented (each of ~40 tool files manages its
own session; a refactor of that scope was not attempted this round) — but
the pre-execution claim gate is what actually prevents a retried request
from executing the mutation twice, which is the concrete threat model
"duplicate effects" names.
"""
import json
import uuid

import pytest

from app.db.base import engine
from app.models.chat_pending_proposal import ChatPendingProposal  # noqa: F401 (table registration)
from app.services import action_receipt_service as svc


@pytest.fixture(scope="module", autouse=True)
def _provision_table():
    ChatPendingProposal.__table__.create(engine, checkfirst=True)
    yield


@pytest.fixture()
def db_session():
    from app.db.base import SessionLocal
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def user_id(db_session):
    from sqlalchemy import text
    uid = str(uuid.uuid4())
    db_session.execute(text("""
        INSERT INTO app_user (id, email, password_hash, created_at)
        VALUES (:id, :email, 'x', NOW())
    """), {"id": uid, "email": f"{uid}@test.local"})
    db_session.commit()
    yield uid
    db_session.execute(text("DELETE FROM action_receipt WHERE user_id = :id"), {"id": uid})
    db_session.execute(text("DELETE FROM app_user WHERE id = :id"), {"id": uid})
    db_session.commit()


class TestComputeOperationKey:
    def test_the_same_inputs_produce_the_same_key(self):
        k1 = svc.compute_operation_key("cmid-1", "conv-1", "reminders_cancel", {"reminder_id": "r1"})
        k2 = svc.compute_operation_key("cmid-1", "conv-1", "reminders_cancel", {"reminder_id": "r1"})
        assert k1 == k2

    def test_a_different_client_message_id_produces_a_different_key(self):
        k1 = svc.compute_operation_key("cmid-1", "conv-1", "reminders_cancel", {"reminder_id": "r1"})
        k2 = svc.compute_operation_key("cmid-2", "conv-1", "reminders_cancel", {"reminder_id": "r1"})
        assert k1 != k2

    def test_different_arguments_produce_a_different_key(self):
        k1 = svc.compute_operation_key("cmid-1", "conv-1", "reminders_cancel", {"reminder_id": "r1"})
        k2 = svc.compute_operation_key("cmid-1", "conv-1", "reminders_cancel", {"reminder_id": "r2"})
        assert k1 != k2

    def test_argument_key_order_does_not_change_the_result(self):
        k1 = svc.compute_operation_key("cmid-1", "conv-1", "t", {"a": 1, "b": 2})
        k2 = svc.compute_operation_key("cmid-1", "conv-1", "t", {"b": 2, "a": 1})
        assert k1 == k2


class TestClaimOperation:
    def test_a_fresh_claim_succeeds(self, db_session, user_id):
        key = svc.compute_operation_key("cmid-1", "conv-1", "reminders_cancel", {"reminder_id": "r1"})
        action_id = svc.claim_operation(
            db_session, user_id=user_id, conversation_id="conv-1",
            operation_key=key, tool_name="reminders_cancel", target="reminders_cancel:r1",
        )
        assert action_id is not None

    def test_a_second_claim_with_the_same_key_fails(self, db_session, user_id):
        """The actual duplicate-effect guard: a second attempt at the SAME
        logical operation must never be granted a claim — proven directly
        against the real unique-index/ON CONFLICT semantics, not a mock."""
        key = svc.compute_operation_key("cmid-1", "conv-1", "reminders_cancel", {"reminder_id": "r1"})
        first = svc.claim_operation(
            db_session, user_id=user_id, conversation_id="conv-1",
            operation_key=key, tool_name="reminders_cancel", target="reminders_cancel:r1",
        )
        second = svc.claim_operation(
            db_session, user_id=user_id, conversation_id="conv-1",
            operation_key=key, tool_name="reminders_cancel", target="reminders_cancel:r1",
        )
        assert first is not None
        assert second is None

    def test_a_fresh_claim_is_recorded_as_running_not_completed(self, db_session, user_id):
        key = svc.compute_operation_key("cmid-1", "conv-1", "reminders_cancel", {"reminder_id": "r1"})
        svc.claim_operation(
            db_session, user_id=user_id, conversation_id="conv-1",
            operation_key=key, tool_name="reminders_cancel", target="reminders_cancel:r1",
        )
        op = svc.get_operation_by_key(db_session, key)
        assert op["status"] == "running"


class TestReclaimStaleRunningOperation:
    def test_a_fresh_running_claim_is_not_reclaimable(self, db_session, user_id):
        key = svc.compute_operation_key("cmid-1", "conv-1", "t", {})
        svc.claim_operation(db_session, user_id=user_id, conversation_id="conv-1", operation_key=key, tool_name="t", target="t")
        reclaimed = svc.reclaim_stale_running_operation(db_session, key, expiry_seconds=120)
        assert reclaimed is None

    def test_an_aged_claim_is_reclaimable(self, db_session, user_id):
        from sqlalchemy import text
        key = svc.compute_operation_key("cmid-1", "conv-1", "t", {})
        action_id = svc.claim_operation(db_session, user_id=user_id, conversation_id="conv-1", operation_key=key, tool_name="t", target="t")
        db_session.execute(text(
            "UPDATE action_receipt SET executed_at = NOW() - INTERVAL '200 seconds' WHERE action_id = :id"
        ), {"id": action_id})
        db_session.commit()
        reclaimed = svc.reclaim_stale_running_operation(db_session, key, expiry_seconds=120)
        assert reclaimed == action_id


class TestFinalizeOperation:
    def test_success_transitions_to_completed(self, db_session, user_id):
        key = svc.compute_operation_key("cmid-1", "conv-1", "t", {})
        action_id = svc.claim_operation(db_session, user_id=user_id, conversation_id="conv-1", operation_key=key, tool_name="t", target="t")
        svc.finalize_operation(db_session, action_id, success=True, result_message="done")
        op = svc.get_operation_by_key(db_session, key)
        assert op["status"] == "completed"

    def test_failure_transitions_to_failed_not_completed(self, db_session, user_id):
        """'A failed write stays failed' — unchanged from round 3."""
        key = svc.compute_operation_key("cmid-1", "conv-1", "t", {})
        action_id = svc.claim_operation(db_session, user_id=user_id, conversation_id="conv-1", operation_key=key, tool_name="t", target="t")
        svc.finalize_operation(db_session, action_id, success=False, result_message="boom")
        op = svc.get_operation_by_key(db_session, key)
        assert op["status"] == "failed"

    def test_finalizing_twice_is_a_safe_no_op_the_second_time(self, db_session, user_id):
        key = svc.compute_operation_key("cmid-1", "conv-1", "t", {})
        action_id = svc.claim_operation(db_session, user_id=user_id, conversation_id="conv-1", operation_key=key, tool_name="t", target="t")
        svc.finalize_operation(db_session, action_id, success=True, result_message="first")
        svc.finalize_operation(db_session, action_id, success=False, result_message="second, should not apply")
        op = svc.get_operation_by_key(db_session, key)
        assert op["status"] == "completed"  # unchanged — the WHERE status='running' guard prevented the second write


class TestExecuteToolWiring:
    """End-to-end via the actual execute_tool call site."""

    @pytest.mark.asyncio
    async def test_an_executed_mutating_tool_gets_a_completed_operation_receipt(self, monkeypatch, user_id):
        from app import main_simple as ms
        from app.tools.base import ToolResult

        client = ms.SimpleLLMClient()

        async def _noop(*a, **kw):
            return None
        client.emit_event = _noop
        client.emit_activity = _noop

        client._active_tools = [{"type": "function", "function": {"name": "reminders_cancel"}}]
        client._turn_message_for_mutation_gate = "Cancel my dentist reminder."
        client._last_turn_mutating_tools_for_boundary = []
        client._current_client_message_id = f"cmid-{uuid.uuid4()}"

        conv_id = f"conv-{uuid.uuid4()}"

        async def _fake_execute(name, user_id, parameters, context=None):
            return ToolResult(success=True, message="Cancelled.", data={"reminder_id": "r1"})
        monkeypatch.setattr(ms.tool_registry, "execute_tool", _fake_execute)
        monkeypatch.setattr(ms.tool_registry, "get_tool", lambda name: object())

        tc = {"id": f"call-{uuid.uuid4()}", "function": {"name": "reminders_cancel", "arguments": '{"reminder_id": "r1"}'}}
        result = await client.execute_tool(tc, user_id=user_id, conversation_id=conv_id)
        assert json.loads(result["content"])["success"] is True

        from app.db.base import SessionLocal
        db = SessionLocal()
        try:
            receipts = svc.find_receipts(db, user_id=user_id, conversation_id=conv_id)
        finally:
            db.close()
        assert len(receipts) == 1
        assert receipts[0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_a_retried_client_message_does_not_re_execute_the_mutation(self, monkeypatch, user_id):
        """The core round-4 fix: a SECOND tool call carrying the SAME
        client_message_id + tool + arguments (a client retry/reconnect
        that reprocessed the same user message into a fresh model turn,
        with a brand-new tool_call_id) must NOT re-execute the mutation —
        the registry must be called at most once."""
        from app import main_simple as ms
        from app.tools.base import ToolResult

        client = ms.SimpleLLMClient()

        async def _noop(*a, **kw):
            return None
        client.emit_event = _noop
        client.emit_activity = _noop

        client._active_tools = [{"type": "function", "function": {"name": "reminders_cancel"}}]
        client._turn_message_for_mutation_gate = "Cancel my dentist reminder."
        client._last_turn_mutating_tools_for_boundary = []
        shared_cmid = f"cmid-{uuid.uuid4()}"
        client._current_client_message_id = shared_cmid

        conv_id = f"conv-{uuid.uuid4()}"
        call_count = {"n": 0}

        async def _fake_execute(name, user_id, parameters, context=None):
            call_count["n"] += 1
            return ToolResult(success=True, message="Cancelled.", data={"reminder_id": "r1"})
        monkeypatch.setattr(ms.tool_registry, "execute_tool", _fake_execute)
        monkeypatch.setattr(ms.tool_registry, "get_tool", lambda name: object())

        tc1 = {"id": f"call-{uuid.uuid4()}", "function": {"name": "reminders_cancel", "arguments": '{"reminder_id": "r1"}'}}
        result1 = await client.execute_tool(tc1, user_id=user_id, conversation_id=conv_id)
        assert json.loads(result1["content"])["success"] is True
        assert call_count["n"] == 1

        # A fresh model turn, DIFFERENT tool_call_id, SAME client_message_id
        # (the client retried/reconnected) and identical arguments.
        client._current_client_message_id = shared_cmid
        tc2 = {"id": f"call-{uuid.uuid4()}", "function": {"name": "reminders_cancel", "arguments": '{"reminder_id": "r1"}'}}
        result2 = await client.execute_tool(tc2, user_id=user_id, conversation_id=conv_id)
        payload2 = json.loads(result2["content"])

        assert call_count["n"] == 1  # NOT re-executed
        assert "already" in payload2["message"].lower()

    @pytest.mark.asyncio
    async def test_a_refused_call_produces_no_operation_receipt(self, monkeypatch, user_id):
        """R01's execution-boundary gate refuses a mutating call with no
        action evidence BEFORE it ever reaches the claim step — a
        zero-call outcome genuinely cannot be presented as executed."""
        from app import main_simple as ms

        client = ms.SimpleLLMClient()

        async def _noop(*a, **kw):
            return None
        client.emit_event = _noop
        client.emit_activity = _noop

        client._active_tools = [{"type": "function", "function": {"name": "reminders_cancel"}}]
        client._turn_message_for_mutation_gate = "Good morning Sara"
        client._last_turn_mutating_tools_for_boundary = []
        client._current_client_message_id = f"cmid-{uuid.uuid4()}"

        conv_id = f"conv-{uuid.uuid4()}"

        async def _must_not_run(*a, **kw):
            raise AssertionError("should not reach the registry")
        monkeypatch.setattr(ms.tool_registry, "execute_tool", _must_not_run)

        tc = {"id": f"call-{uuid.uuid4()}", "function": {"name": "reminders_cancel", "arguments": "{}"}}
        result = await client.execute_tool(tc, user_id=user_id, conversation_id=conv_id)
        assert json.loads(result["content"])["success"] is False

        from app.db.base import SessionLocal
        db = SessionLocal()
        try:
            receipts = svc.find_receipts(db, user_id=user_id, conversation_id=conv_id)
        finally:
            db.close()
        assert receipts == []

    @pytest.mark.asyncio
    async def test_a_read_only_tool_produces_no_operation_receipt(self, monkeypatch, user_id):
        from app import main_simple as ms
        from app.tools.base import ToolResult

        client = ms.SimpleLLMClient()

        async def _noop(*a, **kw):
            return None
        client.emit_event = _noop
        client.emit_activity = _noop

        client._active_tools = [{"type": "function", "function": {"name": "reminders_list"}}]
        client._turn_message_for_mutation_gate = "What are my reminders?"
        client._last_turn_mutating_tools_for_boundary = []
        client._current_client_message_id = f"cmid-{uuid.uuid4()}"

        conv_id = f"conv-{uuid.uuid4()}"

        async def _fake_execute(name, user_id, parameters, context=None):
            return ToolResult(success=True, message="ok", data={"reminders": []})
        monkeypatch.setattr(ms.tool_registry, "execute_tool", _fake_execute)
        monkeypatch.setattr(ms.tool_registry, "get_tool", lambda name: object())

        tc = {"id": f"call-{uuid.uuid4()}", "function": {"name": "reminders_list", "arguments": "{}"}}
        await client.execute_tool(tc, user_id=user_id, conversation_id=conv_id)

        from app.db.base import SessionLocal
        db = SessionLocal()
        try:
            receipts = svc.find_receipts(db, user_id=user_id, conversation_id=conv_id)
        finally:
            db.close()
        assert receipts == []

    @pytest.mark.asyncio
    async def test_a_failed_tool_call_finalizes_to_failed(self, monkeypatch, user_id):
        from app import main_simple as ms
        from app.tools.base import ToolResult

        client = ms.SimpleLLMClient()

        async def _noop(*a, **kw):
            return None
        client.emit_event = _noop
        client.emit_activity = _noop

        client._active_tools = [{"type": "function", "function": {"name": "reminders_cancel"}}]
        client._turn_message_for_mutation_gate = "Cancel my dentist reminder."
        client._last_turn_mutating_tools_for_boundary = []
        client._current_client_message_id = f"cmid-{uuid.uuid4()}"

        conv_id = f"conv-{uuid.uuid4()}"

        async def _fake_execute(name, user_id, parameters, context=None):
            return ToolResult(success=False, message="Reminder not found.")
        monkeypatch.setattr(ms.tool_registry, "execute_tool", _fake_execute)
        monkeypatch.setattr(ms.tool_registry, "get_tool", lambda name: object())

        tc = {"id": f"call-{uuid.uuid4()}", "function": {"name": "reminders_cancel", "arguments": '{"reminder_id": "does-not-exist"}'}}
        result = await client.execute_tool(tc, user_id=user_id, conversation_id=conv_id)
        assert json.loads(result["content"])["success"] is False

        from app.db.base import SessionLocal
        db = SessionLocal()
        try:
            receipts = svc.find_receipts(db, user_id=user_id, conversation_id=conv_id)
        finally:
            db.close()
        assert len(receipts) == 1
        assert receipts[0]["status"] == "failed"


class TestVerifyActionReportsRunningStateHonestly:
    @pytest.mark.asyncio
    async def test_a_stuck_running_operation_is_not_reported_as_completed(self, db_session, user_id):
        from app.tools.action_verification import VerifyActionTool

        conv = f"conv-{uuid.uuid4()}"
        key = svc.compute_operation_key("cmid-x", conv, "reminders_cancel", {"reminder_id": "dentist-1"})
        svc.claim_operation(
            db_session, user_id=user_id, conversation_id=conv,
            operation_key=key, tool_name="reminders_cancel", target="reminders_cancel:dentist-1",
        )
        tool = VerifyActionTool()
        result = await tool.execute(user_id, _conversation_id=conv, query="dentist")
        assert result.success is True
        assert len(result.data["receipts"]) == 1
        assert result.data["receipts"][0]["status"] == "running"
        assert "running" in result.message.lower()
