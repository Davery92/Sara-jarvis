"""
Tests for the SINGULAR_SARA_MASTER_PLAN §C3 intent-graph service: the
legal-transition enforcement and the projection -> real-table sync.
"""

from types import SimpleNamespace

import pytest

from app.services import intent_graph_service as svc


class _FakeDb:
    """Records executed statements; lets a test script canned results per
    call in order."""

    def __init__(self, results=None):
        self._results = list(results or [])
        self.executed = []
        self.committed = False

    def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params or {}))
        if self._results:
            return self._results.pop(0)
        return SimpleNamespace(fetchone=lambda: None, fetchall=lambda: [],
                               mappings=lambda: SimpleNamespace(fetchall=lambda: []))

    def commit(self):
        self.committed = True


class _Row(tuple):
    """A minimal stand-in for a SQLAlchemy Row supporting row[0] access."""


def _select_result(status_value):
    row = _Row((status_value,))
    return SimpleNamespace(fetchone=lambda: row)


class TestTransitionIntent:
    def test_legal_transition_succeeds(self):
        db = _FakeDb(results=[_select_result("active")])
        result = svc.transition_intent(db, "reminder:r1", "done")

        assert result == {"intent_id": "reminder:r1", "status": "done", "changed": True}
        assert db.committed is True

    def test_illegal_transition_raises(self):
        db = _FakeDb(results=[_select_result("done")])

        with pytest.raises(svc.IllegalTransitionError):
            svc.transition_intent(db, "mission:m1", "active")

    def test_same_status_is_a_noop(self):
        db = _FakeDb(results=[_select_result("active")])
        result = svc.transition_intent(db, "reminder:r1", "active")

        assert result["changed"] is False
        assert db.committed is False  # no UPDATE issued

    def test_missing_intent_raises_value_error(self):
        db = _FakeDb(results=[SimpleNamespace(fetchone=lambda: None)])

        with pytest.raises(ValueError):
            svc.transition_intent(db, "nonexistent:x", "done")

    def test_terminal_state_allows_nothing(self):
        db = _FakeDb(results=[_select_result("failed")])

        with pytest.raises(svc.IllegalTransitionError):
            svc.transition_intent(db, "mission:m2", "active")


class TestSyncFromProjections:
    def test_upserts_every_seen_intent(self, monkeypatch):
        fake_graph = {
            "total": 2,
            "by_source": {"reminders": 1, "missions": 1},
            "source_errors": {},
            "intents": [
                {"intent_id": "reminder:r1", "kind": "reminder", "origin": "david",
                 "owner_user_id": "user-1", "status": "active"},
                {"intent_id": "mission:m1", "kind": "mission", "origin": "sara",
                 "owner_user_id": "user-1", "status": "active"},
            ],
        }
        monkeypatch.setattr(
            "app.services.intent_graph_projection.get_intent_graph",
            lambda db, uid: fake_graph,
        )

        db = _FakeDb()
        result = svc.sync_from_projections(db, "user-1")

        assert result["seen"] == 2
        assert result["upserted"] == 2
        assert result["errors"] == []
        assert db.committed is True
        # One INSERT per intent.
        insert_calls = [e for e in db.executed if "INSERT INTO intent" in e[0]]
        assert len(insert_calls) == 2

    def test_one_bad_intent_id_does_not_abort_the_rest(self, monkeypatch):
        fake_graph = {
            "total": 2,
            "by_source": {},
            "source_errors": {},
            "intents": [
                {"intent_id": "malformed_no_colon", "kind": "reminder", "origin": "david",
                 "owner_user_id": "user-1", "status": "active"},
                {"intent_id": "mission:m1", "kind": "mission", "origin": "sara",
                 "owner_user_id": "user-1", "status": "active"},
            ],
        }
        monkeypatch.setattr(
            "app.services.intent_graph_projection.get_intent_graph",
            lambda db, uid: fake_graph,
        )

        db = _FakeDb()
        result = svc.sync_from_projections(db, "user-1")

        assert result["upserted"] == 1
        assert len(result["errors"]) == 1
        assert "malformed_no_colon" in result["errors"][0]
