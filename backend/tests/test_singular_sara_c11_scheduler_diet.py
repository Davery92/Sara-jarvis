"""
Tests for the SINGULAR_SARA_MASTER_PLAN §C11 scheduler-diet classifier and
its backfill into `scheduled_job.singular_class`.
"""

from types import SimpleNamespace

from app.services import scheduler_diet as diet


class TestClassifyJob:
    def test_legacy_cognition_hints(self):
        assert diet.classify_job({"key": "periodic_deliberation"}) == "legacy_cognition"
        assert diet.classify_job({"display_name": "Nightly Dream Cycle"}) == "legacy_cognition"
        assert diet.classify_job({"task_name": "app.tasks.reflection.run_reflection_cycle"}) == "legacy_cognition"

    def test_anchor_hints(self):
        assert diet.classify_job({"display_name": "Morning Brief"}) == "anchor"

    def test_maintenance_hints(self):
        assert diet.classify_job({"task_name": "app.tasks.health.system_heartbeat"}) == "maintenance"

    def test_sensor_hints(self):
        assert diet.classify_job({"display_name": "Pattern Discovery Poll"}) == "sensor"

    def test_unclassified_fallback(self):
        assert diet.classify_job({"display_name": "Something Unrelated"}) == "unclassified"

    def test_legacy_cognition_takes_priority_over_anchor(self):
        # A job that mentions both "morning" and "deliberate" should read as
        # legacy cognition — the more specific, higher-priority bucket.
        assert diet.classify_job({"display_name": "Morning deliberation pass"}) == "legacy_cognition"


class _FakeDb:
    def __init__(self, rows):
        self._rows = rows
        self.updates = []
        self.committed = False

    def execute(self, stmt, params=None):
        sql = str(stmt).strip().upper()
        if sql.startswith("SELECT"):
            return SimpleNamespace(mappings=lambda: SimpleNamespace(fetchall=lambda: self._rows))
        if sql.startswith("UPDATE"):
            self.updates.append(params)
            return SimpleNamespace()
        return SimpleNamespace()

    def commit(self):
        self.committed = True


class TestBackfillSingularClass:
    def test_classifies_and_updates_every_row(self):
        rows = [
            {"key": "morning_brief", "display_name": "Morning Brief", "description": None,
             "category": "brief", "task_name": "app.tasks.brief.morning"},
            {"key": "deliberation_fallback", "display_name": "Deliberation Fallback", "description": None,
             "category": "cognition", "task_name": "app.tasks.autonomy.periodic_deliberation_fallback"},
        ]
        db = _FakeDb(rows)

        result = diet.backfill_singular_class(db)

        assert result["total"] == 2
        assert result["by_singular_class"] == {"anchor": 1, "legacy_cognition": 1}
        assert db.committed is True
        assert len(db.updates) == 2
        assert {u["key"] for u in db.updates} == {"morning_brief", "deliberation_fallback"}
