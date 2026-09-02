"""Fixes driven by reading Sara's own interoception log (2026-08-28).

Her log was 81% two repeating non-events, and one real fault was retrying
without a bound. These pin the four fixes:

1. the world interpreter gives up instead of retrying an unusable response forever
2. every queue a worker subscribes to is declared, so the topology check stays quiet
3. a One Call auth rejection is a standing config fact, logged once, not per call
4. a forked celery worker drops the DB pool it inherited from the parent
"""

import time

import pytest


class TestInterpreterAttemptCap:
    def test_cap_is_small_and_positive(self):
        from app.services.world_state.interpreter import MAX_INTERPRETER_ATTEMPTS

        assert 1 < MAX_INTERPRETER_ATTEMPTS <= 5

    def test_processing_row_tracks_interpreter_attempts_separately(self):
        """The reducer owns attempt_count; sharing it would let a reducer retry
        burn the interpreter's budget (and vice versa)."""
        from app.models.world_model import WorldEventProcessing

        cols = WorldEventProcessing.__table__.columns
        assert "interpreter_attempt_count" in cols
        assert "attempt_count" in cols
        assert cols["interpreter_attempt_count"].nullable is False

    def test_drain_only_picks_up_pending_and_retry(self):
        """'failed' must not be in the drain's status filter, or the cap does
        nothing and the event keeps costing a model call every cycle."""
        import inspect
        from app.tasks import world_state as world_state_tasks

        source = inspect.getsource(world_state_tasks.drain_interpretations)
        assert '"pending", "retry"' in source or "'pending', 'retry'" in source
        assert "failed" not in source


class TestQueueTopology:
    # Mirrors CELERY_WORKER_QUEUES across the celery services in
    # docker-compose.dev.yml. 'acs' is the one that was missing: celery-acs
    # subscribes to it, nothing declared it, and the topology check said so
    # ~1,324 times a day.
    CLUSTER_SUBSCRIPTIONS = {
        "cognitive", "health", "input", "maintenance", "low_priority",
        "reflection", "dispatch", "critical", "david_priority", "acs",
    }

    def test_every_subscribed_queue_is_declared(self):
        from app.celery_app import celery_app

        declared = set(celery_app.conf.task_queues or {})
        missing = self.CLUSTER_SUBSCRIPTIONS - declared
        assert missing == set(), f"undeclared queues: {missing}"

    def test_compose_subscriptions_match_this_list(self):
        """Keeps CLUSTER_SUBSCRIPTIONS honest when compose is reachable (it is
        from the host checkout, not from inside the backend container)."""
        import re
        from pathlib import Path

        compose = Path(__file__).resolve().parents[2] / "docker-compose.dev.yml"
        if not compose.exists():
            pytest.skip("compose file not mounted in this environment")

        subscribed = set()
        for line in compose.read_text().splitlines():
            match = re.search(r"CELERY_WORKER_QUEUES=(\S+)", line)
            if match:
                subscribed.update(q.strip() for q in match.group(1).split(","))
        assert subscribed <= self.CLUSTER_SUBSCRIPTIONS

    def test_routed_queues_are_declared_too(self):
        from app.celery_app import celery_app

        declared = set(celery_app.conf.task_queues or {})
        routed = {
            (route.get("queue") if isinstance(route, dict) else route)
            for route in (celery_app.conf.task_routes or {}).values()
        }
        assert {q for q in routed if q} - declared == set()


class TestWeatherOneCallBackoff:
    @pytest.fixture(autouse=True)
    def _reset(self):
        from app.services import weather_service

        weather_service._onecall_blocked_until = 0.0
        yield
        weather_service._onecall_blocked_until = 0.0

    def test_auth_rejection_parks_the_endpoint(self):
        from app.services import weather_service

        assert weather_service._onecall_available() is True
        weather_service._block_onecall(401)
        assert weather_service._onecall_available() is False

    def test_block_expires_so_a_later_subscription_is_picked_up(self):
        from app.services import weather_service

        weather_service._block_onecall(401)
        weather_service._onecall_blocked_until = time.monotonic() - 1
        assert weather_service._onecall_available() is True

    def test_only_the_first_rejection_in_a_window_warns(self, caplog):
        from app.services import weather_service

        with caplog.at_level("WARNING", logger="app.services.weather_service"):
            for _ in range(25):
                weather_service._block_onecall(401)

        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1, "a standing config fact must not re-log per call"


class TestForkSafety:
    def test_worker_process_init_disposes_inherited_pools(self):
        """The sync engine is built in the celery PARENT at import time; a
        prefork child that keeps using those sockets is what produced months of
        'INTRANS' / 'server closed the connection unexpectedly' errors."""
        from celery.signals import worker_process_init

        import app.celery_app  # noqa: F401  (registers the handler on import)

        names = {getattr(r, "__name__", "") for r in worker_process_init._live_receivers(None)}
        assert "_dispose_inherited_db_pools" in names

    def test_disposal_does_not_close_the_parents_sockets(self):
        """dispose(close=False) is the whole point: closing would tear down
        connections the parent process is still using."""
        import inspect

        import app.celery_app as celery_app_module

        source = inspect.getsource(celery_app_module._dispose_inherited_db_pools)
        assert "dispose(close=False)" in source
        assert "reset_async_session_factory" in source


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value

    def scalar(self):
        return self._value


class _StubDB:
    """Just enough Session to drive interpret() without a database."""

    def __init__(self, row, event):
        self.row, self.event = row, event
        self.commits = 0

    def execute(self, statement, params=None):
        rendered = str(statement)
        if "app_settings" in rendered:
            return _Result("true")  # WORLD_INTERPRETER enabled
        if "world_event_processing" in rendered:
            return _Result(self.row)
        return _Result(self.event)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


def _stub_event():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    return SimpleNamespace(
        event_id="evt-1", user_id="user-1", kind="email.received",
        occurred_at=datetime(2026, 8, 28, 19, 0, tzinfo=timezone.utc),
        source_ref="email:1", aggregate_type="email", aggregate_id="agg-1",
        correlation_id=None, sensitivity="private", payload={"subject": "hi"},
    )


def _stub_row(attempts=0):
    from types import SimpleNamespace

    return SimpleNamespace(
        event_id="evt-1", interpreter_status="pending",
        interpreter_attempt_count=attempts, last_error=None,
    )


@pytest.fixture
def failing_model(monkeypatch):
    """Every interpretation attempt raises the way an unusable response does."""
    import app.core.llm as llm_module

    class _Boom:
        async def chat_completion(self, **kwargs):
            raise ValueError("could not convert string to float: 'high'")

    monkeypatch.setattr(llm_module, "get_background_llm_client", lambda *a, **k: _Boom())


class TestInterpreterGivesUp:
    def test_early_failures_retry_and_reraise(self, failing_model):
        from app.services.world_state.interpreter import run_interpretation

        row = _stub_row(attempts=0)
        db = _StubDB(row, _stub_event())

        with pytest.raises(ValueError):
            run_interpretation(db, "evt-1")

        assert row.interpreter_attempt_count == 1
        assert row.interpreter_status == "retry"

    def test_final_failure_marks_failed_and_stops_raising(self, failing_model):
        """Re-raising on the last attempt would keep re-reporting the same
        permanently-unusable event to the failure ledger forever."""
        from app.services.world_state.interpreter import (
            MAX_INTERPRETER_ATTEMPTS, run_interpretation,
        )

        row = _stub_row(attempts=MAX_INTERPRETER_ATTEMPTS - 1)
        db = _StubDB(row, _stub_event())

        result = run_interpretation(db, "evt-1")

        assert result["effect"] == "failed"
        assert row.interpreter_status == "failed"
        assert row.interpreter_attempt_count == MAX_INTERPRETER_ATTEMPTS
        assert "high" in row.last_error

    def test_a_failed_event_is_not_reprocessed(self, failing_model):
        from app.services.world_state.interpreter import run_interpretation

        row = _stub_row(attempts=3)
        row.interpreter_status = "failed"
        db = _StubDB(row, _stub_event())

        # 'failed' is terminal for the drain, but a direct dispatch must not
        # quietly restart the budget either.
        result = run_interpretation(db, "evt-1")
        assert result["effect"] in {"failed", "completed", "not_needed"}
        assert row.interpreter_attempt_count == 3


class TestTestsDoNotPolluteHerDiagnostics:
    def test_ring_buffer_handler_is_not_attached_under_pytest(self):
        """A test that logs a WARNING must not land in Sara's system_event ring
        buffer — that's how a suite run showed up in her interoception log as
        real malfunctions."""
        import logging

        from app.core.diagnostics_logging import RedisBufferingHandler

        attached = [
            h for h in logging.getLogger().handlers
            if isinstance(h, RedisBufferingHandler)
        ]
        assert attached == []

    def test_install_is_a_no_op_while_pytest_is_loaded(self):
        import logging

        from app.core.diagnostics_logging import RedisBufferingHandler, install

        install(service_name="test")
        attached = [
            h for h in logging.getLogger().handlers
            if isinstance(h, RedisBufferingHandler)
        ]
        assert attached == []


class TestOutcomeContractFlagVsCount:
    """A drain that handled 7 events and couldn't reduce 1 returned
    {'claimed': 7, 'completed': 2, 'failed': 1}. The outcome-contract checker
    read that truthy count as "the task failed", marked the scheduled job red,
    and wrote a ContractMiss to the ledger — a healthy task reporting itself
    broken, straight into Sara's interoception log."""

    def test_a_count_of_failed_subitems_is_not_a_task_failure(self):
        from app.celery_signals import _is_contract_miss

        miss, _ = _is_contract_miss({"claimed": 7, "completed": 6, "failures": 1})
        assert miss is False
        miss, _ = _is_contract_miss({"claimed": 7, "completed": 6, "failed": 1})
        assert miss is False, "an int under `failed` is a count, not a flag"

    def test_real_failure_flags_still_trip_the_contract(self):
        from app.celery_signals import _is_contract_miss

        assert _is_contract_miss({"failed": True})[0] is True
        assert _is_contract_miss({"failed": "database unreachable"})[0] is True
        assert _is_contract_miss({"ok": False})[0] is True
        assert _is_contract_miss({"effect": "error"})[0] is True
        assert _is_contract_miss({"effect": "error_timeout"})[0] is True

    def test_healthy_contracts_pass(self):
        from app.celery_signals import _is_contract_miss

        assert _is_contract_miss({"effect": "completed"})[0] is False
        assert _is_contract_miss({"dispatched": 3})[0] is False
        assert _is_contract_miss({"failed": 0})[0] is False
        assert _is_contract_miss({"failed": False})[0] is False

    def test_the_world_drain_no_longer_names_a_count_failed(self):
        import inspect

        from app.services.world_state import coordinator

        source = inspect.getsource(coordinator.drain_pending)
        assert '"failures":' in source
        assert '"failed": sum' not in source


class TestTestsDoNotWriteWorldEvents:
    def test_world_events_are_disabled_under_pytest(self):
        from app.services.world_state.writer import _enabled

        assert _enabled() is False
