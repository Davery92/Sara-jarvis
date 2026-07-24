"""
Tests for the SINGULAR_SARA_MASTER_PLAN §C10 action-receipt shadow
recorder: permission-tier classification, status mapping, and resilience
(a recorder failure must never break the real standing-order action path).
"""

from types import SimpleNamespace

from app.services import action_receipt_service as svc


class _FakeDb:
    def __init__(self):
        self.executed = []

    def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params or {}))
        return SimpleNamespace(mappings=lambda: SimpleNamespace(fetchall=lambda: []))


class TestRecordStandingOrderAction:
    def test_reversible_action_type_gets_reversible_local_tier(self):
        db = _FakeDb()
        svc.record_standing_order_action(
            db, user_id="user-1", order_id=42, action_type="all_lights_off",
            success=True, correlation_id="turn_1",
        )

        _, params = db.executed[0]
        assert params["permission_tier"] == "reversible_local"
        assert params["reversible"] is True
        assert params["status"] == "completed"
        assert params["order_id"] == "42"

    def test_unclassified_action_type_defaults_to_consequential(self):
        db = _FakeDb()
        svc.record_standing_order_action(
            db, user_id="user-1", order_id=1, action_type="send_email",
            success=True, correlation_id=None,
        )

        _, params = db.executed[0]
        assert params["permission_tier"] == "consequential"
        assert params["reversible"] is False

    def test_failure_maps_to_failed_status_not_a_bare_flag(self):
        db = _FakeDb()
        svc.record_standing_order_action(
            db, user_id="user-1", order_id=1, action_type="home_control",
            success=False, correlation_id=None,
        )

        _, params = db.executed[0]
        assert params["status"] == "failed"

    def test_success_with_verification_false_is_partial_not_completed(self):
        """§C10 Definition of Done #9: a success flag isn't enough — if we
        checked the actual state and it didn't match, it's partial."""
        db = _FakeDb()
        svc.record_standing_order_action(
            db, user_id="user-1", order_id=1, action_type="home_control",
            success=True, verified=False, correlation_id=None,
        )

        _, params = db.executed[0]
        assert params["status"] == "partial"

    def test_success_with_verification_true_is_completed(self):
        db = _FakeDb()
        svc.record_standing_order_action(
            db, user_id="user-1", order_id=1, action_type="home_control",
            success=True, verified=True, correlation_id=None,
        )

        _, params = db.executed[0]
        assert params["status"] == "completed"

    def test_success_with_no_evidence_stays_completed(self):
        """verified=None means 'not checkable' (e.g. a notification action)
        — must not be downgraded just because there's no evidence either way."""
        db = _FakeDb()
        svc.record_standing_order_action(
            db, user_id="user-1", order_id=1, action_type="notification",
            success=True, verified=None, correlation_id=None,
        )

        _, params = db.executed[0]
        assert params["status"] == "completed"

    def test_db_failure_does_not_raise(self):
        class _BrokenDb:
            def execute(self, *a, **kw):
                raise RuntimeError("db exploded")

        # Must not raise.
        svc.record_standing_order_action(
            _BrokenDb(), user_id="user-1", order_id=1, action_type="home_control",
            success=True, correlation_id=None,
        )


class TestListRecentReceipts:
    def test_returns_mapped_rows(self):
        db = SimpleNamespace()
        rows = [{"action_id": "a1", "action_type": "home_control", "status": "completed"}]
        db.execute = lambda stmt, params=None: SimpleNamespace(
            mappings=lambda: SimpleNamespace(fetchall=lambda: rows)
        )

        result = svc.list_recent_receipts(db, "user-1")
        assert result == rows
