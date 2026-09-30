"""Pending-proposal state for the chat mutation gate (Sara repair plan R01
review remediation — round 1, 2026-09-25: "Represent pending proposals
separately from completed actions"; round 2, 2026-09-26: "Verify pending
proposals against what the user actually saw"). See
app/models/chat_pending_proposal.py and app/services/chat_proposal_service.py
for the full rationale.

Round 2 correction: `propose()` now REQUIRES `presented_summary` — Sara's
own finalized reply text for the turn — and `execute_tool` no longer calls
it directly. A refusal only STASHES a candidate in
`self._turn_unpresented_proposals`; the actual persist happens through
`SimpleLLMClient._finalize_turn_proposals(response_content)` (normally
called from `_store_conversation_with_timeout`, after the real reply text
is known). Tests that exercise the full refuse-then-confirm flow now call
`_finalize_turn_proposals` explicitly between the two `execute_tool` calls
to simulate "the turn's reply has been finalized" — anything the model's
own visible reply would plausibly have said about the proposed action.

`chat_pending_proposal` is a NEW table (alembic revision
155_chat_pending_proposal, not applied to any running database as part of
this repair session) — self-provisioned here against the real disposable
Postgres, matching this codebase's convention for in-flight schema
additions not yet in the checked-in schema fixture.
"""
import json
import uuid

import pytest

from app.db.base import engine
from app.models.chat_pending_proposal import ChatPendingProposal
from app.services import chat_proposal_service as svc

# A real, substantive reply mentioning standing-order language — passes
# both MIN_PRESENTED_SUMMARY_CHARS and (where checked) the domain-
# consistency check against standing_order_create's own domain.
STANDING_ORDER_SUMMARY = "I can set that up as a standing order for the porch light — want me to go ahead?"
UNRELATED_SUMMARY = "Sure, here's what's on your calendar for tomorrow afternoon."
STANDING_ORDER_ARGS = json.dumps({"trigger_type": "presence", "action_type": "home_control", "entity_id": "light.porch"})


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
    """A real app_user row — chat_pending_proposal.user_id has an FK to it."""
    from sqlalchemy import text
    uid = str(uuid.uuid4())
    db_session.execute(text("""
        INSERT INTO app_user (id, email, password_hash, created_at)
        VALUES (:id, :email, 'x', NOW())
    """), {"id": uid, "email": f"{uid}@test.local"})
    db_session.commit()
    yield uid
    db_session.execute(text("DELETE FROM chat_pending_proposal WHERE user_id = :id"), {"id": uid})
    db_session.execute(text("DELETE FROM app_user WHERE id = :id"), {"id": uid})
    db_session.commit()


class TestProposeRequiresPresentedSummary:
    def test_propose_without_presented_summary_is_rejected(self, db_session, user_id):
        ok = svc.propose(
            db_session, user_id=user_id, conversation_id="conv-1",
            tool_name="standing_order_create", arguments_json="{}",
            presented_summary="",
        )
        assert ok is False
        result = svc.consume(db_session, user_id=user_id, conversation_id="conv-1", tool_name="standing_order_create")
        assert result is None

    def test_propose_with_a_too_short_presented_summary_is_rejected(self, db_session, user_id):
        ok = svc.propose(
            db_session, user_id=user_id, conversation_id="conv-1",
            tool_name="standing_order_create", arguments_json="{}",
            presented_summary="Sure.",
        )
        assert ok is False

    def test_propose_with_a_substantive_presented_summary_succeeds(self, db_session, user_id):
        ok = svc.propose(
            db_session, user_id=user_id, conversation_id="conv-1",
            tool_name="standing_order_create", arguments_json="{}",
            presented_summary=STANDING_ORDER_SUMMARY,
        )
        assert ok is True


class TestProposeAndConsume:
    def test_a_proposed_call_can_be_consumed_once(self, db_session, user_id):
        svc.propose(
            db_session, user_id=user_id, conversation_id="conv-1",
            tool_name="standing_order_create", arguments_json=json.dumps({"a": 1}),
            presented_summary=STANDING_ORDER_SUMMARY, summary="test",
        )
        result = svc.consume(db_session, user_id=user_id, conversation_id="conv-1", tool_name="standing_order_create")
        assert result.arguments_json == json.dumps({"a": 1})
        assert result.presented_summary == STANDING_ORDER_SUMMARY

    def test_consuming_twice_only_succeeds_once(self, db_session, user_id):
        svc.propose(
            db_session, user_id=user_id, conversation_id="conv-1",
            tool_name="standing_order_create", arguments_json="{}",
            presented_summary=STANDING_ORDER_SUMMARY,
        )
        first = svc.consume(db_session, user_id=user_id, conversation_id="conv-1", tool_name="standing_order_create")
        second = svc.consume(db_session, user_id=user_id, conversation_id="conv-1", tool_name="standing_order_create")
        assert first is not None
        assert second is None

    def test_a_new_proposal_supersedes_the_old_one(self, db_session, user_id):
        """Only one live proposal per conversation at a time — a bare
        'yes' later has no ambiguity about which proposal it confirms."""
        svc.propose(
            db_session, user_id=user_id, conversation_id="conv-1",
            tool_name="standing_order_create", arguments_json=json.dumps({"old": True}),
            presented_summary=STANDING_ORDER_SUMMARY,
        )
        svc.propose(
            db_session, user_id=user_id, conversation_id="conv-1",
            tool_name="standing_order_create", arguments_json=json.dumps({"new": True}),
            presented_summary=STANDING_ORDER_SUMMARY,
        )
        result = svc.consume(db_session, user_id=user_id, conversation_id="conv-1", tool_name="standing_order_create")
        assert result.arguments_json == json.dumps({"new": True})

    def test_wrong_tool_name_does_not_consume_a_different_proposal(self, db_session, user_id):
        svc.propose(
            db_session, user_id=user_id, conversation_id="conv-1",
            tool_name="standing_order_create", arguments_json="{}",
            presented_summary=STANDING_ORDER_SUMMARY,
        )
        result = svc.consume(db_session, user_id=user_id, conversation_id="conv-1", tool_name="notes_delete")
        assert result is None

    def test_a_different_conversation_cannot_consume_it(self, db_session, user_id):
        svc.propose(
            db_session, user_id=user_id, conversation_id="conv-1",
            tool_name="standing_order_create", arguments_json="{}",
            presented_summary=STANDING_ORDER_SUMMARY,
        )
        result = svc.consume(db_session, user_id=user_id, conversation_id="conv-2", tool_name="standing_order_create")
        assert result is None

    def test_a_different_user_cannot_consume_it(self, db_session, user_id):
        svc.propose(
            db_session, user_id=user_id, conversation_id="conv-1",
            tool_name="standing_order_create", arguments_json="{}",
            presented_summary=STANDING_ORDER_SUMMARY,
        )
        result = svc.consume(db_session, user_id="some-other-user", conversation_id="conv-1", tool_name="standing_order_create")
        assert result is None

    def test_an_expired_proposal_cannot_be_consumed(self, db_session, user_id):
        svc.propose(
            db_session, user_id=user_id, conversation_id="conv-1",
            tool_name="standing_order_create", arguments_json="{}",
            presented_summary=STANDING_ORDER_SUMMARY, ttl_seconds=-10,
        )
        result = svc.consume(db_session, user_id=user_id, conversation_id="conv-1", tool_name="standing_order_create")
        assert result is None

    def test_no_proposal_at_all_returns_none(self, db_session, user_id):
        result = svc.consume(db_session, user_id=user_id, conversation_id="conv-never-proposed", tool_name="standing_order_create")
        assert result is None


class TestExecuteToolStashesAndFinalizes:
    """End-to-end: execute_tool refuses an unevidenced call and STASHES a
    candidate proposal (not yet persisted); _finalize_turn_proposals
    persists it once the turn's real reply text is known; a later scoped
    confirmation consumes it and re-executes with the ORIGINALLY proposed
    arguments — not whatever the model passes on the confirming turn."""

    @pytest.mark.asyncio
    async def test_refusal_then_confirmation_reexecutes_the_original_arguments(self, monkeypatch, user_id):
        """Positive case: the ORIGINAL message lacked direct action intent
        (so standing_order_create was refused and proposed) but DID carry
        recurring-scope language ("every night") — a later bare "yes"
        should consume the proposal and execute the originally-proposed
        arguments, regardless of whatever (possibly different) arguments
        the model reconstructs on the confirming turn."""
        from app import main_simple as ms
        from app.tools.base import ToolResult

        client = ms.SimpleLLMClient()

        async def _noop(*a, **kw):
            return None
        client.emit_event = _noop
        client.emit_activity = _noop

        client._active_tools = [{"type": "function", "function": {"name": "standing_order_create"}}]
        client._turn_message_for_mutation_gate = "Every night before I go to bed, I was wondering about the porch light."
        client._last_turn_mutating_tools_for_boundary = []

        conv_id = f"conv-{uuid.uuid4()}"
        original_args = '{"trigger_type": "presence", "action_type": "home_control", "entity_id": "light.porch"}'

        async def _must_not_run(*a, **kw):
            raise AssertionError("should not reach the registry on the exploratory turn")
        monkeypatch.setattr(ms.tool_registry, "execute_tool", _must_not_run)

        tc1 = {"id": "c1", "function": {"name": "standing_order_create", "arguments": original_args}}
        result1 = await client.execute_tool(tc1, user_id=user_id, conversation_id=conv_id)
        payload1 = json.loads(result1["content"])
        assert payload1["success"] is False

        # Nothing is in the DB yet — only stashed in memory.
        from app.db.base import SessionLocal
        _check_session = SessionLocal()
        try:
            pre_finalize = svc.consume(
                _check_session, user_id=user_id, conversation_id=conv_id,
                tool_name="standing_order_create",
            )
        finally:
            _check_session.close()
        assert pre_finalize is None

        # Simulate the turn's reply being finalized with real, substantive
        # content that actually concerns the proposed standing order.
        client._finalize_turn_proposals(STANDING_ORDER_SUMMARY)

        # Next turn: David confirms. The model might reconstruct DIFFERENT
        # (even wrong) arguments this time — that must not matter; the
        # ORIGINALLY proposed ones are what actually execute.
        client._turn_message_for_mutation_gate = "yes"
        client._last_turn_mutating_tools_for_boundary = []

        captured = {}

        async def _fake_execute(name, user_id, parameters, context=None):
            captured["parameters"] = parameters
            return ToolResult(success=True, message="ok", data={"id": 1})

        monkeypatch.setattr(ms.tool_registry, "execute_tool", _fake_execute)

        tc2 = {"id": "c2", "function": {"name": "standing_order_create", "arguments": '{"totally": "different"}'}}
        result2 = await client.execute_tool(tc2, user_id=user_id, conversation_id=conv_id)
        payload2 = json.loads(result2["content"])

        assert payload2["success"] is True
        assert captured["parameters"] == json.loads(original_args)

    @pytest.mark.asyncio
    async def test_no_finalize_means_no_persisted_proposal_to_confirm(self, monkeypatch, user_id):
        """If the turn never reaches finalization (e.g. the process died,
        or a caller forgot to call it), the refused call must NOT become
        confirmable later — there is no evidence the user was ever told.
        Regression test for the exact round-1 gap: propose() used to run
        synchronously inside execute_tool, before any reply text existed
        at all."""
        from app import main_simple as ms

        client = ms.SimpleLLMClient()

        async def _noop(*a, **kw):
            return None
        client.emit_event = _noop
        client.emit_activity = _noop

        client._active_tools = [{"type": "function", "function": {"name": "standing_order_create"}}]
        client._turn_message_for_mutation_gate = "Every night before I go to bed, I was wondering about the porch light."
        client._last_turn_mutating_tools_for_boundary = []

        conv_id = f"conv-{uuid.uuid4()}"

        async def _must_not_run(*a, **kw):
            raise AssertionError("should not reach the registry")
        monkeypatch.setattr(ms.tool_registry, "execute_tool", _must_not_run)

        tc1 = {"id": "c1", "function": {"name": "standing_order_create", "arguments": "{}"}}
        result1 = await client.execute_tool(tc1, user_id=user_id, conversation_id=conv_id)
        assert json.loads(result1["content"])["success"] is False
        # _finalize_turn_proposals deliberately NOT called.

        client._turn_message_for_mutation_gate = "yes"
        client._last_turn_mutating_tools_for_boundary = []

        tc2 = {"id": "c2", "function": {"name": "standing_order_create", "arguments": "{}"}}
        result2 = await client.execute_tool(tc2, user_id=user_id, conversation_id=conv_id)
        payload2 = json.loads(result2["content"])
        assert payload2["success"] is False

    @pytest.mark.asyncio
    async def test_a_presented_summary_unrelated_to_the_tool_domain_does_not_authorize(self, monkeypatch, user_id):
        """Round 2 domain-consistency check: a proposal row existing (and
        having a substantive presented_summary) is not enough — the reply
        that was actually shown must concern THIS tool's domain. A refusal
        whose accompanying reply talked about something else entirely
        (e.g. a swallowed exception led to an unrelated fallback answer)
        must not become confirmable."""
        from app import main_simple as ms

        client = ms.SimpleLLMClient()

        async def _noop(*a, **kw):
            return None
        client.emit_event = _noop
        client.emit_activity = _noop

        client._active_tools = [{"type": "function", "function": {"name": "standing_order_create"}}]
        client._turn_message_for_mutation_gate = "Every night before I go to bed, I was wondering about the porch light."
        client._last_turn_mutating_tools_for_boundary = []

        conv_id = f"conv-{uuid.uuid4()}"

        async def _must_not_run(*a, **kw):
            raise AssertionError("should not reach the registry")
        monkeypatch.setattr(ms.tool_registry, "execute_tool", _must_not_run)

        tc1 = {"id": "c1", "function": {"name": "standing_order_create", "arguments": "{}"}}
        result1 = await client.execute_tool(tc1, user_id=user_id, conversation_id=conv_id)
        assert json.loads(result1["content"])["success"] is False

        # Finalize with a reply that never actually mentions the standing
        # order / automation / recurring domain at all.
        client._finalize_turn_proposals(UNRELATED_SUMMARY)

        client._turn_message_for_mutation_gate = "yes"
        client._last_turn_mutating_tools_for_boundary = []

        tc2 = {"id": "c2", "function": {"name": "standing_order_create", "arguments": "{}"}}
        result2 = await client.execute_tool(tc2, user_id=user_id, conversation_id=conv_id)
        payload2 = json.loads(result2["content"])
        assert payload2["success"] is False

    @pytest.mark.asyncio
    async def test_consuming_a_proposal_cannot_bypass_the_recurring_scope_check(self, monkeypatch, user_id):
        """Security-critical negative case, caught by this test suite
        itself during development: the ORIGINAL J11 message ("I'm thinking
        about turning on the porch light...") has neither action intent
        NOR recurring scope. It gets refused-and-proposed. A later bare
        "yes" must NOT be enough to consume that proposal into a real
        standing order — "yes" itself never carries recurring language,
        and the check must be against the STORED original message (which
        also lacks it), not silently skipped just because a proposal was
        consumed. This is exactly the back door a naive
        pending-proposal implementation would reopen."""
        from app import main_simple as ms

        client = ms.SimpleLLMClient()

        async def _noop(*a, **kw):
            return None
        client.emit_event = _noop
        client.emit_activity = _noop

        client._active_tools = [{"type": "function", "function": {"name": "standing_order_create"}}]
        client._turn_message_for_mutation_gate = "I'm thinking about turning on the porch light when I get back."
        client._last_turn_mutating_tools_for_boundary = []

        conv_id = f"conv-{uuid.uuid4()}"

        async def _must_not_run(*a, **kw):
            raise AssertionError("standing_order_create must never reach the registry in this test")
        monkeypatch.setattr(ms.tool_registry, "execute_tool", _must_not_run)

        tc1 = {"id": "c1", "function": {"name": "standing_order_create", "arguments": "{}"}}
        result1 = await client.execute_tool(tc1, user_id=user_id, conversation_id=conv_id)
        assert json.loads(result1["content"])["success"] is False
        client._finalize_turn_proposals(STANDING_ORDER_SUMMARY)

        client._turn_message_for_mutation_gate = "yes"
        client._last_turn_mutating_tools_for_boundary = []

        tc2 = {"id": "c2", "function": {"name": "standing_order_create", "arguments": "{}"}}
        result2 = await client.execute_tool(tc2, user_id=user_id, conversation_id=conv_id)
        payload2 = json.loads(result2["content"])
        assert payload2["success"] is False
        assert "recurring" in payload2["message"].lower() or "one-time" in payload2["message"].lower()

    @pytest.mark.asyncio
    async def test_a_confirmation_that_itself_adds_recurring_language_succeeds(self, monkeypatch, user_id):
        """Live-model validation finding: Sara asked "just tonight, or
        make it the default from here on?" after the original non-
        recurring message was refused-and-proposed; the user answered
        "Yes, every time." — which itself carries recurring language the
        ORIGINAL proposing message never had. This must succeed: the
        recurring-scope check must look at EITHER the confirming turn's
        own message OR the original proposing message, not only the
        latter (which would otherwise keep refusing even an explicit,
        unambiguous answer to Sara's own question)."""
        from app import main_simple as ms
        from app.tools.base import ToolResult

        client = ms.SimpleLLMClient()

        async def _noop(*a, **kw):
            return None
        client.emit_event = _noop
        client.emit_activity = _noop

        client._active_tools = [{"type": "function", "function": {"name": "standing_order_create"}}]
        client._turn_message_for_mutation_gate = "I'm thinking about turning on the porch light when I get back."
        client._last_turn_mutating_tools_for_boundary = []

        conv_id = f"conv-{uuid.uuid4()}"

        async def _must_not_run(*a, **kw):
            raise AssertionError("should not reach the registry on the original hypothetical turn")
        monkeypatch.setattr(ms.tool_registry, "execute_tool", _must_not_run)

        tc1 = {"id": "c1", "function": {"name": "standing_order_create", "arguments": "{}"}}
        result1 = await client.execute_tool(tc1, user_id=user_id, conversation_id=conv_id)
        assert json.loads(result1["content"])["success"] is False
        # Sara's own real reply asked the clarifying question — still
        # substantive and still concerns the standing-order domain.
        client._finalize_turn_proposals(
            "Just for tonight, or should I make it the default and set up a standing order from here on?"
        )

        # The confirming message itself now carries "every time".
        client._turn_message_for_mutation_gate = "Yes, every time."
        client._last_turn_mutating_tools_for_boundary = []

        async def _fake_execute(name, user_id, parameters, context=None):
            return ToolResult(success=True, message="ok", data={"id": 1})
        monkeypatch.setattr(ms.tool_registry, "execute_tool", _fake_execute)

        tc2 = {"id": "c2", "function": {"name": "standing_order_create", "arguments": "{}"}}
        result2 = await client.execute_tool(tc2, user_id=user_id, conversation_id=conv_id)
        payload2 = json.loads(result2["content"])
        assert payload2["success"] is True

    @pytest.mark.asyncio
    async def test_an_unrelated_later_message_does_not_consume_the_proposal(self, monkeypatch, user_id):
        """A generic later message must not accidentally consume a
        dangling proposal from an earlier, unrelated refusal."""
        from app import main_simple as ms

        client = ms.SimpleLLMClient()

        async def _noop(*a, **kw):
            return None
        client.emit_event = _noop
        client.emit_activity = _noop

        client._active_tools = [{"type": "function", "function": {"name": "standing_order_create"}}]
        client._turn_message_for_mutation_gate = "I'm thinking about turning on the porch light when I get back."
        client._last_turn_mutating_tools_for_boundary = []

        conv_id = f"conv-{uuid.uuid4()}"

        async def _must_not_run(*a, **kw):
            raise AssertionError("should never reach the registry in this test")
        monkeypatch.setattr(ms.tool_registry, "execute_tool", _must_not_run)

        tc1 = {"id": "c1", "function": {"name": "standing_order_create", "arguments": "{}"}}
        await client.execute_tool(tc1, user_id=user_id, conversation_id=conv_id)
        client._finalize_turn_proposals(STANDING_ORDER_SUMMARY)

        client._turn_message_for_mutation_gate = "okay what else is going on today"
        client._last_turn_mutating_tools_for_boundary = []

        tc2 = {"id": "c2", "function": {"name": "standing_order_create", "arguments": "{}"}}
        result2 = await client.execute_tool(tc2, user_id=user_id, conversation_id=conv_id)
        payload2 = json.loads(result2["content"])
        assert payload2["success"] is False


class TestStructuralPresentationGate:
    """R01 review remediation round 4 (2026-09-27): 'a sufficiently long
    reply containing a domain noun does not prove the user saw the
    proposed operation, target, parameters, and recurring scope... A
    denial or unrelated discussion must not create confirmable
    authority.' propose() itself now refuses to persist anything that
    fails this structural check — tested here directly at the propose()
    call, and via execute_tool's real refuse-then-finalize flow."""

    def test_a_flat_denial_is_never_persisted_even_though_it_is_long_and_on_topic(self, db_session, user_id):
        denial = (
            "I won't set up a standing order for the porch light automatically "
            "without you confirming that's really what you want first."
        )
        ok = svc.propose(
            db_session, user_id=user_id, conversation_id="conv-1",
            tool_name="standing_order_create", arguments_json=STANDING_ORDER_ARGS,
            presented_summary=denial,
        )
        assert ok is False
        result = svc.consume(db_session, user_id=user_id, conversation_id="conv-1", tool_name="standing_order_create")
        assert result is None

    def test_a_reply_about_the_domain_but_not_the_actual_parameters_is_not_persisted(self, db_session, user_id):
        ok = svc.propose(
            db_session, user_id=user_id, conversation_id="conv-1",
            tool_name="standing_order_create", arguments_json=STANDING_ORDER_ARGS,
            presented_summary="I could set up a standing order for something else entirely, if you want.",
        )
        assert ok is False

    def test_a_reply_referencing_the_real_target_is_persisted(self, db_session, user_id):
        ok = svc.propose(
            db_session, user_id=user_id, conversation_id="conv-1",
            tool_name="standing_order_create", arguments_json=STANDING_ORDER_ARGS,
            presented_summary=STANDING_ORDER_SUMMARY,
        )
        assert ok is True

    @pytest.mark.asyncio
    async def test_a_denial_reply_leaves_nothing_for_a_later_yes_to_confirm(self, monkeypatch, user_id):
        """End-to-end via execute_tool: a genuine denial reply must not
        become confirmable authority for a later, unrelated 'yes'."""
        from app import main_simple as ms

        client = ms.SimpleLLMClient()

        async def _noop(*a, **kw):
            return None
        client.emit_event = _noop
        client.emit_activity = _noop

        client._active_tools = [{"type": "function", "function": {"name": "standing_order_create"}}]
        client._turn_message_for_mutation_gate = "Every night before I go to bed, I was wondering about the porch light."
        client._last_turn_mutating_tools_for_boundary = []

        conv_id = f"conv-{uuid.uuid4()}"

        async def _must_not_run(*a, **kw):
            raise AssertionError("should not reach the registry")
        monkeypatch.setattr(ms.tool_registry, "execute_tool", _must_not_run)

        tc1 = {"id": "c1", "function": {"name": "standing_order_create", "arguments": STANDING_ORDER_ARGS}}
        result1 = await client.execute_tool(tc1, user_id=user_id, conversation_id=conv_id)
        assert json.loads(result1["content"])["success"] is False

        # Sara's real reply is a flat denial, not an offer.
        client._finalize_turn_proposals(
            "I won't set up a standing order for the porch light automatically "
            "without you confirming that's really what you want first."
        )

        client._turn_message_for_mutation_gate = "yes"
        client._last_turn_mutating_tools_for_boundary = []

        tc2 = {"id": "c2", "function": {"name": "standing_order_create", "arguments": "{}"}}
        result2 = await client.execute_tool(tc2, user_id=user_id, conversation_id=conv_id)
        payload2 = json.loads(result2["content"])
        assert payload2["success"] is False
