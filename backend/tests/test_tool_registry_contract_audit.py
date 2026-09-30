"""Registry-wide contract audit — reliable-assistant plan Phase F.

*"Audit registered tools for schema/signature/return-contract mismatches and
actual read/write metadata. Tool discovery must allow access to needed
capabilities without exposing every tool on every turn."*

Finding 4 is why this exists: `start_workout` was **completely
non-functional** — every invocation crashed with `'dict' object has no
attribute 'success'` because the tool returned a plain dict — and it went
undiagnosed across multiple studies, because nothing anywhere checked the
contract. A second bug in the same tool (`got multiple values for argument
'template_id'`) is a signature mismatch of the same family.

These run over EVERY registered tool, so a tool added later is audited
automatically rather than needing someone to remember.
"""
import inspect

import pytest

from app.tools.base import BaseTool, ToolResult
from app.tools.registry import tool_registry


def all_tools():
    return sorted(tool_registry.tools.items()) if hasattr(tool_registry, "tools") else []


@pytest.fixture(scope="module")
def tools():
    registered = getattr(tool_registry, "tools", None)
    if not registered:
        pytest.skip("registry exposes no tools mapping")
    return dict(registered)


class TestRegistryShape:
    def test_the_registry_has_the_tools_it_claims(self, tools):
        assert len(tools) > 100, f"only {len(tools)} tools registered"

    def test_every_key_matches_its_tools_own_name(self, tools):
        mismatched = [(k, t.name) for k, t in tools.items() if k != t.name]
        assert not mismatched, f"registry key != tool.name: {mismatched}"

    def test_every_tool_is_a_basetool(self, tools):
        wrong = [k for k, t in tools.items() if not isinstance(t, BaseTool)]
        assert not wrong, wrong


class TestSchemas:
    def test_every_parameters_block_is_a_valid_object_schema(self, tools):
        bad = []
        for name, tool in tools.items():
            try:
                params = tool.parameters
            except Exception as exc:
                bad.append((name, f"parameters raised {type(exc).__name__}: {exc}"))
                continue
            if not isinstance(params, dict):
                bad.append((name, f"parameters is {type(params).__name__}"))
                continue
            if params.get("type") != "object":
                bad.append((name, f"type is {params.get('type')!r}, not 'object'"))
            if not isinstance(params.get("properties", {}), dict):
                bad.append((name, "properties is not an object"))
        assert not bad, bad

    def test_every_required_parameter_is_declared(self, tools):
        """A required name with no property is a schema the model cannot
        satisfy correctly — it guesses, and the call fails on arguments."""
        bad = []
        for name, tool in tools.items():
            params = tool.parameters
            properties = set((params.get("properties") or {}).keys())
            required = params.get("required") or []
            missing = [r for r in required if r not in properties]
            if missing:
                bad.append((name, missing))
        assert not bad, bad

    def test_every_property_declares_a_type(self, tools):
        bad = []
        for name, tool in tools.items():
            for prop, spec in (tool.parameters.get("properties") or {}).items():
                if not isinstance(spec, dict):
                    bad.append((name, prop, "not an object"))
                elif not any(spec.get(k) for k in ("type", "enum", "anyOf", "oneOf", "allOf")):
                    bad.append((name, prop, "no type"))
        assert not bad, bad

    @pytest.mark.xfail(
        reason=(
            "Recorded, not fixed: 50 declared properties across 15 tools carry no "
            "description (41 of them with no enum to fall back on either), so the "
            "model has to infer them from the name. Real but low severity, and "
            "writing 50 descriptions is outside this task's scope — kept as an "
            "xfail so the count stays visible instead of being quietly dropped."
        ),
        strict=True,
    )
    def test_every_property_has_a_description(self, tools):
        bad = []
        for name, tool in tools.items():
            for prop, spec in (tool.parameters.get("properties") or {}).items():
                if isinstance(spec, dict) and not str(spec.get("description") or "").strip():
                    bad.append((name, prop))
        assert not bad, f"{len(bad)} undescribed properties: {bad[:10]}"

    def test_every_description_says_something(self, tools):
        bad = [n for n, t in tools.items() if len(str(t.description or "").strip()) < 20]
        assert not bad, bad


class TestSignatures:
    def test_every_execute_is_an_async_function(self, tools):
        bad = [n for n, t in tools.items()
               if not inspect.iscoroutinefunction(t.execute)]
        assert not bad, bad

    def test_every_execute_can_receive_its_declared_parameters(self, tools):
        """Finding 4's second bug — "got multiple values for argument
        'template_id'" — is a declared parameter the signature cannot accept.
        A tool taking **kwargs is fine; one with fixed keyword arguments must
        name every property it declares."""
        bad = []
        for name, tool in tools.items():
            sig = inspect.signature(tool.execute)
            has_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD
                             for p in sig.parameters.values())
            if has_var_kw:
                continue
            accepted = {
                p.name for p in sig.parameters.values()
                if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                              inspect.Parameter.KEYWORD_ONLY)
            }
            declared = set((tool.parameters.get("properties") or {}).keys())
            unreachable = declared - accepted
            if unreachable:
                bad.append((name, sorted(unreachable)))
        assert not bad, bad

    def test_every_execute_takes_user_id(self, tools):
        bad = []
        for name, tool in tools.items():
            sig = inspect.signature(tool.execute)
            if "user_id" not in sig.parameters:
                bad.append(name)
        assert not bad, bad


class TestOperationContractCoverage:
    """Every registered tool must be classifiable, or the execution boundary
    cannot decide about it at all."""

    def test_every_tool_gets_an_operation_kind(self, tools):
        from app.services.operation_contract import operation_kind_for
        bad = []
        for name in tools:
            try:
                operation_kind_for(name, {})
            except Exception as exc:
                bad.append((name, repr(exc)))
        assert not bad, bad

    def test_every_tool_gets_a_domain(self, tools):
        from app.services.operation_contract import domain_for_tool
        bad = [n for n in tools if not domain_for_tool(n)]
        assert not bad, bad

    def test_read_tools_are_not_classified_as_writes(self, tools):
        """A read classified as a write needs action evidence to run, which is
        exactly wrong on the turn David asks a question — the live 2026-09-27
        `query_david_knowledge` refusal."""
        from app.services.operation_contract import OperationKind, operation_kind_for

        known_reads = [
            "notes_search", "notes_list", "notes_list_folders", "reminders_list",
            "memory_search", "documents_search", "calendar_list", "list_view",
            "food_log_search", "food_log_summary", "workout_list", "workout_stats",
            "query_david_knowledge", "pattern_query", "diagnostics_explain",
            "verify_action", "email_search", "email_read", "email_recent",
            "inbox_search", "inbox_read", "home_status", "home_get_devices",
            "timers_status", "daily_task_list", "recipes_list", "recipes_get",
            "standing_order_list", "research_plan_status", "get_background_tasks",
            "find_tools", "get_tool_result_details", "fitness_summary",
            "training_schedule", "get_self_knowledge", "weather",
        ]
        misclassified = [
            n for n in known_reads
            if n in tools and operation_kind_for(n, {}) is not OperationKind.READ
        ]
        assert not misclassified, misclassified

    def test_write_tools_are_not_classified_as_reads(self, tools):
        from app.services.operation_contract import OperationKind, operation_kind_for

        known_writes = [
            "notes_create", "notes_edit", "notes_delete", "notes_correct_fact",
            "reminders_create", "reminders_cancel", "reminders_reschedule",
            "reminders_update", "timers_start", "timers_cancel",
            "calendar_create", "list_add", "list_remove", "list_check",
            "list_correct_item", "food_log_create", "food_log_correct",
            "workout_log_create", "standing_order_create", "home_light_control",
            "home_lock_control", "daily_task_create", "daily_task_complete",
            "resolve_thread", "cancel_research_plan", "remember_about_david",
        ]
        misclassified = [
            n for n in known_writes
            if n in tools and operation_kind_for(n, {}) is OperationKind.READ
        ]
        assert not misclassified, misclassified


class TestTheOperationsTheJourneysNeed:
    """Plan C4: coherent domain operations must actually be registered, or the
    model is back to improvising delete/create pairs."""

    @pytest.mark.parametrize("name", [
        "notes_correct_fact",     # correct a fact in a note
        "reminders_reschedule",   # move a reminder without cancel+create
        "reminders_update",       # change what it says
        "list_correct_item",      # change one list item in place
        "food_log_correct",       # fix a logged quantity
    ])
    def test_the_operation_is_registered(self, tools, name):
        assert name in tools, f"{name} is not registered"

    @pytest.mark.parametrize("name,group", [
        ("notes_correct_fact", "notes"),
        ("reminders_reschedule", "time"),
        ("reminders_update", "time"),
        ("list_correct_item", "lists"),
        ("food_log_correct", "fitness"),
    ])
    def test_the_operation_is_offerable_through_its_group(self, name, group):
        """Registered but never offered is the finding-27 shape: "an explicit,
        fully-authorized standing-order request never reached the real tool"
        because of what was in hand that turn."""
        groups = getattr(tool_registry, "TOOL_CATEGORIES", None) or \
            getattr(tool_registry, "CATEGORIES", None)
        if not groups:
            pytest.skip("registry exposes no category mapping")
        assert group in groups, f"group {group} missing"
        assert name in groups[group]["tools"], f"{name} not in the {group} group"


class TestReturnContractIsEnforced:
    @pytest.mark.asyncio
    async def test_a_tool_returning_a_plain_dict_is_adapted_not_crashed(self, monkeypatch):
        """Finding 4 verbatim: a dict return used to raise "'dict' object has
        no attribute 'success'" and surface as an opaque failure."""
        class BadTool(BaseTool):
            name = "audit_dict_tool"
            description = "x" * 25
            parameters = {"type": "object", "properties": {}}

            async def execute(self, user_id, **kwargs):
                return {"success": True, "message": "did the thing", "data": {"a": 1}}

        tool_registry.tools["audit_dict_tool"] = BadTool()
        try:
            result = await tool_registry.execute_tool(
                "audit_dict_tool", "u1", {}, context={"origin": "chat"})
            assert isinstance(result, ToolResult)
            assert result.success is True
            assert result.message == "did the thing"
        finally:
            tool_registry.tools.pop("audit_dict_tool", None)

    @pytest.mark.asyncio
    async def test_a_tool_returning_nonsense_fails_honestly(self):
        class NonsenseTool(BaseTool):
            name = "audit_nonsense_tool"
            description = "x" * 25
            parameters = {"type": "object", "properties": {}}

            async def execute(self, user_id, **kwargs):
                return "just a string"

        tool_registry.tools["audit_nonsense_tool"] = NonsenseTool()
        try:
            result = await tool_registry.execute_tool(
                "audit_nonsense_tool", "u1", {}, context={"origin": "chat"})
            assert result.success is False
            assert "do not describe it as done" in result.message.lower()
        finally:
            tool_registry.tools.pop("audit_nonsense_tool", None)

    @pytest.mark.asyncio
    async def test_a_signature_mismatch_is_reported_as_not_run(self):
        class RigidTool(BaseTool):
            name = "audit_rigid_tool"
            description = "x" * 25
            parameters = {"type": "object", "properties": {}}

            async def execute(self, user_id, only_this=None):
                return ToolResult(success=True, message="ok")

        tool_registry.tools["audit_rigid_tool"] = RigidTool()
        try:
            result = await tool_registry.execute_tool(
                "audit_rigid_tool", "u1", {"unexpected": 1}, context={"origin": "chat"})
            assert result.success is False
            assert "did not run" in result.message
        finally:
            tool_registry.tools.pop("audit_rigid_tool", None)
