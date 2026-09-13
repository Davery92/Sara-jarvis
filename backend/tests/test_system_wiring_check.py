"""The weekly wiring check must inform, not nag.

The incident: on 2026-09-13 — as on Aug 2, 16, 23, 30 and Sep 6 — the Sunday
8 AM run pushed "System wiring check found issues: found issues with several
unscheduled tasks … plus eleven more" to David's phone. Every one of the
sixteen findings had been there the previous week. The visible five were the
same event-driven false positives every time, because `all_problems[:5]`
truncates alphabetically, so the only genuinely new finding (five threads
with kinds the interpreter invented) was in the hidden tail.

These tests lock in the four fixes: classification instead of a hand-written
allowlist, a delta against the previous run, a stable dedup topic, and
priority="normal" so it lands in the inbox instead of on the phone.

Everything here is mocked — no live DB, no broker, no worker.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.tasks import system_wiring_check as w


# ── helpers ────────────────────────────────────────────────────────────────

def _db_returning(rows=None, scalar=None):
    """A SessionLocal() context manager whose execute() answers with `rows`
    (for .fetchall()) and `scalar`."""
    db = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = rows or []
    result.scalar.return_value = scalar
    db.execute.return_value = result
    ctx = MagicMock()
    ctx.__enter__.return_value = db
    ctx.__exit__.return_value = False
    factory = MagicMock(return_value=ctx)
    return factory, db


class _AsyncSession:
    """`async with AsyncSessionLocal() as db` needs a real async context
    manager; MagicMock's __aenter__ isn't awaitable."""

    def __init__(self):
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def commit(self):
        self.committed = True


def _inspector(registered, active_queues):
    inspector = MagicMock()
    inspector.registered.return_value = registered
    inspector.active_queues.return_value = active_queues
    control = MagicMock()
    control.inspect.return_value = inspector
    return control


# ── 1. classification totality ─────────────────────────────────────────────

class TestClassificationTotality:
    """The allowlist rotted because nothing checked it against reality. This
    is the check that keeps TASK_CLASS honest."""

    def test_no_key_names_a_task_that_no_longer_exists(self):
        from app.celery_app import celery_app

        celery_app.loader.import_default_modules()
        stale = sorted(set(w.TASK_CLASS) - set(celery_app.tasks.keys()))
        assert stale == [], f"TASK_CLASS names tasks that are gone: {stale}"

    def test_every_class_is_one_of_the_three(self):
        assert set(w.TASK_CLASS.values()) <= {"event", "manual", "test"}

    def test_the_deleted_shims_are_not_resurrected_here(self):
        """Phase 1 deleted these outright rather than classifying them quiet."""
        assert "app.tasks.attention.escalate_unread_attention" not in w.TASK_CLASS
        assert "app.tasks.ml.retrain_all" not in w.TASK_CLASS


# ── 2/3. task coverage ─────────────────────────────────────────────────────

class TestTaskCoverage:
    def _run(self, registry, scheduled_rows, task_class=None):
        factory, _ = _db_returning(rows=[(name,) for name in scheduled_rows])
        with patch.object(w.celery_app, "tasks", registry), \
             patch.object(w, "TASK_CLASS", task_class or {}), \
             patch("app.db.base.SessionLocal", factory):
            return w._check_task_coverage()

    def test_no_row_is_reported_but_a_disabled_row_is_not(self):
        """David turns jobs off on purpose from routes/schedules.py
        (curiosity-sweep and weekly-digest are off right now). A deliberate
        off switch is not a wiring gap — which is why the query has no
        `WHERE enabled = TRUE`: a disabled row is still a row."""
        result = self._run(
            registry={"app.tasks.fake.never_scheduled": object(),
                      "app.tasks.fake.disabled_but_present": object()},
            scheduled_rows=["app.tasks.fake.disabled_but_present"],
        )
        assert result["unscheduled"] == ["app.tasks.fake.never_scheduled"]

    def test_a_classified_task_needs_no_row(self):
        result = self._run(
            registry={"app.tasks.fake.evented": object()},
            scheduled_rows=[],
            task_class={"app.tasks.fake.evented": "event"},
        )
        assert result["unscheduled"] == []

    def test_a_classification_with_no_task_behind_it_is_reported(self):
        """How Phase 1's deletions stay honest: classify a task away and then
        delete it, and the map itself becomes the finding."""
        result = self._run(
            registry={"app.tasks.fake.alive": object()},
            scheduled_rows=["app.tasks.fake.alive"],
            task_class={"app.tasks.gone.forever": "event"},
        )
        assert result["stale_classification"] == ["app.tasks.gone.forever"]

    def test_non_app_tasks_are_ignored(self):
        result = self._run(
            registry={"celery.chord": object(), "app.tasks.fake.alive": object()},
            scheduled_rows=["app.tasks.fake.alive"],
        )
        assert result["unscheduled"] == []


# ── 4/5. orphan schedules ──────────────────────────────────────────────────

class TestOrphanSchedules:
    """The inverse of coverage, and the one the module docstring always
    promised: DBScheduler marks last_status='success' at DISPATCH time, so a
    job firing into a queue nobody consumes has always shown green."""

    ROW = [MagicMock(key="critical-job", task_name="app.tasks.critical_thing.go")]

    def _run(self, control, routes=None):
        factory, _ = _db_returning(rows=self.ROW)
        with patch.object(w.celery_app, "control", control), \
             patch.dict(w.celery_app.conf.task_routes or {},
                        routes or {"app.tasks.critical_thing.*": {"queue": "critical"}},
                        clear=False), \
             patch("app.db.base.SessionLocal", factory):
            return w._check_orphan_schedules()

    def test_registered_everywhere_but_consumed_nowhere_is_an_orphan(self):
        """Registration is not enough: every worker imports every task, so
        the only question that matters is who consumes the queue."""
        control = _inspector(
            registered={"celery@main": ["app.tasks.critical_thing.go [rate_limit=60/m]"]},
            active_queues={"celery@main": [{"name": "cognitive"}]},
        )
        problems = self._run(control)
        assert len(problems) == 1
        assert "critical-job" in problems[0] and "'critical'" in problems[0]

    def test_a_worker_on_that_queue_clears_it(self):
        control = _inspector(
            registered={
                "celery@main": ["app.tasks.critical_thing.go [rate_limit=60/m]"],
                "critical@box": ["app.tasks.critical_thing.go [rate_limit=60/m]"],
            },
            active_queues={
                "celery@main": [{"name": "cognitive"}],
                "critical@box": [{"name": "critical"}],
            },
        )
        assert self._run(control) == []

    def test_consuming_the_queue_without_registering_the_task_is_still_an_orphan(self):
        control = _inspector(
            registered={"critical@box": ["app.tasks.something_else.go"]},
            active_queues={"critical@box": [{"name": "critical"}]},
        )
        assert len(self._run(control)) == 1

    def test_silence_from_inspect_is_never_an_all_clear(self):
        """A broker nobody answers looks exactly like a healthy cluster from
        here. Say so instead of inventing good news."""
        control = _inspector(registered=None, active_queues={"celery@main": [{"name": "critical"}]})
        problems = self._run(control)
        assert problems == ["Orphan-schedule check could not verify: no worker answered inspect"]

    def test_inspect_raising_is_also_not_an_all_clear(self):
        control = MagicMock()
        control.inspect.return_value.registered.side_effect = OSError("broker gone")
        problems = self._run(control)
        assert problems == ["Orphan-schedule check could not verify: no worker answered inspect"]


class TestQueueResolution:
    def test_the_first_matching_route_wins_like_celery(self):
        assert w._queue_for_task("app.tasks.dispatch.execute_dispatch") == "dispatch"
        assert w._queue_for_task("app.tasks.health.system_heartbeat") == "health"

    def test_an_unrouted_task_falls_back_to_the_default_queue(self):
        assert w._queue_for_task("app.tasks.brand_new_module.go") == (
            w.celery_app.conf.task_default_queue or "celery"
        )


# ── 6/7. delta + fingerprints ──────────────────────────────────────────────

class TestFingerprintStability:
    """A count that drifts is the same finding; a new kind is not. This is
    what makes "nothing new this week" mean something."""

    def test_an_ageing_timestamp_is_the_same_finding(self):
        assert w._fingerprint("x: last ran 49h ago") == w._fingerprint("x: last ran 73h ago")

    def test_a_drifting_count_is_the_same_finding(self):
        assert (w._fingerprint("4 open thread(s) with a deadline nothing vouches for")
                == w._fingerprint("5 open thread(s) with a deadline nothing vouches for"))

    def test_a_parenthesised_count_is_the_same_finding(self):
        assert (w._fingerprint("thread kind 'x' (2 open) has no registered closer")
                == w._fingerprint("thread kind 'x' (7 open) has no registered closer"))

    def test_code_freshness_age_is_the_same_finding(self):
        assert (w._fingerprint("code on disk is 3.5h newer than this container's boot")
                == w._fingerprint("code on disk is 91.2h newer than this container's boot"))

    def test_a_different_subject_is_a_different_finding(self):
        assert (w._fingerprint("thread kind 'x' (2 open) has no registered closer")
                != w._fingerprint("thread kind 'y' (2 open) has no registered closer"))


class _DeltaHarness:
    """Drives run_check with every check stubbed, so a test can say exactly
    which findings this week produced."""

    def __init__(self):
        self.state = None  # the app_settings row, as a JSON string or None
        self.sent = []

    def run(self, findings, notify=True):
        async def _fake_send(**kwargs):
            self.sent.append(kwargs)
            return {"sent": True}

        def _load():
            return (json.loads(self.state) or {}).get("findings", {}) if self.state else {}

        def _store(current):
            self.state = json.dumps({"run_at": "now", "findings": current})

        factory = MagicMock(side_effect=lambda: _AsyncSession())

        with patch.object(w, "_check_task_coverage",
                          return_value={"unscheduled": list(findings), "stale_classification": []}), \
             patch.object(w, "_check_orphan_schedules", return_value=[]), \
             patch.object(w, "_check_scheduled_job_health", return_value=[]), \
             patch.object(w, "_check_learning_freshness", return_value=[]), \
             patch.object(w, "_check_deployed_code_freshness", return_value=[]), \
             patch.object(w, "_check_thread_closer_coverage", return_value=[]), \
             patch.object(w, "_check_one_task_world", return_value=[]), \
             patch.object(w, "_check_self_model_docs", return_value=[]), \
             patch.object(w, "_load_last_findings", side_effect=_load), \
             patch.object(w, "_store_findings", side_effect=_store), \
             patch("app.db.session.get_async_session_factory", return_value=factory), \
             patch("app.services.unified_notification.send_notification", side_effect=_fake_send):
            return w.run_check(notify=notify)


class TestDeltaReporting:
    def test_the_full_arc(self):
        h = _DeltaHarness()

        first = h.run(["a", "b"])
        assert len(first["new"]) == 2 and first["notified"] is True
        assert len(h.sent) == 1

        second = h.run(["a", "b"])
        assert second["new"] == []
        assert len(second["persisting"]) == 2
        assert second["notified"] is False
        assert len(h.sent) == 1, "an unchanged list is not news"

        third = h.run(["a", "b", "c"])
        assert third["new"] == ["Unscheduled task: c"]
        assert len(third["persisting"]) == 2
        assert len(h.sent) == 2
        assert h.sent[-1]["message"].startswith("Unscheduled task: c")

        fourth = h.run(["b"])
        assert fourth["new"] == []
        assert len(fourth["resolved"]) == 2
        assert fourth["notified"] is False
        assert len(h.sent) == 2, "things getting better is not a push either"

    def test_notify_false_exercises_everything_but_the_send(self):
        h = _DeltaHarness()
        result = h.run(["a"], notify=False)
        assert result["new"] == ["Unscheduled task: a"]
        assert result["notified"] is False
        assert h.sent == []
        assert h.state is not None, "a dry run still seeds the state"

    def test_first_seen_is_carried_across_runs(self):
        h = _DeltaHarness()
        h.run(["a"])
        first_seen = json.loads(h.state)["findings"]
        h.run(["a"])
        assert json.loads(h.state)["findings"] == first_seen

    def test_all_clear_notifies_nothing(self):
        h = _DeltaHarness()
        result = h.run([])
        assert result["healthy"] is True
        assert result["notified"] is False
        assert h.sent == []


# ── 8. notification shape ──────────────────────────────────────────────────

class TestNotificationShape:
    def test_inbox_not_phone_and_a_stable_topic(self):
        h = _DeltaHarness()
        h.run(["a", "b"])
        call = h.sent[-1]
        # normal => attention item only, never a push (route_through_attention_queue)
        assert call["priority"] == "normal"
        # the old key was sha256(title+message) and the phrasing stage rewrote
        # the message weekly, so the cooldown never once matched
        assert call["topic"] == "system_wiring_check:weekly"
        assert call["cooldown_hours"] == 24 * 6
        assert call["category"] == "system"
        assert call["source"] == "system_wiring_check"
        assert call["title"] == "Wiring check: 2 new finding(s)"
        # The phrasing stage turned the first verification run into "I found
        # one new thing in the wiring check" — the finding's name, the only
        # part David can act on, paraphrased away.
        assert call["_skip_phrasing"] is True

    def test_the_new_findings_come_first_and_whole(self):
        h = _DeltaHarness()
        h.run(["a"])
        h.run(["a", "zzz_new"])
        message = h.sent[-1]["message"]
        assert message.startswith("Unscheduled task: zzz_new")
        assert "1 known finding(s) still open, 0 cleared." in message

    def test_severity_beats_alphabetical(self):
        """`all_problems[:5]` sorted the boring entries to the top and hid the
        real one. Orphan schedules outrank unscheduled tasks now."""
        with patch.object(w, "_check_task_coverage",
                          return_value={"unscheduled": ["aaa"], "stale_classification": []}), \
             patch.object(w, "_check_orphan_schedules", return_value=["zzz"]), \
             patch.object(w, "_check_scheduled_job_health", return_value=[]), \
             patch.object(w, "_check_learning_freshness", return_value=[]), \
             patch.object(w, "_check_deployed_code_freshness", return_value=[]), \
             patch.object(w, "_check_thread_closer_coverage", return_value=[]), \
             patch.object(w, "_check_one_task_world", return_value=[]), \
             patch.object(w, "_check_self_model_docs", return_value=[]), \
             patch.object(w, "_load_last_findings", return_value={}), \
             patch.object(w, "_store_findings"):
            result = w.run_check(notify=False)
        assert result["all_findings"][0] == "Orphan schedule: zzz"
        assert result["new"][0] == "Orphan schedule: zzz"


class TestMessageTruncation:
    def test_the_tail_is_what_gets_cut_never_a_new_finding(self):
        new = [f"Unscheduled task: task_number_{i:03d}" for i in range(40)]
        message = w._compose_message(new, {"a": 1}, {})
        assert len(message) <= 1500
        assert message.startswith(new[0])
        assert new[-1] in message

    def test_a_short_message_keeps_its_tail(self):
        message = w._compose_message(["one"], {"a": 1, "b": 2}, {"c": 3})
        assert message == "one\n2 known finding(s) still open, 1 cleared."


# ── state round-trip ───────────────────────────────────────────────────────

class TestStatePersistence:
    def test_a_corrupt_state_row_does_not_lose_the_run(self):
        factory, _ = _db_returning(scalar="{not json")
        with patch("app.db.base.SessionLocal", factory):
            assert w._load_last_findings() == {}

    def test_a_missing_state_row_reads_as_empty(self):
        factory, _ = _db_returning(scalar=None)
        with patch("app.db.base.SessionLocal", factory):
            assert w._load_last_findings() == {}

    def test_the_stored_shape_is_what_the_loader_expects(self):
        factory, db = _db_returning()
        with patch("app.db.base.SessionLocal", factory):
            w._store_findings({"fp1": {"text": "x", "first_seen": "2026-09-13T00:00:00+00:00"}})
        params = db.execute.call_args.args[1]
        assert params["k"] == w.LAST_FINDINGS_KEY
        stored = json.loads(params["v"])
        assert stored["findings"]["fp1"]["text"] == "x"
        assert "run_at" in stored
        db.commit.assert_called_once()


# ── integration: the real registry against the real DB ─────────────────────

@pytest.mark.integration
class TestAgainstTheRealSystem:
    def test_the_check_is_quiet_right_now(self):
        """The point of the whole exercise: after the 2026-09-13 cleanup a
        fresh coverage run finds nothing. Skips without a database."""
        import os

        if not os.environ.get("DATABASE_URL"):
            pytest.skip("no DATABASE_URL")
        from app.celery_app import celery_app

        celery_app.loader.import_default_modules()
        result = w._check_task_coverage()
        assert result["unscheduled"] == []
        assert result["stale_classification"] == []
