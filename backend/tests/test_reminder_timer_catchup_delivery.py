"""R06 remainder (Sara repair plan 2026-09-25, extended round 4 2026-09-27
review remediation): overdue catch-up, no-duplicate-delivery, and a real
claim/outcome state machine for `notification_predispatch()`.

Confirmed root cause (round 1 of this fix): the prior selection was
`now <= due_at <= now+20s` — the instant `due_at` slipped into the past (a
missed beat, a worker restart, a slow prior run), the item became
permanently unselectable, with no record it was ever due.

Review finding 1 (round 4) on round 1's own fix: `_claim_for_dispatch` set
`notified_at`/`delivery_status='sent'` in the SAME atomic UPDATE used to
CLAIM the occurrence — i.e. it recorded SUCCESS before the push was ever
attempted. A crash or send failure between claim and actual send left the
occurrence marked 'sent' forever with nothing ever delivered. Fixed:
claiming (`_claim_for_dispatch`, sets only `delivery_status='claimed'` +
`claimed_at`) and recording the real outcome (`_record_delivery_outcome`,
called only after the actual dispatch attempt returns) are now separate
writes. A claim that's never resolved becomes reclaimable after
`CLAIM_EXPIRY` — the next run's own selection naturally reconciles it,
with no separate sweep process. Failed dispatches retry up to
`MAX_DELIVERY_ATTEMPTS` before becoming a terminal `failed_permanent`.
Also fixed: the old 20-second lookahead fired UP TO 20 SECONDS BEFORE an
occurrence's actual due instant — removed (`REMINDER_TIMER_LOOKAHEAD` is
now 0; this task runs every 5 seconds, so nothing is lost by not looking
ahead).

Runs against the real disposable Postgres throughout — the atomic-claim
and state-transition behavior are properties of the actual
UPDATE...WHERE semantics, not something a mock can stand in for.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text as sa_text

from app.db.base import SessionLocal


@pytest.fixture()
def user_id():
    uid = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.execute(sa_text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :email, 'x', NOW())
        """), {"id": uid, "email": f"{uid}@test.local"})
        db.commit()
    finally:
        db.close()
    yield uid
    db = SessionLocal()
    try:
        db.execute(sa_text("DELETE FROM reminder WHERE user_id = :id"), {"id": uid})
        db.execute(sa_text("DELETE FROM timer WHERE user_id = :id"), {"id": uid})
        db.execute(sa_text("DELETE FROM app_user WHERE id = :id"), {"id": uid})
        db.commit()
    finally:
        db.close()


def _make_reminder(db, user_id, reminder_time, title="Call the bank"):
    from app.models.reminder import Reminder
    r = Reminder(id=str(uuid.uuid4()), user_id=user_id, title=title,
                 description="", reminder_time=reminder_time, is_completed=False)
    db.add(r)
    db.commit()
    return r.id


def _make_timer(db, user_id, end_time, title="Egg timer"):
    from app.models.reminder import Timer
    t = Timer(id=str(uuid.uuid4()), user_id=user_id, title=title, duration_minutes=5,
               start_time=end_time - timedelta(minutes=5), end_time=end_time, is_active=True)
    db.add(t)
    db.commit()
    return t.id


@pytest.fixture(autouse=True)
def _fake_push(monkeypatch):
    sent = []

    async def _fake_send(user_id, title, body, notification_data=None):
        sent.append({"user_id": user_id, "title": title, "body": body, "data": notification_data})

    monkeypatch.setattr("app.routes.push_tokens.send_push_to_user", _fake_send)
    return sent


def _row(table, row_id):
    db = SessionLocal()
    try:
        return db.execute(sa_text(
            f"SELECT notified_at, delivery_status, claimed_at, delivery_attempts, last_error "
            f"FROM {table} WHERE id = :id"
        ), {"id": row_id}).mappings().first()
    finally:
        db.close()


class TestOverdueCatchUp:
    def test_a_reminder_due_moments_ago_is_dispatched_normally(self, user_id, _fake_push):
        from app.tasks import inproc_schedulers as mod
        db = SessionLocal()
        try:
            rid = _make_reminder(db, user_id, datetime.now(timezone.utc) - timedelta(seconds=5))
        finally:
            db.close()

        result = mod.notification_predispatch()
        assert result["sent"] >= 1
        assert any(s["title"].endswith("Call the bank") for s in _fake_push)

        row = _row("reminder", rid)
        assert row["notified_at"] is not None
        assert row["delivery_status"] == "sent"

    def test_a_reminder_overdue_by_30_minutes_still_catches_up(self, user_id, _fake_push):
        """The exact scenario the old code silently dropped forever: due
        time already passed by the time the task runs (a missed beat)."""
        from app.tasks import inproc_schedulers as mod
        db = SessionLocal()
        try:
            rid = _make_reminder(db, user_id, datetime.now(timezone.utc) - timedelta(minutes=30), title="Take medication")
        finally:
            db.close()

        result = mod.notification_predispatch()
        assert result["sent"] >= 1
        assert any("Take medication" in s["title"] for s in _fake_push)
        assert _row("reminder", rid)["delivery_status"] == "sent"

    def test_a_reminder_overdue_beyond_the_catchup_window_is_marked_missed_not_pushed(self, user_id, _fake_push):
        from app.tasks import inproc_schedulers as mod
        db = SessionLocal()
        try:
            rid = _make_reminder(
                db, user_id,
                datetime.now(timezone.utc) - mod.REMINDER_TIMER_CATCHUP_MAX_AGE - timedelta(minutes=1),
                title="Ancient stale reminder",
            )
        finally:
            db.close()

        result = mod.notification_predispatch()
        assert result["missed"] >= 1
        assert not any("Ancient stale reminder" in s["title"] for s in _fake_push)

        row = _row("reminder", rid)
        assert row["notified_at"] is not None
        assert row["delivery_status"] == "missed"

    def test_a_reminder_not_yet_due_is_not_selected_at_all(self, user_id, _fake_push):
        from app.tasks import inproc_schedulers as mod
        db = SessionLocal()
        try:
            rid = _make_reminder(db, user_id, datetime.now(timezone.utc) + timedelta(minutes=5), title="Future reminder")
        finally:
            db.close()

        mod.notification_predispatch()
        assert not any("Future reminder" in s["title"] for s in _fake_push)
        assert _row("reminder", rid)["notified_at"] is None

    def test_a_reminder_due_in_15_seconds_is_not_sent_early(self, user_id, _fake_push):
        """Review finding 1's second part: 'stop sending up to 20 seconds
        early.' A reminder 15 seconds in the future must NOT be pushed
        now — the old lookahead would have fired this immediately."""
        from app.tasks import inproc_schedulers as mod
        db = SessionLocal()
        try:
            rid = _make_reminder(db, user_id, datetime.now(timezone.utc) + timedelta(seconds=15), title="Almost due")
        finally:
            db.close()

        mod.notification_predispatch()
        assert not any("Almost due" in s["title"] for s in _fake_push)
        assert _row("reminder", rid)["notified_at"] is None

    def test_a_timer_overdue_by_30_minutes_still_catches_up(self, user_id, _fake_push):
        from app.tasks import inproc_schedulers as mod
        db = SessionLocal()
        try:
            tid = _make_timer(db, user_id, datetime.now(timezone.utc) - timedelta(minutes=30))
        finally:
            db.close()

        result = mod.notification_predispatch()
        assert result["sent"] >= 1
        assert _row("timer", tid)["delivery_status"] == "sent"


class TestNoDuplicateDelivery:
    def test_a_second_run_does_not_redispatch_an_already_notified_reminder(self, user_id, _fake_push):
        from app.tasks import inproc_schedulers as mod
        db = SessionLocal()
        try:
            rid = _make_reminder(db, user_id, datetime.now(timezone.utc) - timedelta(seconds=5), title="Only once")
        finally:
            db.close()

        mod.notification_predispatch()
        first_count = sum(1 for s in _fake_push if "Only once" in s["title"])
        assert first_count == 1

        mod.notification_predispatch()
        second_count = sum(1 for s in _fake_push if "Only once" in s["title"])
        assert second_count == 1  # unchanged — not dispatched again

    def test_the_atomic_claim_prevents_a_concurrent_second_claim(self, user_id, _fake_push):
        """Direct proof of the claim mechanism itself: once
        _claim_for_dispatch succeeds, an immediate second attempt on the
        same row must fail (return False) — the claim is fresh, not
        expired, so nothing is reclaimable yet."""
        from app.tasks import inproc_schedulers as mod
        db = SessionLocal()
        try:
            rid = _make_reminder(db, user_id, datetime.now(timezone.utc) - timedelta(seconds=5))
            first = mod._claim_for_dispatch(db, "reminder", rid, is_active_column=False)
            second = mod._claim_for_dispatch(db, "reminder", rid, is_active_column=False)
        finally:
            db.close()
        assert first is True
        assert second is False


class TestClaimDoesNotItselfMarkSent:
    """Review finding 1's core defect: claiming must NOT record success.
    Direct proof, independent of any crash simulation."""

    def test_claiming_leaves_the_row_in_claimed_state_not_sent(self, user_id):
        from app.tasks import inproc_schedulers as mod
        db = SessionLocal()
        try:
            rid = _make_reminder(db, user_id, datetime.now(timezone.utc) - timedelta(seconds=5))
            claimed = mod._claim_for_dispatch(db, "reminder", rid, is_active_column=False)
        finally:
            db.close()
        assert claimed is True
        row = _row("reminder", rid)
        assert row["delivery_status"] == "claimed"
        assert row["notified_at"] is None  # NOT terminal — nothing was actually sent yet


class TestCrashBeforeDispatch:
    """A worker claims an occurrence and then crashes before the actual
    push is even attempted (before _dispatch_* is called at all) — the
    row is stuck `claimed` with no outcome. Must be recovered once the
    claim expires, not lost forever."""

    def test_a_stale_claim_is_reclaimed_and_dispatched_after_expiry(self, user_id, _fake_push):
        from app.tasks import inproc_schedulers as mod
        db = SessionLocal()
        try:
            rid = _make_reminder(db, user_id, datetime.now(timezone.utc) - timedelta(seconds=5), title="Crashed before send")
            # Simulate the crash: claim, then never call _record_delivery_outcome.
            claimed = mod._claim_for_dispatch(db, "reminder", rid, is_active_column=False)
            assert claimed is True
            # Age the claim past CLAIM_EXPIRY, simulating time passing
            # with the worker dead the whole time.
            db.execute(sa_text("UPDATE reminder SET claimed_at = :old WHERE id = :id"), {
                "old": datetime.now(timezone.utc) - mod.CLAIM_EXPIRY - timedelta(seconds=5),
                "id": rid,
            })
            db.commit()
        finally:
            db.close()

        # A fresh run (simulating the worker restarting) must reclaim and
        # actually dispatch it — not treat the stale claim as resolved.
        result = mod.notification_predispatch()
        assert result["sent"] >= 1
        assert any("Crashed before send" in s["title"] for s in _fake_push)
        assert _row("reminder", rid)["delivery_status"] == "sent"

    def test_a_fresh_claim_is_not_reclaimed_before_expiry(self, user_id, _fake_push):
        """The other half of the same guarantee: a claim that is NOT yet
        expired must not be picked up by a concurrent/second run — this is
        what actually prevents a real duplicate send during a normal,
        still-in-progress dispatch."""
        from app.tasks import inproc_schedulers as mod
        db = SessionLocal()
        try:
            rid = _make_reminder(db, user_id, datetime.now(timezone.utc) - timedelta(seconds=5), title="Still in flight")
            claimed = mod._claim_for_dispatch(db, "reminder", rid, is_active_column=False)
            assert claimed is True
        finally:
            db.close()

        mod.notification_predispatch()
        assert not any("Still in flight" in s["title"] for s in _fake_push)
        assert _row("reminder", rid)["delivery_status"] == "claimed"


class TestAcknowledgmentLossAfterDispatch:
    """The send itself succeeds, but the process crashes before the
    outcome is recorded (between the push call returning and
    _record_delivery_outcome's commit) — an inherent, narrow, documented
    limitation: on reclaim, this occurrence WILL be retried and may send a
    duplicate push, since there is no way to know the first send actually
    succeeded once its own outcome write never happened. This is the
    accepted trade-off named in this fix's own docstring — the alternative
    (marking success before sending, round 1's actual bug) is worse: a
    GUARANTEED permanent loss instead of a rare possible duplicate."""

    def test_a_lost_acknowledgment_is_retried_not_lost(self, user_id, _fake_push):
        from app.tasks import inproc_schedulers as mod
        db = SessionLocal()
        try:
            rid = _make_reminder(db, user_id, datetime.now(timezone.utc) - timedelta(seconds=5), title="Ack lost")
            claimed = mod._claim_for_dispatch(db, "reminder", rid, is_active_column=False)
            assert claimed is True
            # Simulate: the push was actually sent successfully here
            # (not represented in this test's fake push log, since a real
            # crash means we'd never know) — then the process died before
            # _record_delivery_outcome ran. Age the claim to expiry.
            db.execute(sa_text("UPDATE reminder SET claimed_at = :old WHERE id = :id"), {
                "old": datetime.now(timezone.utc) - mod.CLAIM_EXPIRY - timedelta(seconds=5),
                "id": rid,
            })
            db.commit()
        finally:
            db.close()

        result = mod.notification_predispatch()
        assert result["sent"] >= 1
        assert any("Ack lost" in s["title"] for s in _fake_push)  # retried — not silently dropped
        assert _row("reminder", rid)["delivery_status"] == "sent"


class TestBoundedRetryOnFailure:
    def test_a_failed_dispatch_is_recorded_as_retryable_failed(self, user_id, monkeypatch):
        from app.tasks import inproc_schedulers as mod

        async def _boom(user_id, title, body, notification_data=None):
            raise RuntimeError("push provider unavailable")
        monkeypatch.setattr("app.routes.push_tokens.send_push_to_user", _boom)

        db = SessionLocal()
        try:
            rid = _make_reminder(db, user_id, datetime.now(timezone.utc) - timedelta(seconds=5), title="Will fail")
        finally:
            db.close()

        mod.notification_predispatch()
        row = _row("reminder", rid)
        assert row["delivery_status"] == "failed"
        assert row["delivery_attempts"] == 1
        assert row["notified_at"] is None  # non-terminal — still eligible for retry
        assert "push provider unavailable" in (row["last_error"] or "")

    def test_repeated_failures_become_permanently_failed_after_the_bound(self, user_id, monkeypatch):
        from app.tasks import inproc_schedulers as mod

        async def _boom(user_id, title, body, notification_data=None):
            raise RuntimeError("push provider unavailable")
        monkeypatch.setattr("app.routes.push_tokens.send_push_to_user", _boom)

        db = SessionLocal()
        try:
            rid = _make_reminder(db, user_id, datetime.now(timezone.utc) - timedelta(seconds=5), title="Always fails")
        finally:
            db.close()

        for _ in range(mod.MAX_DELIVERY_ATTEMPTS):
            mod.notification_predispatch()
            # Each retry needs the previous failed claim to be eligible
            # immediately (delivery_status='failed' is retry-eligible with
            # no expiry wait, per the selection/claim WHERE clauses).

        row = _row("reminder", rid)
        assert row["delivery_status"] == "failed_permanent"
        assert row["delivery_attempts"] == mod.MAX_DELIVERY_ATTEMPTS
        assert row["notified_at"] is not None  # now terminal — retries exhausted


class TestCancellationRecheckedAtClaimTime:
    def test_a_reminder_completed_between_selection_and_claim_is_not_claimed(self, user_id, _fake_push):
        """Simulates the cancellation-in-the-gap race directly at the
        claim primitive: if the row is already completed by the time the
        claim's own UPDATE runs, the claim must fail — proving the
        recheck happens at claim time, not only via the earlier SELECT."""
        from app.tasks import inproc_schedulers as mod
        db = SessionLocal()
        try:
            rid = _make_reminder(db, user_id, datetime.now(timezone.utc) - timedelta(seconds=5), title="Cancelled mid-flight")
            db.execute(sa_text("UPDATE reminder SET is_completed = TRUE WHERE id = :id"), {"id": rid})
            db.commit()
            claimed = mod._claim_for_dispatch(db, "reminder", rid, is_active_column=False)
        finally:
            db.close()
        assert claimed is False

    def test_a_timer_deactivated_between_selection_and_claim_is_not_claimed(self, user_id, _fake_push):
        from app.tasks import inproc_schedulers as mod
        db = SessionLocal()
        try:
            tid = _make_timer(db, user_id, datetime.now(timezone.utc) - timedelta(seconds=5), title="Cancelled timer")
            db.execute(sa_text("UPDATE timer SET is_active = FALSE WHERE id = :id"), {"id": tid})
            db.commit()
            claimed = mod._claim_for_dispatch(db, "timer", tid, is_active_column=True)
        finally:
            db.close()
        assert claimed is False
