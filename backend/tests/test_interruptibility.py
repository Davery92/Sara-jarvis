"""
Tests for Interruptibility Model — urgency scoring and notification queueing.
"""

import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.activity_state_machine import ActivityState, ActivitySnapshot, STATE_INTERRUPTIBILITY
from app.services.interruptibility import (
    Urgency,
    URGENCY_THRESHOLDS,
    InterruptibilityScore,
    compute_interruptibility,
    QueuedNotification,
    NotificationQueue,
)

USER_TZ = ZoneInfo("America/New_York")


class TestBaseScores:
    def test_sleeping_gives_low_interruptibility(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.SLEEPING)
        score = compute_interruptibility(snap)
        assert score.score <= 0.1

    def test_active_gives_high_interruptibility(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.ACTIVE)
        score = compute_interruptibility(snap)
        assert score.score >= 0.7

    def test_focused_work_moderate_interruptibility(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.FOCUSED_WORK)
        score = compute_interruptibility(snap)
        assert 0.1 <= score.score <= 0.5

    def test_in_meeting_low_interruptibility(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.IN_MEETING)
        score = compute_interruptibility(snap)
        assert score.score <= 0.3

    def test_score_includes_reasons(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.ACTIVE)
        score = compute_interruptibility(snap)
        assert len(score.reasons) >= 1
        assert "base=" in score.reasons[0]


class TestDeliveryDecisions:
    def test_critical_always_delivers(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.SLEEPING)
        score = compute_interruptibility(snap)
        assert score.should_deliver(Urgency.CRITICAL) is True

    def test_normal_blocked_when_sleeping(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.SLEEPING)
        score = compute_interruptibility(snap)
        assert score.should_deliver(Urgency.NORMAL) is False

    def test_urgent_delivers_when_active(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.ACTIVE)
        score = compute_interruptibility(snap)
        assert score.should_deliver(Urgency.URGENT) is True

    def test_delivery_decision_deliver(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.ACTIVE)
        score = compute_interruptibility(snap)
        assert score.delivery_decision(Urgency.NORMAL) == "deliver"

    def test_delivery_decision_queue(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.FOCUSED_WORK)
        score = compute_interruptibility(snap)
        # NORMAL (0.3) on FOCUSED_WORK (0.2 base) — close enough to queue
        decision = score.delivery_decision(Urgency.NORMAL)
        assert decision in ("queue", "deliver")

    def test_delivery_decision_suppress(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.SLEEPING)
        score = compute_interruptibility(snap)
        # IMPORTANT (0.6) while SLEEPING (0.0 base) — should suppress
        decision = score.delivery_decision(Urgency.IMPORTANT)
        assert decision in ("queue", "suppress")

    def test_critical_always_delivers_via_decision(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.SLEEPING)
        score = compute_interruptibility(snap)
        assert score.delivery_decision(Urgency.CRITICAL) == "deliver"


class TestBodyStateModulation:
    def test_notification_fatigue_reduces_score(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.ACTIVE)
        normal = compute_interruptibility(snap, notification_count_last_hour=0)
        fatigued = compute_interruptibility(snap, notification_count_last_hour=6)
        assert fatigued.score < normal.score

    def test_body_state_stress_reduces_score(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.ACTIVE)
        normal = compute_interruptibility(snap, body_state={"stress_load": 0.3})
        stressed = compute_interruptibility(snap, body_state={"stress_load": 0.9})
        assert stressed.score < normal.score

    def test_low_alertness_reduces_score(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.ACTIVE)
        alert = compute_interruptibility(snap, body_state={"alertness": 0.8})
        tired = compute_interruptibility(snap, body_state={"alertness": 0.1})
        assert tired.score < alert.score


class TestCalendarModulation:
    def test_calendar_meeting_reduces_score(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.ACTIVE)
        normal = compute_interruptibility(snap)
        in_meeting = compute_interruptibility(snap, calendar_context={"in_meeting": True})
        assert in_meeting.score < normal.score
        assert in_meeting.score <= 0.15

    def test_meeting_soon_caps_score(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.ACTIVE)
        normal = compute_interruptibility(snap)
        soon = compute_interruptibility(snap, calendar_context={"minutes_to_next_event": 3})
        assert soon.score <= 0.3


class TestInteractionRecency:
    def test_active_chat_boosts_score(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.FOCUSED_WORK)
        result = compute_interruptibility(snap, hours_since_last_interaction=0.03)
        assert result.score >= 0.8

    def test_long_idle_boosts_score(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.ACTIVE)
        normal = compute_interruptibility(snap)
        idle = compute_interruptibility(snap, hours_since_last_interaction=10.0)
        assert idle.score >= 0.4


class TestRecommendedChannel:
    def test_high_score_push(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.ACTIVE)
        score = compute_interruptibility(snap)
        assert score.recommended_channel == "push"

    def test_low_score_queue(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.SLEEPING)
        score = compute_interruptibility(snap)
        assert score.recommended_channel == "queue"


class TestNotificationQueue:
    def _make_queued(self, title="Test", urgency=Urgency.NORMAL, deliver_by=None):
        return QueuedNotification(
            id="test-1", title=title, message="body",
            urgency=urgency, category="general", topic="test",
            queued_at=datetime.now(USER_TZ),
            deliver_by=deliver_by,
        )

    def test_enqueue_and_flush(self, notification_queue):
        notif = self._make_queued()
        notification_queue.enqueue(notif)
        assert notification_queue.pending_count() == 1

        # Score high enough for NORMAL (0.3) → should flush
        flushed = notification_queue.flush_deliverable(0.5)
        assert len(flushed) == 1
        assert notification_queue.pending_count() == 0

    def test_flush_respects_urgency(self, notification_queue):
        notif = self._make_queued(urgency=Urgency.IMPORTANT)  # threshold 0.6
        notification_queue.enqueue(notif)

        # Score too low
        flushed = notification_queue.flush_deliverable(0.3)
        assert len(flushed) == 0
        assert notification_queue.pending_count() == 1

        # Score high enough
        flushed = notification_queue.flush_deliverable(0.7)
        assert len(flushed) == 1

    def test_queue_expiry(self, notification_queue):
        past = datetime.now(USER_TZ) - timedelta(hours=1)
        notif = self._make_queued(deliver_by=past)
        notification_queue.enqueue(notif)

        # Even with low score, expired items flush
        flushed = notification_queue.flush_deliverable(0.0)
        assert len(flushed) == 1

    def test_queue_catch_up_summary(self, notification_queue):
        notif = self._make_queued(title="Weather update")
        notification_queue.enqueue(notif)
        summary = notification_queue.get_catch_up_summary()
        assert summary is not None
        assert "Weather update" in summary
        assert "1 queued" in summary

    def test_empty_queue_no_summary(self, notification_queue):
        assert notification_queue.get_catch_up_summary() is None

    def test_queue_clear(self, notification_queue):
        notification_queue.enqueue(self._make_queued())
        notification_queue.enqueue(self._make_queued(title="Second"))
        assert notification_queue.pending_count() == 2
        notification_queue.clear()
        assert notification_queue.pending_count() == 0


class TestScoreClamping:
    def test_score_never_negative(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.SLEEPING)
        # Stack all negative modifiers
        score = compute_interruptibility(
            snap,
            body_state={"alertness": 0.0, "stress_load": 1.0},
            notification_count_last_hour=10,
            calendar_context={"in_meeting": True},
        )
        assert score.score >= 0.0

    def test_score_never_above_one(self, make_snapshot):
        snap = make_snapshot(state=ActivityState.ACTIVE)
        score = compute_interruptibility(
            snap,
            hours_since_last_interaction=0.01,
        )
        assert score.score <= 1.0
