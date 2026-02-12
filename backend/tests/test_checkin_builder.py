"""
Tests for CheckinBuilder — deterministic, template-driven check-in generation.
"""

import pytest
from app.services.checkin_builder import build_checkin, _build_title
from app.services.unified_context import UnifiedContextSnapshot


class TestGateChecks:
    def test_skip_if_recent_chat(self, make_snapshot_ctx):
        snap = make_snapshot_ctx(hours_since_last_chat=1.0)
        result = build_checkin(snap, changes=["something happened"])
        assert result is None

    def test_skip_if_sleeping(self, make_snapshot_ctx):
        snap = make_snapshot_ctx(activity_state="SLEEPING", hours_since_last_chat=5.0)
        result = build_checkin(snap, changes=["something happened"])
        assert result is None

    def test_skip_if_winding_down_past_bedtime(self, make_snapshot_ctx):
        snap = make_snapshot_ctx(
            activity_state="WINDING_DOWN", is_past_bedtime=True,
            hours_since_last_chat=5.0,
        )
        result = build_checkin(snap, changes=["something happened"])
        assert result is None

    def test_skip_if_nothing_to_say(self, make_snapshot_ctx):
        snap = make_snapshot_ctx(hours_since_last_chat=5.0, learning_reviews_due=0)
        result = build_checkin(snap, changes=[])
        assert result is None


class TestThreadBasedCheckin:
    def test_thread_based_checkin(self, make_snapshot_ctx):
        snap = make_snapshot_ctx(hours_since_last_chat=3.0)
        threads = [{
            "id": "abc12345-1234-1234-1234-123456789012",
            "topic": "dentist appointment",
            "suggested_followup": "Hey, how'd the dentist go?",
        }]
        result = build_checkin(snap, changes=[], open_threads=threads)
        assert result is not None
        assert "dentist" in result["message"]
        assert result["topic"].startswith("thread:")

    def test_thread_takes_priority_over_changes(self, make_snapshot_ctx):
        snap = make_snapshot_ctx(hours_since_last_chat=3.0)
        threads = [{
            "id": "abc12345-1234-1234-1234-123456789012",
            "topic": "project",
            "suggested_followup": "How's the project going?",
        }]
        result = build_checkin(snap, changes=["weather changed"], open_threads=threads)
        assert result is not None
        assert "project" in result["message"].lower()


class TestCalendarCheckin:
    def test_calendar_upcoming_checkin(self, make_snapshot_ctx):
        snap = make_snapshot_ctx(
            hours_since_last_chat=3.0,
            next_event_title="Team Standup",
            next_event_minutes_away=25,
        )
        result = build_checkin(snap, changes=[])
        assert result is not None
        assert "Team Standup" in result["message"]
        assert result["priority"] == "important"
        assert result["topic"] == "calendar_reminder"

    def test_calendar_very_soon(self, make_snapshot_ctx):
        snap = make_snapshot_ctx(
            hours_since_last_chat=3.0,
            next_event_title="Interview",
            next_event_minutes_away=10,
        )
        result = build_checkin(snap, changes=[])
        assert result is not None
        assert "10 minutes" in result["message"]
        assert result["priority"] == "important"

    def test_calendar_within_hour(self, make_snapshot_ctx):
        snap = make_snapshot_ctx(
            hours_since_last_chat=3.0,
            next_event_title="Lunch",
            next_event_minutes_away=55,
        )
        result = build_checkin(snap, changes=[])
        assert result is not None
        assert "Lunch" in result["message"]


class TestChangesCheckin:
    def test_few_changes_listed(self, make_snapshot_ctx):
        snap = make_snapshot_ctx(hours_since_last_chat=3.0)
        changes = ["[weather] Temperature dropped to 55F", "[home] Front door opened"]
        result = build_checkin(snap, changes=changes)
        assert result is not None
        assert "While you were away" in result["message"]

    def test_many_changes_summarized(self, make_snapshot_ctx):
        snap = make_snapshot_ctx(hours_since_last_chat=3.0)
        changes = [f"Change {i}" for i in range(10)]
        result = build_checkin(snap, changes=changes)
        assert result is not None
        assert "10 updates" in result["message"]


class TestLearningReviewCheckin:
    def test_learning_reviews_checkin(self, make_snapshot_ctx):
        snap = make_snapshot_ctx(hours_since_last_chat=3.0, learning_reviews_due=2)
        result = build_checkin(snap, changes=[])
        assert result is not None
        assert "learning review" in result["message"].lower()

    def test_many_reviews_piling_up(self, make_snapshot_ctx):
        snap = make_snapshot_ctx(hours_since_last_chat=3.0, learning_reviews_due=8)
        result = build_checkin(snap, changes=[])
        assert result is not None
        assert "piling up" in result["message"]


class TestActiveProjectCheckin:
    def test_project_mention_after_long_absence(self, make_snapshot_ctx):
        snap = make_snapshot_ctx(
            hours_since_last_chat=6.0,
            active_projects=["Sara backend refactor"],
        )
        # Need some content to trigger (changes or reviews)
        result = build_checkin(snap, changes=["Something happened"])
        assert result is not None
        assert "Sara backend refactor" in result["message"]


class TestTitleBuilding:
    def test_upcoming_event_title(self, make_snapshot_ctx):
        snap = make_snapshot_ctx(hours_since_last_chat=3.0)
        title = _build_title(snap, has_upcoming=True, priority="important")
        assert title == "Upcoming event"

    def test_focused_work_title(self, make_snapshot_ctx):
        snap = make_snapshot_ctx(activity_state="FOCUSED_WORK", hours_since_last_chat=3.0)
        title = _build_title(snap, has_upcoming=False, priority="normal")
        assert title == "Quick update"

    def test_long_absence_title(self, make_snapshot_ctx):
        snap = make_snapshot_ctx(hours_since_last_chat=8.0)
        title = _build_title(snap, has_upcoming=False, priority="normal")
        assert title == "Checking in"

    def test_default_title(self, make_snapshot_ctx):
        snap = make_snapshot_ctx(hours_since_last_chat=3.0)
        title = _build_title(snap, has_upcoming=False, priority="normal")
        assert title == "Hey David"


class TestReturnFormat:
    def test_returns_dict_format(self, make_snapshot_ctx):
        snap = make_snapshot_ctx(hours_since_last_chat=3.0, learning_reviews_due=2)
        result = build_checkin(snap, changes=[])
        assert result is not None
        assert "title" in result
        assert "message" in result
        assert "priority" in result
        assert "topic" in result

    def test_priority_is_valid(self, make_snapshot_ctx):
        snap = make_snapshot_ctx(
            hours_since_last_chat=3.0,
            next_event_title="Meeting",
            next_event_minutes_away=10,
        )
        result = build_checkin(snap, changes=[])
        assert result["priority"] in ("normal", "important")
