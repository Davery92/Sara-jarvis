"""
Tests for the SINGULAR_SARA_MASTER_PLAN §C3 read-only intent-graph
projection: per-source mapping correctness and aggregation resilience.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

from app.services import intent_graph_projection as proj


def _rows(*items):
    result = SimpleNamespace()
    result.fetchall = lambda: list(items)
    return result


def _db_returning(*row_lists):
    """A fake db whose .execute() returns each row_lists entry in order,
    one per call — matches how each per-source mapper issues exactly one
    query."""
    calls = list(row_lists)
    db = SimpleNamespace()
    db.execute = lambda *a, **kw: _rows(*calls.pop(0))
    return db


NOW = datetime(2026, 7, 24, 14, 0, tzinfo=timezone.utc)


class TestPerSourceMappers:
    def test_reminders(self):
        db = _db_returning([SimpleNamespace(id="r1", title="Pick up dry cleaning",
                                             reminder_time=NOW, created_at=NOW)])
        result = proj._reminders(db, "user-1")
        assert len(result) == 1
        intent = result[0]
        assert intent.intent_id == "reminder:r1"
        assert intent.kind == "reminder"
        assert intent.origin == "david"
        assert intent.status == "active"
        assert intent.next_step == "Pick up dry cleaning"
        assert intent.next_review_at == NOW

    def test_standing_order_user_origin(self):
        db = _db_returning([SimpleNamespace(id="s1", description="Turn off lights at 11pm",
                                             source="user", last_executed_at=None, created_at=NOW)])
        result = proj._standing_orders(db, "user-1")
        assert result[0].origin == "david"
        assert result[0].kind == "standing_order"

    def test_standing_order_pattern_origin_is_sara(self):
        db = _db_returning([SimpleNamespace(id="s2", description="Auto-lock at night",
                                             source="pattern", last_executed_at=NOW, created_at=NOW)])
        result = proj._standing_orders(db, "user-1")
        assert result[0].origin == "sara"

    def test_mission_state_and_origin_mapping(self):
        db = _db_returning([
            SimpleNamespace(id="m1", source="user", state="running", priority="high",
                             created_at=NOW, updated_at=NOW),
            SimpleNamespace(id="m2", source="acs_interest", state="pending", priority="normal",
                             created_at=NOW, updated_at=NOW),
        ])
        result = proj._missions(db, "user-1")
        assert result[0].status == "active"
        assert result[0].origin == "david"
        assert result[1].status == "proposed"
        assert result[1].origin == "sara"

    def test_followup_thread_origin_by_source(self):
        db = _db_returning([
            SimpleNamespace(id="t1", topic="Ask about the trip", priority=0.7, source="chat",
                             opened_at=NOW, last_mentioned_at=NOW),
            SimpleNamespace(id="t2", topic="Follow up on the recipe", priority=0.4, source="deliberation",
                             opened_at=NOW, last_mentioned_at=None),
        ])
        result = proj._followup_threads(db, "user-1")
        assert result[0].origin == "david"
        assert result[0].kind == "waiting_question"
        assert result[1].origin == "sara"
        assert result[1].priority == "0.4"

    def test_background_task_needs_clarification_is_blocked(self):
        db = _db_returning([
            SimpleNamespace(id="b1", original_query="research protein timing",
                             status="needs_clarification", created_at=NOW, updated_at=NOW),
        ])
        result = proj._background_tasks(db, "user-1")
        assert result[0].status == "blocked"
        assert result[0].kind == "investigation"

    def test_background_task_running_is_active(self):
        db = _db_returning([
            SimpleNamespace(id="b2", original_query="research protein timing",
                             status="running", created_at=NOW, updated_at=NOW),
        ])
        result = proj._background_tasks(db, "user-1")
        assert result[0].status == "active"

    def test_interests_are_always_sara_origin(self):
        db = _db_returning([
            SimpleNamespace(id="i1", topic="roman_logistics", display_name="Roman military logistics",
                             weight=0.83, created_at=NOW, last_acted_at=NOW),
        ])
        result = proj._interests(db, "user-1")
        assert result[0].origin == "sara"
        assert result[0].kind == "interest"
        assert result[0].priority == "0.83"
        assert result[0].next_step == "Roman military logistics"

    def test_interests_falls_back_to_topic_without_display_name(self):
        db = _db_returning([
            SimpleNamespace(id="i2", topic="roman_logistics", display_name=None,
                             weight=0.5, created_at=NOW, last_acted_at=None),
        ])
        result = proj._interests(db, "user-1")
        assert result[0].next_step == "roman_logistics"


class TestGetIntentGraph:
    def test_aggregates_across_all_sources(self, monkeypatch):
        monkeypatch.setattr(proj, "_reminders", lambda db, uid: [proj.IntentV1(
            intent_id="reminder:r1", kind="reminder", origin="david",
            owner_user_id=uid, status="active",
        )])
        monkeypatch.setattr(proj, "_standing_orders", lambda db, uid: [])
        monkeypatch.setattr(proj, "_missions", lambda db, uid: [proj.IntentV1(
            intent_id="mission:m1", kind="mission", origin="sara",
            owner_user_id=uid, status="active",
        )])
        monkeypatch.setattr(proj, "_followup_threads", lambda db, uid: [])
        monkeypatch.setattr(proj, "_background_tasks", lambda db, uid: [])
        monkeypatch.setattr(proj, "_interests", lambda db, uid: [])
        # Re-register the (now-patched) functions in the source list used by
        # get_intent_graph, since _SOURCES captured the original references.
        monkeypatch.setattr(proj, "_SOURCES", [
            ("reminders", proj._reminders),
            ("standing_orders", proj._standing_orders),
            ("missions", proj._missions),
            ("followup_threads", proj._followup_threads),
            ("background_tasks", proj._background_tasks),
            ("interests", proj._interests),
        ])

        result = proj.get_intent_graph(db=None, user_id="user-1")

        assert result["total"] == 2
        assert result["by_source"]["reminders"] == 1
        assert result["by_source"]["missions"] == 1
        assert result["by_source"]["standing_orders"] == 0
        assert result["source_errors"] == {}
        assert {i["intent_id"] for i in result["intents"]} == {"reminder:r1", "mission:m1"}

    def test_one_source_failing_does_not_kill_the_others(self, monkeypatch):
        def _broken(db, uid):
            raise RuntimeError("table missing")

        monkeypatch.setattr(proj, "_SOURCES", [
            ("reminders", _broken),
            ("interests", lambda db, uid: [proj.IntentV1(
                intent_id="interest:i1", kind="interest", origin="sara",
                owner_user_id=uid, status="active",
            )]),
        ])

        result = proj.get_intent_graph(db=None, user_id="user-1")

        assert result["total"] == 1
        assert result["by_source"]["reminders"] == 0
        assert "reminders" in result["source_errors"]
        assert result["by_source"]["interests"] == 1
