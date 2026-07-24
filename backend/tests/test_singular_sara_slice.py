"""
Tests for the SINGULAR_SARA_MASTER_PLAN §13 first implementation slice:
versioned contract schemas + fixtures, correlation IDs, the canonical
body-state projection, and the intent/action reconciliation truth audit.

Nothing under test changes cognition or delivery behavior — these are
diagnostics/contracts, verified in isolation with mocked Redis/DB.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import fakeredis.aioredis
import pytest


FIXTURES_PATH = (
    Path(__file__).parent.parent / "app" / "schemas" / "fixtures" / "contracts_v1_examples.json"
)


# ==========================================
# Contract schemas + fixtures
# ==========================================

class TestContractSchemas:
    def test_fixtures_file_round_trips_against_every_schema(self):
        from app.schemas import contracts as c

        fixtures = json.loads(FIXTURES_PATH.read_text())

        model_map = {
            "event_envelope": c.EventEnvelopeV1,
            "body_state": c.BodyStateV1,
            "world_state": c.WorldStateV1,
            "relationship_state": c.RelationshipStateV1,
            "self_state": c.SelfStateV1,
            "kernel_state": c.KernelStateV1,
            "intent": c.IntentV1,
            "intent_edge": c.IntentEdgeV1,
            "mission": c.MissionV1,
            "action_receipt": c.ActionReceiptV1,
            "artifact": c.ArtifactV1,
            "outbound_intent": c.OutboundIntentV1,
            "attention_item": c.AttentionItemV1,
        }

        # Every fixture key (except metadata) must have a schema, and vice
        # versa, so neither can silently drift out of sync.
        fixture_keys = {k for k in fixtures if not k.startswith("_") and k != "schema_version"}
        assert fixture_keys == set(model_map.keys())

        for key, model_cls in model_map.items():
            instance = model_cls.model_validate(fixtures[key])
            assert instance.schema_version == c.CONTRACTS_VERSION
            # Round-trip: dump back to JSON-compatible dict and re-validate.
            model_cls.model_validate(instance.model_dump(mode="json"))

    def test_schema_version_defaults_without_explicit_value(self):
        from app.schemas.contracts import ArtifactV1, CONTRACTS_VERSION

        artifact = ArtifactV1(
            artifact_id="a1", kind="note", title="t", location_ref="note:1",
        )
        assert artifact.schema_version == CONTRACTS_VERSION

    def test_action_receipt_status_is_not_a_bare_boolean(self):
        """§4.7: 'completed requires verified success criteria. Otherwise use
        partial, blocked, failed, or cancelled' — the schema must model a
        status enum-like string field, not a single success flag that could
        hide a partial outcome."""
        from app.schemas.contracts import ActionReceiptV1

        receipt = ActionReceiptV1(
            action_id="act1", action_type="send_email_draft",
            permission_tier="consequential", status="partial",
        )
        assert receipt.status == "partial"
        assert not hasattr(receipt, "success")


# ==========================================
# Correlation IDs
# ==========================================

class TestCorrelationIds:
    def test_new_id_is_unique_and_prefixed(self):
        from app.core.correlation import new_id

        a, b = new_id("turn"), new_id("turn")
        assert a != b
        assert a.startswith("turn_")
        assert b.startswith("turn_")

    def test_new_id_without_prefix(self):
        from app.core.correlation import new_id

        assert "_" not in new_id() or new_id().count("_") == 0

    def test_as_dict_drops_none_fields(self):
        from app.core.correlation import CorrelationIds

        ids = CorrelationIds(kernel_turn_id="turn_1")
        assert ids.as_dict() == {"kernel_turn_id": "turn_1"}

    def test_bind_and_get_current_correlation(self):
        from app.core.correlation import CorrelationIds, bind_correlation, get_current_correlation

        bind_correlation(CorrelationIds(kernel_turn_id="turn_bound"))
        assert get_current_correlation().kernel_turn_id == "turn_bound"

    def test_get_current_correlation_defaults_when_unbound(self):
        from app.core.correlation import CorrelationIds, _current, get_current_correlation

        token = _current.set(None)
        try:
            current = get_current_correlation()
            assert isinstance(current, CorrelationIds)
            assert current.as_dict() == {}
        finally:
            _current.reset(token)


# ==========================================
# Kernel: correlation ID stamped into published state
# ==========================================

class TestKernelCorrelationWiring:
    @pytest.mark.asyncio
    async def test_set_state_and_get_state_round_trip_correlation_id(self, monkeypatch):
        from app.services import kernel

        fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

        async def _fake_redis():
            return fake

        monkeypatch.setattr(kernel, "_redis", _fake_redis)

        await kernel.set_state(
            "user-1", kernel.KernelState.AMBIENT, kernel.WakeReason.MANUAL,
            detail="thinking (manual)", correlation_id="turn_abc123",
        )
        state = await kernel.get_state("user-1")

        assert state["state"] == "ambient"
        assert state["wake_reason"] == "manual"
        assert state["correlation_id"] == "turn_abc123"

    @pytest.mark.asyncio
    async def test_get_state_default_includes_correlation_id_key(self, monkeypatch):
        from app.services import kernel

        async def _broken_redis():
            raise ConnectionError("no redis in test")

        monkeypatch.setattr(kernel, "_redis", _broken_redis)

        state = await kernel.get_state("user-1")
        assert state["correlation_id"] is None


# ==========================================
# Canonical body-state projection
# ==========================================

class TestBodyStateProjection:
    @pytest.mark.asyncio
    async def test_merges_heartbeat_report_and_interoception_degraded_set(self, monkeypatch):
        from app.services import body_state_projection as proj

        async def _fake_report():
            return {
                "timestamp": "2026-07-24T14:00:00+00:00",
                "checks": {
                    "database": {"status": "healthy", "message": "Database responding"},
                    "redis": {"status": "warning", "message": "slow"},
                },
            }

        async def _fake_self_status(user_id):
            return {
                "healthy": False,
                "degraded": [
                    {"subsystem": "acs_daemon", "name": "my autonomous mind",
                     "impact": "background self is offline", "severity": "error"},
                ],
            }

        monkeypatch.setattr(proj, "_load_raw_report", _fake_report)
        monkeypatch.setattr("app.services.body_sense.current_self_status", _fake_self_status)

        result = await proj.get_body_state_projection("user-1")

        by_name = {c.name: c for c in result.components}
        assert by_name["database"].status.value == "ok"
        assert by_name["redis"].status.value == "degraded"
        assert by_name["acs_daemon"].status.value == "degraded"
        assert by_name["acs_daemon"].source == "interoception"
        assert by_name["acs_daemon"].label == "my autonomous mind"
        assert result.healthy is False
        assert result.degraded_count == 2  # redis + acs_daemon

    @pytest.mark.asyncio
    async def test_no_heartbeat_ever_recorded_yields_zero_confidence(self, monkeypatch):
        from app.services import body_state_projection as proj

        async def _no_report():
            return None

        async def _fake_self_status(user_id):
            return {"healthy": True, "degraded": []}

        monkeypatch.setattr(proj, "_load_raw_report", _no_report)
        monkeypatch.setattr("app.services.body_sense.current_self_status", _fake_self_status)

        result = await proj.get_body_state_projection("user-1")

        assert result.confidence == 0.0
        assert result.healthy is True
        assert result.components == []

    @pytest.mark.asyncio
    async def test_get_component_looks_up_by_name(self, monkeypatch):
        from app.services import body_state_projection as proj

        async def _fake_report():
            return {
                "timestamp": "2026-07-24T14:00:00+00:00",
                "checks": {"embeddings": {"status": "healthy", "message": "ok"}},
            }

        async def _fake_self_status(user_id):
            return {"healthy": True, "degraded": []}

        monkeypatch.setattr(proj, "_load_raw_report", _fake_report)
        monkeypatch.setattr("app.services.body_sense.current_self_status", _fake_self_status)

        component = await proj.get_component("embeddings", "user-1")
        assert component is not None
        assert component.status.value == "ok"

        missing = await proj.get_component("nonexistent_subsystem", "user-1")
        assert missing is None


# ==========================================
# Truth audit
# ==========================================

def _rows(*items):
    result = SimpleNamespace()
    result.fetchall = lambda: list(items)
    return result


class TestTruthAudit:
    def test_detects_failed_task_with_completed_mission(self):
        from app.services.truth_audit import run_truth_audit

        db = SimpleNamespace()
        mismatch_row = SimpleNamespace(
            task_id="task-1", task_status="failed", mission_id="mission-1", mission_state="done",
        )
        calls = [
            _rows(mismatch_row),  # task_mission_mismatch
            _rows(),               # mission_step_consistency: failed-step query
            _rows(),               # mission_step_consistency: incomplete-steps query
            _rows(),               # task_error_consistency
        ]
        db.execute = lambda *a, **kw: calls.pop(0)

        report = run_truth_audit(db)

        assert report["violation_count"] == 1
        assert report["violations"][0]["rule"] == "task_mission_state_mismatch"
        assert report["violations"][0]["record_ids"] == {
            "background_task_id": "task-1", "mission_id": "mission-1",
        }
        assert report["check_errors"] == []

    def test_clean_state_has_no_violations(self):
        from app.services.truth_audit import run_truth_audit

        db = SimpleNamespace()
        calls = [_rows(), _rows(), _rows(), _rows()]
        db.execute = lambda *a, **kw: calls.pop(0)

        report = run_truth_audit(db)

        assert report["violation_count"] == 0
        assert report["violations"] == []
        assert report["checks_run"] == 3

    def test_one_check_failing_does_not_abort_the_others(self):
        from app.services.truth_audit import run_truth_audit

        db = SimpleNamespace()
        error_row = SimpleNamespace(task_id="task-2", error_message="boom")
        calls = [
            Exception("db down"),          # task_mission_mismatch raises
            _rows(),                        # mission_step_consistency: failed-step
            _rows(),                        # mission_step_consistency: incomplete-steps
            _rows(error_row),                # task_error_consistency: finds one
        ]

        def _execute(*a, **kw):
            item = calls.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        db.execute = _execute

        report = run_truth_audit(db)

        assert len(report["check_errors"]) == 1
        assert "db down" in report["check_errors"][0]
        assert report["violation_count"] == 1
        assert report["violations"][0]["rule"] == "completed_task_has_error"
